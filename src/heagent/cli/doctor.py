"""``heagent doctor``：配置诊断。

只读命令：检查「结构性不一致」——缺凭据、键名/取值对不上、端口被占、WS 对外模式缺前置条件等。
**不**调用上游 Provider、**不**写任何文件、**不**改配置，因此可以在任何时刻安全运行。

严重度三档：
  - ``error``：按当前配置服务必然起不来或跑不通；
  - ``warning``：能起来但行为会与预期不符；
  - ``info``：值得知道，不一定是问题。

有 ``error`` 时退出码 1（便于 CI / 脚本消费），否则 0。

分层：入口层（``heagent/cli/``），只读 ``config`` / ``skills`` / ``tools`` 的**公开**能力；
``.env`` 的行级诊断复用 ``config.catalog`` 的求解器，不另写一套解析。
"""

from __future__ import annotations

import json
import logging
import os
import socket
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import click
from pydantic import BaseModel

from heagent.config import GLOBAL_SETTING_FILE, Settings, get_settings
from heagent.config.catalog import build_config_report
from heagent.network.exposure import is_loopback_host
from heagent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from heagent.config.catalog import ConfigReport


class Severity(StrEnum):
    """finding 的严重度；``ERROR`` 决定进程退出码。"""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Finding(BaseModel):
    """一条诊断结论。``code`` 是稳定判据（脚本按它匹配），``message``/``fix`` 给人读。"""

    code: str
    severity: Severity
    message: str
    fix: str


#: provider 条目名（与 ``providers/composition.py`` 的 ``named`` 键一致）。
KNOWN_ENTRIES: tuple[str, ...] = ("deepseek", "claude", "openai", "kimi", "glm", "ollama")

#: 各条目判「已配置」的依据。
_ENTRY_CREDENTIAL_FIELDS: dict[str, tuple[str, ...]] = {
    "deepseek": ("deepseek_api_key",),
    "claude": ("anthropic_api_key", "anthropic_api_keys"),
    "openai": ("openai_responses_api_key",),
    "kimi": ("kimi_api_key",),
    "glm": ("glm_api_key",),
    "ollama": ("ollama_enabled",),
}


#: 每条目在 fix 文案里点名的键（与 ``_ENTRY_CREDENTIAL_FIELDS`` 同源，缺一个就补一个）。
_ENTRY_HINT_KEY: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_RESPONSES_API_KEY",
    "kimi": "KIMI_API_KEY",
    "glm": "GLM_API_KEY",
    "ollama": "OLLAMA_ENABLED",
}


def _configured_entries(settings: Settings) -> set[str]:
    """当前凭据可支撑的 provider 条目。"""
    entries: set[str] = set()
    for entry, fields in _ENTRY_CREDENTIAL_FIELDS.items():
        for field in fields:
            value = getattr(settings, field, None)
            if value:
                entries.add(entry)
                break
    return entries


def _port_in_use(host: str, port: int, *, timeout: float = 0.2) -> bool:
    """本机端口是否已被监听（连得上即视为占用）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _routing_pool_entries(settings: Settings) -> tuple[set[str], list[str]]:
    """解析 ``ROUTING_POOLS``：返回 (池声明的条目集合, 解析问题列表)。"""
    raw = (settings.routing_pools or "").strip()
    if not raw:
        return set(), []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return set(), [f"ROUTING_POOLS is not valid JSON: {exc.msg} (line {exc.lineno})"]
    if not isinstance(parsed, dict):
        return set(), ["ROUTING_POOLS must be a JSON object keyed by provider entry name"]
    unknown = [name for name in parsed if name not in KNOWN_ENTRIES]
    problems = [f"ROUTING_POOLS declares unknown provider entry {name!r}" for name in unknown]
    return {name for name in parsed if name in KNOWN_ENTRIES}, problems


def _check_credentials(settings: Settings) -> list[Finding]:
    entries = _configured_entries(settings)
    if entries:
        return []
    return [
        Finding(
            code="doctor.no_credentials",
            severity=Severity.ERROR,
            message="No provider credential is configured; every run will fail at startup.",
            fix=(
                "set one of DEEPSEEK_API_KEY / KIMI_API_KEY / GLM_API_KEY / OPENAI_RESPONSES_API_KEY / "
                "ANTHROPIC_API_KEY in .env, or enable the local model (OLLAMA_ENABLED=true + OLLAMA_MODEL); "
                "OPENAI_API_KEY alone no longer builds a provider entry"
            ),
        )
    ]


def _check_ollama(settings: Settings) -> list[Finding]:
    if settings.ollama_enabled and not settings.ollama_model:
        return [
            Finding(
                code="doctor.ollama_model_missing",
                severity=Severity.ERROR,
                message="OLLAMA_ENABLED=true but OLLAMA_MODEL is empty; startup aborts.",
                fix="set OLLAMA_MODEL=<name> (list local models: curl http://127.0.0.1:11434/api/tags)",
            )
        ]
    return []


def _check_token_limits(settings: Settings) -> list[Finding]:
    output = settings.max_output_tokens
    if output is not None and output >= settings.max_context_tokens:
        return [
            Finding(
                code="doctor.token_limits_inverted",
                severity=Severity.WARNING,
                message=(
                    f"MAX_OUTPUT_TOKENS ({output}) is not smaller than MAX_CONTEXT_TOKENS "
                    f"({settings.max_context_tokens}); the model cannot honour it."
                ),
                fix="lower MAX_OUTPUT_TOKENS, or raise MAX_CONTEXT_TOKENS to the model's real window",
            )
        ]
    return []


def _check_active_provider(settings: Settings) -> list[Finding]:
    active = (settings.active_provider or "").strip().lower()
    if not active:
        return []
    if active not in KNOWN_ENTRIES:
        return [
            Finding(
                code="doctor.active_provider_unknown",
                severity=Severity.WARNING,
                message=(
                    f"ACTIVE_PROVIDER={active!r} is not a known entry; startup falls back to the first available one."
                ),
                fix=f"use one of: {', '.join(KNOWN_ENTRIES)}",
            )
        ]
    if active not in _configured_entries(settings):
        return [
            Finding(
                code="doctor.active_provider_without_credentials",
                severity=Severity.ERROR,
                message=(
                    f"ACTIVE_PROVIDER={active!r} is selected but has no credentials; startup aborts with "
                    "`No API key configured`."
                ),
                fix=f"set {_ENTRY_HINT_KEY[active]}, or point ACTIVE_PROVIDER at a configured entry",
            )
        ]
    return []


def _check_routing_pools(settings: Settings) -> list[Finding]:
    declared, problems = _routing_pool_entries(settings)
    findings = [
        Finding(
            code="doctor.routing_pools_invalid",
            severity=Severity.WARNING,
            message=problem,
            fix="fix ROUTING_POOLS (see .env.example section 4); invalid pools are silently skipped",
        )
        for problem in problems
    ]
    configured = _configured_entries(settings)
    for entry in sorted(declared - configured):
        findings.append(
            Finding(
                code="doctor.routing_pool_without_credentials",
                severity=Severity.WARNING,
                message=f"ROUTING_POOLS declares a pool for {entry!r} but that entry has no credentials; the pool is skipped.",
                fix=(
                    f"set {_ENTRY_HINT_KEY.get(entry, 'the credential')} for that entry, "
                    "or remove the pool from ROUTING_POOLS"
                ),
            )
        )
    return findings


def _check_env_file(report: ConfigReport) -> list[Finding]:
    findings: list[Finding] = []
    env = report.env_file
    if not env.exists:
        findings.append(
            Finding(
                code="doctor.env_missing",
                severity=Severity.INFO,
                message=f"No project .env at {env.path}; only defaults and the user-level setting file apply.",
                fix="create one with `cp .env.example .env` if this project is meant to have its own config",
            )
        )
        return findings
    if env.has_bom:
        findings.append(
            Finding(
                code="doctor.env_bom",
                severity=Severity.INFO,
                message=f"{env.path} starts with a UTF-8 BOM; keys may be misread.",
                fix="re-save the file as UTF-8 without BOM",
            )
        )
    if env.duplicate_keys:
        findings.append(
            Finding(
                code="doctor.env_duplicate_keys",
                severity=Severity.WARNING,
                message=f"Duplicate keys in {env.path}: {', '.join(env.duplicate_keys)} (the last one wins).",
                fix="delete the redundant lines so the effective value is unambiguous",
            )
        )
    if env.blank_keys:
        findings.append(
            Finding(
                code="doctor.env_blank_value",
                severity=Severity.WARNING,
                message=f"Blank values in {env.path}: {', '.join(env.blank_keys)} (parsed as empty, may override defaults).",
                fix="comment the line out (prefix with #) instead of leaving `KEY=`",
            )
        )
    if report.unknown_keys:
        names = ", ".join(item.key for item in report.unknown_keys)
        findings.append(
            Finding(
                code="doctor.env_unknown_keys",
                severity=Severity.WARNING,
                message=f"Keys that match no setting (ignored): {names}.",
                fix="fix the spelling, or remove them (see .env.example for the full key list)",
            )
        )
    return findings


def _check_ws(settings: Settings) -> list[Finding]:
    findings: list[Finding] = []
    if not settings.ws_enabled:
        # 没有任何 WS listener：token / TLS / 绑定地址都无从生效，检查它们只会制造噪声。
        return findings
    token = settings.user_ws_auth_token
    main_external = not is_loopback_host(settings.ws_host)
    if main_external and not token:
        findings.append(
            Finding(
                code="doctor.ws_main_external_without_token",
                severity=Severity.ERROR,
                message=(
                    f"WS_HOST={settings.ws_host!r} is not loopback, so the listener runs in external mode, "
                    "but WS_AUTH_TOKEN is not set; startup is refused."
                ),
                fix=(
                    "add a WS_AUTH_TOKEN entry to the user-level setting file, "
                    "or set WS_HOST=127.0.0.1 to stay in local mode"
                ),
            )
        )
    external_host = (settings.ws_external_host or "").strip()
    if external_host:
        if is_loopback_host(external_host):
            findings.append(
                Finding(
                    code="doctor.ws_external_host_loopback",
                    severity=Severity.ERROR,
                    message=f"WS_EXTERNAL_HOST={external_host!r} is loopback; the external listener refuses to start.",
                    fix="use a non-loopback address (e.g. the LAN IP), or unset WS_EXTERNAL_HOST",
                )
            )
        if main_external:
            findings.append(
                Finding(
                    code="doctor.ws_external_host_conflict",
                    severity=Severity.ERROR,
                    message="Both WS_HOST and WS_EXTERNAL_HOST are non-loopback; only one external listener is allowed.",
                    fix="keep WS_HOST on 127.0.0.1 and use WS_EXTERNAL_HOST for the exposed listener",
                )
            )
        if not token:
            findings.append(
                Finding(
                    code="doctor.ws_external_listener_without_token",
                    severity=Severity.ERROR,
                    message=(
                        "WS_EXTERNAL_HOST is set (external listener) but WS_AUTH_TOKEN is missing; startup is refused."
                    ),
                    fix="add a WS_AUTH_TOKEN entry to the user-level setting file",
                )
            )
    if settings.ws_local_auth_enabled and not token:
        findings.append(
            Finding(
                code="doctor.ws_local_auth_without_token",
                severity=Severity.ERROR,
                message=(
                    "WS_LOCAL_AUTH_ENABLED=true requires WS_AUTH_TOKEN even on a loopback listener; startup is refused."
                ),
                fix=("add a WS_AUTH_TOKEN entry to the user-level setting file, or set WS_LOCAL_AUTH_ENABLED=false"),
            )
        )
    for label, cert, key in (
        ("WS_TLS", settings.ws_tls_cert_file, settings.ws_tls_key_file),
        ("WS_EXTERNAL_TLS", settings.ws_external_tls_cert_file, settings.ws_external_tls_key_file),
    ):
        if bool(cert) != bool(key):
            findings.append(
                Finding(
                    code="doctor.ws_tls_half_configured",
                    severity=Severity.ERROR,
                    message=f"{label} has only one of cert/key; startup is refused rather than serving plaintext.",
                    fix=f"set both {label}_CERT_FILE and {label}_KEY_FILE, or neither",
                )
            )
    return findings


def _check_ports(settings: Settings) -> list[Finding]:
    findings: list[Finding] = []
    candidates: list[tuple[str, str, int]] = []
    if settings.http_enabled:
        candidates.append(("HTTP_PORT", "HTTP listener", settings.http_port))
    if settings.ws_enabled:
        candidates.append(("WS_PORT", "WS listener", settings.ws_port))
        if (settings.ws_external_host or "").strip():
            candidates.append(("WS_EXTERNAL_PORT", "external WS listener", settings.ws_external_port))
    for key, label, port in candidates:
        if _port_in_use("127.0.0.1", port):
            findings.append(
                Finding(
                    code="doctor.port_in_use",
                    severity=Severity.INFO,
                    message=(
                        f"{key}={port} already accepts connections on 127.0.0.1 ({label}); "
                        "this may be a heagent instance you just started."
                    ),
                    fix=(
                        "only a problem if a second instance is meant to start here: "
                        "leave --port unset so auto-find can shift it, or pick another port"
                    ),
                )
            )
    return findings


def _check_tools(settings: Settings, registered: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    unknown = [name for name in settings.approval_tool_list if name and name not in registered]
    if unknown:
        findings.append(
            Finding(
                code="doctor.approval_tools_unknown",
                severity=Severity.WARNING,
                message=f"APPROVAL_TOOLS lists tools that are not registered: {', '.join(unknown)}.",
                fix="fix the names to match registered tools (see the tool list in docs/frame.md), or remove them",
            )
        )
    if "shell" in settings.safety_blocked_tools:
        findings.append(
            Finding(
                code="doctor.safety_blocks_shell",
                severity=Severity.WARNING,
                message="SAFETY_BLOCKED_TOOLS blocks `shell`; every shell call will be refused before execution.",
                fix="remove `shell` from SAFETY_BLOCKED_TOOLS unless that is intentional",
            )
        )
    return findings


def _docker_daemon_endpoint() -> str | None:
    """尽力判断 docker daemon 端点；判不出返回 ``None``。

    只覆盖三种最常见形态（``DOCKER_HOST`` / unix socket / 2375）；Windows 命名管道与 Docker Desktop
    的私有 socket 不在其中——因此判不出时**只给 info**，不当成故障。
    """
    docker_host = os.environ.get("DOCKER_HOST", "").strip()
    if docker_host:
        return docker_host
    if Path("/var/run/docker.sock").exists():
        return "/var/run/docker.sock"
    if _port_in_use("127.0.0.1", 2375):
        return "tcp://127.0.0.1:2375"
    return None


def _check_sandbox(settings: Settings) -> list[Finding]:
    backend = settings.sandbox_backend.strip().lower()
    if backend != "docker":
        return []
    if _docker_daemon_endpoint() is None:
        return [
            Finding(
                code="doctor.docker_backend_unavailable",
                severity=Severity.INFO,
                message=(
                    "SANDBOX_BACKEND=docker but no daemon endpoint was found at DOCKER_HOST / "
                    "/var/run/docker.sock / 127.0.0.1:2375; the backend degrades to host execution with a "
                    "WARNING per call. Windows named pipes are not probed."
                ),
                fix=(
                    "start Docker Desktop / the daemon, or set SANDBOX_BACKEND=auto/passthrough "
                    "to make the choice explicit"
                ),
            )
        ]
    return []


def _check_skills() -> list[Finding]:
    """技能双根同名冲突（全局根生效、项目根被遮蔽）。"""
    from heagent.skills.skill_store import SkillStore, default_skill_roots  # noqa: PLC0415

    store = SkillStore(default_skill_roots(Path.cwd()))
    conflicts = store.conflicts()
    if not conflicts:
        return []
    pairs = ", ".join(f"{item.name} (from {item.effective_root})" for item in conflicts)
    return [
        Finding(
            code="doctor.skill_name_conflict",
            severity=Severity.WARNING,
            message=f"Same skill name exists in both roots: {pairs}.",
            fix=(
                "rename one of them, or delete the shadowed copy under .heagent/skills "
                "(same-name skills resolve global-first)"
            ),
        )
    ]


def run_checks(settings: Settings, report: ConfigReport, *, registered_tools: set[str]) -> list[Finding]:
    """跑全部检查。每项独立 try/except：单项崩了只记 info，不影响其余。"""
    checks: tuple[tuple[str, Callable[[], list[Finding]]], ...] = (
        ("credentials", lambda: _check_credentials(settings)),
        ("ollama", lambda: _check_ollama(settings)),
        ("token_limits", lambda: _check_token_limits(settings)),
        ("active_provider", lambda: _check_active_provider(settings)),
        ("routing_pools", lambda: _check_routing_pools(settings)),
        ("env_file", lambda: _check_env_file(report)),
        ("ws", lambda: _check_ws(settings)),
        ("ports", lambda: _check_ports(settings)),
        ("tools", lambda: _check_tools(settings, registered_tools)),
        ("sandbox", lambda: _check_sandbox(settings)),
        ("skills", _check_skills),
    )
    findings: list[Finding] = []
    for name, check in checks:
        try:
            findings.extend(check())
        except Exception as exc:  # noqa: BLE001 - 单项检查失败不能拖垮整个 doctor
            logger.warning("doctor check %r crashed", name, exc_info=True)
            findings.append(
                Finding(
                    code="doctor.check_crashed",
                    severity=Severity.WARNING,
                    message=f"Check {name!r} crashed: {type(exc).__name__}: {exc}",
                    fix="re-run with LOG_LEVEL=DEBUG and report it if it persists (docs/errors.md)",
                )
            )
    order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    return sorted(findings, key=lambda item: (order[item.severity], item.code))


def _render(findings: list[Finding]) -> None:
    """人读输出走 stderr（与其它 CLI 诊断一致）；`--json` 仍走 stdout 供脚本消费。"""
    if not findings:
        click.echo("[doctor] no problems found", err=True)
        return
    for item in findings:
        click.echo(f"[{item.severity.value}] {item.code}: {item.message}", err=True)
        click.echo(f"    fix: {item.fix}", err=True)


@click.command("doctor")
@click.option("--json", "as_json", is_flag=True, default=False, help="Emit findings as a JSON array")
def doctor_cmd(as_json: bool) -> None:
    """检查配置的一致性（只读；不调用模型、不写文件）。"""
    import heagent.tools.builtins  # noqa: F401, PLC0415 - 注册内置工具，APPROVAL_TOOLS 才能校验

    # doctor 按「当前工作目录的项目」判读；与 CLI 的启动口径一致（README：在仓库根启动）。
    # 多项目控制台下项目根 ≠ 进程 cwd——那种场景请先 cd 到项目根再跑 doctor。
    env_file = Path.cwd() / ".env"
    try:
        settings = get_settings()
        report = build_config_report(env_file, global_setting_file=GLOBAL_SETTING_FILE)
    except Exception as exc:  # noqa: BLE001 - Settings 校验或求解失败时也要给出可读结论
        findings = [
            Finding(
                code="doctor.settings_unreadable",
                severity=Severity.ERROR,
                message=f"Configuration could not be solved: {type(exc).__name__}: {exc}",
                fix="fix the reported file first, then re-run; see docs/errors.md section 3 (CLI 与启动期错误)",
            )
        ]
    else:
        findings = run_checks(settings, report, registered_tools=set(ToolRegistry.get().list_names()))

    if as_json:
        click.echo(json.dumps([item.model_dump(mode="json") for item in findings], ensure_ascii=False))
    else:
        _render(findings)
    raise SystemExit(1 if any(item.severity is Severity.ERROR for item in findings) else 0)
