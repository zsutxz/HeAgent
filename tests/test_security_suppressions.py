"""安全抑制注解的双引擎契约（ruff ``S`` 规则族 ↔ bandit ``B`` 规则族）。

背景（2026-10-23 实测）：CI 的 lint job 同时跑 ``ruff check`` 与 ``bandit -r src/ -ll``，但两者
**互不认对方的抑制注解**——ruff 只认 ``# noqa: S###``，bandit 只认 ``# nosec B###``。只写一方
的行会在另一侧静默变红：``goal/script_runtime.py``（``exec``）与 ``network/http_server.py``
（通配地址识别）当时只写了 ruff 侧的 noqa，bandit 报 2 条 medium ⇒ lint job 失败 ⇒
``needs: lint`` 让 test 矩阵全部跳过，而本地 ``scripts/quality_gate.py`` 当时没有 bandit 门，
所以本地始终显示全绿。本判据把两条不变量钉死：

1. ``src/`` 里每一条 ``# noqa: S<n>`` 必须在同一行带 ``# nosec B<n>``（两引擎口径不漂移）。
2. 任何 ``# nosec`` 都必须点名测试编号（禁止裸 ``# nosec`` 抑制整行全部告警）。

镜像**刻意不按严重度筛选**：``-ll``（medium 及以上）只是当前选定的门限，``S603``/``S607``
这类 bandit 只报 LOW 的抑制也一并镜像（注：bandit 把 ``B607`` 记在**调用行**、把 ruff 的
``S607`` 记在 argv 行，所以这两处的 nosec 在 ``-ll`` 下不产生可见差异——对齐的是「抑制面」
而非「当前是否恰好被报告」）。理由是一旦门限放宽或某条规则升级严重度，抑制集已经
对齐的代码不会突然变红；反过来「按当前严重度挑着镜像」会随 bandit 版本悄悄失效。

``# nosec`` 的理由文字**只写中文**：bandit 会把注释里每个 ASCII 词当作测试名解析，命中不上就
逐词打 WARNING（``Test in comment: ... is not a test name or id``）——实测英文理由会刷出噪声。
ASCII 说明（例如要引用文件名）请写在相邻的代码注释里，不要塞进 nosec 理由段。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src" / "heagent"

_NOQA = re.compile(r"#\s*noqa:\s*(?P<codes>[A-Z]+[0-9]+(?:[\s,]+[A-Z]+[0-9]+)*)")
_NOSEC = re.compile(r"#\s*nosec\b(?P<rest>[^#]*)")
_NOSEC_CODE = re.compile(r"B[0-9]+")
_ASCII_WORD = re.compile(r"[A-Za-z]")


def _source_files() -> list[Path]:
    files = sorted(SRC_ROOT.rglob("*.py"))
    assert files, f"未扫描到任何源文件：{SRC_ROOT}"
    return files


def _sites() -> list[tuple[str, int, str]]:
    """``(相对路径, 行号, 行文本)`` —— 只取含抑制注解的行。"""
    sites: list[tuple[str, int, str]] = []
    for path in _source_files():
        relative = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _NOQA.search(line) or _NOSEC.search(line):
                sites.append((relative, lineno, line))
    return sites


def _nosec_codes(line: str) -> set[str]:
    match = _NOSEC.search(line)
    if match is None:
        return set()
    return set(_NOSEC_CODE.findall(match.group("rest")))


def test_ruff_security_noqa_is_mirrored_by_bandit_nosec() -> None:
    """ruff 的 ``S`` 抑制必须在同一行镜像成 bandit 的 ``B`` 抑制。"""
    missing: list[str] = []
    for relative, lineno, line in _sites():
        match = _NOQA.search(line)
        if match is None:
            continue
        nosec = _nosec_codes(line)
        for code in re.findall(r"[A-Z]+[0-9]+", match.group("codes")):
            if not code.startswith("S"):
                continue
            bandit_code = f"B{code[1:]}"
            if bandit_code not in nosec:
                missing.append(f"{relative}:{lineno} 缺 `# nosec {bandit_code}`")
    assert missing == [], "ruff 抑制未镜像到 bandit：" + "; ".join(missing)


def test_nosec_reasons_stay_ascii_free() -> None:
    """``# nosec`` 的理由段只写中文（bandit 会把 ASCII 词逐词当测试名解析并告警）。"""
    noisy: list[str] = []
    for relative, lineno, line in _sites():
        match = _NOSEC.search(line)
        if match is None:
            continue
        rest = match.group("rest")
        if "-" not in rest:
            continue
        reason = _NOSEC_CODE.sub("", rest.split("-", 1)[1])
        if _ASCII_WORD.search(reason) is not None:
            noisy.append(f"{relative}:{lineno}")
    assert noisy == [], "`# nosec` 理由含 ASCII 词（bandit 会逐词告警）：" + ", ".join(noisy)


def test_nosec_suppressions_are_code_scoped() -> None:
    """``# nosec`` 必须点名测试编号，不允许裸抑制整行。"""
    blanket: list[str] = []
    for relative, lineno, line in _sites():
        if _NOSEC.search(line) is None:
            continue
        if not _nosec_codes(line):
            blanket.append(f"{relative}:{lineno}")
    assert blanket == [], "存在裸 `# nosec`（未点名测试编号）：" + ", ".join(blanket)
