"""只读 Git 端口：base / head / 变更集与工作区冲突状态；**从不执行写操作**（AD-11）。

供两个消费方共用（Story 51-3）：

1. **Git 证据**：:meth:`ReadOnlyGitPort.evidence` 产出
   :class:`~heagent.goal.evidence.GitEvidence`（base / head、tracked 变更、未跟踪文件）；
2. **工作区危险状态预检**（51-1 递延项）：:meth:`ReadOnlyGitPort.conflict_state` 产出
   工作区冲突状态（未解决冲突 / 进行中的 merge / 领先落后 / upstream 消失），供预检判断
   「当前工作区是否处于冲突性未提交变更」。

**不是 agent 工具、不在治理链上**：本端口不接收模型发起的任意命令，而是**固定查询模板**——
子命令必须在 :data:`_READONLY_SUBCOMMANDS` 白名单内，旗标必须逐字来自
:data:`_FIXED_FLAGS` 模板，位置参数（rev / 路径）一律拒 ``-`` 前缀。``exec`` 直 spawning、
无 shell、无 ``commit`` / ``push`` / ``reset`` 等任何写形态。这是确定性证据 / 预检查询，
不是绕过 ``ToolExecutor`` 的命令执行入口（AD-6 约束的是模型工具链，见 goal/evidence.py）。
rev / base 参数另受 :data:`_REVISION_PATTERN` 约束（首字符必须是 word 字符，防 ``-`` 旗标
注入）。查询输出**不截断**：超过查询预算显性报错——截断会伪造路径、丢中间条目。

**子树语义（如实声明，review #21）**：全部查询走 ``git -C <workspace>``——workspace 只是
仓库内的一个锚点：当 workspace 是仓库**子目录**时，``diff`` / ``ls-files`` 等只报该子树
相对根的路径、且只覆盖子树内的变更；只有 workspace 恰为仓库根时证据才覆盖全仓。调用方
（如 ``/goal verify``）据 workspace 解析的仓库布局如实取值，不在本端口内"补齐"全仓视图。
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

from heagent.goal.evidence import GitEvidence
from heagent.pub.safe_logging import safe_log
from heagent.tools.sandbox import communicate_subprocess, decode_channel, reap_subprocess

logger = logging.getLogger(__name__)

# 只读子命令白名单：端口的全部查询都必须落在这里（防御「端口长大成写入口」的静默漂移，
# tests/test_goal_evidence.py 有判据钉住「白名单不含任何写形态子命令」）。
_READONLY_SUBCOMMANDS = frozenset({"status", "diff", "rev-parse", "ls-files"})
# 固定旗标模板：每个子命令允许的旗标**逐字**枚举——旗标不可能从调用方混入
# （``_run`` 拒绝模板之外的任何 ``-`` 开头参数，位置参数一律当操作数、拒 ``-`` 前缀）。
# ``diff`` 追加 ``--no-textconv --no-ext-diff``：外部 diff/textconv 驱动是不必要的
# 任意执行面，只读端口必须关死。
_FIXED_FLAGS: dict[str, frozenset[str]] = {
    "diff": frozenset({"--name-only", "--no-renames", "--no-textconv", "--no-ext-diff"}),
    "status": frozenset({"--porcelain=v1", "-b"}),
    "ls-files": frozenset({"--others", "--exclude-standard"}),
    "rev-parse": frozenset({"--verify", "--quiet"}),
}
_GIT_TIMEOUT_SECONDS = 60
# 单次查询输出预算：超出即显性报错而不是截断（截断的路径清单是伪证据）。
# 预算给足（≈ 数十万条路径），只防失控仓库 / 异常输出把证据文件撑爆。
_MAX_QUERY_BYTES = 8 * 1024 * 1024
# rev / base 只接受 commit-ish 字符：首字符必须是 word 字符（拒裸 ``-``），其余无空白、
# 无 shell 元字符、不以 ``-`` 开头（防 git 旗标注入）。
_REVISION_PATTERN = re.compile(r"^[A-Za-z0-9_][\w./@+^~-]*$")


class GitPortError(RuntimeError):
    """Raised when a read-only Git query cannot run or the path is not a repository."""


class WorkspaceConflictState(BaseModel):
    """工作区冲突状态（危险状态预检的输入，全部来自只读查询）。

    未跟踪文件与 :class:`~heagent.goal.evidence.GitEvidence.untracked_files` 用**同一
    表示**（路径列表，尊重 .gitignore），两个消费方对「未跟踪」的理解不会分叉。
    """

    branch: str = ""
    upstream: str = ""
    ahead: int = Field(default=0, ge=0)
    behind: int = Field(default=0, ge=0)
    # upstream 在本地配置里声明、但远端已不存在（``[gone]``）：显性信号，
    # 不伪装成 ahead=0 / behind=0 的「同步」状态。
    upstream_gone: bool = False
    # tracked 未提交变更（staged + unstaged 的路径）。
    uncommitted_files: list[str] = Field(default_factory=list)
    # 未跟踪文件路径（与 GitEvidence.untracked_files 同口径：--others --exclude-standard）。
    untracked_files: list[str] = Field(default_factory=list)
    # 未解决冲突的路径（porcelain 的 DD / AU / UD / UA / DU / AA / UU）。
    conflicting_files: list[str] = Field(default_factory=list)
    merge_in_progress: bool = False

    @property
    def has_unresolved_conflicts(self) -> bool:
        """True 表示工作区处于冲突性未提交状态（预检应报告为危险）。"""
        return bool(self.conflicting_files) or self.merge_in_progress


def _validate_revision(revision: str) -> str:
    """rev / base 只接受安全的 commit-ish 字符（首字符 word，``-`` 开头会被 git 当旗标）。"""
    if not revision or _REVISION_PATTERN.match(revision) is None:
        raise GitPortError(f"invalid git revision: {revision!r}")
    return revision


# porcelain 未合并（冲突）状态码：XY 两字母都表达「双方/一边未解决」。
_UNMERGED_CODES = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})
# rename / copy 条目（``R `` / ``C ``）的路径段是 ``old -> new``，取生效路径要引号感知。
_RENAME_CODES = frozenset({"R", "C"})


class ReadOnlyGitPort:
    """对 ``root`` 仓库的只读 Git 查询端口；所有调用都不改变仓库状态。"""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """Repository root this port queries."""
        return self._root

    async def head(self) -> str:
        """当前 HEAD commit（无提交的仓库显性报错：没有基线就没有证据）。"""
        return await self._run("rev-parse", "HEAD")

    async def evidence(self, base: str = "") -> GitEvidence:
        """base / head、tracked 变更、未跟踪文件；``base`` 空 = 与 HEAD 比对的未提交变更。

        tracked 变更取 ``git diff --name-only --no-renames <base|HEAD>``：含已提交（自
        base 起）+ 暂存 + 未暂存，重命名拆成删 + 加（变更集不隐藏删除）；未跟踪取
        ``git ls-files --others --exclude-standard``（尊重 .gitignore）。
        """
        effective_base = _validate_revision(base) if base else "HEAD"
        head = await self.head()
        # --no-textconv / --no-ext-diff：外部 diff 驱动是不必要的任意执行面，只读端口关死。
        changed = _split_lines(
            await self._run("diff", "--name-only", "--no-renames", "--no-textconv", "--no-ext-diff", effective_base)
        )
        untracked = _split_lines(await self._run("ls-files", "--others", "--exclude-standard"))
        return GitEvidence(base=effective_base, head=head, changed_files=changed, untracked_files=untracked)

    async def conflict_state(self) -> WorkspaceConflictState:
        """工作区冲突状态：分支 / 领先落后 / 未提交 / 冲突 / 进行中的 merge。"""
        text = await self._run("status", "--porcelain=v1", "-b")
        # porcelain 是**定前列**格式（XY + 空格 + 路径）：行首空格是状态的一半（` M` =
        # 未暂存修改），绝不能 strip 行首——只丢空行，不碰列。
        lines = [line for line in text.splitlines() if line.strip()]
        branch, upstream, ahead, behind, upstream_gone = _parse_branch_line(lines[0]) if lines else _NO_BRANCH
        uncommitted: list[str] = []
        conflicting: list[str] = []
        untracked: list[str] = []
        for line in lines[1:]:
            code, path = line[:2], _entry_path(line[3:], rename=line[0] in _RENAME_CODES)
            if code == "??":
                untracked.append(path)
                continue
            if code in _UNMERGED_CODES:
                conflicting.append(path)
                continue
            uncommitted.append(path)
        return WorkspaceConflictState(
            branch=branch,
            upstream=upstream,
            ahead=ahead,
            behind=behind,
            upstream_gone=upstream_gone,
            uncommitted_files=uncommitted,
            untracked_files=untracked,
            conflicting_files=conflicting,
            merge_in_progress=await self._merge_in_progress(),
        )

    async def _merge_in_progress(self) -> bool:
        """``MERGE_HEAD`` 可解析 = 一次 merge 正在进行（只读探测）。"""
        try:
            return bool(await self._run("rev-parse", "--verify", "--quiet", "MERGE_HEAD"))
        except GitPortError:
            return False

    async def _run(self, *args: str) -> str:
        """执行一条固定模板内的只读 git 子查询；越权 / 超时 / 超预算 / 失败显性报错。

        ``args[0]`` 是子命令（白名单）；其后以 ``-`` 开头的参数必须逐字命中
        :data:`_FIXED_FLAGS` 模板，其余参数是操作数（rev / 路径），**拒 ``-`` 前缀**——
        调用方无法借操作数位置走私旗标，读写形态的子命令进不了白名单。
        """
        if not args or args[0] not in _READONLY_SUBCOMMANDS:
            raise GitPortError(f"git subcommand is not on the read-only allowlist: {args[:1]}")
        allowed_flags = _FIXED_FLAGS.get(args[0], frozenset())
        for argument in args[1:]:
            if argument.startswith("-") and argument not in allowed_flags:
                raise GitPortError(f"git flag is not on the fixed query template: {argument}")
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-c",
                "core.quotePath=false",  # 证据要原始路径：非 ASCII 路径不加引号转义
                "-C",
                str(self._root),
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise GitPortError(f"git executable is not available: {exc}") from exc
        except OSError as exc:
            # spawn 的其余 OS 故障（权限 / 资源耗尽等）同样显性包成 GitPortError，
            # 不让调用方（verify / 预检）收到裸 OSError（review #4）。
            raise GitPortError(f"git {' '.join(args[:1])} could not be started: {exc}") from exc
        try:
            stdout, stderr = await communicate_subprocess(proc, timeout=_GIT_TIMEOUT_SECONDS)
        except TimeoutError:
            try:
                proc.kill()
                await reap_subprocess(proc)
            except ProcessLookupError:
                pass
            except Exception:  # noqa: BLE001 - 清理失败仅诊断，不掩盖超时本身
                safe_log(logger, logging.WARNING, "git %s cleanup after timeout failed", args[0], exc_info=True)
            raise GitPortError(f"git {' '.join(args)} timed out after {_GIT_TIMEOUT_SECONDS}s") from None
        except asyncio.CancelledError:
            try:
                proc.kill()
                await reap_subprocess(proc)
            except ProcessLookupError:
                pass
            except Exception:  # noqa: BLE001 - 取消路径尽力清理，不掩盖取消本身
                safe_log(logger, logging.WARNING, "git %s cleanup after cancellation failed", args[0], exc_info=True)
            raise
        if proc.returncode != 0:
            detail = decode_channel(stderr).strip()
            raise GitPortError(detail or f"git {' '.join(args)} failed with code {proc.returncode}")
        if len(stdout) > _MAX_QUERY_BYTES:
            # 查询不截断：截断的路径清单会伪造变更集（丢中间条目 / 半条路径）。
            raise GitPortError(
                f"git {' '.join(args)} output exceeds the {_MAX_QUERY_BYTES}-byte query budget "
                f"({len(stdout)} bytes); narrow the query"
            )
        return decode_channel(stdout).strip()


_NO_BRANCH = ("HEAD", "", 0, 0, False)
_NO_COMMITS_PREFIX = "No commits yet on "


def _parse_branch_line(line: str) -> tuple[str, str, int, int, bool]:
    """解析 porcelain ``-b`` 首行 → ``(branch, upstream, ahead, behind, upstream_gone)``。

    特判三种非标形态：detached（``## HEAD (no branch)``）、尚无提交
    （``## No commits yet on <branch>``）、upstream 已消失（``[gone]``——显性布尔，
    不伪装成 ahead=0 / behind=0 的同步态）。
    """
    body = line.removeprefix("## ").strip()
    if not body:
        return _NO_BRANCH
    if body == "HEAD (no branch)":
        return _NO_BRANCH
    if body.startswith(_NO_COMMITS_PREFIX):
        return body[len(_NO_COMMITS_PREFIX) :].strip() or "HEAD", "", 0, 0, False
    ahead = behind = 0
    upstream_gone = False
    bracket = ""
    if "[" in body and body.endswith("]"):
        body, bracket = body[: body.index("[")].strip(), body[body.index("[") + 1 : -1]
    for token in bracket.split(","):
        label, _, raw = token.strip().partition(" ")
        if label == "ahead":
            ahead = _non_negative_int(raw)
        elif label == "behind":
            behind = _non_negative_int(raw)
        elif label == "gone":
            upstream_gone = True
    branch, _, rest = body.partition("...")
    upstream = rest.split(" ", 1)[0] if rest else ""
    return branch, upstream, ahead, behind, upstream_gone


def _non_negative_int(raw: str) -> int:
    try:
        return max(int(raw.strip()), 0)
    except ValueError:
        return 0


def _entry_path(raw: str, *, rename: bool) -> str:
    """porcelain 路径段 → 生效路径：rename/copy 条目引号感知地取箭头右侧，再去 porcelain 引号。"""
    return _unquote(_right_of_arrow(raw) if rename else raw)


def _right_of_arrow(raw: str) -> str:
    """``old -> new`` 取右侧；引号内的 `` -> `` 不是分隔箭头（文件名可以含箭头）。"""
    quote: str | None = None
    index = 0
    while index < len(raw) - 3:
        character = raw[index]
        if quote is not None:
            if character == quote:
                quote = None
        elif character in {'"', "'"}:
            quote = character
        elif raw.startswith(" -> ", index):
            return raw[index + 4 :]
        index += 1
    return raw


def _unquote(path: str) -> str:
    """porcelain 对含特殊字符路径加引号；去引号保留字面内容（不做转义解码，防非 ASCII 乱码）。"""
    if path.startswith('"') and path.endswith('"') and len(path) >= 2:
        return path[1:-1]
    return path


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]
