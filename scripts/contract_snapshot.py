#!/usr/bin/env python3
"""导出并校验 HeAgent 的契约快照（公共导出面 / 传输路由 / 异常类型）。

纯 stdlib（argparse / ast / json / sys / pathlib）、AST 静态解析，不导入 heagent 本体，
因此可在任何 Python 3.9+ 环境离线运行。

用法::

    python3 scripts/contract_snapshot.py --write          # 重新生成三份基线
    python3 scripts/contract_snapshot.py --check          # 校验基线是否与代码一致（默认）
    python3 scripts/contract_snapshot.py --write --only public

退出码：``0`` = 一致（或 ``--write`` 写成功）；``1`` = 与基线不一致（打印首个差异位置）；
``2`` = 参数或环境错误（基线缺失、源码树不可读）。

退出码为 ``1`` 时，若变更属**有意**修改，用 ``--write`` 重生基线并在提交信息里说明差异；
若属**意外**漂移，应改代码而不是改基线。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = REPO_ROOT / "tests" / "contract_baselines"

PUBLIC_MODULES = (
    "src/heagent/__init__.py",
    "src/heagent/config/__init__.py",
    "src/heagent/config/catalog.py",
    "src/heagent/pub/types.py",
    "src/heagent/pub/exceptions.py",
    "src/heagent/network/http_protocol.py",
    "src/heagent/network/http_console_protocol.py",
)

ROUTE_MODULES = (
    "src/heagent/network/http_server.py",
    "src/heagent/network/ws_host.py",
)

EXCEPTION_ROOT = "src/heagent"
ERROR_SUFFIXES = ("Error", "Exception")
HTTP_PROTOCOL_MODULE = "src/heagent/network/http_protocol.py"

SNAPSHOT_NAMES = {
    "public": "public_exports.json",
    "routes": "transport_routes.json",
    "exceptions": "exception_types.json",
}


# ---------------------------------------------------------------- 通用工具


def module_name(rel_path: str) -> str:
    """src/heagent/a/b.py -> heagent.a.b ; src/heagent/a/__init__.py -> heagent.a"""
    parts = Path(rel_path).with_suffix("").parts
    if parts and parts[0] == "src":
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def parse_file(rel_path: str) -> ast.Module:
    source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    return ast.parse(source, filename=rel_path)


def dump(payload: object) -> str:
    """唯一序列化口径：与平台、时间、路径无关的稳定文本。"""
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def string_assignments(tree: ast.Module) -> dict[str, str]:
    """模块级 `NAME = "literal"` 的名字 → 字符串值。"""
    table: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        table[target.id] = value.value
    return table


def module_all(tree: ast.Module) -> list[str] | None:
    """模块级 `__all__` 字面量列表；无则 None（快照里落 null）。"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        return None
                    if isinstance(value, (list, tuple)):
                        return [str(item) for item in value]
                    return None
    return None


def dotted_tail(node: ast.AST) -> str | None:
    """`Foo` / `mod.Foo` 都取末段名。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


# ------------------------------------------------------- A. public_exports


def collect_public() -> dict[str, object]:
    modules: dict[str, object] = {}
    for rel_path in PUBLIC_MODULES:
        tree = parse_file(rel_path)
        defined: set[str] = set()
        imported: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        defined.add(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                defined.add(node.target.id)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported.add(alias.asname or alias.name)
        modules[module_name(rel_path)] = {
            "defined": sorted(defined),
            "imported": sorted(imported),
            "all": module_all(tree),
        }
    return {"modules": modules}


# ---------------------------------------------------- C. transport_routes


def call_name(node: ast.AST) -> str | None:
    """`Route(...)` / `routing.Route(...)` 都认作 "Route"。"""
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
    return None


def collect_routes() -> dict[str, object]:
    path_constants: dict[str, dict[str, str]] = {}
    registrations: dict[str, int] = {}
    routes: list[dict[str, object]] = []
    for rel_path in ROUTE_MODULES:
        tree = parse_file(rel_path)
        constants = string_assignments(tree)
        path_constants[rel_path] = constants
        if "ws_host" in rel_path:
            listener = "ws"
        elif "http_server" in rel_path:
            listener = "http"
        else:
            listener = "http_console"
        count = 0
        # ast.walk 覆盖跨行 / 嵌套（if / try / 循环体内）的 Route(...) 调用
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or call_name(node) != "Route":
                continue
            count += 1
            path: str | None = None
            path_expr: str | None = None
            if node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    path = first.value
                elif isinstance(first, ast.Name):
                    path_expr = first.id
                    path = constants.get(first.id, f"<unresolved: {first.id}>")
                else:
                    path_expr = "<expr>"
                    path = "<unresolved: <expr>>"
            methods: list[str] = []
            name: str | None = None
            for keyword in node.keywords:
                if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
                    methods = [
                        element.value
                        for element in keyword.value.elts
                        if isinstance(element, ast.Constant) and isinstance(element.value, str)
                    ]
                elif keyword.arg == "endpoint":
                    name = dotted_tail(keyword.value)
            routes.append(
                {
                    "listener": listener,
                    "name": name,
                    "path": path,
                    "path_expr": path_expr,
                    "methods": sorted(methods),
                    "source": rel_path,
                }
            )
        registrations[rel_path] = count
    # 列表顺序显式排序：json sort_keys 不覆盖数组，顺序必须自带确定性
    routes.sort(key=lambda item: (item["listener"], item["path"] or "", item["name"] or "", item["source"]))
    return {
        "path_constants": path_constants,
        "registrations": registrations,
        "route_count": sum(registrations.values()),
        "routes": routes,
    }


# ------------------------------------------------- D. exception_types


def iter_source_files() -> list[Path]:
    return sorted(path for path in (REPO_ROOT / EXCEPTION_ROOT).rglob("*.py") if path.is_file())


def collect_http_error_codes() -> dict[str, dict[str, str]]:
    tree = parse_file(HTTP_PROTOCOL_MODULE)
    codes: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "HttpErrorCode":
            for item in node.body:
                if isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant):
                    for target in item.targets:
                        if isinstance(target, ast.Name):
                            codes[target.id] = str(item.value.value)
    return {"HttpErrorCode": dict(sorted(codes.items()))}


def collect_exceptions() -> dict[str, object]:
    entries: list[dict[str, object]] = []
    for path in iter_source_files():
        rel_path = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)
        exported = set(module_all(tree) or [])
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [base for base in (dotted_tail(base) or "" for base in node.bases) if base]
            named = any(base.endswith(ERROR_SUFFIXES) for base in bases)
            if not named and node.name not in exported:
                continue
            entries.append(
                {
                    "module": module_name(rel_path),
                    "name": node.name,
                    "bases": sorted(bases),
                }
            )
    entries.sort(key=lambda item: (item["module"], item["name"]))
    return {"classes": entries, "http_error_codes": collect_http_error_codes()}


# ------------------------------------------------------------ CLI 主流程


BUILDERS = {
    "public": collect_public,
    "routes": collect_routes,
    "exceptions": collect_exceptions,
}


def baseline_path(kind: str) -> Path:
    return BASELINE_DIR / SNAPSHOT_NAMES[kind]


def first_difference(expected: object, actual: object, trail: str = "") -> str | None:
    """返回首个差异的可读位置（基线名 + 名字路径），不含行号 / 时间戳。"""
    if type(expected) is not type(actual):
        return f"{trail or '<root>'}: 类型 {type(expected).__name__} != {type(actual).__name__}"
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            if key not in expected:
                return f"{trail}.{key}: 基线缺失、代码新增"
            if key not in actual:
                return f"{trail}.{key}: 基线存在、代码缺失"
            found = first_difference(expected[key], actual[key], f"{trail}.{key}")
            if found:
                return found
        return None
    if isinstance(expected, list) and isinstance(actual, list):
        for index in range(min(len(expected), len(actual))):
            found = first_difference(expected[index], actual[index], f"{trail}[{index}]")
            if found:
                return found
        if len(expected) != len(actual):
            return f"{trail or '<root>'}: 长度 {len(expected)} != {len(actual)}"
        return None
    if expected != actual:
        return f"{trail or '<root>'}: {expected!r} != {actual!r}"
    return None


def do_check(kinds: list[str]) -> int:
    failures = 0
    for kind in kinds:
        path = baseline_path(kind)
        if not path.is_file():
            print(f"[FAIL] {kind}: 基线文件缺失 -> {path.relative_to(REPO_ROOT).as_posix()}")
            failures += 1
            continue
        expected = json.loads(path.read_text(encoding="utf-8"))
        diff = first_difference(expected, BUILDERS[kind]())
        if diff:
            print(f"[FAIL] {kind} ({path.name}): 首个差异 @ {diff}")
            failures += 1
        else:
            print(f"[OK] {kind} ({path.name})")
    return 1 if failures else 0


def do_write(kinds: list[str]) -> int:
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    for kind in kinds:
        text = dump(BUILDERS[kind]())
        baseline_path(kind).write_text(text, encoding="utf-8", newline="\n")
        print(
            f"[WRITE] {kind} -> {baseline_path(kind).relative_to(REPO_ROOT).as_posix()}"
            f" ({len(text.encode('utf-8'))} bytes)"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出/校验 HeAgent 契约快照")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="重新生成基线文件")
    mode.add_argument("--check", action="store_true", help="校验基线是否与代码一致（默认）")
    parser.add_argument("--only", default="all", choices=["all", *SNAPSHOT_NAMES], help="只处理某一类快照")
    args = parser.parse_args(argv)

    kinds = list(SNAPSHOT_NAMES) if args.only == "all" else [args.only]
    return do_write(kinds) if args.write else do_check(kinds)


if __name__ == "__main__":
    sys.exit(main())
