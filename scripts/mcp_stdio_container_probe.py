"""MCP stdio 进容器的整链探针（Story 53-5 的真链路取证，两种模式）。

- ``--mode fake``：生成一个**替身 docker CLI**（应答 ``docker version`` 让可用性闸通过，``run``
  时解析旗标后 ``exec`` 镜像之后的命令，并把自己收到的 argv 落到 ``.heagent/tmp/mcp-probe/fake-docker-ran.json``），
  用它跑完整链：``stdio_client`` → 我们拼的 argv → 真 MCP stdio server → 真 JSON-RPC 握手 →
  ``tools/list`` → ``tools/call``。证明「argv 拼接正确 + 双向管道通 + env 只透传声明键」，
  **不**证明容器隔离（替身不建容器）。
- ``--mode docker``：真 daemon（须在**宿主**跑；容器沙箱里没有 docker CLI / socket）。
  额外断言工具自报的 ``in_container`` 为真（容器内 ``/.dockerenv`` 存在）且 cwd 为 ``/workspace``。

用法::

    python scripts/mcp_stdio_container_probe.py --mode fake     # 任何环境（含容器沙箱）
    python scripts/mcp_stdio_container_probe.py --mode docker   # 宿主 + daemon 可用

退出码：0 = 全部断言通过；1 = 有断言失败。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from heagent.tools.mcp.client import default_transport_opener  # noqa: E402
from heagent.tools.mcp.config import StdioServerConfig  # noqa: E402
from heagent.tools.mcp.session_api import call_tool, list_tools  # noqa: E402
from heagent.tools.mcp.stdio_sandbox import StdioSandboxSpec  # noqa: E402

TMP = ROOT / ".heagent/tmp/mcp-probe"
SERVER = TMP / "probe_server.py"
FAKE_BIN = TMP / "bin"
FAKE_DOCKER = FAKE_BIN / "docker"
FAKE_MARKER = TMP / "fake-docker-ran.json"
MARKER_ENV = "HEAGENT_MCP_PROBE_TOKEN"
MARKER_VALUE = "s3cr3t-value"

# 最小 MCP stdio server：换行分隔 JSON-RPC（stdlib only，镜像里无需 mcp 包）。
SERVER_SRC = '''\
"""最小 MCP stdio server（探针用，stdlib only）：initialize / tools/list / tools/call。"""

import json
import os
import socket
import sys


def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()


for raw in sys.stdin:
    line = raw.strip()
    if not line:
        continue
    msg = json.loads(line)
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        send(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": msg["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "probe", "version": "0.1"},
                },
            }
        )
    elif method == "tools/list":
        send(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "tools": [
                        {
                            "name": "whereami",
                            "description": "report runtime facts",
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ]
                },
            }
        )
    elif method == "tools/call":
        payload = {
            "in_container": os.path.exists("/.dockerenv"),
            "hostname": socket.gethostname(),
            "cwd": os.getcwd(),
            "env_token": os.environ.get("HEAGENT_MCP_PROBE_TOKEN", "<unset>"),
        }
        send(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False},
            }
        )
    elif mid is not None:
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
'''

# 替身 docker CLI：`version` 应答让可用性闸通过；`run` 解析旗标后 exec 镜像之后的命令。
FAKE_DOCKER_SRC = '''\
#!/usr/bin/env python3
"""替身 docker CLI（探针用）：version 应答 + run 旗标解析 + exec 镜像后的命令。"""

import json
import os
import sys
from pathlib import Path

MARKER = Path(__file__).resolve().parent.parent / "fake-docker-ran.json"
VALUE_FLAGS = {
    "--name",
    "--network",
    "--security-opt",
    "--user",
    "--label",
    "-e",
    "-v",
    "-w",
    "--memory",
    "--pids-limit",
    "--pull",
}

argv = sys.argv[1:]
if argv[:1] == ["version"]:
    print("24.0.0-probe")
    raise SystemExit(0)
if argv[:1] != ["run"]:
    sys.stderr.write("fake docker: only 'version' / 'run' supported\\n")
    raise SystemExit(2)

index = 1
env_names, binds, workdir = [], [], None
while index < len(argv):
    item = argv[index]
    if not item.startswith("-"):
        break  # 到镜像名
    if item in VALUE_FLAGS:
        value = argv[index + 1]
        if item == "-e":
            env_names.append(value)
        elif item == "-v":
            binds.append(value)
        elif item == "-w":
            workdir = value
        index += 2
        continue
    index += 1  # 布尔旗标 / --flag=value

image, command = argv[index], argv[index + 1 :]
MARKER.write_text(json.dumps({"image": image, "command": command, "env_names": env_names, "workdir": workdir}, ensure_ascii=False))
if image != "PROBE_IMAGE" or not command:
    sys.stderr.write(f"fake docker: unexpected image={image!r} command={command!r}\\n")
    raise SystemExit(3)

# 等价 `-w`：优先用 workdir（容器侧路径不存在时退回 bind 源的宿主路径），再退回当前目录。
target = None
if workdir and os.path.isdir(workdir):
    target = workdir
elif binds:
    source = binds[0].rsplit(":", 1)[0]
    if os.path.isdir(source):
        target = source
if target:
    os.chdir(target)
# 只保留声明的 env（等价 `docker run -e KEY` 从 CLI 进程 env 取值），其它一律不传；
# PATH 由替身自补（真实容器里 PATH 来自镜像，替身没有镜像层可继承）。
child_env = {key: os.environ[key] for key in env_names if key in os.environ}
child_env.setdefault("PATH", os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"))
os.execvpe(command[0], command, child_env)
'''


def _prepare(mode: str) -> StdioSandboxSpec:
    TMP.mkdir(parents=True, exist_ok=True)
    SERVER.write_text(SERVER_SRC, encoding="utf-8")
    if FAKE_MARKER.exists():
        FAKE_MARKER.unlink()
    if mode == "fake":
        FAKE_BIN.mkdir(parents=True, exist_ok=True)
        FAKE_DOCKER.write_text(FAKE_DOCKER_SRC, encoding="utf-8")
        FAKE_DOCKER.chmod(FAKE_DOCKER.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return StdioSandboxSpec(
            image="PROBE_IMAGE",
            docker_path=str(FAKE_DOCKER),
            workspace=str(ROOT),
            user=os.environ.get("USER", "sandbox"),
        )
    image = os.environ.get("HEAGENT_PROBE_IMAGE", "heagent-sandbox:3.11")
    return StdioSandboxSpec(image=image, workspace=str(ROOT))


def _server_path(mode: str) -> str:
    if mode == "fake":
        return str(SERVER)
    # 容器内路径必须 POSIX 形态：Windows 上 Path.__str__ 给反斜杠，容器(Linux)会当成单文件名
    return (Path("/workspace") / SERVER.relative_to(ROOT)).as_posix()


async def _run(mode: str, spec: StdioSandboxSpec) -> tuple[list[str], dict[str, object]]:
    failures: list[str] = []
    cfg = StdioServerConfig(command="python", args=[_server_path(mode)], env={MARKER_ENV: MARKER_VALUE})
    os.environ[MARKER_ENV] = MARKER_VALUE

    async with default_transport_opener(cfg, stdio_sandbox=spec) as session:
        tools = await list_tools(session)
        names = [tool.name for tool in tools]
        print(f"[probe] tools/list -> {names}")
        if names != ["whereami"]:
            failures.append(f"tools/list 期望 ['whereami']，实际 {names}")
        result = await call_tool(session, "whereami", {})
        facts = json.loads(result.content[0].text)  # type: ignore[union-attr]
        print(f"[probe] tools/call -> {facts}")

    if facts["env_token"] != MARKER_VALUE:
        failures.append(f"env 透传失败：server 未收到 {MARKER_ENV}（实际 {facts['env_token']!r}）")
    if mode == "docker":
        if not facts["in_container"]:
            failures.append("真 daemon 模式却不在容器内（/.dockerenv 不存在）")
        if facts["cwd"] != "/workspace":
            failures.append(f"容器内 cwd 应为 /workspace，实际 {facts['cwd']}")
    else:
        if not FAKE_MARKER.exists():
            failures.append("替身 docker CLI 未被调用（argv 从未经过 docker run）")
        else:
            marker = json.loads(FAKE_MARKER.read_text(encoding="utf-8"))
            print(f"[probe] fake docker argv -> {marker}")
            if marker["image"] != "PROBE_IMAGE":
                failures.append(f"镜像名位置错误：{marker['image']!r}")
            if marker["command"] != ["python", _server_path("fake")]:
                failures.append(f"镜像后的命令错误：{marker['command']!r}")
            if marker["env_names"] != [MARKER_ENV]:
                failures.append(f"env 透传清单错误：{marker['env_names']!r}")
            if marker["workdir"] != "/workspace":
                failures.append(f"-w 值错误：{marker['workdir']!r}")
    return failures, facts


async def _run_degradation() -> list[str]:
    """显性降级：docker CLI 不存在 ⇒ 宿主直跑，且 docker 从未被调用。"""
    cfg = StdioServerConfig(command=sys.executable, args=[str(SERVER)], env={MARKER_ENV: "host-value"})
    os.environ[MARKER_ENV] = "host-value"
    spec = StdioSandboxSpec(image="PROBE_IMAGE", docker_path=str(FAKE_BIN / "does-not-exist"), workspace=str(ROOT))

    failures: list[str] = []
    if FAKE_MARKER.exists():
        FAKE_MARKER.unlink()  # 清掉上一轮的痕迹，本轮只要被调用就会被重新写出
    async with default_transport_opener(cfg, stdio_sandbox=spec) as session:
        result = await call_tool(session, "whereami", {})
        facts = json.loads(result.content[0].text)  # type: ignore[union-attr]
    print(f"[degrade] tools/call -> {facts}")
    if facts["env_token"] != "host-value":  # noqa: S105 - 探针的比较值，非真实凭证
        failures.append(f"降级模式 env 透传异常（实际 {facts['env_token']!r}）")
    if FAKE_MARKER.exists():
        failures.append("降级模式却调用了 docker CLI")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("fake", "docker"), default="fake")
    args = parser.parse_args()

    spec = _prepare(args.mode)
    print(f"[probe] mode={args.mode} docker_path={spec.docker_path} image={spec.image} available={spec.available()}")
    if args.mode == "fake" and not spec.available():
        print("[FAIL] 替身 CLI 的 version 应答未通过可用性闸")
        return 1

    failures, _facts = asyncio.run(_run(args.mode, spec))
    if args.mode == "fake":
        failures += asyncio.run(_run_degradation())

    if failures:
        for item in failures:
            print(f"[FAIL] {item}")
        print("VERDICT: FAIL")
        return 1
    print("VERDICT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
