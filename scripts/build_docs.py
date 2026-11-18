#!/usr/bin/env python3
"""一条命令生成本地文档站点（`mkdocs build --strict`）+ 版本注入 + 产物摘要。

旧流程要靠人记住那条 mkdocs 命令，且站点不声明版本。本脚本把三件事固定下来：

1. **构建**：`sys.executable -m mkdocs build --strict`（`--strict` = 未 ignore 的告警一律失败，
   告警口径见 `mkdocs.yml` 的 `validation:` 注释），与 CI 的 docs 门同一参数；
2. **版本注入**：把 ``src/heagent/__init__.py::__version__``（版本唯一真源）经环境变量交给
   `mkdocs.yml` 的 `!ENV` 标签，页脚因此显示「HeAgent vX.Y.Z」；脚本用 AST 读常量，不导入
   heagent 运行栈（构建期工具不需要装运行依赖）；
3. **产物摘要**：打印站点目录、页面数（数 `.html`），并把版本落成 ``<site_dir>/version.txt``
   随站点一起发布。

纯 stdlib（ast / importlib / os / re / subprocess / sys / pathlib）。

用法::

    python scripts/build_docs.py

退出码：``0`` = 构建成功；``1`` = 构建失败（mkdocs 返回非零，或产物目录缺失）；
``2`` = 环境错误（版本号读不到 / 缺 mkdocs / 无法启动解释器）。
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INIT_MODULE = REPO_ROOT / "src" / "heagent" / "__init__.py"
MKDOCS_CONFIG = REPO_ROOT / "mkdocs.yml"

#: 缺 mkdocs 时给出的**可执行**提示（mkdocs 是构建期工具，刻意不在依赖树里）。
INSTALL_HINT = "pip install mkdocs"

#: `site_dir` 是 `mkdocs.yml` 里的裸标量；只取该键字面值，不做完整 YAML 解析（`!ENV` 标签
#: 会让 `SafeLoader` 报未知 tag，为一个路径引入自定义 loader 得不偿失）。
SITE_DIR_PATTERN = re.compile(r"^site_dir:\s*([^#\s]+)", flags=re.MULTILINE)

#: mkdocs 自己的默认站点目录（`mkdocs.yml` 省略 `site_dir` 时）。
DEFAULT_SITE_DIR = "site"

#: 成功/失败的日志前缀，便于在 CI 日志里 grep。
PREFIX = "[docs]"


def read_version() -> str:
    """``src/heagent/__init__.py`` 的 ``__version__``（AST 取值，不 import 运行栈）。"""
    tree = ast.parse(INIT_MODULE.read_text(encoding="utf-8"), filename=str(INIT_MODULE))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__":
                    value = ast.literal_eval(node.value)
                    if not isinstance(value, str):
                        raise ValueError(f"__version__ is not a string literal: {value!r}")
                    return value
    raise LookupError(f'{INIT_MODULE.relative_to(REPO_ROOT)} has no module-level `__version__ = "..."`')


def read_site_dir() -> Path:
    """`mkdocs.yml` 里 `site_dir` 指向的绝对路径（缺省回退 mkdocs 的 `site`）。"""
    match = SITE_DIR_PATTERN.search(MKDOCS_CONFIG.read_text(encoding="utf-8"))
    raw = match.group(1).strip("\"'") if match else DEFAULT_SITE_DIR
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def display(path: Path) -> str:
    """仓库内路径显示成相对形态（日志可读、跨机器可比）。"""
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def build_environment(version: str) -> dict[str, str]:
    """构建子进程的环境：注入 `mkdocs.yml` 的 `!ENV` 两个键，其余原样继承。"""
    env = dict(os.environ)
    env["HEAGENT_DOC_VERSION"] = version
    env["HEAGENT_DOC_COPYRIGHT"] = f"HeAgent v{version} · 文档版本随代码版本发布"
    return env


def report(site_dir: Path, version: str) -> int:
    """落 `version.txt` 并打印产物摘要；页面数 = 站点里的 `.html` 文件数。"""
    if not site_dir.is_dir():
        print(f"{PREFIX} 构建自报成功，但产物目录不存在：{display(site_dir)}", file=sys.stderr)
        return 1
    version_file = site_dir / "version.txt"
    version_file.write_text(f"{version}\n", encoding="utf-8")
    pages = sum(1 for _ in site_dir.rglob("*.html"))
    print(f"{PREFIX} 构建成功")
    print(f"  version:      {version}  （真源 src/heagent/__init__.py）")
    print(f"  site:         {display(site_dir)}")
    print(f"  pages:        {pages} 个 .html")
    print(f"  version file: {display(version_file)}")
    return 0


def main() -> int:
    try:
        version = read_version()
        site_dir = read_site_dir()
    except (OSError, SyntaxError, ValueError, LookupError) as exc:
        print(f"{PREFIX} 读不到版本号或站点目录：{exc}", file=sys.stderr)
        return 2

    if importlib.util.find_spec("mkdocs") is None:
        print(
            f"{PREFIX} 缺少构建依赖 mkdocs（构建期工具，不在项目依赖树里）。\n  Try: {INSTALL_HINT}",
            file=sys.stderr,
        )
        return 2

    print(f"{PREFIX} mkdocs build --strict（版本 {version}）")
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "mkdocs", "build", "--strict"],
            cwd=REPO_ROOT,
            env=build_environment(version),
            check=False,
        )
    except OSError as exc:
        print(f"{PREFIX} 无法启动 `{sys.executable} -m mkdocs`：{exc}", file=sys.stderr)
        return 2

    if completed.returncode != 0:
        print(
            f"{PREFIX} 构建失败（mkdocs 退出码 {completed.returncode}）。"
            "`--strict` 下未 ignore 的 warning 即失败，先修上面的告警。",
            file=sys.stderr,
        )
        return 1
    return report(site_dir, version)


if __name__ == "__main__":
    raise SystemExit(main())
