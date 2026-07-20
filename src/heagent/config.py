"""HeAgent 配置管理 — 基于 pydantic-settings 的统一配置。

从 .env 文件和系统环境变量加载配置。
通过 get_settings() 获取单例，reset_settings() 用于测试重置。
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

_settings: Settings | None = None  # 单例缓存


def _parse_comma_list(v: str) -> list[str]:
    """将逗号分隔的字符串解析为列表（用于多 Key 池配置）。"""
    if not v:
        return []
    return [k.strip() for k in v.split(",") if k.strip()]


class Settings(BaseSettings):
    """全局配置，字段名与 .env / 环境变量名一一对应。

    加载优先级：.env 文件 > 系统环境变量 > 字段默认值
    （同 key 冲突时 .env 胜出，系统环境变量仅作兜底，填充 .env 未声明的键；
    由下方 settings_customise_sources 反转 dotenv/env 顺序实现）。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略 .env 中未声明的变量
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """配置源优先级：.env 文件 > 系统环境变量。

        pydantic-settings 默认顺序为 init > env > dotenv（系统变量覆盖 .env）；
        此处将 dotenv 提至 env 之前，使 .env 在同 key 冲突时胜出，
        系统环境变量退居兜底，仅填充 .env 未声明的键。
        """
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)

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
    deepseek_model: str = "deepseek-chat"  # DeepSeek 默认模型
    kimi_model: str = "moonshot-v1-8k"  # Kimi (Moonshot) 默认模型

    # ---- Anthropic 提示词缓存（FR-3） ----
    # 对 system prompt 注入 cache_control 断点，降低重复输入成本。
    # 使用不支持 cache_control 的 Anthropic 代理时应关闭。
    anthropic_prompt_caching: bool = True

    # ---- 多密钥池（逗号分隔存储，运行时解析为列表） ----
    openai_api_keys: str = ""
    anthropic_api_keys: str = ""

    # ---- 框架运行参数 ----
    max_iterations: int = Field(default=50, ge=1)  # Agent 循环最大迭代次数
    compression_threshold: float = Field(default=0.8, ge=0.0, le=1.0)  # 上下文压缩触发阈值
    max_context_tokens: int = Field(default=128000, ge=1)  # 模型上下文窗口大小（用于压缩判断）
    shell_timeout: int = Field(default=120, ge=1)  # Shell 命令超时时间（秒）

    # ---- 重试策略参数 ----
    retry_max_attempts: int = Field(default=3, ge=1)  # 最大重试次数
    retry_base_delay: float = Field(default=1.0, ge=0.0)  # 重试基础延迟（秒）
    retry_max_delay: float = Field(default=30.0, ge=0.0)  # 重试最大延迟（秒）

    # ---- 技能系统参数 ----
    skill_match_threshold: float = Field(default=0.3, ge=0.0, le=1.0)  # 自动调用关键词匹配阈值
    skill_max_auto_invoke: int = Field(default=3, ge=0)  # 每轮最多自动注入技能数

    # ---- 上下文文件参数 ----
    context_files_enabled: bool = Field(default=True)  # 是否自动加载项目上下文文件

    # ---- 记忆提醒参数 ----
    memory_nudge_enabled: bool = Field(default=True)  # 是否注入记忆保存提醒

    # ---- 技能策展参数 ----
    skill_curator_stale_days: int = Field(default=30, ge=1)  # 多少天未使用视为过期

    # ---- Cron 调度参数 ----
    cron_enabled: bool = Field(default=True)  # 是否启用 cron 调度
    cron_tick_seconds: int = Field(default=60, ge=10)  # 调度器检查间隔（秒）

    # ---- MCP Client 参数（FR-7 门控；无 .mcp.json 时纯内置模式） ----
    mcp_enabled: bool = Field(default=True)  # 是否启用 MCP server 连接
    mcp_config_path: str = Field(default=".mcp.json")  # 声明式 MCP server 配置路径（项目根）
    safety_blocked_tools: list[str] = Field(default_factory=list)  # SafetyGuard 工具名黑名单（正则，对所有工具生效）

    @property
    def openai_key_pool(self) -> list[str]:
        """解析逗号分隔的 OpenAI 多密钥池。"""
        return _parse_comma_list(self.openai_api_keys)

    @property
    def anthropic_key_pool(self) -> list[str]:
        """解析逗号分隔的 Anthropic 多密钥池。"""
        return _parse_comma_list(self.anthropic_api_keys)


def get_settings() -> Settings:
    """获取配置单例。首次调用时从环境变量/.env 加载，后续返回缓存。"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """重置配置单例（主要用于测试隔离）。"""
    global _settings
    _settings = None
