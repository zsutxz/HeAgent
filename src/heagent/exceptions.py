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
