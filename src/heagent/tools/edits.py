"""编辑原语支撑（P0-1）：行尾保真读写、diff 回执、落盘前快照。

``file_write`` / ``file_edit`` 共用本模块，解决三件事：

1. **行尾 / BOM 保真** —— :func:`read_text_file` / :func:`write_text_file` 走
   ``read_bytes`` / ``write_bytes``。``Path.read_text`` / ``Path.write_text`` 默认做
   universal-newline 翻译：Windows 上会把 LF 文件写成 CRLF、并把 CRLF 读成 LF。本仓
   2026-09-08 刚做过一次仓级行尾治理（``.gitattributes`` 声明 ``eol=lf``），编辑类工具若
   破坏行尾即是真实事故面——读写两侧都保真，才能保证「只改一处，其余字节不动」。
2. **diff 回执** —— :func:`render_diff` 生成 ``+N -M`` 与有界 hunk 预览：模型能自证
   「我到底改了什么」，用户能在回执里直接审阅，不必再补一次 ``git_diff``。
3. **落盘前快照** —— :func:`snapshot_before_write` 复制旧字节到
   ``<workspace>/.heagent/tmp/edit-snapshots/`` 并追加 ``manifest.jsonl`` 台账，为误改
   提供回滚依据（best-effort：快照失败绝不阻断一次合法编辑）。

⚠ 非安全边界（与 CLAUDE.md 立场一致）：行尾保真与快照都只是**可用性**护栏——快照目录
位于 workspace 内、可被 shell 删除，不提供防篡改或防丢失保证。
"""

from __future__ import annotations

import codecs
import difflib
import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

from heagent.tools.path_safety import workspace_root
from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

logger = logging.getLogger(__name__)

# UTF-8 BOM 字节前缀（保真读写用）。
_BOM = codecs.BOM_UTF8

# 单次快照体积上限：超过则跳过快照（不阻断编辑，回执里不出现 snapshot 行）。
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
# diff 比对源体积上限：超过则不读旧内容（difflib 对超大文件代价高），回执退化为计数。
MAX_DIFF_SOURCE_BYTES = 512 * 1024
# diff 回执双上限（行数 + 字符数）：防长 diff 刷爆上下文。
MAX_DIFF_LINES = 40
MAX_DIFF_CHARS = 4000
# 快照目录（相对 workspace 根的相对路径）：与 sandbox 会话目录同属 .heagent/tmp 运行态产物。
SNAPSHOT_DIRNAME = "edit-snapshots"
# manifest 文件名（append-only JSONL，一行一次编辑）。
MANIFEST_NAME = "manifest.jsonl"

_snapshot_run = RuntimeSlot[str]("heagent_edit_snapshot_run")


class TextFile(BaseModel):
    """一次「保真读取」的结果。

    ``text`` 已把行尾归一为 ``\\n``（供匹配与编辑），``newline`` / ``has_bom`` 记录原始
    形态以便原样写回。
    """

    text: str
    newline: str = "\n"
    has_bom: bool = False


def read_text_file(path: Path) -> TextFile:
    """按字节读取文件并归一为 ``\\n``，同时记住原行尾与 BOM。

    行尾判定：``\\r\\n`` 计数非零且不存在单独 ``\\n`` → 纯 CRLF（``newline="\\r\\n"``）；
    其余（纯 LF / 混合）→ ``"\\n"``。混合行尾文件在此归一为 LF（罕见情形，显式取 LF 更
    可预测，不会把孤立 ``\\n`` 也改写成 CRLF）。
    """
    raw = path.read_bytes()
    has_bom = raw.startswith(_BOM)
    if has_bom:
        raw = raw[len(_BOM) :]
    text = raw.decode("utf-8")
    crlf = raw.count(b"\r\n")
    lone_lf = raw.count(b"\n") - crlf
    newline = "\r\n" if crlf and not lone_lf else "\n"
    return TextFile(text=text.replace("\r\n", "\n"), newline=newline, has_bom=has_bom)


def write_text_file(path: Path, text: str, *, newline: str = "\n", has_bom: bool = False) -> None:
    """按 ``newline`` / ``has_bom`` 原样写回（不触发平台行尾翻译）。

    ``text`` 内部若夹杂 ``\\r\\n`` 会先归一为 ``\\n`` 再统一展开，避免出现 ``\\r\\r\\n``。
    """
    normalized = text.replace("\r\n", "\n")
    payload = normalized.replace("\n", "\r\n") if newline == "\r\n" else normalized
    data = payload.encode("utf-8")
    path.write_bytes(_BOM + data if has_bom else data)


def render_diff(old_text: str, new_text: str, *, max_lines: int = MAX_DIFF_LINES) -> str:
    """渲染 ``+N -M`` 与有界 hunk 预览（无变化时返回 ``no content change``）。

    截断是**有界且有标注**的：行数超限追加 ``… (+N more diff lines)``，字符数超限追加
    ``… (diff truncated)``——调用方拿到的一定是可直接进上下文的短回执。
    """
    if old_text == new_text:
        return "no content change"
    added = removed = 0
    hunks: list[str] = []
    for line in difflib.unified_diff(old_text.splitlines(), new_text.splitlines(), n=2, lineterm=""):
        if line.startswith(("+++", "---")):
            continue  # 文件头不是内容变更，不计入 +N/-M
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
        hunks.append(line)

    body = "\n".join(hunks[:max_lines])
    if len(body) > MAX_DIFF_CHARS:
        body = body[:MAX_DIFF_CHARS] + "\n… (diff truncated)"
    if len(hunks) > max_lines:
        body += f"\n… (+{len(hunks) - max_lines} more diff lines)"
    return f"+{added} -{removed}\n{body}"


def render_new_file(new_text: str) -> str:
    """新文件的回执行（不做 hunk 展开——全文即全部新增，展开无信息量）。"""
    return f"new file, {len(new_text.splitlines())} lines"


def snapshot_root() -> Path:
    """当前 run 的快照目录；无 run 绑定时退化为工作区级的共享目录。"""
    base = workspace_root() / ".heagent" / "tmp" / SNAPSHOT_DIRNAME
    run_id = _snapshot_run.get()
    return base / run_id if run_id else base


@contextmanager
def bind_edit_snapshot_run(run_id: str | None) -> Iterator[None]:
    """把快照目录绑定到当前 run（由 :meth:`AgentLoop._runtime_scope` 每 run 进出）。

    绑定后同一 run 的编辑产物集中在 ``edit-snapshots/<run_id>/``；未绑定（直接调工具、
    子进程、测试）时统一落工作区级 ``edit-snapshots/``——不因缺少 run 上下文而放弃留痕。
    """
    with _snapshot_run.bind(run_id):
        yield


def snapshot_before_write(path: Path, *, op: str) -> str | None:
    """落盘前把 ``path`` 现有字节复制到快照目录，并追加一行 manifest 台账。

    返回**相对 workspace 根**的快照路径（用于回执展示）。以下情形返回 ``None``：文件
    不存在（新建，无可丢内容）、超过 :data:`MAX_SNAPSHOT_BYTES`、任何 I/O 异常
    （best-effort——快照失败绝不能阻断一次合法编辑，仅记日志）。
    """
    try:
        if not path.is_file():
            return None
        size = path.stat().st_size
        if size > MAX_SNAPSHOT_BYTES:
            logger.debug("edit snapshot skipped for %s: %d bytes exceeds cap", path, size)
            return None
        root = snapshot_root()
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = root / f"{stamp}-{uuid.uuid4().hex[:8]}-{path.name}.bak"
        target.write_bytes(path.read_bytes())
        _append_manifest(root, path=path, snapshot=target, op=op, size=size)
        return display_path(target)
    except Exception as exc:
        logger.warning("edit snapshot failed for %s: %s", path, exc)
        return None


def display_path(target: Path) -> str:
    """优先返回相对 workspace 根的 POSIX 风格路径（回执更短、可跨平台阅读）。"""
    try:
        return target.relative_to(workspace_root()).as_posix()
    except ValueError:
        return str(target)


def _append_manifest(root: Path, *, path: Path, snapshot: Path, op: str, size: int) -> None:
    """追加一行 JSON 台账（一行一次写，best-effort；并发下最坏情况是行交错丢失）。"""
    record = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "op": op,
        "path": str(path),
        "snapshot": str(snapshot),
        "bytes": size,
    }
    with (root / MANIFEST_NAME).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
