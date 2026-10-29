"""S-2 变异体验证：证明「状态不变量」的每条判据都能被精确打红。

做法（永不碰工作树）：把**整棵工作区**（排除 `.git` / `.venv` / `.heagent` / `_he-output` 等重量级目录）
复制到 `.heagent/tmp/heagent-next-cycle/s-2/` 下，只改副本，用副本自己的 `pyproject.toml` 与
`PYTHONPATH=<副本>/src` 跑对应判据，断言退出码非 0。

为什么必须整棵复制（而不是只拷 `src/` 再改 PYTHONPATH）：本仓的架构守卫用
`Path(__file__).resolve().parents[1] / "src"` 定位源码（见 `tests/test_architecture_contracts.py` 的
`SRC`），只改 PYTHONPATH 时守卫读的仍是仓库本体，变异会**假绿**——2026-10-26 首次跑就撞上
M2/M8 两条假阴性。同样地，守卫还会按相对路径读 `docs/`、`deploy/`、`.env.example`，
逐个枚举复制必然漏项，故改为「整树复制 + 跳过表」。

用法：
    .heagent/tmp/py311-venv-linux/bin/python scripts/mutate_state_invariants.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / ".heagent" / "tmp" / "heagent-next-cycle" / "s-2"
TIMEOUT_SECONDS = 900

#: 不参与复制的目录（与变异无关，且体积大）。
_SKIP_DIRS = {
    ".git",
    ".venv",
    ".heagent",
    "_he-output",
    "projects",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".benchmarks",
    ".test-workdirs",
    ".pytest_tmp_local",
    "_bmad",
    "logs",
}


@dataclass(frozen=True)
class Mutation:
    """一条变异：改哪儿、怎么改、哪条判据必须变红。"""

    code: str
    target: str
    old: str
    new: str
    test: str
    why: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        code="M1",
        target="src/heagent/engine/checkpoint.py",
        old='    transition_reason: str = ""\n',
        new="",
        test="tests/test_workflow_transition_reason.py",
        why="删字段 ⇒ 往返用例取不到值",
    ),
    Mutation(
        code="M2",
        target="src/heagent/engine/workflow_runner.py",
        old='            "status": transition(self.state.status, event),',
        new='            "status": WorkflowStatus.PENDING,',
        test="tests/test_architecture_contracts.py::test_transition_fields_helper_is_the_only_status_writer",
        why="绕过 transition() 直写状态 ⇒ AST 守卫",
    ),
    Mutation(
        code="M3",
        target="src/heagent/engine/workflow_runner.py",
        old='            "transition_reason": _bounded_reason(reason),',
        new='            "transition_reason": reason,',
        test="tests/test_workflow_transition_reason.py::test_oversized_reason_is_truncated_on_write",
        why="跳过 _bounded_reason ⇒ 5000 字符原样落盘",
    ),
    Mutation(
        code="M4",
        target="src/heagent/engine/checkpoint.py",
        old="        if value and value not in _WORKFLOW_EVENT_VALUES:",
        new="        if False:",
        test="tests/test_workflow_transition_reason.py::test_illegal_last_event_fails_loud_and_names_the_value",
        why="删词表校验 ⇒ 非法驱动事件被静默接受",
    ),
    Mutation(
        code="M5",
        target="src/heagent/engine/workflow_transition.py",
        old='        raise WorkflowTransitionError(f"illegal workflow transition: {source.value} + {event.value}") from exc',
        new='        raise WorkflowTransitionError(f"illegal workflow transition: {source.value} + {event.value}")',
        test="tests/test_workflow_transition_reason.py::test_transition_failure_preserves_cause_chain",
        why="去掉 from exc ⇒ 原始 cause 链丢失",
    ),
    Mutation(
        code="M6",
        target="src/heagent/engine/workflow_runner.py",
        old="            transition_reason=self.state.transition_reason,\n",
        new="",
        test="tests/test_workflow_transition_reason.py::test_roundtrip_via_store_keeps_reason",
        why="落盘漏写 ⇒ 第二次往返后字段为空",
    ),
    Mutation(
        code="M7",
        target="src/heagent/engine/workflow_runner.py",
        old="    if len(text) <= _MAX_REASON_CHARS:\n        return text",
        new='    if len(text) <= _MAX_REASON_CHARS:\n        return text\n    raise ValueError("reason too long")',
        test="tests/test_workflow_transition_reason.py::test_oversized_reason_is_truncated_on_write",
        why="超长时抛异常 ⇒ 观测反噬主流程",
    ),
    Mutation(
        code="M8",
        target="src/heagent/engine/workflow_runner.py",
        old="                error_kind=error_kind_for(exc),",
        new='                error_kind="exception",',
        test="tests/test_architecture_contracts.py::test_workflow_runner_error_kind_comes_from_the_closed_mapping",
        why="内联分类字面量 ⇒ 绕过封闭映射",
    ),
)


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _SKIP_DIRS or name.endswith(".pyc")}


def _prepare(code: str) -> Path:
    """把工作区复制到隔离目录（变异只改副本，永不碰工作树）。"""
    dest = WORK / code
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for entry in ROOT.iterdir():
        if entry.name in _SKIP_DIRS:
            continue
        target = dest / entry.name
        try:
            if entry.is_dir():
                shutil.copytree(entry, target, ignore=_ignore)
            else:
                shutil.copy2(entry, target)
        except (PermissionError, OSError) as exc:  # 个别本地运行目录不可读：跳过并记录
            print(f"[copy] 跳过 {entry.name}：{exc}")
    return dest


def _run(test: str, workdir: Path) -> subprocess.CompletedProcess[str]:
    env = {
        "PYTHONPATH": str(workdir / "src"),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(Path.home()),
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", *test.split(), "-q", "-p", "no:cacheprovider"],
        cwd=workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    baseline = _prepare("baseline")
    base = _run(
        "tests/test_workflow_transition_reason.py tests/test_architecture_contracts.py",
        baseline,
    )
    if base.returncode != 0:
        print("[baseline] FAILED — 未变异副本本应为绿，说明副本本身不可用")
        print(base.stdout[-2000:])
        return 2
    print("[baseline] 绿（未变异副本可作为对照）")

    for mutation in MUTATIONS:
        workdir = _prepare(mutation.code)
        target = workdir / mutation.target
        text = target.read_text(encoding="utf-8")
        hits = text.count(mutation.old)
        if hits != 1:
            failures.append(f"{mutation.code}: 变异点命中 {hits} 次（应为 1）")
            print(f"[{mutation.code}] SKIP — 变异点不唯一")
            continue
        target.write_text(text.replace(mutation.old, mutation.new), encoding="utf-8")
        result = _run(mutation.test, workdir)
        turned_red = result.returncode != 0
        print(f"[{mutation.code}] {'红（预期）' if turned_red else '**绿了（判据失效）**'} — {mutation.why}")
        if not turned_red:
            failures.append(f"{mutation.code}: 期望变红但仍是绿 —— {mutation.why}")

    print()
    if failures:
        print("FAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print(f"OK: {len(MUTATIONS)} 个变异体全部精确变红")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
