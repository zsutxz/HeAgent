"""入口兜底异常族清单（``ERROR_FAMILIES``）的守恒判据（A72）。

口径：入口层不写 ``except HeAgentError``，而是显式列举它的**全部直接子类**。
新增直接子类却忘记登记 ⇒ 本测试红——新错误族必须被显式接纳（进而可被赋予各自的出口行为），
而不是被根类静默吞成一行 ``[error]``。
"""

from __future__ import annotations

from pathlib import Path

from heagent.pub.exceptions import ERROR_FAMILIES, HeAgentError

SRC = Path(__file__).resolve().parents[1] / "src" / "heagent"


def test_error_families_cover_every_direct_subclass() -> None:
    direct = set(HeAgentError.__subclasses__())
    families = set(ERROR_FAMILIES)
    assert families == direct, (
        f"ERROR_FAMILIES 与 HeAgentError 直接子类不一致：缺 {direct - families}，多 {families - direct}"
    )


def test_error_families_are_all_framework_errors() -> None:
    # 顺序 = 类定义顺序（``__subclasses__()`` 是定义序），与异常体系章节同序，便于对读。
    assert list(ERROR_FAMILIES) == list(HeAgentError.__subclasses__())
    for cls in ERROR_FAMILIES:
        assert issubclass(cls, HeAgentError)


def test_cli_entry_layer_never_catches_the_root_class() -> None:
    """结构守卫：``cli/`` 下不得再出现裸 ``except HeAgentError``。"""
    offenders = [
        path.name for path in (SRC / "cli").glob("*.py") if "except HeAgentError" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"这些入口模块仍用根类兜底：{offenders}"
