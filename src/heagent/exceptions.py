"""HeAgent 异常层级体系。

所有框架异常继承自 HeAgentError，禁止抛出裸 Exception。
层级设计使调用方可按粒度捕获：ProviderError/ToolError/SafetyViolation/BudgetExceeded。
"""


class HeAgentError(Exception):
    """框架异常基类，所有自定义异常的父类。"""

    def __init__(self, message: str = "") -> None:
        self.message = message
        super().__init__(message)


class ProviderError(HeAgentError):
    """Provider 调用失败：API 错误、限流、认证失败等。"""


class ToolError(HeAgentError):
    """工具执行失败：运行时错误、参数异常等。"""


class SafetyViolation(HeAgentError):
    """安全违规：工具调用被 SafetyGuard 拦截（危险命令等）。"""


class BudgetExceeded(HeAgentError):
    """预算超限：迭代次数或 Token 用量超出设定的上限。"""
