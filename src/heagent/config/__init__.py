"""HeAgent 配置管理 — 基于 pydantic-settings 的统一配置。

加载优先级（高 → 低）：
1. 系统环境变量（``os.environ``）
2. 项目本地 ``.env`` 文件（当前工作目录）——``.env`` 是**项目级专用**格式
3. 用户全局 ``~/.heagent/setting.md``（YAML frontmatter，见 ``config/user_settings.py``）
4. 字段默认值

通过 get_settings() 获取单例，reset_settings() 用于测试重置。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from heagent.config.user_settings import UserMarkdownSettingsSource, read_setting_md
from heagent.pub.types import RoutingPoolSpec, RuntimeConfigSource

logger = logging.getLogger(__name__)

#: WS 对外模式 token 在用户级 ``setting.md`` 里的键名（Epic 56 D3）。
#: 它**不是** ``Settings`` 字段（见 :attr:`Settings.user_ws_auth_token` 的说明）；
#: ``config/catalog.py`` 把它计入「已知键」白名单，配置面板不会把它报成 unknown_key。
WS_AUTH_TOKEN_KEY = "ws_auth_token"  # nosec B105 - 这是键名不是凭证 # noqa: S105

# 沙箱权限档位（P0-2）的合法取值；非法配置回退 ``workspace-write``（见 Settings.sandbox_mode_resolved）。
SANDBOX_MODES: frozenset[str] = frozenset({"read-only", "workspace-write", "danger-full-access"})

_settings: Settings | None = None  # 单例缓存

GLOBAL_CONFIG_DIR: Path = Path.home() / ".heagent"
GLOBAL_SETTING_FILE: Path = GLOBAL_CONFIG_DIR / "setting.md"
#: 迁移前的旧用户级文件（一次性迁移的**锚点**；只在 ``Settings`` 类级默认路径上生效）。
LEGACY_GLOBAL_ENV_FILE: Path = GLOBAL_CONFIG_DIR / ".env"

# 路由池可绑定的 provider 条目名（与 cli._build_provider 的池内条目名一致）。
ROUTING_POOL_ENTRIES: frozenset[str] = frozenset({"deepseek", "kimi", "glm", "ollama", "openai", "claude"})


def _parse_comma_list(v: str) -> list[str]:
    """将逗号分隔的字符串解析为列表（用于多 Key 池配置）。"""
    if not v:
        return []
    return [k.strip() for k in v.split(",") if k.strip()]


class Settings(BaseSettings):
    """全局配置，字段名与 .env / 环境变量名一一对应。

    加载优先级：系统环境变量 > 项目 ``.env`` > 用户 ``~/.heagent/setting.md`` > 字段默认值。
    用户层是自定义源（:class:`UserMarkdownSettingsSource`），经 ``settings_customise_sources``
    插在 dotenv（项目 ``.env``）之后——源元组顺序即优先级，前者胜。
    """

    #: 用户层 ``setting.md`` 路径载体：ClassVar 单一查找点，测试经 ``monkeypatch.setattr(Settings, ...)``
    #: 一句全密封；逐调用注入/禁用走 ``user_settings.with_user_setting_layer`` 动态子类。
    _user_setting_file: ClassVar[Path | None] = GLOBAL_SETTING_FILE
    #: 一次性迁移的 legacy 锚点（真实 ``~/.heagent/.env``）；注入层/密封态置 ``None`` 显式禁用迁移
    #: ——绝不从目录布局猜测 legacy 位置（面板沙箱里 md 的同目录 ``.env`` 是项目配置，不能动）。
    _legacy_env_file: ClassVar[Path | None] = LEGACY_GLOBAL_ENV_FILE

    model_config = SettingsConfigDict(
        # ``.env`` 是项目级专用（用户级已迁 setting.md）；用户层走自定义源，不占 env_file。
        env_file=[".env"],
        env_file_encoding="utf-8",
        extra="ignore",  # 忽略 .env 中未声明的变量
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            UserMarkdownSettingsSource(settings_cls, setting_file=cls._user_setting_file),
            file_secret_settings,
        )

    # ---- 活跃 Provider（交互模式启动时默认使用哪个） ----
    active_provider: str | None = None  # 启动时默认 provider，如 deepseek / kimi / glm / ollama / openai / anthropic

    # ---- API 密钥（可选，在 Provider 使用时校验） ----
    deepseek_api_key: str | None = None  # DeepSeek API Key
    anthropic_api_key: str | None = None  # Anthropic API Key
    kimi_api_key: str | None = None  # Kimi (Moonshot AI) API Key
    glm_api_key: str | None = None  # GLM (智谱 AI) API Key
    openai_responses_api_key: str | None = None  # OpenAI Responses API Key（wire_api="responses" 中转站）

    # ---- API 基础 URL（用于 OpenAI 兼容的第三方服务） ----
    deepseek_base_url: str | None = None  # DeepSeek 默认 https://api.deepseek.com/v1
    anthropic_base_url: str | None = None  # Anthropic 代理地址
    kimi_base_url: str | None = None  # Kimi 默认 https://api.moonshot.cn/v1
    glm_base_url: str | None = None  # GLM 默认 https://open.bigmodel.cn/api/paas/v4
    openai_responses_base_url: str | None = None  # Responses API 中转站（如 https://www.komapi.top/v1）

    # ---- 各 Provider 默认模型（--model CLI 参数可覆盖） ----
    default_model: str = "gpt-4o"  # claude 条目的兜底模型
    deepseek_model: str = "deepseek-v4-pro"  # DeepSeek 默认模型
    kimi_model: str = "kimi-k3"  # Kimi (Moonshot) 默认模型
    glm_model: str = "glm-5.3"  # GLM (智谱) 默认模型
    openai_model: str = "gpt-5.6-terra"  # openai（Responses API）条目默认模型（env: OPENAI_MODEL）

    # ---- 本地 Ollama（OpenAI 兼容 /v1；无真实 API Key） ----
    # ollama_enabled 默认 False：本地端点属显式 opt-in——避免默认向 localhost 发请求，
    # 也避免「装了 Ollama 但没启动」时被当成可用 provider 混进回退池。
    # ollama_model 无合理默认值（Ollama 无「官方默认模型」概念），启用时必填，否则 fail-fast。
    # 注意：本地模型窗口常远小于 max_context_tokens 默认 512000（取决于 Ollama Modelfile 的
    # num_ctx），须按实际值下调，否则压缩/窗口重置阈值永不触发、先撞 API 400。
    ollama_enabled: bool = False
    ollama_base_url: str = "http://127.0.0.1:11434/v1"  # Ollama OpenAI 兼容端点
    ollama_model: str | None = None  # 必填（启用时）：如 qwen3.5-9b-local:latest
    ollama_api_key: str | None = None  # Ollama 不校验 key，留空时用占位符 "ollama"

    # ---- Anthropic 提示词缓存（FR-3） ----
    anthropic_prompt_caching: bool = True

    # ---- 多密钥池（逗号分隔存储，运行时解析为列表） ----
    anthropic_api_keys: str = ""

    # ---- 智能路由（唯一入口：ROUTING_POOLS 声明式路由池） ----
    # JSON：键 = provider 条目名（出现即启用该池，须有凭据），值含 tiers/roles/default/keywords/base_url；
    # 无效 JSON / 未知条目 → 告警并忽略该条。完整规格见 .env.example 第 4 节。
    routing_pools: str = Field(default="")

    # true = 上轮 pro 的思考痕迹仍在历史时继续走 pro；默认 false = 只按当前请求判定（单池可覆盖）。
    routing_reasoning_continuity: bool = Field(default=False)

    # ---- 框架运行参数 ----
    max_iterations: int = Field(default=50, ge=1)
    goal_max_iterations: int = Field(default=20, ge=1)
    # 子 Agent 委派最大嵌套深度（0=禁止委派；超限 task_delegate / task_parallel 返回 status=error）。
    subagent_max_depth: int = Field(default=3, ge=0)
    # 嵌套子代理兜底迭代预算（优先级：显式参数 > 角色声明 > 本项）。
    subagent_max_iterations: int = Field(default=20, ge=1)
    # 声明式 /goal 工作流的 checkpoint 策略；工作流 frontmatter 可覆盖。
    goal_checkpoint_mode: Literal["auto", "prompt"] = "prompt"
    # /goal 步骤子代理的开放问题策略：block=停 waiting_user；default=按推荐默认推进并记录假设。
    goal_open_question_mode: Literal["block", "default"] = "block"
    # /goal 工作流包 id，由 skill catalog 按 id/别名解析（默认包 .heagent/skills/he-goal/）。
    goal_workflow_skill: str = "he-goal"
    # ▶/✔ 进度公告写 stderr；与交互输入行共用终端、可能被误提交为提示词，false 静音。
    announce_progress: bool = Field(default=True)
    compression_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    # 上下文管理策略："compressor"=原地摘要压缩（默认）；"reset"=窗口重置（清窗后 resume 续跑，D3 互斥）。
    context_strategy: str = Field(default="compressor")
    # 窗口重置触发阈值（context_strategy=reset 时生效）。
    window_reset_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    # 触发阈值 = threshold % of window：窗口越大触发越晚，须确认模型实际上下文 ≥ 此值，
    # 否则压缩触发前先撞 API 400。
    max_context_tokens: int = Field(default=512000, ge=1)
    # 单次输出 token 上限（各 provider 的 max_tokens）；None = 沿用 provider 默认。本地思考模型建议设。
    max_output_tokens: int | None = Field(default=None, ge=1)
    shell_timeout: int = Field(default=120, ge=1)

    # ---- 日志参数 ----
    log_dir: str = Field(default="logs")  # 日志文件目录，每次启动创建新文件
    log_level: str = Field(default="INFO")  # 控制台(stderr)日志级别: DEBUG / INFO / WARNING / ERROR
    log_file_level: str | None = Field(default=None)  # 文件日志级别; None=回退到 log_level

    # ---- Token 计量（P0-3） ----
    # auto（默认）= 有 tiktoken 用真实 tokenizer，否则 CJK 启发式 + 真实 usage 在线校准；
    # estimate = 强制启发式；tiktoken = 强制真实（缺失告警一次后回退）。计量偏差会放大为误压缩或白丢上下文。
    tokenizer: str = Field(default="auto")

    # ---- 重试策略参数 ----
    retry_max_attempts: int = Field(default=3, ge=1)
    retry_base_delay: float = Field(default=1.0, ge=0.0)
    retry_max_delay: float = Field(default=30.0, ge=0.0)

    # ---- 技能系统参数 ----
    skill_match_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    skill_max_auto_invoke: int = Field(default=3, ge=0)
    # None 保持旧行为；设置后按完整 Skill 估算 token 限制自动注入总量。
    skill_max_auto_invoke_tokens: int | None = Field(default=None, ge=1)
    # skill_load 的完整正文读取预算；超出时显式拒绝，不截断可能含安全约束的 Markdown。
    skill_max_manual_load_tokens: int | None = Field(default=8192, ge=1)

    # ---- 上下文文件参数 ----
    context_files_enabled: bool = Field(default=True)
    # 字节总预算：超预算近端优先（越靠近 cwd 越具体），被丢弃/截断者显式标记回报。
    context_files_max_bytes: int = Field(default=32768, ge=1)
    # 是否纳入用户级 ~/.heagent/AGENTS.md；默认关——全局文件会静默影响每个项目。
    context_files_user_level: bool = Field(default=False)

    # ---- 事件传输（JSONL / rollout）----
    # 每 run 事件落盘 .heagent/runs/<run_id>/rollout.jsonl（可 replay 回放）；含工具原始输出，按需开启。
    events_rollout_enabled: bool = Field(default=False)

    # ---- 记忆提醒参数 ----
    memory_nudge_enabled: bool = Field(default=True)
    # <memory> 注入字节预算（0=不限）：MEMORY.md 为 append-only 整份注入，无预算会无界增长。
    # 超预算从尾部倒装保留最新后缀（59-3 读序翻转）并在块尾显式标注省略数；文件本体不改，整理 MEMORY.md 即释放。
    memory_inject_max_bytes: int = Field(default=98_304, ge=0)
    # MEMORY.md fact 总字节超此值启动一次归档：中间老条目移入 archive/MEMORY-archive.md；0=禁用。
    # 按字节而非天数（事实条目无时间戳，年龄靠外推会出错）；默认 = 注入预算的一半，先修剪后省略。
    memory_archive_trigger_bytes: int = Field(default=49_152, ge=0)
    # 自动归档的跨进程节流（秒）：距上次归档不足该间隔就跳过扫描（0=每次都扫）。
    memory_archive_min_interval_seconds: int = Field(default=86400, ge=0)  # 默认 1 天
    # MEMORY.md 语义压缩（fact_compact 工具）写侧开关：默认 False——无人监督下删改持久记忆
    # 须显式 opt-in（对齐 dream_enabled 立场）；关闭时工具层显性报错（fail-closed），不静默成功。
    memory_compact_enabled: bool = Field(default=False)

    # ---- 技能策展参数 ----
    skill_curator_stale_days: int = Field(default=30, ge=1)

    # ---- Cron 调度参数 ----
    cron_enabled: bool = Field(default=True)
    cron_tick_seconds: int = Field(default=60, ge=10)
    # cron 结果推送（Epic 58 D4）：两个**互相独立**的开关，默认都 False（不改变现行为）。
    # push = 建通知中枢并把 `WS /api/notifications/ws` 挂上 listener；echo = 终端 stderr 回显一行。
    # 可以只回显不推送（无 WS listener 的入口），也可以只推送不回显（无人值守）。
    cron_push_enabled: bool = Field(default=False)
    cron_echo_to_terminal: bool = Field(default=False)

    # ---- Dreaming（离线记忆巩固）参数 ----
    # 默认 False：无人监督后台跑 + 联网 + 改持久记忆，非安全边界（须 OS 级沙箱兜底），opt-in。
    dream_enabled: bool = Field(default=False)
    dream_cron: str = Field(default="0 3 * * *")  # cron 触发表达式（凌晨 3 点低峰）
    dream_idle_minutes: int = Field(default=30, ge=0)  # idle 触发阈值（分钟）；0 = 禁用 idle 触发
    dream_max_iterations: int = Field(default=20, ge=1)  # dreamer SubAgent 独立预算（不复用全局）
    dream_session_lookback: int = Field(default=5, ge=1)  # 预加载近期 session 个数

    # ---- Ledger 自动清理参数 ----
    # ledger 幂等记录（.heagent/ledger/）超过此天数在 run 启动时自动删除；0=禁用清理。
    ledger_retention_days: int = Field(default=7, ge=0)

    # ---- Run 快照自动清理参数 ----
    # .heagent/runs/ 的 run 快照超过此天数在 run 启动时自动删除；persist.py 刻意保留 .lock（规避
    # unlink 竞态），本项是 runs 侧唯一回收方。0=禁用。
    run_retention_days: int = Field(default=7, ge=0)
    # 过期清理的跨进程节流（秒）：短命 CLI 进程靠这层省掉重复扫描（0=每次都扫）。
    prune_min_interval_seconds: int = Field(default=900, ge=0)

    # 三类此前无回收方、随使用单调增长，由 CLI 启动时 housekeeping 回收；0=禁用该类清理。
    log_retention_days: int = Field(default=14, ge=0)
    # 会话文件（`.heagent/sessions/`）：老会话基本不会被 --continue 再用，保留 30 天。
    session_retention_days: int = Field(default=30, ge=0)
    # 编辑快照（`.heagent/tmp/edit-snapshots/`，「误改后悔药」，每次编辑都可能新增）。
    edit_snapshot_retention_days: int = Field(default=7, ge=0)

    # ---- MCP Client 参数 ----
    mcp_enabled: bool = Field(default=True)
    mcp_config_path: str = Field(default=".mcp.json")
    safety_blocked_tools: list[str] = Field(default_factory=list)

    # ---- 沙箱后端与权限档位（FR-S4 / P0-2） ----
    # auto（默认）= 探测 firejail 可用则用，否则 passthrough（零隔离）；winjob / docker 须显式指定
    # （WinJob 无文件系统隔离，auto 不自动选）；docker = 每命令一次性容器（OS 级强隔离兜底）。
    # CLI --sandbox 可覆盖；显式指定而不可用时降级 Passthrough 并告警。
    sandbox_backend: str = Field(default="auto")
    # read-only = 只放行只读工具（fail-closed）；workspace-write = 工作区围栏 + 凭证 deny + 审批管辖；
    # danger-full-access = 跳过围栏与 deny 预检（显式危险，仅限受控环境）。
    # 非法值经 sandbox_mode_resolved 回退 workspace-write 并告警。
    sandbox_mode: str = Field(default="workspace-write")
    # False（默认）= 禁止子进程出站（firejail --net=none / docker --network=none）；passthrough /
    # winjob 无隔离能力只记提示。宿主进程内的 web_fetch 不受此开关约束。
    sandbox_network: bool = Field(default=False)
    # True（默认）= 探测到真实沙箱后端时自动把 shell 纳入沙箱工具集并授权走沙箱路径；passthrough 下不改变行为。
    sandbox_enforce: bool = Field(default=True)
    # firejail 可执行文件路径（PATH 查找或绝对路径）。
    sandbox_firejail_path: str = Field(default="firejail")
    # docker 沙箱镜像标签（构建见 docker/sandbox/Dockerfile）；换镜像=换工具链，不改隔离语义。
    sandbox_docker_image: str = Field(default="heagent-sandbox:3.11")
    # 运行期 digest pin：非空时首 run 前 inspect 校验本地 tag 的 repo digest，不符显性拒绝（防 retag 换载荷）。
    sandbox_docker_digest: str = Field(default="")
    # True 时每 run 在 `<cwd>/.heagent/sandboxes/<run_id>/` 幂等创建 per-run workspace，经
    # RunContext.metadata["sandbox_workspace"] 送达后端（firejail --private 根 / winjob 子进程 cwd）。
    sandbox_session_workspace: bool = Field(default=False)
    # 逗号分隔的环境变量名，命中者不参与敏感剥离；空 = 全剥离。
    sandbox_env_allowlist: str = Field(default="")
    # 沙箱会话目录保留开关（FR-4）：True = run 结束后保留会话目录；False（默认）= 删除。
    sandbox_session_keep: bool = Field(default=False)
    # 崩溃 run 的孤儿会话目录由 CLI/GUI 启动时按本保留期回收（0=禁用）。
    sandbox_dir_retention_days: int = Field(default=7, ge=0)
    # profile → firejail 参数映射（JSON {"<profile名>": ["--seccomp", ...]}）：高级隔离参数由此声明，默认关闭。
    # 均为 defense-in-depth 启发式层，非真正安全边界。
    sandbox_profiles: str = Field(default="")
    # 工具 → profile 名映射（JSON {"<工具名>": "<profile名>"}），与代码内映射叠加生效；空 = 落 "default"。
    sandbox_tool_profiles: str = Field(default="")
    # 沙箱 shell 内存限额（MB，0=关闭）：firejail --rlimit-as / winjob Job Memory；触发即终止子进程、显性失败。
    sandbox_memory_limit_mb: int = Field(default=0, ge=0)
    # 沙箱 shell CPU 时间限额（秒，0=关闭）：firejail --rlimit-cpu / winjob Process Time；触发行为同上。
    sandbox_cpu_seconds: int = Field(default=0, ge=0)
    # 沙箱 shell 进程数限额（0=关闭）：firejail --rlimit-nproc / winjob ActiveProcessLimit。
    # ⚠ 语义不对称：firejail 按 Linux 真实 UID 计数（波及同用户其他进程），winjob 才是 job 作用域，故默认关。
    sandbox_nproc_limit: int = Field(default=0, ge=0)

    # ---- 审批参数（Epic 29） ----
    # 逗号分隔的需要交互审批的工具名（如 "shell,file_write"）。空 = 无审批工具。
    approval_tools: str = Field(default="")

    # ---- 用户事件钩子（Epic 32） ----
    # hooks 是用户自配置的本地命令（非安全边界），不可信仓库可投放该文件——故须显式开启。
    hooks_enabled: bool = Field(default=False)

    # ---- Plan Mode（Epic 33） ----
    # True 时收敛为只读模式：仅允许 readOnlyHint=True 的内置工具，禁止写操作（CLI --plan 覆盖）。
    plan_mode: bool = Field(default=False)

    # ---- 成本估算（Epic 34） ----
    # 模型价格表 JSON：{"<model>": {"input": <$/M tok>, "output": <$/M tok>}}；空 = 不显示成本。
    model_pricing: str = Field(default="")

    # ---- HTTP 网页入口（Epic 49 Story 49-1） ----
    # 默认 CLI 在同一进程内自动启动 HTTP 服务并把本地地址打到 stderr；`heagent http-server` 单独拉起；
    # 显式 gui / init / replay 不附带启动。定位：实验性、无认证、无 TLS，默认只绑 loopback。
    # http_enabled 只是装配开关（持久关闭用），CLI 另有单次覆盖 --no-http / --no-ws（不改 Settings 单例）。
    # 非法值由 Pydantic 显式校验失败，不静默放宽。
    http_enabled: bool = Field(default=True)  # False = 不装配 HTTP listener（仅 WS 或全关）
    http_host: str = Field(default="127.0.0.1", min_length=1)
    http_port: int = Field(default=8766, ge=1, le=65535)
    # 端口被占时自动顺延（默认 10 = 开），实际监听地址以启动时 stderr 的 [http] listening on ... 为准；
    # 显式 --port 是契约：冲突仍 fail-loud、不顺延。
    http_port_auto_find_attempts: int = Field(default=10, ge=0, le=100)
    # 客户端连接上限（超限收 503 不排队）；内部另预留 1 条给就绪探测。
    http_max_connections: int = Field(default=16, ge=1)
    # 每 run 的 SSE 订阅者上限（与连接额度分开：超额订阅回 429 rate_limited，走本入口错误信封而非裸 503）。
    http_max_subscribers: int = Field(default=16, ge=1)
    # 同时在途的网页 Agent 运行上限；MVP 固定为 1（单会话单运行），超限的提交收 run_conflict。
    http_max_inflight_runs: int = Field(default=1, ge=1)
    # 服务级在途运行总额（跨项目共享；0 = 不限），与每项目上限 http_max_inflight_runs 同时生效。
    http_max_total_inflight: int = Field(default=0, ge=0)
    # 请求体字节上限（超限收 request_too_large）；默认值必须容纳协议允许的最大 prompt——config 是底层
    # 模块不得依赖 network/，故写死数字，与 network.http_protocol 的关系由 tests 钉住。
    http_max_request_bytes: int = Field(default=394_240, ge=1)
    # 每个 run 的 SSE 事件环形缓冲条数；超出窗口的重连收 resync_required（AD-4）。
    http_event_buffer_size: int = Field(default=512, ge=1)
    # 已终结 run 记录的保留条数；淘汰后按其 id 订阅得 unknown_run（AD-4）。
    http_run_history_size: int = Field(default=64, ge=1)
    # 单次运行总时长硬上限（秒；0=不限默认）——只该是运维兜底闸门，墙钟当默认会误杀长任务。
    http_request_timeout: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    # 单次运行静默上限（秒）：无新事件且无在途工具才计时，到点按 timed_out 终结；0 = 关闭。
    http_idle_timeout: float = Field(default=300.0, ge=0, allow_inf_nan=False)
    # 单个在途工具最长在途时间（秒）；与静默阈值分开——长工具期间同样无事件，静默阈值会误杀。
    http_tool_inflight_timeout: float = Field(default=3600.0, ge=0, allow_inf_nan=False)
    # 服务关闭时「停止接收 → 终结在途 run → 关闭订阅 → 关闭 listener」全程的等待上限（秒）。
    http_shutdown_timeout: float = Field(default=5.0, gt=0, allow_inf_nan=False)

    # ---- WS 入口（Epic 56 D1：与 HTTP 完全分离的独立 server，唯一宿主所有 WS 能力） ----
    # 回环 = 本地模式（无认证，Origin 只是入口层防线）；非回环 = 对外模式（Bearer token 强制、缺 token 拒绝启动）。
    ws_enabled: bool = Field(default=True)  # False = 不装配 WS listener（仅 HTTP 或全关）
    ws_host: str = Field(default="127.0.0.1", min_length=1)
    ws_port: int = Field(default=9901, ge=1, le=65535)
    # 每 run 订阅额度 + CLI 旁路连接总额；不经 Uvicorn limit_concurrency，超额在 ASGI 层原子检查+登记。
    ws_max_connections: int = Field(default=16, ge=1)
    # WS server 关闭排空的等待上限（秒）：关既有连接 → 停 listener 全程有界。
    ws_shutdown_timeout: float = Field(default=5.0, gt=0, allow_inf_nan=False)
    # PEM 证书/私钥：两者都给才启用 wss（半配 fail-loud）；对外不配 TLS 时启动告警但不拒绝。
    ws_tls_cert_file: str | None = None
    ws_tls_key_file: str | None = None
    # ---- 期二（Epic 56 D8）：第二个 WS listener（对外），与主 listener 并存 ----
    # 空 = 不启用（默认）；非空即启用且必须非回环（回环归主 listener；主 listener 已非回环时再配同样 fail-loud）。
    ws_external_host: str | None = None
    # 对外 listener 端口，默认 9002；未显式指定时沿用端口顺延（与 HTTP / 主 WS 同口径）。
    ws_external_port: int = Field(default=9002, ge=1, le=65535)
    # 成对给才生效；都不给则整对继承 WS_TLS_*；只给一半 fail-loud（绝不 A 的证书配 B 的私钥）。
    ws_external_tls_cert_file: str | None = None
    ws_external_tls_key_file: str | None = None
    # 只读旁观（默认关）：true 时对外 listener 不注册提交端点、cancel 回 invalid_request——给看不给下命令。
    ws_external_readonly: bool = False
    # 对外模式的 token 不是 Settings 字段（见 user_ws_auth_token 属性）：凭证只认用户级 setting.md，
    # 做成字段会让项目 .env / 系统环境变量能够覆盖它。
    # CLI 旁路订阅：把终端那轮 run 的事件只读推给外部客户端；默认关——无认证，开了等于让能连上的
    # 本机进程看到终端 agent 工具输出。不占运行名额、不写会话历史、无取消通道。
    ws_cli_bypass_enabled: bool = False
    # ---- 网页控制台的配置写入通道（Epic 50 Story 50-5） ----
    # 默认关：关闭时配置面全只读，且网页无法通过任何请求打开它（不在白名单，写入通道改不到自己）。
    # 开启渠道 = 任何启动配置；开启时入口层打高亮告警：任何能连上的人都能改项目 .env。
    # 写通道本身不是安全边界（无认证、无 TLS）。
    http_console_write_enabled: bool = False
    # 项目注册表落点覆盖（缺省 <服务启动工作区>/.heagent/console/projects.json；缺省不写用户 home）。
    http_console_projects_file: str | None = None

    @property
    def anthropic_key_pool(self) -> list[str]:
        return _parse_comma_list(self.anthropic_api_keys)

    @property
    def approval_tool_list(self) -> list[str]:
        return _parse_comma_list(self.approval_tools)

    @property
    def user_ws_auth_token(self) -> str | None:
        """WS 对外模式的 token：**只**读用户级 ``~/.heagent/setting.md`` 的 ``WS_AUTH_TOKEN``。

        刻意不做成 Settings 字段（Epic 56 D3）：字段会进入「系统环境变量 > 项目 ``.env`` >
        用户 setting.md」的优先级链，于是**仓库作者**可以在项目 ``.env`` 里预置一个「攻击者已知」
        的 token，让对外监听器照单全收。凭证只认用户级文件 ⇒ 项目配置无法参与。

        ``None`` = 未配置（对外模式据此 fail-closed）；空串 / 全空白同判。文件语法错时
        :class:`~heagent.config.user_settings.SettingsError` 原样上抛（配置坏了就该立刻看见）。
        """
        path = type(self)._user_setting_file
        if path is None:
            return None
        token = read_setting_md(Path(path)).get(WS_AUTH_TOKEN_KEY, "").strip()
        return token or None

    @property
    def sandbox_mode_resolved(self) -> str:
        """解析后的权限档位；非法值回退 ``workspace-write`` 并告警（不阻断启动）。

        与 ``ROUTING_POOLS`` 的容错风格一致：配置错误降级为安全默认值 + 显式告警，
        而不是让整个进程起不来（安全侧默认值即现状语义，不会静默放宽权限）。
        """
        mode = self.sandbox_mode.strip().lower()
        if mode in SANDBOX_MODES:
            return mode
        logger.warning(
            "SANDBOX_MODE %r is not one of %s; falling back to 'workspace-write'",
            self.sandbox_mode,
            sorted(SANDBOX_MODES),
        )
        return "workspace-write"

    @property
    def sandbox_env_allowlist_set(self) -> frozenset[str]:
        """沙箱 env 豁免 allowlist 的大小写不敏感集合（供 scrub_sensitive_env 匹配）。"""
        return frozenset(name.upper() for name in _parse_comma_list(self.sandbox_env_allowlist))

    @property
    def sandbox_profiles_map(self) -> dict[str, tuple[str, ...]]:
        """``SANDBOX_PROFILES``（JSON）解析结果：profile 名 → firejail 参数表。

        非法内容告警后丢弃（对齐 ``routing_pool_map`` 容错风格，不阻断启动）；
        逐条校验——单条非法仅跳过该条。
        """
        return self._parse_str_list_map(self.sandbox_profiles, "SANDBOX_PROFILES")

    def _json_object(self, raw: str, env_name: str, shape: str, *, warn: bool = True) -> dict[str, object]:
        """共享 JSON 配置内核：空串 / 非 JSON / 非 JSON object 告警后返回 ``{}``（不阻断启动）。

        ``shape`` 是「合法形状」的告警文案片段（如 ``{tool: profile}``）；``warn=False``
        用于静默降级的消费面（如价格表缺失只影响成本显示，不必每次启动告警）。
        """
        if not raw.strip():
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            if warn:
                logger.warning("%s is not valid JSON (%s); ignored", env_name, exc)
            return {}
        if not isinstance(payload, dict):
            if warn:
                logger.warning("%s must be a JSON object of %s; ignored", env_name, shape)
            return {}
        return payload

    @property
    def sandbox_tool_profiles_map(self) -> dict[str, str]:
        """``SANDBOX_TOOL_PROFILES``（JSON）解析结果：工具名 → profile 名。"""
        payload = self._json_object(self.sandbox_tool_profiles, "SANDBOX_TOOL_PROFILES", "{tool: profile}")
        result: dict[str, str] = {}
        for tool, profile in payload.items():
            if not isinstance(tool, str) or not tool.strip() or not isinstance(profile, str) or not profile.strip():
                logger.warning(
                    "SANDBOX_TOOL_PROFILES[%r] invalid (tool/profile must be non-empty strings); skipped", tool
                )
                continue
            result[tool] = profile.strip()
        return result

    def _parse_str_list_map(self, raw: str, env_name: str) -> dict[str, tuple[str, ...]]:
        """解析 ``{name: [str, ...]}`` 形状的 JSON；坏条目跳过、整体非法告警丢弃。"""
        payload = self._json_object(raw, env_name, "{profile: [args]}")
        result: dict[str, tuple[str, ...]] = {}
        for name, args in payload.items():
            if not isinstance(name, str) or not name.strip():
                logger.warning("%s has a non-string or empty profile name; skipped", env_name)
                continue
            if not isinstance(args, list) or not args or not all(isinstance(a, str) and a for a in args):
                logger.warning("%s[%r] must be a non-empty list of non-empty strings; skipped", env_name, name)
                continue
            result[name] = tuple(args)
        return result

    @property
    def routing_pool_map(self) -> dict[str, RoutingPoolSpec]:
        """路由池规格表：``ROUTING_POOLS``（JSON）解析结果（条目名 → 规格）。

        **唯一的路由配置入口**：某条目出现在这里即为启用该池——不再有按 provider 的专用
        开关（``ROUTING_ENABLED`` / ``GPT_ROUTING_ENABLED`` 等已移除）。
        """
        if not self.routing_pools.strip():
            return {}
        return self._parse_routing_pools(self.routing_pools)

    def _parse_routing_pools(self, raw: str) -> dict[str, RoutingPoolSpec]:
        """解析 ``ROUTING_POOLS`` JSON；非法内容告警后丢弃（不阻断启动）。"""
        payload = self._json_object(raw, "ROUTING_POOLS", "{entry: spec}")

        specs: dict[str, RoutingPoolSpec] = {}
        for entry, spec in payload.items():
            if entry not in ROUTING_POOL_ENTRIES:
                logger.warning(
                    "ROUTING_POOLS declares unknown provider entry %r (known: %s); ignored",
                    entry,
                    ", ".join(sorted(ROUTING_POOL_ENTRIES)),
                )
                continue
            try:
                specs[entry] = RoutingPoolSpec.model_validate(spec)
            except ValidationError as exc:
                logger.warning("ROUTING_POOLS[%s] invalid (%s); ignored", entry, exc)
        return specs

    @property
    def model_pricing_map(self) -> dict[str, dict[str, float]]:
        """解析模型价格表 JSON；无效 JSON 返回空 dict（不崩溃、不显示成本）。"""
        data = self._json_object(self.model_pricing, "MODEL_PRICING", "{model: {input, output}}", warn=False)
        result: dict[str, dict[str, float]] = {}
        for model, prices in data.items():
            if isinstance(prices, dict):
                result[model] = {
                    "input": float(prices.get("input", 0.0)),
                    "output": float(prices.get("output", 0.0)),
                }
        return result


class ResolvedRuntimeConfig(Settings):
    """Immutable construction-time copy; parsed properties return detached values.

    JSON configuration remains immutable text, so routing/profile dictionaries
    never alias the snapshot or another caller. Credentials are assembly-only.
    """

    model_config = SettingsConfigDict(**{**Settings.model_config, "frozen": True})
    safety_blocked_tools: tuple[str, ...] = ()  # type: ignore[assignment]
    workspace_root: str | None = None
    sources: tuple[RuntimeConfigSource, ...] = ()
    deepseek_api_key: str | None = Field(default=None, repr=False, exclude=True)
    anthropic_api_key: str | None = Field(default=None, repr=False, exclude=True)
    kimi_api_key: str | None = Field(default=None, repr=False, exclude=True)
    glm_api_key: str | None = Field(default=None, repr=False, exclude=True)
    openai_responses_api_key: str | None = Field(default=None, repr=False, exclude=True)
    ollama_api_key: str | None = Field(default=None, repr=False, exclude=True)
    anthropic_api_keys: str = Field(default="", repr=False, exclude=True)

    def source_for(self, name: str) -> str:
        for item in self.sources:
            if item.field == name:
                return item.source
        raise ValueError(f"Unknown runtime configuration field: {name}")


def resolve_runtime_config(settings: Settings | None = None, **overrides: object) -> ResolvedRuntimeConfig:
    """Resolve explicit non-None overrides once, retaining explicit False."""
    settings = settings if settings is not None else get_settings()
    if isinstance(settings, ResolvedRuntimeConfig) and not any(value is not None for value in overrides.values()):
        return settings
    values = {name: getattr(settings, name) for name in Settings.model_fields}
    values["safety_blocked_tools"] = tuple(settings.safety_blocked_tools)
    values["workspace_root"] = getattr(settings, "workspace_root", None)
    sources: dict[str, Literal["settings", "override"]] = {name: "settings" for name in values}
    if isinstance(settings, ResolvedRuntimeConfig):
        sources.update({item.field: item.source for item in settings.sources})
    for name, value in overrides.items():
        if name not in values:
            raise ValueError(f"Unknown runtime configuration override: {name}")
        if value is not None:
            values[name] = value
            sources[name] = "override"
    values["sandbox_mode"] = Settings.model_construct(**values).sandbox_mode_resolved
    values["sources"] = tuple(RuntimeConfigSource(field=name, source=source) for name, source in sources.items())
    return ResolvedRuntimeConfig(**values)


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
