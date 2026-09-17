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
from heagent.engine.workflow import _iso_now as workflow_iso_now
from heagent.events.protocol import _now_iso as events_now_iso

if TYPE_CHECKING:
    from collections.abc import Iterator

SRC = Path(__file__).resolve().parents[1] / "src" / "heagent"

# 包 → 运行期不得导入的 heagent 子模块（CLAUDE.md「硬约束（违反即架构错误）」）。
FORBIDDEN_RUNTIME_IMPORTS: dict[str, tuple[str, ...]] = {
    "providers": ("heagent.agent",),
    "tools": ("heagent.agent",),
    "engine": ("heagent.agent",),
    "memory": ("heagent.agent",),
    "context": ("heagent.agent",),
    "cron": ("heagent.agent",),
    # events/ 是事件传输层，运行期零 engine 依赖（引擎类型仅出现在 TYPE_CHECKING 里）。
    "events": ("heagent.agent", "heagent.engine"),
}


def _heagent_root(module: str | None) -> str:
    parts = (module or "").split(".")
    return f"heagent.{parts[1]}" if parts[0] == "heagent" and len(parts) > 1 else ""


def _imports(path: Path) -> tuple[set[str], set[str]]:
    """返回 ``(运行期导入的 heagent 子模块, TYPE_CHECKING 内导入的)``。

    区分两者是必要的：``events/protocol.py`` 有意在 ``TYPE_CHECKING`` 下引用引擎类型（类型注解
    需要、运行期不需要），若把类型期导入也算违反，这条契约就只能靠放宽来维持。
    函数体内的局部导入**算**运行期依赖——它同样构成模块间的层次耦合。
    """
    runtime: set[str] = set()
    typing_only: set[str] = set()

    def record(node: ast.stmt, bucket: set[str]) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = _heagent_root(alias.name)
                if root:
                    bucket.add(root)
        elif isinstance(node, ast.ImportFrom):
            root = _heagent_root(node.module)
            if root:
                bucket.add(root)

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

    walk(ast.parse(path.read_text(encoding="utf-8")).body, runtime)
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
    TYPE_CHECKING 引用；engine→memory 的合法边是 ``workflow_runner`` 对 ``skill_packages``
    资源模型的单向依赖）。
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
      - ``engine.workflow._iso_now``：**微秒**精度（源码里显式写 ``timespec="microseconds"``，用途是
        状态迁移的 ``updated_at``）。它是否需要亚秒分辨率没有测试或注释佐证，故本测试**不锁定**其精度。

    真正会出事的是 **naive 与否**：某处一旦带上 tzinfo，与存量 naive 状态（checkpoint / rollout /
    ledger 记录）比较就会 ``TypeError``——``ledger._parse_iso_to_naive`` 正是为抹平这种混用而存在。
    """
    for name, factory in (
        ("engine.context.iso_now", iso_now),
        ("engine.workflow._iso_now", workflow_iso_now),
        ("events.protocol._now_iso", events_now_iso),
    ):
        value = factory()
        assert datetime.fromisoformat(value).tzinfo is None, f"{name} 不再是 naive：{value!r}"

    # 同一格式的一对独立实现：格式必须一致（任一处改精度/加时区即红）。
    seconds = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
    for name, factory in (("engine.context.iso_now", iso_now), ("events.protocol._now_iso", events_now_iso)):
        assert seconds.match(factory()), f"{name} 与另一处不再同格式：{factory()!r}"
