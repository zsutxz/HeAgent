"""``heagent init --interactive``：交互式配置向导。

落点与 ``heagent init`` 一致——只写**用户级** ``~/.heagent/setting.md``（全机默认值），不碰项目
``.env``。流程：逐项询问 → 合并进既有 frontmatter（注释 / 正文 / 未涉及键原样保留）→ 验证 →
原子替换。

四条约束（违反即偏离本模块的契约）：

1. **非 tty 显性失败**：管道 / CI 里没有可交互终端时报错并给可执行替代（写环境变量 / 直接编辑
   文件），绝不把默认值静默写盘。
2. **先验证后落盘**：候选内容写在临时目录里的同名文件，经 ``read_setting_md`` 往返、``Settings``
   构造、``build_config_report`` 结构校验全部通过后才原子替换目标文件；任何一步失败都不动目标文件。
3. **不破坏既有内容**：只改命中的 frontmatter 行；注释、正文、未涉及的键、行尾风格一律原样保留。
4. **覆盖范围有界**：只问 :data:`COMMON_KEY_GROUPS` 列出的常用面，顺序即提问顺序（凭据 → 模型与预算
   → 路由池 → 上下文 → 记忆与技能 → MCP → 入口（HTTP / WS）→ 观测 → 沙箱）；安全闸门
   （``SAFETY_BLOCKED_TOOLS`` / ``APPROVAL_TOOLS``）、宿主路径、无人监督后台开关（``DREAM_*``）刻意
   不进向导——在向导里顺手削 defense-in-depth 或改宿主任意路径不属于「常用配置」。沙箱与监听面**在**
   清单内：向导是本地交互式操作、逐项按当前值现答，写进去的是用户自己的选择；``config.catalog``
   的只读原因针对的是网页写通道，不是本向导。

推荐值口径：默认取 ``Settings`` 的字段默认值（唯一事实源，:func:`_field_default_text` 现读），
只有「字段默认值不是推荐起点」的键才在 :class:`WizardItem.recommend` 显式覆盖并写明理由。
值域口径：优先用 ``catalog.guards_for``（单一事实源）；catalog 没有守卫的可枚举键才在
:class:`WizardItem.choices` 显式列出（填错会被静默降级的那类键，如 ``SANDBOX_BACKEND``）。

依赖面：click + ``heagent.config`` / ``heagent.config.catalog`` + 标准库；不导入 agent / providers /
engine——向导是 CLI 的轻量配置路径。
"""

from __future__ import annotations

import sys
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import click
from pydantic import BaseModel, ConfigDict

from heagent.cli.errors import ANCHOR_CLI_ERRORS, exit_with_hints
from heagent.cli.settings_audit import record_settings_write, snapshot_settings
from heagent.config import GLOBAL_SETTING_FILE, Settings
from heagent.config.catalog import ConfigSource, build_config_report, guards_for
from heagent.config.envfile import check_key, parse_value
from heagent.config.user_settings import SettingsError, read_setting_md, with_user_setting_layer, write_setting_md

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from heagent.config.catalog import ConfigGuard, ConfigItem, ConfigReport

#: 覆盖率下限（票面「覆盖 >80% 常用配置项」）。分母 = :data:`COMMON_KEYS`，分子 = :func:`covered_keys`。
MIN_COVERAGE = 0.8

#: 新文件的 frontmatter 注释块：只写加载优先级这条不变量。
_FRESH_HEADER = """# HeAgent 用户级配置（~/.heagent/setting.md）
# 加载优先级：系统环境变量 > 项目 .env > 本文件 > 字段默认值。
# 写法：`KEY: value`（冒号+空格）；`#` 整行注释。值后面「空白 + #」起算行内注释、会被剥掉，
# 要写字面 `#` 请确保前面没有空白（或用引号包起来）。
"""

#: 新文件的正文（既有文件保留自身正文，不被本段替换）。
_FRESH_BODY = """
## 说明

本文件是全机默认值，单个项目可在自己的 `.env` 里覆盖同名键。
逐键含义见 `.env.example` 与 `docs/frame/config.md`；改完可跑 `heagent doctor` 复核。
"""

#: 有效值来源的中文文案（与 ``config.catalog`` 的 ``ConfigSource`` 一一对应）。
_SOURCE_LABELS: dict[ConfigSource, str] = {
    ConfigSource.SYSTEM_ENV: "系统环境变量",
    ConfigSource.PROJECT_ENV: "项目 .env",
    ConfigSource.GLOBAL_SETTING: "用户级 setting.md",
    ConfigSource.DEFAULT: "字段默认值",
}

#: 无法表达的值 / 无法解析的文件等显性失败的统一下一步建议。
_REPAIR_OPTIONS: tuple[str, ...] = (
    "按上面报出的键名修正取值，然后重新运行 heagent init --interactive",
    "手工编辑 ~/.heagent/setting.md（KEY: value 写在 --- 之间），再跑 heagent doctor 复核",
)


class WizardKind(StrEnum):
    """一项的输入形态：布尔 / 明文 / 不回显（凭证）。"""

    TEXT = "text"
    BOOL = "bool"
    SECRET = "secret"  # noqa: S105 - 这是字段形态的枚举值，不是口令  # nosec B105


class WizardItem(BaseModel):
    """向导的一项：键名 + 中文名 + 一句说明 + 推荐值（+ 可选值域）。

    ``recommend=None`` 表示「推荐值 = 字段默认值」（唯一事实源在 ``Settings``）；显式给字符串只用于
    「字段默认值不是推荐起点」的键。``choices`` 只在 ``catalog`` 没有枚举守卫时使用——它把值域钉在
    交互这一层（写错不会有第二道校验兜住）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    label: str
    why: str
    recommend: str | None = None
    kind: WizardKind = WizardKind.TEXT
    choices: tuple[str, ...] = ()


class WizardResult(BaseModel):
    """一次向导运行的结果（写入 / 未变 / 被环境变量接管 的键名，按向导顺序）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    written: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    system_env: tuple[str, ...] = ()
    verified: bool = False


class WizardError(Exception):
    """向导的显性失败：``options`` 是给人读的下一步动作（渲染成 ``Try:`` 列表）。"""

    def __init__(self, message: str, *, options: Sequence[str]) -> None:
        super().__init__(message)
        self.options: tuple[str, ...] = tuple(options)


class _InvalidValue(ValueError):
    """单个输入值不合规（重问当前项，不终止向导）。"""


# ── 常用配置项清单（覆盖率的分母）与向导覆盖项（分子） ──


class CommonKeyGroup(BaseModel):
    """常用项的一个「面」：id（报告与测试引用）+ 中文面名 + 该面的键（顺序即提问顺序）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    keys: tuple[str, ...]


#: 「常用配置项」按面分组：票面 80% 覆盖率的分母，同时**决定提问顺序**——按依赖 / 心智顺序排，
#: 别让用户先被问 WS 端口再被问 API key：凭据 → 模型与预算 → 路由池 → 上下文 → 记忆与技能 →
#: MCP → 入口（HTTP / WS）→ 观测 → 沙箱（最后问：这一面最影响隔离姿态）。
#: 每项都必须是 ``Settings`` 真实字段、且能被 ``config.catalog`` 分类（测试钉住，防清单与字段漂移）。
COMMON_KEY_GROUPS: tuple[CommonKeyGroup, ...] = (
    CommonKeyGroup(
        id="provider_credentials",
        label="Provider 与凭据",
        keys=(
            "DEEPSEEK_API_KEY",
            "ANTHROPIC_API_KEY",
            "KIMI_API_KEY",
            "GLM_API_KEY",
            "OPENAI_RESPONSES_API_KEY",
            "WEB_SEARCH_API_KEY",
            "ACTIVE_PROVIDER",
            "OLLAMA_ENABLED",
        ),
    ),
    CommonKeyGroup(
        id="models",
        label="模型与输出预算",
        keys=(
            "DEFAULT_MODEL",
            "DEEPSEEK_MODEL",
            "KIMI_MODEL",
            "GLM_MODEL",
            "OPENAI_MODEL",
            "OLLAMA_MODEL",
            "MAX_OUTPUT_TOKENS",
        ),
    ),
    CommonKeyGroup(
        id="routing",
        label="路由池",
        keys=("ROUTING_POOLS", "ROUTING_REASONING_CONTINUITY"),
    ),
    CommonKeyGroup(
        id="limits",
        label="迭代预算",
        keys=("MAX_ITERATIONS", "SUBAGENT_MAX_ITERATIONS"),
    ),
    CommonKeyGroup(
        id="context",
        label="上下文与压缩",
        keys=(
            "MAX_CONTEXT_TOKENS",
            "COMPRESSION_THRESHOLD",
            "CONTEXT_STRATEGY",
            "TOKENIZER",
            "CONTEXT_FILES_ENABLED",
            "CONTEXT_FILES_MAX_BYTES",
        ),
    ),
    CommonKeyGroup(
        id="memory_skills",
        label="记忆与技能",
        keys=(
            "MEMORY_NUDGE_ENABLED",
            "MEMORY_INJECT_MAX_BYTES",
            "SKILL_MATCH_THRESHOLD",
            "SKILL_CURATOR_STALE_DAYS",
        ),
    ),
    CommonKeyGroup(
        id="mcp",
        label="MCP 外部工具",
        keys=("MCP_ENABLED", "MCP_CONFIG_PATH"),
    ),
    CommonKeyGroup(
        id="http_entry",
        label="HTTP 入口",
        keys=("HTTP_ENABLED", "HTTP_HOST", "HTTP_PORT", "HTTP_MAX_INFLIGHT_RUNS"),
    ),
    CommonKeyGroup(
        id="ws_entry",
        label="WS 入口",
        keys=("WS_ENABLED", "WS_HOST", "WS_PORT", "WS_LAN_NO_AUTH", "WS_LOCAL_AUTH_ENABLED"),
    ),
    CommonKeyGroup(
        id="observability",
        label="日志与事件",
        keys=("LOG_LEVEL", "EVENTS_ROLLOUT_ENABLED"),
    ),
    CommonKeyGroup(
        id="sandbox",
        label="沙箱与执行后端",
        keys=("SANDBOX_BACKEND", "SANDBOX_DOCKER_IMAGE", "SANDBOX_DOCKER_DIGEST"),
    ),
)

#: 常用项扁平清单（覆盖率的分母）：由 :data:`COMMON_KEY_GROUPS` 展平派生，不另写第二份。
COMMON_KEYS: tuple[str, ...] = tuple(key for group in COMMON_KEY_GROUPS for key in group.keys)

#: 向导逐项询问的键（覆盖率分子）。**顺序必须与** :data:`COMMON_KEYS` **一致**（测试钉住）：
#: 分组表是提问顺序的唯一事实源，这里只补中文名 / 一句说明 / 推荐值口径。
WIZARD_ITEMS: tuple[WizardItem, ...] = (
    # ── Provider 与凭据 ──
    WizardItem(
        key="DEEPSEEK_API_KEY",
        label="DeepSeek API Key",
        why="写入本文件即成为全机默认；单个项目可在 .env 覆盖。留空 = 不改动",
        kind=WizardKind.SECRET,
    ),
    WizardItem(
        key="ANTHROPIC_API_KEY",
        label="Anthropic API Key",
        why="claude 条目用；同 provider 的多密钥轮换走另一键 ANTHROPIC_API_KEYS（逗号分隔）。留空 = 不改动",
        kind=WizardKind.SECRET,
    ),
    WizardItem(
        key="KIMI_API_KEY",
        label="Kimi (Moonshot) API Key",
        why="kimi 条目用；与 KIMI_MODEL 一起决定该条目能否启动。留空 = 不改动",
        kind=WizardKind.SECRET,
    ),
    WizardItem(
        key="GLM_API_KEY",
        label="GLM (智谱) API Key",
        why="glm 条目用；与 GLM_MODEL 一起决定该条目能否启动。留空 = 不改动",
        kind=WizardKind.SECRET,
    ),
    WizardItem(
        key="OPENAI_RESPONSES_API_KEY",
        label="OpenAI Responses API Key",
        why="只服务 wire_api=responses 的 openai 条目（中转站 / GPT-5.x）；只配 OPENAI_API_KEY 不产生可用条目。"
        "留空 = 不改动",
        kind=WizardKind.SECRET,
    ),
    WizardItem(
        key="WEB_SEARCH_API_KEY",
        label="联网搜索 API Key",
        why="web_search 工具用（引擎看 WEB_SEARCH_ENGINE，默认 tavily）；不填则调用时显性报错。留空 = 不改动",
        kind=WizardKind.SECRET,
    ),
    WizardItem(
        key="ACTIVE_PROVIDER",
        label="默认 Provider 条目",
        why="启动时默认用哪个条目（deepseek / claude / openai / kimi / glm / ollama）；留空 = 自动选第一个有凭据的",
    ),
    WizardItem(
        key="OLLAMA_ENABLED",
        label="启用本地 Ollama",
        why="true 时才装配本地条目（默认端点 127.0.0.1:11434）；启用后 OLLAMA_MODEL 必填，否则启动即失败",
        kind=WizardKind.BOOL,
    ),
    # ── 模型与输出预算 ──
    WizardItem(
        key="DEFAULT_MODEL",
        label="claude 条目的兜底模型",
        why="claude 条目未显式指定模型时用它；--model 可在单次运行覆盖",
    ),
    WizardItem(
        key="DEEPSEEK_MODEL",
        label="DeepSeek 默认模型",
        why="deepseek 条目未显式指定模型时用它；--model 可在单次运行覆盖",
    ),
    WizardItem(
        key="KIMI_MODEL",
        label="Kimi 默认模型",
        why="kimi 条目未显式指定模型时用它；--model 可在单次运行覆盖",
    ),
    WizardItem(
        key="GLM_MODEL",
        label="GLM 默认模型",
        why="glm 条目未显式指定模型时用它；--model 可在单次运行覆盖",
    ),
    WizardItem(
        key="OPENAI_MODEL",
        label="openai（Responses API）条目默认模型",
        why="只作用于 wire_api=responses 的条目；--model 可在单次运行覆盖",
    ),
    WizardItem(
        key="OLLAMA_MODEL",
        label="Ollama 模型名",
        why="OLLAMA_ENABLED=true 时必填（如 qwen3.5-9b-local:latest）；本地窗口通常远小于 MAX_CONTEXT_TOKENS",
    ),
    WizardItem(
        key="MAX_OUTPUT_TOKENS",
        label="单次输出 token 上限",
        why="留空 = 沿用 provider 默认；本地思考模型常需要显式设定",
        recommend="",
    ),
    # ── 路由池 ──
    WizardItem(
        key="ROUTING_POOLS",
        label="路由池 JSON",
        why="声明式路由池（键 = 条目名，值含 tiers / roles）；留空 = 不自动换档，规格见 .env.example 第 4 节",
    ),
    WizardItem(
        key="ROUTING_REASONING_CONTINUITY",
        label="推理链续接（继续走 pro 档）",
        why="true = 上一轮实际命中 pro 档就继续用它；默认 false = 每轮按当前请求重选（池内单池可覆盖）",
        kind=WizardKind.BOOL,
    ),
    # ── 迭代预算 ──
    WizardItem(
        key="MAX_ITERATIONS",
        label="单次运行最大迭代",
        why="一次 run 的 LLM ↔ 工具循环上限；无人值守的长任务才需要调高",
    ),
    WizardItem(
        key="SUBAGENT_MAX_ITERATIONS",
        label="子 Agent 迭代上限",
        why="task_delegate 子会话的兜底预算（优先级：显式参数 > 角色声明 > 本项）；与主循环上限分开算",
    ),
    # ── 上下文与压缩 ──
    WizardItem(
        key="MAX_CONTEXT_TOKENS",
        label="上下文窗口 token 数",
        why="压缩阈值按它折算；必须与模型真实窗口一致，否则压缩触发前先撞 API 400",
    ),
    WizardItem(
        key="COMPRESSION_THRESHOLD",
        label="压缩触发阈值（0–1）",
        why="上下文占用达到窗口的这个比例时开始摘要压缩",
    ),
    WizardItem(
        key="CONTEXT_STRATEGY",
        label="上下文管理策略",
        why="compressor = 原地摘要压缩；reset = 清窗后 resume 续跑（两种策略互斥）",
    ),
    WizardItem(
        key="TOKENIZER",
        label="token 计量方式",
        why="auto = 有 tiktoken 就用真实计量，否则启发式 + 在线校准；estimate = 强制启发式；tiktoken = 强制真实",
    ),
    WizardItem(
        key="CONTEXT_FILES_ENABLED",
        label="加载上下文文件",
        why="自动加载 .heagent/CONTEXT.md > AGENTS.md > CLAUDE.md",
        kind=WizardKind.BOOL,
    ),
    WizardItem(
        key="CONTEXT_FILES_MAX_BYTES",
        label="上下文文件字节预算",
        why="超预算按近端优先丢弃 / 截断并显式标注",
    ),
    # ── 记忆与技能 ──
    WizardItem(
        key="MEMORY_NUDGE_ENABLED",
        label="记忆注入",
        why="把 MEMORY.md 注入每轮上下文；关闭后记忆写入工具照常可用",
        kind=WizardKind.BOOL,
    ),
    WizardItem(
        key="MEMORY_INJECT_MAX_BYTES",
        label="记忆注入字节预算",
        why="注入的字节预算（0 = 不限）；超预算只保留最新后缀并在块尾标注省略数，MEMORY.md 本体不动",
    ),
    WizardItem(
        key="SKILL_MATCH_THRESHOLD",
        label="技能自动匹配阈值（0–1）",
        why="匹配分数低于阈值的技能不会被自动注入",
    ),
    WizardItem(
        key="SKILL_CURATOR_STALE_DAYS",
        label="技能陈旧判定天数",
        why="skill_curate 报「多久没被使用」的窗口；外部装入的技能恒为 0 次使用，别据此批量归档",
    ),
    # ── MCP 外部工具 ──
    WizardItem(
        key="MCP_ENABLED",
        label="启用 MCP 外部工具",
        why="true 才按 MCP_CONFIG_PATH 装配 MCP server；stdio 子进程在 docker 沙箱档下进同一镜像容器",
        kind=WizardKind.BOOL,
    ),
    WizardItem(
        key="MCP_CONFIG_PATH",
        label="MCP 配置文件路径",
        why="相对进程 cwd 的 .mcp.json；文件不存在 = 不装配（不报错）",
    ),
    # ── HTTP 入口 ──
    WizardItem(
        key="HTTP_ENABLED",
        label="启用 HTTP 入口",
        why="false = 不装配 HTTP listener；WS 是独立开关，仍按 WS_ENABLED 起停（CLI 另有 --no-http 单次覆盖）",
        kind=WizardKind.BOOL,
    ),
    WizardItem(
        key="HTTP_HOST",
        label="HTTP 绑定地址",
        why="HTTP 入口没有对外模式（无认证、无 TLS），只供本机 / 内网直连；对外暴露请走 WS 入口（LAN 模式或 token）",
    ),
    WizardItem(
        key="HTTP_PORT",
        label="HTTP 端口",
        why="被占用时在 HTTP_PORT_AUTO_FIND_ATTEMPTS 内顺延（日志打 Port N was in use）；显式 --port 冲突仍 fail-loud",
    ),
    WizardItem(
        key="HTTP_MAX_INFLIGHT_RUNS",
        label="每项目并发 run 上限",
        why="同一项目同时可提交的 run 数（超限的提交收 run_conflict）；控制台多标签并行时才调高",
    ),
    # ── WS 入口 ──
    WizardItem(
        key="WS_ENABLED",
        label="启用 WS 入口",
        why="false = 不装配 WS listener；HTTP 与 WS 是两个独立开关（CLI 另有 --no-ws 单次覆盖）",
        kind=WizardKind.BOOL,
    ),
    WizardItem(
        key="WS_HOST",
        label="WS 绑定地址",
        why="回环 = 本地模式（无认证）；非回环默认升格为对外模式（强制 Bearer token、缺 token 拒绝启动），"
        "配 WS_LAN_NO_AUTH=true + 私有 IPv4 则为内网免认证模式",
    ),
    WizardItem(
        key="WS_PORT",
        label="WS 端口",
        why="被占用时同 HTTP 口径顺延；实际监听地址以启动日志 ws event=started 为准",
    ),
    WizardItem(
        key="WS_LAN_NO_AUTH",
        label="内网免认证 WS 接入",
        why="true = 非回环绑定也不校验 token（内网调试入口，明文）；只接受私有地址字面量，"
        "不得与 WS_LOCAL_AUTH_ENABLED 同开；同网段任何设备都能驱使代理",
        kind=WizardKind.BOOL,
    ),
    WizardItem(
        key="WS_LOCAL_AUTH_ENABLED",
        label="本地 WS 也强制认证",
        why="true = 回环主 listener 也强制 Bearer token（含旁路 /api/cli/ws），本机消费者都要带 token",
        kind=WizardKind.BOOL,
    ),
    # ── 日志与事件 ──
    WizardItem(
        key="LOG_LEVEL",
        label="控制台日志级别",
        why="写到 stderr 的日志级别；排查问题临时用 DEBUG",
    ),
    WizardItem(
        key="EVENTS_ROLLOUT_ENABLED",
        label="事件落盘（rollout）",
        why="true = 每次 run 的事件写进 .heagent/runs/<run_id>/rollout.jsonl（含工具原始输出），排查 / 回放用",
        kind=WizardKind.BOOL,
    ),
    # ── 沙箱与执行后端（最后问：这一面最影响隔离姿态）──
    WizardItem(
        key="SANDBOX_BACKEND",
        label="沙箱后端",
        why="auto = 探到 firejail 才用、否则 passthrough（零隔离）；docker = OS 级兜底；winjob 须显式指定；"
        "以上都不是真正的安全边界",
        choices=("auto", "passthrough", "firejail", "winjob", "docker"),
    ),
    WizardItem(
        key="SANDBOX_DOCKER_IMAGE",
        label="沙箱镜像标签",
        why="docker 档用的镜像（构建见 docker/sandbox/Dockerfile）；换镜像 = 换工具链，不改隔离语义",
    ),
    WizardItem(
        key="SANDBOX_DOCKER_DIGEST",
        label="沙箱镜像 digest 钉住",
        why="非空时首个 run 前校验本地 tag 的 repo digest，不符显性拒绝（防 retag 换载荷）；留空 = 不钉",
    ),
)


def covered_keys() -> frozenset[str]:
    """向导覆盖的键（覆盖率的分子）。"""
    return frozenset(item.key for item in WIZARD_ITEMS)


def coverage() -> float:
    """常用项覆盖率 = |向导覆盖 ∩ 常用项| / |常用项|。"""
    return len(covered_keys() & frozenset(COMMON_KEYS)) / len(COMMON_KEYS)


# ── 取值辅助 ──


def _as_text(value: object) -> str:
    """把配置值渲染成写盘文本（布尔按 setting.md / pydantic 都认的 ``true`` / ``false``）。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _value_matches(intent: str, actual: object) -> bool:
    """写盘文本与生效值是否等价（数字按数值比，布尔按真值比，其余按字符串比）。"""
    if isinstance(actual, bool):
        return intent.strip().lower() in ({"true", "1", "yes"} if actual else {"false", "0", "no"})
    if isinstance(actual, int | float):
        try:
            return float(intent) == float(actual)
        except ValueError:
            return False
    return str(actual) == intent


def _annotation_has(key: str, kind: type) -> bool:
    """字段注解是否是 ``kind``（含 ``X | None`` 形态）。"""
    info = Settings.model_fields.get(key.lower())
    if info is None:
        return False
    annotation = info.annotation
    return annotation is kind or kind in getattr(annotation, "__args__", ())


def _field_default_text(key: str) -> str:
    """字段默认值的写盘文本（``None`` → 空串 = 不设置）。"""
    info = Settings.model_fields.get(key.lower())
    return "" if info is None else _as_text(info.default)


def _recommend(item: WizardItem) -> str:
    return item.recommend if item.recommend is not None else _field_default_text(item.key)


def _stdin_is_tty() -> bool:
    """stdin 是否是可交互终端（管道 / CI / CliRunner 都返回 False）。"""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):  # 某些被替换掉的 stdin 没有 isatty
        return False


# ── 输入规整与校验 ──


def _check_bounds(key: str, number: float, guard: ConfigGuard) -> None:
    minimum, maximum = guard.minimum, guard.maximum
    if minimum is not None and (number < minimum or (guard.exclusive_minimum and number == minimum)):
        raise _InvalidValue(f"{key} 需{'大于' if guard.exclusive_minimum else '不小于'} {minimum:g}")
    if maximum is not None and (number > maximum or (guard.exclusive_maximum and number == maximum)):
        raise _InvalidValue(f"{key} 需{'小于' if guard.exclusive_maximum else '不大于'} {maximum:g}")


def _normalize_number(key: str, text: str, guard: ConfigGuard) -> str:
    try:
        number = float(text)
    except ValueError as exc:
        raise _InvalidValue(f"{key} 需要一个数字，收到 {text!r}") from exc
    _check_bounds(key, number, guard)
    if _annotation_has(key, int):
        if not number.is_integer():
            raise _InvalidValue(f"{key} 需要整数，收到 {text!r}")
        return str(int(number))
    return str(number)


def _normalize(item: WizardItem, raw: object, guard: ConfigGuard | None) -> str:
    """把 prompt 的结果规整成可写盘文本；非法值抛 :class:`_InvalidValue`（当前项重问）。"""
    if item.kind is WizardKind.BOOL:
        return _as_text(bool(raw))
    text = str(raw).strip()
    if not text:
        return ""
    if guard is not None and guard.kind == "enum":
        # click.Choice 已挡掉非法取值；这里只做大小写归一（Choice 不区分大小写时返回原选项）。
        return text
    if guard is not None and guard.kind == "range":
        if guard.minimum is None and guard.maximum is None:
            # 只有长度约束（``*_HOST`` 这类 min_length 字段）：是文本项，别当数字解析。
            return text
        return _normalize_number(item.key, text, guard)
    return text


# ── 提示与提问 ──


def _current_text(item: WizardItem, current: ConfigItem | None) -> str:
    if current is None:
        return "（未知）"
    source = _SOURCE_LABELS[current.source]
    if item.kind is WizardKind.SECRET:
        return f"{'已配置（不回显）' if current.configured else '未配置'}（来源: {source}）"
    return f"{_as_text(current.value) or '（未设置）'}（来源: {source}）"


def _prompt_value(item: WizardItem, *, default: str, guard: ConfigGuard | None) -> str:
    """问一项并规整取值；非法输入就地重问（不终止向导）。"""
    if item.kind is WizardKind.SECRET:
        secret_input = click.prompt("    值（不回显；留空 = 不改动）", default="", hide_input=True, show_default=False)
        return str(secret_input).strip()
    # 值域来源：显式 choices 优先，否则用 catalog 的枚举守卫（两者都没有 = 自由文本）。
    values = item.choices or (guard.values if guard is not None and guard.kind == "enum" else ())
    choice = click.Choice(list(values), case_sensitive=False) if values else None
    while True:
        value: object
        if item.kind is WizardKind.BOOL:
            # click 会把 bool 默认值渲染成 ``[False]``；默认值已在上面的「当前 / 推荐」两行给出。
            value = click.prompt("    值 (true/false)", type=bool, default=default.strip().lower() == "true")
        elif choice is not None:
            value = click.prompt("    值", type=choice, default=default, show_default=True)
        else:
            value = click.prompt("    值", type=str, default=default, show_default=True)
        try:
            return _normalize(item, value, guard)
        except _InvalidValue as exc:
            click.echo(f"    × {exc}", err=True)


def _ask(item: WizardItem, *, position: int, total: int, current: ConfigItem | None) -> str:
    """展示一项的说明 / 当前值 / 推荐值，然后提问。"""
    recommend = _recommend(item)
    origin = "向导推荐" if item.recommend is not None else "字段默认值"
    click.echo("")
    click.echo(f"[{position}/{total}] {item.key} — {item.label}")
    click.echo(f"    说明: {item.why}")
    click.echo(f"    当前: {_current_text(item, current)}")
    click.echo(f"    推荐: {recommend or '（留空，不设置）'}（{origin}）")
    default = recommend if current is None or current.source is ConfigSource.DEFAULT else _as_text(current.value)
    if item.kind is WizardKind.SECRET:
        default = ""
    return _prompt_value(item, default=default, guard=guards_for(item.key))


def _collect(report: ConfigReport) -> tuple[dict[str, str], list[str], list[str]]:
    """逐项提问，返回 (要写入的键值, 与当前生效值相同的键, 被系统环境变量接管的键)。"""
    by_key = {entry.key: entry for entry in report.items}
    answers: dict[str, str] = {}
    unchanged: list[str] = []
    system_env: list[str] = []
    total = len(WIZARD_ITEMS)
    for position, item in enumerate(WIZARD_ITEMS, start=1):
        current = by_key.get(item.key)
        if current is not None and current.source is ConfigSource.SYSTEM_ENV:
            click.echo("")
            click.echo(f"[{position}/{total}] {item.key} — {item.label}")
            click.echo("    跳过: 当前值由系统环境变量提供，写入本文件不会生效（优先级更高）")
            system_env.append(item.key)
            continue
        value = _ask(item, position=position, total=total, current=current)
        if not value:
            unchanged.append(item.key)
            continue
        if item.kind is not WizardKind.SECRET and current is not None and _value_matches(value, current.value):
            unchanged.append(item.key)
            continue
        answers[item.key] = value
    return answers, unchanged, system_env


# ── 合并与验证 ──


def _trailing_comment(raw_value: str) -> str:
    """既有行里值后面的行内注释（无则空串），**逐字节**保留它前面的空白。

    判据与读侧同源：``parse_value`` 会把这段剥掉，因此「前缀单独解析 == 整行解析」的位置就是注释起点；
    引号里的 ``#`` 不满足该等式，不会被误判。
    """
    for position, char in enumerate(raw_value):
        if char != "#" or position == 0 or not raw_value[position - 1].isspace():
            continue
        if parse_value(raw_value[: position - 1]) != parse_value(raw_value):
            continue
        start = position - 1
        while start > 0 and raw_value[start - 1].isspace():
            start -= 1
        return raw_value[start:]
    return ""


def _render_value(key: str, value: str) -> str:
    """把值渲染成 frontmatter 行里的文本；无法保真表达则显性失败。"""
    check_key(key)
    if any(char in value for char in ("\r", "\n", "\x00")):
        raise WizardError(f"{key} 的值含控制字符，无法写入 setting.md", options=_REPAIR_OPTIONS)
    if value != value.strip():
        raise WizardError(f"{key} 的值首尾有空白，写入后会被读侧剥掉", options=_REPAIR_OPTIONS)
    if parse_value(value) == value:
        return value
    quoted = f'"{value}"'
    if parse_value(quoted) == value:
        return quoted
    raise WizardError(f"{key} 的值 {value!r} 无法在 setting.md 中保真表达", options=_REPAIR_OPTIONS)


def _frontmatter_bounds(lines: list[str]) -> tuple[int, int]:
    """既有文本的 frontmatter 起止行号（闭合 ``---`` 那行本身不含在内）。"""
    head = lines[0].lstrip("\ufeff") if lines else ""
    if head.strip() != "---":
        raise WizardError(
            "既有 setting.md 缺少 YAML frontmatter 头（首行须是 ---），无法安全合并",
            options=(
                "先手工补上 --- 头与结尾的 ---，或用 heagent init 重新生成模板骨架",
                "备份后删除该文件，再运行 heagent init --interactive 重新生成",
            ),
        )
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return 0, index
    raise WizardError(
        "既有 setting.md 的 frontmatter 没有闭合（缺少结尾的 ---）",
        options=("补上结尾的 --- 行", "备份后删除该文件，再运行 heagent init --interactive 重新生成"),
    )


def _merge_text(existing: str | None, intended: Mapping[str, str]) -> str:
    """把已确认的值合并进既有文本（只改命中行，注释 / 正文 / 行尾原样保留）。"""
    rendered = {key: _render_value(key, value) for key, value in intended.items()}
    if existing is None or not existing.strip():
        body = "\n".join(f"{key}: {value}" for key, value in rendered.items())
        return f"---\n{_FRESH_HEADER}{body}\n---\n{_FRESH_BODY}"
    lines = existing.split("\n")
    head, close = _frontmatter_bounds(lines)
    front = lines[head + 1 : close]
    terminator = "\r" if lines[close].endswith("\r") else ""
    positions: dict[str, int] = {}
    for line_number, line in enumerate(front):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        name = stripped.split(":", 1)[0].strip()
        if name:
            positions[name.lower()] = line_number
    appended: list[str] = []
    for key, value in rendered.items():
        position = positions.get(key.lower())
        if position is None:
            appended.append(f"{key}: {value}{terminator}")
            continue
        old_line = front[position]
        line_terminator = "\r" if old_line.endswith("\r") else ""
        content = old_line[: -len(line_terminator)] if line_terminator else old_line
        comment = _trailing_comment(content.split(":", 1)[1])
        front[position] = f"{key}: {value}{comment}{line_terminator}"
    return "\n".join([*lines[: head + 1], *front, *appended, *lines[close:]])


def _read_existing(path: Path) -> str | None:
    """读既有配置；不存在返回 ``None``，存在但不可解析则显性失败（不覆盖用户的坏文件）。"""
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8", newline="") as handle:  # newline="" 保住既有行尾（CRLF 不被翻译）
            text = handle.read()
        read_setting_md(path)
    except SettingsError as exc:
        raise WizardError(
            f"既有配置无法解析：{exc}",
            options=(
                "先手动修好该文件的 frontmatter（键值对写在两个 --- 之间）",
                "备份后删除该文件，再运行 heagent init --interactive 重新生成",
            ),
        ) from exc
    except OSError as exc:
        raise WizardError(f"无法读取既有配置 {path}：{exc}", options=_REPAIR_OPTIONS) from exc
    return text


def _verify_candidate(text: str, *, intended: Mapping[str, str], target: Path, project_env: Path) -> None:
    """三重校验候选内容；任何一步不通过都抛 :class:`WizardError`（此时目标文件还没被碰过）。

    候选落在独立临时目录（不污染 ``~/.heagent``），校验完即随目录一起删除。
    """
    with tempfile.TemporaryDirectory(prefix="heagent-init-") as tmp:
        candidate = Path(tmp) / target.name
        with candidate.open("w", encoding="utf-8", newline="") as handle:  # 逐字节写，不让行尾被翻译
            handle.write(text)
        try:
            parsed = read_setting_md(candidate)
        except SettingsError as exc:
            raise WizardError(f"生成的配置无法解析：{exc}", options=_REPAIR_OPTIONS) from exc
        for key, value in intended.items():
            if parsed.get(key.lower()) != value:
                raise WizardError(
                    f"生成的配置里 {key} 读回为 {parsed.get(key.lower())!r}，与写入值 {value!r} 不一致",
                    options=_REPAIR_OPTIONS,
                )
        # 只校验「系统环境变量 + 本文件」两层：项目 .env 的独立问题由 heagent doctor 报。
        try:
            with_user_setting_layer(candidate, Settings)(_env_file=None)
        except Exception as exc:  # noqa: BLE001 - 构造失败的种类很多，一律转成可读结论
            raise WizardError(
                f"生成的配置无法构造 Settings：{type(exc).__name__}: {exc}", options=_REPAIR_OPTIONS
            ) from exc
        report = build_config_report(project_env, global_setting_file=candidate)
        if "user_setting_unparseable" in report.notes:
            raise WizardError("生成的配置未被配置求解器接受（语法不可解析）", options=_REPAIR_OPTIONS)
        unknown = [entry.key for entry in report.unknown_keys if entry.source is ConfigSource.GLOBAL_SETTING]
        if unknown:
            raise WizardError(f"向导写入了配置目录之外的键：{', '.join(unknown)}", options=_REPAIR_OPTIONS)
        by_key = {entry.key: entry for entry in report.items}
        missing = [key for key in intended if by_key.get(key) is None or by_key[key].source is ConfigSource.DEFAULT]
        if missing:
            raise WizardError(f"这些键写入后未被配置求解器认作已提供：{', '.join(missing)}", options=_REPAIR_OPTIONS)


def _verify_written(target: Path, intended: Mapping[str, str]) -> None:
    """落盘后读回确认（I/O 异常或写入被外部改动时显性报错，不假装成功）。"""
    try:
        parsed = read_setting_md(target)
    except (SettingsError, OSError) as exc:
        raise WizardError(
            f"{target} 已写入但读回失败：{exc}",
            options=("检查该文件的编码与权限后重跑 heagent doctor", "从备份恢复该文件后重试"),
        ) from exc
    mismatched = [key for key, value in intended.items() if parsed.get(key.lower()) != value]
    if mismatched:
        raise WizardError(
            f"{target} 写入后读回不一致：{', '.join(mismatched)}",
            options=("确认没有别的进程同时改写该文件后重试", "从备份恢复该文件后重试"),
        )


# ── 主流程 ──


def _require_tty() -> None:
    """没有可交互终端就拒绝（不猜、不写盘）。"""
    if _stdin_is_tty():
        return
    raise WizardError(
        "heagent init --interactive 需要可交互终端；当前 stdin 不是 tty（管道 / CI），拒绝把默认值静默写盘",
        options=(
            "在交互式终端里重新运行 heagent init --interactive",
            "直接编辑 ~/.heagent/setting.md（KEY: value 写在 --- 之间），或用项目 .env / 系统环境变量",
            "跑 heagent init 生成模板骨架（非交互，不写具体值）",
        ),
    )


def require_interactive_terminal() -> None:
    """非 tty 时以「描述 + Try + Docs」退出。

    供调用方在**改动文件系统之前**先判终端（``heagent init --interactive`` 会先建目录、迁移旧文件，
    那些副作用不该发生在注定要拒绝的路径上）。
    """
    try:
        _require_tty()
    except WizardError as exc:
        exit_with_hints(str(exc), options=exc.options, anchor=ANCHOR_CLI_ERRORS)


def _run_wizard(*, target: Path, project_env: Path) -> WizardResult:
    _require_tty()
    try:
        report = build_config_report(project_env, global_setting_file=target)
    except Exception as exc:  # noqa: BLE001 - 求解失败（如系统环境变量非法）也要给可读结论
        raise WizardError(
            f"读取当前配置失败：{type(exc).__name__}: {exc}",
            options=("先跑 heagent doctor 定位坏掉的配置层", "检查系统环境变量里的数值型配置是否合法"),
        ) from exc
    existing = _read_existing(target)

    click.echo(f"[init] 交互式配置向导 → {target}")
    click.echo("      回车 = 接受中括号里的值；值与当前生效值相同时不会写入（避免把默认值固化成快照）。")
    answers, unchanged, system_env = _collect(report)
    if not answers:
        click.echo("")
        click.echo("[init] 没有需要写入的变更：所有项都与当前生效值相同。")
        return WizardResult(path=str(target), unchanged=tuple(unchanged), system_env=tuple(system_env), verified=False)

    text = _merge_text(existing, answers)
    _verify_candidate(text, intended=answers, target=target, project_env=project_env)
    before = snapshot_settings(target)
    write_setting_md(target, text)
    # 写后立即留痕（先于回读校验）：即使后续校验失败，落盘事实也必须可追证。
    record_settings_write(target=target, before=before)
    _verify_written(target, answers)

    click.echo("")
    secrets = {item.key for item in WIZARD_ITEMS if item.kind is WizardKind.SECRET}
    for key, value in answers.items():
        click.echo(f"[OK] {key}: {'***' if key in secrets else value}")
    click.echo(f"[OK] Verified: {target} 可被 Settings 解析（{len(answers)} 项）")
    click.echo("     下一步: heagent doctor 复核一致性")
    return WizardResult(
        path=str(target),
        written=tuple(answers),
        unchanged=tuple(unchanged),
        system_env=tuple(system_env),
        verified=True,
    )


def run_wizard(*, setting_file: Path | None = None, project_env_file: Path | None = None) -> WizardResult:
    """跑一遍交互式向导。

    Args:
        setting_file: 落盘目标，默认用户级 ``~/.heagent/setting.md``。
        project_env_file: 判定「当前生效值」用的项目 ``.env``，默认进程 cwd 下的 ``.env``。

    Returns:
        结果摘要（写入 / 未变 / 被环境变量接管的键）。

    Raises:
        click.ClickException: 非 tty、既有文件不可解析、验证未过等显性失败（带 ``Try:`` 与 ``Docs:``）。
    """
    target = Path(setting_file) if setting_file is not None else GLOBAL_SETTING_FILE
    project_env = Path(project_env_file) if project_env_file is not None else Path.cwd() / ".env"
    try:
        return _run_wizard(target=target.expanduser(), project_env=project_env)
    except WizardError as exc:
        exit_with_hints(str(exc), options=exc.options, anchor=ANCHOR_CLI_ERRORS)


__all__ = [
    "COMMON_KEY_GROUPS",
    "COMMON_KEYS",
    "MIN_COVERAGE",
    "WIZARD_ITEMS",
    "CommonKeyGroup",
    "WizardError",
    "WizardItem",
    "WizardKind",
    "WizardResult",
    "coverage",
    "covered_keys",
    "require_interactive_terminal",
    "run_wizard",
]
