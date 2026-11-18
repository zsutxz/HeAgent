"""测试数据集中宿契约（Story 63.7）。

三条判据钉死 ``tests/fixtures/`` 是 ``tests/`` 树内唯一的静态测试数据存放点：

1. ``tests/`` 下任何非 ``.py`` 文件必须位于 ``fixtures/`` 内——数据散落即红并点名
   （``.heagent`` / ``__pycache__`` / ``.pytest_cache`` 是运行期产物，不参与判定）；
2. ``fixtures/README.md`` 必须登记全部数据域与引用约定；
3. conftest 的 ``fixtures_dir`` fixture 必须解析到真实 fixtures 根（``__file__`` 锚定，
   与启动 CWD 无关），且 ``ws_tls`` 材料真实存在。
"""

from __future__ import annotations

from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[0]

# 运行期产物目录：不参与数据宿判定（README「约定」节的口径）。
_RUNTIME_RESIDUE = {"__pycache__", ".heagent", ".pytest_cache"}


def _candidate_files() -> list[Path]:
    files: list[Path] = []
    for path in TESTS_ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(TESTS_ROOT).parts
        if _RUNTIME_RESIDUE.intersection(rel_parts):
            continue
        files.append(path)
    return files


def test_no_stray_data_files_outside_fixtures() -> None:
    """tests/ 下非 .py 文件必须住 fixtures/；散落即红并点名。"""
    stray = [p for p in _candidate_files() if p.suffix != ".py" and p.relative_to(TESTS_ROOT).parts[0] != "fixtures"]
    assert not stray, (
        f"发现 fixtures/ 之外的测试数据（迁入 tests/fixtures/<域>/，或为未清理的临时文件）: "
        f"{[str(p.relative_to(TESTS_ROOT)) for p in stray]}"
    )


def test_readme_registers_all_data_domains() -> None:
    """fixtures/README.md 必须登记全部数据域——机制文档缺失即红。"""
    readme = TESTS_ROOT / "fixtures" / "README.md"
    text = readme.read_text(encoding="utf-8")
    for domain in ("ws_tls", "contract_baselines", "js"):
        assert domain in text, f"README.md 未登记数据域 {domain}"


def test_fixtures_dir_fixture_resolves(fixtures_dir: Path) -> None:
    """fixtures_dir fixture 解析到真实根：__file__ 锚定 + ws_tls 材料在位。"""
    assert fixtures_dir == TESTS_ROOT / "fixtures"
    assert (fixtures_dir / "ws_tls" / "cert.pem").is_file()
    assert (fixtures_dir / "contract_baselines" / "public_exports.json").is_file()
