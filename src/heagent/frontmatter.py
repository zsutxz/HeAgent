"""共享 frontmatter 解析工具——收敛此前散落六处的手写解析器。

历史：``engine/artifacts.py``、``memory/skills.py``、``memory/skill_packages.py``（×2）、
``slash.py``、``roles.py`` 各自维护一份 ``---`` frontmatter 正则与键值解析，同一文档在
不同模块可能解析出不同结果（2026-09-17 勘察登记的架构债）。本模块把「分隔符识别 + 键值
拆分 + 标量 coercion」收敛为单一实现，调用方按各自的宽容度选用：

- **严档** :func:`parse_strict_pairs`——artifacts / skill_packages workflow 用：跳过空行与
  ``#`` 注释；无冒号、行首空白、重复或空 key 一律报错。
- **宽档** :func:`parse_inline_pairs`——skills / slash / roles / skill_packages metadata 用：
  已知键前缀匹配或任意 ``key: value`` 行，未知键忽略、永不报错。
- **标量** :func:`parse_scalar`——artifacts 的值 coercion（JSON/ast 尝试、引号剥壳、bool）。

DAG 定位：与 ``persist.py`` / ``roles.py`` 同层的**零 heagent 依赖顶层模块**（仅 stdlib），
任何模块可依赖；反向禁止——本文件不得 import heagent 的任何子模块。

有意保留**两个分隔符变体**，不做「统一」：EOF 变体允许 frontmatter 以 ``---`` + EOF 结尾
（无尾随换行的文件也能解析），换行变体要求闭合 ``---`` 后必须有换行。两者对 EOF 结尾文件
判定不同，统一会改变其中一侧的现有解析结果（违反「不改任何现有文档格式」边界）。
"""

from __future__ import annotations

import ast
import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

# 变体一（EOF）：闭合 ``---`` 后允许换行或文件结束。artifacts / skill_packages workflow 现状。
FRONTMATTER_EOF_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
# 变体二（换行）：闭合 ``---`` 后必须有换行。skills / slash / roles / metadata 现状
# （skills 另依赖其 match.end() 字节跨度做就地改写，行为不可变）。
FRONTMATTER_NEWLINE_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class FrontmatterSyntaxError(ValueError):
    """严档解析的结构错误（无冒号 / 行首空白 / 重复或空 key）。

    继承 ``ValueError``：调用方此前的异常契约建立在 ``ValueError`` 之上
    （``ArtifactContractError`` / workflow 的裸 ``ValueError``），换异常基类会破坏调用方捕获。
    """

    def __init__(self, kind: str, *, line_number: int = 0, line: str = "", key: str = "") -> None:
        super().__init__(kind)
        #: "invalid_line"（无冒号或行首空白）| "bad_key"（重复或空 key）
        self.kind = kind
        self.line_number = line_number
        self.line = line
        self.key = key


def split_frontmatter(text: str, *, closed_at_eof: bool = False) -> tuple[str, int, str] | None:
    """分离 frontmatter 块与正文；无 frontmatter 返回 ``None``。

    返回 ``(raw 块, match.end() 字节位, body)``——``match.end()`` 供 skills 的就地改写按
    字节跨度保留正文。``closed_at_eof`` 选择分隔符变体（见模块 docstring，两变体有意并存）。
    """
    match = (FRONTMATTER_EOF_RE if closed_at_eof else FRONTMATTER_NEWLINE_RE).match(text)
    if match is None:
        return None
    return match.group(1), match.end(), text[match.end() :]


def parse_strict_pairs(raw: str) -> dict[str, str]:
    """严档键值解析（artifacts / skill_packages workflow 历史语义）。

    逐行扫描 raw 块：跳过空行与 ``#`` 注释行；无冒号或行首空白 → :class:`FrontmatterSyntaxError`
    （kind=``invalid_line``）；重复或空 key → 同上（kind=``bad_key``）。返回 key → 冒号后的
    **原始未剥壳值**（strip / 引号 / 标量 coercion 交调用方按需做）。
    """
    values: dict[str, str] = {}
    for line_number, line in enumerate(raw.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line or line[:1].isspace():
            raise FrontmatterSyntaxError("invalid_line", line_number=line_number, line=line)
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or key in values:
            raise FrontmatterSyntaxError("bad_key", line_number=line_number, line=line, key=key)
        values[key] = value
    return values


def parse_inline_pairs(raw: str, keys: Sequence[str] = ()) -> dict[str, str]:
    """宽档键值解析（skills / slash / roles / metadata 历史语义），永不报错。

    ``keys`` 非空：逐行 strip 后按 ``startswith(f"{key}:")`` 前缀匹配，仅识别已知键
    （同行命中多个键取 ``keys`` 序序靠前者；重复键后行覆盖前行）。
    ``keys`` 为空：任意含冒号行按首个冒号拆分、key 取 strip（``_parse_metadata`` 历史语义，
    注释 / 缩进行不做特殊处理）。
    返回 key → 冒号后的**原始未剥壳值**。
    """
    pairs: dict[str, str] = {}
    for line in raw.splitlines():
        if keys:
            stripped = line.strip()
            for key in keys:
                if stripped.startswith(f"{key}:"):
                    pairs[key] = stripped.split(":", 1)[1]
                    break
        elif ":" in line:
            key, value = line.split(":", 1)
            pairs[key.strip()] = value
    return pairs


def parse_scalar(value: str) -> Any:
    """标量值 coercion（artifacts 历史语义）：JSON/ast 尝试、成对引号剥壳、bool，否则原样字符串。"""
    value = value.strip()
    if not value:
        return ""
    if value.startswith(("[", "{")):
        for parser in (json.loads, ast.literal_eval):
            try:
                return parser(value)
            except (ValueError, SyntaxError, json.JSONDecodeError):
                continue
    if (len(value) >= 2 and value[0] == value[-1]) and value[0] in "\"'":
        return value[1:-1]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


_H2_SECTION_RE = re.compile(r"(?m)^##\s+([^\n#]+?)\s*$")


def extract_h2_section(text: str, name: str) -> str:
    """Return the body of the ``## <name>`` section (case-insensitive); ``""`` when absent.

    段体从标题行结束处延伸到下一个 ``##`` 标题（或文本结束）并 strip；先剥去 frontmatter
    （NEWLINE 分隔符变体）。当前消费方是 goal 需求文档（``goal/document.py``）；
    ``engine/artifacts.py`` 的段提取另带 fence 跳过与重复/空段校验，语义不同，未收敛到此。
    """
    split = split_frontmatter(text)
    if split is not None:
        text = split[2]
    matches = list(_H2_SECTION_RE.finditer(text))
    wanted = name.casefold()
    for index, match in enumerate(matches):
        if match.group(1).casefold() != wanted:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return text[match.end() : end].strip()
    return ""
