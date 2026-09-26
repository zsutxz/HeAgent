"""日志卫生内核测试：`safe_log` 容错 + `redact_secrets` 启发式脱敏。

覆盖三层：
1. 纯函数（脱敏形态、幂等、无误伤、深度上限）；
2. 日志设施故障的**隔离**（自定义 handler 在 emit 中抛错时，插桩路径不得把故障
   升级成业务失败）；
3. 端到端（`EventBus.emit` / `AgentLoop.run` 在坏 handler 下仍完成运行）。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator

import pytest

from heagent.agent.loop import AgentLoop
from heagent.config import reset_settings
from heagent.engine.observability import EngineEvent, EventBus, LoggingObserver
from heagent.providers.base import ProviderMetadata
from heagent.pub.safe_logging import (
    ORIGINAL_HANDLER_HANDLE,
    install_logging_fault_guard,
    redact_details,
    redact_mapping,
    redact_secrets,
    safe_log,
)
from heagent.tools.registry import ToolRegistry
from heagent.pub.types import ProviderResponse, TokenUsage


class _RaisingHandler(logging.Handler):
    """在 ``emit`` 中抛异常的 handler——模拟第三方的坏日志设施。

    ``logging`` 的 ``Handler.handle`` **不**捕获 ``emit`` 的异常（与
    ``logging.raiseExceptions`` 无关，2026-09-23 实测），故被它接住的 ``logger.*``
    调用都会向上抛。``match`` 非空时只对消息含该子串的记录抛错——用于把「插桩路径
    是否免疫」与「普通进度日志是否免疫」两件事分开测。
    """

    def __init__(self, match: str = "") -> None:
        super().__init__()
        self.calls = 0
        self._match = match

    def emit(self, record: logging.LogRecord) -> None:
        if self._match and self._match not in record.getMessage():
            return
        self.calls += 1
        raise RuntimeError("broken log handler")


class _StubProvider:
    """最小 provider（与 tests/test_agent_loop.py 同形，此处自持以保持本文件独立）。"""

    def __init__(self, response: ProviderResponse) -> None:
        self._response = response

    async def send(self, messages: list[object], *, tools: list[object] | None = None) -> ProviderResponse:  # noqa: ARG002
        return self._response

    async def stream(
        self, messages: list[object], *, tools: list[object] | None = None
    ) -> AsyncIterator[ProviderResponse]:
        yield self._response

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _final(content: str) -> ProviderResponse:
    return ProviderResponse(
        content=content,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        model="stub",
        finish_reason="stop",
    )


@pytest.fixture
def fresh_registry() -> ToolRegistry:
    """每个测试独享的非单例注册表。"""
    return ToolRegistry()


@pytest.fixture(autouse=True)
def _reset_settings() -> Iterator[None]:
    reset_settings()
    yield
    reset_settings()


def _install_raising_handler(match: str) -> Iterator[_RaisingHandler]:
    """在 root logger 上挂坏 handler，并把 root level 提到 INFO（否则记录到不了 handler）。"""
    handler = _RaisingHandler(match)
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


@pytest.fixture
def broken_logging() -> Iterator[_RaisingHandler]:
    """对**所有**记录抛错的 handler，测试结束移除。"""
    yield from _install_raising_handler("")


@pytest.fixture
def fault_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """安装进程级守卫；测试结束由 monkeypatch 把 ``Handler.handle`` 还原。

    先注册一次 setattr（值即当前实现）只为让 pytest 记住「还原成什么」——否则守卫是
    进程级副作用，会污染同进程的其他测试（尤其是专门验证「无守卫时会失败」的用例）。
    """
    monkeypatch.setattr(logging.Handler, "handle", logging.Handler.handle)
    install_logging_fault_guard()


@pytest.fixture
def unguarded(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制回到**无守卫**状态（即便同进程里别的测试装过守卫）。"""
    monkeypatch.setattr(logging.Handler, "handle", ORIGINAL_HANDLER_HANDLE)


class TestRedactSecrets:
    """脱敏形态（启发式，非安全边界）。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            # 键值形态（.env 行 / export）
            ("DEEPSEEK_API_KEY=sk-abcdef123456", "DEEPSEEK_API_KEY=***"),
            ("OPENAI_API_KEY: sk-abcdef123456", "OPENAI_API_KEY: ***"),
            ('{"token": "abc123"}', '{"token": "***"}'),
            ("password=hunter2", "password=***"),
            # CLI 旗标
            ("curl --api-key sk-abcdef123456 https://x", "curl --api-key *** https://x"),
            ("tool --token=abcdefghij", "tool --token=***"),
            # 厂商前缀
            ("Authorization: Bearer abcdefghijklmn", "Authorization: Bearer ***"),
            ("ghp_0123456789012345678901234567890abc", "***"),
            ("AKIAIOSFODNN7EXAMPLE", "***"),
            # URL 内嵌凭证
            ("https://user:s3cret@example.com/v1", "https://user:***@example.com/v1"),
            # JWT
            ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcd", "***"),
        ],
    )
    def test_masks_credential_shapes(self, raw: str, expected: str) -> None:
        assert redact_secrets(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            # 普通命令与路径：不得误伤（这是「日志仍可审计」的前提）
            "pytest tests/ -q --cov=heagent",
            "src/heagent/cli.py",
            "TOKENIZER=auto",
            "OPENAI_MODEL=gpt-5.6-terra",
            "git commit -F .heagent/tmp/msg.txt",
            "routing_pools={'glm': {'tiers': {'fast': 'glm-5.3-flash'}}}",
            "",
        ],
    )
    def test_leaves_ordinary_text_untouched(self, raw: str) -> None:
        assert redact_secrets(raw) == raw

    def test_idempotent(self) -> None:
        once = redact_secrets("DEEPSEEK_API_KEY=sk-abcdef123456")
        assert redact_secrets(once) == once

    def test_never_raises_on_weird_input(self) -> None:
        # 纯函数契约：任何输入都返回字符串，不抛异常（日志路径不得因脱敏失败而失败）
        assert isinstance(redact_secrets("\\" * 1000), str)


class TestRedactDetails:
    """结构脱敏：浅层遍历 + 深度上限。"""

    def test_masks_nested_strings(self) -> None:
        payload = {
            "error": "failed: API_KEY=sk-abcdef123456",
            "argv": ["--token=abcdefghij", "run"],
            "meta": {"secret": "x", "nested": {"deep": "token=abcdefghij"}},
            "count": 3,
        }
        masked = redact_details(payload)
        assert masked["error"] == "failed: API_KEY=***"
        assert masked["argv"] == ["--token=***", "run"]
        assert masked["meta"]["secret"] == "***"  # noqa: S105 - 断言的是掩码结果，非口令本身
        assert masked["count"] == 3

    def test_depth_limit_stops_recursion(self) -> None:
        deep = {"a": {"b": {"c": {"d": "token=abcdefghij"}}}}
        assert redact_details(deep, depth=1) == deep  # 超出深度：原样返回，不越界递归

    def test_non_container_returns_as_is(self) -> None:
        assert redact_details(42) == 42
        assert redact_details(None) is None

    def test_mapping_entry_point(self) -> None:
        masked = redact_mapping({"reason": "auth failed with token=abcdefghij"})
        assert masked == {"reason": "auth failed with token=***"}


class TestSafeLog:
    """`safe_log` 的容错语义。"""

    def test_returns_true_on_success(self) -> None:
        logger = logging.getLogger("heagent.tests.safe_logging.ok")
        assert safe_log(logger, logging.INFO, "hello %s", "world") is True

    def test_returns_false_and_swallows_on_broken_handler(
        self, broken_logging: _RaisingHandler, unguarded: None
    ) -> None:
        # 必须显式无守卫：进程级守卫一旦装上，handler 故障会在更下层被吞，本函数无从察觉。
        logger = logging.getLogger("heagent.tests.safe_logging.broken")
        assert safe_log(logger, logging.ERROR, "hello") is False

    def test_swallows_exception_with_traceback_request(self, broken_logging: _RaisingHandler, unguarded: None) -> None:
        logger = logging.getLogger("heagent.tests.safe_logging.broken_exc")
        try:
            raise ValueError("boom")
        except ValueError:
            assert safe_log(logger, logging.ERROR, "failed", exc_info=True) is False


class TestBrokenLoggingIsIsolated:
    """日志设施故障不得把「观测故障」升级成「业务失败」。"""

    def test_event_bus_emit_survives_broken_handler(self, broken_logging: _RaisingHandler) -> None:
        bus = EventBus([LoggingObserver()])
        event = bus.publish("iteration_started", run_id="r1")
        assert event.event_type == "iteration_started"
        assert bus.recent_events == [event]

    def test_logging_observer_masks_credentials(self, caplog: pytest.LogCaptureFixture) -> None:
        observer = LoggingObserver()
        with caplog.at_level(logging.INFO, logger="heagent.engine.observability"):
            observer.handle(
                EngineEvent(
                    event_type="tool_call_completed",
                    tool_name="shell",
                    target="curl --api-key sk-abcdef123456 https://x",
                    details={"error": "DEEPSEEK_API_KEY=sk-abcdef123456"},
                )
            )
        assert "sk-abcdef123456" not in caplog.text
        assert "curl --api-key *** https://x" in caplog.text
        assert "DEEPSEEK_API_KEY=***" in caplog.text

    @pytest.mark.asyncio
    async def test_agent_run_completes_with_fault_guard(
        self, broken_logging: _RaisingHandler, fault_guard: None, fresh_registry: ToolRegistry
    ) -> None:
        """端到端：装了进程级守卫后，**任何**记录都抛错的 handler 也不会拖垮 run。"""
        loop = AgentLoop(_StubProvider(_final("pong")), registry=fresh_registry, max_iterations=3)
        assert await loop.run("test") == "pong"
        # handler 确实被命中过（否则本测试没覆盖到目标路径，属假通过）
        assert broken_logging.calls > 0

    @pytest.mark.asyncio
    async def test_agent_run_fails_without_the_guard(
        self, broken_logging: _RaisingHandler, unguarded: None, fresh_registry: ToolRegistry
    ) -> None:
        """对照：拆掉守卫后同一个 run 会失败——证明守卫是**承重**的，而非装饰。

        失败点在运行栈**未被逐调用点收口**的普通进度日志（实测最先命中
        ``EngineContainer.default`` 的 sandbox backend 日志，其次还有
        ``Calling provider: …``）：插桩路径有 :func:`safe_log` 兜底，进度日志没有——
        这正是需要进程级守卫的原因。
        """
        with pytest.raises(RuntimeError, match="broken log handler"):
            loop = AgentLoop(_StubProvider(_final("pong")), registry=fresh_registry, max_iterations=3)
            await loop.run("test")
        assert broken_logging.calls > 0


class TestFaultGuard:
    """进程级守卫本身的行为。"""

    def test_install_is_idempotent(self, fault_guard: None) -> None:
        assert install_logging_fault_guard() is False  # 已装：不重复包装

    def test_guard_restores_diagnostics_via_handle_error(
        self, broken_logging: _RaisingHandler, fault_guard: None
    ) -> None:
        """「不抛」不等于「无声」：失败仍走 stdlib 的 handleError 诊断路径。"""
        errors: list[logging.LogRecord] = []

        class Recording(_RaisingHandler):
            def handleError(self, record: logging.LogRecord) -> None:
                errors.append(record)

        handler = Recording()
        logging.getLogger("heagent.tests.safe_logging.diag").addHandler(handler)
        try:
            logging.getLogger("heagent.tests.safe_logging.diag").error("boom")
        finally:
            logging.getLogger("heagent.tests.safe_logging.diag").removeHandler(handler)
        assert len(errors) == 1

    def test_install_returns_true_when_not_yet_installed(self, unguarded: None) -> None:
        assert install_logging_fault_guard() is True
