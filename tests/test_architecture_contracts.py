"""架构契约的可执行断言。

把只写在 ``CLAUDE.md`` / docstring 里的**硬约束**钉成测试——它们此前只靠人工 grep 与「记得同步」
维持（本仓库已有先例：``_READ_ONLY_TOOLS`` 双份靠测试锁一致）。这类断言的价值不在发现今天的错误，
而在**拒绝明天的静默漂移**。
"""

from __future__ import annotations

import ast
import importlib
import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from heagent.engine.context import iso_now
from heagent.engine.checkpoint import _iso_now as workflow_iso_now
from heagent.events.protocol import _now_iso as events_now_iso

if TYPE_CHECKING:
    from collections.abc import Iterator

SRC = Path(__file__).resolve().parents[1] / "src" / "heagent"

# 已知的 heagent 模块路径（``src/heagent`` 下的 .py 文件与包目录，点分形式、去 ``heagent.`` 前缀）：
# 用于识别 ``from heagent import <名>`` / ``from heagent.pub import <名>`` 这类**别名形态**。
# 不能直接用 ``(SRC / name).is_dir()``——Windows 文件系统大小写不敏感，
# ``from heagent import Agent``（包根符号再导出）会被误判成 ``heagent/agent`` 子包。
# 2026-09-26 分层收敛后本表是识别器的唯一依据：包与模块、任意深度一视同仁
# （``pub.types`` / ``config.catalog`` 与 ``providers`` 同款处理，不再区分「子包」与「顶层模块」）。
_KNOWN_MODULES = frozenset(
    entry
    for entry in (
        {path.relative_to(SRC).with_suffix("").as_posix().replace("/", ".") for path in SRC.rglob("*.py")}
        | {path.relative_to(SRC).as_posix().replace("/", ".") for path in SRC.rglob("*") if path.is_dir()}
    )
    if not entry.endswith(("__init__", "__main__"))
)

# 包 → 运行期不得导入的 heagent 子模块（CLAUDE.md「硬约束（违反即架构错误）」）。
# 入口层模块（cli 包 / gui）：组合根与展示适配只属于入口层，下层一律不得反向导入
# （Phase 1 组合根收敛的契约化；新增入口模块须同步此表）。
# 2026-09-26：原七个平铺模块 ``cli*.py`` 收进 ``heagent/cli/`` 包 ⇒ 本表按**包根**收敛为一条
# ``heagent.cli``（``_heagent_root`` 取模块路径第二段，故 ``heagent.cli.display`` 也归它）。
# 这比原先更严：``cli_display``（展示辅助）与 ``cli_dialogs``（原生目录选择）此前各自单列，
# 现在同属入口层——两者实测都只被入口层导入（GUI / cli/http.py）。
# 2026-09-26 同日：顶层 ``wiring.py``（provider 组合根）迁入 ``heagent/cli/wiring.py``——
# 它此前已单列在本表里，迁入后由 ``heagent.cli`` 包根覆盖，故条目删除（位置追上判据）。
_ENTRYPOINT_MODULES = (
    "heagent.cli",
    "heagent.gui",
)
# goal/ 是入口层**域模块**（cli/goal.py 的装载/文档层，frame.md 六）：与组合根同属「下层不得反向
# 导入」的入口面。此前只有 engine/memory 条目显式列它，其余包存在形式绕过（48-5 评审 W-7，
# AST 实测运行期只有 cli/goal.py 导入 goal/）。
_ENTRY_LAYER_MODULES = (*_ENTRYPOINT_MODULES, "heagent.goal")

FORBIDDEN_RUNTIME_IMPORTS: dict[str, tuple[str, ...]] = {
    "providers": ("heagent.agent", *_ENTRY_LAYER_MODULES),
    "tools": ("heagent.agent", *_ENTRY_LAYER_MODULES),
    "engine": ("heagent.agent", *_ENTRY_LAYER_MODULES),
    "memory": ("heagent.agent", "heagent.engine", *_ENTRY_LAYER_MODULES),
    "context": ("heagent.agent", *_ENTRY_LAYER_MODULES),
    "cron": ("heagent.agent", *_ENTRY_LAYER_MODULES),
    # events/ 是事件传输层，运行期零 engine 依赖（引擎类型仅出现在 TYPE_CHECKING 里）。
    "events": ("heagent.agent", "heagent.engine", *_ENTRY_LAYER_MODULES),
    # network/ 是入口传输层（Epic 48）：只承载 framing / 协议 / 连接生命周期，运行期不得伸手进
    # 运行时栈——Provider/Engine/AgentLoop 的装配是入口层（cli / wiring）单向伸手。
    # Epic 50 的 I1 再收紧一档：**网络层不认识项目与配置**——``heagent.config``（Settings 本体 +
    # 配置目录 + 写通道 + envfile，一条覆盖整包）/ ``projects``（注册表）/ ``heagent.pub.workspace``
    # （状态根）一律不得出现在 network/ 里。
    # 粒度必须细到**模块**：``heagent.pub.safe_logging`` 是网络层唯一合法的 pub 依赖
    # （零依赖的日志安全模块），所以这里不能写成 ``heagent.pub``。
    "network": (
        "heagent.agent",
        "heagent.engine",
        "heagent.providers",
        "heagent.tools",
        "heagent.memory",
        "heagent.context",
        "heagent.cron",
        "heagent.events",
        "heagent.config",
        "heagent.pub.projects",
        "heagent.pub.workspace",
        *_ENTRY_LAYER_MODULES,
    ),
    # 公共层 ``heagent/pub/``（2026-09-26 自顶层平铺模块收敛）：只许依赖标准库、Pydantic 与**同层**
    # 公共模块。这是「任何层都可以依赖 pub；pub 不依赖任何层」的可执行面——漏了这条，
    # ``pub/*.py`` 顺手 ``import heagent.engine`` 不会触发任何断言。
    "pub": (
        "heagent.providers",
        "heagent.tools",
        "heagent.context",
        "heagent.engine",
        "heagent.agent",
        "heagent.memory",
        "heagent.cron",
        "heagent.events",
        "heagent.network",
        "heagent.config",
        *_ENTRY_LAYER_MODULES,
    ),
    # 配置包 ``heagent/config/``：依赖 ``pub`` + stdlib/pydantic，不得伸手进运行栈。
    "config": (
        "heagent.providers",
        "heagent.tools",
        "heagent.context",
        "heagent.engine",
        "heagent.agent",
        "heagent.memory",
        "heagent.cron",
        "heagent.events",
        "heagent.network",
        *_ENTRY_LAYER_MODULES,
    ),
    # agent/ 是运行栈顶：不得导入任何入口层（组装是入口层单向伸手，不是运行栈反向伸手）。
    "agent": _ENTRY_LAYER_MODULES,
}


def _module_prefixes(module: str | None) -> set[str]:
    """``heagent.a.b`` → ``{"heagent.a", "heagent.a.b"}``（逐级前缀，供「按包禁依赖」匹配）。

    返回**全部前缀**而不是「只取前两段」，是 2026-09-26 分层收敛的硬需求：``pub`` / ``config``
    两包内部还有子模块（``heagent.pub.workspace`` / ``heagent.config.catalog``），只取两段会让
    「禁 ``heagent.pub.workspace`` 而放行 ``heagent.pub.safe_logging``」这类精确条目无法表达——
    ``network/`` 恰好是这个形状（它对 pub 的唯一合法依赖就是 ``safe_logging``）。
    """
    parts = (module or "").split(".")
    if parts[0] != "heagent" or len(parts) < 2:
        return set()
    return {".".join(parts[:size]) for size in range(2, len(parts) + 1)}


def _imported_roots(node: ast.Import | ast.ImportFrom) -> set[str]:
    """把一条 import 语句映射为「heagent 子模块」集合（两种等价写法同样处理）。

    ``import heagent.providers.router``（子模块在 ``node.module`` 上）与
    ``from heagent import providers``（子模块在 alias 上）必须都被识别——此前只识别前者，
    后者可用于绕过反向依赖断言。别名形态只把**真实存在的模块路径**（``_KNOWN_MODULES``）计入，
    避免误伤 ``from heagent import Agent`` 这类包根符号再导出；``from heagent.pub import types``
    同样展开出 ``heagent.pub.types``。
    """
    if isinstance(node, ast.Import):
        return {prefix for alias in node.names for prefix in _module_prefixes(alias.name)}
    if not node.module or not node.module.startswith("heagent"):
        return set()
    prefixes = _module_prefixes(node.module)
    tail = node.module.removeprefix("heagent").lstrip(".")
    for alias in node.names:
        candidate = f"{tail}.{alias.name}".strip(".")
        if candidate in _KNOWN_MODULES:
            prefixes |= _module_prefixes(f"heagent.{candidate}")
    return prefixes


def _imports(path: Path) -> tuple[set[str], set[str]]:
    """返回 ``(运行期导入的 heagent 子模块, TYPE_CHECKING 内导入的)``。

    区分两者是必要的：``events/protocol.py`` 有意在 ``TYPE_CHECKING`` 下引用引擎类型（类型注解
    需要、运行期不需要），若把类型期导入也算违反，这条契约就只能靠放宽来维持。
    函数体内的局部导入**算**运行期依赖——它同样构成模块间的层次耦合。
    """
    return _module_imports(path.read_text(encoding="utf-8"))


def _module_imports(source: str) -> tuple[set[str], set[str]]:
    """按源码文本解析导入（``_imports`` 的可测内核：两种导入写法都必须被识别）。

    两种等价写法都要记：``import heagent.providers.router``（子模块在 ``node.module`` 上）与
    ``from heagent import providers``（子模块在 alias 上）。此前只识别前者，后者可用于绕过
    反向依赖断言（如 ``from heagent import providers`` 在 ``network/`` 里不会被判违反）。
    只把**真实存在的模块路径**计入，避免误伤 ``from heagent import Agent`` 这类包根符号再导出。
    """
    runtime: set[str] = set()
    typing_only: set[str] = set()

    def record(node: ast.stmt, bucket: set[str]) -> None:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            bucket |= _imported_roots(node)

    def walk(body: list[ast.stmt], bucket: set[str]) -> None:
        for node in body:
            if isinstance(node, ast.If):
                target = typing_only if "TYPE_CHECKING" in ast.unparse(node.test) else bucket
                walk(node.body, target)
                walk(node.orelse, bucket)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                walk(node.body, bucket)
            elif isinstance(node, ast.Try):
                walk(node.body, bucket)
                for handler in node.handlers:
                    walk(handler.body, bucket)
                walk(node.orelse, bucket)
                walk(node.finalbody, bucket)
            else:
                record(node, bucket)

    walk(ast.parse(source).body, runtime)
    return runtime, typing_only


def _package_modules(package: str) -> Iterator[Path]:
    base = SRC / package
    if base.is_dir():
        yield from sorted(base.rglob("*.py"))


def test_no_reverse_dependency_on_agent() -> None:
    """底层包运行期不得反向导入 ``agent``（memory/events 另外不得导入 ``engine``）。

    反向依赖会破坏「新增 provider / 工具不得反向导入 agent」的可插拔性——``AgentLoop`` 应当零改动
    地接纳新 provider 与工具；一旦底层包开始 import agent，扩展点就变成了循环。
    ``memory → engine`` 于 2026-09-17 收敛（``memory/dream.py`` 的整包导入改为入口层注入 +
    TYPE_CHECKING 引用）。engine→memory 的旧合法边（``workflow_runner`` 对 ``skill_packages``
    资源模型）已于 2026-09-20 消除：工作流模型迁至 ``engine/workflow_resource.py``，声明解析
    迁至 ``goal/workflow_loader.py``（入口层，goal→engine/memory 同向）。
    """
    offenders: list[str] = []
    for package, forbidden in FORBIDDEN_RUNTIME_IMPORTS.items():
        for path in _package_modules(package):
            runtime, _ = _imports(path)
            rel = path.relative_to(SRC).as_posix()
            offenders.extend(f"{rel} → {target}" for target in sorted(runtime & set(forbidden)))
    assert offenders == [], "运行期反向依赖：" + ", ".join(offenders)


def test_workspace_paths_is_the_only_state_path_module() -> None:
    source = (SRC / "pub" / "workspace.py").read_text(encoding="utf-8")
    assert "from heagent" not in source
    assert "import os" not in source


def test_getcwd_configuration_is_limited_to_entrypoints() -> None:
    """cwd 兜底只许出现在入口层 ``heagent/cli/`` 包内（其余一律经 ``WorkspacePaths.from_root``）。

    判据按**包**而不是文件白名单：2026-09-26 起入口层是 ``cli/`` 包（console/composition/
    interactive/http/tcp/…），逐个文件名列举会在每次拆分时静默失效（漏掉的文件就变成豁免）。
    """
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if path.name == "workspace.py":
            continue
        text = path.read_text(encoding="utf-8")
        is_entry_layer = path.relative_to(SRC).parts[0] == "cli"
        if "os.getcwd()" in text and not is_entry_layer:
            offenders.append(path.relative_to(SRC).as_posix())
        for line in text.splitlines():
            if "os.getcwd()" in line and "WorkspacePaths.from_root" not in line:
                position = text.find(line)
                window = text[max(0, position - 160) : position + len(line) + 160]
                if "WorkspacePaths.from_root" not in window:
                    offenders.append(path.relative_to(SRC).as_posix())
    assert offenders == []


def test_types_only_imports_stay_types_only() -> None:
    """``events`` 对 ``engine`` 的引用必须仍只出现在 ``TYPE_CHECKING`` 下。

    上一条断言只保证「没有运行期导入」；若把某个类型期引用挪到运行期，那条会立刻红——这里再钉一层
    正向证据，避免「两边都改」把契约悄悄抹平。
    """
    typing_refs = 0
    for path in _package_modules("events"):
        _, typing_only = _imports(path)
        typing_refs += len(typing_only & {"heagent.engine"})
    assert typing_refs > 0, "events 对 engine 的类型期引用消失了？契约文档需要同步更新"


def test_forbidden_import_detection_covers_the_package_root_import_form() -> None:
    """两种等价导入写法必须同样计入运行期依赖。

    ``from heagent import providers``（子模块名在 alias 上）此前整条漏掉，新增的 network 反向
    依赖断言因此存在形式绕过：``network/`` 里写 ``from heagent import providers`` 不会被判违反。
    """
    runtime, typing_only = _module_imports(
        "import heagent.providers.router\n"
        "from heagent import providers\n"
        "from heagent.tools import registry\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from heagent.agent import AgentLoop\n"
    )

    assert runtime == {
        "heagent.providers",
        "heagent.providers.router",
        "heagent.tools",
        "heagent.tools.registry",
    }
    assert typing_only == {"heagent.agent"}


def test_forbidden_import_detection_ignores_package_root_symbol_reexports() -> None:
    """``from heagent import Agent`` 是包根符号再导出，不是子包依赖（不得误伤）。"""
    runtime, typing_only = _module_imports("from heagent import Agent, Settings\n")

    assert runtime == set()
    assert typing_only == set()


def test_forbidden_import_detection_covers_top_level_modules() -> None:
    """模块/包的别名写法与分层路径同样计入运行期依赖。

    评审发现（镜头三③）：I1 要求「网络层不认识项目与配置」，但可执行断言此前只列子包 ⇒
    ``heagent.config`` / ``heagent.pub.projects`` / ``heagent.config.catalog`` 写进 ``network/`` 不会被
    判违反，契约形同虚设。本用例钉住识别器本身（谁漏了这几种写法，这里先红）——
    2026-09-26 分层收敛后还要覆盖 ``from heagent.pub import types`` 与 ``heagent.pub.workspace``
    这类**三层**路径（network 禁 workspace 而放行 safe_logging 全靠这个粒度）。
    """
    runtime, typing_only = _module_imports(
        "from heagent import config\n"
        "from heagent.pub.projects import ProjectRegistry\n"
        "from heagent.pub import types\n"
        "import heagent.pub.workspace\n"
    )

    assert runtime == {
        "heagent.config",
        "heagent.pub",
        "heagent.pub.projects",
        "heagent.pub.types",
        "heagent.pub.workspace",
    }
    assert typing_only == set()


def test_frontmatter_parsing_is_centralized() -> None:
    """frontmatter 分隔正则只允许出现在共享模块 ``frontmatter.py`` 中。

    2026-09-17 勘察发现六处手写 ``---`` frontmatter 解析器各自漂移（同一文档在不同模块
    可能解析出不同结果），已收敛为 ``heagent.pub.frontmatter``。此断言拒绝「明天又有人就地
    手写一份」的静默回退——新增解析需求必须走共享模块。
    """
    needle = "---\\s*\\n"  # 源码中正则字面量的原始字符序列
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in sorted(SRC.rglob("*.py"))
        if path.name != "frontmatter.py" and needle in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], "frontmatter 正则漂移出共享模块 heagent.pub.frontmatter：" + ", ".join(offenders)


def test_timestamps_are_naive_and_parseable() -> None:
    """各处时间戳必须是 **naive** ISO（可被 ``datetime.fromisoformat`` 解析、无 tzinfo）。

    **精度有意不同，不要「顺手统一」**（本次加断言时实测发现，此前被误以为三处同格式）：

      - ``engine.context.iso_now`` / ``events.protocol._now_iso``：秒精度。两者是「同一格式的独立
        实现」——``events/`` 运行期不得依赖 ``engine``（见上方断言），所以这份格式是照抄而非共用。
      - ``engine.checkpoint._iso_now``：**微秒**精度（源码里显式写 ``timespec="microseconds"``，用途是
        状态迁移的 ``updated_at``）。它是否需要亚秒分辨率没有测试或注释佐证，故本测试**不锁定**其精度。

    真正会出事的是 **naive 与否**：某处一旦带上 tzinfo，与存量 naive 状态（checkpoint / rollout /
    ledger 记录）比较就会 ``TypeError``——``ledger._parse_iso_to_naive`` 正是为抹平这种混用而存在。
    """
    for name, factory in (
        ("engine.context.iso_now", iso_now),
        ("engine.checkpoint._iso_now", workflow_iso_now),
        ("events.protocol._now_iso", events_now_iso),
    ):
        value = factory()
        assert datetime.fromisoformat(value).tzinfo is None, f"{name} 不再是 naive：{value!r}"

    # 同一格式的一对独立实现：格式必须一致（任一处改精度/加时区即红）。
    seconds = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
    for name, factory in (("engine.context.iso_now", iso_now), ("events.protocol._now_iso", events_now_iso)):
        assert seconds.match(factory()), f"{name} 与另一处不再同格式：{factory()!r}"


def test_loop_strategy_modules_do_not_runtime_import_loop_facade() -> None:
    """Phase 2：loop 策略模块**运行期**禁止导入 ``heagent.agent.loop``（反向导入即成环）。

    ``loop.py``（façade）运行期导入五个策略模块；策略模块对 ``AgentLoop`` 的引用只允许
    出现在 ``TYPE_CHECKING`` 下（首参类型注解需要）。包级 ``FORBIDDEN_RUNTIME_IMPORTS``
    的粒度是包根（``heagent.agent``），会把策略模块间合法的兄弟导入一并误伤，故此处按
    **完整模块路径**单独扫描。新增 loop 策略模块时必须同步 ``_LOOP_STRATEGY_MODULES``。
    """
    strategy_modules = (
        "run_lifecycle.py",
        "stream_runtime.py",
        "resume_runtime.py",
        "context_runtime.py",
        "message_ports.py",
    )

    def runtime_imports(path: Path) -> set[str]:
        """完整模块路径粒度的运行期导入集（TYPE_CHECKING 块不算）。"""
        found: set[str] = set()

        def record(node: ast.stmt) -> None:
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)

        def walk(body: list[ast.stmt]) -> None:
            for node in body:
                if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
                    continue
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    walk(node.body)
                elif isinstance(node, ast.Try):
                    walk(node.body)
                    walk(node.orelse)
                    walk(node.finalbody)
                    for handler in node.handlers:
                        walk(handler.body)
                else:
                    record(node)

        walk(ast.parse(path.read_text(encoding="utf-8")).body)
        return found

    offenders: list[str] = []
    for name in strategy_modules:
        path = SRC / "agent" / name
        if "heagent.agent.loop" in runtime_imports(path):
            offenders.append(f"agent/{name}")
    assert offenders == [], "策略模块运行期导入 loop façade（成环）：" + ", ".join(offenders)


def test_goal_application_use_case_is_click_free() -> None:
    """Phase 3：goal/application.py 的 use-case **运行期**禁止依赖 Click 与入口模块。

    workflow 校验 / gate 渲染 / story 选择 / checkpoint 恢复与推进全部收敛在
    ``goal/application``；用户可见文案以结构化 outcome（messages）携带、由 cli/goal.py
    统一渲染。该模块一旦 import ``click`` / ``heagent.cli*`` / ``heagent.gui*``，
    use-case 就再也离不开 Click 环境（test.md Phase 3 验收「同一 workflow use-case
    可在无 Click 环境下运行」），GUI 原生渲染的演进路径也被焊死。``goal/naming.py``
    的 click.echo 是入口侧回退提示，不属 use-case，不在本契约内。
    """
    forbidden_prefixes = ("heagent.cli", "heagent.gui")

    def runtime_imports(path: Path) -> set[str]:
        """完整模块路径粒度的运行期导入集（TYPE_CHECKING 块不算）。"""
        found: set[str] = set()

        def record(node: ast.stmt) -> None:
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)

        def walk(body: list[ast.stmt]) -> None:
            for node in body:
                if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
                    continue
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    walk(node.body)
                elif isinstance(node, ast.Try):
                    walk(node.body)
                    walk(node.orelse)
                    walk(node.finalbody)
                    for handler in node.handlers:
                        walk(handler.body)
                else:
                    record(node)

        walk(ast.parse(path.read_text(encoding="utf-8")).body)
        return found

    offenders = [
        name
        for name in runtime_imports(SRC / "goal" / "application.py")
        if name == "click" or name.startswith(forbidden_prefixes)
    ]
    assert offenders == [], "goal use-case 运行期依赖 Click/入口模块（无 Click 验收失效）：" + ", ".join(offenders)


def test_sandbox_and_mcp_subpackages_are_click_free() -> None:
    """Phase 4：``tools/sandbox/*`` 与 ``tools/mcp/*`` 运行期禁止依赖 Click。

    两子包是确定性基础设施（沙箱后端 / MCP 生命周期），用户可见文案属入口层职责
    （如 MCP discovery_failures 由 cli 渲染）——一旦 import ``click``，基础设施就再也
    离不开 Click 环境、无法在 GUI / cron / 库消费方下独立运行。heagent 侧入口模块
    （``heagent.cli*`` / ``heagent.gui*`` / ``heagent.agent``）的反向导入已由
    ``FORBIDDEN_RUNTIME_IMPORTS["tools"]`` 钉死，本契约只补第三方 Click 这一格。
    """
    offenders: list[str] = []
    for sub in ("sandbox", "mcp"):
        for path in sorted((SRC / "tools" / sub).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
                    continue
                is_click_import = (
                    isinstance(node, ast.Import)
                    and any(alias.name == "click" or alias.name.startswith("click.") for alias in node.names)
                ) or (
                    isinstance(node, ast.ImportFrom)
                    and node.module
                    and (node.module == "click" or node.module.startswith("click."))
                )
                if is_click_import:
                    offenders.append(f"tools/{sub}/{path.relative_to(SRC / 'tools' / sub)}")
    assert offenders == [], "基础设施子包运行期依赖 Click（入口渲染职责泄漏）：" + ", ".join(offenders)


def test_os_open_is_whitelisted_to_safe_open_and_lock_files() -> None:
    """Phase 4：``os.open`` 仅允许出现在安全读取内核与锁文件两处。

    ``tools/path_safety.open_text_under_root`` 是「解析后安全打开」的单一入口（围栏 +
    O_NOFOLLOW + fstat）；``persist.py`` 的 ``os.open`` 是跨进程 ``.lock`` 文件创建
    （O_CREAT|O_RDWR，非内容读取路径，强行并入读取内核属扭曲）。其余模块一律经这两处
    ——分散的底层 open 即分散的 TOCTOU/符号链接暴露面。
    """
    allowed = {"tools/path_safety.py", "pub/persist.py"}
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "open"
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            ):
                offenders.append(rel)
    assert offenders == [], "os.open 逃出白名单（安全读取内核单点被稀释）：" + ", ".join(offenders)


def test_skill_modules_do_not_read_files_directly() -> None:
    """Phase 4：skill 拆分层四文件禁止裸 ``read_text`` / ``open`` 读取技能文件。

    全部读取须走 ``path_safety.open_text_under_root``（TOCTOU/路径逃逸/并发替换的
    统一覆盖面）。``skill_importer.py`` 的 manifest.csv（csv raw newline 语义）与
    ``_hash``（字节流）是已留档的例外，不在本契约文件集合内。
    """
    guarded = ("skill_models.py", "skill_catalog.py", "skill_store.py", "skill_rewrite.py")
    offenders: list[str] = []
    for name in guarded:
        path = SRC / "memory" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "read_text":
                offenders.append(name)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                offenders.append(name)
    assert offenders == [], "skill 模块裸读文件（绕过 safe-open 单一入口）：" + ", ".join(offenders)


# ── Epic 49：HTTP 网页入口的可选依赖与投递面 ──

# 可选 HTTP 栈的顶层包名（pyproject 的 ``http`` extra 直接声明）。
_OPTIONAL_ASGI_ROOTS = frozenset({"starlette", "uvicorn"})


def _top_level_runtime_imports(tree: ast.Module) -> set[str]:
    """模块顶层的**运行期**导入的顶层包名（``if TYPE_CHECKING:`` 块内的不算）。"""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING":
            continue
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_optional_asgi_stack_is_only_imported_lazily() -> None:
    """starlette / uvicorn 只能**延迟导入**（``importlib.import_module``，在真要服务时才加载）。

    机械保证「基础安装（不含 ``heagent[http]``）下，普通 CLI 用法、gui、tcp-server、init、
    replay 与库用法都不会因为导入而拉起 ASGI 栈，也不会因为缺依赖而失败」：源码里不存在
    顶层的 starlette/uvicorn 导入——传输层刻意用 ``importlib`` 在函数体内加载它们。
    """
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _top_level_runtime_imports(tree) & _OPTIONAL_ASGI_ROOTS:
            offenders.append(path.relative_to(SRC).as_posix())
    assert offenders == [], "可选 ASGI 栈被顶层导入（可选依赖会变成硬依赖）：" + ", ".join(offenders)


def test_web_package_has_no_runtime_imports() -> None:
    """``heagent/web/`` 只是投递面（HTML/CSS/JS + 包标记）：不得依赖任何 heagent 运行时模块。

    页面资源经 ``importlib.resources`` 读取（AD-11），因此这个包被导入时必须没有任何副作用，
    也不能把传输层/运行栈拖进来。
    """
    offenders: list[str] = []
    for path in sorted((SRC / "web").rglob("*.py")):
        runtime, typing_only = _module_imports(path.read_text(encoding="utf-8"))
        if runtime or typing_only:
            offenders.append(path.relative_to(SRC).as_posix())
    assert offenders == [], "web 包出现了 heagent 运行时导入：" + ", ".join(offenders)


def test_workspace_module_only_imports_stdlib_and_pydantic() -> None:
    import sys

    tree = ast.parse((SRC / "pub" / "workspace.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module.split(".")[0] in sys.stdlib_module_names | {"pydantic"}
        elif isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] in sys.stdlib_module_names | {"pydantic"} for alias in node.names)


def test_entrypoints_do_not_duplicate_runtime_store_paths() -> None:
    modules = [
        "cli/console.py",
        "cli/composition.py",
        "cli/interactive.py",
        "cli/goal.py",
        "cli/http.py",
        "cli/http_console.py",
        "cli/tcp.py",
        "engine/container.py",
        "gui/__init__.py",
        "cli/housekeeping.py",
        "tools/edits.py",
        "tools/sandbox/session.py",
    ]
    for module in modules:
        tree = ast.parse((SRC / module).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not re.match(
                    r"^\.heagent[\\/](sessions|skills|runs|ledger|memory|user|cron|checkpoints|sandboxes|tmp|console|backups)([\\/]|$)",
                    node.value,
                ), module


def test_config_layer_stays_out_of_the_runtime_stack() -> None:
    """Story 50-7 T6：配置面（catalog / envfile / config_write / projects）不得伸手进运行时栈。

    ``network/`` 的依赖面已由 ``FORBIDDEN_RUNTIME_IMPORTS`` 钉住；这几个**顶层模块**是 Epic 50 新加的
    同层面（配置来源求解 / 保真写 / 写流水线 / 项目注册表），同样只允许依赖 stdlib + pydantic + 底层
    共用模块。漏掉它们的话，``config/write.py`` 这类模块顺手 ``import heagent.engine`` 不会触发任何断言。
    """
    forbidden = {
        "heagent.agent",
        "heagent.engine",
        "heagent.providers",
        "heagent.tools",
        "heagent.memory",
        "heagent.context",
        "heagent.cron",
        "heagent.events",
        *_ENTRY_LAYER_MODULES,
    }
    for module in (
        "config/__init__.py",
        "config/catalog.py",
        "config/envfile.py",
        "config/write.py",
        "pub/projects.py",
    ):
        runtime, _typing = _imports(SRC / module)
        assert runtime & forbidden == set(), f"{module}: {sorted(runtime & forbidden)}"


def test_write_whitelist_is_a_subset_of_settings_and_holds_no_credentials() -> None:
    """Story 50-7 T6 / 负向验证②：白名单 ⊆ ``Settings`` 字段（env 大写口径）**且**不含凭证键。

    两个方向都要断言：① 白名单里出现一个不存在（或拼错）的字段名 ⇒ 用户会看到一个永远写不进去的项
    （静默走「未知键」分支）；② 白名单里混进 `*_API_KEY` ⇒ 直接打破「凭证永不回传、永不写入」的承诺。
    另加一条「白名单里的键必须真的被判成可写」，防止靠「没被分类」蒙混过关。
    """
    from heagent.config import catalog
    from heagent.config import Settings

    whitelist = catalog.whitelist()
    env_keys = {name.upper() for name in Settings.model_fields}
    assert whitelist <= env_keys, f"白名单里有不存在的字段名：{sorted(whitelist - env_keys)}"
    assert [key for key in whitelist if key.endswith(("_API_KEY", "_API_KEYS"))] == []
    assert {key for key in whitelist if not catalog.classify(key).writable} == set()

    for key in ("KIMI_API_KEY", "OPENAI_API_KEYS", "ANTHROPIC_API_KEY"):
        verdict = catalog.classify(key)
        assert verdict.writable is False
        assert verdict.reason is not None and verdict.reason in catalog.LABELS, key


# ── 2026-09-26：CLI 入口层收进 `heagent/cli/` 包（原七个平铺 ``cli*.py``）──


def test_cli_package_shell_stays_thin() -> None:
    """``heagent/cli/__init__.py`` 必须零 import。

    包一旦在 ``__init__`` 里导入子模块，``import heagent.cli.display``（GUI 的轻量用法）就会先执行
    ``console.py`` 的整条入口装配图（click + wiring + provider + engine），把「展示辅助」变成重型
    导入；同时包 ``__init__`` 会成为后端子模块函数体内延迟导入的必经节点，扩大既有的成环面。
    """
    tree = ast.parse((SRC / "cli" / "__init__.py").read_text(encoding="utf-8"))
    offenders = [node.lineno for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert offenders == [], f"cli/__init__.py 出现 import（第 {offenders} 行）——包壳必须保持零 import"


def test_cli_package_layout_is_pinned() -> None:
    """布局即契约：新增/重命名入口子模块必须同步本表与 frame.md 的目录树。"""
    actual = sorted(path.stem for path in (SRC / "cli").glob("*.py") if path.stem != "__init__")
    assert actual == [
        "composition",
        "console",
        "dialogs",
        "display",
        "goal",
        "housekeeping",
        "http",
        "http_console",
        "init",
        "interactive",
        "slash",
        "tcp",
        "terminal",
        "wiring",
    ]


def test_entrypoint_script_points_at_an_importable_module() -> None:
    """``[project.scripts]`` 的目标必须可导入且 ``main`` 可调用。

    这条断言的价值：入口点字符串是**纯文本**，改包结构时最容易漏——``heagent.cli:main`` 在
    ``cli/__init__.py`` 不再 re-export 之后会静默坏掉，直到有人真的敲 ``heagent`` 才发现。
    """
    pyproject = (SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^heagent = "([^"]+)"$', pyproject, re.MULTILINE)
    assert match is not None, "pyproject 里找不到 heagent 入口脚本声明"
    target = match.group(1)
    assert target == "heagent.cli.console:main", target
    module_name, _, attr = target.partition(":")
    assert callable(getattr(importlib.import_module(module_name), attr))


# ── 2026-09-26：公共层 ``pub/`` 与配置包 ``config/`` 的分层收敛（原顶层平铺模块）──


def test_shared_layer_layout_is_pinned() -> None:
    """布局即契约：``pub/``（零运行栈依赖）与 ``config/``（配置面）的文件清单。

    2026-09-26 自顶层平铺模块收敛为两个包：``pub/`` 收零依赖公共模块（任何层可依赖），
    ``heagent.config`` 收配置面四件套（依赖 ``pub``、被运行栈与入口层共同依赖）。
    2026-09-26 同日：``projects``（网页控制台项目注册表）自顶层迁入 ``pub/``——它零运行栈依赖，
    本就是数据面；network 侧仍**显式**禁导 ``heagent.pub.projects``（见下表 network 条目）。
    ``heagent.config`` 的名字**刻意保持不变**（模块 → 包）——``from heagent.config import Settings``
    这条最大宗的导入面因此零改动。新增/搬移模块必须同步本表与 ``docs/frame.md`` 的目录树。
    """
    pub_modules = sorted(path.stem for path in (SRC / "pub").glob("*.py") if path.stem != "__init__")
    config_modules = sorted(path.stem for path in (SRC / "config").glob("*.py") if path.stem != "__init__")

    assert pub_modules == [
        "exceptions",
        "frontmatter",
        "persist",
        "projects",
        "roles",
        "safe_logging",
        "task_shutdown",
        "types",
        "workspace",
    ]
    assert config_modules == ["catalog", "envfile", "write"]


def test_pub_package_shell_stays_thin() -> None:
    """``pub/__init__.py`` 必须零 import（与 ``cli/__init__.py`` 同款理由）。

    ``pub`` 是公共层：``from heagent.pub import types`` 不应该顺带把其余公共模块全拉起来。
    包壳一旦 import 子模块，「导入一个公共模块」的成本就不再可控。
    """
    tree = ast.parse((SRC / "pub" / "__init__.py").read_text(encoding="utf-8"))
    offenders = [node.lineno for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert offenders == [], f"pub/__init__.py 出现 import（第 {offenders} 行）——包壳必须保持零 import"


def test_config_package_only_depends_on_the_public_layer() -> None:
    """``config/__init__.py``（``Settings`` 本体）只许依赖 ``pub`` 与 stdlib/pydantic。

    它是原顶层 ``config.py`` 整体迁入的包壳，因此「包壳零 import」不适用（它就是实现本体），
    但**不得伸手进运行栈**——配置面一旦依赖 engine/agent，「配置」就成了运行栈的下游环路，
    入口层与运行栈共用同一份 Settings 的快照前提随之破坏。
    """
    forbidden = {
        "heagent.providers",
        "heagent.tools",
        "heagent.context",
        "heagent.engine",
        "heagent.agent",
        "heagent.memory",
        "heagent.cron",
        "heagent.events",
        "heagent.network",
        *_ENTRY_LAYER_MODULES,
    }
    runtime, _typing = _imports(SRC / "config" / "__init__.py")
    assert runtime & forbidden == set(), f"config/__init__.py: {sorted(runtime & forbidden)}"
