"""架构契约的可执行断言。

把只写在 ``CLAUDE.md`` / docstring 里的**硬约束**钉成测试——它们此前只靠人工 grep 与「记得同步」
维持（本仓库已有先例：``_READ_ONLY_TOOLS`` 双份靠测试锁一致）。这类断言的价值不在发现今天的错误，
而在**拒绝明天的静默漂移**。
"""

from __future__ import annotations

import ast
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

# 真实子包名（大小写敏感）：用于识别 ``from heagent import <子包>`` 形态。
# 不能直接用 ``(SRC / name).is_dir()``——Windows 文件系统大小写不敏感，
# ``from heagent import Agent``（包根符号再导出）会被误判成 ``heagent/agent`` 子包。
_SUBPACKAGE_NAMES = frozenset(path.name for path in SRC.iterdir() if path.is_dir())

# 包 → 运行期不得导入的 heagent 子模块（CLAUDE.md「硬约束（违反即架构错误）」）。
# 入口层模块（wiring/cli/cli_goal/cli_tcp/gui）：组合根与展示适配只属于入口层，下层一律不得
# 反向导入（Phase 1 组合根收敛的契约化；新增入口模块须同步此表）。
_ENTRYPOINT_MODULES = ("heagent.wiring", "heagent.cli", "heagent.cli_goal", "heagent.cli_tcp", "heagent.gui")

FORBIDDEN_RUNTIME_IMPORTS: dict[str, tuple[str, ...]] = {
    "providers": ("heagent.agent", *_ENTRYPOINT_MODULES),
    "tools": ("heagent.agent", *_ENTRYPOINT_MODULES),
    # goal/ 是入口层域模块（cli_goal 的装载/文档层），下层不得反向导入。
    "engine": ("heagent.agent", "heagent.goal", *_ENTRYPOINT_MODULES),
    "memory": ("heagent.agent", "heagent.engine", "heagent.goal", *_ENTRYPOINT_MODULES),
    "context": ("heagent.agent", *_ENTRYPOINT_MODULES),
    "cron": ("heagent.agent", *_ENTRYPOINT_MODULES),
    # events/ 是事件传输层，运行期零 engine 依赖（引擎类型仅出现在 TYPE_CHECKING 里）。
    "events": ("heagent.agent", "heagent.engine", *_ENTRYPOINT_MODULES),
    # network/ 是入口传输层（Epic 48）：只承载 framing / 协议 / 连接生命周期，运行期不得伸手进
    # 运行时栈——Provider/Engine/AgentLoop 的装配是入口层（cli/wiring/cli_tcp）单向伸手。
    "network": (
        "heagent.agent",
        "heagent.engine",
        "heagent.providers",
        "heagent.tools",
        "heagent.memory",
        "heagent.context",
        "heagent.cron",
        "heagent.events",
        *_ENTRYPOINT_MODULES,
    ),
    # agent/ 是运行栈顶：不得导入任何入口层（组装是入口层单向伸手，不是运行栈反向伸手）。
    "agent": _ENTRYPOINT_MODULES,
}


def _heagent_root(module: str | None) -> str:
    parts = (module or "").split(".")
    return f"heagent.{parts[1]}" if parts[0] == "heagent" and len(parts) > 1 else ""


def _imported_roots(node: ast.Import | ast.ImportFrom) -> set[str]:
    """把一条 import 语句映射为「heagent 子模块」集合（两种等价写法同样处理）。

    ``import heagent.providers.router``（子模块在 ``node.module`` 上）与
    ``from heagent import providers``（子模块在 alias 上）必须都被识别——此前只识别前者，
    后者可用于绕过反向依赖断言。只把**真实存在的子包名**计入，避免误伤
    ``from heagent import Agent`` 这类包根符号再导出。
    """
    if isinstance(node, ast.Import):
        return {root for alias in node.names if (root := _heagent_root(alias.name))}
    if node.module == "heagent":
        return {f"heagent.{alias.name}" for alias in node.names if alias.name in _SUBPACKAGE_NAMES}
    root = _heagent_root(node.module)
    return {root} if root else set()


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
    只把**真实存在的子包目录**计入，避免误伤 ``from heagent import Agent`` 这类包根符号再导出。
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
            offenders.extend(f"{rel} → {target}" for target in forbidden if target in runtime)
    assert offenders == [], "运行期反向依赖：" + ", ".join(offenders)


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

    assert runtime == {"heagent.providers", "heagent.tools"}
    assert typing_only == {"heagent.agent"}


def test_forbidden_import_detection_ignores_package_root_symbol_reexports() -> None:
    """``from heagent import Agent`` 是包根符号再导出，不是子包依赖（不得误伤）。"""
    runtime, typing_only = _module_imports("from heagent import Agent, Settings\n")

    assert runtime == set()
    assert typing_only == set()


def test_frontmatter_parsing_is_centralized() -> None:
    """frontmatter 分隔正则只允许出现在共享模块 ``frontmatter.py`` 中。

    2026-09-17 勘察发现六处手写 ``---`` frontmatter 解析器各自漂移（同一文档在不同模块
    可能解析出不同结果），已收敛为 ``heagent.frontmatter``。此断言拒绝「明天又有人就地
    手写一份」的静默回退——新增解析需求必须走共享模块。
    """
    needle = "---\\s*\\n"  # 源码中正则字面量的原始字符序列
    offenders = [
        path.relative_to(SRC).as_posix()
        for path in sorted(SRC.rglob("*.py"))
        if path.name != "frontmatter.py" and needle in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], "frontmatter 正则漂移出共享模块 heagent.frontmatter：" + ", ".join(offenders)


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
    ``goal/application``；用户可见文案以结构化 outcome（messages）携带、由 cli_goal
    统一渲染。该模块一旦 import ``click`` / ``heagent.cli*`` / ``heagent.gui*``，
    use-case 就再也离不开 Click 环境（test.md Phase 3 验收「同一 workflow use-case
    可在无 Click 环境下运行」），GUI 原生渲染的演进路径也被焊死。``goal/naming.py``
    的 click.echo 是入口侧回退提示，不属 use-case，不在本契约内。
    """
    forbidden_prefixes = ("heagent.cli", "heagent.gui", "heagent.wiring")

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
    allowed = {"tools/path_safety.py", "persist.py"}
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
