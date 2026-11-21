"""框架错误码注册表守卫（台账 A71：「只增不复用」）。

既有断言只钉「唯一 + ``E_*`` 形态 + ``docs/errors.md`` 逐条一致」——因此
**改名**（``E_FOO`` → ``E_BAR``）与**把码挪给另一个类**都能静默通过，客户端拿旧码
去匹配就失效了。这里补机器锚点：``tests/fixtures/contract_baselines/error_codes.json``
冻结「码 → 类名」，基线里的每个码必须仍存在且仍归属同一个类；删除或改归属即红并点名该码。

三层数据源两两交叉，任一层漂移都能被发现（防止守卫自己失真）：

1. **基线 JSON**：冻结面，只能经 ``--write --only error_codes`` 再生 ⇒ 任何改动必进 git diff；
2. **AST 快照**：``scripts/contract_snapshot.py --print --only error_codes``（纯静态解析，
   不 import heagent——测的是 CI 真正跑的那条子进程路径，与 ``test_contract_baselines.py`` 同型）；
3. **运行时真源**：``pub.exceptions.error_catalog()``（顺序 = ``_CATALOG_CLASSES``）。

新增码是允许的（只增语义），但必须同步重生成基线，否则 ``--check`` 门
（``test_contract_baselines.py::test_snapshot_check_passes``）会红——与 INV-1/2/3/8
的既有口径一致；也就是说「加码」只需 ``--write``，「删码 / 改归属」会在此处单独红。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from heagent.pub.exceptions import error_catalog

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/contract_snapshot.py"
BASELINE = REPO_ROOT / "tests" / "fixtures" / "contract_baselines" / "error_codes.json"


def _snapshot(kind: str) -> dict[str, object]:
    """以 `--print --only <kind>` 取「当前代码算出的快照」（不落盘、不比对）。"""
    result = subprocess.run(  # noqa: S603 -- argv 是固定字面量 + 本仓脚本路径，无外部输入
        [sys.executable, SCRIPT, "--print", "--only", kind],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"--print {kind} failed\n{result.stdout}\n{result.stderr}"
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict), f"--print {kind} did not return a JSON object"
    return payload


def _baseline() -> dict[str, object]:
    assert BASELINE.is_file(), (
        f"missing baseline {BASELINE.relative_to(REPO_ROOT).as_posix()}; regenerate with "
        "`python scripts/contract_snapshot.py --write --only error_codes`"
    )
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{BASELINE.name} must be a JSON object"
    return payload


def _codes_view(payload: dict[str, object]) -> dict[str, str]:
    """快照的扁平视图 ``{码: 类名}``。"""
    codes = payload["codes"]
    assert isinstance(codes, dict), "snapshot has no `codes` mapping"
    return {str(code): str(class_name) for code, class_name in codes.items()}


def _entries_view(payload: dict[str, object]) -> list[tuple[str, str]]:
    """快照的有序视图 ``[(码, 类名), ...]``（顺序 = ``_CATALOG_CLASSES``）。"""
    entries = payload["entries"]
    assert isinstance(entries, list), "snapshot has no `entries` list"
    return [(str(entry["code"]), str(entry["class_name"])) for entry in entries]


def registry_drift(frozen: dict[str, str], current: dict[str, str]) -> list[str]:
    """`frozen` 里每个 ``(码 → 类名)`` 在当前注册表里是否仍成立；返回问题清单（空 = 无漂移）。

    只查「基线有、现在没了 / 换了归属」——基线没有的新码不进问题清单，这就是「只增」语义。
    """
    issues: list[str] = []
    for code in sorted(frozen):
        expected = frozen[code]
        actual = current.get(code)
        if actual is None:
            issues.append(f"{code}: 已从注册表移除（基线归属 {expected}）")
        elif actual != expected:
            issues.append(f"{code}: 归属从 {expected} 改成 {actual}")
    return issues


def test_frozen_codes_still_map_to_the_same_class() -> None:
    """A71：基线里的每个码必须仍存在、且仍归属同一个类；删除或改名即红并点名该码。"""
    issues = registry_drift(_codes_view(_baseline()), _codes_view(_snapshot("error_codes")))
    assert not issues, (
        "A71 violated: 框架错误码只增不复用——基线里的码不得删除或改归属"
        "（如确实要改，先确认客户端与 docs/errors.md 已迁移，再 `--write` 重生基线）\n"
        + "\n".join(f"  - {issue}" for issue in issues)
    )


def test_ast_snapshot_matches_the_runtime_catalog() -> None:
    """AST 解析器与运行时真源逐条一致（含顺序）——防解析器与 `error_catalog()` 各自漂移。"""
    snapshot = _snapshot("error_codes")
    ast_entries = _entries_view(snapshot)
    catalog = error_catalog()
    runtime_entries = [(entry.code, entry.class_name) for entry in catalog]
    assert ast_entries == runtime_entries, (
        f"AST 快照与 error_catalog() 不一致\n  ast    : {ast_entries}\n  runtime: {runtime_entries}"
    )
    assert _codes_view(snapshot) == dict(runtime_entries), (
        "快照的 codes 视图与 entries 视图不一致（同一份数据两处口径必须相等）"
    )


def test_baseline_views_are_self_consistent() -> None:
    """基线内部自洽：``codes`` 扁平视图必须与 ``entries`` 逐条相等（防手改 JSON 造成假冻结）。"""
    baseline = _baseline()
    assert _codes_view(baseline) == dict(_entries_view(baseline)), (
        f"基线 {BASELINE.name} 的 codes 与 entries 视图不一致；请用 `--write` 重生成而非手改"
    )


def test_baseline_declares_its_order_source() -> None:
    """基线记住顺序来自 `_CATALOG_CLASSES`——避免日后有人以为这里自带排序。"""
    assert _baseline()["order_source"] == "_CATALOG_CLASSES"


def test_new_codes_are_allowed() -> None:
    """只增语义：基线没有、当前注册表有的码不算漂移。"""
    assert registry_drift({"E_A": "AError"}, {"E_A": "AError", "E_NEW": "NewError"}) == []


def test_removed_code_is_reported() -> None:
    """删码必须被点名（含基线归属类）。"""
    issues = registry_drift({"E_GONE": "GoneError"}, {})
    assert issues == ["E_GONE: 已从注册表移除（基线归属 GoneError）"]


def test_reassigned_code_is_reported() -> None:
    """同一个码改归到另一个类也算破坏（客户端按码分派的语义被偷换）。"""
    issues = registry_drift({"E_MOVED": "OldError"}, {"E_MOVED": "NewError"})
    assert issues == ["E_MOVED: 归属从 OldError 改成 NewError"]
