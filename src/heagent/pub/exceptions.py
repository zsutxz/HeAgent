"""HeAgent exception hierarchy."""


class HeAgentError(Exception):
    """Base class for framework-defined exceptions."""

    def __init__(self, message: str = "") -> None:
        self.message = message
        super().__init__(message)


class ProviderError(HeAgentError):
    """Provider request failed."""

    def __init__(self, message: str = "", *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ToolError(HeAgentError):
    """Tool execution failed."""


class SafetyViolation(HeAgentError):
    """Safety guard blocked a tool call."""


class BudgetExceeded(HeAgentError):
    """Iteration or token budget exceeded."""


class PolicyViolation(HeAgentError):
    """Engine policy denied a tool call before execution."""


class SessionConflictError(HeAgentError):
    """A session file changed on disk since the caller read it.

    只在调用方显式传 ``expected_version`` 时抛出（``SessionStore.save`` / ``rename``）；不传则维持
    既有的 last-write-wins 语义，CLI 行为因此逐字节不变（Epic 50 / Story 50-3，脊柱 I11）。
    """


class SessionNotFoundError(HeAgentError):
    """No session file exists for the requested session id."""


class SessionUnreadableError(HeAgentError):
    """A session file exists but cannot be parsed.

    与「空会话」严格区分：``SessionStore.load`` 为兼容 CLI 仍对损坏文件返回空列表，而元数据读
    （``load_metadata`` / ``list_metadata`` / ``rename``）抛出本异常，由控制台映射为
    ``session_unreadable`` —— 否则网页会把损坏的会话当空会话继续写并覆盖掉原内容。
    """
