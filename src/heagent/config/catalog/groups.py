"""配置分组数据表：组规格、可写白名单来源、只读原因与展示标签。

自 ``heagent.config.catalog`` 单文件拆出（E3 绞杀者），行为零改动。
"""

from __future__ import annotations

from .models import MAX_FILE_DIAGNOSTIC_KEYS, MAX_UNKNOWN_KEYS, ConfigGroupSpec

#: 可写白名单（fail-closed：显式允许子集，**不是**排除法）——键数由下方分组常量派生，不另记数。
WHITELIST_GROUPS: tuple[ConfigGroupSpec, ...] = (
    ConfigGroupSpec(
        id="models",
        label="模型",
        keys=(
            "DEFAULT_MODEL",
            "DEEPSEEK_MODEL",
            "KIMI_MODEL",
            "GLM_MODEL",
            "OPENAI_MODEL",
            "OLLAMA_MODEL",
        ),
    ),
    ConfigGroupSpec(
        id="routing",
        label="智能路由",
        keys=("ROUTING_POOLS", "ROUTING_REASONING_CONTINUITY"),
    ),
    ConfigGroupSpec(
        id="limits",
        label="迭代与限额",
        keys=(
            "MAX_ITERATIONS",
            "GOAL_MAX_ITERATIONS",
            "SUBAGENT_MAX_ITERATIONS",
            "SUBAGENT_MAX_DEPTH",
            "MAX_OUTPUT_TOKENS",
            "ANNOUNCE_PROGRESS",
        ),
    ),
    ConfigGroupSpec(
        id="context",
        label="上下文",
        keys=(
            "MAX_CONTEXT_TOKENS",
            "COMPRESSION_THRESHOLD",
            "WINDOW_RESET_THRESHOLD",
            "CONTEXT_STRATEGY",
            "TOKENIZER",
            "CONTEXT_FILES_ENABLED",
            "CONTEXT_FILES_MAX_BYTES",
            "CONTEXT_FILES_USER_LEVEL",
        ),
    ),
    ConfigGroupSpec(
        id="memory_skills",
        label="记忆与技能",
        keys=(
            "MEMORY_NUDGE_ENABLED",
            "MEMORY_INJECT_MAX_BYTES",
            # 语义压缩写侧开关：与归档两键同属记忆整理旋钮，但它是无人监督删改的
            # 显式 opt-in（默认 False，对齐 DREAM_ENABLED 立场），故与注入开关同组可见可写。
            "MEMORY_COMPACT_ENABLED",
            "SKILL_MATCH_THRESHOLD",
            "SKILL_MAX_AUTO_INVOKE",
            "SKILL_MAX_AUTO_INVOKE_TOKENS",
            "SKILL_MAX_MANUAL_LOAD_TOKENS",
            "SKILL_CURATOR_STALE_DAYS",
        ),
    ),
    ConfigGroupSpec(
        id="retention",
        label="保留期与回收",
        keys=(
            "LEDGER_RETENTION_DAYS",
            "RUN_RETENTION_DAYS",
            "RUN_STALE_IDLE_HOURS",
            "LOG_RETENTION_DAYS",
            "SESSION_RETENTION_DAYS",
            "EDIT_SNAPSHOT_RETENTION_DAYS",
            # 显式白名单 > 模式排除 ⇒ 本键可写（保留天数是运维可调项，非隔离姿态）。
            "SANDBOX_DIR_RETENTION_DAYS",
            "PRUNE_MIN_INTERVAL_SECONDS",
            # 记忆自动归档（触发口径为「字节」）：
            # 触发阈值与节流间隔同属「数据生命周期旋钮」，与上面几项同型 —— 都支持 0 = 禁用，
            # 且都由 RESOURCE_CEILINGS 给上界。
            "MEMORY_ARCHIVE_TRIGGER_BYTES",
            "MEMORY_ARCHIVE_MIN_INTERVAL_SECONDS",
        ),
    ),
    ConfigGroupSpec(
        id="cron",
        label="定时调度",
        # 结果推送两键：与 tick 同组可见可写——「调度」这件事的两端：
        # 多久扫一次（tick）与扫完把结果送哪里去（push / echo）。
        keys=("CRON_TICK_SECONDS", "CRON_PUSH_ENABLED", "CRON_ECHO_TO_TERMINAL"),
    ),
    ConfigGroupSpec(
        id="observability",
        label="日志与观测",
        keys=("LOG_LEVEL", "LOG_FILE_LEVEL", "EVENTS_ROLLOUT_ENABLED"),
    ),
    ConfigGroupSpec(
        id="providers",
        label="Provider 行为",
        keys=("ANTHROPIC_PROMPT_CACHING", "OLLAMA_ENABLED"),
    ),
    ConfigGroupSpec(
        id="resilience",
        label="重试与退避",
        keys=("RETRY_MAX_ATTEMPTS", "RETRY_BASE_DELAY", "RETRY_MAX_DELAY"),
    ),
)

#: 只读排除组（**显式行 > 模式行**，同型按表内顺序取首条）。
EXCLUSION_GROUPS: tuple[ConfigGroupSpec, ...] = (
    # ── 显式键行（先于一切模式行求值 ⇒ HTTP_CONSOLE_* 的只读原因是「控制台自身」而非「监听面」）──
    ConfigGroupSpec(
        id="console",
        label="控制台自身",
        keys=("HTTP_CONSOLE_WRITE_ENABLED", "HTTP_CONSOLE_PROJECTS_FILE"),
        reason="console_itself",
    ),
    ConfigGroupSpec(
        id="dream_supervision",
        label="无人监督的后台巩固",
        keys=("DREAM_CRON", "DREAM_IDLE_MINUTES", "DREAM_MAX_ITERATIONS", "DREAM_SESSION_LOOKBACK"),
        reason="dream_supervision",
    ),
    ConfigGroupSpec(
        id="process_spawn",
        label="进程拉起与后台执行",
        keys=("HOOKS_ENABLED", "MCP_ENABLED", "MCP_CONFIG_PATH", "CRON_ENABLED", "DREAM_ENABLED"),
        reason="process_spawn",
    ),
    ConfigGroupSpec(
        id="safety",
        label="安全闸门",
        keys=("SAFETY_BLOCKED_TOOLS", "APPROVAL_TOOLS"),
        reason="safety_gate",
    ),
    ConfigGroupSpec(
        id="paths",
        label="宿主路径与工作流",
        keys=("LOG_DIR", "GOAL_WORKFLOW_SKILL"),
        reason="host_path",
    ),
    ConfigGroupSpec(id="outbound", label="出站与端点", keys=("ACTIVE_PROVIDER",), reason="outbound_redirect"),
    ConfigGroupSpec(
        id="run_semantics",
        label="运行语义开关",
        keys=("PLAN_MODE", "MODEL_PRICING"),
        reason="run_semantics",
    ),
    # ── 模式行 ──
    ConfigGroupSpec(
        id="credentials",
        label="凭证",
        patterns=("*_API_KEY", "*_API_KEYS"),
        reason="credential",
    ),
    ConfigGroupSpec(
        id="listening",
        label="监听面",
        # WS server 独立成 WS_* 配置面，与 HTTP_* 同属「监听面」。
        patterns=("HTTP_*", "WS_*"),
        reason="listening_surface",
    ),
    ConfigGroupSpec(
        id="sandbox",
        label="沙箱与执行后端",
        patterns=("SANDBOX_*",),
        reason="sandbox_posture",
    ),
    ConfigGroupSpec(
        id="outbound",
        label="出站与端点",
        patterns=("*_BASE_URL",),
        reason="outbound_redirect",
    ),
    ConfigGroupSpec(
        id="run_semantics",
        label="运行语义开关",
        patterns=("GOAL_*_MODE",),
        reason="run_semantics",
    ),
)

#: 兜底分组：划分破损时条目仍可见（由完备性测试断言其恒为空）。
UNKNOWN_GROUP = ConfigGroupSpec(id="unclassified", label="未分类", reason="unknown_key")

#: 只读原因 / 诊断码的中文文案（响应随 ``labels`` 一并回给客户端，UI 无需硬编码）。
LABELS: dict[str, str] = {
    # 高影响键：徽标短文案 + 说明长文案
    "impact_high": "高影响",
    "impact_high_note": "有上界的资源旋钮：极端值会让下一次运行不可完成",
    # 只读原因
    "system_env": "被系统环境变量提供：改 .env 不会影响本次进程",
    "credential": "凭证项：永不回传、永不写入",
    "listening_surface": "监听面 / 暴露面：改动需要重启服务",
    "sandbox_posture": "沙箱与执行后端：改动等于改变 OS 级隔离姿态",
    "process_spawn": "进程拉起 / 无人监督后台执行开关",
    "dream_supervision": "无人监督的后台巩固参数（其开关 DREAM_ENABLED 本身只读）",
    "host_path": "宿主路径 / 任意工作流加载面",
    "safety_gate": "安全闸门：降低 defense-in-depth 等于自我削权",
    "outbound_redirect": "出站重定向：可把凭证送往往意端点（准外泄通道）",
    "run_semantics": "运行语义开关：静默改变行为，超出「配置展示」范围",
    "console_itself": "控制台自身开关：写入面不得给自己解锁",
    "unknown_key": "未知键（不在 Settings 字段集内）",
    # 项目 .env / 全局 setting.md 的诊断
    "duplicate_in_project_env": "项目 .env 中该键出现多次（后者生效）",
    "empty_in_project_env": "项目 .env 中该键为空值（显式置空，不生效）",
    "empty_in_global_setting": "全局 setting.md 中该键为空值（显式置空，不生效）",
    "ineffective_in_project_env": "项目 .env 中该键未被解析（写法不受支持）",
    "bom_prefixed_in_project_env": "项目 .env 中该键带 BOM 前缀 ⇒ 不生效（请删除该字节）",
    "bom_stripped_in_project_env": "项目 .env 文件头带 BOM，已按容差读取（盘上字节未改）",
    "inline_comment_in_project_env": "项目 .env 中该键带行内注释",
    "routing_pools_invalid": "ROUTING_POOLS 不是合法 JSON 对象 ⇒ **整份配置被忽略**，已回落各条目 `<条目>_MODEL`",
    "routing_pools_entries_ignored": "ROUTING_POOLS 中这些条目被整条忽略（未知条目名或规格非法）⇒ 该池不生效",
    # 文件级 / 响应级
    "project_env_missing": "项目 .env 不存在：全部字段回退到全局 .env / 默认值",
    "project_env_unreadable": "项目 .env 不可读：全部字段回退到全局 .env / 默认值",
    "project_env_bom_stripped": "项目 .env 带文件头 BOM：已剥离后求解（盘上字节未改）",
    "project_env_blank_values": (
        "项目 .env 含空值键（`KEY=`）：bool/int 等字段会因此**拒绝加载**配置，故本次求解把空值"
        "当作「未提供」（请填值或删除该行；文件未改动）"
    ),
    "project_env_invalid": "项目 .env 的值非法：本次求解不含项目层（文件未改动）",
    "user_setting_unparseable": "全局 setting.md 无法解析（语法错 / 重复键）：本次求解不含用户层（文件未改动）",
    "env_files_unavailable": "所有 .env 都不可用：本次求解只有系统环境变量与默认值",
    "bom_prefixed_keys": "存在带 BOM 前缀的键名 ⇒ 这些键不生效（见对应条目）",
    "unknown_keys_truncated": f"未知键过多，只列出前 {MAX_UNKNOWN_KEYS} 条",
    "file_diagnostics_truncated": f"文件级诊断（重复键 / 空值键）过多，只列出前 {MAX_FILE_DIAGNOSTIC_KEYS} 条",
    "write_channel_disabled": (
        "服务启动时未开启配置写入（HTTP_CONSOLE_WRITE_ENABLED）：所有可写项在本页只读；"
        "网页无法自行开启，需在启动配置（系统环境变量 / 项目 .env / 全局 .env）里开启后重启服务"
    ),
    # 面板级**一行短状态**：上面那句长文案仍保留（写进 HTML `title` / 直接调 API
    # 的客户端仍能读到完整解释），版面上只显示短文案；逐项那份重复已撤（可写项只在头部
    # 的徽标上说一次），本键改作徽标 `title` 的第一句。
    "write_channel_short": "未开启配置写入：可写项在本页只读",
    # 挂在设置面板头部**项目名后面的紧凑徽标**文案。宽度是硬约束：设置列只有 ~364px，
    # 「项目设置 + 项目名徽标」已占 ~160px，再长的文案会换行 ⇒ 又变成「独占一行」。
    # 因此徽标只显示「只读」，完整原因（`write_channel_short` + `write_channel_disabled`）见 `title`。
    "write_channel_badge": "只读",
    # 写入通道：写已生效但审计没落盘 —— 必须显式，不能让人误以为「已审计」。
    "audit_not_recorded": "写入已生效，但审计记录未能落盘（服务端有 ERROR 日志；请检查 console 目录写权限）",
}
