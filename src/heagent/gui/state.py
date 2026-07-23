"""GUI 响应式全局状态 — Pydantic 模型 + Textual reactive 适配。

与项目统一的 Pydantic 类型体系一致；AgentBridge 直接写入 GuiState，
Textual reactive 自动驱动绑定的 widget 更新。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from heagent.types import TokenUsage


class GuiState(BaseModel):
    """GUI 全局状态（Pydantic 模型）。

    AgentBridge 在 stream 事件循环中更新本模型的字段；Textual widgets
    通过 ``watch_*`` 方法或 ``compose`` 中的属性绑定响应变化。
    """

    model_name: str = ""  # 当前 LLM 模型名（状态栏显示）
    iteration: int = 0  # 当前迭代轮数
    max_iterations: int = 50  # 最大迭代数（状态栏进度）
    token_usage: TokenUsage = Field(
        default_factory=lambda: TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    )
    is_running: bool = False  # Agent 是否正在执行
    active_tool: str = ""  # 当前活跃工具名（空=无）
    last_error: str | None = None  # 最近错误信息
