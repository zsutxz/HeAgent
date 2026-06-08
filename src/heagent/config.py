"""HeAgent 配置管理 — 基于 pydantic-settings 的统一配置。

从 .env 文件和系统环境变量加载配置。
通过 get_settings() 获取单例，reset_settings() 用于测试重置。
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_settings: Settings | None = None  # 单例缓存


def _parse_comma_list(v: str) -> list[str]:
    """将逗号分隔的字符串解析为列表（用于多 Key 池配置）。"""
    if not v:
        return []
    return [k.strip() for k in v.split(",") if k.strip()]


class Settings(BaseSettings):
    """全局配置，字段名与 .env / 环境变量名一一对应。

    加载优先级：系统环境变量 > .env 文件 > 字段默认值。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略 .env 中未声明的变量
    )

    # ---- API 密钥（可选，在 Provider 使用时校验） ----
    deepseek_api_key: str | None = None    # DeepSeek API Key（优先检测）
    openai_api_key: str | None = None      # OpenAI API Key
    anthropic_api_key: str | None = None   # Anthropic API Key

    # ---- API 基础 URL（用于 OpenAI 兼容的第三方服务） ----
    deepseek_base_url: str | None = None   # DeepSeek 默认 https://api.deepseek.com/v1
    openai_base_url: str | None = None     # OpenAI 兼容服务（如智谱 AI）
    anthropic_base_url: str | None = None  # Anthropic 代理地址

    # ---- 多密钥池（逗号分隔存储，运行时解析为列表） ----
    openai_api_keys: str = ""
    anthropic_api_keys: str = ""

    # ---- 框架运行参数 ----
    default_model: str = "gpt-4o"                    # 默认模型名称
    max_iterations: int = Field(default=50, ge=1)     # Agent 循环最大迭代次数
    compression_threshold: float = Field(default=0.8, ge=0.0, le=1.0)  # 上下文压缩触发阈值
    max_context_tokens: int = Field(default=128000, ge=1)  # 模型上下文窗口大小（用于压缩判断）
    shell_timeout: int = Field(default=120, ge=1)     # Shell 命令超时时间（秒）

    # ---- 重试策略参数 ----
    retry_max_attempts: int = Field(default=3, ge=1)   # 最大重试次数
    retry_base_delay: float = Field(default=1.0, ge=0.0)  # 重试基础延迟（秒）
    retry_max_delay: float = Field(default=30.0, ge=0.0)  # 重试最大延迟（秒）

    # ---- 技能系统参数 ----
    skill_match_threshold: float = Field(default=0.3, ge=0.0, le=1.0)  # 自动调用关键词匹配阈值
    skill_max_auto_invoke: int = Field(default=3, ge=0)                # 每轮最多自动注入技能数

    # ---- 上下文文件参数 ----
    context_files_enabled: bool = Field(default=True)                   # 是否自动加载项目上下文文件

    # ---- 记忆提醒参数 ----
    memory_nudge_enabled: bool = Field(default=True)                    # 是否注入记忆保存提醒

    # ---- 技能策展参数 ----
    skill_curator_stale_days: int = Field(default=30, ge=1)            # 多少天未使用视为过期

    # ---- Cron 调度参数 ----
    cron_enabled: bool = Field(default=True)                            # 是否启用 cron 调度
    cron_tick_seconds: int = Field(default=60, ge=10)                   # 调度器检查间隔（秒）

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
