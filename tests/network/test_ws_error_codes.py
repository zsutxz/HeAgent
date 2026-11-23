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


def _package_of(path: Path) -> str:
    """文件所属包（``ws_commands.py`` → ``heagent.network``）：相对导入靠它补全成绝对名。"""
    parts = list(path.relative_to(_NETWORK).parts[:-1])
    return ".".join(["heagent", "network", *parts])


def _imported_modules(tree: ast.Module, package: str) -> set[str]:
    """模块里出现的全部导入目标（``from ... import`` 的模块名、``import`` 的别名与**相对**写法）。

    相对导入必须补全：``from ..config import get_settings`` 在 ``network/`` 里就是
    ``heagent.config``——只认 ``node.module`` 的绝对名会让包内最惯用的写法整条绕过本守卫。
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)]
                module = ".".join([*anchor, module]) if module else ".".join(anchor)
            if module:
                names.add(module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def _imported_names(path: Path) -> set[str]:
    """单个源文件的导入面（含相对写法，按文件所属包补全）。"""
    return _imported_modules(ast.parse(path.read_text(encoding="utf-8")), _package_of(path))


@pytest.mark.parametrize("code", _E74_CODES)
def test_e74_error_codes_are_existing_members(code: str) -> None:
    """七条 code 都是 ``HttpErrorCode`` 的既有成员：本 epic 没有新增错误码。"""
    assert code in {item.value for item in HttpErrorCode}


@pytest.mark.parametrize("code", _E74_CODES)
def test_e74_error_codes_are_registered_in_the_transport_baseline(code: str) -> None:
    """每条 code 在 ``transport_errors`` 基线里**有具名条目**：不接受「落在未分派清单」这档。

    ``unmapped_codes`` 是「服务端会产生但状态表不分派」的历史清单；让本判据容它，等于某条 code
    掉出 entries 时用例仍绿而 R4 已不成立。
    """
    baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))

    assert code in {entry["code"] for entry in baseline["entries"]}


def test_network_never_imports_the_runtime_stack_or_config() -> None:
    """哑传输：``network/`` 对运行栈与配置面的导入面**零命中**（含 ``TYPE_CHECKING``）。"""
    offenders: list[str] = []
    for path in _network_sources():
        for name in _imported_names(path):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in _FORBIDDEN_IMPORT_PREFIXES):
                offenders.append(f"{path.relative_to(_NETWORK).as_posix()} → {name}")
    assert offenders == [], "network/ 导入了运行栈或配置面：" + "; ".join(offenders)


def test_network_never_touches_the_filesystem_to_resolve_projects() -> None:
    """项目解析不进传输层：``network/`` 里没有 ``is_dir`` 调用（项目目录由注入端口自己解析）。

    按 **AST** 判（属性/名字引用），不按源码文本：docstring 与注释里提到 ``is_dir`` 属于说明，
    文本匹配会把正当注释判成违规（与本文件其余断言的导入面口径一致）。
    """
    offenders = [
        path.relative_to(_NETWORK).as_posix()
        for path in _network_sources()
        if any(
            (isinstance(node, ast.Attribute) and node.attr == "is_dir")
            or (isinstance(node, ast.Name) and node.id == "is_dir")
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        )
    ]
    assert offenders == []


def test_import_face_recognizer_resolves_relative_imports() -> None:
    """相对导入同样算导入面：``from ..config import x`` 在 ``network/`` 里就是 ``heagent.config``。

    E74 R2 反证（2026-11-23）：本守卫原先只看 ``node.module`` 的绝对名，把
    ``from ..config import get_settings`` 写进 ``network/ws_commands.py`` 时这里与架构契约双绿
    ——守卫对包内最惯用的写法没有牙。本用例钉住识别器本身。
    """
    tree = ast.parse("from ..config import get_settings\nfrom .ws_protocol import WsCommand\n")

    assert _imported_modules(tree, "heagent.network") == {
        "heagent.config",
        "heagent.network.ws_protocol",
    }


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
