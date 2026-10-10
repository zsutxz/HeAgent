"""用户级 ``setting.md`` 的读 / 写 / 渲染 / 迁移与源优先级（双层配置改造）。

优先级链用例同时是 ``Settings`` 接线的**蓝图**：接线后的真实 ``Settings`` 必须保持这里的
源元组顺序（init > 系统 env > 项目 .env > setting.md > 默认），顺序错位即「项目覆盖不了用户」
的静默反转——源序契约用例把它钉死。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest
from pydantic_settings import BaseSettings, SettingsConfigDict

from heagent.config.user_settings import (
    UserMarkdownSettingsSource,
    ensure_user_settings_migrated,
    read_setting_md,
    render_setting_md,
    with_user_setting_layer,
    write_setting_md,
)


def _write_md(path: Path, frontmatter: str, body: str = "") -> Path:
    text = f"---\n{frontmatter}\n---\n" + (f"\n{body}\n" if body else "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ── read_setting_md ──────────────────────────────────────────────


def test_read_parses_pairs_lowercases_keys_and_strips_values(tmp_path: Path) -> None:
    md = _write_md(tmp_path / "setting.md", "ACTIVE_PROVIDER:  glm \nMAX_ITERATIONS: 40")

    assert read_setting_md(md) == {"active_provider": "glm", "max_iterations": "40"}


def test_read_unwraps_paired_quotes_and_strips_inline_comments(tmp_path: Path) -> None:
    """值口径与 dotenv 同源（``envfile.parse_value``）：剥行内注释（引号感知）、剥成对引号。"""
    md = _write_md(
        tmp_path / "setting.md",
        "# 整行注释被跳过\nLOG_LEVEL: \"INFO\"  # 安静\nROUTING_POOLS: 'a,b'\nPLAIN_HASH: a#b",
    )

    assert read_setting_md(md) == {"log_level": "INFO", "routing_pools": "a,b", "plain_hash": "a#b"}


def test_read_tolerates_bom(tmp_path: Path) -> None:
    md = tmp_path / "setting.md"
    md.write_bytes("﻿".encode() + b"---\nLOG_LEVEL: INFO\n---\n")

    assert read_setting_md(md) == {"log_level": "INFO"}


@pytest.mark.parametrize(
    ("frontmatter", "fragments"),
    [
        ("A: 1\nA: 2", ["bad_key", "A"]),
        ("NO_COLON_LINE", ["无法解析", "NO_COLON_LINE"]),
    ],
)
def test_read_raises_on_strict_violations(tmp_path: Path, frontmatter: str, fragments: list[str]) -> None:
    from heagent.config.user_settings import SettingsError

    md = _write_md(tmp_path / "setting.md", frontmatter)

    with pytest.raises(SettingsError) as exc_info:
        read_setting_md(md)
    for fragment in fragments:
        assert fragment in str(exc_info.value)


def test_read_raises_when_content_has_no_frontmatter(tmp_path: Path) -> None:
    from heagent.config.user_settings import SettingsError

    md = tmp_path / "setting.md"
    md.write_text("KEY: value\n", encoding="utf-8")  # 没有 --- 围栏

    with pytest.raises(SettingsError, match="frontmatter"):
        read_setting_md(md)


@pytest.mark.parametrize("shape", ["missing", "empty"])
def test_read_returns_empty_for_missing_or_blank_file(tmp_path: Path, shape: str) -> None:
    md = tmp_path / "setting.md"
    if shape == "empty":
        md.write_text("", encoding="utf-8")

    assert read_setting_md(md) == {}


# ── render / write 与往返 ────────────────────────────────────────


@pytest.mark.parametrize(
    "pairs",
    [
        {"PLAIN": "value"},
        {"WITH_HASH": "a #b"},  # 严档不识别行内注释，值内 # 保真
        {"URL": "https://api.example.com/v1"},
        {"QUOTED": '"already"'},
        {"EMPTY": ""},
    ],
)
def test_render_round_trips_through_read(tmp_path: Path, pairs: dict[str, str]) -> None:
    md = tmp_path / "setting.md"
    write_setting_md(md, render_setting_md(pairs))

    assert read_setting_md(md) == {key.lower(): value for key, value in pairs.items()}


def test_render_empty_pairs_stays_parseable(tmp_path: Path) -> None:
    md = tmp_path / "setting.md"
    write_setting_md(md, render_setting_md({}))

    assert read_setting_md(md) == {}


def test_render_rejects_unrepresentable_values() -> None:
    from heagent.config.envfile import EnvWriteError
    from heagent.config.user_settings import SettingsError

    with pytest.raises(SettingsError, match="control character"):
        render_setting_md({"BAD": "a\nb"})
    with pytest.raises(SettingsError, match="whitespace"):
        render_setting_md({"BAD": " padded "})
    with pytest.raises(EnvWriteError, match="not a valid environment"):
        render_setting_md({"bad-key": "v"})


def test_render_quotes_values_that_parse_value_would_alter(tmp_path: Path) -> None:
    md = tmp_path / "setting.md"
    text = render_setting_md({"WITH_HASH": "a #b", "QUOTED": '"already"'})

    assert '"a #b"' in text and '""already""' in text
    write_setting_md(md, text)

    assert read_setting_md(md) == {"with_hash": "a #b", "quoted": '"already"'}


# ── 迁移：三态 + 双存在态 + 失败分支 ─────────────────────────────


def _write_env(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_migration_state_b_moves_env_renames_legacy_and_is_idempotent(tmp_path: Path) -> None:
    legacy = _write_env(
        tmp_path / ".env", ["# 注释", "GLM_API_KEY = glm-key", "LOG_LEVEL=INFO # 安静", "DUP=1", "DUP=2"]
    )
    setting = tmp_path / "setting.md"

    assert ensure_user_settings_migrated(setting) is True
    assert setting.is_file()
    assert read_setting_md(setting) == {"glm_api_key": "glm-key", "log_level": "INFO", "dup": "2"}  # 后者胜
    assert not legacy.exists()
    migrated = tmp_path / ".env.migrated"
    assert migrated.is_file() and "GLM_API_KEY" in migrated.read_text(encoding="utf-8")
    assert "自动迁移" in setting.read_text(encoding="utf-8")

    assert ensure_user_settings_migrated(setting) is False  # 幂等


def test_migration_state_a_leaves_md_alone(tmp_path: Path) -> None:
    setting = _write_md(tmp_path / "setting.md", "LOG_LEVEL: DEBUG")

    assert ensure_user_settings_migrated(setting) is False
    assert read_setting_md(setting) == {"log_level": "DEBUG"}


def test_migration_dual_existence_archives_legacy_without_touching_md(tmp_path: Path) -> None:
    setting = _write_md(tmp_path / "setting.md", "LOG_LEVEL: DEBUG")
    legacy = _write_env(tmp_path / ".env", ["LOG_LEVEL=TRACE"])

    assert ensure_user_settings_migrated(setting) is False  # md 胜，返回值只认「是否迁移」
    assert not legacy.exists()
    assert (tmp_path / ".env.migrated").is_file()
    assert read_setting_md(setting) == {"log_level": "DEBUG"}


def test_migration_state_c_is_a_noop(tmp_path: Path) -> None:
    assert ensure_user_settings_migrated(tmp_path / "setting.md") is False


def test_migration_write_failure_raises_settings_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_env(tmp_path / ".env", ["LOG_LEVEL=INFO"])
    import heagent.config.user_settings as user_settings

    def broken(path: Path, data: bytes) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(user_settings, "atomic_write_bytes", broken)

    with pytest.raises(user_settings.SettingsError, match="disk full"):
        ensure_user_settings_migrated(tmp_path / "setting.md")


def test_migration_rename_failure_still_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy = _write_env(tmp_path / ".env", ["LOG_LEVEL=INFO"])
    import os

    def locked(src: Any, dst: Any) -> None:
        raise PermissionError(13, "file in use")

    monkeypatch.setattr(os, "rename", locked)
    setting = tmp_path / "setting.md"

    assert ensure_user_settings_migrated(setting) is True  # md 已落盘 = 实质完成
    assert read_setting_md(setting) == {"log_level": "INFO"}
    assert legacy.exists()  # 残留旧文件不在任何源里，无害


def test_migration_rename_target_already_taken_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    def taken(src: Any, dst: Any) -> None:
        raise FileExistsError()

    monkeypatch.setattr(os, "rename", taken)
    setting = tmp_path / "setting.md"

    assert ensure_user_settings_migrated(setting, legacy_env_file=_write_env(tmp_path / ".env", ["K=v"])) is True


# ── 源优先级链（接线蓝图）与源序契约 ─────────────────────────────


class _DemoSettings(BaseSettings):
    """``Settings`` 接线的最小镜像：md 源插在 dotenv 之后——顺序错位即优先级反转。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    _user_setting_file: ClassVar[Path | None] = None
    openai_api_key: str | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            UserMarkdownSettingsSource(settings_cls, setting_file=cls._user_setting_file),
            file_secret_settings,
        )


def test_source_order_puts_md_source_after_dotenv() -> None:
    sources = _DemoSettings.settings_customise_sources(_DemoSettings, None, None, None, None)

    assert isinstance(sources[3], UserMarkdownSettingsSource)
    assert sources[3]._setting_file is None  # _DemoSettings 默认禁用 md 层


def test_layer_factory_injects_path_and_memoizes(tmp_path: Path) -> None:
    first = with_user_setting_layer(tmp_path / "setting.md", _DemoSettings)
    again = with_user_setting_layer(tmp_path / "setting.md", _DemoSettings)
    other = with_user_setting_layer(tmp_path / "elsewhere.md", _DemoSettings)

    assert first is again
    assert first is not other
    assert first is not _DemoSettings
    assert first._user_setting_file == tmp_path / "setting.md"


def test_priority_chain_system_env_over_project_env_over_md_over_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    setting = _write_md(tmp_path / "setting.md", "OPENAI_API_KEY: from-md")
    project = _write_env(tmp_path / "project.env", ["OPENAI_API_KEY=from-project"])
    layer = with_user_setting_layer(setting, _DemoSettings)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    md_only = layer(_env_file=str(tmp_path / "absent.env"))
    assert md_only.openai_api_key == "from-md"

    with_project = layer(_env_file=str(project))
    assert with_project.openai_api_key == "from-project"

    monkeypatch.setenv("OPENAI_API_KEY", "from-system")
    assert layer(_env_file=str(project)).openai_api_key == "from-system"

    monkeypatch.delenv("OPENAI_API_KEY")
    default_only = with_user_setting_layer(tmp_path / "absent.md", _DemoSettings)(_env_file=str(project))
    assert default_only.openai_api_key == "from-project"  # md 层缺席不碍项目层

    bare = with_user_setting_layer(None, _DemoSettings)(_env_file=str(tmp_path / "absent.env"))
    assert bare.openai_api_key is None
