"""``heagent init --interactive`` 的判据。

四组：覆盖率口径（分子 / 分母都能从代码里读出）、提问与写入（含隐藏输入、非法输入重问）、
合并保真（注释 / 正文 / 行尾不破）、以及两条硬边界（非 tty 拒绝、验证失败不写盘）。
最后一组钉住「既有 ``heagent init``（无 ``--interactive``）行为逐字不变」。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from click import ClickException
from click.testing import CliRunner
from pydantic import ValidationError

from heagent.cli import init as init_module
from heagent.cli import wizard as wz
from heagent.cli.init import _INIT_SETTING_TEMPLATE, init_cmd
from heagent.config import Settings
from heagent.config.catalog import UNKNOWN_GROUP, classify
from heagent.config.user_settings import read_setting_md, with_user_setting_layer

if TYPE_CHECKING:
    from pathlib import Path

#: 一次「正常走通」的输入：按 ``WIZARD_ITEMS`` 顺序逐项作答。
WALKTHROUGH: tuple[str, ...] = (
    "sk-deepseek-test",  # DEEPSEEK_API_KEY（隐藏输入）
    "",  # OPENAI_RESPONSES_API_KEY 留空 = 不改动
    "deepseek",  # ACTIVE_PROVIDER（字段默认未设置 ⇒ 会写入）
    "",  # DEFAULT_MODEL 回车 = 推荐值（= 当前生效值 ⇒ 不写入）
    "",  # DEEPSEEK_MODEL
    "",  # OLLAMA_ENABLED 回车 = false（= 当前值）
    "",  # OLLAMA_MODEL
    "",  # ROUTING_POOLS
    "80",  # MAX_ITERATIONS
    "",  # MAX_OUTPUT_TOKENS 推荐值为空 ⇒ 不设置
    "200000",  # MAX_CONTEXT_TOKENS
    "0.75",  # COMPRESSION_THRESHOLD
    "compressor",  # CONTEXT_STRATEGY 与字段默认相同 ⇒ 不写入
    "auto",  # TOKENIZER 同上
    "",  # CONTEXT_FILES_ENABLED
    "65536",  # CONTEXT_FILES_MAX_BYTES
    "",  # MEMORY_NUDGE_ENABLED
    "0.4",  # SKILL_MATCH_THRESHOLD
    "debug",  # LOG_LEVEL（Choice 不区分大小写 ⇒ 归一成 DEBUG）
)

#: 上面输入里预期**不**写入的键（值与当前生效值相同）。
EXPECTED_UNCHANGED = frozenset({"OPENAI_RESPONSES_API_KEY", "DEFAULT_MODEL", "DEEPSEEK_MODEL", "CONTEXT_STRATEGY"})


def _input(*answers: str) -> str:
    return "\n".join(answers) + "\n"


def _seal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """把 init 的落点（全局目录 / setting.md / legacy .env）与 cwd 全部指向 tmp。"""
    config_dir = tmp_path / ".heagent"
    target = config_dir / "setting.md"
    monkeypatch.setattr(init_module, "GLOBAL_CONFIG_DIR", config_dir)
    monkeypatch.setattr(init_module, "GLOBAL_SETTING_FILE", target)
    monkeypatch.setattr(init_module, "LEGACY_GLOBAL_ENV_FILE", config_dir / ".env")
    monkeypatch.chdir(tmp_path)
    return target


@pytest.fixture()
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """密封 home 的 fixture：返回本次运行的 setting.md 路径（此时还不存在）。"""
    return _seal(monkeypatch, tmp_path)


def _run_cli(answers: str, *, args: tuple[str, ...] = ("--interactive",)) -> object:
    return CliRunner().invoke(init_cmd, list(args), input=answers)


def _settings_from(path: Path) -> Settings:
    return with_user_setting_layer(path, Settings)(_env_file=None)  # type: ignore[call-arg]


class TestCoverageAccounting:
    """「覆盖 >80% 常用配置项」的分母 / 分子都在代码里，且都能被反查。"""

    def test_common_keys_are_catalog_known_and_bounded(self) -> None:
        assert 15 <= len(wz.COMMON_KEYS) <= 20, "常用配置项清单的规模约定是 15–20 项"
        unknown = [key for key in wz.COMMON_KEYS if key in {""}]
        assert unknown == []
        unclassified = [key for key in wz.COMMON_KEYS if classify(key).group == UNKNOWN_GROUP.id]
        assert unclassified == [], f"这些键无法被 config.catalog 分类：{unclassified}"

    def test_common_keys_are_real_settings_fields(self) -> None:
        fields = {name.upper() for name in Settings.model_fields}
        missing = [key for key in wz.COMMON_KEYS if key not in fields]
        assert missing == [], f"常用项里有 Settings 不认识的键：{missing}"

    def test_wizard_items_are_unique_and_mapped_to_fields(self) -> None:
        keys = [item.key for item in wz.WIZARD_ITEMS]
        assert len(keys) == len(set(keys)), "向导项重复会让同一键被问两次"
        fields = {name.upper() for name in Settings.model_fields}
        assert [key for key in keys if key not in fields] == []

    def test_coverage_meets_the_ticket_floor(self) -> None:
        covered = wz.covered_keys()
        common = frozenset(wz.COMMON_KEYS)
        numerator, denominator = len(covered & common), len(common)
        assert denominator == len(wz.COMMON_KEYS)
        assert numerator / denominator >= wz.MIN_COVERAGE, f"{numerator}/{denominator} 未达 {wz.MIN_COVERAGE}"
        assert wz.coverage() == numerator / denominator
        # 票面要「>80%」，实装是全覆盖——差集必须为空，否则分母里有一项没人问过。
        assert common - covered == set()

    def test_recommendation_falls_back_to_the_field_default(self) -> None:
        items = {item.key: item for item in wz.WIZARD_ITEMS}
        assert wz._recommend(items["MAX_ITERATIONS"]) == str(Settings.model_fields["max_iterations"].default)
        # 显式覆盖的推荐值（字段默认 None 不是推荐起点）
        assert wz._recommend(items["MAX_OUTPUT_TOKENS"]) == ""
        assert items["MAX_OUTPUT_TOKENS"].recommend is not None

    def test_secrets_are_the_only_hidden_inputs(self) -> None:
        secret_keys = {item.key for item in wz.WIZARD_ITEMS if item.kind is wz.WizardKind.SECRET}
        assert secret_keys == {"DEEPSEEK_API_KEY", "OPENAI_RESPONSES_API_KEY"}


class TestWalkthrough:
    """完整走通一遍：写入、隐藏输入、推荐值展示、生成文件可被 Settings 解析。"""

    def test_writes_only_the_answered_values(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        result = _run_cli(_input(*WALKTHROUGH))

        assert result.exit_code == 0, result.output
        text = home.read_text(encoding="utf-8")
        assert "DEEPSEEK_API_KEY: sk-deepseek-test" in text
        assert "ACTIVE_PROVIDER: deepseek" in text
        assert "MAX_ITERATIONS: 80" in text
        assert "LOG_LEVEL: DEBUG" in text  # Choice 不区分大小写 ⇒ 归一
        assert "MAX_CONTEXT_TOKENS: 200000" in text
        assert "COMPRESSION_THRESHOLD: 0.75" in text
        # 与当前生效值相同的项不写入：不把字段默认值固化成快照
        assert "CONTEXT_STRATEGY" not in text
        assert "TOKENIZER" not in text
        assert "OPENAI_RESPONSES_API_KEY" not in text

    def test_generated_file_is_parseable_by_settings(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        assert _run_cli(_input(*WALKTHROUGH)).exit_code == 0

        parsed = read_setting_md(home)
        assert parsed["max_iterations"] == "80"
        assert parsed["log_level"] == "DEBUG"
        settings = _settings_from(home)
        assert settings.max_iterations == 80
        assert settings.compression_threshold == 0.75
        assert settings.deepseek_api_key == "sk-deepseek-test"

    def test_new_file_carries_the_priority_invariant_header(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        assert _run_cli(_input(*WALKTHROUGH)).exit_code == 0
        text = home.read_text(encoding="utf-8")
        assert "加载优先级：系统环境变量 > 项目 .env > 本文件 > 字段默认值" in text
        assert text.startswith("---\n")
        assert text.endswith("\n")

    def test_secret_input_is_not_echoed(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        result = _run_cli(_input(*WALKTHROUGH))
        assert "sk-deepseek-test" not in result.output
        assert "sk-deepseek-test" not in (result.stderr or "")
        assert "DEEPSEEK_API_KEY: ***" in result.output
        # 隐藏输入仍然真的写进去了
        assert "sk-deepseek-test" in home.read_text(encoding="utf-8")

    def test_each_item_shows_help_current_and_recommendation(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        result = _run_cli(_input(*WALKTHROUGH))
        output = result.output
        total = len(wz.WIZARD_ITEMS)
        for position, item in enumerate(wz.WIZARD_ITEMS, start=1):
            assert f"[{position}/{total}] {item.key} — {item.label}" in output
        assert output.count("说明:") == total
        assert output.count("推荐:") == total
        # 默认值来源要写明（初次运行全部来自字段默认值）
        assert "（来源: 字段默认值）" in output
        assert "（字段默认值）" in output  # 推荐值的来源标签

    def test_result_model_reports_written_and_unchanged(
        self, home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        with CliRunner().isolation(input=_input(*WALKTHROUGH)):
            result = wz.run_wizard(setting_file=home, project_env_file=tmp_path / "absent.env")
        assert result.verified is True
        assert "MAX_ITERATIONS" in result.written
        assert "CONTEXT_STRATEGY" in result.unchanged
        assert set(result.written) & EXPECTED_UNCHANGED == set()
        assert result.path == str(home)

    def test_no_changes_leaves_the_file_alone(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        result = _run_cli(_input(*("" for _ in wz.WIZARD_ITEMS)))
        assert result.exit_code == 0
        assert "没有需要写入的变更" in result.output
        assert not home.exists()

    def test_invalid_number_is_asked_again(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        answers = list(WALKTHROUGH)
        answers[8] = "abc"  # MAX_ITERATIONS 先给个非数字
        answers.insert(9, "80")  # 重问时补一个合法值（其余答案随之后移一位）
        result = _run_cli(_input(*answers))
        assert result.exit_code == 0
        assert "MAX_ITERATIONS 需要一个数字" in (result.stderr or "")
        assert "MAX_ITERATIONS: 80" in home.read_text(encoding="utf-8")

    def test_out_of_range_value_is_asked_again(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        answers = list(WALKTHROUGH)
        answers[11] = "1.5"  # COMPRESSION_THRESHOLD 上界 1
        answers.insert(12, "0.75")  # 重问时补一个合法值
        result = _run_cli(_input(*answers))
        assert result.exit_code == 0
        assert "COMPRESSION_THRESHOLD 需不大于 1" in (result.stderr or "")


class TestExistingFileIsPreserved:
    """合并只改命中行：整行注释、行内注释、正文、未涉及的键、行尾风格一律保留。"""

    def test_comments_and_body_survive(self, home: Path) -> None:
        home.parent.mkdir(parents=True, exist_ok=True)
        home.write_text(
            "---\n"
            "# 手工注释：别动我\n"
            "MAX_ITERATIONS: 10\n"
            "LOG_LEVEL: WARNING  # 运维临时调高\n"
            "---\n"
            "\n"
            "## 我的笔记\n"
            "\n"
            "这段正文必须原样保留。\n",
            encoding="utf-8",
        )
        answers = {
            "MAX_ITERATIONS": "80",
            "LOG_LEVEL": "DEBUG",
            "OLLAMA_MODEL": "qwen3.5-9b-local:latest",
        }
        merged = wz._merge_text(home.read_text(encoding="utf-8"), answers)
        assert "# 手工注释：别动我" in merged
        assert "MAX_ITERATIONS: 80" in merged
        assert "LOG_LEVEL: DEBUG  # 运维临时调高" in merged  # 行内注释保留
        assert "OLLAMA_MODEL: qwen3.5-9b-local:latest" in merged  # 新键追加在闭合 --- 之前
        assert "这段正文必须原样保留。" in merged
        assert merged.endswith("\n")

    def test_crlf_line_endings_are_kept(self, home: Path) -> None:
        home.parent.mkdir(parents=True, exist_ok=True)
        home.write_bytes(b"---\r\nMAX_ITERATIONS: 10\r\n---\r\n\r\nbody\r\n")
        # 按字节读（read_text 会做通用换行翻译，CRLF 就看不出来了）
        merged = wz._merge_text(home.read_bytes().decode("utf-8"), {"MAX_ITERATIONS": "80", "LOG_LEVEL": "DEBUG"})
        assert "MAX_ITERATIONS: 80\r" in merged
        assert "LOG_LEVEL: DEBUG\r" in merged
        assert merged.count("\r\n") >= 4

    def test_quoted_value_is_rendered_so_it_round_trips(self, home: Path) -> None:
        rendered = wz._render_value("ROUTING_POOLS", "x # not-a-comment")
        assert rendered.startswith('"') and rendered.endswith('"')
        merged = wz._merge_text("---\n---\n", {"ROUTING_POOLS": "x # not-a-comment"})
        assert merged.count('ROUTING_POOLS: "x # not-a-comment"') == 1

    def test_file_without_frontmatter_is_refused(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home.parent.mkdir(parents=True, exist_ok=True)
        home.write_text("no frontmatter here\n", encoding="utf-8")
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        result = _run_cli(_input(*WALKTHROUGH))
        assert result.exit_code == 1
        assert "无法解析" in (result.stderr or "")
        assert home.read_text(encoding="utf-8") == "no frontmatter here\n"  # 用户的坏文件不被动


class TestNonTtyIsRefused:
    """管道 / CI 里没有交互终端时必须显性失败，且绝不写盘。"""

    def test_piped_stdin_is_refused_with_actions(self, home: Path) -> None:
        result = _run_cli(_input(*WALKTHROUGH))
        assert result.exit_code == 1
        assert not home.exists()
        # 终端能力先判：拒绝路径不该顺手建目录（也谈不上迁移旧文件）
        assert not home.parent.exists()
        message = result.stderr or ""
        assert "需要可交互终端" in message
        assert "Try:" in message
        assert "Docs:" in message
        assert "编辑 ~/.heagent/setting.md" in message

    def test_gate_helper_exits_with_hints(self) -> None:
        with pytest.raises(ClickException) as excinfo:
            wz.require_interactive_terminal()
        message = str(excinfo.value)
        assert "需要可交互终端" in message
        assert "Try:" in message and "Docs:" in message

    def test_gate_helper_passes_on_a_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        assert wz.require_interactive_terminal() is None

    def test_stdin_without_isatty_counts_as_non_tty(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        class _NoIsatty:
            pass

        # 被替换掉的 stdin 可能连 isatty 都没有：按「非 tty」处理，不得抛 AttributeError。
        monkeypatch.setattr(wz.sys, "stdin", _NoIsatty())
        with pytest.raises(wz.WizardError) as excinfo:
            wz._run_wizard(target=tmp_path / "setting.md", project_env=tmp_path / "none.env")
        assert "需要可交互终端" in str(excinfo.value)
        assert len(excinfo.value.options) >= 2


class TestVerificationGate:
    """验证不过就不写盘；写盘后读回不一致也要显性报错。"""

    def test_invalid_value_never_reaches_the_file(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(wz.WizardError) as excinfo:
            wz._verify_candidate(
                "---\nMAX_ITERATIONS: abc\n---\n",
                intended={"MAX_ITERATIONS": "abc"},
                target=home,
                project_env=home.parent / "absent.env",
            )
        assert "无法构造 Settings" in str(excinfo.value)
        assert not home.exists()

    def test_key_outside_the_config_catalog_is_rejected(self, home: Path) -> None:
        with pytest.raises(wz.WizardError) as excinfo:
            wz._verify_candidate(
                "---\nNOT_A_SETTING: x\n---\n",
                intended={"NOT_A_SETTING": "x"},
                target=home,
                project_env=home.parent / "absent.env",
            )
        assert "配置目录之外的键" in str(excinfo.value)

    def test_failed_verification_keeps_the_existing_file(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home.parent.mkdir(parents=True, exist_ok=True)
        home.write_text("---\nMAX_ITERATIONS: 10\n---\n", encoding="utf-8")
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise wz.WizardError("候选内容未通过验证", options=("修好配置后重试",))

        monkeypatch.setattr(wz, "_verify_candidate", _boom)
        result = _run_cli(_input(*WALKTHROUGH))
        assert result.exit_code == 1
        assert "候选内容未通过验证" in (result.stderr or "")
        assert home.read_text(encoding="utf-8") == "---\nMAX_ITERATIONS: 10\n---\n"

    def test_write_back_mismatch_is_reported(self, home: Path) -> None:
        home.parent.mkdir(parents=True, exist_ok=True)
        home.write_text("---\nMAX_ITERATIONS: 10\n---\n", encoding="utf-8")
        with pytest.raises(wz.WizardError) as excinfo:
            wz._verify_written(home, {"MAX_ITERATIONS": "80"})
        assert "读回不一致" in str(excinfo.value)


class TestSystemEnvironmentWins:
    """系统环境变量优先：写入本文件不会生效 ⇒ 跳过该键并明说。"""

    def test_key_provided_by_env_is_skipped(self, home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("MAX_ITERATIONS", "77")
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        answers = list(WALKTHROUGH)
        answers[8] = ""  # MAX_ITERATIONS 会被跳过，这里的输入不会被消费
        with CliRunner().isolation(input=_input(*answers)):
            result = wz.run_wizard(setting_file=home, project_env_file=tmp_path / "absent.env")
        assert "MAX_ITERATIONS" in result.system_env
        assert "MAX_ITERATIONS" not in result.written
        assert "MAX_ITERATIONS" not in home.read_text(encoding="utf-8")


class TestMigrationPrecedesTheWizard:
    """旧 ``~/.heagent/.env`` 先迁进 setting.md，再由向导合并（不丢既有值）。"""

    def test_legacy_env_is_migrated_first(self, home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home.parent.mkdir(parents=True, exist_ok=True)
        (home.parent / ".env").write_text("MAX_ITERATIONS=13\n", encoding="utf-8")
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        result = _run_cli(_input(*WALKTHROUGH))
        assert result.exit_code == 0
        assert "Migrated legacy" in result.output
        assert (home.parent / ".env.migrated").exists()
        assert read_setting_md(home)["max_iterations"] == "80"


class TestNonInteractiveInitIsUnchanged:
    """``heagent init``（无 ``--interactive``）逐字不变。"""

    def test_creates_the_template_verbatim(self, home: Path) -> None:
        result = _run_cli("", args=())
        assert result.exit_code == 0
        assert home.read_text(encoding="utf-8") == _INIT_SETTING_TEMPLATE
        assert "[OK] Created settings template" in result.output

    def test_second_run_does_not_overwrite(self, home: Path) -> None:
        assert _run_cli("", args=()).exit_code == 0
        result = _run_cli("", args=())
        assert result.exit_code == 0
        assert "Already exists" in result.output
        assert home.read_text(encoding="utf-8") == _INIT_SETTING_TEMPLATE

    def test_project_flag_still_creates_context(self, home: Path, tmp_path: Path) -> None:
        result = _run_cli("", args=("--project",))
        assert result.exit_code == 0
        assert (tmp_path / ".heagent" / "CONTEXT.md").exists()

    def test_interactive_project_flag_creates_context(
        self, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(wz, "_stdin_is_tty", lambda: True)
        result = _run_cli(_input(*WALKTHROUGH), args=("--interactive", "--project"))
        assert result.exit_code == 0
        assert (tmp_path / ".heagent" / "CONTEXT.md").exists()
        assert home.exists()

    def test_help_lists_the_interactive_flag(self) -> None:
        result = CliRunner().invoke(init_cmd, ["--help"])
        assert result.exit_code == 0
        assert "--interactive" in result.output


class TestModelFieldValidation:
    """写进文件的取值必须能被 ``Settings`` 的字段约束接受（防线在验证门而非 prompt）。"""

    def test_bool_fields_render_as_lowercase(self) -> None:
        item = next(entry for entry in wz.WIZARD_ITEMS if entry.key == "OLLAMA_ENABLED")
        assert wz._normalize(item, True, None) == "true"
        assert wz._normalize(item, False, None) == "false"

    def test_secret_value_with_control_character_is_refused(self) -> None:
        with pytest.raises(wz.WizardError):
            wz._render_value("DEEPSEEK_API_KEY", "sk-abc\ndef")

    def test_unrepresentable_value_is_refused(self) -> None:
        # 首尾都是引号且中间带 `` #``：裸写会被读侧当成行内注释截断，外包一层引号也救不回来。
        with pytest.raises(wz.WizardError):
            wz._render_value("DEEPSEEK_API_KEY", '"a # b"')

    def test_settings_rejects_a_value_the_wizard_would_never_write(self, tmp_path: Path) -> None:
        """反面对照：放开校验的坏值确实会被 pydantic 拒绝（证明验证门不是空的）。"""
        bad = tmp_path / "bad.md"
        bad.write_text("---\nMAX_ITERATIONS: abc\n---\n", encoding="utf-8")
        with pytest.raises(ValidationError):
            _settings_from(bad)
