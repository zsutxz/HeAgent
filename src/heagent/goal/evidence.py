"""结构化执行证据：版本化模型、追加式存储与受治理执行结果的证据化。

**为什么在引擎而非声明**（AD-14 证明，Story 51-3）：「执行结果 → 证据」是运行期数据
通道——Markdown 声明只能表达**要什么**证据（``validation:`` 子句），无法承载记录本体、
输出 digest 与脱敏。模型因此落在本模块，词汇保持通用：不认识任何具体 Epic / Story /
步骤（AD-13）。

三条硬边界：

1. **证据只从受治理执行结果生成**（AD-6）：:func:`build_command_evidence` 只消费
   ``ToolExecutor`` 链路产出的 :class:`~heagent.pub.types.ToolCall` /
   :class:`~heagent.pub.types.ToolResult`，本模块**从不**自行执行命令（只读 Git 查询在
   :mod:`heagent.goal.git_port`，是白名单内的确定性只读子进程查询，不经 ToolExecutor、
   也不是模型可调用的工具入口）。
2. **追加式**：:class:`EvidenceStore` 对同一 ``evidence_id`` 的第二次写入显性报错
   （独占创建，并发写只有一家成功），重跑不得覆盖历史；报告（Markdown）只能引用
   ``evidence_id``，:meth:`EvidenceStore.resolve` 是唯一取回通道——非 id 字符串（含拼凑的
   原始 dict 文本）解析不到记录即报错，无法伪装；``schema_version`` 不为当前版本同样拒绝。
3. **脱敏与上限**：命令与输出摘须经 :func:`~heagent.pub.safe_logging.redact_secrets`
   启发式脱敏并截断到有界长度，明文凭证不进证据；输出只留 digest（可复算完整性）+
   有界摘要。脱敏是启发式、非安全边界（与 ``safe_logging`` 同一立场），须 OS 级沙箱兜底。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final
from uuid import uuid4

from pydantic import BaseModel, Field

from heagent.pub.persist import load_json_model
from heagent.pub.safe_logging import redact_secrets
from heagent.tools.call_summary import summarize_tool_call

if TYPE_CHECKING:
    from heagent.pub.types import ToolCall, ToolResult

EVIDENCE_SCHEMA_VERSION = "1"

# 受治理 shell 结果的超时标记（tools/sandbox/process.py 的 _TIMEOUT_RESULT 文案；
# tests/test_goal_evidence.py 有判据钉住两者不漂移）。
_TIMEOUT_MARKING = "Command timed out"
# 摘要上限：证据只留「可定位 + 可复核」的最小文本——完整输出以 digest 存在，
# 有界脱敏摘要供人读，防巨型输出把证据文件与报告撑爆（验收：输出有大小上限）。
_MAX_COMMAND_CHARS = 500
_MAX_OUTPUT_SUMMARY_CHARS = 2000
# 有界摘要的截断标记（**公开常量**）：goal/quality_gates 的命令身份匹配也消费它，
# 两侧同源（Story 51-4 review #19——跨模块私有导入收敛为公开单一真源）。
TRUNCATION_MARKER = "…[truncated]"
# evidence id 白名单：单个路径安全名（charset 已排除路径分隔符与 ``.``，``..`` / 子目录
# / Windows 盘符写法全部进不来），另拒 Windows 保留设备名（``con.json`` 一类在 Windows
# 上根本无法创建，提前显性报错而不是留到落盘时炸）。
_EVIDENCE_ID_PATTERN = re.compile(r"[0-9A-Za-z_-]+")
_WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{index}" for index in range(1, 10)), *(f"lpt{index}" for index in range(1, 10))}
)


class EvidenceError(ValueError):
    """Raised when evidence cannot be recorded, located, or legitimately bound."""


#: :meth:`EvidenceStore.list_records` 的过滤维度缺省值：显性「不过滤」。
#: 缺省 sentinel 与字面量 ``None``（= 只取该维度为 None 的记录，如步骤级证据）分开，
#: 消除「两个 ``None`` 两种含义」的歧义（:meth:`EvidenceStore.resolve` 的 ``story_id=None``
#: 是字面量绑定语义，与此对齐）。
UNFILTERED: Final = object()


class CommandOutcome(StrEnum):
    """一次命令执行如何结束——成功、失败、超时、取消、策略阻断都有显式分类。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    POLICY_BLOCKED = "policy_blocked"


class CommandEvidence(BaseModel):
    """一条命令执行的证据（cwd / 退出码 / 耗时 / 命令摘要 / digest / 失败分类）。"""

    # 命令摘要不允许空串：连 ``call.name`` 都缺的构造是调用方 bug（模型侧守卫，
    # builder 另有 command → target 摘要 → 工具名的三级回退）。
    command: str = Field(min_length=1)
    cwd: str
    outcome: CommandOutcome
    # 策略阻断 / 取消（结果未到达）没有退出码；None 即「进程没有跑到退出」。
    exit_code: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    # 受治理输出原文的 SHA-256（可复算完整性）；结果未到达时为空。
    output_digest: str = ""
    # 有界脱敏摘要（先脱敏后截断）；明文凭证不进证据。
    output_summary: str = ""
    output_truncated: bool = False
    tool_name: str = ""
    tool_call_id: str = ""


class GitEvidence(BaseModel):
    """一次只读 Git 查询的证据：base / head、tracked 变更与未跟踪文件；从不 commit（AD-11）。"""

    base: str = ""
    head: str = ""
    changed_files: list[str] = Field(default_factory=list)
    untracked_files: list[str] = Field(default_factory=list)


def _utc_now_iso() -> str:
    """UTC 微秒 ISO 时间戳（``+00:00`` 后缀恒定，字典序 = 时间序）。"""
    return datetime.now(UTC).isoformat(timespec="microseconds")


class EvidenceRecord(BaseModel):
    """版本化证据信封：与 goal / workflow / revision / step / story 绑定，防跨 Story 冒用。

    ``created_at`` 用 **UTC** ISO：字典序 = 时间序（本地时间在 DST 回拨会倒序），
    :meth:`EvidenceStore.list_records` 的 ``(created_at, evidence_id)`` 排序因此单调；
    同微秒并写时由 ``evidence_id`` 决定先后（确定性，不依赖墙钟精度）。
    """

    schema_version: str = EVIDENCE_SCHEMA_VERSION
    evidence_id: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    # workflow 声明标识与包 revision（51-6 起由创建时冻结流程写入；缺省空 = 未声明绑定）。
    workflow_id: str = ""
    revision: str = ""
    step: str = ""
    # None = 非story-loop步骤的步骤级证据；story 级证据必须带确切 story id。
    story_id: str | None = None
    created_at: str = Field(default_factory=_utc_now_iso)
    commands: list[CommandEvidence] = Field(default_factory=list)
    git: GitEvidence | None = None


def new_evidence_id() -> str:
    """Fresh evidence id（``[0-9A-Za-z_-]`` 白名单内的 hex，见 ``EvidenceStore._path``）。"""
    return uuid4().hex


def _bounded(text: str, limit: int) -> tuple[str, bool]:
    """截断到 ``limit`` 字符并标记；返回 ``(有界文本, 是否截断)``。"""
    if len(text) <= limit:
        return text, False
    return text[: max(limit - len(TRUNCATION_MARKER), 0)] + TRUNCATION_MARKER, True


def parse_exit_code(content: str) -> int | None:
    """从受治理 shell 结果（首行 ``exit_code=N``）解析退出码；非该形状返回 ``None``。"""
    if not content.startswith("exit_code="):
        return None
    first = content.split("\n", 1)[0]
    raw = first.removeprefix("exit_code=").strip()
    try:
        return int(raw)
    except ValueError:
        return None


def classify_command_result(result: ToolResult) -> CommandOutcome:
    """从受治理 shell 结果分类成败 / 超时；非 shell 形状（无 ``exit_code=``）显性报错。

    分类次序是刻意的：**先按退出码短路成功**（受治理超时结果恒为 ``exit_code=-1``，
    不可能为 0），再识别超时文案——否则一条输出里含 "Command timed out" 字样的成功命令
    会被误记为超时。「跑了没过」「没跑成」与「被拦下」不能都读成失败：策略阻断与普通
    失败在结果文本上不可区分，必须由调用方显式给
    :attr:`CommandOutcome.POLICY_BLOCKED` / :attr:`CommandOutcome.FAILED`（fail-loud，
    不做文本猜测）。
    """
    if not result.content.startswith("exit_code="):
        raise EvidenceError(
            "tool result is not a governed shell result (no exit_code line); "
            "pass an explicit outcome to record it as evidence"
        )
    exit_code = parse_exit_code(result.content)
    if exit_code is None:
        raise EvidenceError("governed shell result has an unparsable exit_code line; refusing to guess")
    if exit_code == 0:
        return CommandOutcome.SUCCEEDED
    if _TIMEOUT_MARKING in result.content:
        return CommandOutcome.TIMEOUT
    return CommandOutcome.FAILED


def build_command_evidence(
    call: ToolCall,
    result: ToolResult | None,
    *,
    cwd: str,
    duration_ms: int = 0,
    outcome: CommandOutcome | None = None,
) -> CommandEvidence:
    """从**既有受治理执行结果**生成命令证据（不执行任何命令，AD-6）。

    ``result`` 为 ``None`` 表示结果未到达（取消路径）：必须显式给 ``outcome``
    （如 :attr:`CommandOutcome.CANCELLED`）。``outcome`` 缺省时从受治理 shell 形状
    分类；无法分类（策略阻断结果、非 shell 错误结果）时显性报错而不是猜。
    """
    content = result.content if result is not None else ""
    if outcome is None:
        if result is None:
            raise EvidenceError("command evidence without a result requires an explicit outcome (e.g. cancelled)")
        outcome = classify_command_result(result)
    exit_code = parse_exit_code(content)
    if outcome is CommandOutcome.SUCCEEDED and exit_code is not None and exit_code != 0:
        # 矛盾证据不得进入 append-only 记录：声称成功却带非零退出码 = 调用方 bug，显性报错。
        raise EvidenceError(f"contradictory evidence: outcome 'succeeded' but exit code is {exit_code}")
    # 命令摘要三级回退：声明的命令 → 受治理 target 摘要 → 工具名；永不为空。
    raw_command = str(call.arguments.get("command", "")) if call.arguments else ""
    summary_command = raw_command or summarize_tool_call(call.name, call.arguments) or call.name
    command, _ = _bounded(redact_secrets(summary_command), _MAX_COMMAND_CHARS)
    summary, truncated = _bounded(redact_secrets(content), _MAX_OUTPUT_SUMMARY_CHARS)
    return CommandEvidence(
        command=command,
        cwd=cwd,
        outcome=outcome,
        exit_code=exit_code,
        duration_ms=max(int(duration_ms), 0),
        output_digest=hashlib.sha256(content.encode("utf-8")).hexdigest() if result is not None else "",
        output_summary=summary,
        output_truncated=truncated,
        tool_name=call.name,
        tool_call_id=call.id,
    )


class EvidenceStore:
    """追加式证据存取：文件落盘、id 定位、跨 goal / Story 绑定校验。

    一个证据一个 JSON 文件（``<root>/<evidence_id>.json``）。append-only 的实现是
    **独占创建**（``open("x")`` / ``O_EXCL``）：同 id 二次写、跨进程并发同 id 写都只有
    一家成功，绝不覆盖历史（崩溃中断只留半截文件，读取时按「损坏」显性报错——也不静默）。
    读取侧拒绝一切 ``schema_version`` 不等于当前版本的记录（「版本化」有门，旧/新版本
    记录不冒充当前语义）。
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._lock = asyncio.Lock()

    @property
    def root(self) -> Path:
        """Directory this store reads and writes."""
        return self._root

    def _path(self, evidence_id: str) -> Path:
        if (
            not evidence_id
            or not _EVIDENCE_ID_PATTERN.fullmatch(evidence_id)
            or evidence_id.casefold() in _WINDOWS_DEVICE_NAMES
        ):
            raise EvidenceError("evidence id must match [0-9A-Za-z_-]+ and must not be a reserved device name")
        return self._root / f"{evidence_id}.json"

    @staticmethod
    def _require_current_schema(record: EvidenceRecord) -> None:
        if record.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise EvidenceError(
                f"evidence schema version {record.schema_version!r} is not supported "
                f"(expected {EVIDENCE_SCHEMA_VERSION!r})"
            )

    async def append(self, record: EvidenceRecord) -> Path:
        """持久化一条新证据；同 id 已存在（或损坏残留）即显性报错，绝不覆盖。

        崩溃可能留下半截文件：独占创建保证不会覆盖任何已存在内容，半截文件在读取时
        按「损坏」显性报错（不静默），清理交给使用者。
        """
        self._require_current_schema(record)
        path = self._path(record.evidence_id)
        payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2)
        async with self._lock:
            if await asyncio.to_thread(path.exists):
                existing = await asyncio.to_thread(load_json_model, path, EvidenceRecord)
                if existing is None:
                    raise EvidenceError(f"evidence record is corrupted: {path}")
                raise EvidenceError(f"evidence record already exists (append-only): {record.evidence_id}")
            try:
                await asyncio.to_thread(self._create_exclusive, path, payload)
            except FileExistsError as exc:  # 跨进程并发同 id 写：独占创建只有一家成功
                raise EvidenceError(f"evidence record already exists (append-only): {record.evidence_id}") from exc
        return path

    @staticmethod
    def _create_exclusive(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)  # 写者是 store 自身：首次 append 建自己的目录
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)

    async def load(self, evidence_id: str) -> EvidenceRecord | None:
        """按 id 取回；不存在返回 ``None``，存在但损坏或版本不符显性报错。"""
        path = self._path(evidence_id)
        record = await asyncio.to_thread(load_json_model, path, EvidenceRecord)
        if path.exists() and record is None:
            raise EvidenceError(f"evidence record is corrupted: {path}")
        if record is not None:
            self._require_current_schema(record)
        return record

    async def list_records(
        self, *, goal_id: str | object | None = UNFILTERED, story_id: str | object | None = UNFILTERED
    ) -> list[EvidenceRecord]:
        """按 ``(created_at, evidence_id)`` 列出证据（UTC 时间戳，字典序单调）；损坏 / 版本不符显性报错。

        过滤语义（与 :meth:`resolve` 刻意对齐，显性 sentinel 消除「两个 ``None`` 两种含义」）：

        - 缺省（:data:`UNFILTERED`）：该维度不过滤；
        - 显式 ``None``：只取该维度为 ``None`` 的记录（``story_id=None`` 即步骤级证据）；
        - 显式值：严格相等过滤。
        """
        if not await asyncio.to_thread(self._root.exists):
            return []
        records: list[EvidenceRecord] = []
        for path in sorted(await asyncio.to_thread(lambda: list(self._root.glob("*.json")))):
            record = await asyncio.to_thread(load_json_model, path, EvidenceRecord)
            if record is None:
                raise EvidenceError(f"evidence record is corrupted: {path}")
            self._require_current_schema(record)
            if goal_id is not UNFILTERED and record.goal_id != goal_id:
                continue
            if story_id is not UNFILTERED and record.story_id != story_id:
                continue
            records.append(record)
        return sorted(records, key=lambda item: (item.created_at, item.evidence_id))

    async def resolve(
        self,
        evidence_ids: list[str],
        *,
        goal_id: str,
        story_id: str | None,
        workflow_id: str = "",
        revision: str = "",
    ) -> list[EvidenceRecord]:
        """把报告里的证据 id 引用解析回记录，并校验绑定（防跨 Story / 跨 Goal 冒用）。

        - 引用必须是可定位的 id：Markdown 里拼一段原始 dict 文本（或任何非 id 字符串）
          解析不到记录即显性报错——报告无法用等价原始 dict 伪装证据；
        - ``goal_id`` / ``story_id`` 严格相等（含 ``None``）：story 级证据不能被别的
          Story（或步骤级引用）冒用；
        - ``workflow_id`` / ``revision`` 双方都非空且不同 = 漂移，拒绝；任一侧为空表示
          该侧未声明绑定（51-6 之前的工作流尚无 revision，缺省放行）。
        """
        records: list[EvidenceRecord] = []
        for evidence_id in evidence_ids:
            record = await self.load(evidence_id)
            if record is None:
                raise EvidenceError(f"referenced evidence does not exist: {evidence_id}")
            self._require_binding(
                record, goal_id=goal_id, story_id=story_id, workflow_id=workflow_id, revision=revision
            )
            records.append(record)
        return records

    @staticmethod
    def _require_binding(
        record: EvidenceRecord,
        *,
        goal_id: str,
        story_id: str | None,
        workflow_id: str,
        revision: str,
    ) -> None:
        if record.goal_id != goal_id:
            raise EvidenceError(f"evidence {record.evidence_id} belongs to goal {record.goal_id!r}, not {goal_id!r}")
        if record.story_id != story_id:
            raise EvidenceError(f"evidence {record.evidence_id} belongs to story {record.story_id!r}, not {story_id!r}")
        for field, expected, actual in (
            ("workflow_id", workflow_id, record.workflow_id),
            ("revision", revision, record.revision),
        ):
            if expected and actual and expected != actual:
                raise EvidenceError(
                    f"evidence {record.evidence_id} declares {field} {actual!r}, which does not match {expected!r}"
                )


def evidence_store(goal_dir: Path) -> EvidenceStore:
    """证据存取的**唯一位置解析点**（与 ``application.checkpoint_store`` 同款先例）：
    ``<goal_dir>/evidence/``。预检 / 求值方不得另算一份路径。"""
    return EvidenceStore(goal_dir / "evidence")
