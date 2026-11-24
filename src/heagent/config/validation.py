"""启动期必需配置验证（Story 64.7）——只判「不满足就一定跑不起来」的项。

**与 ``heagent doctor`` 的分工**（刻意不重叠）：

- ``doctor`` = 全量结构体检（含 ``.env`` 行级诊断、端口探测、技能双根冲突），给人手动跑，warning 可容忍；
- 本模块 = 极简、每次启动自动跑，只收**结构性阻断**，预算 <100ms。

判据因此只允许 ``Settings`` 构造结果 + 纯内存读取：**不**做 socket 探测、**不**起子进程、**不**联网。

失败即显性失败：本模块只产出结构化 :class:`StartupValidationResult`；渲染成「描述 + Try + Docs」并
以退出码 1 结束由入口层（:func:`heagent.cli.wiring.ensure_startup_config`）负责——config 层不得 import
``cli``。同理，判据里的回环判定内联了一份纯 stdlib 等价实现：唯一权威实现在
:func:`heagent.network.exposure.is_loopback_host`，但 ``config/`` 不得依赖 ``network/``，两处等价性由
``tests/test_config_validation.py`` 交叉断言钉住。

覆盖率口径（票面 verify「覆盖 >90% 必需配置项」）：
分母 = :data:`REQUIRED_SETTING_KEYS`（独立策展、逐键附「为何必需」），分子 =
各检查 ``covers`` 的并集与分母的交集（:func:`required_coverage`）。检查被删除或忘记登记键都会把比例
打下来——是可漂移的红灯，不是同义反复。
"""

from __future__ import annotations

import ipaddress
import re
import time
from collections.abc import Callable  # noqa: TC003 - pydantic 在类创建期解析注解，运行期需真实对象

from pydantic import BaseModel, ConfigDict

from heagent.config import Settings

#: 视为「必需」的 ``Settings`` 字段全集 = 覆盖率**分母**。
#: 收入标准唯一：该键取值不满足时，进程一定在 provider 装配或 listener 装配处失败。
REQUIRED_SETTING_KEYS: frozenset[str] = frozenset(
    {
        # provider 面：没有任何可用凭据 → composition 直接拒绝装配（含 ollama 缺模型）
        "deepseek_api_key",
        "anthropic_api_key",
        "anthropic_api_keys",
        "kimi_api_key",
        "glm_api_key",
        "openai_responses_api_key",
        "ollama_enabled",
        "ollama_model",
        # WS 面：认证 / 绑定 / TLS 三条 fail-closed 判据挂在 WsServerConfig 的 model_validator 上
        "ws_enabled",
        "ws_host",
        "ws_local_auth_enabled",
        "ws_lan_no_auth",
        "ws_tls_cert_file",
        "ws_tls_key_file",
        # 沙箱面：SANDBOX_BACKEND=docker 时镜像引用是每条命令的输入
        "sandbox_backend",
        "sandbox_docker_image",
        "sandbox_docker_digest",
    }
)

#: 计入「已配置 provider」的凭据字段（与 ``providers/composition.py`` 的条目守卫同源）。
_CREDENTIAL_FIELDS: tuple[str, ...] = (
    "deepseek_api_key",
    "anthropic_api_key",
    "anthropic_api_keys",
    "kimi_api_key",
    "glm_api_key",
    "openai_responses_api_key",
)

#: 零凭据的文案**逐字**复用 ``providers/composition.py`` 的同一条消息：它既是用户熟悉的原文，也被
#: 既有终端断言（``No API key configured``）钉住。两面同文案由
#: ``tests/test_config_validation.py::test_credentials_message_matches_composition_contract`` 反向钉死。
NO_CREDENTIALS_MESSAGE = (
    "Error: No API key configured. Set DEEPSEEK_API_KEY, KIMI_API_KEY, "
    "GLM_API_KEY, OPENAI_RESPONSES_API_KEY or ANTHROPIC_API_KEY "
    "in environment, or enable the local Ollama entry with OLLAMA_ENABLED=true."
)

#: Ollama 缺模型同理（原文来自 composition 的同一条 fail-fast 消息）。
OLLAMA_MODEL_MISSING_MESSAGE = (
    "Error: OLLAMA_ENABLED=true requires OLLAMA_MODEL "
    "(e.g. OLLAMA_MODEL=qwen3:8b; list local models: curl http://127.0.0.1:11434/api/tags)."
)

#: docker 沙箱 digest pin 的合法形态：``sha256:`` + 64 位小写十六进制。
_REPO_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

#: 清单外的主机名不做 DNS 解析，一律按「可能对外暴露」处理（与 network.exposure 的 fail-safe 同口径）。
_LOCALHOST_NAME = "localhost"


class ConfigIssue(BaseModel):
    """一条阻断性结论：``message`` 是首行（含具体键名），``options`` 是 ``Try:`` 条目。"""

    model_config = ConfigDict(frozen=True)

    check: str
    message: str
    options: tuple[str, ...]


class RequiredCheck(BaseModel):
    """一项必需配置检查：``gate`` 先判适用条件，``judge`` 返回问题描述（``None`` = 通过）。

    门控先行的意义有二：WS 未启用时不去读取用户级 ``setting.md``（零文件 I/O 的快速路径），
    以及避免对「本进程根本不会用到的键」误报。
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    covers: tuple[str, ...]
    gate: Callable[[Settings], bool]
    judge: Callable[[Settings], str | None]
    options: tuple[str, ...]


class StartupValidationResult(BaseModel):
    """一次启动验证的结论；``duration_ms`` 供性能断言与排障使用。"""

    model_config = ConfigDict(frozen=True)

    issues: tuple[ConfigIssue, ...] = ()
    duration_ms: float = 0.0

    @property
    def ok(self) -> bool:
        """无阻断项即可启动。"""
        return not self.issues


def _is_loopback(host: str) -> bool:
    """该绑定地址是否只对本机可见（语义与 :func:`heagent.network.exposure.is_loopback_host` 一致）。

    ``127.0.0.0/8`` 与 ``::1``（含 ``[::1]`` 写法）为真，``localhost`` 按 RFC 6761 为真；
    其它主机名**不解析 DNS**，一律判为可能对外暴露——漏报暴露的代价远高于多一条告警。
    空串在多数 socket API 里等价于「所有接口」，同样按暴露处理。
    """
    candidate = host.strip()
    if candidate.startswith("[") and candidate.endswith("]"):
        inner = candidate[1:-1]
        try:
            ipaddress.IPv6Address(inner)
        except ValueError:
            pass
        else:
            candidate = inner
    if not candidate:
        return False
    if candidate.casefold() == _LOCALHOST_NAME:
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _is_private_address(host: str) -> bool:
    """该绑定地址是否为私有地址字面量（语义同 :func:`heagent.network.exposure.is_private_address`）。

    内网免认证模式（``WS_LAN_NO_AUTH``）的准入判据：``config/`` 不得依赖 ``network/``，故此处内联
    一份纯 stdlib 等价实现，等价性由 ``tests/test_config_validation.py`` 交叉断言钉住。
    """
    candidate = host.strip()
    if candidate.startswith("[") and candidate.endswith("]"):
        inner = candidate[1:-1]
        try:
            ipaddress.IPv6Address(inner)
        except ValueError:
            pass
        else:
            candidate = inner
    if not candidate:
        return False
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_global:
        return False
    return address.is_private or address.is_link_local


def _has_provider_credential(settings: Settings) -> bool:
    """是否存在任一可用凭据（Ollama 本地条目单独判定，见 ``ollama_model`` 检查）。"""
    return any((getattr(settings, name) or "").strip() for name in _CREDENTIAL_FIELDS)


# ── 判据实现 ──
# 每条判据只读 Settings 字段，返回「问题首行」；消息必须点名具体键名，否则用户无从下手。


def _judge_provider_credentials(settings: Settings) -> str | None:
    if _has_provider_credential(settings) or settings.ollama_enabled:
        return None
    return NO_CREDENTIALS_MESSAGE


def _judge_ollama_model(settings: Settings) -> str | None:
    return None if (settings.ollama_model or "").strip() else OLLAMA_MODEL_MISSING_MESSAGE


def _gate_ws_auth(settings: Settings) -> bool:
    """需要 Bearer token 的两条路径：非回环且未开内网免认证、本地强制认证。"""
    if not settings.ws_enabled:
        return False
    main_needs_auth = not _is_loopback(settings.ws_host) and not settings.ws_lan_no_auth
    return settings.ws_local_auth_enabled or main_needs_auth


def _judge_ws_auth_token(settings: Settings) -> str | None:
    if settings.user_ws_auth_token:
        return None
    reasons: list[str] = []
    if not _is_loopback(settings.ws_host) and not settings.ws_lan_no_auth:
        reasons.append(f"WS_HOST={settings.ws_host!r} is not loopback")
    if settings.ws_local_auth_enabled:
        reasons.append("WS_LOCAL_AUTH_ENABLED=true")
    return (
        f"Error: WS_AUTH_TOKEN is required but not set ({'; '.join(reasons)}); "
        "an auth-enforcing WS listener refuses to start without it (fail-closed)."
    )


def _gate_ws_lan_no_auth(settings: Settings) -> bool:
    return settings.ws_enabled and settings.ws_lan_no_auth


def _judge_ws_lan_no_auth(settings: Settings) -> str | None:
    """``WS_LAN_NO_AUTH`` 的准入：不得与 TLS 同开、私有地址字面量、与本地强制认证互斥、回环上无意义。"""
    host = settings.ws_host
    if settings.ws_tls_cert_file and settings.ws_tls_key_file:
        return (
            "Error: WS_LAN_NO_AUTH=true cannot be combined with WS TLS (WS_TLS_CERT_FILE + "
            "WS_TLS_KEY_FILE); an encrypted listener must also authenticate clients. Set "
            "WS_LAN_NO_AUTH=false and use WS_AUTH_TOKEN, or clear both WS_TLS_* keys."
        )
    if settings.ws_local_auth_enabled:
        return (
            "Error: WS_LAN_NO_AUTH=true and WS_LOCAL_AUTH_ENABLED=true are mutually exclusive; "
            "one listener cannot be both unauthenticated and auth-enforcing."
        )
    if _is_loopback(host):
        return (
            f"Error: WS_LAN_NO_AUTH=true has no effect on a loopback bind (WS_HOST={host!r}); "
            "loopback is already unauthenticated — drop the flag."
        )
    if not _is_private_address(host):
        return (
            f"Error: WS_LAN_NO_AUTH=true requires a private address literal (WS_HOST={host!r}); "
            "wildcard binds (0.0.0.0 / ::), public addresses and hostnames are refused."
        )
    return None


def _judge_ws_tls_pair(settings: Settings) -> str | None:
    pairs = [("WS_TLS", settings.ws_tls_cert_file, settings.ws_tls_key_file)]
    for label, cert, key in pairs:
        if bool(cert) == bool(key):
            continue
        missing = f"{label}_KEY_FILE" if cert else f"{label}_CERT_FILE"
        present = f"{label}_CERT_FILE" if cert else f"{label}_KEY_FILE"
        return (
            f"Error: {present} is set but {missing} is missing; WS TLS needs both halves "
            "(startup is refused rather than serving plaintext)."
        )
    return None


def _gate_sandbox_docker(settings: Settings) -> bool:
    return settings.sandbox_backend.strip().lower() == "docker"


def _judge_sandbox_docker(settings: Settings) -> str | None:
    image = settings.sandbox_docker_image.strip()
    if not image:
        return (
            "Error: SANDBOX_BACKEND=docker but SANDBOX_DOCKER_IMAGE is empty; "
            "every sandboxed command would fail to start a container."
        )
    digest = settings.sandbox_docker_digest.strip()
    if digest and not _REPO_DIGEST_RE.match(digest):
        return (
            f"Error: SANDBOX_DOCKER_DIGEST={digest!r} is not a repo digest (expected sha256:<64 hex>); "
            "the pinned-digest guard would refuse every run."
        )
    return None


#: 每项必需检查：name（稳定判据）/ covers（覆盖的 Settings 字段）/ gate（适用条件）/ judge / options。
REQUIRED_CHECKS: tuple[RequiredCheck, ...] = (
    RequiredCheck(
        name="provider_credentials",
        covers=(*_CREDENTIAL_FIELDS, "ollama_enabled"),
        gate=lambda settings: True,
        judge=_judge_provider_credentials,
        options=(
            "put one credential in .env: DEEPSEEK_API_KEY / KIMI_API_KEY / GLM_API_KEY / "
            "OPENAI_RESPONSES_API_KEY / ANTHROPIC_API_KEY",
            "or use a local model: OLLAMA_ENABLED=true + OLLAMA_MODEL=<name>",
        ),
    ),
    RequiredCheck(
        name="ollama_model",
        covers=("ollama_enabled", "ollama_model"),
        gate=lambda settings: settings.ollama_enabled,
        judge=_judge_ollama_model,
        options=(
            "set OLLAMA_MODEL=qwen3:8b (or any model you have pulled)",
            "or set OLLAMA_ENABLED=false while the model name is unknown",
        ),
    ),
    RequiredCheck(
        name="ws_auth_token",
        covers=("ws_enabled", "ws_host", "ws_local_auth_enabled", "ws_lan_no_auth"),
        gate=_gate_ws_auth,
        judge=_judge_ws_auth_token,
        options=(
            "add a `WS_AUTH_TOKEN` entry to ~/.heagent/setting.md (the token is read only from the "
            "user-level file; project .env is ignored)",
            "or bind a private LAN address with WS_LAN_NO_AUTH=true for a plaintext LAN entry",
            "or keep the listener on loopback: WS_HOST=127.0.0.1",
        ),
    ),
    RequiredCheck(
        name="ws_lan_no_auth",
        covers=(
            "ws_enabled",
            "ws_host",
            "ws_lan_no_auth",
            "ws_local_auth_enabled",
            "ws_tls_cert_file",
            "ws_tls_key_file",
        ),
        gate=_gate_ws_lan_no_auth,
        judge=_judge_ws_lan_no_auth,
        options=(
            "set WS_HOST to this machine's private LAN IPv4 (e.g. 192.168.2.226) and keep WS_LAN_NO_AUTH=true",
            "or set WS_LAN_NO_AUTH=false and use WS_HOST=127.0.0.1 for local mode / a WS_AUTH_TOKEN for an "
            "auth-enforcing listener",
        ),
    ),
    RequiredCheck(
        name="ws_tls_pair",
        covers=("ws_enabled", "ws_tls_cert_file", "ws_tls_key_file"),
        gate=lambda settings: settings.ws_enabled,
        judge=_judge_ws_tls_pair,
        options=(
            "set both halves (WS_TLS_CERT_FILE + WS_TLS_KEY_FILE), or clear both",
            "run `python scripts/gen_ws_cert.py` to issue a matching cert/key pair",
        ),
    ),
    RequiredCheck(
        name="sandbox_docker",
        covers=("sandbox_backend", "sandbox_docker_image", "sandbox_docker_digest"),
        gate=_gate_sandbox_docker,
        judge=_judge_sandbox_docker,
        options=(
            "set SANDBOX_DOCKER_IMAGE=heagent-sandbox:3.11 (build it from docker/sandbox/Dockerfile)",
            "or switch SANDBOX_BACKEND back to auto / passthrough",
        ),
    ),
)


def _crash_issue(check_name: str, exc: BaseException) -> ConfigIssue:
    """检查自身崩溃也升为阻断项：静默放行会让「验证过了但起不来」重新出现。"""
    text = str(exc).strip()
    first_line = text.splitlines()[0] if text else type(exc).__name__
    return ConfigIssue(
        check=check_name,
        message=f"Error: startup config check {check_name!r} crashed: {type(exc).__name__}: {first_line}",
        options=(
            "fix the configuration file / value the message names, then retry",
            "run `heagent doctor` for the full configuration diagnosis",
        ),
    )


def validate_startup(settings: Settings) -> StartupValidationResult:
    """跑全部必需检查；返回结论模型（不抛异常、不打印、不退出）。"""
    started = time.perf_counter()
    issues: list[ConfigIssue] = []
    for check in REQUIRED_CHECKS:
        try:
            if not check.gate(settings):
                continue
            problem = check.judge(settings)
        except Exception as exc:  # noqa: BLE001 - 单项检查崩溃必须升为阻断，不能静默放行
            issues.append(_crash_issue(check.name, exc))
            continue
        if problem:
            issues.append(ConfigIssue(check=check.name, message=problem, options=check.options))
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return StartupValidationResult(issues=tuple(issues), duration_ms=elapsed_ms)


def covered_setting_keys() -> frozenset[str]:
    """已被某项检查判定的必需键集合（覆盖率分子来源）。"""
    covered: set[str] = set()
    for check in REQUIRED_CHECKS:
        covered.update(check.covers)
    return frozenset(covered & REQUIRED_SETTING_KEYS)


def required_coverage() -> tuple[int, int]:
    """``(已覆盖键数, 必需键总数)``——票面「覆盖 >90%」的分子与分母。"""
    return len(covered_setting_keys()), len(REQUIRED_SETTING_KEYS)


def required_coverage_ratio() -> float:
    """覆盖率（无必需键时定义为 1.0，避免空集产生除零）。"""
    covered, total = required_coverage()
    return covered / total if total else 1.0


def _verify_key_registry() -> None:
    """导入即核：必需键与检查覆盖的键都必须是真实存在的 ``Settings`` 字段。

    字段被重命名而本注册表没跟上时，宁可 import 就炸（fails loud at load），也不要让覆盖率
    静默变成「全部已覆盖」的假象。
    """
    fields = set(Settings.model_fields)
    unknown = sorted((REQUIRED_SETTING_KEYS | covered_setting_keys()) - fields)
    if unknown:
        raise ValueError(f"config.validation references unknown Settings fields: {unknown}")


_verify_key_registry()

__all__ = [
    "NO_CREDENTIALS_MESSAGE",
    "OLLAMA_MODEL_MISSING_MESSAGE",
    "REQUIRED_CHECKS",
    "REQUIRED_SETTING_KEYS",
    "ConfigIssue",
    "RequiredCheck",
    "StartupValidationResult",
    "covered_setting_keys",
    "required_coverage",
    "required_coverage_ratio",
    "validate_startup",
]
