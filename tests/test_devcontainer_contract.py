"""开发容器（`.devcontainer/`）契约。

**为什么要有这个文件**：devcontainer 是「一键开发环境」的唯一载体（R13），但它天然不入任何
代码门禁——没人跑它，坏了也不会红，直到某个新同事 clone 下来发现装不起来。票面 verify
（「包含全部必需依赖与预配置检查工具」）因此必须落成可执行断言，而不是一次性人工核对。

四条断言各自对应一种真实漂移：

1. **extras 面**：`postCreateCommand` 装的 extras 必须真实存在于 `pyproject.toml`，且**必含**
   `dev` / `gui` / `http` —— 缺 `gui` 或 `http` 时 `mypy src` 会在 textual / starlette 上报
   import-not-found（CI 的 lint job 就是为此三个都装）。
2. **检查工具就位**：`pre-commit install` 必须在 postCreate 里（否则钩子不生效，提交前门禁形同不存在）。
3. **端口面**：`forwardPorts` 必须与 `Settings` 的三条 listener 默认端口一致——改默认端口而忘了
   容器转发，症状是「容器里服务起得来、宿主机浏览器连不上」，排查成本极高而原因极廉价。
4. **Python 次版本**：Dockerfile 基础镜像的 X.Y 必须等于 `pyproject.toml` 的
   `requires-python` 下界——镜像比声明低一个次版本时，语法糖/标准库 API 会在容器里炸而在本机不炸。
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from heagent.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVCONTAINER_DIR = REPO_ROOT / ".devcontainer"
DEVCONTAINER_JSON = DEVCONTAINER_DIR / "devcontainer.json"
DOCKERFILE = DEVCONTAINER_DIR / "Dockerfile"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _devcontainer() -> dict:
    return json.loads(DEVCONTAINER_JSON.read_text(encoding="utf-8"))


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_devcontainer_build_points_at_a_real_dockerfile() -> None:
    """`build.dockerfile` 指向的文件必须存在（相对 `.devcontainer/`）。"""
    build = _devcontainer().get("build", {})
    dockerfile = build.get("dockerfile")
    assert dockerfile, "devcontainer.json has no build.dockerfile"
    resolved = (DEVCONTAINER_DIR / dockerfile).resolve()
    assert resolved.is_file(), f"devcontainer build.dockerfile does not exist: {resolved}"


def test_post_create_installs_declared_extras_and_hooks() -> None:
    """postCreateCommand 装的 extras 必须真实存在，且含 mypy 需要的 dev/gui/http。"""
    command = _devcontainer().get("postCreateCommand", "")
    assert isinstance(command, str) and command, "devcontainer.json has no postCreateCommand"

    match = re.search(r"pip install -e \"\.\[([^\]]+)\]\",?", command)
    assert match is not None, f"postCreateCommand does not install the project editable: {command!r}"
    extras = {name.strip() for name in match.group(1).split(",") if name.strip()}

    declared = set(_pyproject()["project"]["optional-dependencies"])
    unknown = extras - declared
    assert not unknown, f"postCreateCommand requests extras that pyproject.toml does not declare: {sorted(unknown)}"
    missing = {"dev", "gui", "http"} - extras
    assert not missing, f"postCreateCommand must install {sorted(missing)} (mypy needs gui/http stubs)"

    assert "pre-commit install" in command, "postCreateCommand must run `pre-commit install`"


def test_forwarded_ports_match_listener_defaults() -> None:
    """转发端口必须跟随 `Settings` 的 listener 默认端口（改默认值须同步 devcontainer）。"""
    settings = Settings()
    expected = {settings.http_port, settings.ws_port}
    forwarded = set(_devcontainer().get("forwardPorts", []))
    assert forwarded == expected, (
        "devcontainer forwardPorts drifted from Settings listener defaults: "
        f"forwardPorts={sorted(forwarded)}, Settings={sorted(expected)}"
    )


def test_base_image_python_matches_requires_python() -> None:
    """基础镜像的 Python X.Y 必须等于 `requires-python` 下界（当前 >=3.11）。"""
    requires = _pyproject()["project"]["requires-python"]
    lower = re.search(r">=\s*(\d+\.\d+)", requires)
    assert lower is not None, f"unparsable requires-python: {requires}"
    from_match = re.search(
        r"^FROM\s+mcr\.microsoft\.com/devcontainers/python:[^\s]*?(\d+\.\d+)",
        DOCKERFILE.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    assert from_match is not None, "Dockerfile does not use the devcontainers/python base image"
    assert from_match.group(1) == lower.group(1), (
        f"base image python {from_match.group(1)} != requires-python lower bound {lower.group(1)}"
    )
