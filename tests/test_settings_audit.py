"""``cli/settings_audit.py`` 的判据（A62）：留痕落点、形状正确、**值不进审计**。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from click.testing import CliRunner

from heagent.cli import init as init_module
from heagent.cli.init import init_cmd
from heagent.cli.settings_audit import OPERATION_SETTINGS_WRITE, record_settings_write, snapshot_settings

if TYPE_CHECKING:
    from pathlib import Path


def _entries(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_snapshot_of_missing_file_stays_comparable(tmp_path: Path) -> None:
    snap = snapshot_settings(tmp_path / "setting.md")
    assert snap["bytes"] == 0
    assert snap["error"] == "FileNotFoundError"


def test_record_settings_write_lands_in_target_parent_audit(tmp_path: Path) -> None:
    target = tmp_path / "setting.md"
    before = snapshot_settings(target)
    target.write_text("## 密钥\n\nDEEPSEEK_API_KEY: sk-secret\n", encoding="utf-8")

    assert record_settings_write(target=target, before=before) is True

    audit = tmp_path / "audit" / "tool-audit.jsonl"
    assert audit.is_file()
    entry = _entries(audit)[-1]
    assert entry["operation"] == OPERATION_SETTINGS_WRITE
    assert entry["target"] == str(target)
    assert entry["before"] == {"bytes": 0, "error": "FileNotFoundError"}
    assert isinstance(entry["after"], dict) and entry["after"]["bytes"] > 0
    # 摘要口径：整行不得出现配置值明文
    assert "sk-secret" not in audit.read_text(encoding="utf-8")


def test_init_template_creation_is_audited(monkeypatch, tmp_path: Path) -> None:
    """`heagent init`（非交互）建 setting.md 模板时留一条 settings.write。"""
    config_dir = tmp_path / ".heagent"
    target = config_dir / "setting.md"
    monkeypatch.setattr(init_module, "GLOBAL_CONFIG_DIR", config_dir)
    monkeypatch.setattr(init_module, "GLOBAL_SETTING_FILE", target)
    monkeypatch.setattr(init_module, "LEGACY_GLOBAL_ENV_FILE", config_dir / ".env")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(init_cmd, [])
    assert result.exit_code == 0, result.output
    assert target.is_file()

    entry = _entries(config_dir / "audit" / "tool-audit.jsonl")[-1]
    assert entry["operation"] == OPERATION_SETTINGS_WRITE
    assert entry["target"] == str(target)
    assert entry["before"] == {"bytes": 0, "error": "FileNotFoundError"}
    assert isinstance(entry["after"], dict) and entry["after"]["bytes"] > 0
