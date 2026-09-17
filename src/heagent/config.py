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
import logging
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from heagent.types import RoutingPoolSpec

logger = logging.getLogger(__name__)

# 沙箱权限档位（P0-2）的合法取值；非法配置回退 ``workspace-write``（见 Settings.sandbox_mode_resolved）。
SANDBOX_MODES: frozenset[str] = frozenset({"read-only", "workspace-write", "danger-full-access"})

_settings: Settings | None = None  # 单例缓存

GLOBAL_CONFIG_DIR: Path = Path.home() / ".heagent"
GLOBAL_CONFIG_FILE: Path = GLOBAL_CONFIG_DIR / ".env"

# 路由池可绑定的 provider 条目名（与 cli._build_provider 的池内条目名一致）。
ROUTING_POOL_ENTRIES: frozenset[str] = frozenset({"deepseek", "kimi", "glm", "ollama", "openai", "gpt", "anthropic"})


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
    active_provider: str | None = None  # 启动时默认 provider，如 deepseek / kimi / glm / ollama / openai / anthropic

    # ---- API 密钥（可选，在 Provider 使用时校验） ----
    deepseek_api_key: str | None = None  # DeepSeek API Key
    openai_api_key: str | None = None  # OpenAI API Key
    anthropic_api_key: str | None = None  # Anthropic API Key
    kimi_api_key: str | None = None  # Kimi (Moonshot AI) API Key
    glm_api_key: str | None = None  # GLM (智谱 AI) API Key
    openai_responses_api_key: str | None = None  # OpenAI Responses API Key（wire_api="responses" 中转站）

    # ---- API 基础 URL（用于 OpenAI 兼容的第三方服务） ----
    deepseek_base_url: str | None = None  # DeepSeek 默认 https://api.deepseek.com/v1
    openai_base_url: str | None = None  # OpenAI 兼容服务（如 vLLM / 自营代理）
    anthropic_base_url: str | None = None  # Anthropic 代理地址
    kimi_base_url: str | None = None  # Kimi 默认 https://api.moonshot.cn/v1
    glm_base_url: str | None = None  # GLM 默认 https://open.bigmodel.cn/api/paas/v4
    openai_responses_base_url: str | None = None  # Responses API 中转站（如 https://www.komapi.top/v1）

    # ---- 各 Provider 默认模型（--model CLI 参数可覆盖） ----
    default_model: str = "gpt-4o"  # OpenAI 默认模型名称
    deepseek_model: str = "deepseek-v4-pro"  # DeepSeek 默认模型
    kimi_model: str = "kimi-k3"  # Kimi (Moonshot) 默认模型
    glm_model: str = "glm-5.3"  # GLM (智谱) 默认模型
    openai_model: str = "gpt-5.6-terra"  # gpt（Responses API）条目默认模型（env: OPENAI_MODEL）

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
    openai_api_keys: str = ""
    anthropic_api_keys: str = ""

    # ---- 智能路由（唯一入口：ROUTING_POOLS 声明式路由池） ----
    # JSON 形如：
    #   {"glm": {"tiers": {"fast": "glm-5.3-flash", "pro": "glm-5.3"}},
    #    "gpt": {"tiers": {"terra": "gpt-5.6-terra", "luna": "gpt-5.6-luna", "sol": "gpt-5.6-sol"},
    #            "roles": {"fast": "terra", "mid": "luna", "pro": "sol"}, "default": "terra"}}
    # 键须为 provider 条目名（deepseek/kimi/glm/ollama/openai/gpt/anthropic），**条目出现在这里
    # 即为启用该池**（必须有对应凭据）；没有按 provider 的专用开关。档位模型、角色映射、默认档、
    # 关键词（命中即路由到该档）、base_url 覆盖全在配置里——**调整路由池无需改代码**。
    # 无效 JSON / 非法规格 / 未知条目名 → 告警并忽略该条（不阻断启动）。
    routing_pools: str = Field(default="")

    # 推理链续接（判据 1，**所有池的默认值**，单池可用 "reasoning_continuity" 覆盖）：true 时
    # 「上一轮走了 pro 且思考痕迹仍在历史中」会让后续轮次即使没命中关键词也继续走 pro；
    # 默认 false = 尽量用 fast（只按**当前请求**是否命中关键词判定，历史命中不再锁定）。
    routing_reasoning_continuity: bool = Field(default=False)

    # ---- 框架运行参数 ----
    max_iterations: int = Field(default=50, ge=1)
    goal_max_iterations: int = Field(default=20, ge=1)
    # 子 Agent 委派的最大嵌套深度（0=禁止任何委派）。超限时 task_delegate /
    # task_parallel 返回 status=error，避免 LLM 自我委派无限递归。
    subagent_max_depth: int = Field(default=3, ge=0)
    # 嵌套子代理（task_delegate / task_parallel）的兜底迭代预算：角色未声明
    # `max_iterations` 时生效（优先级：显式参数 > 角色声明 > 本项）。默认 20 与
    # 此前写死在 SubAgent / 角色解析里的值一致。
    subagent_max_iterations: int = Field(default=20, ge=1)
    # Checkpoint decision policy for declarative /goal workflows.  Workflow
    # frontmatter may override this process-wide default.
    goal_checkpoint_mode: Literal["auto", "prompt"] = "prompt"
    # Open-question decision policy for declarative /goal step subagents.
    # block=stop with waiting_user on competing interpretations (default);
    # default=proceed with recommended defaults and record assumptions.
    # Workflow frontmatter may override this process-wide default.
    goal_open_question_mode: Literal["block", "default"] = "block"
    # 是否把「▶ 启动 / ✔ 完成 + 状态行」进度公告写到 stderr。嵌套子代理与交互输入行
    # 共用终端，公告可能被误提交为提示词；ANNOUNCE_PROGRESS=false 可静音。
    announce_progress: bool = Field(default=True)
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
    # 单次输出的最大 token 数（OpenAI 兼容 Chat Completions 的 max_tokens、Responses 的
    # max_output_tokens、Anthropic 的 max_tokens）。None = 不设上限（沿用各 provider 默认）。
    # 本地思考模型（如 Ollama 的 qwen3.5 等）无上限时可能无限生成，本地测试建议设一个值（如 4096）。
    max_output_tokens: int | None = Field(default=None, ge=1)
    shell_timeout: int = Field(default=120, ge=1)

    # ---- 日志参数 ----
    log_dir: str = Field(default="logs")  # 日志文件目录，每次启动创建新文件
    log_level: str = Field(default="INFO")  # 控制台(stderr)日志级别: DEBUG / INFO / WARNING / ERROR
    log_file_level: str | None = Field(default=None)  # 文件日志级别; None=回退到 log_level

    # ---- Token 计量（P0-3） ----
    # auto（默认）= 装了 tiktoken 就用真实 tokenizer，否则用 CJK 感知启发式（并按 provider
    #   真实 usage 在线校准系数）；estimate = 强制启发式（对齐旧行为 / 离线复现）；
    #   tiktoken = 强制真实 tokenizer（依赖缺失时告警一次后回退估算）。
    # 注：计量结果直接决定压缩阈值与窗口重置判定，偏差会放大为「该压缩时没压缩」或白丢上下文。
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
    # 分层发现的字节总预算：超预算时**近端优先**（越靠近 cwd 越具体），被丢弃/截断的文件
    # 以显式标记回报，绝不静默。
    context_files_max_bytes: int = Field(default=32768, ge=1)
    # 是否纳入用户级 `~/.heagent/AGENTS.md`（排在最前、最泛）。默认关闭：全局文件会静默
    # 影响每个项目，且会让测试依赖开发机 home。
    context_files_user_level: bool = Field(default=False)

    # ---- 事件传输（JSONL / rollout）----
    # 是否把每次 run 的事件落盘为 .heagent/runs/<run_id>/rollout.jsonl（可 `heagent replay` 回放）。
    # 默认关闭：落盘内容含命令与工具原始输出（与工具返回同等不可信），按需开启。
    events_rollout_enabled: bool = Field(default=False)

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

    # ---- Run 快照自动清理参数 ----
    # .heagent/runs/ 的 run 快照（`<run_id>.json` + 配套 .lock + `<run_id>/` 产物目录）超过此天数
    # 在 run 启动时自动删除；0=禁用清理。默认 7 天与 ledger 对齐——persist.py 刻意保留 .lock
    # 以规避 unlink 竞态，故必须有回收方，否则 runs 目录随运行次数单调增长（实测 84 天 6 万文件）。
    run_retention_days: int = Field(default=7, ge=0)
    # 过期清理的跨进程节流（秒）：距上次清理不足该间隔就跳过扫描（0=每次都扫）。
    # 每次全新 run 启动都要扫 `.heagent/runs` + `.heagent/ledger`，短命 CLI 进程（每次调用
    # 都是新进程）在这层节流下能省掉几乎全部扫描成本；保留期以天计，延迟清理无副作用。
    prune_min_interval_seconds: int = Field(default=900, ge=0)

    # ---- 运行时产物保留期（日志 / 会话 / 编辑快照，由 CLI 启动时的 housekeeping 回收）----
    # 这三类此前没有回收方，会随使用单调增长（实测 84 天：logs 21 MiB、sessions 83 MiB、
    # edit-snapshots 只增不减）。0=禁用该类清理。
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
    # "auto"（默认）= 探测可用后端：firejail 可用则用（Linux/macOS），否则 passthrough。
    #   Windows 的 "winjob" 需显式指定——WinJob 无文件系统隔离，自动启用会改变所有
    #   shell 命令的进程语义而收益有限（故 auto 不选它）。
    # "passthrough" = 零隔离；"firejail" = FirejailBackend；"winjob" = WinJobBackend。
    # CLI --sandbox flag 可覆盖；显式指定而不可用时降级 Passthrough 并告警。
    sandbox_backend: str = Field(default="auto")
    # 权限档位（P0-2）：
    #   read-only          = 只放行只读工具，其余一律 BLOCKED（fail-closed）；
    #   workspace-write    = 现状：写操作受工作区围栏 + 凭证 deny + 审批管辖；
    #   danger-full-access = 跳过围栏与 deny 预检（显式危险模式，仅限受控环境）。
    # 非法值经 sandbox_mode_resolved 回退 workspace-write 并告警（不阻断启动）。
    sandbox_mode: str = Field(default="workspace-write")
    # 沙箱网络开关（P0-2）：False（默认）= 禁止子进程出站。仅真实沙箱后端可强制
    # （firejail 映射为 --net=none）；passthrough / winjob 无网络隔离能力，会记提示
    # 而非假装生效。宿主进程内的 HTTP 工具（web_fetch）不受此开关约束。
    sandbox_network: bool = Field(default=False)
    # 沙箱强制开关（P0-2）：True（默认）= 探测到**真实**沙箱后端时，自动把 shell 纳入
    # PolicyEngine.sandbox_tools 并授权当次 run 走沙箱路径（否则要手工配 sandbox_tools）。
    # 无真实后端（passthrough）时不改变任何行为——不给「已在沙箱里跑」的假象。
    sandbox_enforce: bool = Field(default=True)
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
    # 沙箱会话目录保留开关（FR-4）：True = run 结束后保留会话目录；False（默认）= 删除。
    sandbox_session_keep: bool = Field(default=False)
    # 沙箱会话目录保留天数（E40-D1）：崩溃 run 留下的 `.heagent/sandboxes/<run_id>/` 不经过
    # 正常 teardown，由 CLI/GUI 启动时的 housekeeping 按本保留期回收（0=禁用）。
    # 7 天与编辑快照同档——它是 per-run 临时工作区，比 run 快照（30 天）短命得多。
    sandbox_dir_retention_days: int = Field(default=7, ge=0)
    # 沙箱 profile → firejail 参数映射（2026-09-17 硬化批）：JSON 对象
    # ``{"<profile名>": ["--seccomp", "--caps.drop=all"]}``。经 FirejailBackend.profiles
    # 生效，使 "default"/"mcp"/自定义 profile 产生实际参数差异（高级隔离参数 --seccomp/
    # --caps 由此声明，默认关闭）。空 = 零参数（现状）。均为 defense-in-depth，
    # 非真正安全边界（见 CLAUDE.md 安全声明）。
    sandbox_profiles: str = Field(default="")
    # 工具 → 沙箱 profile 名映射（per-tool 参数粒度）：JSON 对象 ``{"<工具名>": "<profile名>"}``。
    # 注入 PolicyEngine.sandbox_profiles（与代码内 sandbox_profiles 参数同形状、叠加生效），
    # 使单个工具可差异化选用 profile。空 = 现状（工具名映射缺省落 "default"）。
    sandbox_tool_profiles: str = Field(default="")
    # 沙箱 shell 内存限额（MB，0=关闭）：firejail 映射 --rlimit-as；WinJob 映射
    # JOB_OBJECT_LIMIT_JOB_MEMORY。限额触发 → 子进程被终止 → 非零退出码经正常结果回传
    # （显性失败，对齐超时语义；不静默截断输出）。
    sandbox_memory_limit_mb: int = Field(default=0, ge=0)
    # 沙箱 shell CPU 时间限额（秒，0=关闭）：firejail 映射 --rlimit-cpu；WinJob 映射
    # JOB_OBJECT_LIMIT_PROCESS_TIME。触发行为同内存限额（显性失败）。
    sandbox_cpu_seconds: int = Field(default=0, ge=0)

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

    @property
    def sandbox_tool_profiles_map(self) -> dict[str, str]:
        """``SANDBOX_TOOL_PROFILES``（JSON）解析结果：工具名 → profile 名。"""
        if not self.sandbox_tool_profiles.strip():
            return {}
        try:
            payload = json.loads(self.sandbox_tool_profiles)
        except json.JSONDecodeError as exc:
            logger.warning("SANDBOX_TOOL_PROFILES is not valid JSON (%s); ignored", exc)
            return {}
        if not isinstance(payload, dict):
            logger.warning("SANDBOX_TOOL_PROFILES must be a JSON object of {tool: profile}; ignored")
            return {}
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
        if not raw.strip():
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("%s is not valid JSON (%s); ignored", env_name, exc)
            return {}
        if not isinstance(payload, dict):
            logger.warning("%s must be a JSON object of {profile: [args]}; ignored", env_name)
            return {}
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
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("ROUTING_POOLS is not valid JSON (%s); ignored", exc)
            return {}
        if not isinstance(payload, dict):
            logger.warning("ROUTING_POOLS must be a JSON object of {entry: spec}; ignored")
            return {}

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
