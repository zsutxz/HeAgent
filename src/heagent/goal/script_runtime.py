"""Bounded host execution for trusted, package-local GoalScript resources."""

from __future__ import annotations

import ast
import asyncio
import builtins
from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from heagent.goal.script_api import GoalScript, ScriptExecutionResult, ScriptResponse
from heagent.goal.script_loader import SCRIPT_ENTRYPOINT, GoalScriptResource, load_script

if TYPE_CHECKING:
    from heagent.memory.skill_packages import SkillPackage


class GoalScriptRuntimeError(RuntimeError):
    """Raised when a script exceeds a host limit or returns an invalid result."""


ScriptRequestHandler = Callable[[Any], ScriptResponse | Awaitable[ScriptResponse]]


class ScriptRuntime:
    """Execute one trusted package script with explicit resource limits.

    **This is not a Python sandbox**（AD-9 / AD-12）：脚本在宿主解释器内运行，理论上拥有
    进程权限；限额只是资源与形态上的约束，不是安全边界。不可信 workflow 包必须靠 OS 级
    隔离（容器 / VM / firejail），该隔离 worker 不在本 Story 范围。

    限额的**真实强度**（如实声明，不冒称）：

    - 请求数上限：由 facade 计数，确定性生效；
    - 形态上限：加载期 AST 拒绝 `while`、`import`、私有属性、辅助函数与进程调用；
    - 超时：`asyncio.wait_for` 是**协作式**取消——脚本若在同步 CPU 循环里不让出事件循环
      （如超大 `range` 推导），取消不会生效。这正是「不是安全边界」的具体含义，也是必须
      放进 OS 级隔离的原因；此处不假装它被挡住。
    """

    def __init__(
        self,
        *,
        max_requests: int = 64,
        max_depth: int = 8,
        timeout_seconds: float = 30.0,
    ) -> None:
        if max_requests < 1 or max_depth < 1 or timeout_seconds <= 0:
            raise ValueError("script runtime limits must be positive")
        self.max_requests = max_requests
        self.max_depth = max_depth
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        package: SkillPackage,
        resource: str,
        *,
        inputs: Mapping[str, Any] | None = None,
        artifacts: Mapping[str, Any] | None = None,
        request: ScriptRequestHandler,
    ) -> ScriptExecutionResult:
        script = load_script(package, resource)
        depth = _script_depth(script)
        if depth > self.max_depth:
            raise GoalScriptRuntimeError(f"script nesting depth {depth} exceeds limit {self.max_depth}")
        facade = GoalScript(
            inputs=inputs,
            artifacts=artifacts,
            request=request,
            max_requests=self.max_requests,
        )
        try:
            result = await asyncio.wait_for(self._invoke(script, facade), timeout=self.timeout_seconds)
        except (GoalScriptRuntimeError, TimeoutError, asyncio.CancelledError):
            # 有界失败语义与取消语义保持可区分：取消必须原样上抛（Runner 的 CANCELLED 路径），
            # 超时以 TimeoutError 交给调用方，已具名的运行时错误不重复包装。
            raise
        except Exception as exc:
            # 脚本自身的任何异常都收敛为**有界失败**，不得打崩 /goal run：宿主把它映射为
            # 步骤 FAILED，绝不静默放行、也不把控制权交给未捕获异常。
            raise GoalScriptRuntimeError(f"script raised {type(exc).__name__}: {exc}") from exc
        if isinstance(result, ScriptExecutionResult):
            return result.model_copy(update={"requests": list(facade.requests)})
        return ScriptExecutionResult(requests=list(facade.requests), value=result)

    async def _invoke(self, script: GoalScriptResource, facade: GoalScript) -> Any:
        namespace: dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS,
            "__name__": "__goal_script__",
        }
        exec(compile(script.tree, f"scripts/{script.name}", "exec"), namespace, namespace)  # noqa: S102
        entry = namespace.get(SCRIPT_ENTRYPOINT)
        if not callable(entry):
            raise GoalScriptRuntimeError(f"GoalScript must define callable {SCRIPT_ENTRYPOINT}(goal)")
        result = entry(facade)
        if not hasattr(result, "__await__"):
            raise GoalScriptRuntimeError(f"GoalScript {SCRIPT_ENTRYPOINT}(goal) must be async")
        return await result


#: 脚本可见的内建名白名单（**闭集**）：只有纯计算/容器构造，没有任何 I/O、反射或
#: 代码加载入口。刻意**不含** ``print``（会污染 CLI 输出）、``open``/``eval``/``exec``/
#: ``compile``/``__import__``（能力面）与 ``getattr``/``setattr``/``vars``（反射绕过面）。
_SAFE_BUILTINS = {
    name: getattr(builtins, name)
    for name in (
        "False",
        "None",
        "True",
        "abs",
        "all",
        "any",
        "bool",
        "bytes",
        "dict",
        "enumerate",
        "float",
        "frozenset",
        "int",
        "isinstance",
        "len",
        "list",
        "max",
        "min",
        "range",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    )
}


def _script_depth(script: GoalScriptResource) -> int:
    """Return maximum nested control depth used by a script."""

    def visit(node: ast.AST, depth: int) -> int:
        child_depth = (
            depth + 1 if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.AsyncWith)) else depth
        )
        return max([child_depth, *(visit(child, child_depth) for child in ast.iter_child_nodes(node))])

    return visit(script.tree, 0)
