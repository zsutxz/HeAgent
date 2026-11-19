"""node 行为探针的共用执行器（Epic 70 评审新增）。

前端探针（`tests/fixtures/js/*_probe.js`）的调用约定一致：把真实资源写到临时目录，用 node 执行
探针脚本，读回一行 `PROBE_RESULT {json}`。三个用例文件（任务面板 / API 探索器 / 服务身份）共用
本模块，避免各写一份 subprocess 样板。

没有 node 的环境（本仓开发容器实测 `shutil.which("node")` 为 `None`）由调用方
`@pytest.mark.skipif(NODE is None, ...)` 跳过；CI 镜像自带 node，探针在那里生效。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from heagent.network.http_server import read_web_asset

PROBE_DIR = Path(__file__).parent / "fixtures" / "js"
NODE: str | None = shutil.which("node")

_MARKER = "PROBE_RESULT "


def _run(probe: str, args: list[str]) -> dict[str, Any]:
    assert NODE is not None, "没有 node：调用方应当 skip"
    completed = subprocess.run(  # noqa: S603 - 固定 argv（node + 仓库内探针脚本 + 临时路径），不经 shell
        [NODE, str(PROBE_DIR / probe), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    line = next((item for item in completed.stdout.splitlines() if item.startswith(_MARKER)), None)
    assert line is not None, completed.stdout
    return json.loads(line[len(_MARKER) :])


def run_app_probe(case: str, tmp_path: Path) -> dict[str, Any]:
    """执行 `app_probe.js` 的用例（加载真实 `app.js`，断言落在可观察结果上）。"""
    for name in ("app.js", "index.html"):
        (tmp_path / name).write_bytes(read_web_asset(name))
    return _run("app_probe.js", [str(tmp_path / "app.js"), str(tmp_path / "index.html"), case])


def run_panels_probe(case: str, tmp_path: Path) -> dict[str, Any]:
    """执行 `panels_probe.js` 的用例（加载真实 `panels.js` + 目标面板脚本）。"""
    for name in ("tasks.js", "api-console.js", "panels.js", "index.html"):
        (tmp_path / name).write_bytes(read_web_asset(name))
    return _run(
        "panels_probe.js",
        [
            str(tmp_path / "tasks.js"),
            str(tmp_path / "api-console.js"),
            str(tmp_path / "panels.js"),
            str(tmp_path / "index.html"),
            case,
        ],
    )
