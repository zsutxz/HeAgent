"""cron 结果的两条投递支路 + 装配判据（Epic 58 story 58-2）。

覆盖 D4 的「两个开关互相独立」四组合、D6 的终端回显形态，以及装配层的两条判据：

- ``CRON_PUSH_ENABLED=true`` ⇒ ``build_ws_servers`` 在**每个** listener 上挂同一份中枢，
  且 ``/api/notifications/ws`` 真的进了路由表；
- 关 ⇒ 无中枢、路由不注册（客户端拿 403，而不是「连上但永远没帧」的假可用）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

from heagent.cli.display import CRON_ECHO_MAX_CHARS, echo_cron_result
from heagent.cli.interactive import _build_cron_notifier
from heagent.config import Settings, reset_settings, resolve_runtime_config
from heagent.network.http_protocol import CronResultStatus
from heagent.network.notification_hub import NotificationHub
from heagent.network.ws_host import NOTIFICATIONS_WS_PATH

if TYPE_CHECKING:
    from pathlib import Path

JOB_ID = "1661798f"


@pytest.fixture(autouse=True)
def _reset_settings_singleton():
    reset_settings()
    yield
    reset_settings()


class _Service:
    """``EmbeddedHttpService`` 的最小替身：只暴露 notifier 需要的那个属性。"""

    def __init__(self, hub: Any | None = None) -> None:
        self.notification_hub = hub


def _config(**overrides: Any) -> Any:
    """按显式字段解析一份运行时快照（不读项目 .env 里的真实取值）。"""
    base: dict[str, Any] = {"cron_push_enabled": False, "cron_echo_to_terminal": False}
    base.update(overrides)
    return resolve_runtime_config(Settings(**base))


class TestEchoCronResult:
    def test_completed_line_goes_to_stderr_only(self, capsys: pytest.CaptureFixture[str]) -> None:
        echo_cron_result(JOB_ID, "completed", "hello")

        captured = capsys.readouterr()
        assert captured.out == ""  # stdout 是 --json 的 JSONL 契约，绝不能被污染
        assert captured.err == f"[cron {JOB_ID}] hello\n"

    def test_failed_line_is_marked_within_the_same_single_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        echo_cron_result(JOB_ID, "failed", "provider exploded")

        assert capsys.readouterr().err == f"[cron {JOB_ID}] failed: provider exploded\n"

    def test_newlines_fold_into_one_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        echo_cron_result(JOB_ID, "completed", "line one\nline two\r\nline three")

        assert capsys.readouterr().err == f"[cron {JOB_ID}] line one ⏎ line two ⏎ line three\n"

    def test_long_text_is_clipped(self, capsys: pytest.CaptureFixture[str]) -> None:
        echo_cron_result(JOB_ID, "completed", "x" * (CRON_ECHO_MAX_CHARS + 50))

        err = capsys.readouterr().err
        assert err.count("\n") == 1
        assert err.endswith("…\n")
        assert len(err) == len(f"[cron {JOB_ID}] ") + CRON_ECHO_MAX_CHARS + len("…\n")


class TestNotifierMatrix:
    """D4：推送与回显是两件事，四种组合都必须成立。"""

    def test_both_off_returns_none(self) -> None:
        assert _build_cron_notifier(_Service(NotificationHub()), _config()) is None

    def test_push_only_reaches_the_hub_and_stays_silent(self, capsys: pytest.CaptureFixture[str]) -> None:
        hub = NotificationHub()
        notifier = _build_cron_notifier(_Service(hub), _config(cron_push_enabled=True))
        assert notifier is not None

        notifier(JOB_ID, CronResultStatus.COMPLETED, "hello")

        _stream_id, payload = hub.published_events[0]
        assert (payload.job_id, payload.status, payload.text) == (JOB_ID, CronResultStatus.COMPLETED, "hello")
        assert capsys.readouterr().err == ""

    def test_echo_only_does_not_need_a_hub(self, capsys: pytest.CaptureFixture[str]) -> None:
        notifier = _build_cron_notifier(_Service(None), _config(cron_echo_to_terminal=True))
        assert notifier is not None

        notifier(JOB_ID, CronResultStatus.FAILED, "boom")

        assert capsys.readouterr().err == f"[cron {JOB_ID}] failed: boom\n"

    def test_both_on_deliver_the_same_notification_twice_over(self, capsys: pytest.CaptureFixture[str]) -> None:
        hub = NotificationHub()
        notifier = _build_cron_notifier(_Service(hub), _config(cron_push_enabled=True, cron_echo_to_terminal=True))
        assert notifier is not None

        notifier(JOB_ID, CronResultStatus.COMPLETED, "hello")

        assert hub.published_events[0][1].text == "hello"
        assert capsys.readouterr().err == f"[cron {JOB_ID}] hello\n"

    def test_push_requested_without_a_hub_warns_instead_of_pretending(self, caplog: pytest.LogCaptureFixture) -> None:
        """WS 关掉却开了推送：不能静默送进黑洞。"""
        with caplog.at_level(logging.WARNING, logger="heagent.cli.interactive"):
            notifier = _build_cron_notifier(_Service(None), _config(cron_push_enabled=True))

        assert notifier is None
        assert any("no notification hub" in record.message for record in caplog.records)


def _user_setting(tmp_path: Path, token: str = "s3cret") -> Path:
    """对外 listener 的凭证真源（用户级 setting.md）。"""
    path = tmp_path / "setting.md"
    path.write_text(f"---\nWS_AUTH_TOKEN: {token}\n---\n", encoding="utf-8")
    return path


def _paths(server: Any) -> list[str]:
    return [getattr(route, "path", "") for route in server.app.routes]


class TestWiringJudge:
    """装配判据：push 开/关决定「有没有中枢」与「路由在不在」。"""

    def test_push_off_registers_no_endpoint(self) -> None:
        from heagent.cli.http import build_ws_servers

        servers, _cli_hub = build_ws_servers(
            Settings(http_port_auto_find_attempts=0, cron_push_enabled=False), cli_bypass=False
        )

        assert [server.notification_hub for server in servers] == [None]
        assert NOTIFICATIONS_WS_PATH not in _paths(servers[0])

    def test_push_on_shares_one_hub_across_listeners_and_registers_the_endpoint(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from heagent.cli.http import build_ws_servers

        monkeypatch.setattr(Settings, "_user_setting_file", _user_setting(tmp_path))
        servers, _cli_hub = build_ws_servers(
            Settings(
                http_port_auto_find_attempts=0,
                cron_push_enabled=True,
                ws_external_host="0.0.0.0",
            ),
            cli_bypass=False,
        )

        assert [server.config.mode for server in servers] == ["local", "external"]
        hub = servers[0].notification_hub
        assert isinstance(hub, NotificationHub)
        # D2：对外 listener 也挂——同一份中枢（seq / 游标是进程级语义，不能拆成两份）。
        assert servers[1].notification_hub is hub
        assert NOTIFICATIONS_WS_PATH in _paths(servers[0])
        assert NOTIFICATIONS_WS_PATH in _paths(servers[1])

    @pytest.mark.embedded_http_service
    def test_embedded_service_surfaces_the_hub_to_the_entry_layer(self) -> None:
        from heagent.cli.http import build_http_service

        settings = Settings(http_port_auto_find_attempts=0, cron_push_enabled=True)
        service = build_http_service(settings, http_enabled=False)

        assert isinstance(service.notification_hub, NotificationHub)

    @pytest.mark.embedded_http_service
    def test_ws_disabled_means_no_hub_even_with_push_on(self) -> None:
        from heagent.cli.http import build_http_service

        settings = Settings(http_port_auto_find_attempts=0, cron_push_enabled=True)
        service = build_http_service(settings, http_enabled=False, ws_enabled=False)

        assert service.notification_hub is None

    def test_explicit_override_off_beats_the_settings_flag(self) -> None:
        """``http-server`` 没有 cron：命令层显式传 ``push_enabled=False``，配置开着也不建中枢。"""
        from heagent.cli.http import build_ws_servers

        servers, _cli_hub = build_ws_servers(
            Settings(http_port_auto_find_attempts=0, cron_push_enabled=True),
            cli_bypass=False,
            push_enabled=False,
        )

        assert servers[0].notification_hub is None
        assert NOTIFICATIONS_WS_PATH not in _paths(servers[0])
