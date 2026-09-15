"""事件 JSONL 接收器 + rollout 落盘 / 回放（``--json`` 传输层）。

三件事：

1. :class:`JsonlSink` —— 订阅 :class:`~heagent.engine.observability.EventBus`，把事件写成 JSONL：
   可只写 stdout（``--json``）、只落盘（``EVENTS_ROLLOUT_ENABLED``），或两者都做。
2. :func:`read_rollout` —— 读回 rollout / 任意 JSONL 事件文件。
3. :func:`render_event` —— 把事件渲染成人读单行（``heagent replay`` 用）。

⚠ 落盘与 stdout 输出的内容含命令、文件路径与工具原始返回（含 MCP / 远端内容），与工具返回
**同等不可信**；且 rollout 属项目内部状态（``.heagent/`` 已被 gitignore，path_safety 亦对内
部状态文件设读拒）——不得改写到可提交路径。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from heagent.events.protocol import ASSISTANT_MESSAGE_KIND, RunEvent, from_engine_event, make_event

if TYPE_CHECKING:
    from typing import TextIO

    from heagent.engine.observability import EngineEvent

logger = logging.getLogger(__name__)

# rollout 根目录（相对进程 cwd）与文件名。
ROLLOUT_DIRNAME = Path(".heagent") / "runs"
ROLLOUT_FILENAME = "rollout.jsonl"
# run_id 缺失时的兜底分片名（正常路径不会用到：run_started 起就带 run_id）。
_UNKNOWN_RUN_DIR = "unknown"


def default_rollout_dir(root: Path | None = None) -> Path:
    """rollout 根目录 ``<root>/.heagent/runs``（默认取进程 cwd）。"""
    return (root or Path.cwd()) / ROLLOUT_DIRNAME


class JsonlSink:
    """把引擎事件写成 JSONL 的观察者（stdout 流与 rollout 文件相互独立、可任选）。

    实现约束：

    * ``handle`` 由 :meth:`EventBus.emit` 在调用方协程内**同步**派发，协议要求不得阻塞——
      因此这里只做「内存序列化 + 一次 write/flush」，不做压缩、轮转或额外 I/O。
    * rollout 按 ``<rollout_dir>/<run_id>/rollout.jsonl`` 分片：**每个 run 一个文件 ⇒ 单写者**，
      无需跨进程锁；同一 run_id 复跑（resume）为顺序追加。
    * 写盘失败只告警，不影响主循环（可观测性故障不得中断 agent 运行）。
    """

    def __init__(self, *, stream: TextIO | None = None, rollout_dir: Path | None = None) -> None:
        self._stream = stream
        self._rollout_dir = rollout_dir
        self._seq = 0
        self._last_run_id = ""

    @property
    def seq(self) -> int:
        """已写出的事件条数（同时也是最后一条的 ``seq``）。"""
        return self._seq

    @property
    def last_run_id(self) -> str:
        """最近一条事件携带的 ``run_id``（用于回填传输层补充事件）。"""
        return self._last_run_id

    @property
    def writes_stdout(self) -> bool:
        """是否输出到 stdout 流。"""
        return self._stream is not None

    @property
    def writes_rollout(self) -> bool:
        """是否落盘 rollout。"""
        return self._rollout_dir is not None

    def handle(self, event: EngineEvent) -> None:
        """总线回调：映射并写出一个引擎事件。"""
        if event.run_id:
            self._last_run_id = event.run_id
        self._write(from_engine_event(event, seq=self._next_seq()))

    def assistant_message(self, content: str) -> RunEvent:
        """写出最终答案（本传输层补充的**唯一**事件；引擎侧无对应事件）。

        在 ``run_completed`` / ``run_failed`` 之后调用，使 ``--json`` 流与 rollout 回放
        都能看到「这一轮最后说了什么」。
        """
        event = make_event(
            ASSISTANT_MESSAGE_KIND,
            seq=self._next_seq(),
            run_id=self._last_run_id,
            details={"content": content, "content_length": len(content)},
        )
        self._write(event)
        return event

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _write(self, event: RunEvent) -> None:
        line = event.to_jsonl()
        if self._stream is not None:
            self._stream.write(f"{line}\n")
            self._stream.flush()
        if self._rollout_dir is not None:
            self._append(self._rollout_dir, event.run_id, line)

    def _append(self, rollout_dir: Path, run_id: str, line: str) -> None:
        path = rollout_dir / (run_id or _UNKNOWN_RUN_DIR) / ROLLOUT_FILENAME
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # newline="\n"：JSONL 必须 LF，禁止平台行尾翻译（Windows 上会变 CRLF）。
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"{line}\n")
        except OSError:
            logger.warning("Failed to append rollout line to %s", path, exc_info=True)


def read_rollout(path: Path) -> list[RunEvent]:
    """读取 rollout / JSONL 事件文件。

    无法解析的行**跳过并告警**（crash 截断的尾行不应毁掉整次回放），空行忽略。
    """
    events: list[RunEvent] = []
    skipped = 0
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            events.append(RunEvent.model_validate_json(line))
        except ValidationError:
            skipped += 1
            logger.warning("Skipped malformed rollout line %d in %s", lineno, path)
    if skipped:
        logger.warning("Rollout %s: %d malformed line(s) skipped", path, skipped)
    return events


def render_event(event: RunEvent) -> str:
    """把一条事件渲染成人读单行（``replay`` 用；最终答案渲染为原文多行）。"""
    if event.kind == ASSISTANT_MESSAGE_KIND:
        return f"{event.ts} [assistant_message]\n{event.details.get('content', '')}"
    parts = [f"{event.ts} [{event.kind}]"]
    if event.run_id:
        parts.append(f"run={event.run_id}")
    if event.iteration:
        parts.append(f"iter={event.iteration}")
    if event.tool:
        parts.append(f"{event.tool} → {event.target}" if event.target else event.tool)
    if event.details:
        parts.append(json.dumps(event.details, ensure_ascii=False, default=str))
    return " ".join(parts)
