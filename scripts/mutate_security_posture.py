#!/usr/bin/env python3
"""S-10 红化自检：安全口径守卫的**变异体验证**（可复跑，默认 fail-closed）。

用法
====
    python scripts/mutate_security_posture.py

它依次施加两个变异体、跑对应的判据子集、断言**必须变红**，然后无论成败都还原原文件：

- M1 删掉 `docs/frame.md` 4.19 canonical 段的**第 3 要素**（本地模式口径）⇒ G1 必须红，
  且失败信息里要出现 `docs/frame.md` + `要素 3` + 缺失短语 + 行号。
- M2 把 `Settings.ws_cli_bypass_enabled` 的默认值改成 `True` ⇒ G2 的安全侧布尔判据必须红，
  且失败信息里要出现 `ws_cli_bypass_enabled`。

判据（脚本退出码）：两个变异体都精确变红、原文件还原成功 ⇒ exit 0；任一不满足 ⇒ exit 1。
为什么入库而不是留在 `.heagent/tmp/`：变异体验证是这条守卫的**可复核证据**，后续改动可重放。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / "docs" / "frame.md"
CONFIG = ROOT / "src" / "heagent" / "config" / "__init__.py"
TEST = "tests/test_security_posture_contract.py"
BACKUP_DIR = ROOT / ".heagent" / "tmp" / "mutate-security-posture"

ELEMENT3_HEAD = "3. **本地模式口径**"
WS_BYPASS = "    ws_cli_bypass_enabled: bool = False"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)


def _pytest_subset(selector: str) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "-m", "pytest", TEST, "-q", "-k", selector])


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def _backup() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    # 只拷内容，不拷元数据：本机 `/workspace` 是 9p 挂载，copystat 的 utime 会 EPERM。
    shutil.copyfile(FRAME, BACKUP_DIR / "frame.md.bak")
    shutil.copyfile(CONFIG, BACKUP_DIR / "config.bak")


def _restore() -> None:
    # 同上：只还原内容（`_write` 走 write_bytes），避免 copystat 在 9p 上 EPERM 半途而废。
    _write(FRAME, _read(BACKUP_DIR / "frame.md.bak"))
    _write(CONFIG, _read(BACKUP_DIR / "config.bak"))


def _baseline_green() -> bool:
    result = _pytest_subset("frame_canonical or security_side_booleans")
    print(f"[baseline] {result.stdout.strip().splitlines()[-1] if result.stdout.strip() else result.stderr.strip()}")
    return result.returncode == 0


def _mutate_frame_drop_element3() -> tuple[bool, str]:
    text = _read(FRAME)
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith(ELEMENT3_HEAD)), None)
    if start is None:
        return False, "未找到第 3 要素起始行"
    end = start + 1
    while end < len(lines) and not lines[end].startswith("4. "):
        end += 1
    _write(FRAME, "".join(lines[:start] + lines[end:]))
    return True, ""


def _mutate_backend_default() -> tuple[bool, str]:
    text = _read(CONFIG)
    if text.count(WS_BYPASS) != 1:
        return False, f"锚点不唯一：{WS_BYPASS!r}"
    _write(CONFIG, text.replace(WS_BYPASS, WS_BYPASS.replace("False", "True")))
    return True, ""


def main() -> int:
    _backup()
    failures: list[str] = []
    try:
        if not _baseline_green():
            failures.append("baseline 不是绿的：先修守卫本身，变异验证无意义")

        ok, why = _mutate_frame_drop_element3()
        if not ok:
            failures.append(f"M1 施加失败：{why}")
        else:
            result = _pytest_subset("frame_canonical or numbers_six")
            out = result.stdout + result.stderr
            red = result.returncode != 0
            named = "docs/frame.md" in out and "要素 3" in out
            print(f"[M1 删第 3 要素] red={red} named={named}")
            if not red:
                failures.append("M1 没有变红：G1 未能守住要素缺失")
            elif not named:
                failures.append("M1 变红了但失败信息没点名 docs/frame.md + 要素 3")
        _restore()

        ok, why = _mutate_backend_default()
        if not ok:
            failures.append(f"M2 施加失败：{why}")
        else:
            result = _pytest_subset("security_side_booleans")
            out = result.stdout + result.stderr
            red = result.returncode != 0
            named = "ws_cli_bypass_enabled" in out
            print(f"[M2 旁路默认改 True] red={red} named={named}")
            if not red:
                failures.append("M2 没有变红：G2 未能守住安全侧布尔默认")
            elif not named:
                failures.append("M2 变红了但失败信息没点名 ws_cli_bypass_enabled")
        _restore()
    finally:
        _restore()

    if failures:
        print("VERDICT: FAIL")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("VERDICT: PASS（两个变异体均精确变红，原文件已还原）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
