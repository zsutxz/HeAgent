#!/usr/bin/env python
"""Epic 49 Story 49-6 验收：**安装 wheel** 后 HTTP 入口可用（静态资源 + API），不依赖源码目录。

做法（与 CI 的 release 验收同构，但在本机用 ``uv`` 跑）：

1. ``uv build --wheel`` 构建当前工作树的 wheel；
2. 建一个 ``--system-site-packages`` 的临时 venv（复用宿主已装的依赖），
   ``uv pip install --no-deps`` 安装该 wheel —— 于是 ``heagent`` 只来自 wheel；
3. 在**空目录**里启动 ``python -m heagent http-server --port <随机>``（cwd 不含源码）；
4. 断言：``/api/health`` 200、``/`` 返回内置页面、``/app.js`` 可下载、``POST /api/runs`` 201 且
   ``DELETE`` 能取消（运行 API 真的可用，不依赖真实 LLM）。

用法：``python scripts/accept_http_wheel.py``（需要 ``uv``；失败以非零码退出）。
"""

from __future__ import annotations

import glob
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".heagent" / "tmp" / "http-wheel-accept"
VENV = WORK / "venv"
DIST = WORK / "dist"


def _run(
    cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def main() -> int:
    uv = shutil.which("uv") or str(ROOT / ".venv" / "Scripts" / "uv.exe")
    if not Path(uv).exists() and shutil.which("uv") is None:
        print("SKIP: uv not available")
        return 0
    shutil.rmtree(WORK, ignore_errors=True)
    DIST.mkdir(parents=True)

    built = _run([uv, "build", "--wheel", "--out-dir", str(DIST)], cwd=ROOT)
    if built.returncode != 0:
        print(built.stdout, built.stderr)
        return 1
    wheel = glob.glob(str(DIST / "*.whl"))[0]
    print("wheel:", wheel)

    # 把 wheel **装进独立目录**（``--no-deps``），再用宿主解释器 + ``PYTHONPATH`` 指向它运行：
    # 于是 ``heagent`` 只来自 wheel（断言 ``__file__``），依赖复用宿主 venv——
    # 完全干净的依赖安装需要联网拉全套依赖，本机网络不稳时会让验收变成「网络测试」。
    host_python = sys.executable
    target = WORK / "installed"
    target.mkdir()
    installed = _run([host_python, "-m", "pip", "install", "--no-deps", "--quiet", "--target", str(target), wheel])
    if installed.returncode != 0:
        print(installed.stdout, installed.stderr)
        return 1

    runtime_dir = WORK / "runtime"
    runtime_dir.mkdir()
    port = _free_port()
    env = {
        **os.environ,
        "PYTHONPATH": str(target),
        "HTTP_PORT": str(port),
        "DEEPSEEK_API_KEY": "dummy-for-acceptance",
        "LOG_LEVEL": "WARNING",
    }
    location = _run([host_python, "-c", "import heagent, heagent.web; print(heagent.__file__)"], env=env).stdout.strip()
    print("heagent:", location)
    if not location.startswith(str(target)):
        print("FAIL: 验收环境里的 heagent 不是来自 wheel（被源码树污染）")
        return 1
    proc = subprocess.Popen(
        [host_python, "-m", "heagent", "http-server", "--port", str(port)],
        cwd=runtime_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        health = None
        for _ in range(120):
            try:
                health = httpx.get(f"{base}/api/health", timeout=2.0)
                break
            except Exception:
                time.sleep(0.25)
        assert health is not None and health.status_code == 200, f"health failed: {health}"
        print("health:", health.json())

        page = httpx.get(f"{base}/", timeout=5.0)
        assert page.status_code == 200 and "<title>HeAgent</title>" in page.text, page.status_code
        assert page.headers["x-content-type-options"] == "nosniff"
        print("page:", len(page.text), "chars;", page.headers["content-type"])

        script = httpx.get(f"{base}/app.js", timeout=5.0)
        assert script.status_code == 200 and "EventSource" in script.text
        print("app.js:", len(script.text), "chars")

        session = httpx.get(f"{base}/api/session", timeout=5.0)
        assert session.status_code == 200, session.status_code
        print("session:", session.json()["session_id"][:8], "...")

        created_run = httpx.post(f"{base}/api/runs", json={"prompt": "acceptance"}, timeout=5.0)
        assert created_run.status_code == 201, created_run.text
        run_id = created_run.json()["run_id"]
        cancelled = httpx.delete(f"{base}/api/runs/{run_id}", timeout=10.0)
        assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled", cancelled.text
        print("run:", run_id[:8], "->", cancelled.json()["status"])
    finally:
        proc.terminate()
        _out, err = proc.communicate(timeout=30)
        tail = [line for line in err.splitlines() if line.strip()][-3:]
        print("stderr tail:", tail)
    print("OK: wheel-installed HTTP entry serves the page and the run API")
    return 0


if __name__ == "__main__":
    sys.exit(main())
