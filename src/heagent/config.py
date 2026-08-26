"""HeAgent 配置管理 — 基于 pydantic-settings 的统一配置。

加载优先级（高 → 低）：
1. 系统环境变量（``os.environ``）
2. 项目本地 ``.env`` 文件（当前工作目录）
3. 用户全局 ``~/.heagent/.env``
4. 字段默认值

通过 get_settings() 获取单例，reset_settings() 用于测试重置。
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_settings: Settings | None = None  # 单例缓存

GLOBAL_CONFIG_DIR: Path = Path.home() / ".heagent"
GLOBAL_CONFIG_FILE: Path = GLOBAL_CONFIG_DIR / ".env"


def _parse_comma_list(v: str) -> list[str]:
    """将逗号分隔的字符串解析为列表（用于多 Key 池配置）。"""
    if not v:
        return []
    return [k.strip() for k in v.split(",") if k.strip()]


class Settings(BaseSettings):
    """全局配置，字段名与 .env / 环境变量名一一对应。

    加载优先级：系统环境变量 > 项目 ``.env`` > 用户全局 ``~/.heagent/.env`` > 字段默认值。
    遵循 pydantic-settings 标准顺序，用户可通过命令行环境变量临时覆盖 .env 中的值。
    """

    model_config = SettingsConfigDict(
        # 优先加载全局配置，然后用项目 .env 覆盖；
        # pydantic-settings 对序列按顺加载，后面的文件覆盖前面的重复 key。
        env_file=[str(GLOBAL_CONFIG_FILE), ".env"],
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略 .env 中未声明的变量
    )

    # ---- 活跃 Provider（交互模式启动时默认使用哪个） ----
    active_provider: str | None = None  # 启动时默认 provider，如 deepseek / kimi / openai / anthropic

    # ---- API 密钥（可选，在 Provider 使用时校验） ----
    deepseek_api_key: str | None = None  # DeepSeek API Key
    openai_api_key: str | None = None  # OpenAI API Key
    anthropic_api_key: str | None = None  # Anthropic API Key
    kimi_api_key: str | None = None  # Kimi (Moonshot AI) API Key

    # ---- API 基础 URL（用于 OpenAI 兼容的第三方服务） ----
    deepseek_base_url: str | None = None  # DeepSeek 默认 https://api.deepseek.com/v1
    openai_base_url: str | None = None  # OpenAI 兼容服务（如智谱 AI）
    anthropic_base_url: str | None = None  # Anthropic 代理地址
    kimi_base_url: str | None = None  # Kimi 默认 https://api.moonshot.cn/v1

    # ---- 各 Provider 默认模型（--model CLI 参数可覆盖） ----
    default_model: str = "gpt-4o"  # OpenAI 默认模型名称
    deepseek_model: str = "deepseek-v4-pro"  # DeepSeek 默认模型
    kimi_model: str = "moonshot-v1-8k"  # Kimi (Moonshot) 默认模型

    # ---- Anthropic 提示词缓存（FR-3） ----
    anthropic_prompt_caching: bool = True

    # ---- 多密钥池（逗号分隔存储，运行时解析为列表） ----
    openai_api_keys: str = ""
    anthropic_api_keys: str = ""

    # ---- 智能路由参数（Provider 智能路由：按任务特征在 flash/pro 模型间自动切换） ----
    # True 时 CLI 将 DeepSeek 条目构建为 RoutingProvider（flash=快速 / pro=深度，按问题难度
    # 自动切换），并照常放入多 provider 池——不影响 Multiple providers Choose。
    routing_enabled: bool = Field(default=False)
    # 快速模型（flash 类比）与深度模型（pro 类比）的模型名。
    routing_fast_model: str = Field(default="deepseek-v4-flash")
    routing_pro_model: str = Field(default="deepseek-v4-pro")
    # 追加到内置推理关键词表的自定义词（逗号分隔；命中即路由到 pro）。
    routing_reasoning_keywords: str = Field(default="")

    # ---- 框架运行参数 ----
    max_iterations: int = Field(default=50, ge=1)
    compression_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    # 上下文管理策略："compressor"=原地摘要压缩（默认）；"reset"=窗口重置（清窗后 resume 续跑，D3 互斥）。
    context_strategy: str = Field(default="compressor")
    # 窗口重置触发阈值（context_strategy=reset 时生效）。
    window_reset_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    # 默认上下文窗口 512k：与 .env.example 文档一致。注意 window_reset/compressor
    # 的触发阈值 = threshold % of window，窗口越大触发越晚（0.8 × 512k ≈ 410k）；
    # 须确认所用模型实际上下文 ≥512k，否则压缩触发前就会先撞上 API 上限报 400。
    # （历史：574c2d9 曾把默认改为 1M，导致这两套机制在默认配置下几乎永不触发。）
    max_context_tokens: int = Field(default=512000, ge=1)
    shell_timeout: int = Field(default=120, ge=1)

    # ---- 日志参数 ----
    log_dir: str = Field(default="logs")  # 日志文件目录，每次启动创建新文件
    log_level: str = Field(default="INFO")  # 控制台(stderr)日志级别: DEBUG / INFO / WARNING / ERROR
    log_file_level: str | None = Field(default=None)  # 文件日志级别; None=回退到 log_level

    # ---- 重试策略参数 ----
    retry_max_attempts: int = Field(default=3, ge=1)
    retry_base_delay: float = Field(default=1.0, ge=0.0)
    retry_max_delay: float = Field(default=30.0, ge=0.0)

    # ---- 技能系统参数 ----
    skill_match_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    skill_max_auto_invoke: int = Field(default=3, ge=0)

    # ---- 上下文文件参数 ----
    context_files_enabled: bool = Field(default=True)

    # ---- 记忆提醒参数 ----
    memory_nudge_enabled: bool = Field(default=True)

    # ---- 技能策展参数 ----
    skill_curator_stale_days: int = Field(default=30, ge=1)

    # ---- Cron 调度参数 ----
    cron_enabled: bool = Field(default=True)
    cron_tick_seconds: int = Field(default=60, ge=10)

    # ---- Dreaming（离线记忆巩固）参数 ----
    # dream_enabled 默认 False：dreaming = 无人监督后台跑 + 联网 + 改持久记忆，opt-in。
    # 非安全边界（PolicyEngine/role/web 围栏均非真边界，须 OS 级沙箱兜底）。
    dream_enabled: bool = Field(default=False)
    dream_cron: str = Field(default="0 3 * * *")  # cron 触发表达式（凌晨 3 点低峰）
    dream_idle_minutes: int = Field(default=30, ge=0)  # idle 触发阈值（分钟）；0 = 禁用 idle 触发
    dream_max_iterations: int = Field(default=20, ge=1)  # dreamer SubAgent 独立预算（不复用全局）
    dream_session_lookback: int = Field(default=5, ge=1)  # 预加载近期 session 个数

    # ---- Ledger 自动清理参数 ----
    # ledger 幂等记录（.heagent/ledger/）超过此天数在 run 启动时自动删除；0=禁用清理。
    ledger_retention_days: int = Field(default=7, ge=0)

    # ---- MCP Client 参数 ----
    mcp_enabled: bool = Field(default=True)
    mcp_config_path: str = Field(default=".mcp.json")
    safety_blocked_tools: list[str] = Field(default_factory=list)

    # ---- 沙箱后端（FR-S4） ----
    # "passthrough" = 零隔离（默认），"firejail" = FirejailBackend。
    # CLI --sandbox flag 可覆盖；firejail 不可用时自动降级 Passthrough。
    sandbox_backend: str = Field(default="passthrough")
    # firejail 可执行文件路径（PATH 查找或绝对路径）。
    sandbox_firejail_path: str = Field(default="firejail")
    # 沙箱会话目录开关（FR-1）：True 时每个 run 经 EngineContainer.create_run_context
    # 在 `<cwd>/.heagent/sandboxes/<run_id>/` 幂等创建 per-run workspace，并经
    # RunContext.metadata["sandbox_workspace"] 送达后端（Firejail 作 --private 根、
    # WinJob 作子进程 cwd——目录约定，无文件系统隔离）。默认 False：行为与现状一致。
    sandbox_session_workspace: bool = Field(default=False)
    # 沙箱 env 豁免 allowlist（FR-3）：逗号分隔的环境变量名（如 "GITHUB_TOKEN,CUSTOM_SECRET"）。
    # 命中 allowlist 的变量不参与 scrub_sensitive_env 的敏感剥离。空 = 全剥离（现状）。
    sandbox_env_allowlist: str = Field(default="")

    # ---- 审批参数（Epic 29） ----
    # 逗号分隔的需要交互审批的工具名（如 "shell,file_write"）。空 = 无审批工具。
    approval_tools: str = Field(default="")

    # ---- 用户事件钩子（Epic 32） ----
    # false = 不加载 .heagent/hooks.json。hooks 是用户自配置的本地命令（非安全边界），
    # 不可信仓库可投放该文件自动执行——故须显式开启（防供给链式自动执行）。
    hooks_enabled: bool = Field(default=False)

    # ---- Plan Mode（Epic 33） ----
    # True 时收敛为只读模式：仅允许 readOnlyHint=True 的内置工具，禁止写操作（CLI --plan 覆盖）。
    plan_mode: bool = Field(default=False)

    # ---- 成本估算（Epic 34） ----
    # 模型价格表 JSON：{"<model>": {"input": <$/M tok>, "output": <$/M tok>}}；空 = 不显示成本。
    model_pricing: str = Field(default="")

    @property
    def openai_key_pool(self) -> list[str]:
        return _parse_comma_list(self.openai_api_keys)

    @property
    def anthropic_key_pool(self) -> list[str]:
        return _parse_comma_list(self.anthropic_api_keys)

    @property
    def approval_tool_list(self) -> list[str]:
        return _parse_comma_list(self.approval_tools)

    @property
    def sandbox_env_allowlist_set(self) -> frozenset[str]:
        """沙箱 env 豁免 allowlist 的大小写不敏感集合（供 scrub_sensitive_env 匹配）。"""
        return frozenset(name.upper() for name in _parse_comma_list(self.sandbox_env_allowlist))

    @property
    def routing_keyword_list(self) -> list[str]:
        return _parse_comma_list(self.routing_reasoning_keywords)

    @property
    def model_pricing_map(self) -> dict[str, dict[str, float]]:
        """解析模型价格表 JSON；无效 JSON 返回空 dict（不崩溃、不显示成本）。"""
        if not self.model_pricing:
            return {}
        try:
            data = json.loads(self.model_pricing)
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        result: dict[str, dict[str, float]] = {}
        for model, prices in data.items():
            if isinstance(prices, dict):
                result[model] = {
                    "input": float(prices.get("input", 0.0)),
                    "output": float(prices.get("output", 0.0)),
                }
        return result


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
