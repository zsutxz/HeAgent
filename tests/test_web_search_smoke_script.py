"""`scripts/web_search_smoke.py` 的契约（E78-S02）：A55 的闭合工具本身得先可信。

冒烟脚本要真打外部 API，所以本文件**不联网**：只验三件可离线判定的行为——离线段自检通过、
无 key 时以 `2` 退出并点名 `WEB_SEARCH_API_KEY`、`--help` 正常；再加一条静态断言钉住凭证纪律
（取 key 的行不许同时是输出行，任何分支都不许把值打到屏幕/日志）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "web_search_smoke.py"


def _run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - 固定 argv（当前解释器 + 仓内脚本），不经 shell、无外部输入
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd or REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_self_check_passes_without_any_credential() -> None:
    """离线段（预算常量 + 注入围栏）无 key 也要全绿：否则「没有 key 就无法自检脚本」= 死循环。"""
    completed = _run("--self-check")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "③ 预算常量自检" in completed.stdout
    assert "④ 注入围栏" in completed.stdout
    assert "api_key = 未配置" in completed.stdout


def test_missing_key_exits_with_the_precondition_code(tmp_path: Path) -> None:
    """无 key 跑主流程：退出码 `2`（前提缺失，不是判据失败）+ 明确提示配置位置。"""
    env = {**os.environ, "WEB_SEARCH_API_KEY": ""}

    completed = _run(cwd=tmp_path, env=env)
    output = completed.stdout + completed.stderr

    assert completed.returncode == 2, output
    assert "WEB_SEARCH_API_KEY" in output
    assert "已配置（长度" not in output  # 没有 key 就不许报长度，避免「空 key 也算配置」的错觉


def test_help_exits_zero() -> None:
    completed = _run("--help")

    assert completed.returncode == 0
    assert "--self-check" in completed.stdout


def test_the_key_is_never_interpolated_into_an_output_line() -> None:
    """凭证纪律的静态判据：读 key 的行与输出行必须是两回事。

    真实事故形态不是「故意打印 key」，而是顺手把 `api_key` 塞进 f-string 调试输出。这条断言让那种
    改动当场红，而不是等 key 进 transcript/日志之后才发现。
    """
    source = SCRIPT.read_text(encoding="utf-8")

    offending = [
        line
        for line in source.splitlines()
        if "{api_key" in line and any(marker in line for marker in ("print(", ".note(", "logger."))
    ]
    assert offending == [], offending
    assert "settings.web_search_api_key" in source  # 取值路径存在（不是把 key 从别处捞）


def _script_module() -> object:
    """把冒烟脚本当模块导入（只为测它的纯函数解析，不触发任何网络）。"""
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import web_search_smoke  # noqa: PLC0415 - 需要先把 scripts/ 放上 sys.path
    finally:
        sys.path.remove(str(SCRIPT.parent))
    return web_search_smoke


def test_entry_parser_does_not_count_a_forged_line_inside_a_snippet() -> None:
    """摘要多行时，行首出现 `[9] …` 不得被数成第 6 条。

    这是冒烟的**假阳性**防线：真实检索结果的摘要常带换行，若按「行首 `[n] `」数行，一个正常结果
    会让 A55 的判据报 FAIL。
    """
    module = _script_module()
    text = "\n\n".join(f"[{i}] 标题{i}\n    https://e{i}.example\n    摘要{i}" for i in range(1, 6))
    text = text.replace("    摘要5", "    摘要5\n[9] 这不是条目，是摘要里的第二行")

    blocks = module._split_entries(text)

    assert len(blocks) == 5
    assert module._ENTRY_HEADER.match(blocks[4][0]).group(2) == "标题5"


def test_entry_parser_ignores_the_guard_warning_block() -> None:
    """围栏 warning 也是「空行分块」，但不是条目 ⇒ 不计入条数。"""
    module = _script_module()
    text = "⚠️ 注入提示\n\n[1] 标题\n    https://e1.example\n    摘要"

    assert len(module._split_entries(text)) == 1


def test_empty_result_is_reported_but_is_not_a_failure() -> None:
    """引擎返回 0 条不判 FAIL（文案与判据必须一致：可能真是无匹配）。"""
    module = _script_module()
    source = SCRIPT.read_text(encoding="utf-8")

    assert "不判 FAIL" in source
    assert "seg.check(bool(results)" not in source
    assert module is not None
