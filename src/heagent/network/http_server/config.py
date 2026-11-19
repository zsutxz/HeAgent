"""HTTP 服务实例的有界配置与启动失败异常（Story 62.1 自 ``network/http_server.py`` 拆出）。

层序最底层：只依赖 Pydantic 与 ``http_protocol`` 的请求上限常量，被包内其余全部模块依赖。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from heagent.network.exposure import is_loopback_host
from heagent.network.http_protocol import MAX_REQUEST_BYTES_FOR_MAX_PROMPT

__all__ = ["HttpServerConfig", "HttpStartupError"]


class HttpStartupError(RuntimeError):
    """HTTP 服务未能绑定或未通过就绪探测。"""


class HttpServerConfig(BaseModel):
    """单个 HTTP 服务实例的有界配置（默认值与 ``HTTP_*`` 设置、``docs/frame.md`` 4.17 一致）。

    ``port=0`` 允许（操作系统分配随机端口），仅用于程序化/测试用法——CLI 与设置层限定 1..65535。
    所有超时都禁 ``inf``/``nan``：``Inf`` 会让「有界关闭」静默变成无界等待。
    """

    model_config = ConfigDict(frozen=True)

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=9101, ge=0, le=65535)
    max_connections: int = Field(default=16, ge=1)
    # 每个 run 的 **SSE 订阅者**上限：从 ``max_connections`` 拆出（默认值相同 ⇒ 默认行为不变）。
    # 拆出的理由：连接额度由 Uvicorn 在**进 ASGI 之前**拒绝 ⇒ 超额订阅拿不到错误信封 / 安全头 / 访问日志，
    # 429 ``rate_limited`` 分支实际不可达；订阅面现在有独立旋钮，调大连接额度不再被迫放大它。
    max_subscribers: int = Field(default=16, ge=1)
    # **每个项目各自**的在途运行上限：全局上限 = 项目数 × 该值，因此「A 项目在跑」
    # 不挡 B 项目；``POST /api/runs``（无项目归属）自己算一档，语义保持不变。
    max_inflight_runs: int = Field(default=1, ge=1)
    # **服务级**在途运行总额（跨项目共享）：``0`` = 不限（默认 ⇒「并发随项目数线性」语义逐字
    # 不变）。设 N > 0 后所有项目加总不得超过 N；它与 ``max_inflight_runs`` **同时**生效，先撞谁按谁
    # 拒（总额这一路回 ``total_inflight_limit``，见 :class:`HttpRunConflictError`）。
    max_total_inflight: int = Field(default=0, ge=0)
    max_request_bytes: int = Field(default=MAX_REQUEST_BYTES_FOR_MAX_PROMPT, ge=1)
    event_buffer_size: int = Field(default=512, ge=1)
    run_history_size: int = Field(default=64, ge=1)
    # 单次运行的**总时长**硬上限（秒）：0 = 不限制（默认）。它只该是运维显式设的兜底闸门——
    # 「跑得久」不等于「卡死」，把墙钟上限当默认会在长任务（多轮工具 / 子代理 / goal 工作流）上
    # 误杀，而卡死判定是 idle_timeout 的职责。
    request_timeout: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    # 单次运行的**静默**上限（秒）：既没有新事件、也没有在途工具时才开始计时，到点按 ``timed_out``
    # 终结（0 = 关闭静默判定）。在途工具（``tool_call`` 已发、``tool_result`` 未到）算「有进展」：
    # 一次长的 shell / 子代理调用期间没有事件，但它显然没有卡死。
    idle_timeout: float = Field(default=300.0, ge=0, allow_inf_nan=False)
    # 单个在途工具的最长在途时间（秒）：超过即按「工具卡死」终结（阈值独立于 idle_timeout）。
    # 默认 1 小时——远高于任何真实工具调用，但让「永不返回的工具」不再无界占住在途名额。
    tool_inflight_timeout: float = Field(default=3600.0, ge=0, allow_inf_nan=False)
    shutdown_timeout: float = Field(default=5.0, gt=0, allow_inf_nan=False)

    @property
    def mode(self) -> str:
        """``"local"``（回环绑定）或 ``"external"``（非回环绑定）。

        与 :attr:`~heagent.network.ws_host.WsServerConfig.mode` 同义、同判定函数
        （:func:`~heagent.network.exposure.is_loopback_host`）：两处各写一套「算不算本地」，漏报
        暴露的那天就会得出两个结论。
        """
        return "local" if is_loopback_host(self.host) else "external"
