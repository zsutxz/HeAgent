"""安全口径不倒退守卫（纯只读，不 import `heagent.network` / `heagent.cli`）。

两组判据：

- **G1 文档口径**：`docs/frame.md` 的 `### 4.19 安全口径（canonical）` 段与 `AGENTS.md` 的
  「⚠️ 安全声明」派生副本，逐要素做**正向包含**断言（只查「该说的话还在」，不匹配任何否定句），
  并守 canonical 段在真源里只出现一次——派生副本可以改措辞，但六个要素一个都不能少、不能软化。
- **G2 配置默认值**：用 `Settings.model_fields` 反射收网全部安全相关字段，按谓词组逐条覆盖
  （回环绑定 / 安全侧布尔 / 有界正数 / 有记录的 0=不限 / TLS 成对 / 敏感档位 / 只读凭证不变量）。
  不 pin 易变字面量：后端档位名只要求「显式具名」，档位只做「不是最危险档」的相对断言。

失败信息一律点明「哪个文件 / 哪个字段 / 缺什么」，便于回溯到 `docs/frame.md` 4.19 真源。
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

import pytest

from heagent.config import WS_AUTH_TOKEN_KEY, Settings
from heagent.config.catalog import USER_ONLY_SETTING_KEYS

REPO_ROOT = Path(__file__).resolve().parents[1]
FRAME_DOC = REPO_ROOT / "docs" / "frame.md"
AGENTS_DOC = REPO_ROOT / "AGENTS.md"

#: canonical 段标题（含 `### ` 前缀：避免命中目录 / 交叉引用行）。
CANONICAL_HEADING = "### 4.19 安全口径（canonical）"
#: 段落终止判据：同级或更高级标题（`"### ".startswith("## ")` 为 False，二者互不吞并）。
_SECTION_STOP_PREFIXES = ("### ", "## ")
_NUMBERED_ITEM = re.compile(r"^(\d)\.\s")


# ---------------------------------------------------------------------------
# G1：文档口径（真源 + 派生副本）
# ---------------------------------------------------------------------------

# 要素号 → 该要素在 canonical 段里必须仍在的短语（正向包含，取自 4.19 原文）。
FRAME_ELEMENT_PHRASES: dict[int, tuple[str, ...]] = {
    1: ("SafetyGuard", "PolicyEngine", "defense-in-depth"),
    2: ("默认链路未启用", "MCP stdio"),
    3: ("无认证", "无 TLS", "回环绑定不等于可信"),
    4: ("Authorization: Bearer", "fail-closed", "浏览器 WebSocket API"),
    5: ("/api/cli/ws", "/api/notifications/ws", "没有对外模式"),
    6: ("deferred-work-archive.md",),
}

# 派生副本措辞不同，故短语集独立；要素数量与编号必须与真源一一对应。
AGENTS_ELEMENT_PHRASES: dict[int, tuple[str, ...]] = {
    1: ("SafetyGuard", "PolicyEngine", "sandbox 后端"),
    2: ("Docker 后端默认未启用", "MCP stdio", "D53-1"),
    3: ("无认证", "无 TLS", "回环绑定不等于可信"),
    4: ("Authorization: Bearer", "fail-closed", "浏览器 WebSocket API"),
    5: ("/api/cli/ws", "/api/notifications/ws", "没有对外模式"),
    6: ("deferred-work-archive.md",),
}


def _read_doc(path: Path) -> str:
    assert path.is_file(), f"缺少口径文档 {path}：安全声明与真源都不可缺"
    return path.read_text(encoding="utf-8")


def _slice_section(text: str, start_marker: str) -> tuple[str, int]:
    """从含 `start_marker` 的行切到下一个同级/更高级标题之前，返回 (段文本, 起点 1-based 行号)。"""
    lines = text.splitlines()
    start_index = next((index for index, line in enumerate(lines) if start_marker in line), None)
    assert start_index is not None, f"未找到段落起点 {start_marker!r}"
    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if lines[index].startswith(_SECTION_STOP_PREFIXES):
            end_index = index
            break
    return "\n".join(lines[start_index:end_index]), start_index + 1


def _slice_agents_safety(text: str) -> tuple[str, int]:
    """切出 `## ⚠️ 安全声明` 段：按「二级标题 + 含『安全声明』」定位，不依赖 emoji 变体选择符。"""
    lines = text.splitlines()
    start_index = next(
        (index for index, line in enumerate(lines) if line.startswith("## ") and "安全声明" in line),
        None,
    )
    assert start_index is not None, "AGENTS.md 未找到「## ⚠️ 安全声明」标题行"
    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if lines[index].startswith("## "):
            end_index = index
            break
    return "\n".join(lines[start_index:end_index]), start_index + 1


def _frame_canonical_section() -> tuple[str, int]:
    return _slice_section(_read_doc(FRAME_DOC), CANONICAL_HEADING)


def _element_line_numbers(section: str, start_lineno: int) -> dict[int, int]:
    """要素号 → 文件内 1-based 行号（搜「N. 」行）；缺号由调用方回退到「段起点 + 偏移」。"""
    numbers: dict[int, int] = {}
    for offset, line in enumerate(section.splitlines()):
        matched = _NUMBERED_ITEM.match(line)
        if matched is not None:
            numbers.setdefault(int(matched.group(1)), start_lineno + offset)
    return numbers


def _assert_element_phrases(
    doc_name: str,
    section: str,
    element: int,
    phrases: tuple[str, ...],
    lineno: int,
) -> None:
    missing = [phrase for phrase in phrases if phrase not in section]
    assert not missing, (
        f"{doc_name} 第 {lineno} 行起的「要素 {element}」缺失短语 {missing}："
        "安全口径被删改即视为倒退，请回滚或先改 4.19 真源再同步派生副本"
    )


@pytest.mark.parametrize(
    ("element", "phrases"),
    sorted(FRAME_ELEMENT_PHRASES.items()),
    ids=[f"frame-element-{element}" for element in sorted(FRAME_ELEMENT_PHRASES)],
)
def test_frame_canonical_section_keeps_the_six_elements(element: int, phrases: tuple[str, ...]) -> None:
    """守 G1-a：`docs/frame.md` 4.19 canonical 段的 6 要素措辞不得删改（只做正向包含断言）。"""
    section, start_lineno = _frame_canonical_section()
    line_numbers = _element_line_numbers(section, start_lineno)
    _assert_element_phrases(
        "docs/frame.md",
        section,
        element,
        phrases,
        line_numbers.get(element, start_lineno + element - 1),
    )


@pytest.mark.parametrize(
    ("element", "phrases"),
    sorted(AGENTS_ELEMENT_PHRASES.items()),
    ids=[f"agents-element-{element}" for element in sorted(AGENTS_ELEMENT_PHRASES)],
)
def test_agents_derived_section_keeps_the_six_elements(element: int, phrases: tuple[str, ...]) -> None:
    """守 G1-b：`AGENTS.md` 派生副本的 6 要素与真源一一对应，措辞可不同但不可缺项。"""
    section, start_lineno = _slice_agents_safety(_read_doc(AGENTS_DOC))
    line_numbers = _element_line_numbers(section, start_lineno)
    _assert_element_phrases(
        "AGENTS.md",
        section,
        element,
        phrases,
        line_numbers.get(element, start_lineno + element - 1),
    )


def test_canonical_heading_appears_exactly_once() -> None:
    """守「唯一真源」：canonical 段在 frame.md 里只能出现一次，复制出第二份即口径分裂。"""
    occurrences = _read_doc(FRAME_DOC).count(CANONICAL_HEADING)
    assert occurrences == 1, (
        f"docs/frame.md 中 {CANONICAL_HEADING!r} 出现 {occurrences} 次，期望恰好 1 次：安全口径唯一真源不得复制出第二份"
    )


def test_canonical_section_numbers_six_elements() -> None:
    """守结构完整性：canonical 段必须是 1..6 六个编号要素，删项 / 合并项都属倒退。"""
    section, start_lineno = _frame_canonical_section()
    numbers = sorted(_element_line_numbers(section, start_lineno))
    assert numbers == [1, 2, 3, 4, 5, 6], (
        f"canonical 段（起点第 {start_lineno} 行）的编号要素应为 [1, 2, 3, 4, 5, 6]，实为 {numbers}"
    )


# ---------------------------------------------------------------------------
# G2：Settings 默认值（反射收网 + 语义谓词）
# ---------------------------------------------------------------------------

#: 反射收网规则：字段名以这三类前缀开头，或含 `token`（凭证类）。
#: 新增安全字段只要遵循命名约定就会自动被收网出来，然后由「未归类即红」兜住。
SECURITY_FIELD_PATTERNS: tuple[str, ...] = (
    r"^sandbox_",
    r"^http_",
    r"^ws_",
    r"token",
)
_SECURITY_FIELD_RE = re.compile("|".join(SECURITY_FIELD_PATTERNS))

# **重要**：`Settings` 是 pydantic-settings（会读项目 `.env` / 系统环境变量），因此 `Settings()`
# 取到的是**本机有效值**而不是「代码里的默认值」——实测项目 `.env` 里的 `SANDBOX_NETWORK=true`
# 会让「默认必须 False」的断言假红。默认值一律走 `FieldInfo.get_default(call_default_factory=True)`。

# 字段 → 期望的**安全侧**布尔值；每一项都写清「哪一侧才是安全侧」。
_SAFETY_SIDE_BOOL: tuple[tuple[str, bool], ...] = (
    ("sandbox_enforce", True),  # 安全侧 = True：强制走沙箱；关掉等于裸跑
    ("sandbox_network", False),  # 安全侧 = False：沙箱内默认不出网
    ("sandbox_session_workspace", False),  # 安全侧 = False：不额外落会话级 workspace
    ("sandbox_session_keep", False),  # 安全侧 = False：不保留会话目录（少留残留物）
    ("http_console_write_enabled", False),  # 安全侧 = False：网页不能自己给自己开写通道
    ("ws_cli_bypass_enabled", False),  # 安全侧 = False：终端旁路观众席默认不挂任何 listener
)

# 有记录的产品默认（不是「安全侧」断言）：只要求仍是显式布尔，防止退化成 None / 三态。
_DOCUMENTED_BOOL_DEFAULTS: tuple[str, ...] = (
    # 对外 listener 的只读旁观：True 更严，但 Epic 56 期二 P2-A3 显式选择「默认 False = 可提交」，
    # 属已记录的产品能力（见 docs/frame.md 4.17.1）；本守卫只钉「口径被静默改掉」。
    "ws_external_readonly",
)

# 显式映射表：谓词组 → 字段。反射到的字段必须全部命中此处，差集非空即红（不 skip）。
_PREDICATE_GROUPS: dict[str, tuple[str, ...]] = {
    "loopback-host": ("http_host", "ws_host"),
    "optional-bind": ("ws_external_host",),
    "safety-bool": tuple(field_name for field_name, _ in _SAFETY_SIDE_BOOL),
    "documented-bool": _DOCUMENTED_BOOL_DEFAULTS,
    "bounded-positive": (
        "http_max_connections",
        "http_max_subscribers",
        "http_max_inflight_runs",
        "ws_max_connections",
        "ws_shutdown_timeout",
        "http_shutdown_timeout",
        # 资源上限族：0 / 负值等于关掉上限，同样属「有界正数」谓词。
        "http_max_request_bytes",
        "http_event_buffer_size",
        "http_run_history_size",
        "http_idle_timeout",
        "http_tool_inflight_timeout",
        "http_port",
        "http_port_auto_find_attempts",
        "ws_port",
        "ws_external_port",
    ),
    # 0 = 不限：`http_max_total_inflight` 见 docs/frame.md 4.18 D9（有记录的显式选择），
    # 其余三项（请求超时 / 内存 / CPU 秒数 / 进程数）同理——**不是**安全默认，故只断言 >= 0。
    "unlimited-zero": (
        "http_max_total_inflight",
        "http_request_timeout",
        "sandbox_memory_limit_mb",
        "sandbox_cpu_seconds",
        "sandbox_nproc_limit",
    ),
    "tls-pair": (
        "ws_tls_cert_file",
        "ws_tls_key_file",
        "ws_external_tls_cert_file",
        "ws_external_tls_key_file",
    ),
    "sandbox-mode": ("sandbox_mode",),
    "sandbox-backend": ("sandbox_backend",),
    "retention-days": ("sandbox_dir_retention_days",),
    "listener-toggle": ("http_enabled", "ws_enabled"),
    "optional-path": ("http_console_projects_file",),
}


#: 反射误命中但**不是**安全默认值轴的字段（story 允许「按语义谓词适用性剔除并登记」）：
#: 这些是后端参数 / 模型能力 / 名称里恰好含 `token` 的预算项，与「默认是否安全」无关。
_EXCLUDED_FIELDS: dict[str, str] = {
    "sandbox_firejail_path": "后端可执行文件路径，不构成默认安全性轴",
    "sandbox_docker_image": "镜像标签，安全由 digest 与运行时决定，非默认值轴",
    "sandbox_docker_digest": "镜像 digest 属可选加固项（空 = 未钉），不是「默认不安全」",
    "sandbox_env_allowlist": "env 豁免名单（默认空 = 不豁免任何键，空本身即最严）",
    "sandbox_profiles": "profile 映射表（默认空 = 用内置映射）",
    "sandbox_tool_profiles": "工具级 profile 覆盖表（默认空 = 不覆盖）",
    "max_context_tokens": "上下文窗口（模型能力，非安全轴）",
    "max_output_tokens": "输出预算（模型能力，非安全轴）",
    "skill_max_auto_invoke_tokens": "技能 token 预算，名称含 token 但非凭证",
    "skill_max_manual_load_tokens": "技能 token 预算，名称含 token 但非凭证",
    "tokenizer": "分词器选择，名称含 token 但非凭证",
}


def _default(field_name: str) -> Any:
    """取字段**代码默认值**（不经 env / .env）；字段不存在则直接红并点名。"""
    field = Settings.model_fields.get(field_name)
    if field is None:
        pytest.fail(
            f"{field_name!r} 不在 Settings.model_fields 中：反射收网映射已过期（字段改名/删除），"
            "请同步 _PREDICATE_GROUPS 与 docs/frame.md 4.19"
        )
    return field.get_default(call_default_factory=True)


def _reflect_security_fields() -> frozenset[str]:
    return frozenset(name for name in Settings.model_fields if _SECURITY_FIELD_RE.search(name))


def _is_loopback_or_local(value: Any) -> bool:
    """回环判定：IP 字面量走 `is_loopback`；非 IP 字面量用 `localhost` / 空串兜底。"""
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if candidate in {"", "localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


@pytest.mark.parametrize("field_name", _PREDICATE_GROUPS["loopback-host"])
def test_listeners_bind_to_loopback_by_default(field_name: str) -> None:
    """守「本地模式」：HTTP / WS listener 默认只绑回环，不得默认暴露到非回环地址。"""
    value = _default(field_name)
    assert _is_loopback_or_local(value), (
        f"Settings.{field_name} 默认值 {value!r} 不是回环绑定：本地模式口径要求 listener 绑回环"
    )


@pytest.mark.parametrize("field_name", _PREDICATE_GROUPS["optional-bind"])
def test_external_listener_is_unset_or_loopback_by_default(field_name: str) -> None:
    """守「对外 listener 默认不启用」：`ws_external_host` 默认 None；回环值等价于未对外开放。"""
    value = _default(field_name)
    assert value is None or _is_loopback_or_local(value), (
        f"Settings.{field_name} 默认值 {value!r}：对外 listener 默认必须是 None 或回环，非回环即等于默认对外暴露"
    )


@pytest.mark.parametrize(
    ("field_name", "expected"),
    _SAFETY_SIDE_BOOL,
    ids=[f"{field_name}-safe-side-{expected}" for field_name, expected in _SAFETY_SIDE_BOOL],
)
def test_security_side_booleans_keep_safe_default(field_name: str, expected: bool) -> None:
    """守安全侧布尔默认：每条的「哪一侧才是安全侧」写在 `_SAFETY_SIDE_BOOL` 注释里，漂移即红。"""
    value = _default(field_name)
    assert isinstance(value, bool) and value is expected, (
        f"Settings.{field_name} 默认值 {value!r}，安全侧要求 {expected!r}"
    )


@pytest.mark.parametrize("field_name", _PREDICATE_GROUPS["documented-bool"])
def test_documented_bool_defaults_stay_explicit(field_name: str) -> None:
    """守「有记录的产品默认」不被静默改形：允许当前值，但必须是显式布尔。"""
    value = _default(field_name)
    assert isinstance(value, bool), f"Settings.{field_name} 默认值 {value!r}，要求显式布尔"


@pytest.mark.parametrize("field_name", _PREDICATE_GROUPS["bounded-positive"])
def test_bounded_limits_are_positive(field_name: str) -> None:
    """守「有上限」：限额与关停超时默认必须 > 0，0 或负数等于把上限悄悄关掉。"""
    value = _default(field_name)
    assert _is_number(value) and value > 0, (
        f"Settings.{field_name} 默认值 {value!r}，要求 > 0（0 / 负值 = 无上限，属不安全默认）"
    )


@pytest.mark.parametrize("field_name", _PREDICATE_GROUPS["unlimited-zero"])
def test_unlimited_knobs_are_non_negative(field_name: str) -> None:
    """守「0 = 不限」的有记录项：只要求 >= 0。

    这几项默认 0 表示不限，是 `docs/frame.md` 与台账里**记录过的显式选择**（如
    `http_max_total_inflight` 见 4.18 D9），**不是安全默认**；故本守卫不得把它们改成 > 0 的断言。
    """
    value = _default(field_name)
    assert _is_number(value) and value >= 0, f"Settings.{field_name} 默认值 {value!r}，要求 >= 0"


def test_tls_files_are_paired_or_unset() -> None:
    """守 TLS 成对：cert / key 要么同时配置、要么同时未配置，默认值里不藏半配状态。"""
    cert = _default("ws_tls_cert_file")
    key = _default("ws_tls_key_file")
    assert bool(cert) == bool(key), (
        f"Settings.ws_tls_cert_file={cert!r} 与 ws_tls_key_file={key!r} 半配："
        "TLS 材料必须成对（半配应在启动期 fail-loud，不该出现在默认值里）"
    )


def test_sandbox_mode_default_is_not_full_access() -> None:
    """守最危险档位：默认不得是 danger-full-access（用 `!=` 表达语义，不 pin 具体档位名）。"""
    value = _default("sandbox_mode")
    assert value != "danger-full-access", f"Settings.sandbox_mode 默认值 {value!r}：默认档位不得是全权访问"


@pytest.mark.parametrize("field_name", _PREDICATE_GROUPS["sandbox-backend"])
def test_sandbox_backend_default_is_an_explicit_choice(field_name: str) -> None:
    """守「后端选择显式」：默认必须是具名档位（非空字符串），不得是 None 静默降级；档位名不 pin。"""
    value = _default(field_name)
    assert isinstance(value, str) and value.strip(), (
        f"Settings.{field_name} 默认值 {value!r}，要求显式具名档位（非空字符串）"
    )


@pytest.mark.parametrize("field_name", _PREDICATE_GROUPS["retention-days"])
def test_sandbox_retention_days_is_non_negative(field_name: str) -> None:
    """守保留期可判定：默认 >= 0（0 = 不保留），负值无意义。"""
    value = _default(field_name)
    assert isinstance(value, int) and not isinstance(value, bool) and value >= 0, (
        f"Settings.{field_name} 默认值 {value!r}，要求 >= 0 的整数"
    )


@pytest.mark.parametrize("field_name", _PREDICATE_GROUPS["listener-toggle"])
def test_listener_toggles_are_explicit_booleans(field_name: str) -> None:
    """守装配开关是显式布尔：开关本身不是安全轴（安全由绑定地址 + 认证决定），只防三态歧义。"""
    value = _default(field_name)
    assert isinstance(value, bool), f"Settings.{field_name} 默认值 {value!r}，要求显式布尔"


@pytest.mark.parametrize("field_name", _PREDICATE_GROUPS["optional-path"])
def test_optional_path_defaults_are_unset(field_name: str) -> None:
    """守「缺省即不落盘」：可选落点默认 None，避免默认值把工程/日志文件写到意外位置。"""
    value = _default(field_name)
    assert value is None, f"Settings.{field_name} 默认值 {value!r}，期望 None（缺省不落盘）"


def test_reflected_security_fields_are_all_covered_by_predicates() -> None:
    """守收网完整性：反射到的每个安全相关字段都必须落在某个谓词组里，未归类直接红并点名。"""
    reflected = _reflect_security_fields()
    assert reflected, "Settings 未反射到任何安全相关字段：收网正则或字段命名口径已失效"
    mapped = frozenset(name for names in _PREDICATE_GROUPS.values() for name in names)
    excluded = frozenset(_EXCLUDED_FIELDS)
    overlap = sorted(mapped & excluded)
    assert not overlap, f"同一字段既被谓词组覆盖又被排除（口径冲突，必须二选一）：{overlap}"
    unclassified = sorted(reflected - mapped - excluded)
    assert not unclassified, (
        "以下安全相关字段既未覆盖也未登记排除"
        f"（请补 _PREDICATE_GROUPS 或写进 _EXCLUDED_FIELDS 并给理由）：{unclassified}"
    )


def test_predicate_mapping_names_only_real_fields() -> None:
    """守映射表不腐化：`_PREDICATE_GROUPS` 里出现的字段名必须真的存在于 `Settings.model_fields`。"""
    dangling = sorted(
        name for names in _PREDICATE_GROUPS.values() for name in names if name not in Settings.model_fields
    )
    assert not dangling, f"映射表引用了不存在的 Settings 字段：{dangling}"


def test_auth_token_is_a_read_only_property_not_a_field() -> None:
    """守凭证不变量：WS token 只从用户级 `~/.heagent/setting.md` 读，不能变成可被 env / .env 覆盖的字段。"""
    assert "user_ws_auth_token" not in Settings.model_fields, (
        "user_ws_auth_token 变成了 Settings 字段：凭证会被「系统 env > 项目 .env > 用户 md」优先级链接管"
    )
    assert isinstance(getattr(Settings, "user_ws_auth_token", None), property), (
        "Settings.user_ws_auth_token 必须仍是只读 @property"
    )


def test_token_key_is_user_only() -> None:
    """守凭证真源位置：`WS_AUTH_TOKEN_KEY` 必须在 `USER_ONLY_SETTING_KEYS` 里（只认用户级 setting.md）。"""
    assert isinstance(USER_ONLY_SETTING_KEYS, frozenset), (
        f"USER_ONLY_SETTING_KEYS 应为 frozenset，实为 {type(USER_ONLY_SETTING_KEYS)!r}"
    )
    assert WS_AUTH_TOKEN_KEY in USER_ONLY_SETTING_KEYS, (
        f"{WS_AUTH_TOKEN_KEY!r} 不在 USER_ONLY_SETTING_KEYS 中：项目层 .env 可能覆盖对外 WS 的认证凭证"
    )


# ---------------------------------------------------------------------------
# S-11：MCP annotations「server 自声明 / 不可信」标注在场（只读源码文本，不 import mcp 模块）
# ---------------------------------------------------------------------------

MCP_MAPPING_SRC = REPO_ROOT / "src" / "heagent" / "tools" / "mcp" / "mapping.py"

#: 两处注释都必须同时出现这两个词：它们把「annotations 是外部声明」这件事写死在代码里。
MCP_ANNOTATION_HINT_KEYWORDS = ("自声明", "不可信")


def _mcp_mapping_lines() -> list[str]:
    """读 ``tools/mcp/mapping.py`` 源码行（复用 ``_read_doc``：utf-8、缺文件即断言失败）。"""
    return _read_doc(MCP_MAPPING_SRC).splitlines()


def _window_from_anchor(lines: list[str], anchor: str, span: int) -> str:
    """返回含 ``anchor`` 那行起向下 ``span`` 行的拼接文本；锚点缺席即断言失败并点名文件。"""
    for index, line in enumerate(lines):
        if anchor in line:
            return "\n".join(lines[index : index + span])
    raise AssertionError(f"{MCP_MAPPING_SRC} 中找不到锚点：{anchor!r}")


def test_mcp_annotation_conversion_declares_self_declared_and_untrusted() -> None:
    """判据 1：``_mcp_annotations_to_heagent`` 及其后 30 行内声明「自声明 / 不可信」并指向 §4.19。"""
    window = _window_from_anchor(_mcp_mapping_lines(), "def _mcp_annotations_to_heagent", 30)
    for keyword in (*MCP_ANNOTATION_HINT_KEYWORDS, "§4.19"):
        assert keyword in window, (
            f"{MCP_MAPPING_SRC} 的 _mcp_annotations_to_heagent 附近缺少关键词 {keyword!r}；"
            "应声明 Tool.annotations 为 server 自声明 / 不可信，并指向 docs/frame.md §4.19"
        )


def test_mcp_annotations_passthrough_marks_known_gap_unclosed() -> None:
    """判据 2：``annotations=`` 透传点上方 10 行内声明「自声明 / 不可信」并点名 D53-1 未闭合。"""
    lines = _mcp_mapping_lines()
    anchor = "annotations=_mcp_annotations_to_heagent("
    hits = [index for index, line in enumerate(lines) if anchor in line]
    assert hits, f"{MCP_MAPPING_SRC} 中找不到锚点：{anchor!r}"
    index = hits[-1]
    window = "\n".join(lines[max(0, index - 10) : index + 1])
    for keyword in (*MCP_ANNOTATION_HINT_KEYWORDS, "D53-1"):
        assert keyword in window, (
            f"{MCP_MAPPING_SRC} 的 {anchor} 上方 10 行内缺少关键词 {keyword!r}；"
            "应声明 annotations 自声明 / 不可信，并写明 MCP stdio 沙箱缺口 D53-1 未闭合"
        )


def test_mcp_canonical_section_points_back_to_the_stdio_gap() -> None:
    """判据 3：canonical §4.19 反向指向 MCP stdio 缺口（代码 → canonical → 缺口 双向在场）。"""
    section, _start_lineno = _slice_section(_read_doc(FRAME_DOC), CANONICAL_HEADING)
    for keyword in ("MCP stdio", "D53-1"):
        assert keyword in section, (
            f"{FRAME_DOC} 的 {CANONICAL_HEADING!r} 段缺少关键词 {keyword!r}；"
            "canonical 要素 2 必须写明 MCP stdio 未进沙箱并挂 epic-53 期二 D53-1"
        )
