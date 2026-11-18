"""Story 67.4 密钥轮换提醒的判据。

覆盖：首次观测即落盘且第二次启动不重置 ``first_seen``、超期报告名字与天数、``0`` 关闭、
状态文件只含密钥名不含明文、损坏文件降级、housekeeping 层的 WARNING 与「绝不阻断启动」。
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pytest

from heagent import housekeeping as hk
from heagent.config import Settings
from heagent.config import rotation as rot

#: 明文密钥哨兵：状态文件与任何日志里都不允许出现它。
SECRET = "sk-rotation-must-never-be-recorded-0123456789"

_API_KEY_ENV_VARS = (
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_API_KEYS",
    "KIMI_API_KEY",
    "GLM_API_KEY",
    "OPENAI_RESPONSES_API_KEY",
    "OLLAMA_API_KEY",
)


@pytest.fixture(autouse=True)
def _seal_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """抹掉宿主环境里的真实 API key：观测名单只由用例显式给出的字段决定。"""
    for name in _API_KEY_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def _state_file(root: Path) -> Path:
    return root / ".heagent" / rot.ROTATION_FILE_NAME


def _seed(root: Path, first_seen: dict[str, str]) -> Path:
    path = _state_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "first_seen": first_seen}), encoding="utf-8")
    return path


class TestObserve:
    def test_first_observation_is_recorded_once(self, tmp_path: Path) -> None:
        state = tmp_path / ".heagent"
        today = date(2026, 1, 1)

        first = rot.observe(("DEEPSEEK_API_KEY",), state_root=state, remind_days=90, today=today)
        assert first.recorded == ("DEEPSEEK_API_KEY",)
        assert first.overdue == ()
        payload = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
        assert payload["first_seen"] == {"DEEPSEEK_API_KEY": "2026-01-01"}

        # 第二次启动（晚了 60 天）不改写既有记录 —— 轮换计时不由启动期重算。
        second = rot.observe(("DEEPSEEK_API_KEY",), state_root=state, remind_days=90, today=date(2026, 3, 2))
        assert second.recorded == ()
        assert json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))["first_seen"] == {
            "DEEPSEEK_API_KEY": "2026-01-01"
        }

    def test_overdue_key_is_reported_with_age(self, tmp_path: Path) -> None:
        _seed(tmp_path, {"KIMI_API_KEY": "2026-01-01"})
        report = rot.observe(
            ("KIMI_API_KEY",), state_root=tmp_path / ".heagent", remind_days=90, today=date(2026, 4, 11)
        )
        assert [entry.name for entry in report.overdue] == ["KIMI_API_KEY"]
        assert report.overdue[0].age_days == 100
        assert report.overdue[0].first_seen == date(2026, 1, 1)

    def test_recent_key_is_not_reported(self, tmp_path: Path) -> None:
        _seed(tmp_path, {"KIMI_API_KEY": "2026-01-01"})
        report = rot.observe(
            ("KIMI_API_KEY",), state_root=tmp_path / ".heagent", remind_days=90, today=date(2026, 2, 1)
        )
        assert report.overdue == ()

    def test_new_key_is_never_overdue_on_first_sight(self, tmp_path: Path) -> None:
        report = rot.observe(("GLM_API_KEY",), state_root=tmp_path / ".heagent", remind_days=1, today=date(2026, 1, 1))
        assert report.recorded == ("GLM_API_KEY",)
        assert report.overdue == ()

    def test_zero_days_disables_recording_and_reporting(self, tmp_path: Path) -> None:
        report = rot.observe(("KIMI_API_KEY",), state_root=tmp_path / ".heagent", remind_days=0, today=date(2026, 1, 1))
        assert report.disabled is True
        assert report.recorded == ()
        assert report.overdue == ()
        assert not _state_file(tmp_path).exists()

    def test_state_file_holds_names_only_never_values(self, tmp_path: Path) -> None:
        settings = _settings(deepseek_api_key=SECRET)
        names = rot.secret_names(settings)
        assert names == ("DEEPSEEK_API_KEY",)

        rot.observe(names, state_root=tmp_path / ".heagent", remind_days=90, today=date(2026, 1, 1))
        text = _state_file(tmp_path).read_text(encoding="utf-8")
        assert "DEEPSEEK_API_KEY" in text
        assert SECRET not in text

    def test_corrupt_state_file_starts_a_fresh_record(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        path = _state_file(tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{ not json", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="heagent.config.rotation"):
            report = rot.observe(
                ("KIMI_API_KEY",), state_root=tmp_path / ".heagent", remind_days=90, today=date(2026, 1, 1)
            )
        assert report.recorded == ("KIMI_API_KEY",)
        assert "unreadable" in caplog.text
        assert json.loads(path.read_text(encoding="utf-8"))["first_seen"] == {"KIMI_API_KEY": "2026-01-01"}

    def test_malformed_single_entry_does_not_wipe_the_rest(self, tmp_path: Path) -> None:
        _seed(tmp_path, {"KIMI_API_KEY": "not-a-date", "GLM_API_KEY": "2026-01-01"})
        report = rot.observe((), state_root=tmp_path / ".heagent", remind_days=90, today=date(2026, 4, 11))
        assert [entry.name for entry in report.overdue] == ["GLM_API_KEY"]


class TestSecretNames:
    def test_empty_settings_yield_no_names(self, tmp_path: Path) -> None:
        assert rot.secret_names(_settings()) == ()

    def test_multi_key_pool_counts_as_one_name(self) -> None:
        names = rot.secret_names(_settings(anthropic_api_keys="key1,key2"))
        assert names == ("ANTHROPIC_API_KEYS",)

    def test_every_configured_key_field_is_tracked(self) -> None:
        names = rot.secret_names(
            _settings(
                deepseek_api_key="sk-ds",
                kimi_api_key="sk-kimi",
                glm_api_key="sk-glm",
                openai_responses_api_key="sk-resp",
                anthropic_api_key="sk-ant",
            )
        )
        assert set(names) == {
            "DEEPSEEK_API_KEY",
            "KIMI_API_KEY",
            "GLM_API_KEY",
            "OPENAI_RESPONSES_API_KEY",
            "ANTHROPIC_API_KEY",
        }


class TestHousekeepingWiring:
    def test_overdue_key_logs_warning_with_name_and_days(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        old = date(2026, 1, 1)
        _seed(tmp_path, {"DEEPSEEK_API_KEY": old.isoformat()})
        settings = _settings(deepseek_api_key=SECRET)

        with caplog.at_level(logging.WARNING, logger="heagent.housekeeping"):
            report = hk.report_key_rotation(settings, workspace=tmp_path, today=date(2026, 4, 11))

        assert [entry.name for entry in report.overdue] == ["DEEPSEEK_API_KEY"]
        assert "DEEPSEEK_API_KEY" in caplog.text
        assert "100 days" in caplog.text
        assert "Rotate the credential" in caplog.text
        assert SECRET not in caplog.text  # 提醒里只有名字，没有值

    def test_reminder_disabled_by_zero_does_not_touch_state(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _seed(tmp_path, {"DEEPSEEK_API_KEY": (date(2026, 1, 1)).isoformat()})
        settings = _settings(deepseek_api_key=SECRET, key_rotation_remind_days=0)

        with caplog.at_level(logging.WARNING, logger="heagent.housekeeping"):
            report = hk.report_key_rotation(settings, workspace=tmp_path, today=date(2026, 4, 11))

        assert report.disabled is True
        assert caplog.text == ""

    def test_no_configured_key_means_no_state_file(self, tmp_path: Path) -> None:
        report = hk.report_key_rotation(_settings(), workspace=tmp_path)
        assert report.recorded == ()
        assert not _state_file(tmp_path).exists()

    def test_failure_never_blocks_startup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """轮换提醒是维护动作：内部异常只记 warning，启动流程照旧返回。"""

        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("state root is read-only")

        monkeypatch.setattr(hk, "observe", _boom)
        hk.prune_runtime_artifacts_best_effort(_settings(deepseek_api_key=SECRET), workspace=tmp_path)

    def test_startup_path_records_first_seen(self, tmp_path: Path) -> None:
        settings = _settings(kimi_api_key="sk-kimi")
        hk.prune_runtime_artifacts_best_effort(settings, workspace=tmp_path)
        payload = json.loads(_state_file(tmp_path).read_text(encoding="utf-8"))
        assert payload["first_seen"] == {"KIMI_API_KEY": date.today().isoformat()}


class TestReminderThreshold:
    def test_threshold_comes_from_settings(self, tmp_path: Path) -> None:
        today = date(2026, 1, 1) + timedelta(days=30)
        _seed(tmp_path, {"GLM_API_KEY": "2026-01-01"})
        settings = _settings(glm_api_key="sk-glm", key_rotation_remind_days=30)
        report = hk.report_key_rotation(settings, workspace=tmp_path, today=today)
        assert [entry.name for entry in report.overdue] == ["GLM_API_KEY"]

    def test_default_threshold_is_90_days(self) -> None:
        assert Settings.model_fields["key_rotation_remind_days"].get_default(call_default_factory=True) == 90
