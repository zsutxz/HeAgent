"""Story 50-5 T4/T6/T6b/T9/T11：配置写入流水线（10 步，fail-closed）。

这一层的断言口径是「**文件字节 + 副作用集合**」：每一次拒绝都必须同时满足「文件一字未动」与
「没有备份、没有审计」；每一次成功都必须留下写前备份与一条不含值的审计。

``global_env_file`` 一律显式传（多数用例传 ``None``）——否则本机 ``~/.heagent/.env`` 会成为隐藏输入，
本地通过 / CI 失败的不可复现差异正是 50-4 已经踩过的坑。
"""

from __future__ import annotations

import ast
import hashlib
import json
import threading
from pathlib import Path

import pytest

from heagent import envfile
from heagent.config_write import (
    AUDIT_FILENAME,
    ConfigAuditRecord,
    ConfigChange,
    ConfigWriteCode,
    ConfigWriteRejection,
    append_audit,
    apply_config_write,
    guard_reason,
)
from heagent.workspace import WorkspacePaths

_MISSING = object()

SAMPLE = b"# project\r\nMAX_ITERATIONS=25\r\nLOG_LEVEL=INFO  # console level\r\n"


@pytest.fixture()
def paths(tmp_path: Path) -> WorkspacePaths:
    root = tmp_path / "proj"
    root.mkdir()
    return WorkspacePaths.from_root(root)


def _run(
    paths: WorkspacePaths,
    changes: list[tuple[str, str]],
    *,
    fingerprint: object = _MISSING,
    write_enabled: bool = True,
    global_env: Path | None = None,
    source: str = "test-loopback",
) -> object:
    env_file = paths.env_file
    if fingerprint is _MISSING:
        fingerprint = envfile.fingerprint(env_file.read_bytes()) if env_file.exists() else None
    return apply_config_write(
        [ConfigChange(key=key, value=value) for key, value in changes],
        env_file=env_file,
        backups_dir=paths.config_backups,
        audit_dir=paths.console_dir,
        write_enabled=write_enabled,
        expected_fingerprint=fingerprint,  # type: ignore[arg-type]
        global_env_file=global_env,
        source=source,
    )


def _seed(paths: WorkspacePaths, raw: bytes = SAMPLE) -> bytes:
    paths.env_file.write_bytes(raw)
    return raw


def _side_effects(paths: WorkspacePaths) -> list[str]:
    """写通道可能留下的副作用（备份 / 审计 / 临时文件）——拒绝路径上必须为空。

    **不含** ``.env.lock``：跨进程锁文件由 :mod:`heagent.persist` 刻意保留（删除会引入「B 等旧 inode、
    C 拿着新文件加锁成功」的经典竞态，见该模块注释），因此任何一次尝试都会留下一个 0 字节锁文件。
    """
    found: list[str] = []
    for directory in (paths.config_backups, paths.console_dir, paths.root):
        if directory.exists():
            found.extend(sorted(path.name for path in directory.iterdir()))
    return [name for name in found if name != ".env" and not name.endswith(".lock")]


def _audit_lines(paths: WorkspacePaths) -> list[dict[str, object]]:
    audit = paths.console_dir / AUDIT_FILENAME
    if not audit.exists():
        return []
    return [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestGate:
    """第 1 步：闸门（I12）。"""

    def test_write_disabled_rejects_without_touching_anything(self, paths: WorkspacePaths) -> None:
        before = _seed(paths)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_ITERATIONS", "30")], write_enabled=False)

        assert excinfo.value.code == ConfigWriteCode.WRITE_DISABLED
        assert paths.env_file.read_bytes() == before
        assert _side_effects(paths) == []

    def test_the_console_switch_itself_is_not_writable(self, paths: WorkspacePaths) -> None:
        """I12：写入面不得给自己解锁 —— 开关本身在白名单外，网页任何请求都改不到它。"""
        before = _seed(paths)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("HTTP_CONSOLE_WRITE_ENABLED", "true")])

        assert excinfo.value.code == ConfigWriteCode.FIELD_NOT_WRITABLE
        assert paths.env_file.read_bytes() == before


class TestWhitelist:
    """第 2/3 步：键白名单与「被系统环境变量提供」闸门。"""

    def test_whitelisted_key_is_written_with_backup_and_audit(self, paths: WorkspacePaths) -> None:
        before = _seed(paths)

        result = _run(paths, [("MAX_ITERATIONS", "30")])

        raw = paths.env_file.read_bytes()
        assert raw == before.replace(b"MAX_ITERATIONS=25", b"MAX_ITERATIONS=30")
        assert result.fingerprint == envfile.fingerprint(raw)  # type: ignore[attr-defined]
        assert result.keys == ("MAX_ITERATIONS",)  # type: ignore[attr-defined]
        assert result.audit_recorded is True  # type: ignore[attr-defined]
        backup = paths.config_backups / str(result.backup)  # type: ignore[attr-defined]
        assert backup.read_bytes() == before  # 备份是**写前**字节
        assert len(_audit_lines(paths)) == 1

    def test_new_key_is_appended_with_the_file_eol(self, paths: WorkspacePaths) -> None:
        before = _seed(paths)

        _run(paths, [("MEMORY_NUDGE_ENABLED", "false")])

        raw = paths.env_file.read_bytes()
        assert raw.startswith(before)
        assert raw[len(before) :] == b"MEMORY_NUDGE_ENABLED=false\r\n"

    def test_first_write_creates_the_file_without_a_backup(self, paths: WorkspacePaths) -> None:
        result = _run(paths, [("MAX_ITERATIONS", "5")], fingerprint=None)

        assert paths.env_file.read_bytes() == b"MAX_ITERATIONS=5\n"
        assert result.backup is None  # type: ignore[attr-defined]
        assert _audit_lines(paths)[0]["fingerprint_before"] is None

    def test_batch_writes_every_key_atomically(self, paths: WorkspacePaths) -> None:
        _seed(paths)

        result = _run(paths, [("MAX_ITERATIONS", "30"), ("LOG_LEVEL", "DEBUG")])

        raw = paths.env_file.read_bytes()
        assert b"MAX_ITERATIONS=30" in raw and b"LOG_LEVEL=DEBUG  # console level" in raw
        assert result.keys == ("MAX_ITERATIONS", "LOG_LEVEL")  # type: ignore[attr-defined]

    def test_one_bad_key_rejects_the_whole_batch(self, paths: WorkspacePaths) -> None:
        before = _seed(paths)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_ITERATIONS", "30"), ("KIMI_API_KEY", "sk-x")])

        assert excinfo.value.code == ConfigWriteCode.FIELD_NOT_WRITABLE
        assert paths.env_file.read_bytes() == before
        assert _side_effects(paths) == []

    @pytest.mark.parametrize(
        "key",
        [
            "KIMI_API_KEY",
            "OPENAI_API_KEYS",
            "HTTP_PORT",
            "TCP_PORT",
            "SANDBOX_BACKEND",
            "SANDBOX_MODE",
            "SANDBOX_NETWORK",
            "SANDBOX_ENFORCE",
            "SANDBOX_FIREJAIL_PATH",
            "SANDBOX_PROFILES",
            "CRON_ENABLED",
            "MCP_ENABLED",
            "MCP_CONFIG_PATH",
            "HOOKS_ENABLED",
            "DREAM_ENABLED",
            "DREAM_CRON",
            "LOG_DIR",
            "GOAL_WORKFLOW_SKILL",
            "SAFETY_BLOCKED_TOOLS",
            "APPROVAL_TOOLS",
            "ACTIVE_PROVIDER",
            "DEEPSEEK_BASE_URL",
            "HTTP_CONSOLE_PROJECTS_FILE",
            "PLAN_MODE",
            "TOTALLY_UNKNOWN_KEY",
        ],
    )
    def test_read_only_classes_are_rejected(self, paths: WorkspacePaths, key: str) -> None:
        """AC4：凭证 / 监听面 / 沙箱姿态 / 进程拉起 / 路径 / 安全闸门 / 出站 / 控制台自身 / 未知键。"""
        before = _seed(paths)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [(key, "x")])

        assert excinfo.value.code == ConfigWriteCode.FIELD_NOT_WRITABLE
        assert str(excinfo.value)  # 必须**指明原因**
        assert paths.env_file.read_bytes() == before
        assert _side_effects(paths) == []

    def test_sandbox_dir_retention_days_is_writable(
        self, paths: WorkspacePaths, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """D2：显式白名单 > 模式排除 ⇒ 保留天数可写（``conftest`` 默认把它设成系统环境变量，故先清掉）。"""
        monkeypatch.delenv("SANDBOX_DIR_RETENTION_DAYS", raising=False)
        _seed(paths)

        _run(paths, [("SANDBOX_DIR_RETENTION_DAYS", "3")])

        assert b"SANDBOX_DIR_RETENTION_DAYS=3" in paths.env_file.read_bytes()

    def test_key_provided_by_the_system_environment_is_rejected(self, paths: WorkspacePaths) -> None:
        """AC12（F1）：系统环境变量优先级高于 ``.env`` ⇒ 写进去的是「当下无效、日后生效」的坏值。"""
        before = _seed(paths)
        monkeypatch_key = "MAX_ITERATIONS"

        import os

        previous = os.environ.get(monkeypatch_key)
        os.environ[monkeypatch_key] = "99"
        try:
            with pytest.raises(ConfigWriteRejection) as excinfo:
                _run(paths, [(monkeypatch_key, "30")])
        finally:
            if previous is None:
                del os.environ[monkeypatch_key]
            else:
                os.environ[monkeypatch_key] = previous

        assert excinfo.value.code == ConfigWriteCode.FIELD_NOT_WRITABLE
        assert "process environment" in str(excinfo.value)
        assert paths.env_file.read_bytes() == before
        assert _side_effects(paths) == []


class TestValueValidation:
    """第 4/6 步：字段级守卫（D3 的强制前提）+ 候选构造（I6）。"""

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("MAX_ITERATIONS", "abc"),  # 类型不符（候选构造拦下）
            ("MAX_ITERATIONS", "0"),  # 越界（字段元数据派生下界）
            ("MAX_ITERATIONS", "1.5"),  # int 字段收到浮点（候选构造拦下）
            ("LOG_LEVEL", "BANANA"),  # 弱校验键：候选构造**是空门**，只有守卫拦得住
            ("LOG_LEVEL", "debug"),  # 枚举大小写敏感（写通道口径）
            ("LOG_FILE_LEVEL", "BANANA"),
            ("RETRY_MAX_ATTEMPTS", "1000000"),
            ("RETRY_BASE_DELAY", "1e9"),
            ("RETRY_MAX_DELAY", "1e9"),
            ("CONTEXT_STRATEGY", "banana"),
            ("ANNOUNCE_PROGRESS", "maybe"),  # bool 字段
            ("COMPRESSION_THRESHOLD", "2"),  # 上界 1
            ("MAX_ITERATIONS", " 30"),  # 首尾空白：写进去与解析出来会不一致
            ("MAX_ITERATIONS", "30 # note"),  # 行内注释：值会被截断
            ("DEFAULT_MODEL", '"gpt-4o"'),  # 引号：解析时会被去引号
        ],
    )
    def test_invalid_values_are_rejected(self, paths: WorkspacePaths, key: str, value: str) -> None:
        before = _seed(paths)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [(key, value)])

        assert excinfo.value.code == ConfigWriteCode.INVALID_VALUE
        assert key in str(excinfo.value).upper()  # 字段级原因必须点名该键
        assert paths.env_file.read_bytes() == before
        assert _side_effects(paths) == []

    def test_empty_value_is_allowed_for_optional_log_file_level(self, paths: WorkspacePaths) -> None:
        _seed(paths)

        _run(paths, [("LOG_FILE_LEVEL", "")])

        assert b"LOG_FILE_LEVEL=\r\n" in paths.env_file.read_bytes()

    def test_candidate_construction_rejects_a_value_that_only_it_can_see(self, paths: WorkspacePaths) -> None:
        """I6：写坏 = 起不来 —— 候选必须先能构造出 ``Settings``（``1.5`` 过得了范围守卫、过不了 int 解析）。"""
        _seed(paths, b"MAX_CONTEXT_TOKENS=1000\n")

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_CONTEXT_TOKENS", "1.5")])

        assert excinfo.value.code == ConfigWriteCode.INVALID_VALUE
        assert "MAX_CONTEXT_TOKENS" in str(excinfo.value)

    def test_candidate_sees_the_global_layer_too(self, paths: WorkspacePaths, tmp_path: Path) -> None:
        """候选构造的口径与运行期一致：``[全局, 项目候选]`` + 系统环境（否则会放行被全局层打断的值）。"""
        global_env = tmp_path / "global.env"
        global_env.write_bytes(b"MAX_CONTEXT_TOKENS=1000\n")
        _seed(paths, b"MAX_ITERATIONS=25\n")

        _run(paths, [("MAX_ITERATIONS", "30")], global_env=global_env)
        assert b"MAX_ITERATIONS=30" in paths.env_file.read_bytes()

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_CONTEXT_TOKENS", "nope")], global_env=global_env)
        assert excinfo.value.code == ConfigWriteCode.INVALID_VALUE


class TestRoutingPools:
    """``ROUTING_POOLS`` 是唯一需要额外语义校验的键（JSON + 池条目）。"""

    def test_valid_pools_are_written(self, paths: WorkspacePaths) -> None:
        _seed(paths)
        payload = '{"deepseek": {"tiers": {"fast": "deepseek-flash"}}}'

        _run(paths, [("ROUTING_POOLS", payload)])

        assert envfile.read_value(paths.env_file.read_text(encoding="utf-8"), "ROUTING_POOLS") == payload

    def test_invalid_json_is_rejected(self, paths: WorkspacePaths) -> None:
        before = _seed(paths)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("ROUTING_POOLS", "{not json")])

        assert excinfo.value.code == ConfigWriteCode.INVALID_VALUE
        assert "ROUTING_POOLS" in str(excinfo.value)
        assert paths.env_file.read_bytes() == before

    def test_json_array_is_rejected(self, paths: WorkspacePaths) -> None:
        _seed(paths)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("ROUTING_POOLS", '["deepseek"]')])

        assert excinfo.value.code == ConfigWriteCode.INVALID_VALUE

    def test_entry_that_would_be_ignored_is_rejected(self, paths: WorkspacePaths) -> None:
        """池写错时现有实现是「整条忽略 + WARNING」⇒ 写通道必须在这里挡住（否则面板显示成功而池没生效）。"""
        before = _seed(paths)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("ROUTING_POOLS", '{"deepseek": {"roles": {"pro": "mid"}}}')])

        assert excinfo.value.code == ConfigWriteCode.INVALID_VALUE
        assert "ignored" in str(excinfo.value)
        assert paths.env_file.read_bytes() == before


class TestConflict:
    """第 5 步：指纹冲突（I11 的显式冲突语义）。"""

    def test_stale_fingerprint_is_rejected_without_side_effects(self, paths: WorkspacePaths) -> None:
        before = _seed(paths)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_ITERATIONS", "30")], fingerprint="0" * 64)

        assert excinfo.value.code == ConfigWriteCode.CONFIG_CONFLICT
        assert paths.env_file.read_bytes() == before
        assert _side_effects(paths) == []

    def test_missing_fingerprint_does_not_overwrite_an_existing_file(self, paths: WorkspacePaths) -> None:
        before = _seed(paths)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_ITERATIONS", "30")], fingerprint=None)

        assert excinfo.value.code == ConfigWriteCode.CONFIG_CONFLICT
        assert paths.env_file.read_bytes() == before

    def test_external_edit_between_read_and_write_is_detected(self, paths: WorkspacePaths) -> None:
        _seed(paths)
        stale = envfile.fingerprint(paths.env_file.read_bytes())
        paths.env_file.write_bytes(SAMPLE + b"EXTRA=1\r\n")  # 模拟外部编辑器

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_ITERATIONS", "30")], fingerprint=stale)

        assert excinfo.value.code == ConfigWriteCode.CONFIG_CONFLICT
        assert paths.env_file.read_bytes() == SAMPLE + b"EXTRA=1\r\n"

    def test_concurrent_writers_only_one_wins(self, paths: WorkspacePaths) -> None:
        """R3：跨进程锁 + 指纹校验双保险 —— 同一起点的两个写者只有一个能落地。"""
        _seed(paths)
        fingerprint = envfile.fingerprint(paths.env_file.read_bytes())
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        lock = threading.Lock()

        def writer(value: str) -> None:
            barrier.wait(timeout=5)
            try:
                _run(paths, [("MAX_ITERATIONS", value)], fingerprint=fingerprint)
            except ConfigWriteRejection as exc:
                code = exc.code.value
            else:
                code = "ok"
            with lock:
                outcomes.append(code)

        threads = [threading.Thread(target=writer, args=(value,)) for value in ("30", "31")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert sorted(outcomes) == ["config_conflict", "ok"]
        assert paths.env_file.read_bytes() in (
            SAMPLE.replace(b"MAX_ITERATIONS=25", b"MAX_ITERATIONS=30"),
            SAMPLE.replace(b"MAX_ITERATIONS=25", b"MAX_ITERATIONS=31"),
        )
        assert len(_audit_lines(paths)) == 1  # 只有一次真的写成功


class TestAuditAndBackup:
    """第 7/10 步：备份与审计（I8/I9）。"""

    def test_audit_record_has_hashes_and_lengths_but_no_values(self, paths: WorkspacePaths) -> None:
        _seed(paths)

        _run(paths, [("MAX_ITERATIONS", "30")], source="http-loopback")

        records = _audit_lines(paths)
        assert len(records) == 1
        record = records[0]
        assert record["result"] == "applied"
        assert record["source"] == "http-loopback"
        assert record["fingerprint_before"] != record["fingerprint_after"]
        entry = record["entries"][0]  # type: ignore[index]
        assert entry["key"] == "MAX_ITERATIONS"
        assert entry["old_hash"] == hashlib.sha256(b"25").hexdigest()
        assert (entry["old_length"], entry["new_length"]) == (2, 2)
        assert entry["new_hash"] == hashlib.sha256(b"30").hexdigest()
        # 审计里**不含**值本身（I9）：值若被记录，会以带引号的完整 token 出现（长度/哈希里不会有它）。
        text = (paths.console_dir / AUDIT_FILENAME).read_text(encoding="utf-8")
        assert '"30"' not in text
        assert '"25"' not in text

    def test_audit_records_a_new_key_with_null_old_value(self, paths: WorkspacePaths) -> None:
        _seed(paths)

        _run(paths, [("MEMORY_NUDGE_ENABLED", "false")])

        entry = _audit_lines(paths)[0]["entries"][0]  # type: ignore[index]
        assert entry["old_hash"] is None and entry["old_length"] is None
        assert entry["new_length"] == len("false")

    def test_every_write_with_an_existing_file_leaves_a_backup(self, paths: WorkspacePaths) -> None:
        """「有原内容就必有备份」是硬约束（I8）：连续两次写 ⇒ 两个备份，各对应当时的字节。"""
        _seed(paths)

        for value in ("30", "31"):
            before = paths.env_file.read_bytes()
            result = _run(paths, [("MAX_ITERATIONS", value)])
            assert result.backup is not None  # type: ignore[attr-defined]
            assert (paths.config_backups / str(result.backup)).read_bytes() == before  # type: ignore[attr-defined]

    def test_audit_failure_is_reported_not_swallowed(self, paths: WorkspacePaths, tmp_path: Path) -> None:
        """T3：审计追加失败**不阻断**已成功的写，但结果里必须如实带 ``audit_recorded=False``。"""
        _seed(paths)
        blocker = tmp_path / "audit-blocker"
        blocker.write_bytes(b"not a directory")

        result = apply_config_write(
            [ConfigChange(key="MAX_ITERATIONS", value="30")],
            env_file=paths.env_file,
            backups_dir=paths.config_backups,
            audit_dir=blocker / "console",
            write_enabled=True,
            expected_fingerprint=envfile.fingerprint(paths.env_file.read_bytes()),
        )

        assert result.audit_recorded is False
        assert b"MAX_ITERATIONS=30" in paths.env_file.read_bytes()  # 写本身成功了

    def test_append_audit_reports_failure(self, tmp_path: Path) -> None:
        blocker = tmp_path / "file"
        blocker.write_bytes(b"x")
        record = ConfigAuditRecord(timestamp="2026-01-01T00:00:00Z", source="s", result="applied")

        assert append_audit(tmp_path / "ok", record) is True
        assert append_audit(blocker, record) is False

    def test_unexpected_candidate_failure_is_an_invalid_value(
        self, paths: WorkspacePaths, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """候选构造**非校验类**失败（pydantic-settings 的 SettingsError 等）同样必须 fail-closed。"""
        _seed(paths)

        def boom(candidate: bytes, global_env_file: Path | None) -> object:
            raise RuntimeError("exotic settings failure")

        monkeypatch.setattr("heagent.config_write._candidate_settings", boom)
        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_ITERATIONS", "30")])

        assert excinfo.value.code == ConfigWriteCode.INVALID_VALUE
        assert "candidate configuration is invalid" in str(excinfo.value)

    def test_backup_cap_is_enforced_by_the_pipeline(self, paths: WorkspacePaths) -> None:
        """上限参数真的接到 ``prune_backups``（否则备份目录会随写入次数无界增长）。"""
        _seed(paths)

        for index in range(3):
            apply_config_write(
                [ConfigChange(key="MAX_ITERATIONS", value=str(30 + index))],
                env_file=paths.env_file,
                backups_dir=paths.config_backups,
                audit_dir=paths.console_dir,
                write_enabled=True,
                expected_fingerprint=envfile.fingerprint(paths.env_file.read_bytes()),
                global_env_file=None,
                max_backups=2,
            )

        backups = [path for path in paths.config_backups.iterdir() if path.name.endswith(".bak")]
        assert len(backups) == 2

    def test_backup_directory_is_bounded(self, paths: WorkspacePaths, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed(paths)
        for index in range(4):
            _run(paths, [("MAX_ITERATIONS", str(30 + index))])
        backups = sorted(path.name for path in paths.config_backups.iterdir() if path.name.endswith(".bak"))
        assert len(backups) == 4

        _seed(paths, SAMPLE.replace(b"MAX_ITERATIONS=25", b"MAX_ITERATIONS=99"))
        _run(paths, [("MAX_ITERATIONS", "100")], fingerprint=envfile.fingerprint(paths.env_file.read_bytes()))

        backups = [path for path in paths.config_backups.iterdir() if path.name.endswith(".bak")]
        assert len(backups) == 5  # 默认上限 50，未触发回收


class TestFailureRecovery:
    """第 8/9 步：磁盘失败与回读不符 —— 必须还原 + 显式报错（AC8）。"""

    def test_disk_failure_leaves_the_file_untouched(
        self, paths: WorkspacePaths, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = _seed(paths)

        def boom(*args: object, **kwargs: object) -> None:
            raise OSError("disk on fire")

        monkeypatch.setattr("heagent.config_write.atomic_update_bytes", boom)
        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_ITERATIONS", "30")])

        assert excinfo.value.code == ConfigWriteCode.CONFIG_WRITE_FAILED
        assert paths.env_file.read_bytes() == before

    def test_readback_mismatch_rolls_back_and_reports(
        self, paths: WorkspacePaths, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = _seed(paths)
        monkeypatch.setattr("heagent.config_write._read_back", lambda path: before)  # 盘上不是刚写的内容

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_ITERATIONS", "30")])

        assert excinfo.value.code == ConfigWriteCode.CONFIG_WRITE_FAILED
        assert "verification failed" in str(excinfo.value)
        assert paths.env_file.read_bytes() == before  # 已还原
        assert _audit_lines(paths)[0]["result"] == "rolled_back"  # 磁盘级异常留痕

    def test_readback_failure_for_a_new_file_removes_it(
        self, paths: WorkspacePaths, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("heagent.config_write._read_back", lambda path: b"something else")

        with pytest.raises(ConfigWriteRejection):
            _run(paths, [("MAX_ITERATIONS", "30")], fingerprint=None)

        assert not paths.env_file.exists()

    def test_non_utf8_env_file_is_refused(self, paths: WorkspacePaths) -> None:
        """非 UTF-8 的项目 ``.env``：拒绝改写（解码不可逆 ⇒ 改了就丢字节），文件一个字节都不动。"""
        before = b"MAX_ITERATIONS=25\nLOG_LEVEL=" + "中文".encode("gbk") + b"\n"
        _seed(paths, before)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_ITERATIONS", "30")])

        assert excinfo.value.code == ConfigWriteCode.CONFIG_WRITE_FAILED
        assert "UTF-8" in str(excinfo.value)
        assert paths.env_file.read_bytes() == before


class TestBomFidelity:
    """AC11（评审 F6）：带 BOM 的项目 `.env`，首行键必须被**替换**而不是追加重写。"""

    def test_head_bom_first_line_is_replaced_and_bom_survives(self, paths: WorkspacePaths) -> None:
        before = _seed(paths, b"\xef\xbb\xbfMAX_ITERATIONS=25\r\nLOG_LEVEL=INFO\r\n")

        _run(paths, [("MAX_ITERATIONS", "30")])

        raw = paths.env_file.read_bytes()
        assert raw == b"\xef\xbb\xbfMAX_ITERATIONS=30\r\nLOG_LEVEL=INFO\r\n"
        assert raw.count(b"MAX_ITERATIONS") == 1
        assert raw.startswith(envfile.BOM_BYTES)
        assert raw != before


class TestDestinationGuard:
    """写入目的地只能是项目的 ``.env``（绝对路径）——不接受任意文件路径。"""

    @pytest.mark.parametrize("name", ["config.txt", ".env.example", ".env.local"])
    def test_other_file_names_are_refused(self, paths: WorkspacePaths, name: str) -> None:
        with pytest.raises(ValueError, match=r"only target a project \.env"):
            apply_config_write(
                [ConfigChange(key="MAX_ITERATIONS", value="1")],
                env_file=paths.root / name,
                backups_dir=paths.config_backups,
                audit_dir=paths.console_dir,
                write_enabled=True,
                expected_fingerprint=None,
            )

    def test_relative_path_is_refused(self, paths: WorkspacePaths) -> None:
        with pytest.raises(ValueError, match=r"only target a project \.env"):
            apply_config_write(
                [ConfigChange(key="MAX_ITERATIONS", value="1")],
                env_file=Path(".env"),
                backups_dir=paths.config_backups,
                audit_dir=paths.console_dir,
                write_enabled=True,
                expected_fingerprint=None,
            )

    def test_empty_change_list_is_an_invalid_request(self, paths: WorkspacePaths) -> None:
        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [])

        assert excinfo.value.code == ConfigWriteCode.INVALID_REQUEST

    def test_duplicate_keys_in_one_batch_are_refused(self, paths: WorkspacePaths) -> None:
        _seed(paths)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            _run(paths, [("MAX_ITERATIONS", "30"), ("MAX_ITERATIONS", "31")])

        assert excinfo.value.code == ConfigWriteCode.INVALID_REQUEST


class TestGuards:
    """T6b：弱校验键的字段级守卫（I6 对它们是空门）。"""

    def test_enum_guard(self) -> None:
        assert guard_reason("LOG_LEVEL", "DEBUG") is None
        assert guard_reason("LOG_LEVEL", "DEBUG ") is not None
        assert "must be one of" in (guard_reason("LOG_LEVEL", "BANANA") or "")
        assert guard_reason("LOG_FILE_LEVEL", "") is None  # allow_empty
        assert guard_reason("LOG_LEVEL", "") is not None
        assert guard_reason("CONTEXT_STRATEGY", "reset") is None

    def test_range_guard(self) -> None:
        assert guard_reason("RETRY_MAX_ATTEMPTS", "10") is None
        assert guard_reason("RETRY_MAX_ATTEMPTS", "11") == "must be at most 10"
        assert guard_reason("RETRY_BASE_DELAY", "-1") == "must be at least 0"
        assert guard_reason("RETRY_BASE_DELAY", "abc") == "must be a number"
        assert guard_reason("RETRY_BASE_DELAY", "nan") == "must be a finite number"
        assert guard_reason("COMPRESSION_THRESHOLD", "1.5") == "must be at most 1"

    def test_keys_without_constraints_pass(self) -> None:
        assert guard_reason("DEFAULT_MODEL", "anything") is None
        assert guard_reason("NOT_A_FIELD", "anything") is None

    def test_exclusive_bounds_are_reported_verbatim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """开区间报「greater than / less than」（合成守卫：``Settings`` 现无 ``gt`` / ``lt`` 字段）。"""
        from heagent.config_catalog import VALUE_GUARDS, ConfigGuard

        monkeypatch.setitem(
            VALUE_GUARDS, "DEFAULT_MODEL", ConfigGuard(kind="range", minimum=1.0, exclusive_minimum=True)
        )
        assert guard_reason("DEFAULT_MODEL", "1") == "must be greater than 1"
        assert guard_reason("DEFAULT_MODEL", "2") is None

        monkeypatch.setitem(
            VALUE_GUARDS, "DEFAULT_MODEL", ConfigGuard(kind="range", maximum=5.0, exclusive_maximum=True)
        )
        assert guard_reason("DEFAULT_MODEL", "5") == "must be less than 5"


class TestChangeModel:
    def test_key_is_normalised_to_uppercase(self) -> None:
        assert ConfigChange(key=" max_iterations ", value="1").key == "MAX_ITERATIONS"

    def test_value_is_never_normalised(self) -> None:
        assert ConfigChange(key="DEFAULT_MODEL", value=" gpt-4o ").value == " gpt-4o "


class TestModuleBoundary:
    def test_config_write_has_no_runtime_imports_of_the_stack(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "src" / "heagent" / "config_write.py").read_text(
            encoding="utf-8"
        )
        for forbidden in ("heagent.engine", "heagent.agent", "heagent.cli", "heagent.network"):
            assert f"from {forbidden}" not in source, forbidden
        tree = ast.parse(source)
        assert any(
            (isinstance(node, ast.ImportFrom) and node.module in {"heagent.envfile", "heagent"}) for node in tree.body
        ), "写入流水线必须经 envfile 做行级改写（不得自带第二套 .env 解析）"
        assert "envfile.replace_or_append" in source
