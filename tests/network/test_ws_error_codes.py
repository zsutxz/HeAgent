"""74.5 · 错误码台账与哑传输边界收口（E74 的两条「不新增」承诺各一条判据）。

本 entry 预期**零 src 改动**：它的价值是证明 E74 引入的两条判定路径（带 ``project_id`` 的提交、
``cancel_run`` 取消）可能抛出的每一个 code 都是 ``HttpErrorCode`` **既有**成员、且在
``transport_errors`` 基线里有条目 —— 也就是说「新增错误码」这件事本 epic 一件都没做。

第二组判据守 ``network/`` 的哑传输边界。注意口径：这里断言的是**导入面**（AST 的
``import`` / ``from ... import``），不是源码文本——网络层多处 docstring 会写「镜像
``heagent.config.catalog`` 的同名常量」「不得 import ``heagent.engine.tasks``」这类**说明**，
按纯文本搜会把正当注释判成违规。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from heagent.network.http_protocol import HttpErrorCode

_NETWORK = Path(__file__).resolve().parents[2] / "src" / "heagent" / "network"
_BASELINE = Path(__file__).resolve().parents[1] / "fixtures" / "contract_baselines" / "transport_errors.json"

#: E74 的两条新判定路径可能产生的**全部** code（提交 + 取消）。它们必须都是既有成员。
_E74_CODES = (
    "unknown_project",
    "project_unavailable",
    "project_busy",
    "run_conflict",
    "total_inflight_limit",
    "unknown_run",
    "invalid_request",
)

#: ``network/`` 不得导入的运行栈与配置前缀（含 ``TYPE_CHECKING`` 分支）。
_FORBIDDEN_IMPORT_PREFIXES = (
    "heagent.cli",
    "heagent.config",
    "heagent.pub.projects",
    "heagent.engine",
    "heagent.agent",
)


def _network_sources() -> list[Path]:
    return sorted(_NETWORK.rglob("*.py"))


def _imported_names(path: Path) -> set[str]:
    """模块里出现的全部导入目标（含 ``from ... import`` 的模块名与 ``import`` 的别名）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize("code", _E74_CODES)
def test_e74_error_codes_are_existing_members(code: str) -> None:
    """七条 code 都是 ``HttpErrorCode`` 的既有成员：本 epic 没有新增错误码。"""
    assert code in {item.value for item in HttpErrorCode}


@pytest.mark.parametrize("code", _E74_CODES)
def test_e74_error_codes_are_registered_in_the_transport_baseline(code: str) -> None:
    """每条 code 在 ``transport_errors`` 基线里有条目（或落在既有的未分派清单里）。"""
    baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))

    assert code in {entry["code"] for entry in baseline["entries"]} or code in baseline["unmapped_codes"]


def test_network_never_imports_the_runtime_stack_or_config() -> None:
    """哑传输：``network/`` 对运行栈与配置面的导入面**零命中**（含 ``TYPE_CHECKING``）。"""
    offenders: list[str] = []
    for path in _network_sources():
        for name in _imported_names(path):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in _FORBIDDEN_IMPORT_PREFIXES):
                offenders.append(f"{path.relative_to(_NETWORK).as_posix()} → {name}")
    assert offenders == [], "network/ 导入了运行栈或配置面：" + "; ".join(offenders)


def test_network_never_touches_the_filesystem_to_resolve_projects() -> None:
    """项目解析不进传输层：``network/`` 里没有 ``is_dir`` 调用（项目目录由注入端口自己解析）。"""
    offenders = [
        path.relative_to(_NETWORK).as_posix()
        for path in _network_sources()
        if "is_dir" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_network_still_has_no_http_transport_import_cycle() -> None:
    """同层传输模块互不依赖：WS 侧模块不导入 ``network/http_server``（共享契约住 ``http_protocol``）。"""
    ws_modules = [
        "ws_server.py",
        "ws_commands.py",
        "ws_protocol.py",
        "ws_host.py",
        "ws_auth.py",
    ]
    offenders = [
        f"{name} → heagent.network.http_server"
        for name in ws_modules
        if "heagent.network.http_server" in _imported_names(_NETWORK / name)
    ]
    assert offenders == []
