"""依赖锁的漂移判据（A66）：``requirements.lock`` 必须覆盖 ``pyproject.toml`` 声明的每个包。

锁由 `scripts/lock_requirements.py` 从**生成时的那套环境**全量导出，`--check` 只验「与当前环境
一致」；本测试补的是另一半——「锁里的包集合 ⊇ 声明的包集合」，即改了 `pyproject.toml` 却忘了
重新生成锁时能红。版本区间是否被锁满足不在本测试面内（区间允许漂移，那正是锁存在的理由）。
"""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements.lock"
PYPROJECT = ROOT / "pyproject.toml"

_ENTRY = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s]+)$")


def _normalize(name: str) -> str:
    """PEP 503 归一：小写、`._-` 统一成 `-`。"""
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_names() -> set[str]:
    names: set[str] = set()
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENTRY.match(stripped)
        assert match is not None, f"requirements.lock 存在非 `name==version` 行：{line!r}"
        names.add(_normalize(match.group("name")))
    return names


def _requirement_names(spec: str) -> str:
    """从一条 requirement 字符串取出包名（去掉版本约束、extras 与环境标记）。"""
    head = re.split(r"[<>=!~;\[ ]", spec.strip(), maxsplit=1)[0]
    return _normalize(head)


def _dist_installed(name: str) -> bool:
    """本环境是否装了该分发（按分发名查，不做导入）。"""
    try:
        metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return False
    return True


def test_lock_covers_every_declared_requirement() -> None:
    """core 依赖必须全在锁里；optional extra 只在**本环境已安装**时要求（锁 = 生成时的那套环境）。"""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    lock_names = _lock_names()

    core = [_requirement_names(spec) for spec in project["dependencies"]]
    missing_core = sorted(name for name in core if name not in lock_names)
    assert missing_core == [], (
        f"requirements.lock 未覆盖核心依赖：{missing_core}；改过 pyproject.toml 后请重生成锁"
        "（python scripts/lock_requirements.py）并与改动同一提交"
    )

    optional = [
        _requirement_names(spec)
        for specs in project.get("optional-dependencies", {}).values()
        for spec in specs
        if _dist_installed(_requirement_names(spec))
    ]
    missing_optional = sorted(name for name in optional if name not in lock_names)
    assert missing_optional == [], (
        f"这些声明依赖已装在本环境、但 requirements.lock 里没有：{missing_optional}；锁与安装面不一致 ⇒ 重新生成锁"
    )


def test_lock_does_not_pin_the_project_itself() -> None:
    """editable 安装（本项目自身）不该以固定版本出现在锁里。"""
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert _normalize(project["name"]) not in _lock_names()
