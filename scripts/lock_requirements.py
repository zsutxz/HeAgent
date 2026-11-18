"""生成 / 校验 `requirements.lock`（从当前环境导出的精确版本集合）。

**定位**：`pyproject.toml` 只写区间约束（例如 `pydantic>=2.13,<2.14`），同一个约束在不同日期
安装会得到不同版本，出问题时「用的到底是哪个版本」无从复现。本脚本把当前环境的传递依赖全量
导出成 `name==version`，作为**参考锁定**：排查故障、比对两台机器、做依赖漏洞扫描的输入。

它**不接管安装**：CI 与本地仍按 `pyproject.toml` 的 extras 装（`pip install -e ".[dev,gui,http]"`），
lock 只描述「生成本文件的那套环境」。因此它在版本漂移时不会自己更新，需要显式重生成。

**更新流程**（改 `pyproject.toml` 的依赖 / 升级任何包之后）：

1. 在干净环境装齐 extras：``pip install -e ".[dev,gui,http]"``；
2. 用**该环境**的解释器重生成：``python scripts/lock_requirements.py``；
3. 校验幂等与一致性：``python scripts/lock_requirements.py --check``（应绿）；
4. 把 `requirements.lock` 与 `pyproject.toml` 的改动**放进同一个提交**——只提交其中之一会让
   「锁定的版本」与「约束的版本」互相矛盾。

**产物纪律**：文件里只有 `name==version` 行。editable 安装（本项目自身）、`-e` / `-r` 行、
直接 URL（`pkg @ https://…`、`pkg @ file://…`）与其它 pip 选项一律不写入——它们要么依赖本机路径、
要么不可从索引复现。被丢弃的行会打印条数，便于发现「某依赖没进锁」。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "requirements.lock"

#: 严格形态：`name==version`（name 允许 `.`/`-`/`_`；version 允许 PEP 440 的 `+local` / `!epoch` / 预发布标签）。
ENTRY = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[A-Za-z0-9][A-Za-z0-9.+!_-]*)$",
)

#: 环境标记（`; python_version < "3.12"`）是合法 pip 语法，但本锁由单一环境生成、不携带标记。
_ENV_MARKER = ";"


def _freeze(python: str) -> list[str]:
    """`pip freeze --exclude-editable` 的输出行（不含本项目的 editable 安装）。"""
    command = [python, "-m", "pip", "freeze", "--exclude-editable"]
    try:
        result = subprocess.run(command, capture_output=True, timeout=180, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"[lock] 无法执行 pip freeze：{exc}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"[lock] pip freeze 失败（exit {result.returncode}）：{stderr}")
    return result.stdout.decode("utf-8", "replace").splitlines()


def build_entries(frozen_lines: list[str]) -> tuple[list[str], int]:
    """把 pip freeze 输出规整成排序去重的 `name==version` 列表，返回 (条目, 丢弃行数)。

    丢弃（不入锁）：空行、注释、pip 选项行（``-e`` / ``-r`` / ``--index-url``）、直接 URL 引用
    （含 ``@``，会带本机路径或 git 地址）、无法解析的形态。同名条目按 name 小写去重（保留首个）。
    """
    entries: dict[str, str] = {}
    dropped = 0
    for raw in frozen_lines:
        line = raw.strip()
        if not line or line.startswith(("#", "-")) or "@" in line or _ENV_MARKER in line:
            dropped += 1 if line else 0
            continue
        match = ENTRY.match(line)
        if match is None:
            dropped += 1
            continue
        entries.setdefault(match["name"].lower(), f"{match['name']}=={match['version']}")
    return [entries[key] for key in sorted(entries)], dropped


def render(entries: list[str]) -> str:
    """锁文件正文：纯 `name==version` 行，行尾 LF，末尾单个换行（幂等的关键）。"""
    return "".join(f"{entry}\n" for entry in entries)


def _assert_lock_shape(text: str) -> None:
    """写盘前自检：正文只许 `name==version` 行——违反即 fail loud，不写出可疑文件。"""
    bad = [line for line in text.splitlines() if ENTRY.match(line) is None]
    if bad:
        raise SystemExit(f"[lock] 内部错误：非 name==version 行未过滤：{bad[:3]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lock_requirements.py",
        description="从当前环境导出 requirements.lock（name==version），或校验其是否最新。",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出路径（默认 requirements.lock）")
    parser.add_argument("--python", default=sys.executable, help="用于 pip freeze 的解释器（默认当前解释器）")
    parser.add_argument("--check", action="store_true", help="只校验：锁文件与当前环境一致则退出 0，否则 1")
    args = parser.parse_args(argv)

    entries, dropped = build_entries(_freeze(args.python))
    text = render(entries)
    _assert_lock_shape(text)
    output = Path(args.output)

    if args.check:
        current = output.read_text(encoding="utf-8") if output.is_file() else ""
        if current == text:
            print(f"[lock] up to date: {output.name} ({len(entries)} entries)")
            return 0
        expected = set(entries)
        actual = {line for line in current.splitlines() if line.strip()}
        print(f"[lock] stale: {output.name} differs from the installed environment", file=sys.stderr)
        for line in sorted(expected - actual)[:10]:
            print(f"[lock]   + {line}", file=sys.stderr)
        for line in sorted(actual - expected)[:10]:
            print(f"[lock]   - {line}", file=sys.stderr)
        print("[lock] 重新生成：python scripts/lock_requirements.py", file=sys.stderr)
        return 1

    previous = output.read_text(encoding="utf-8") if output.is_file() else None
    if previous == text:
        print(f"[lock] unchanged: {output.name} ({len(entries)} entries)")
        return 0
    output.write_text(text, encoding="utf-8", newline="\n")
    print(f"[lock] wrote {output.name}: {len(entries)} entries ({dropped} non-pinnable lines dropped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
