"""错误场景 → 可直接执行的命令建议（声明式映射表 + 关键词匹配）。

与 ``cli/errors.py`` 的分工：``errors.py`` 负责**形状**（原消息 + ``Try:`` + ``Docs:``），本模块只
负责**内容**——某个错误场景下用户能直接粘贴执行的命令。两者在渲染处合流，互不反向依赖。

约定：
- 每条命令必须真实存在（CLI 子命令或斜杠命令）且**无占位符**，用户不必替换任何字符即可执行；
  ``tests/test_cli_suggestions.py`` 用代码反射逐条校验，命令表变了测试跟着变。
- 每个场景至少 :data:`MIN_SUGGESTIONS` 条——表级不变量在导入期校验，坏表当场抛错，不把「只有一条
  建议」的畸形块写给用户。
- 场景按 ``SCENARIOS`` 的**声明顺序**匹配，首个关键词命中的场景胜出；未命中走兜底场景。

分层：入口层模块，只依赖 ``pydantic`` 与 stdlib，不导入任何 heagent 运行栈符号。
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, ConfigDict

#: 每个场景的最少建议条数（票面 R11：≥2 条）。
MIN_SUGGESTIONS: Final = 2

#: 映射未命中时使用的场景 key。
FALLBACK_SCENARIO: Final = "unknown"


class CommandSuggestion(BaseModel):
    """一条可直接执行的命令建议。

    Attributes:
        command: 完整命令行（``heagent <sub> …`` 或 ``/<name> …``），可直接粘贴执行。
        when: 一句话说明这条命令用来做什么（渲染在命令后的 ``#`` 注释里）。
    """

    model_config = ConfigDict(frozen=True)

    command: str
    when: str


class ErrorScenario(BaseModel):
    """一类错误场景及其关键词与命令建议。

    Attributes:
        key: 场景标识（稳定，用于 ``suggest_commands(scenario=...)`` 显式指定）。
        label: 中文场景名（与 ``docs/errors.md`` 的「建议命令」表一一对应）。
        keywords: 短语级关键词；按边界感知正则匹配（``port`` 不命中 ``support``）。
        suggestions: 该场景的命令建议，长度 ≥ :data:`MIN_SUGGESTIONS`。
    """

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    keywords: tuple[str, ...]
    suggestions: tuple[CommandSuggestion, ...]


_DOCTOR = CommandSuggestion(command="heagent doctor", when="只读体检：逐项列出问题键与修法")

SCENARIOS: tuple[ErrorScenario, ...] = (
    ErrorScenario(
        key="credentials",
        label="凭据缺失",
        keywords=(
            "api key",
            "api_key",
            "api keys",
            "credential",
            "no key configured",
            "authentication failed",
            "auth_failed",
            "unauthorized",
            "401",
        ),
        suggestions=(
            CommandSuggestion(
                command="heagent init --interactive",
                when="交互式逐项写入凭据与常用配置（写 ~/.heagent/setting.md）",
            ),
            _DOCTOR,
            CommandSuggestion(command="/provider", when="切到一个已配好凭据的 provider"),
        ),
    ),
    ErrorScenario(
        key="ws_token",
        label="WS 对外缺 token",
        keywords=(
            "ws_auth_token",
            "bearer token",
            "auth-enforcing",
            "auth token",
            "token required",
            "requires token",
            "ws_local_auth_enabled",
        ),
        suggestions=(
            # 不能建议 `--no-ws`：启动校验作用于 `Settings`，早于本进程的 --no-ws 覆盖生效，
            # 该选项在当前实现下**不**能绕过这道 fail-closed（建议必须可直接执行且真的有效）。
            CommandSuggestion(
                command="heagent init", when="生成/补齐 ~/.heagent/setting.md 模板，按注释填 WS_AUTH_TOKEN"
            ),
            _DOCTOR,
        ),
    ),
    ErrorScenario(
        key="port",
        label="端口占用 / 绑定失败",
        keywords=(
            "port",
            "--port",
            "--ws-port",
            "bind",
            "address already in use",
            "address unavailable",
            "eaddrinuse",
            "eacces",
        ),
        suggestions=(
            CommandSuggestion(
                command="heagent http-server --port 9102",
                when="换一个 HTTP 端口（默认 9101 被占或不可绑时）",
            ),
            CommandSuggestion(
                command="heagent http-server --ws-port 9202",
                when="WS 端口同样顺延一位（默认 9201）",
            ),
            _DOCTOR,
        ),
    ),
    ErrorScenario(
        key="sandbox",
        label="沙箱后端不可用",
        keywords=("sandbox", "firejail", "docker", "winjob", "bubblewrap", "sandbox_backend"),
        suggestions=(
            CommandSuggestion(
                command='heagent run --sandbox passthrough "hi"',
                when="显式接受零隔离，先让这一轮跑通",
            ),
            CommandSuggestion(
                command='heagent run --sandbox docker "hi"',
                when="容器沙箱可用时改用 docker 后端",
            ),
            _DOCTOR,
        ),
    ),
    ErrorScenario(
        key="mcp",
        label="MCP 配置 / 连接失败",
        keywords=("mcp", ".mcp.json", "mcp_config_path", "mcp-server", "stdio server"),
        suggestions=(
            _DOCTOR,
            CommandSuggestion(command="/mcp-prompt", when="列出已连上的 MCP server 与其 prompt"),
        ),
    ),
    ErrorScenario(
        key="skill",
        label="技能 / 工作流包不可用",
        keywords=("skill", "workflow role", "workflow package", "canonical_id", "frontmatter"),
        suggestions=(
            CommandSuggestion(command="/goal doctor", when="预检工作流与角色技能包是否存在"),
            _DOCTOR,
            CommandSuggestion(command="/help", when="查看当前实际可用的斜杠命令"),
        ),
    ),
    ErrorScenario(
        key="cron",
        label="定时任务失败",
        keywords=("cron", "job store", "scheduled job", "schedule"),
        suggestions=(
            CommandSuggestion(command="heagent cron list", when="查看已注册的定时任务与状态"),
            _DOCTOR,
        ),
    ),
    ErrorScenario(
        key="session",
        label="会话 id 非法 / 会话缺失",
        keywords=("session", "--resume", "rollout", "replay"),
        suggestions=(
            CommandSuggestion(command="/clear", when="丢掉当前会话，下一条消息从新会话开始"),
            CommandSuggestion(command='heagent run "hi"', when="不带 --resume 起一个新会话"),
        ),
    ),
    ErrorScenario(
        key="provider",
        label="provider 未配置 / 切换失败",
        keywords=("provider", "routing pool", "routing_pools", "not supported by any configured account"),
        suggestions=(
            CommandSuggestion(command="/provider", when="列出 provider 池并切换生效项"),
            CommandSuggestion(command="/model auto", when="清掉强制档位，回到自动路由"),
            _DOCTOR,
        ),
    ),
    ErrorScenario(
        key="config_invalid",
        label="配置键非法",
        keywords=(
            "invalid value",
            "cannot parse",
            "unknown key",
            "validationerror",
            "could not be loaded",
            ".env",
            "config",
        ),
        suggestions=(
            _DOCTOR,
            CommandSuggestion(
                command="heagent init --interactive",
                when="交互式重写配置，逐项校验后再原子落盘",
            ),
        ),
    ),
)


def _compile_keyword(keyword: str) -> re.Pattern[str]:
    """把关键词编译成「边界感知」的大小写不敏感正则。

    边界只加在关键词首/尾是字母数字的一侧：``port`` 因此不会命中 ``support`` / ``reports``，而
    ``.mcp.json`` 这类以标点结尾的关键词照常按字面匹配。
    """
    body = re.escape(keyword)
    if keyword[:1].isalnum():
        body = rf"(?<![0-9a-z_]){body}"
    if keyword[-1:].isalnum():
        body = rf"{body}(?![0-9a-z_])"
    return re.compile(body, re.IGNORECASE)


_KEYWORD_PATTERNS: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    scenario.key: tuple(_compile_keyword(keyword) for keyword in scenario.keywords) for scenario in SCENARIOS
}

_SCENARIO_BY_KEY: Final[dict[str, ErrorScenario]] = {scenario.key: scenario for scenario in SCENARIOS}

FALLBACK_SUGGESTIONS: Final[tuple[CommandSuggestion, ...]] = (
    _DOCTOR,
    CommandSuggestion(command="/help", when="列出全部斜杠命令，找对应的入口"),
)


def _validate_table() -> None:
    """表级不变量：导入期炸掉比给用户畸形建议块好。

    Raises:
        RuntimeError: 场景 key 重复/为空、关键词为空、建议条数 < :data:`MIN_SUGGESTIONS`、
            或建议条目的命令为空。
    """
    seen: set[str] = set()
    for scenario in SCENARIOS:
        if not scenario.key or scenario.key in seen:
            raise RuntimeError(f"error scenario key is empty or duplicated: {scenario.key!r}")
        seen.add(scenario.key)
        if not scenario.keywords:
            raise RuntimeError(f"error scenario {scenario.key!r} has no keywords")
        if len(scenario.suggestions) < MIN_SUGGESTIONS:
            raise RuntimeError(
                f"error scenario {scenario.key!r} has {len(scenario.suggestions)} suggestion(s), "
                f"at least {MIN_SUGGESTIONS} required"
            )
        for item in scenario.suggestions:
            if not item.command.strip() or not item.when.strip():
                raise RuntimeError(f"error scenario {scenario.key!r} has an empty suggestion field")
    if len(FALLBACK_SUGGESTIONS) < MIN_SUGGESTIONS:
        raise RuntimeError("fallback suggestions must hold at least two commands")


_validate_table()


def detect_scenario(message: str) -> str:
    """按表序返回首个关键词命中的场景 key；未命中返回 :data:`FALLBACK_SCENARIO`。

    顺序即优先级：更具体的场景（凭据、WS token）写在前面，泛化的 ``config`` 写在最后，避免
    「No API key configured for provider X」被 provider 场景截走。
    """
    for scenario in SCENARIOS:
        if any(pattern.search(message) for pattern in _KEYWORD_PATTERNS[scenario.key]):
            return scenario.key
    return FALLBACK_SCENARIO


def suggest_commands(message: str = "", *, scenario: str | None = None) -> tuple[CommandSuggestion, ...]:
    """返回该错误对应的命令建议（长度恒 ≥ :data:`MIN_SUGGESTIONS`）。

    Args:
        message: 错误文本（纯文本，可含换行）；仅在 ``scenario`` 为空时用于推断场景。
        scenario: 显式场景 key；为空时按 ``message`` 推断。

    Returns:
        命令建议元组。

    Raises:
        KeyError: ``scenario`` 不是已声明的场景 key（拼错要显性失败，不静默给兜底）。
    """
    key = scenario if scenario is not None else detect_scenario(message)
    if key == FALLBACK_SCENARIO:
        return FALLBACK_SUGGESTIONS
    if key not in _SCENARIO_BY_KEY:
        raise KeyError(f"unknown error scenario {key!r}; known: {', '.join(sorted(_SCENARIO_BY_KEY))}")
    return _SCENARIO_BY_KEY[key].suggestions


def scenario_labels() -> dict[str, str]:
    """返回 ``场景 key → 中文场景名``（文档一致性测试用，避免测试手抄一份表）。"""
    labels = {scenario.key: scenario.label for scenario in SCENARIOS}
    labels[FALLBACK_SCENARIO] = "未识别场景"
    return labels


__all__ = [
    "FALLBACK_SCENARIO",
    "FALLBACK_SUGGESTIONS",
    "MIN_SUGGESTIONS",
    "SCENARIOS",
    "CommandSuggestion",
    "ErrorScenario",
    "detect_scenario",
    "scenario_labels",
    "suggest_commands",
]
