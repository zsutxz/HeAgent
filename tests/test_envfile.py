"""Story 50-5 T1/T2/T10：``.env`` 行级保真读写的逐字节断言。

这一层是**唯一**会改写用户既有文件的代码路径，因此断言的口径是「字节」而不是「语义」：
只有目标行被替换，其余行的字节、行尾（CRLF/LF）、文件头 BOM、注释、空行逐字节不变。

样本刻意取真实项目 ``.env`` 的四种形态（CRLF + 行内注释 + 重复键 + 无末行换行 + BOM），因为这四处
正是「整文件重写」实现最容易出错的地方（也是评审 F6 的来源：首行键名被 BOM 污染 ⇒ 找不到目标行）。
"""

from __future__ import annotations

import ast
import hashlib
import os
import time
from pathlib import Path

import pytest

from heagent.config import envfile

# 真实项目 .env 的形态：CRLF + 行内注释 + 重复键（后者生效）+ 末行无换行。
CRLF_SAMPLE = (
    b"# HeAgent project config\r\n"
    b"MAX_ITERATIONS=25\r\n"
    b"LOG_LEVEL=INFO  # console level\r\n"
    b"\r\n"
    b"SKILL_MAX_AUTO_INVOKE_TOKENS=4000\r\n"
    b"SKILL_MAX_AUTO_INVOKE_TOKENS=5000\r\n"
    b"NO_TRAILING_NEWLINE=1"
)

BOM_SAMPLE = b"\xef\xbb\xbfMAX_ITERATIONS=25\r\nLOG_LEVEL=INFO\r\n"


def _segments(raw: bytes) -> list[bytes]:
    """按 ``\\n`` 切段（保留段内的 ``\\r``）：与 ``replace_or_append`` 的行序一一对应。"""
    return raw.split(b"\n")


def _assert_only_line_changed(before: bytes, after: bytes, index: int) -> None:
    """除第 ``index`` 段外，其余段**逐字节**相同（行序与段数也必须一致）。"""
    old, new = _segments(before), _segments(after)
    assert len(old) == len(new), (old, new)
    for position, (was, now) in enumerate(zip(old, new, strict=True)):
        if position == index:
            assert was != now, f"target line {index} did not change"
            continue
        assert was == now, f"line {position} changed: {was!r} → {now!r}"


def _assert_appended(before: bytes, after: bytes, appended: bytes, *, eol: bytes) -> None:
    """追加语义：``before`` 逐字节是 ``after`` 的前缀，且新增部分**恰好**是 ``eol + appended``。"""
    assert after.startswith(before), (before, after)
    assert after[len(before) :] == eol + appended


class TestParseIndex:
    def test_indexes_keys_comments_and_duplicates(self) -> None:
        index = envfile.parse_index(CRLF_SAMPLE.decode("utf-8"))

        assert index.eol == "\r\n"
        assert index.has_bom is False
        assert index.trailing_newline is False  # 末行没有换行
        assert index.line_count == 7
        # 注释行与空行不产生键；同键只留**最后**一行（后者生效，脊柱 §7 坑 5）。
        assert index.keys == ("MAX_ITERATIONS", "LOG_LEVEL", "SKILL_MAX_AUTO_INVOKE_TOKENS", "NO_TRAILING_NEWLINE")
        assert index.line_by_key["skill_max_auto_invoke_tokens"] == 5
        assert index.duplicate_keys == ("SKILL_MAX_AUTO_INVOKE_TOKENS",)
        assert index.inline_comment_keys == ("LOG_LEVEL",)

    def test_empty_file_has_no_lines(self) -> None:
        index = envfile.parse_index("")

        assert (index.line_count, index.keys, index.eol) == (0, (), "\n")
        assert index.trailing_newline is False

    def test_trailing_newline_does_not_add_a_line(self) -> None:
        index = envfile.parse_index("A=1\nB=2\n")

        assert (index.line_count, index.trailing_newline) == (2, True)

    def test_head_bom_is_recorded_and_stripped_from_the_first_key(self) -> None:
        """F6 的另一半：索引里的键名**不带** BOM，否则替换会 miss 而追加死行。"""
        index = envfile.parse_index(BOM_SAMPLE.decode("utf-8"))

        assert index.has_bom is True
        assert index.keys == ("MAX_ITERATIONS", "LOG_LEVEL")
        assert index.line_by_key["max_iterations"] == 0

    def test_export_prefix_is_recognised(self) -> None:
        index = envfile.parse_index("export MAX_ITERATIONS=3\n")

        assert index.keys == ("MAX_ITERATIONS",)
        assert envfile.read_value("export MAX_ITERATIONS=3\n", "max_iterations") == "3"  # 读侧同一口径

    def test_line_without_a_key_is_not_indexed(self) -> None:
        """``=1`` 这种没有键名的行不产生键（否则会出现一个永远匹配不上的幽灵键）。"""
        index = envfile.parse_index("=1\nA=2\n")

        assert index.keys == ("A",)

    def test_fingerprint_is_sha256_of_bytes(self) -> None:
        assert envfile.fingerprint(CRLF_SAMPLE) == hashlib.sha256(CRLF_SAMPLE).hexdigest()


class TestReadValue:
    def test_last_occurrence_wins_and_comment_is_stripped(self) -> None:
        text = CRLF_SAMPLE.decode("utf-8")

        assert envfile.read_value(text, "SKILL_MAX_AUTO_INVOKE_TOKENS") == "5000"
        assert envfile.read_value(text, "LOG_LEVEL") == "INFO"
        assert envfile.read_value(text, "max_iterations") == "25"  # 键名大小写不敏感
        assert envfile.read_value(text, "NOT_THERE") is None

    def test_commented_out_key_is_not_a_value(self) -> None:
        assert envfile.read_value("# MAX_ITERATIONS=99\n", "MAX_ITERATIONS") is None


class TestReplaceOrAppend:
    def test_replace_touches_only_the_target_line(self) -> None:
        text = CRLF_SAMPLE.decode("utf-8")

        updated = envfile.replace_or_append(text, "MAX_ITERATIONS", "30")

        _assert_only_line_changed(CRLF_SAMPLE, updated.encode("utf-8"), 1)
        assert envfile.read_value(updated, "MAX_ITERATIONS") == "30"

    def test_inline_comment_and_crlf_survive_on_the_target_line(self) -> None:
        updated = envfile.replace_or_append(CRLF_SAMPLE.decode("utf-8"), "LOG_LEVEL", "DEBUG")

        _assert_only_line_changed(CRLF_SAMPLE, updated.encode("utf-8"), 2)
        assert _segments(updated.encode("utf-8"))[2] == b"LOG_LEVEL=DEBUG  # console level\r"

    def test_comment_after_a_quoted_value_is_preserved(self) -> None:
        """引号值里的 ``#`` 不是注释（实测），因此注释只在**闭合引号之后**判断。"""
        updated = envfile.replace_or_append('DEFAULT_MODEL="a # b" # note\n', "DEFAULT_MODEL", "c")

        assert updated == "DEFAULT_MODEL=c # note\n"

    def test_duplicate_key_replaces_the_last_line_only(self) -> None:
        updated = envfile.replace_or_append(CRLF_SAMPLE.decode("utf-8"), "SKILL_MAX_AUTO_INVOKE_TOKENS", "9001")

        _assert_only_line_changed(CRLF_SAMPLE, updated.encode("utf-8"), 5)
        assert envfile.read_value(updated, "SKILL_MAX_AUTO_INVOKE_TOKENS") == "9001"
        # 第一行（4000）原样留着 —— 替换的是**生效**的那一行。
        assert _segments(updated.encode("utf-8"))[4] == b"SKILL_MAX_AUTO_INVOKE_TOKENS=4000\r"

    def test_replacing_the_last_line_without_terminator_keeps_it_terminator_free(self) -> None:
        updated = envfile.replace_or_append(CRLF_SAMPLE.decode("utf-8"), "NO_TRAILING_NEWLINE", "2")

        raw = updated.encode("utf-8")
        _assert_only_line_changed(CRLF_SAMPLE, raw, 6)
        assert raw.endswith(b"NO_TRAILING_NEWLINE=2")  # 仍无末行换行

    def test_append_follows_the_file_eol_and_keeps_the_missing_terminator(self) -> None:
        updated = envfile.replace_or_append(CRLF_SAMPLE.decode("utf-8"), "NEW_KEY", "v")

        raw = updated.encode("utf-8")
        # 末行原本没有换行 ⇒ 追加时先补上文件的 EOL，新增的末行同样没有换行。
        _assert_appended(CRLF_SAMPLE, raw, b"NEW_KEY=v", eol=b"\r\n")

    def test_append_after_a_terminated_file_adds_no_extra_blank_line(self) -> None:
        text = "A=1\nB=2\n"

        updated = envfile.replace_or_append(text, "C", "3")

        assert updated == "A=1\nB=2\nC=3\n"

    def test_append_to_empty_or_missing_file_uses_lf_with_terminator(self) -> None:
        assert envfile.replace_or_append("", "MAX_ITERATIONS", "5") == "MAX_ITERATIONS=5\n"
        assert envfile.replace_or_append("", "LOG_FILE_LEVEL", "") == "LOG_FILE_LEVEL=\n"

    def test_lf_file_stays_lf(self) -> None:
        text = "A=1\nB=2\n"

        updated = envfile.replace_or_append(text, "A", "9")

        assert updated == "A=9\nB=2\n"
        assert "\r" not in updated

    def test_existing_key_spelling_and_export_prefix_are_preserved(self) -> None:
        """只重写值区：键名写法 / ``export`` 前缀不是我们要改的东西。"""
        assert envfile.replace_or_append("export MAX_ITERATIONS=3\n", "MAX_ITERATIONS", "4") == (
            "export MAX_ITERATIONS=4\n"
        )
        assert envfile.replace_or_append("max_iterations=3\n", "MAX_ITERATIONS", "4") == "max_iterations=4\n"

    def test_values_containing_spaces_round_trip(self) -> None:
        updated = envfile.replace_or_append("DEFAULT_MODEL=x\n", "DEFAULT_MODEL", "gpt-4o mini")

        assert envfile.read_value(updated, "DEFAULT_MODEL") == "gpt-4o mini"

    # ── BOM（评审 F6 / AC11） ──

    def test_head_bom_key_is_replaced_not_appended_and_bom_survives(self) -> None:
        updated = envfile.replace_or_append(BOM_SAMPLE.decode("utf-8"), "MAX_ITERATIONS", "7")

        raw = updated.encode("utf-8")
        _assert_only_line_changed(BOM_SAMPLE, raw, 0)
        assert raw.startswith(envfile.BOM_BYTES)
        assert raw.count(b"MAX_ITERATIONS") == 1  # 没有追加出第二条（那会是一条永不生效的死行）

    def test_head_bom_survives_an_append(self) -> None:
        updated = envfile.replace_or_append(BOM_SAMPLE.decode("utf-8"), "NEW_KEY", "1")

        raw = updated.encode("utf-8")
        assert raw.startswith(envfile.BOM_BYTES)
        assert raw.endswith(b"NEW_KEY=1\r\n")  # 文件是 CRLF ⇒ 追加行也用 CRLF

    # ── 值 / 键的 fail-closed 校验 ──

    @pytest.mark.parametrize(
        ("value", "reason"),
        [
            ("a\nb", "control_characters"),
            ("a\rb", "control_characters"),
            ("a\x00b", "control_characters"),
            (f"a{envfile.BOM}b", "control_characters"),
            (" padded", "whitespace"),
            ("padded ", "whitespace"),
            ("a # looks like a comment", "inline_comment"),
            ("a\t# tab comment", "inline_comment"),
            ('"quoted"', "quoted"),
            ("'quoted'", "quoted"),
            ("x" * (envfile.MAX_VALUE_CHARS + 1), "too_long"),
        ],
    )
    def test_unrepresentable_values_are_rejected(self, value: str, reason: str) -> None:
        with pytest.raises(envfile.EnvWriteError) as excinfo:
            envfile.replace_or_append("A=1\n", "MAX_ITERATIONS", value)

        assert excinfo.value.reason == reason

    @pytest.mark.parametrize("value", ["a#b", "gpt-4o mini", "#x", "1e9", ""])
    def test_values_that_round_trip_are_accepted(self, value: str) -> None:
        """裸 ``#``（前面无空白）与内含空格都是 dotenv 原样保留的值（实测），不该被拒。"""
        updated = envfile.replace_or_append("A=1\n", "DEFAULT_MODEL", value)

        assert envfile.read_value(updated, "DEFAULT_MODEL") == value

    def test_unclosed_quote_is_treated_as_a_plain_value(self) -> None:
        """没闭合引号时按「没有注释」处理（不猜）——引号感知只影响注释定位，不改值。"""
        assert envfile.parse_value('"unclosed') == '"unclosed'
        assert envfile.parse_value('"closed"') == "closed"

    def test_empty_value_is_allowed(self) -> None:
        """``KEY=`` 是合法写法（``LOG_FILE_LEVEL=`` = 关掉文件日志）——空值另有语义，不是「坏值」。"""
        envfile.check_value("", key="LOG_FILE_LEVEL")

    @pytest.mark.parametrize("key", ["MAX ITERATIONS", "MAX=1", "", "1MAX", "MAX-ITERATIONS", "x" * 65])
    def test_invalid_keys_are_rejected(self, key: str) -> None:
        with pytest.raises(envfile.EnvWriteError) as excinfo:
            envfile.replace_or_append("A=1\n", key, "1")

        assert excinfo.value.reason == "invalid_key"


class TestParseValueAlignment:
    """``envfile.parse_value`` 必须与**真正**解析 ``.env`` 的那一层逐字一致（探针实测的口径）。

    这是「写通道不只是写进去、还要写上生效的值」的根：审计的旧值哈希、``changes`` 的写后条目都从
    这条口径派生。直接用 ``DotEnvSettingsSource``（求解器 / 运行期同款）当参照，任何一侧漂移即红。
    """

    LINES = (
        "MAX_CONTEXT_TOKENS=1111",
        "MAX_CONTEXT_TOKENS=INFO  # two spaces",
        "MAX_CONTEXT_TOKENS=INFO # one space",
        "MAX_CONTEXT_TOKENS=a#b",
        "MAX_CONTEXT_TOKENS=a #b",
        'MAX_CONTEXT_TOKENS="a # b"',
        "MAX_CONTEXT_TOKENS='quoted'",
        "MAX_CONTEXT_TOKENS=  spaced",
        "MAX_CONTEXT_TOKENS=trail   ",
        "MAX_CONTEXT_TOKENS=",
        "MAX_CONTEXT_TOKENS=#x",
        "MAX_CONTEXT_TOKENS=x#y # z",
        "MAX_CONTEXT_TOKENS=x\t# tab",
        "MAX_CONTEXT_TOKENS=`backtick`",
        "MAX_CONTEXT_TOKENS=x\t",
    )

    @pytest.mark.parametrize("line", LINES)
    def test_parse_value_matches_the_dotenv_layer(self, line: str, tmp_path: Path) -> None:
        from pydantic_settings import DotEnvSettingsSource

        from heagent.config import Settings

        path = tmp_path / ".env"
        path.write_bytes(f"{line}\n".encode())
        layer = DotEnvSettingsSource(Settings, env_file=path)()

        raw = line.partition("=")[2]
        assert envfile.parse_value(raw) == layer["max_context_tokens"]

    def test_unparseable_multi_quote_line_is_dropped_by_the_parser(self, tmp_path: Path) -> None:
        """``"a"b"`` 会让 dotenv **整行作废**（实测）——所以写通道把配对引号的值直接拒掉（fail-closed）。"""
        from pydantic_settings import DotEnvSettingsSource

        from heagent.config import Settings

        path = tmp_path / ".env"
        path.write_bytes(b'MAX_CONTEXT_TOKENS="a"b"\n')
        assert DotEnvSettingsSource(Settings, env_file=path)() == {}
        with pytest.raises(envfile.EnvWriteError) as excinfo:
            envfile.replace_or_append("A=1\n", "MAX_CONTEXT_TOKENS", '"a"b"')
        assert excinfo.value.reason == "quoted"


class TestBackup:
    def test_backup_name_has_stamp_and_fingerprint_prefix(self, tmp_path: Path) -> None:
        source = tmp_path / ".env"
        source.write_bytes(CRLF_SAMPLE)
        backups = tmp_path / "backups"

        created = envfile.backup(source, backups, envfile.fingerprint(CRLF_SAMPLE))

        assert created is not None
        assert created.parent == backups
        name = created.name
        assert name.startswith("env-") and name.endswith(envfile.BACKUP_SUFFIX)
        assert envfile.fingerprint(CRLF_SAMPLE)[:8] in name
        assert created.read_bytes() == CRLF_SAMPLE  # 备份是**源字节**的副本

    def test_backup_is_none_when_there_is_no_previous_file(self, tmp_path: Path) -> None:
        assert envfile.backup(tmp_path / ".env", tmp_path / "backups", "0" * 64) is None

    def test_backups_of_consecutive_writes_are_distinct(self, tmp_path: Path) -> None:
        source = tmp_path / ".env"
        backups = tmp_path / "backups"
        source.write_bytes(b"A=1\n")
        first = envfile.backup(source, backups, envfile.fingerprint(b"A=1\n"))
        source.write_bytes(b"A=2\n")
        second = envfile.backup(source, backups, envfile.fingerprint(b"A=2\n"))

        assert first is not None and second is not None and first != second


class TestPruneBackups:
    def _make(self, directory: Path, count: int, *, age_days: float = 0.0, prefix: str = "") -> list[Path]:
        """造 ``count`` 个备份：文件名唯一，序号越大 **mtime 越新**（``created[-1]`` 是最新的）。"""
        directory.mkdir(parents=True, exist_ok=True)
        created = []
        for index in range(count):
            path = directory / f"env-{prefix}{index:03d}-{'0' * 8}.bak"
            path.write_bytes(b"A=1\n")
            stamp = time.time() - age_days * 86_400 + index
            os.utime(path, (stamp, stamp))
            created.append(path)
        return created

    def test_count_cap_keeps_the_newest(self, tmp_path: Path) -> None:
        backups = tmp_path / "backups"
        created = self._make(backups, 5)

        deleted = envfile.prune_backups(backups, retention_days=0, max_entries=2)

        assert deleted == 3
        assert sorted(path.name for path in backups.iterdir()) == sorted(path.name for path in created[3:])

    def test_retention_removes_expired_entries(self, tmp_path: Path) -> None:
        backups = tmp_path / "backups"
        old = self._make(backups, 2, age_days=40, prefix="old")
        fresh = self._make(backups, 1, prefix="new")

        deleted = envfile.prune_backups(backups, retention_days=30, max_entries=50)

        assert deleted == 2
        assert [path.name for path in backups.iterdir()] == [fresh[0].name]
        assert len(old) == 2

    def test_foreign_files_are_left_alone(self, tmp_path: Path) -> None:
        backups = tmp_path / "backups"
        self._make(backups, 3)
        keep = backups / "notes.txt"
        keep.write_text("not a backup", encoding="utf-8")

        envfile.prune_backups(backups, retention_days=0, max_entries=1)

        assert keep.exists()

    def test_missing_directory_is_a_no_op(self, tmp_path: Path) -> None:
        assert envfile.prune_backups(tmp_path / "nope", retention_days=30, max_entries=1) == 0


class TestModuleBoundary:
    def test_envfile_has_no_runtime_imports_of_the_stack(self) -> None:
        """配置包模块（脊柱 §2）：只允许标准库 / pydantic / ``pub.persist``。"""
        source = (Path(__file__).resolve().parents[1] / "src" / "heagent" / "config" / "envfile.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        roots = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        assert {"heagent"} <= roots
        for forbidden in ("heagent.engine", "heagent.agent", "heagent.cli", "heagent.network", "heagent.config"):
            assert f"from {forbidden}" not in source, forbidden
        assert "heagent.pub.persist" in source
