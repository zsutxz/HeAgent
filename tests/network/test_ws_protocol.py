"""Epic 54 Story 54-1：WebSocket 帧协议契约判据。"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from heagent.network.http_protocol import (
    HttpErrorCode,
    RunEventKind,
    RunEventPayload,
    RunStatus,
    SSE_HEARTBEAT_SECONDS,
    error_envelope,
)
from heagent.network.ws_protocol import (
    _FRAME_FIELDS,
    WS_CLOSE_GOING_AWAY,
    WS_CLOSE_INTERNAL,
    WS_CLOSE_POLICY,
    WS_CLOSE_TOO_LARGE,
    WS_MAX_COMMAND_CHARS,
    WS_MAX_FRAME_BYTES,
    WS_MAX_INBOUND_CHARS,
    WS_PING_INTERVAL_SECONDS,
    WS_PING_TIMEOUT_SECONDS,
    WsAckFrame,
    ProjectChannelEntry,
    SubmittedRun,
    WsAckFrame,
    WsCliAckFrame,
    WsCliEventFrame,
    WsCommand,
    WsCommandFrame,
    WsErrorFrame,
    WsEventFrame,
    WsFrameError,
    WsFrameErrorKind,
    WsFrameType,
    WsHelloFrame,
    WsNotificationFrame,
    WsProjectsFrame,
    parse_command_frame,
)


def test_hello_frame_carries_only_the_server_version() -> None:
    """56-9：hello 首帧只含版本；形状钉死（type=hello + version，extra=forbid）。"""
    dumped = WsHelloFrame(version="0.8.4").model_dump(mode="json")

    assert dumped == {"type": "hello", "version": "0.8.4"}


def test_event_frame_round_trip_preserves_nested_sse_payload() -> None:
    event = RunEventPayload(kind=RunEventKind.TEXT, seq=1, text="hello")
    frame = WsEventFrame(event=event)

    dumped = frame.model_dump(mode="json")

    assert dumped == {
        "type": "event",
        "event": {
            "kind": "text",
            "seq": 1,
            "text": "hello",
            "tool_name": "",
            "tool_target": "",
            "tool_output": "",
            "tool_error": False,
            "message": "",
            "model": None,
            "usage": None,
        },
    }
    assert WsEventFrame.model_validate(dumped) == frame


def test_ack_frame_round_trip_has_closed_shape() -> None:
    frame = WsAckFrame(command=WsCommand.CANCEL, run_id="run-1", status=RunStatus.CANCELLED)
    dumped = frame.model_dump(mode="json")

    assert dumped == {
        "type": "ack",
        "command": "cancel",
        "run_id": "run-1",
        "status": "cancelled",
    }
    assert WsAckFrame.model_validate(dumped) == frame


def test_error_frame_round_trip_reuses_http_error_envelope() -> None:
    for code in HttpErrorCode:
        frame = WsErrorFrame(error=error_envelope(code, "request failed"))
        dumped = frame.model_dump(mode="json")
        assert dumped["type"] == "error"
        assert dumped["error"]["error"]["code"] == code.value
        assert WsErrorFrame.model_validate(dumped) == frame


def test_command_frame_round_trip_and_closed_models_reject_extra_fields() -> None:
    frame = WsCommandFrame(command=WsCommand.PING)
    assert WsCommandFrame.model_validate(frame.model_dump(mode="json")) == frame

    event = RunEventPayload(kind=RunEventKind.TEXT, seq=1)
    with pytest.raises(ValidationError):
        WsEventFrame(event=event, text="flattened")
    with pytest.raises(ValidationError):
        RunEventPayload(kind=RunEventKind.TEXT, seq=1, type="event")
    with pytest.raises(ValidationError):
        WsCommandFrame(command=WsCommand.PING, run_id="run-1")
    with pytest.raises(ValidationError):
        WsErrorFrame.model_validate({"type": "error", "code": "custom", "error": {}})


def test_unknown_frame_types_and_commands_are_rejected() -> None:
    with pytest.raises(ValidationError):
        WsAckFrame.model_validate({"type": "unknown", "command": "ping", "run_id": "run-1", "status": "running"})
    with pytest.raises(ValidationError):
        WsCommandFrame.model_validate({"command": "subscribe"})


def test_protocol_limits_and_close_codes_match_contract() -> None:
    """三条上限口径（Epic 56 Story 56-3 起）：run 帧要装得下协议允许的最大 prompt。"""
    from heagent.network.http_protocol import (
        JSON_ENVELOPE_ALLOWANCE_BYTES,
        MAX_PROMPT_CHARS,
        MAX_REQUEST_BYTES_FOR_MAX_PROMPT,
    )

    # 字符上限按**最坏 JSON 转义**推算（ensure_ascii=True 时 1 个 CJK 字符 → 6 个 ASCII 字符）：
    # 按原始字符数（32 K）定会把合法的最大 prompt 挡在协议层之外（实现期实测 1009）。
    assert WS_MAX_INBOUND_CHARS == 6 * MAX_PROMPT_CHARS + JSON_ENVELOPE_ALLOWANCE_BYTES
    assert WS_MAX_COMMAND_CHARS == 4096
    assert WS_MAX_FRAME_BYTES == MAX_REQUEST_BYTES_FOR_MAX_PROMPT
    assert WS_MAX_FRAME_BYTES >= 4 * MAX_PROMPT_CHARS  # 最坏 UTF-8（4 字节/字符）也装得下
    assert WS_MAX_COMMAND_CHARS < WS_MAX_INBOUND_CHARS <= WS_MAX_FRAME_BYTES
    assert WS_PING_INTERVAL_SECONDS == SSE_HEARTBEAT_SECONDS == 15.0
    assert WS_PING_TIMEOUT_SECONDS == 20.0
    assert (WS_CLOSE_POLICY, WS_CLOSE_TOO_LARGE, WS_CLOSE_INTERNAL, WS_CLOSE_GOING_AWAY) == (
        1008,
        1009,
        1011,
        1001,
    )


def test_parse_command_frame_accepts_cancel_and_ping() -> None:
    assert parse_command_frame('{"command":"cancel"}').command is WsCommand.CANCEL
    assert parse_command_frame('{"command":"ping"}').command is WsCommand.PING


def test_parse_command_frame_accepts_run_with_prompt() -> None:
    frame = parse_command_frame('{"command":"run","prompt":"写一个快速排序"}')
    assert frame.command is WsCommand.RUN
    assert frame.prompt == "写一个快速排序"
    # 最大长度 prompt 必须能通过（HTTP 侧同一条字符上限）。
    from heagent.network.http_protocol import MAX_PROMPT_CHARS

    biggest = json.dumps({"command": "run", "prompt": "中" * MAX_PROMPT_CHARS}, ensure_ascii=False)
    assert parse_command_frame(biggest).command is WsCommand.RUN


@pytest.mark.parametrize(
    "text",
    [
        '{"command":"run"}',  # run 必须带 prompt
        '{"command":"run","prompt":null}',
        '{"command":"run","prompt":"hi","extra":1}',
        '{"command":"ping","prompt":"hi"}',  # prompt 只对 run 有效
        '{"command":"cancel","prompt":""}',
    ],
)
def test_run_and_prompt_are_mutually_bound(text: str) -> None:
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame(text)
    assert exc_info.value.kind is WsFrameErrorKind.MALFORMED


def test_non_run_frames_keep_the_small_character_limit() -> None:
    """命令面刻意保持最小：ping 不能借 prompt 那一档上限灌进 30 KiB。"""
    padded = json.dumps({"command": "ping", "pad": "x" * WS_MAX_COMMAND_CHARS})
    assert len(padded) > WS_MAX_COMMAND_CHARS
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame(padded)
    assert exc_info.value.kind is WsFrameErrorKind.TOO_LARGE


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("{", WsFrameErrorKind.MALFORMED),
        ('{"command":"subscribe"}', WsFrameErrorKind.UNKNOWN_COMMAND),
        ('{"command":"ping","extra":true}', WsFrameErrorKind.MALFORMED),
    ],
)
def test_parse_command_frame_classifies_invalid_inputs(text: str, kind: WsFrameErrorKind) -> None:
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame(text)
    assert exc_info.value.kind is kind


def test_parse_command_frame_checks_character_limit_before_json() -> None:
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame("{" * (WS_MAX_INBOUND_CHARS + 1))
    assert exc_info.value.kind is WsFrameErrorKind.TOO_LARGE

    # 字符上限不是 UTF-8 字节上限：字符数在上限内的多字节帧仍进入结构校验。
    # （`run` 帧不受 WS_MAX_COMMAND_CHARS 约束——那一档只挡 cancel / ping。）
    text = json.dumps({"command": "run", "prompt": "你" * (WS_MAX_INBOUND_CHARS - 60)}, ensure_ascii=False)
    assert WS_MAX_COMMAND_CHARS < len(text) <= WS_MAX_INBOUND_CHARS
    assert len(text.encode()) > WS_MAX_INBOUND_CHARS  # 字节数远超字符上限：两个口径确实不同
    assert parse_command_frame(text).command is WsCommand.RUN


def test_cancel_run_frame_requires_exactly_a_run_id() -> None:
    """E74-S03：``cancel_run`` 的目标是必带字段，且不许夹带 ``project_id`` 或未知键。"""
    frame = parse_command_frame(json.dumps({"command": "cancel_run", "run_id": "run-abc"}))
    assert frame.command is WsCommand.CANCEL_RUN
    assert frame.run_id == "run-abc"
    assert frame.project_id is None
    # 不做 strip：服务端签发的 opaque id 必须原样回传，加空格就是另一个 id（长度仍在界内）。
    assert parse_command_frame(json.dumps({"command": "cancel_run", "run_id": " run-abc "})).run_id == " run-abc "


def test_run_frame_carries_an_opaque_request_id_and_does_not_strip_it() -> None:
    """E77-S01：``request_id`` 是可选的幂等键，原样保留（客户端不透明 id，不 strip）。"""
    plain = parse_command_frame(json.dumps({"command": "run", "prompt": "hi"}))
    assert plain.request_id is None  # 旧帧逐字等价：缺省 = 不带幂等语义

    keyed = parse_command_frame(json.dumps({"command": "run", "prompt": "hi", "request_id": " req-1 "}))
    assert keyed.request_id == " req-1 "


@pytest.mark.parametrize("request_id", ["", "x" * 65])
def test_run_request_id_is_bounded_to_sixty_four_chars(request_id: str) -> None:
    """与 ``run_id`` 同档长度界：空串与超长在解析面即 ``malformed``。"""
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame(json.dumps({"command": "run", "prompt": "hi", "request_id": request_id}))
    assert exc_info.value.kind is WsFrameErrorKind.MALFORMED


@pytest.mark.parametrize(
    "project_id",
    ["", "x" * 17],
)
def test_run_project_id_is_bounded_to_sixteen_chars(project_id: str) -> None:
    """``project_id`` 的长度界与 ``run_id`` 对称：``min_length=1`` / ``max_length=16``。

    界值本身在帧模型上（``ProjectChannelEntry.id`` 与命令帧同一上限），这里钉的是**解析面**：
    空串与超长都在 ``parse_command_frame`` 就回 ``malformed``，不会漏到端点去查一个不存在的项目。
    """
    text = json.dumps({"command": "run", "prompt": "hi", "project_id": project_id})

    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame(text)
    assert exc_info.value.kind is WsFrameErrorKind.MALFORMED


def test_run_project_id_accepts_exactly_sixteen_chars() -> None:
    """上界是闭区间：16 字符合法（17 才是越界），免得把「刚好满」判成非法。"""
    text = json.dumps({"command": "run", "prompt": "hi", "project_id": "x" * 16})

    assert parse_command_frame(text).project_id == "x" * 16


@pytest.mark.parametrize(
    "text",
    [
        '{"command":"cancel_run"}',  # run_id 必带
        '{"command":"cancel_run","run_id":null}',  # 显式 null 与缺席同义
        '{"command":"cancel_run","run_id":""}',  # min_length=1
        '{"command":"cancel_run","run_id":"' + "x" * 65 + '"}',  # max_length=64
        '{"command":"cancel_run","run_id":"run-1","project_id":"p1234abcd"}',  # 项目字段只对 run 有效
        '{"command":"cancel_run","run_id":"run-1","extra":1}',
        '{"command":"cancel","run_id":"run-1"}',  # cancel 沿用连接绑定，多带目标即非法
        '{"command":"ping","run_id":"run-1"}',
        '{"command":"run","prompt":"hi","run_id":"run-1"}',
    ],
)
def test_run_id_is_exclusive_to_cancel_run(text: str) -> None:
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame(text)
    assert exc_info.value.kind is WsFrameErrorKind.MALFORMED


def test_cancel_run_keeps_the_small_character_limit() -> None:
    """``cancel_run`` 与 ``cancel`` / ``ping`` 同档：非 ``run`` 命令一律走 4096 字符上限。"""
    padded = json.dumps({"command": "cancel_run", "run_id": "run-1", "pad": "x" * WS_MAX_COMMAND_CHARS})
    assert len(padded) > WS_MAX_COMMAND_CHARS
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame(padded)
    assert exc_info.value.kind is WsFrameErrorKind.TOO_LARGE


def test_ws_protocol_runtime_imports_stay_within_network_leaf_dependencies() -> None:
    source = Path("src/heagent/network/ws_protocol.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name.split(".", 1)[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    )

    assert imported_modules <= {
        "__future__",
        "json",
        "enum",
        "pydantic",
        "typing",  # 端口 Protocol 的 ``Any`` / ``Protocol``（E74 起注入端口与帧同住本模块）
        "heagent.network.http_protocol",
    }


def test_ws_protocol_does_not_define_duplicate_error_messages() -> None:
    source = Path("src/heagent/network/ws_protocol.py").read_text(encoding="utf-8")
    assert '"invalid_request"' not in source
    assert '"unknown_run"' not in source
    assert '"resync_required"' not in source
    assert "error_envelope" in source


@pytest.mark.parametrize("text", ['"run"', "[1,2]", "null", "42"])
def test_json_that_is_not_an_object_is_malformed(text: str) -> None:
    """合法 JSON 但不是对象 ⇒ ``malformed``（与「解不出 JSON」同档，不崩、不静默当空帧）。"""
    with pytest.raises(WsFrameError) as excinfo:
        parse_command_frame(text)

    assert excinfo.value.kind is WsFrameErrorKind.MALFORMED


# ── E76-S03（R5）：远程可见面白名单收口 ──────────────────────────────────────
#
# R5 = 「远程能做的事」不扩张。判据分两层：
#  1. 命令值与帧字段名是**封闭白名单**（集合相等，不是子集）：多一条命令、多一个入站字段都是
#     「多一层远程能力」，必须在这里显性变红，而不是被顺手漏出；
#  2. 白名单里不出现配置读写 / 项目注册 / 会话历史族的词根（命令值与帧字段名双向），解析器对
#     这类帧回 ``unknown_command``，WS 面源码里也不出现这些能力的实现符号。
# 端点面（四条 WS 路径）已由 ``tests/test_architecture_contracts.py`` 钉死，此处不重复。

_NETWORK_DIR = Path("src/heagent/network")

#: WS 面全部模块。远程可达面只由这几个文件构成，配置 / 注册 / 会话能力一律不得出现在其中。
_WS_SURFACE_MODULES = ("ws_auth.py", "ws_commands.py", "ws_host.py", "ws_protocol.py", "ws_server.py")

#: ``network/`` 内**唯一**允许出现配置写入 / 项目注册 / 会话浏览符号的模块：回环 HTTP 控制台。
#: R5 允许这些能力留在本机 HTTP 面（远程注册回 403），只要求它们不跨越到 WS 面。
_LOOPBACK_CONSOLE_MODULES = frozenset(
    {"http_console_protocol.py", "http_server/app.py", "http_server/endpoints_console.py"}
)

#: 远程面禁止的能力族词根（口径：**子串**、大小写不敏感）。
#:
#: 取子串而非前缀是刻意的：``set_setting`` / ``update_setting`` / ``setting_value`` 都要命中，
#: ``unregister_project`` 这种**否定前缀 + 动词**的真能力也必须命中 —— 换成「单词相等」或「前缀」
#: 都会漏掉它们，守卫就只剩装饰作用。
#: 不误伤的边界例子：``registry_state``（项目列表帧的注册表健康态）含 ``registr`` 但**不含**
#: ``register``，因此不会把既有的只读项目列表判成「项目注册」。
#: 真出现假阳性（子串巧合）时按 :data:`_ALLOWED_STEM_FALSE_POSITIVES` 加**具名 + 理由**的豁免，
#: 不要改这里的口径。
_FORBIDDEN_REMOTE_STEMS = (
    "setting",
    "config",
    "register",
    "session",
    "history",
    "write",
    "delete",
    "remove",
    "rename",
    "approve",
    "dialog",
)

#: 命令 → 字段白名单的完整期望值（``_FRAME_FIELDS`` 的逐条镜像）。
_EXPECTED_REMOTE_FRAME_FIELDS: dict[str, frozenset[str]] = {
    "cancel": frozenset({"command"}),
    "cancel_run": frozenset({"command", "run_id"}),
    "ping": frozenset({"command"}),
    "projects": frozenset({"command"}),
    "run": frozenset({"command", "prompt", "project_id", "request_id"}),
}

#: 协议层入站 + 出站帧模型：帧面冻结，新增一格的字段就等于新开一格对外可见面。
_REMOTE_FRAME_MODELS: dict[str, type[BaseModel]] = {
    "WsCommandFrame": WsCommandFrame,
    "WsHelloFrame": WsHelloFrame,
    "WsEventFrame": WsEventFrame,
    "WsAckFrame": WsAckFrame,
    "WsCliEventFrame": WsCliEventFrame,
    "WsCliAckFrame": WsCliAckFrame,
    "WsNotificationFrame": WsNotificationFrame,
    "WsProjectsFrame": WsProjectsFrame,
    "WsErrorFrame": WsErrorFrame,
    "ProjectChannelEntry": ProjectChannelEntry,
    "SubmittedRun": SubmittedRun,
}

_EXPECTED_REMOTE_MODEL_FIELDS: dict[str, frozenset[str]] = {
    "WsCommandFrame": frozenset({"command", "prompt", "project_id", "request_id", "run_id"}),
    "WsHelloFrame": frozenset({"type", "version"}),
    "WsEventFrame": frozenset({"type", "event"}),
    "WsAckFrame": frozenset({"type", "command", "run_id", "status"}),
    "WsCliEventFrame": frozenset({"type", "run_id", "event"}),
    "WsCliAckFrame": frozenset({"type", "command", "run_id"}),
    "WsNotificationFrame": frozenset({"type", "notification"}),
    "WsProjectsFrame": frozenset({"type", "projects", "registry_state"}),
    "WsErrorFrame": frozenset({"type", "error"}),
    "ProjectChannelEntry": frozenset({"id", "name", "available"}),
    "SubmittedRun": frozenset({"run_id", "status"}),
}

#: 配置 / 注册 / 会话能力的运行期符号。与上面的**名字**守卫互补：名字守卫挡「帧面变宽」，这一条
#: 挡「WS 模块偷偷去调控制台回调」——只扩字段不扩命令也能漏出能力，所以两层都要有。
_FORBIDDEN_RUNTIME_SYMBOLS = re.compile(
    r"\b(set_setting|write_config|update_project_config|register_project|remove_project"
    r"|rename_project|list_sessions|read_session|session_history)\b"
)


#: 命中词根但已确认正当的名字（小写） → 放行理由。假阳性的**唯一**出口。
#:
#: 键是**精确名**而不是词根：豁免 ``writelines`` 不会连带放过 ``write_config``。理由为空即视为配置
#: 错误（``_forbidden_family_names`` fail loud）—— 不写理由的豁免等于悄悄把守卫撑开。
_ALLOWED_STEM_FALSE_POSITIVES: dict[str, str] = {}


def _forbidden_family_names(names: Iterable[str], *, exemptions: Mapping[str, str] | None = None) -> list[str]:
    """落在 R5 禁用能力族里的名字（子串、大小写不敏感，返回排序后的去重结果）。

    ``exemptions`` 供判据传临时豁免集（默认取 :data:`_ALLOWED_STEM_FALSE_POSITIVES`）；任何豁免
    缺理由即抛 ``ValueError``，让「顺手放宽」在评审时显性暴露。
    """
    allowed = _ALLOWED_STEM_FALSE_POSITIVES if exemptions is None else exemptions
    for name, reason in allowed.items():
        if not reason.strip():
            raise ValueError(f"stem exemption for {name!r} needs a reason")
    return sorted(
        {
            lowered
            for name in names
            if (lowered := name.lower()) not in allowed and any(stem in lowered for stem in _FORBIDDEN_REMOTE_STEMS)
        }
    )


def test_remote_command_surface_is_exactly_five_values() -> None:
    """R5：远程命令集合是**集合相等**的封闭契约——多一条即红，不是「包含这五个」。"""
    assert {command.value for command in WsCommand} == {"cancel", "cancel_run", "ping", "projects", "run"}
    assert len(WsCommand) == 5


def test_remote_command_frame_fields_are_pinned_per_command() -> None:
    """R5：命令 → 字段白名单逐条镜像（给某条命令加字段 = 帧面变宽，必须显性出现在这里）。"""
    assert set(_FRAME_FIELDS) == set(WsCommand)
    actual = {command.value: frozenset(fields) for command, fields in _FRAME_FIELDS.items()}
    assert actual == _EXPECTED_REMOTE_FRAME_FIELDS


def test_frame_models_stay_at_the_pinned_field_sets() -> None:
    """帧面冻结：入站命令帧与七类出站帧的字段集合逐字钉死。"""
    actual = {name: frozenset(model.model_fields) for name, model in _REMOTE_FRAME_MODELS.items()}
    assert actual == _EXPECTED_REMOTE_MODEL_FIELDS


def test_server_frame_types_stay_closed_to_six_values() -> None:
    """帧类型不随命令扩张：``projects`` 是 E75 的响应帧，此后新增类型也要过同一道门。"""
    assert {item.value for item in WsFrameType} == {"ack", "error", "event", "hello", "notification", "projects"}


def test_no_config_register_or_session_family_on_the_remote_surface() -> None:
    """R5 的双向守卫：命令值 + 帧字段名都不落在配置 / 注册 / 会话历史族。"""
    inbound_fields = set(WsCommandFrame.model_fields)
    whitelisted_fields = set().union(*_FRAME_FIELDS.values())
    outbound_fields = set().union(*(set(model.model_fields) for model in _REMOTE_FRAME_MODELS.values()))

    assert _forbidden_family_names(command.value for command in WsCommand) == []
    assert _forbidden_family_names(inbound_fields) == []
    assert _forbidden_family_names(whitelisted_fields) == []
    assert _forbidden_family_names(outbound_fields) == []
    # 阳性控制：匹配器本身必须是活的，否则上面四条断言恒真、什么都证明不了。
    # `unregister_project` 也在内：否定前缀 + 动词的真能力同样要命中（子串口径的理由）。
    assert _forbidden_family_names({"set_config", "register_project", "list_sessions", "unregister_project"}) == [
        "list_sessions",
        "register_project",
        "set_config",
        "unregister_project",
    ]


def test_stem_exemptions_need_a_reason_and_release_only_the_named_symbol() -> None:
    """假阳性的出口是**具名 + 写理由**的豁免，不是放宽词根口径（那样会连真能力一起放过）。"""
    assert _forbidden_family_names({"writelines"}) == ["writelines"]  # 子串碰巧命中
    assert _forbidden_family_names({"writelines"}, exemptions={"writelines": "内置写接口名，非远程能力"}) == []
    # 键是精确名：豁免这个不放过那个。
    assert _forbidden_family_names(
        {"writelines", "write_config"}, exemptions={"writelines": "内置写接口名，非远程能力"}
    ) == ["write_config"]
    with pytest.raises(ValueError, match="needs a reason"):
        _forbidden_family_names({"writelines"}, exemptions={"writelines": "   "})
    # 生产豁免集默认为空且每条都带理由（现状即这份契约）。
    assert all(reason.strip() for reason in _ALLOWED_STEM_FALSE_POSITIVES.values())


@pytest.mark.parametrize(
    "text",
    [
        '{"command":"set_config","key":"MAX_ITERATIONS","value":"30"}',
        '{"command":"register_project","path":"/tmp/p","name":"p"}',
        '{"command":"list_sessions","project_id":"default"}',
        '{"command":"read_session","session_id":"s1"}',
    ],
)
def test_family_commands_are_unknown_on_the_remote_surface(text: str) -> None:
    """命令值层再挡一道：配置 / 注册 / 会话族命令在解析器上就是 ``unknown_command``。"""
    with pytest.raises(WsFrameError) as exc_info:
        parse_command_frame(text)
    assert exc_info.value.kind is WsFrameErrorKind.UNKNOWN_COMMAND


def test_ws_modules_never_reach_config_register_or_session_symbols() -> None:
    """WS 面源码里不出现配置写入 / 项目注册 / 会话浏览的实现符号（R5 的执行面）。"""
    hits = {
        name: _FORBIDDEN_RUNTIME_SYMBOLS.findall((_NETWORK_DIR / name).read_text(encoding="utf-8"))
        for name in _WS_SURFACE_MODULES
    }
    assert {name: found for name, found in hits.items() if found} == {}


def test_config_register_and_session_symbols_stay_in_the_loopback_console() -> None:
    """``network/`` 内这类符号只准住在回环 HTTP 控制台模块里。

    口径说明：``network/`` **整棵树**不是零命中——``register_project`` / ``list_sessions`` 正是回环
    HTTP 端点（``POST /api/projects`` 等）的实现符号，R5 只要求远程注册回 403、不要求删掉本机能力。
    所以判据写成**集合相等**：命中文件集合恰为这三个控制台模块，既挡住「WS 面拿到这些能力」，也
    用「这三个模块确实被匹配到」反证正则本身是活的。
    """
    hitting = {
        path.relative_to(_NETWORK_DIR).as_posix()
        for path in _NETWORK_DIR.rglob("*.py")
        if _FORBIDDEN_RUNTIME_SYMBOLS.search(path.read_text(encoding="utf-8"))
    }
    assert hitting == _LOOPBACK_CONSOLE_MODULES
