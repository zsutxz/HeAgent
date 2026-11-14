"""Story 写集审计判负策略（AD-18 判负 / A40 内容指纹 / A43 参照系换算 / A41-A42 判负披露与 remediation）。

**为什么单独成模块**（cli/wiring.py、goal/document.py 先例）：写审计判负策略家族（12 符号）原住
入口层命令模块 cli/goal.py——判负语义随 AD-18/A40/A41-A43 演进，与命令编排无关；迁出后 cli/goal
只留编排与呈现（搬规则不搬呈现）。

**emit 注入**：事件发射能力由调用方解析后作首参传入（cli 侧 ``_workflow_event_emitter(engine)``
解析出的可调用），家族零 cli 依赖、同守 click-free；emit 为 ``None`` 时静默（无引擎或无 emitter
场景），与迁出前 ``_workflow_event_emitter(engine)`` 的解析语义等价。

分层：goal 子包属入口层（与 cli/gui 同级，供 cli/goal 消费），不被任何下层模块导入；goal→engine
同向 import 先例见 application.py。
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from heagent.engine.workflow_runner import _emit_step_event, write_set_parts
from heagent.goal.document import goal_step_artifact_path

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from heagent.goal.evidence import GitEvidence
    from heagent.pub.types import StoryExecutionContext


async def _audit_git_evidence(workspace: Path, base: str = "") -> GitEvidence | None:
    """审计用的只读 Git 证据（52-3）；仓库不可用（``GitPortError``）返回 ``None``。

    与 :func:`_goal_live_git_evidence` 的差异在失败语义：门求值把「无 Git」记为空证据
    （显性未过），审计把「无 Git」记为**跳过**（无从判负，不诬告）——两者都不能静默。
    ``base`` 非空时按该 revision 取增量：after 采集传 before 的 head，会话内 ``git commit``
    前移 HEAD 不会把已提交的写从 Δ 里洗掉（evidence 含自 base 起的已提交变更）。
    """
    from heagent.goal.git_port import GitPortError, ReadOnlyGitPort  # noqa: PLC0415

    try:
        return await ReadOnlyGitPort(workspace).evidence(base)
    except GitPortError:
        return None


def _covered_by_write_set(path: str, entries: Sequence[str]) -> bool:
    """git 相对路径是否落在声明写集条目内（目录条目覆盖子树）。

    归一化复用 :func:`heagent.engine.workflow_runner.write_set_parts`（分隔符统一 +
    大小写折叠 + 段级前缀）——宿主判负与引擎批派生的写集语义必须同源，不得各写一份
    词法（AD-18）。空/死条目**不构成豁免判据**（fail-closed：引擎侧「空段覆盖一切→
    与一切相交→不成批」是收紧，宿主侧若同样「覆盖一切→放行」就是免检，方向相反）。
    """
    parts = write_set_parts(path)
    for entry in entries:
        entry_parts = write_set_parts(entry)
        if not entry_parts:
            continue
        if parts[: len(entry_parts)] == entry_parts:
            return True
    return False


def _emit_write_audit_event(emit: Callable[..., None] | None, *, step: Any, story: Any, **details: Any) -> None:
    """``workflow_write_audit`` 观测事件（52-3）：仿 ``_emit_goal_gate_event``，共用
    :func:`_emit_step_event` 的隔离包装（emit-None 守卫 + try/except + safe_log）。"""
    if emit is None:
        return
    _emit_step_event(emit, "workflow_write_audit", step=step, story=story, **details)


@dataclass(frozen=True)
class _WriteAuditBaseline:
    """会话前的审计基线：Git 证据 + 已脏 tracked 路径的**内容指纹**（A40 内容级增量）。"""

    evidence: GitEvidence
    fingerprints: dict[str, str]


async def _audit_story_writes(
    emit: Callable[..., None] | None,
    workspace: Path,
    goal_dir: Path,
    step: Any,
    story: Any,
    execution: StoryExecutionContext,
    before: _WriteAuditBaseline,
) -> str:
    """一次 Story 的 Git 写集审计（AD-18）：返回判负理由（空串 = 通过）。

    会话 + 质量门结束后采集 after（基线钉在 before 的 head 上——会话内 ``git commit``
    不洗白已提交的越集写），``Δ`` 取**内容级**增量（A40）：同名路径只有在目标侧内容指纹
    真的变了才算增量；判负式 ``(Δ \\ 声明写集并集 \\ 宿主自写产物) 非空``——声明写集并集 =
    本 Story 的 ``write_allowlist`` ∪ 兄弟写集（并发兄弟的合法写在共享工作区里必然落进本
    Story 的 Git 增量，不排除就是互诬告）；豁免产物含本 Story 与全部批成员的宿主产物路径
    （``_he-output`` 被 tracked 时并发批互不诬告）。untracked 增量剔除产物路径后发警告
    事件不判负（验证夹具 / 新产物常态，AC4；产物自身是必然噪声，不发）。after 采集
    失败（仓库中途不可用）→ 放弃本次审计（不诬告）。
    """
    after = await _audit_git_evidence(workspace, base=before.evidence.head)
    if after is None:
        _emit_write_audit_event(emit, step=step, story=story, skipped="git_unavailable")
        return ""
    # 内容级增量：路径集合差集看不见「会话前已脏的集外文件被本 Story 再改」——路径
    # 在 before 与 after 里都出现，Δ 因此漏判。改按目标侧内容指纹比较后：未改动的既有脏
    # 文件不误报、被再改的既有脏文件不再隐形；指纹读不到（权限 / 中途删除）记空串，与
    # before 不同即算增量（方向 = 多判负、不漏判）。
    after_fingerprints = await _content_fingerprints(workspace, after.changed_files)
    changed_delta = [
        path for path in after.changed_files if before.fingerprints.get(path) != after_fingerprints.get(path)
    ]
    before_untracked = set(before.evidence.untracked_files)
    untracked_delta = [path for path in after.untracked_files if path not in before_untracked]
    allowed = [*execution.write_allowlist]
    artifacts = {_host_artifact_relpath(goal_dir, step, story, workspace)}
    for member_id, sibling in execution.sibling_write_sets.items():
        allowed.extend(sibling)
        artifacts.add(_host_artifact_relpath(goal_dir, step, SimpleNamespace(id=member_id), workspace))
    artifact_paths = [path for path in artifacts if path]
    allowed.extend(artifact_paths)
    # tracked 差额来自 ``git diff --name-only``，报的是**仓库根**相对路径（实测
    # ``-C <repo/sub>`` 也报 ``sub/...``）；产物路径按**工作区**相对。工作区不是仓库根时
    # 必须补成同一参照系，否则宿主自写产物被当越集写判负并撤并行授权。
    # 同根部署下两者逐字相同（恒等变换，行为不变）。
    toplevel = _git_toplevel(workspace)
    allowed.extend(_repo_relpath(path, workspace, toplevel) for path in artifact_paths)
    if untracked_delta:
        # untracked 来自 ``git ls-files --others``，是 **cwd**（= 工作区）相对，与产物同参照系。
        signal = [path for path in untracked_delta if path not in artifacts]
        if signal:
            _emit_write_audit_event(emit, step=step, story=story, untracked=signal)
    violations = sorted(path for path in changed_delta if not _covered_by_write_set(path, allowed))
    if not violations:
        return ""
    # 判负的两条补充语义：
    # ① 共享工作区**无法把写者归属到某个 Story**——兄弟成员越集写同样落进本 Story 的 Δ，
    #    消息必须如实披露「不能归因」，别让读者当成「本 Story 写的」。
    # ② 只置 FAILED + 闩并不够：越集文件留在工作区，而闩后串行重跑的新基线已含旧违规
    #    （审计对它失明）⇒ 把越集路径与基线 revision 写进观测事件留档，并在 reason 里给出
    #    可直接执行的人工清理指引（本条只做「指引」，不做自动回滚——回滚需要会话前快照，
    #    属 worktree / 快照层）。
    shared_workspace = len(execution.batch_members) > 1
    _emit_write_audit_event(
        emit,
        step=step,
        story=story,
        violations=violations,
        base=before.evidence.head,
        shared_workspace=shared_workspace,
    )
    attribution = (
        "; shared workspace: the writer cannot be attributed to this story (a sibling may be the author)"
        if shared_workspace
        else ""
    )
    base = before.evidence.head
    return (
        f"story '{execution.story_id}' wrote outside its declared write set: {', '.join(violations)}{attribution}; "
        f"parallel authorization for this goal is revoked; remediation: review with `git diff {base} -- <path>`, "
        f"then discard with `git restore --source={base} -- <path>` (delete the path instead if it was newly created)"
    )


async def _write_audit_baseline(workspace: Path) -> _WriteAuditBaseline | None:
    """采集会话前基线；仓库不可用（``GitPortError``）返回 ``None``（= 本次审计跳过）。"""
    evidence = await _audit_git_evidence(workspace)
    if evidence is None:
        return None
    return _WriteAuditBaseline(
        evidence=evidence, fingerprints=await _content_fingerprints(workspace, evidence.changed_files)
    )


async def _content_fingerprints(workspace: Path, paths: Sequence[str]) -> dict[str, str]:
    """``{仓库根相对路径: 内容 sha256}``：审计的内容级增量判据（A40）。

    路径来自 ``git diff --name-only``，是**仓库根**相对（同 A43 的参照系事实），故按仓库
    顶层目录解析；顶层不可知时退回工作区（工作区即仓库根的当前部署两者同形）。文件读不到
    （删除 / 权限）记空串——与「基线里不存在」的 ``None`` 区分，两者都被当作增量，方向是
    多判负、不漏判。
    """
    root = _git_toplevel(workspace) or workspace
    return await asyncio.to_thread(_fingerprint_paths, root, list(paths))


#: 指纹分块大小：只做流式哈希，绝不把整文件读进内存（仓库里可能有数百 MB 的产物）。
_FINGERPRINT_CHUNK_BYTES = 1 << 20


def _fingerprint_paths(root: Path, paths: list[str]) -> dict[str, str]:
    """线程池里跑的分块哈希（库代码不做同步 I/O；单文件异常只记空串）。"""
    digests: dict[str, str] = {}
    for relpath in paths:
        digest = hashlib.sha256()
        try:
            with (root / relpath).open("rb") as handle:
                for chunk in iter(lambda: handle.read(_FINGERPRINT_CHUNK_BYTES), b""):
                    digest.update(chunk)
        except OSError:
            digests[relpath] = ""
            continue
        digests[relpath] = digest.hexdigest()
    return digests


def _host_artifact_relpath(goal_dir: Path, step: Any, story: Any, workspace: Path) -> str:
    """宿主自写产物**相对工作区根**的 posix 路径（不在工作区内返回空串——无需排除）。

    参照系是工作区，不是仓库根：与 ``git diff --name-only`` 的差额集不同源，比较前必须经
    :func:`_repo_relpath` 换算（A43）。
    """
    try:
        return goal_step_artifact_path(goal_dir, step, story).resolve().relative_to(workspace).as_posix()
    except ValueError:
        return ""


def _git_toplevel(workspace: Path) -> Path | None:
    """``workspace`` 所在仓库的顶层目录（最近的含 ``.git`` 的祖先）。

    ``.git`` 是目录（普通仓库）或文件（worktree / 子模块）都算命中。走不到（``GIT_DIR``
    重定向、非仓库）返回 ``None``——调用方退回「产物按工作区相对」，即工作区恰为仓库根时
    的既有语义（fail-safe：宁可多判负，不漏判）。
    """
    for candidate in (workspace, *workspace.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _repo_relpath(relpath: str, workspace: Path, toplevel: Path | None) -> str:
    """工作区相对路径 → 仓库根相对（与 ``git diff --name-only`` 同参照系）。

    工作区即仓库根（当前部署）或参照根不可知时原样返回——此时两种参照系同形。
    """
    if not relpath or toplevel is None or toplevel == workspace:
        return relpath
    try:
        prefix = workspace.relative_to(toplevel).as_posix()
    except ValueError:
        return relpath
    return f"{prefix}/{relpath}" if prefix else relpath
