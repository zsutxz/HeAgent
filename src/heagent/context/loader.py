"""上下文文件扫描器 — 从项目目录加载上下文文件注入系统提示词。

分层发现语义（对齐 Codex 的 ``AGENTS.md`` 约定）：

1. **仓库边界**：自 ``cwd`` 向上逐级查找仓库标记（``.git`` / ``.hg``）；命中即把该级纳入
   并**停止上溯**（该级即仓库根）。不在仓库内时只扫 ``cwd`` 一层——既有行为逐字节不变。
2. **层序由泛到专**：仓库根在前、``cwd`` 在后（越靠近 cwd 越具体）；同一层内保持既有优先级
   ``.heagent/CONTEXT.md`` > ``AGENTS.md`` > ``CLAUDE.md``。
3. **可选用户级文件**：``~/.heagent/AGENTS.md``（``CONTEXT_FILES_USER_LEVEL``，**默认关闭**），
   排在最前（最泛）。默认关闭是刻意的：全局文件会静默影响每个项目，且会让测试依赖开发机 home。
4. **字节预算**：``CONTEXT_FILES_MAX_BYTES``（默认 32768）。超预算时**近端优先**保留（越靠近
   cwd 越具体）；被截断 / 被丢弃的文件以显式标记 + warning 回报，**绝不静默**。

每段以相对最外层目录的路径作标题（``## sub/AGENTS.md``），段落间以 ``---`` 分隔。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

# 同一目录内的扫描优先级（高 → 低），沿用既有约定，未变更。
_CONTEXT_FILES: list[str] = [
    ".heagent/CONTEXT.md",
    "AGENTS.md",
    "CLAUDE.md",
]

# 仓库边界标记：命中即视为仓库根并停止上溯。
_REPO_MARKERS: tuple[str, ...] = (".git", ".hg")

# 上溯层数上限（含起始目录）。超限即退化为单层扫描——不做无界上溯（深目录树上会捞到无关文件）。
_MAX_LEVELS = 8

# 允许的最小「截断保留」预算：低于此值整段丢弃，不产出几十字节的无意义残片。
_MIN_PARTIAL_BYTES = 1024

# 用户级上下文文件（相对 home）。
_USER_CONTEXT_REL = ".heagent/AGENTS.md"

# 省略说明行里最多列举的文件数（其余折叠为计数，避免说明行本身失控）。
_OMISSION_LABEL_LIMIT = 10


class ContextFile(BaseModel):
    """一份被纳入的上下文文件。"""

    # 段落标题与去重键：相对最外层目录的 POSIX 路径（用户级固定为 ``~/.heagent/AGENTS.md``）。
    label: str
    # 文件绝对路径（仅用于诊断，不进提示词）。
    path: str
    content: str
    # 该段是否被预算截断（头部保留 + 显式标记）。
    truncated: bool = False


class ContextBundle(BaseModel):
    """一次分层扫描的结果（结构化，供调用方与测试断言层序 / 预算行为）。"""

    files: list[ContextFile] = Field(default_factory=list)
    # 因预算被整段丢弃的 label（按层序由外到内）。
    omitted: list[str] = Field(default_factory=list)
    # 省略说明行（为空表示无省略）；由 :meth:`render` 追加在末尾。
    omitted_note: str = ""
    # 最终渲染串的 UTF-8 字节数（含省略说明行）；无文件时为 0。
    bytes_used: int = 0

    @property
    def truncated(self) -> bool:
        """是否有段落被截断或被丢弃。"""
        return bool(self.omitted) or any(f.truncated for f in self.files)

    @property
    def empty(self) -> bool:
        """是否未命中任何上下文文件。"""
        return not self.files

    def render(self) -> str | None:
        """渲染为注入用的文本；无文件时返回 None（不注入空块）。"""
        if not self.files:
            return None
        parts = [f"## {item.label}\n\n{item.content}" for item in self.files]
        text = "\n\n---\n\n".join(parts)
        if self.omitted_note:
            text = f"{text}\n\n---\n\n{self.omitted_note}"
        return text


def _read_text(path: Path) -> str | None:
    """读取并 strip 文件内容；不存在 / 非文件 / 空白内容返回 None。

    坏编码（二进制文件）按不可读处理并告警——上下文文件的读取失败不得打断 agent 运行。
    """
    try:
        if not path.is_file():
            return None
        content = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        logger.warning("Failed to read context file %s", path, exc_info=True)
        return None
    return content or None


def _repo_root(start: Path, *, max_levels: int) -> Path | None:
    """返回 ``start`` 或其祖先中最近的含仓库标记的目录；``max_levels`` 内未找到返回 None。"""
    current = start
    for _ in range(max_levels + 1):
        if any((current / marker).exists() for marker in _REPO_MARKERS):
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def _level_dirs(start: Path, *, max_levels: int) -> list[Path]:
    """返回由外到内的目录链 ``[仓库根, …, start]``；不在仓库内时为 ``[start]``。"""
    root = _repo_root(start, max_levels=max_levels)
    if root is None or root == start:
        return [start]
    chain: list[Path] = []
    current = start
    while current != root:
        chain.append(current)
        current = current.parent
    chain.append(root)
    chain.reverse()
    return chain


def _label(directory: Path, rel: str, outermost: Path) -> str:
    """段落标题：相对最外层目录的 POSIX 路径（最外层即 ``rel`` 本身，与旧行为一致）。"""
    try:
        return (directory / rel).relative_to(outermost).as_posix()
    except ValueError:
        return rel


def _slice_bytes(text: str, budget: int) -> str:
    """按 UTF-8 字节截断文本（不切坏多字节字符）。"""
    if budget <= 0:
        return ""
    raw = text.encode("utf-8")
    if len(raw) <= budget:
        return text
    # errors="ignore"：丢弃结尾被切断的半个多字节字符，保证解码结果仍是合法 UTF-8。
    return raw[:budget].decode("utf-8", errors="ignore")


def _truncation_marker(kept: int, total: int) -> str:
    return f"\n\n… (truncated — kept the first {kept} of {total} bytes)"


def _fit_section(section: str, budget: int) -> str | None:
    """预算内放下整段；放不下但预算可观时保留头部并加标记；否则返回 None（整段丢弃）。

    标记长度按**悲观值**（``total``，即 kept 的上界）预留，故单次计算即保证结果不超预算。
    只做「头部保留 + 显式标记」，不做语义压缩——被丢内容一律可见。
    """
    total = len(section.encode("utf-8"))
    if total <= budget:
        return section
    if budget < _MIN_PARTIAL_BYTES:
        return None
    reserved = len(_truncation_marker(total, total).encode("utf-8"))
    kept = _slice_bytes(section, max(budget - reserved, 0))
    return kept + _truncation_marker(len(kept.encode("utf-8")), total)


def _omission_note(omitted: Iterable[str], limit: int) -> str:
    """构造省略说明行（显式列出被丢弃的文件与预算值，供用户调高预算）。"""
    labels = list(omitted)
    listed = ", ".join(labels[:_OMISSION_LABEL_LIMIT])
    if len(labels) > _OMISSION_LABEL_LIMIT:
        listed += f", … (+{len(labels) - _OMISSION_LABEL_LIMIT} more)"
    return (
        f"(context files omitted: {len(labels)} — CONTEXT_FILES_MAX_BYTES={limit} exhausted; "
        f"raise the budget to include: {listed})"
    )


def collect_context_files(
    cwd: str | None = None,
    *,
    max_bytes: int | None = None,
    user_level: bool | None = None,
    home: Path | None = None,
    max_levels: int = _MAX_LEVELS,
) -> ContextBundle:
    """分层收集上下文文件并按字节预算裁剪（纯读，不注入）。

    参数：
        cwd: 起始目录，默认当前工作目录
        max_bytes: 字节预算；None 时取 ``Settings.context_files_max_bytes``
        user_level: 是否纳入用户级文件；None 时取 ``Settings.context_files_user_level``
        home: 用户级文件的 home 根（测试注入用），默认 ``Path.home()``
        max_levels: 上溯层数上限（含起始目录）
    返回：
        结构化结果 :class:`ContextBundle`（无命中时 ``files`` 为空）
    """
    # 惰性 import：context 层其余模块均不依赖 config，此处保持同样的导入期零耦合。
    from heagent.config import get_settings

    settings = get_settings()
    limit = settings.context_files_max_bytes if max_bytes is None else max_bytes
    include_user = settings.context_files_user_level if user_level is None else user_level

    start = Path(cwd or ".").resolve()
    dirs = _level_dirs(start, max_levels=max_levels)
    outermost = dirs[0]
    logger.debug("Context level chain (outermost → cwd): %s", [str(d) for d in dirs])

    labels: list[str] = []
    paths: list[str] = []
    contents: list[str] = []
    if include_user:
        user_path = (home if home is not None else Path.home()) / _USER_CONTEXT_REL
        user_text = _read_text(user_path)
        if user_text is not None:
            # 标题固定为 ``~`` 形式：不把开发机 home 绝对路径泄进提示词。
            labels.append(f"~/{_USER_CONTEXT_REL}")
            paths.append(str(user_path))
            contents.append(user_text)

    for directory in dirs:
        for rel in _CONTEXT_FILES:
            text = _read_text(directory / rel)
            if text is None:
                continue
            labels.append(_label(directory, rel, outermost))
            paths.append(str(directory / rel))
            contents.append(text)

    sections = [f"## {label}\n\n{content}" for label, content in zip(labels, contents, strict=True)]
    kept: dict[int, str] = {}
    omitted: list[str] = []
    remaining = limit
    # 由近到远分配预算：越靠近 cwd 的项目文件越具体，优先保留。
    for index in reversed(range(len(sections))):
        fitted = _fit_section(sections[index], remaining)
        if fitted is None:
            omitted.append(labels[index])
            continue
        kept[index] = fitted
        remaining -= len(fitted.encode("utf-8"))
    omitted.reverse()

    files = [
        ContextFile(
            label=labels[index],
            path=paths[index],
            content=_body(kept[index], labels[index]),
            truncated=kept[index] != sections[index],
        )
        for index in sorted(kept)
    ]
    bundle = ContextBundle(
        files=files,
        omitted=omitted,
        omitted_note=_omission_note(omitted, limit) if omitted else "",
    )
    rendered = bundle.render()
    bundle.bytes_used = len(rendered.encode("utf-8")) if rendered else 0
    if bundle.truncated:
        logger.warning(
            "Context files exceeded CONTEXT_FILES_MAX_BYTES=%d: omitted=%s truncated=%s",
            limit,
            omitted,
            [item.label for item in files if item.truncated],
        )
    return bundle


def _body(section: str, label: str) -> str:
    """从渲染段落里取回正文（截断发生在尾部，故头部标题前缀恒定可剥离）。"""
    header = f"## {label}\n\n"
    return section[len(header) :] if section.startswith(header) else section


def load_context_files(
    cwd: str | None = None,
    *,
    max_bytes: int | None = None,
    user_level: bool | None = None,
    home: Path | None = None,
    max_levels: int = _MAX_LEVELS,
) -> str | None:
    """分层扫描上下文文件，按优先级与字节预算合并返回；无文件时返回 None。

    参数与 :func:`collect_context_files` 一致（本函数是其渲染包装）。
    """
    return collect_context_files(
        cwd,
        max_bytes=max_bytes,
        user_level=user_level,
        home=home,
        max_levels=max_levels,
    ).render()
