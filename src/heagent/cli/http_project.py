"""HTTP 入口的项目面装配：控制台实例与 WS 项目通道服务的唯一构造点（自 ``cli/http.py`` 拆出）。

``cli/http.py`` 的两条入口（内嵌服务 / ``http-server`` 命令）与 ``_http_listener_for`` 都从这里取
**同一个** ``HttpProjectConsole``——写闸门、注册表、项目运行时缓存都挂在实例上，两个面必须拿到
同一个对象，构造散成两处会出现「HTTP 侧可写、WS 侧按旧的启动配置跑」这类不可见的双份状态。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from heagent.cli.http_console import HttpProjectConsole
from heagent.cli.ws_project_adapter import ProjectChannelAdapter

if TYPE_CHECKING:
    from heagent.config import Settings
    from heagent.network.http_server import HttpRunService
    from heagent.pub.workspace import WorkspacePaths


def _project_env_declares(env_key: str) -> bool:
    """项目 ``.env`` 是否声明了该键（用于「写错位置」的显式告警，不作为取值路径）。

    只做行级文本匹配：值本身**不读**（读了也不能用——凭证只认用户级 ``setting.md``）。
    """
    path = Path(".env")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    pattern = re.compile(rf"^\s*{re.escape(env_key)}\s*=", re.IGNORECASE | re.MULTILINE)
    return pattern.search(text) is not None


def _project_console(
    *,
    settings: Settings,
    workspace: WorkspacePaths,
    run_service: HttpRunService | None,
    handler_factory: Any,
    dialog_backend: str = "none",
) -> HttpProjectConsole:
    """网页控制台实例的唯一构造点（HTTP 面与 WS 项目通道共用同一份）。

    写闸门、注册表、项目运行时缓存都挂在实例上，因此两个面必须拿到同一个对象——构造散成两处
    就会出现「HTTP 侧可写、WS 侧按旧的启动配置跑」这类不可见的双份状态。
    """
    return HttpProjectConsole(
        workspace.root,
        projects_file=settings.http_console_projects_file,
        runs=run_service,
        handler_factory=handler_factory,
        write_enabled=settings.http_console_write_enabled,
        dialog_backend=dialog_backend,
    )


def _project_channel(console: HttpProjectConsole) -> ProjectChannelAdapter:
    """WS 项目通道服务：注册表健康探针取控制台自己那份注册表（同一路径、同一缓存）。"""
    return ProjectChannelAdapter(console, lambda: console.registry.health().code)
