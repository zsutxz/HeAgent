"""74.4 · 事件面零漂移契约钉子（E74 的「不改协议」承诺必须可执行）。

五个用例把「远程项目通道不碰事件面」变成可跑的判据：

① ``WsEventFrame`` 字段集合恰为 ``{type, event}``；② ``WsAckFrame`` 字段集合恰为
``{type, command, run_id, status}``；③ 帧类型集合 ``WsFrameType`` 封闭（六档；项目列表走
``projects`` 响应帧，不借道 ``event``）；
④ golden 事件信封 ``model_dump_json()`` 与固定字面**逐字相等**（客户端按字节兼容，不是按字段名）；
⑤ 事件面（帧层与负载层）带 ``project_id`` 一律被判非法；⑥ WS 路由集与
``tests/fixtures/contract_baselines/transport_routes.json`` 一致 —— 本 epic 不新增任何端点。

④ 是这里唯一「逐字节」的判据：字段集合相等仍允许顺序/默认值漂移，而 golden 字面把顺序、默认值、
``ensure_ascii`` 行为一起钉住。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from heagent.network.http_protocol import RunEventKind, RunEventPayload
from heagent.network.ws_protocol import (
    WsAckFrame,
    WsCommand,
    WsEventFrame,
    WsFrameType,
)

_SRC = Path(__file__).resolve().parents[2] / "src"
_BASELINE = Path(__file__).resolve().parents[1] / "fixtures" / "contract_baselines" / "transport_routes.json"

#: 事件信封的**逐字节**黄金样本（客户端按这个形状比对）。字段顺序与空默认值都在里面，
#: 因此任何「加个字段」「改个默认值」都会让这条断言先红，而不是等到客户端解不出。
_GOLDEN_EVENT_ENVELOPE = (
    '{"type":"event","event":{"kind":"text","seq":7,"text":"你好，世界","tool_name":"",'
    '"tool_target":"","tool_output":"","tool_error":false,"message":"","model":null,"usage":null}}'
)


def test_event_frame_holds_exactly_the_envelope_fields() -> None:
    """事件帧只有 ``type`` 与 ``event``：``run_id`` 由 URL 承担，项目归属由客户端本地映射。"""
    assert set(WsEventFrame.model_fields) == {"type", "event"}


def test_ack_frame_holds_exactly_four_fields() -> None:
    """ack 的四项即客户端的全部依赖；``session_id`` / ``project_id`` 都不能进来。"""
    assert set(WsAckFrame.model_fields) == {"type", "command", "run_id", "status"}
    assert "session_id" not in WsAckFrame.model_fields


def test_frame_type_set_stays_closed() -> None:
    """帧类型封闭为六档：``projects``（E75）是**命令响应**帧，事件面仍只有 ``event`` 一档。

    「项目通道不改事件面」这条承诺的判据是事件信封（下面那条逐字节 golden）与 ``WsEventFrame``
    的字段集合，不是「不许新增任何帧类型」——项目列表既不是 run 事件、也没有 ``run_id`` /
    ``seq``，塞进 ``event`` 才会真破坏事件面。
    """
    assert {item.value for item in WsFrameType} == {"hello", "event", "ack", "error", "notification", "projects"}


def test_golden_event_envelope_is_byte_identical() -> None:
    """golden 事件信封逐字相等（顺序、默认值、``ensure_ascii`` 行为一起钉住）。"""
    payload = RunEventPayload(kind=RunEventKind.TEXT, seq=7, text="你好，世界")

    assert WsEventFrame(event=payload).model_dump_json() == _GOLDEN_EVENT_ENVELOPE


@pytest.mark.parametrize(
    "raw",
    [
        # 帧层：事件帧不接受项目归属（D7：run→project 映射由客户端本地维护）。
        {"type": "event", "event": {"kind": "text", "seq": 1}, "project_id": "p1234abcd"},
        # 负载层：``RunEventPayload`` 同样 ``extra="forbid"``，塞进去也解不出。
        {"type": "event", "event": {"kind": "text", "seq": 1, "project_id": "p1234abcd"}},
    ],
)
def test_event_surface_rejects_project_id(raw: dict[str, object]) -> None:
    """事件面**两个层级**都拒绝 ``project_id``：它不是「可忽略的额外字段」。"""
    with pytest.raises(ValidationError):
        WsEventFrame.model_validate(raw)


def test_ws_route_set_matches_the_contract_baseline() -> None:
    """WS 路由集不变：仍只有提交 / 订阅 / 旁路 / 通知四条路径常量，与基线逐字一致。"""
    baseline = json.loads(_BASELINE.read_text(encoding="utf-8"))
    frozen = baseline["path_constants"]["src/heagent/network/ws_host.py"]

    source = (_SRC / "heagent" / "network" / "ws_host.py").read_text(encoding="utf-8")
    found = dict(
        re.findall(r'^(RUNS_WS_PATH|RUNS_SUBMIT_PATH|CLI_WS_PATH|NOTIFICATIONS_WS_PATH) = "([^"]+)"', source, re.M)
    )

    assert found == frozen
    assert frozen["RUNS_WS_PATH"] == "/api/runs/{run_id}/ws"
    # 项目通道复用既有订阅端点：取消与提交都不带自己的路径。
    assert "project" not in json.dumps(frozen)
    assert {item.value for item in WsCommand} == {"run", "cancel", "cancel_run", "ping", "projects"}
