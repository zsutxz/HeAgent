"""Story 50-4：配置目录 + 四层来源求解的测试（AC1–AC12 / 七个坑 / BOM 边界）。

所有用例都把**全局层**指向受控路径（``global_env_file=``）：绝不能读开发机的 ``~/.heagent/.env``，
否则同一断言在不同机器上会得到不同的 ``source``。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING

from heagent.config import Settings
from heagent.config.catalog import (
    BOM,
    EXCLUSION_GROUPS,
    LABELS,
    MASK,
    MAX_FILE_DIAGNOSTIC_KEYS,
    MAX_UNKNOWN_KEYS,
    RESOURCE_CEILINGS,
    UNKNOWN_GROUP,
    VALUE_GUARDS,
    WHITELIST_GROUPS,
    ConfigReport,
    ConfigSource,
    bom_prefixed_keys,
    build_config_report,
    classify,
    guards_for,
    is_secret_key,
    scan_env_file,
    whitelist,
)

if TYPE_CHECKING:
    import pytest

ENV_KEYS = frozenset(name.upper() for name in Settings.model_fields)


def _write(path: Path, lines: list[str] | None = None, *, raw: bytes | None = None) -> Path:
    """写字面字节（``write_bytes`` 不做 EOL 翻译，测试样本必须是确定的 LF）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        path.write_bytes(raw)
    else:
        path.write_bytes(b"".join((line + "\n").encode() for line in lines or []))
    return path


def _report(project: Path, global_env: Path | None = None) -> ConfigReport:
    """求解一个受控项目：全局层默认指向**不存在**的受控路径。"""
    absent = project.parent / "global-absent.env"
    return build_config_report(project, global_env_file=global_env or absent)


def _by_key(report: ConfigReport) -> dict[str, object]:
    return {item.key: item for item in report.items}


# ── 四层来源求解（AC1 / AC2 / AC3 / AC8） ──


class TestSourceSolve:
    def test_missing_everything_falls_back_to_defaults(self, tmp_path: Path) -> None:
        """AC7：项目 .env 不存在 ⇒ 全字段 default + 明确标注文件状态，且不抛。"""
        project = tmp_path / "nope" / ".env"
        report = _report(project)
        item = _by_key(report)["MAX_ITERATIONS"]  # type: ignore[index]
        assert item.source is ConfigSource.DEFAULT  # type: ignore[union-attr]
        assert item.configured is False  # type: ignore[union-attr]
        assert item.value == 50  # type: ignore[union-attr]
        assert report.env_file == report.env_file.__class__(
            path=str(project), exists=False, readable=False, fingerprint=None
        )
        assert "project_env_missing" in report.notes
        assert report.field_count == len(Settings.model_fields)

    def test_project_env_is_the_source(self, tmp_path: Path) -> None:
        project = _write(tmp_path / ".env", ["MAX_ITERATIONS=123"])
        item = _by_key(_report(project))["MAX_ITERATIONS"]  # type: ignore[index]
        assert item.source is ConfigSource.PROJECT_ENV  # type: ignore[union-attr]
        assert item.value == 123  # type: ignore[union-attr]
        assert item.configured is True  # type: ignore[union-attr]

    def test_global_env_is_used_when_project_silent(self, tmp_path: Path) -> None:
        global_env = _write(tmp_path / "global.env", ["MAX_ITERATIONS=77"])
        project = _write(tmp_path / ".env", ["SHELL_TIMEOUT=9"])
        report = _report(project, global_env)
        items = _by_key(report)
        assert items["MAX_ITERATIONS"].source is ConfigSource.GLOBAL_ENV  # type: ignore[union-attr]
        assert items["MAX_ITERATIONS"].value == 77  # type: ignore[union-attr]
        assert items["SHELL_TIMEOUT"].source is ConfigSource.PROJECT_ENV  # type: ignore[union-attr]

    def test_project_overrides_global(self, tmp_path: Path) -> None:
        global_env = _write(tmp_path / "global.env", ["MAX_ITERATIONS=77"])
        project = _write(tmp_path / ".env", ["MAX_ITERATIONS=123"])
        item = _by_key(_report(project, global_env))["MAX_ITERATIONS"]  # type: ignore[index]
        assert (item.source, item.value) == (ConfigSource.PROJECT_ENV, 123)  # type: ignore[union-attr]

    def test_system_env_wins_and_is_read_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC2：系统环境变量提供 ⇒ source=system_env、writable=false 且原因点名。"""
        project = _write(tmp_path / ".env", ["MAX_ITERATIONS=123"])
        monkeypatch.setenv("MAX_ITERATIONS", "456")
        item = _by_key(_report(project))["MAX_ITERATIONS"]  # type: ignore[index]
        assert (item.source, item.value) == (ConfigSource.SYSTEM_ENV, 456)  # type: ignore[union-attr]
        assert item.writable is False  # type: ignore[union-attr]
        assert item.read_only_reason == "system_env"  # type: ignore[union-attr]

    def test_removing_the_line_falls_back(self, tmp_path: Path) -> None:
        """AC3：删掉项目 .env 里的行 ⇒ 回落到 global_env / default 并如实标注新来源。"""
        global_env = _write(tmp_path / "global.env", ["MAX_ITERATIONS=77"])
        project = _write(tmp_path / ".env", ["MAX_ITERATIONS=123"])
        assert _by_key(_report(project, global_env))["MAX_ITERATIONS"].source is ConfigSource.PROJECT_ENV  # type: ignore[union-attr]
        _write(project, [])
        after = _by_key(_report(project, global_env))["MAX_ITERATIONS"]
        assert (after.source, after.value) == (ConfigSource.GLOBAL_ENV, 77)  # type: ignore[union-attr]

    def test_values_match_a_directly_constructed_settings(self, tmp_path: Path) -> None:
        """AC8 对照实验：面板值/来源与「同一份 env_file 直接构造的 Settings」逐键一致。

        这是「同一求解器、非第二套解析」的可执行判据——两处若用不同解析路径，本断言必红。
        """
        global_env = _write(tmp_path / "global.env", ["MAX_ITERATIONS=77", "SHELL_TIMEOUT=5"])
        project = _write(
            tmp_path / ".env",
            ["MAX_ITERATIONS=123", "MAX_CONTEXT_TOKENS=4096", "LOG_LEVEL=DEBUG", "ANNOUNCE_PROGRESS=true"],
        )
        report = _report(project, global_env)
        reference = Settings(_env_file=[str(global_env), str(project)])
        dumped = reference.model_dump(mode="json")
        checked = 0
        for item in report.items:
            if item.is_secret:
                continue  # 凭证项按设计不回值（AC4），只断言「有值」以外的口径
            if item.source is ConfigSource.DEFAULT:
                assert item.value == Settings.model_fields[item.key.lower()].get_default(call_default_factory=True)
                continue
            assert item.value == dumped[item.key.lower()], item.key
            checked += 1
        # 逐键比对的是**全部**非默认来源条目（含系统环境变量层提供的保留期键，数量随 pytest
        # 环境变化），因此这里只钉住「项目层提供的那几个键」与「至少比对过它们」。
        assert {item.key for item in report.items if item.source is ConfigSource.PROJECT_ENV} == {
            "MAX_ITERATIONS",
            "MAX_CONTEXT_TOKENS",
            "LOG_LEVEL",
            "ANNOUNCE_PROGRESS",
        }
        assert checked >= 4

    def test_explicit_path_beats_process_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """坑 4：相对 `.env` 会按**进程 cwd** 解析 ⇒ 求解必须走显式绝对路径。"""
        project = _write(tmp_path / "project" / ".env", ["MAX_ITERATIONS=123"])
        other = _write(tmp_path / "elsewhere" / ".env", ["MAX_ITERATIONS=999"])
        monkeypatch.chdir(other.parent)
        item = _by_key(_report(project))["MAX_ITERATIONS"]  # type: ignore[index]
        assert (item.source, item.value) == (ConfigSource.PROJECT_ENV, 123)  # type: ignore[union-attr]


# ── 七个坑（AC5 / AC6） ──


class TestEnvFilePitfalls:
    def test_layer_raw_string_is_not_used_as_value(self, tmp_path: Path) -> None:
        """坑 1：来源层给的是原始字符串 ``'123'``，展示值必须来自 ``Settings``（``123``）。"""
        project = _write(tmp_path / ".env", ["MAX_ITERATIONS=123"])
        item = _by_key(_report(project))["MAX_ITERATIONS"]  # type: ignore[index]
        assert item.value == 123 and isinstance(item.value, int)  # type: ignore[union-attr]

    def test_unknown_key_is_listed_but_not_an_item(self, tmp_path: Path) -> None:
        """坑 2 + AC5：未知键单列标「不生效」，**不并入**有效值列表。"""
        project = _write(tmp_path / ".env", ["TOTALLY_UNKNOWN_KEY=hello", "MAX_ITERATIONS=123"])
        report = _report(project)
        assert [entry.key for entry in report.unknown_keys] == ["TOTALLY_UNKNOWN_KEY"]
        assert report.unknown_keys[0].source is ConfigSource.PROJECT_ENV
        assert "TOTALLY_UNKNOWN_KEY" not in {item.key for item in report.items}
        assert len(report.items) == len(Settings.model_fields)

    def test_duplicate_key_latter_wins_and_is_noted(self, tmp_path: Path) -> None:
        """坑 5：同文件重复键后者胜，并在条目与文件状态里都提示重复。"""
        project = _write(tmp_path / ".env", ["MAX_CONTEXT_TOKENS=111", "MAX_CONTEXT_TOKENS=222"])
        report = _report(project)
        item = _by_key(report)["MAX_CONTEXT_TOKENS"]  # type: ignore[index]
        assert item.value == 222  # type: ignore[union-attr]
        assert "duplicate_in_project_env" in item.notes  # type: ignore[union-attr]
        assert report.env_file.duplicate_keys == ("MAX_CONTEXT_TOKENS",)

    def test_inline_comment_is_stripped_and_noted(self, tmp_path: Path) -> None:
        """坑 6：行内注释被剥掉（值 = ``99`` 而不是 ``'99 # note'``），且注释本身有诊断。"""
        project = _write(tmp_path / ".env", ["SHELL_TIMEOUT=99   # inline note"])
        item = _by_key(_report(project))["SHELL_TIMEOUT"]  # type: ignore[index]
        assert item.value == 99  # type: ignore[union-attr]
        assert "inline_comment_in_project_env" in item.notes  # type: ignore[union-attr]

    def test_empty_value_is_not_reported_as_default(self, tmp_path: Path) -> None:
        """AC6（坑 7）：``KEY=`` 不得被谎报成「来源=默认」，而要标注空值 + 给出实际生效来源。"""
        global_env = _write(tmp_path / "global.env", ["MEMORY_NUDGE_ENABLED=true"])
        project = _write(tmp_path / ".env", ["MEMORY_NUDGE_ENABLED=", "MAX_ITERATIONS=123"])
        report = _report(project, global_env)
        item = _by_key(report)["MEMORY_NUDGE_ENABLED"]  # type: ignore[index]
        assert item.source is ConfigSource.GLOBAL_ENV  # 实际生效来源  # type: ignore[union-attr]
        assert item.value is True  # type: ignore[union-attr]
        assert "empty_in_project_env" in item.notes  # type: ignore[union-attr]
        assert report.env_file.blank_keys == ("MEMORY_NUDGE_ENABLED",)
        assert "project_env_blank_values" in report.notes
        # 同文件里**其它**键不受影响（空值只降级自己，不拖垮整层）。
        assert _by_key(report)["MAX_ITERATIONS"].source is ConfigSource.PROJECT_ENV  # type: ignore[union-attr]

    def test_empty_value_of_str_field_is_kept_verbatim(self, tmp_path: Path) -> None:
        """``str | None`` 字段接受空串 ⇒ 生效值就是空串（来源仍是项目层），同样标注为空值。"""
        project = _write(tmp_path / ".env", ["LOG_FILE_LEVEL="])
        report = _report(project)
        assert "project_env_blank_values" not in report.notes  # 忠实口径下不需要降级
        item = _by_key(report)["LOG_FILE_LEVEL"]  # type: ignore[index]
        assert item.value == ""  # type: ignore[union-attr]
        assert item.source is ConfigSource.PROJECT_ENV  # type: ignore[union-attr]
        assert "empty_in_project_env" in item.notes  # type: ignore[union-attr]

    def test_invalid_value_degrades_without_raising(self, tmp_path: Path) -> None:
        """项目 .env 值非法 ⇒ 只摘掉项目层（不抛、不 500），并点名文件。"""
        global_env = _write(tmp_path / "global.env", ["MAX_ITERATIONS=77"])
        project = _write(tmp_path / ".env", ["MAX_ITERATIONS=not-a-number"])
        report = _report(project, global_env)
        assert "project_env_invalid" in report.notes
        assert _by_key(report)["MAX_ITERATIONS"].value == 77  # type: ignore[union-attr]
        # 整层摘掉 ⇒ 不再逐项刷「未解析」噪声（响应级一条足够）。
        assert all("ineffective_in_project_env" not in item.notes for item in report.items)

    def test_unknown_keys_survive_layer_degradation(self, tmp_path: Path) -> None:
        """AC5 的诊断不得因「整层被降级摘掉」而消失（评审发现·镜头二③）。

        原先未知键取自参与归属的层，而整层降级会把该层清空 ⇒ 恰在值最可疑的输入上丢掉「键名拼错」
        这条最该给的诊断。现改依据行级扫描（文件里写了什么），与降级无关。
        """
        project = _write(tmp_path / ".env", ["MAX_ITERATIONS=abc", "TYPO_KEY=1", "OTHER_TYPO=2"])
        report = _report(project)
        assert "project_env_invalid" in report.notes
        assert [entry.key for entry in report.unknown_keys] == ["TYPO_KEY", "OTHER_TYPO"]
        assert all(entry.source is ConfigSource.PROJECT_ENV for entry in report.unknown_keys)

    def test_unknown_keys_are_skipped_for_non_utf8_files(self, tmp_path: Path) -> None:
        """非 UTF-8 文件的键名会被替换字符污染 ⇒ 不得据此报「未知键」（避免乱码键名）。"""
        project = _write(tmp_path / ".env", raw=b"MAX_ITERATIONS=7\n\xff\xfe=1\n")
        report = _report(project)
        assert report.unknown_keys == ()
        assert report.env_file.readable is True

    def test_non_utf8_project_env_is_fail_soft(self, tmp_path: Path) -> None:
        """非 UTF-8 的 .env：不抛（与 Z-D12 同立场），如实降级到上层。"""
        global_env = _write(tmp_path / "global.env", ["MAX_ITERATIONS=77"])
        project = _write(tmp_path / ".env", raw="MAX_ITERATIONS=7\n".encode("gbk") + b"\xff\xfe\x00bad\n")
        report = _report(project, global_env)
        assert "project_env_invalid" in report.notes
        assert _by_key(report)["MAX_ITERATIONS"].value == 77  # type: ignore[union-attr]

    def test_unreadable_project_env_is_reported(self, tmp_path: Path) -> None:
        """AC7：``.env`` 不可读（这里是目录） ⇒ 标注不可读、不报 500。"""
        directory = tmp_path / ".env"
        directory.mkdir()
        report = _report(directory)
        assert "project_env_unreadable" in report.notes
        assert report.env_file.exists is True and report.env_file.readable is False
        assert len(report.items) == len(Settings.model_fields)

    def test_unknown_and_file_diagnostics_are_bounded(self, tmp_path: Path) -> None:
        """响应体有界：来自文件内容的列表必须截断并标注。"""
        project = _write(
            tmp_path / ".env",
            [f"UNKNOWN_{index}=1" for index in range(80)]
            + [f"DUP_{index}=1" for index in range(80)]
            + [f"DUP_{index}=2" for index in range(80)],
        )
        report = _report(project)
        assert len(report.unknown_keys) == MAX_UNKNOWN_KEYS
        assert "unknown_keys_truncated" in report.notes
        assert len(report.env_file.duplicate_keys) == MAX_FILE_DIAGNOSTIC_KEYS
        assert "file_diagnostics_truncated" in report.notes


# ── BOM（AC12 / T9b） ──


class TestBomTolerance:
    def test_head_bom_yields_identical_values_and_sources(self, tmp_path: Path) -> None:
        """AC12：文件头 BOM 与「同内容无 BOM」的来源与取值**逐键完全一致**。"""
        body = "MAX_ITERATIONS=777\nMAX_CONTEXT_TOKENS=888\n"
        plain = _write(tmp_path / "plain" / ".env", raw=body.encode())
        bommed = _write(tmp_path / "bom" / ".env", raw=BOM.encode() + body.encode())
        plain_report, bom_report = _report(plain), _report(bommed)
        assert {i.key: (i.value, i.source) for i in plain_report.items} == {
            i.key: (i.value, i.source) for i in bom_report.items
        }
        assert _by_key(bom_report)["MAX_ITERATIONS"].value == 777  # type: ignore[union-attr]
        assert "project_env_bom_stripped" in bom_report.notes
        assert "project_env_bom_stripped" not in plain_report.notes
        assert bom_report.env_file.has_bom is True and plain_report.env_file.has_bom is False
        assert bom_report.env_file.fingerprint != plain_report.env_file.fingerprint

    def test_head_bom_first_key_is_annotated(self, tmp_path: Path) -> None:
        """BOM 容差不是静默行为：首个键的条目上要写明「已按容差读取」。"""
        bommed = _write(tmp_path / ".env", raw=BOM.encode() + b"MAX_ITERATIONS=777\nSHELL_TIMEOUT=9\n")
        report = _report(bommed)
        items = _by_key(report)
        assert "bom_stripped_in_project_env" in items["MAX_ITERATIONS"].notes  # type: ignore[union-attr]
        assert "bom_stripped_in_project_env" not in items["SHELL_TIMEOUT"].notes  # type: ignore[union-attr]

    def test_mid_file_bom_key_is_flagged_not_silently_default(self, tmp_path: Path) -> None:
        """T9b②：**非文件头**的 BOM（键名被污染）必须点名，而不是静默显示为 default。"""
        global_env = _write(tmp_path / "global.env", ["MAX_CONTEXT_TOKENS=4096"])
        project = _write(tmp_path / ".env", raw=b"MAX_ITERATIONS=5\n" + BOM.encode() + b"MAX_CONTEXT_TOKENS=777\n")
        report = _report(project, global_env)
        item = _by_key(report)["MAX_CONTEXT_TOKENS"]  # type: ignore[index]
        assert "bom_prefixed_in_project_env" in item.notes  # type: ignore[union-attr]
        assert item.source is ConfigSource.GLOBAL_ENV  # type: ignore[union-attr]
        assert item.value == 4096  # type: ignore[union-attr]
        assert "bom_prefixed_keys" in report.notes
        assert [entry.key for entry in report.unknown_keys] == [f"{BOM}MAX_CONTEXT_TOKENS"]

    def test_bom_prefixed_keys_helper_is_a_tripwire(self) -> None:
        """绊线本身可执行：任何层漏出 BOM 前缀键都会被点名（当前实现下正常输入为空）。"""
        layers = {
            ConfigSource.PROJECT_ENV: {"max_iterations": "1"},
            ConfigSource.SYSTEM_ENV: {f"{BOM}max_iterations": "1", f"{BOM}shell_timeout": "1"},
        }
        assert bom_prefixed_keys(layers) == (f"{BOM}max_iterations", f"{BOM}shell_timeout")
        assert bom_prefixed_keys({ConfigSource.PROJECT_ENV: {"max_iterations": "1"}}) == ()


# ── 分类：白名单 / 排除 / 只读原因（AC9 / AC10 / R-c） ──


class TestClassification:
    def test_whitelist_keys_all_exist(self) -> None:
        assert whitelist() <= ENV_KEYS
        assert len(whitelist()) == 46  # D3 裁定后的口径（38 + 8）

    def test_partition_is_complete(self) -> None:
        """AC9：每个字段都落在白名单或某条排除规则里 —— 残留 0（没有「只读但无原因」）。"""
        residue = sorted(key for key in ENV_KEYS if classify(key).group == UNKNOWN_GROUP.id)
        assert residue == []
        assert all(entry.reason for entry in EXCLUSION_GROUPS)

    def test_every_item_is_writable_or_has_a_reason(self, tmp_path: Path) -> None:
        report = _report(_write(tmp_path / ".env", ["MAX_ITERATIONS=1"]))
        offenders = [item.key for item in report.items if not item.writable and not item.read_only_reason]
        assert offenders == []
        assert any(item.writable for item in report.items)
        assert any(not item.writable and item.read_only_reason for item in report.items)

    def test_sandbox_dir_retention_days_is_writable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC10（D2）：显式白名单 > 模式排除 ⇒ 保留天数可写且无原因。

        ``tests/conftest.py`` 会用 ``os.environ.setdefault`` 关掉保留期（含本键）——那是**真实**的
        系统环境变量层，故这里先清掉它，断言的是「无系统变量时」的白名单口径。
        """
        monkeypatch.delenv("SANDBOX_DIR_RETENTION_DAYS", raising=False)
        item = _by_key(_report(_write(tmp_path / ".env", [])))["SANDBOX_DIR_RETENTION_DAYS"]  # type: ignore[index]
        assert item.writable is True  # type: ignore[union-attr]
        assert item.read_only_reason is None  # type: ignore[union-attr]

    def test_system_env_overrides_the_whitelist(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """白名单键同样受「被系统环境变量提供」闸门约束（AC2 / 脊柱 §8 第 3 步）。"""
        monkeypatch.setenv("SANDBOX_DIR_RETENTION_DAYS", "3")
        report = _report(_write(tmp_path / ".env", ["SANDBOX_DIR_RETENTION_DAYS=9"]))
        item = _by_key(report)["SANDBOX_DIR_RETENTION_DAYS"]  # type: ignore[index]
        assert (item.source, item.value) == (ConfigSource.SYSTEM_ENV, 3)  # type: ignore[union-attr]
        assert (item.writable, item.read_only_reason) == (False, "system_env")  # type: ignore[union-attr]

    def test_sandbox_posture_keys_stay_read_only(self) -> None:
        """AC10 的另一半：执行姿态键仍只读并给原因。"""
        for key in ("SANDBOX_BACKEND", "SANDBOX_MODE", "SANDBOX_NETWORK", "SANDBOX_FIREJAIL_PATH"):
            verdict = classify(key)
            assert verdict.writable is False and verdict.reason == "sandbox_posture"

    def test_console_keys_reason_is_console_itself(self) -> None:
        """R-c：显式键行 > 模式行 ⇒ 不显示「监听面」而显示「控制台自身」。"""
        for key in ("HTTP_CONSOLE_WRITE_ENABLED", "HTTP_CONSOLE_PROJECTS_FILE"):
            verdict = classify(key)
            assert (verdict.group, verdict.reason) == ("console", "console_itself")
        assert classify("HTTP_PORT").reason == "listening_surface"
        assert classify("TCP_PORT").reason == "listening_surface"

    def test_credential_and_dream_and_redirect_groups(self) -> None:
        assert classify("DEEPSEEK_API_KEY").reason == "credential"
        assert classify("OPENAI_API_KEYS").reason == "credential"
        for key in ("DREAM_CRON", "DREAM_IDLE_MINUTES", "DREAM_MAX_ITERATIONS", "DREAM_SESSION_LOOKBACK"):
            assert classify(key).reason == "dream_supervision"
        assert classify("ACTIVE_PROVIDER").reason == "outbound_redirect"
        assert classify("KIMI_BASE_URL").reason == "outbound_redirect"
        assert classify("GOAL_CHECKPOINT_MODE").reason == "run_semantics"

    def test_groups_are_emitted_once_and_cover_every_item(self, tmp_path: Path) -> None:
        report = _report(_write(tmp_path / ".env", []))
        group_ids = [group.id for group in report.groups]
        assert len(group_ids) == len(set(group_ids))
        assert UNKNOWN_GROUP.id not in group_ids
        assert sum(len(group.items) for group in report.groups) == len(Settings.model_fields)


class TestGuards:
    def test_weak_keys_get_explicit_guards(self) -> None:
        """AC11：5 个弱校验键必须给出守卫约束（枚举 / 上界），否则写通道就是「挂死旋钮」。"""
        level = guards_for("LOG_LEVEL")
        assert level is not None and level.kind == "enum"
        assert level.values == ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        assert guards_for("LOG_FILE_LEVEL").allow_empty is True  # type: ignore[union-attr]
        attempts = guards_for("RETRY_MAX_ATTEMPTS")
        assert (attempts.maximum, attempts.minimum) == (10.0, 1.0)  # type: ignore[union-attr]
        assert guards_for("RETRY_BASE_DELAY").maximum == 60.0  # type: ignore[union-attr]
        assert guards_for("RETRY_MAX_DELAY").maximum == 600.0  # type: ignore[union-attr]
        assert guards_for("CONTEXT_STRATEGY").values == ("compressor", "reset")  # type: ignore[union-attr]
        assert set(VALUE_GUARDS) <= ENV_KEYS  # 守卫表里不允许有幽灵键

    def test_guards_are_derived_from_field_metadata(self) -> None:
        assert guards_for("MAX_ITERATIONS").minimum == 1.0  # type: ignore[union-attr]
        threshold = guards_for("COMPRESSION_THRESHOLD")
        assert (threshold.minimum, threshold.maximum) == (0.0, 1.0)  # type: ignore[union-attr]
        assert guards_for("DEFAULT_MODEL") is None
        assert guards_for("SAFETY_BLOCKED_TOOLS") is None  # 无约束的复合字段
        assert guards_for("HTTP_PORT").maximum == 65535.0  # type: ignore[union-attr]
        assert guards_for("HTTP_MAX_CONNECTIONS").min_length is None  # type: ignore[union-attr]
        assert guards_for("NOT_A_FIELD") is None

    def test_every_ceiling_is_generous_and_actually_applied(self) -> None:
        """上界表**逐条**过一遍（口径的可执行判据）：① 真的进了 ``guards_for``；② 至少是默认值的 10 倍
        （「远高于任何真实用法」不是散文）；③ 字段元数据派生的下界仍被合并保留。

        遍历 :data:`RESOURCE_CEILINGS` 本体而不是在测试里抄一份 —— 单一事实源，新增键自动纳入。
        """
        assert len(RESOURCE_CEILINGS) >= 20, "上界表应覆盖全部「只有下界」的数值键"
        for key, ceiling in RESOURCE_CEILINGS.items():
            guard = guards_for(key)
            assert guard is not None, key
            assert guard.kind == "range" and guard.maximum == ceiling, key
            default = Settings.model_fields[key.lower()].default
            if default is not None:
                assert default * 10 <= ceiling, f"{key}: 上界 {ceiling} 离默认值 {default} 太近，会绑住正常用法"
        assert guards_for("MAX_ITERATIONS").minimum == 1.0  # type: ignore[union-attr]

    def test_no_whitelisted_numeric_key_is_left_unbounded(self) -> None:
        """**完备性**：白名单里的数值键必须**全部**有上界 —— 这是「一处处补」变成「一类问题闭合」的判据。

        没有它，「明天新增一个白名单数值键但忘了给上界」只会静默漂移（本缺口正是这样被登记两遍的）。
        若某键确实无需上界，把它显式豁免在下方的集合里并写清理由，而不是让本断言松掉。
        """
        exempt: set[str] = set()
        unbounded = {
            key
            for key in whitelist()
            if (guard := guards_for(key)) is not None and guard.kind == "range" and guard.maximum is None
        }
        assert unbounded - exempt == set(), f"白名单里仍有无数值上界的键：{sorted(unbounded - exempt)}"

    def test_the_ceiling_table_is_exactly_the_agreed_one(self) -> None:
        """口径固化：上界表的**完整内容**（键 → 上限）逐条钉住。

        上面两条用**规则**钉（≥ 10 × 默认、完备性），但规则挡不住「把 604800 悄悄改成 999999999」——
        它仍然 ≥ 10 × 默认、也仍然完备。而同族同刻度（3650 / 604800 / 8388608 / 1000000 / 100 / 10000 /
        16000000）正是本表的核心口径，故必须逐条比对。
        """
        assert RESOURCE_CEILINGS == {
            # days = 3650（10 年；这批键都支持 0 = 禁用回收，「永久保留」用 0 表达）
            "EDIT_SNAPSHOT_RETENTION_DAYS": 3650.0,
            "LEDGER_RETENTION_DAYS": 3650.0,
            "LOG_RETENTION_DAYS": 3650.0,
            "RUN_RETENTION_DAYS": 3650.0,
            "SANDBOX_DIR_RETENTION_DAYS": 3650.0,
            "SESSION_RETENTION_DAYS": 3650.0,
            "SKILL_CURATOR_STALE_DAYS": 3650.0,
            # seconds = 604800（7 天）
            "CRON_TICK_SECONDS": 604800.0,
            "PRUNE_MIN_INTERVAL_SECONDS": 604800.0,
            "SHELL_TIMEOUT": 604800.0,
            # bytes = 8388608（8 MiB）
            "CONTEXT_FILES_MAX_BYTES": 8_388_608.0,
            "MEMORY_INJECT_MAX_BYTES": 8_388_608.0,
            # tokens = 1000000
            "MAX_OUTPUT_TOKENS": 1_000_000.0,
            "SKILL_MAX_AUTO_INVOKE_TOKENS": 1_000_000.0,
            "SKILL_MAX_MANUAL_LOAD_TOKENS": 1_000_000.0,
            # count = 100
            "SKILL_MAX_AUTO_INVOKE": 100.0,
            "SUBAGENT_MAX_DEPTH": 100.0,
            # 迭代预算 = 10000（自成刻度）
            "MAX_ITERATIONS": 10_000.0,
            "GOAL_MAX_ITERATIONS": 10_000.0,
            "SUBAGENT_MAX_ITERATIONS": 10_000.0,
            # 上下文窗口 = 16000000（模型属性量级，自成刻度）
            "MAX_CONTEXT_TOKENS": 16_000_000.0,
        }

    def test_ceilings_do_not_change_what_settings_accepts(self) -> None:
        """冻结边界：守卫只作用于写入通道与面板展示 —— ``Settings`` 仍接受任意 ``≥1`` 的值。

        给字段加 ``le=`` 会改变**既有配置文件的可加载性**（盘上一个 ``MAX_ITERATIONS=999999`` 会从
        「能起」变成「起不来」），那是另一个决定；本表刻意不做。
        """
        assert Settings(max_iterations=10_000_000, _env_file=None).max_iterations == 10_000_000
        assert guards_for("MAX_ITERATIONS").maximum == 10_000.0  # type: ignore[union-attr]


# ── 凭证掩码（AC4） ──


class TestSecrets:
    def test_all_api_key_fields_are_secret(self, tmp_path: Path) -> None:
        secrets = {key for key in ENV_KEYS if is_secret_key(key)}
        assert secrets == {
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_API_KEYS",
            "DEEPSEEK_API_KEY",
            "GLM_API_KEY",
            "KIMI_API_KEY",
            "OLLAMA_API_KEY",
            "OPENAI_API_KEY",
            "OPENAI_API_KEYS",
            "OPENAI_RESPONSES_API_KEY",
        }
        for item in _report(_write(tmp_path / ".env", [])).items:
            if item.key in secrets:
                assert item.is_secret and item.value is None and item.read_only_reason == "credential"

    def test_configured_flag_and_constant_mask(self, tmp_path: Path) -> None:
        project = _write(tmp_path / ".env", ["KIMI_API_KEY=kimi-live-key"])
        items = _by_key(_report(project))
        present = items["KIMI_API_KEY"]
        absent = items["OPENAI_API_KEY"]
        assert (present.configured, present.masked) == (True, MASK)  # type: ignore[union-attr]
        assert (absent.configured, absent.masked) == (False, None)  # type: ignore[union-attr]

    def test_short_key_does_not_leak(self, tmp_path: Path) -> None:
        """AC4 负向：长度 ≤ 掩码位数的密钥也不得因展示而暴露全文（掩码是常量、零信息量）。"""
        short_key = "q7Zx"
        project = _write(tmp_path / ".env", [f"KIMI_API_KEY={short_key}"])
        report = _report(project)
        payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
        item = _by_key(report)["KIMI_API_KEY"]
        assert item.masked == MASK and len(item.masked) == len(MASK)  # type: ignore[union-attr]
        assert not set(item.masked or "") & set(short_key)  # type: ignore[arg-type]
        assert short_key not in payload

    def test_multi_key_list_does_not_leak(self, tmp_path: Path) -> None:
        """AC4 负向：多密钥（逗号列表）同样只回布尔 + 常量掩码。"""
        project = _write(tmp_path / ".env", ["OPENAI_API_KEYS=key-one,key-two"])
        report = _report(project)
        payload = json.dumps(report.model_dump(mode="json"), ensure_ascii=False)
        item = _by_key(report)["OPENAI_API_KEYS"]
        assert (item.value, item.masked, item.configured) == (None, MASK, True)  # type: ignore[union-attr]
        assert "key-one" not in payload and "key-two" not in payload

    def test_no_secret_plaintext_anywhere_in_the_payload(self, tmp_path: Path) -> None:
        marker = "sk-live-MARKER-1234567890"
        project = _write(
            tmp_path / ".env",
            [f"KIMI_API_KEY={marker}", f"OPENAI_API_KEY={marker}", f"ANTHROPIC_API_KEYS={marker}"],
        )
        payload = json.dumps(_report(project).model_dump(mode="json"), ensure_ascii=False)
        assert marker not in payload


class TestRoutingPoolsView:
    """T8：``ROUTING_POOLS`` 展示的是**有效**结果，不是「一串 JSON」。"""

    def test_valid_pools_are_reported_as_effective(self, tmp_path: Path) -> None:
        project = _write(
            tmp_path / ".env",
            ['ROUTING_POOLS={"glm": {"tiers": {"fast": "glm-5.3-flash", "pro": "glm-5.3"}, "default": "pro"}}'],
        )
        item = _by_key(_report(project))["ROUTING_POOLS"]
        assert item.notes == ()  # type: ignore[union-attr]
        routing = item.routing  # type: ignore[union-attr]
        assert routing is not None and routing.invalid_json is False
        assert routing.declared_entries == ("glm",)
        assert [pool.entry for pool in routing.effective] == ["glm"]
        assert routing.effective[0].tiers == {"fast": "glm-5.3-flash", "pro": "glm-5.3"}
        assert routing.effective[0].default == "pro"
        assert routing.ignored_entries == ()

    def test_invalid_json_is_flagged(self, tmp_path: Path) -> None:
        raw = '{"glm":'  # 注意：dotenv 会吃掉值尾的空白，故样本不带尾空格
        project = _write(tmp_path / ".env", [f"ROUTING_POOLS={raw}"])
        item = _by_key(_report(project))["ROUTING_POOLS"]
        assert item.value == raw  # 原始串仍如实展示（值来自 Settings）  # type: ignore[union-attr]
        assert item.routing is not None and item.routing.invalid_json is True  # type: ignore[union-attr]
        assert "routing_pools_invalid" in item.notes  # type: ignore[union-attr]
        assert item.routing.effective == ()  # type: ignore[union-attr]

    def test_unknown_entry_is_reported_as_ignored(self, tmp_path: Path) -> None:
        project = _write(tmp_path / ".env", ['ROUTING_POOLS={"nope": {"tiers": {"fast": "x"}}}'])
        item = _by_key(_report(project))["ROUTING_POOLS"]
        routing = item.routing  # type: ignore[union-attr]
        assert routing is not None
        assert routing.declared_entries == ("nope",) and routing.ignored_entries == ("nope",)
        assert routing.effective == ()
        assert "routing_pools_entries_ignored" in item.notes  # type: ignore[union-attr]

    def test_empty_value_has_no_routing_view_noise(self, tmp_path: Path) -> None:
        item = _by_key(_report(_write(tmp_path / ".env", [])))["ROUTING_POOLS"]
        routing = item.routing  # type: ignore[union-attr]
        assert routing is not None and routing.declared_entries == () and routing.invalid_json is False
        assert item.notes == ()  # type: ignore[union-attr]
        assert _by_key(_report(_write(tmp_path / "other" / ".env", [])))["MAX_ITERATIONS"].routing is None  # type: ignore[union-attr]


# ── 响应形状与诊断契约 ──


class TestReportShape:
    def test_labels_cover_every_code_in_the_report(self, tmp_path: Path) -> None:
        """诊断码必须都能翻成文案：响应里出现的每个码都要在 ``labels`` 里有条目。"""
        global_env = _write(tmp_path / "global.env", ["MEMORY_NUDGE_ENABLED=true"])
        project = _write(
            tmp_path / ".env",
            ["MAX_ITERATIONS=1", "MAX_ITERATIONS=2", "SHELL_TIMEOUT=3 # note", "MEMORY_NUDGE_ENABLED="],
        )
        report = _report(project, global_env)
        codes = set(report.notes)
        for item in report.items:
            codes.update(item.notes)
            if item.read_only_reason:
                codes.add(item.read_only_reason)
        assert codes <= set(report.labels)
        assert report.labels == LABELS

    def test_write_gate_badge_label_is_declared_and_stays_short(self) -> None:
        """设置面板头部的闸门徽标文案由服务端声明，且**短到不会把同一行挤换行**（Story 50-8 R9）。

        为什么需要这条：前端对该键有**逐字相同**的兜底（`app.js` 里 `|| "只读"`），所以这个键一旦
        消失，页面看不出差别、前端用例也照绿（评审实测：把兜底写死后 `tests/test_http_web_ui.py`
        **137 passed / 0 failed**）。这里的服务端判据钉两件事：①声明存在；②长度受控——设置列内容
        宽约 364px，「项目设置 + 项目名徽标」已占约 160px，文案再长就会换行（那正是 R9 撤销的
        「独占一行」形态）。
        """
        badge = LABELS["write_channel_badge"]
        assert badge, "闸门徽标不得为空（空串会让 UI 回落到兜底，声明形同虚设）"
        assert len(badge) <= 4, f"闸门徽标必须够短（宽度是硬约束）：{badge!r}"

    def test_env_file_fingerprint_is_sha256_of_bytes(self, tmp_path: Path) -> None:
        raw = b"MAX_ITERATIONS=123\n"
        project = _write(tmp_path / ".env", raw=raw)
        report = _report(project)
        assert report.env_file.fingerprint == hashlib.sha256(raw).hexdigest()
        assert report.env_file.line_count == 1  # 末行换行不额外算一行（评审发现·镜头二⑤）

    def test_empty_env_file_counts_zero_lines(self, tmp_path: Path) -> None:
        """0 字节的 .env 是 0 行（原先按 ``split("\\n")`` 段数计会谎报 1 行）。"""
        report = _report(_write(tmp_path / ".env", raw=b""))
        assert (report.env_file.exists, report.env_file.line_count) == (True, 0)
        assert report.notes == ()  # 空文件不是错误：全字段落 global/default，无诊断噪声

    def test_scan_classifies_lines_without_parsing_values(self, tmp_path: Path) -> None:
        project = _write(
            tmp_path / ".env",
            ["# comment", "", "MAX_ITERATIONS=1", "MAX_ITERATIONS=2", "SHELL_TIMEOUT=   # only comment", "X=1"],
        )
        scan = scan_env_file(project)
        assert scan.readable and scan.exists
        assert scan.declared_keys == ("MAX_ITERATIONS", "SHELL_TIMEOUT", "X")
        assert scan.duplicate_keys == ("MAX_ITERATIONS",)
        assert scan.blank_keys == ("SHELL_TIMEOUT",)
        assert scan.inline_comment_keys == ("SHELL_TIMEOUT",)
        assert scan.name_by_lower["max_iterations"] == "MAX_ITERATIONS"

    def test_missing_file_scan_is_empty(self, tmp_path: Path) -> None:
        scan = scan_env_file(tmp_path / "nope.env")
        assert (scan.exists, scan.readable, scan.fingerprint) == (False, False, None)
        assert scan_env_file(None) == scan_env_file(None) and scan_env_file(None).path is None

    def test_report_is_json_serializable_and_deterministic(self, tmp_path: Path) -> None:
        project = _write(tmp_path / ".env", ["MAX_ITERATIONS=123"])
        first, second = _report(project), _report(project)
        payload = json.dumps(first.model_dump(mode="json"), ensure_ascii=False)
        assert payload == json.dumps(second.model_dump(mode="json"), ensure_ascii=False)
        assert len(payload) < 200_000

    def test_iterating_items_is_a_flat_view(self, tmp_path: Path) -> None:
        report = _report(_write(tmp_path / ".env", []))
        assert len(report.items) == report.field_count
        assert {item.key for item in report.items} == ENV_KEYS

    def test_whitelist_groups_do_not_overlap(self) -> None:
        seen: set[str] = set()
        for spec in WHITELIST_GROUPS:
            assert not (set(spec.keys) & seen), spec.id
            seen |= set(spec.keys)
            assert spec.reason is None
            assert spec.label and not spec.patterns  # 可写组一律显式列键
        assert seen == set(whitelist())

    def test_catalog_has_no_runtime_imports(self) -> None:
        """脊柱 §2：``config_catalog`` 不得依赖 engine / agent / 入口层。"""
        source = (Path(__file__).resolve().parents[1] / "src" / "heagent" / "config" / "catalog.py").read_text(
            encoding="utf-8"
        )
        for forbidden in ("heagent.engine", "heagent.agent", "heagent.cli", "heagent.network"):
            assert f"from {forbidden}" not in source, forbidden
