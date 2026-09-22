"""事件传输层测试 — events/protocol.py + events/sink.py（JSONL 契约 / rollout / replay / CLI）。"""

from __future__ import annotations

import json
import logging
from io import StringIO
from typing import TYPE_CHECKING, ClassVar

import pytest
from click.testing import CliRunner

from heagent.agent.loop import AgentLoop
from heagent.cli import main
from heagent.config import reset_settings
from heagent.engine.observability import EngineEvent
from heagent.exceptions import PolicyViolation, ToolError
from heagent.events.protocol import (
    ASSISTANT_MESSAGE_KIND,
    KNOWN_KINDS,
    SCHEMA_VERSION,
    from_engine_event,
    make_event,
)
from heagent.events.sink import JsonlSink, default_rollout_dir, read_rollout, render_event
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, TokenUsage

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# 对外契约的字段集（黄金测试基准）：改字段必须先 bump SCHEMA_VERSION 并更新此处。
# v2（Phase 5 C1）：+duration_ms / error_kind（旧文件缺省读、新字段被旧码 extra=ignore）。
_EXPECTED_FIELDS = {
    "schema_version",
    "seq",
    "ts",
    "run_id",
    "iteration",
    "kind",
    "tool",
    "target",
    "duration_ms",
    "error_kind",
    "details",
}


class _StubProvider:
    """返回单个最终答案的内存 provider（端到端冒烟用）。"""

    def __init__(self, content: str = "done") -> None:
        self._content = content

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        return ProviderResponse(
            content=self._content,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="stub",
            finish_reason="stop",
        )

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


@pytest.fixture(autouse=True)
def _clean_settings() -> Iterator[None]:
    reset_settings()
    yield
    reset_settings()


def _engine_event(event_type: str, **kwargs: object) -> EngineEvent:
    return EngineEvent(event_type=event_type, **kwargs)  # type: ignore[arg-type]


def _lines(stream: StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


# ══════════════════════════════════════════════════════════════════════
# 协议：RunEvent 的字段集与序列化
# ══════════════════════════════════════════════════════════════════════


class TestRunEventProtocol:
    def test_field_set_is_the_stable_contract(self) -> None:
        """黄金测试：JSONL 的字段集是版本化契约，不得漂移。"""
        payload = json.loads(make_event("run_started", seq=1).to_jsonl())
        assert set(payload) == _EXPECTED_FIELDS
        assert payload["schema_version"] == SCHEMA_VERSION == "2"  # v2（Phase 5 C1）

    def test_jsonl_is_a_single_line_even_with_newlines(self) -> None:
        """正文含换行/制表符时仍须是单行（JSON 转义），否则消费方按行解析会错位。"""
        event = make_event(
            ASSISTANT_MESSAGE_KIND,
            seq=1,
            details={"content": 'line1\nline2\t"quoted"'},
        )
        line = event.to_jsonl()
        assert "\n" not in line
        assert json.loads(line)["details"]["content"] == 'line1\nline2\t"quoted"'

    def test_non_serializable_detail_degrades_to_string(self) -> None:
        """details 里出现不可序列化对象时降级为字符串——观测层问题不得打断 run。"""
        line = make_event("run_started", seq=1, details={"obj": object()}).to_jsonl()
        assert isinstance(json.loads(line)["details"]["obj"], str)

    def test_from_engine_event_maps_every_field(self) -> None:
        """映射无信息丢失：kind/tool/target/iteration/run_id/details/ts 逐字段对齐。"""
        source = _engine_event(
            "tool_call_completed",
            run_id="run-1",
            iteration=3,
            tool_name="shell",
            target="ls -la",
            details={"mode": "direct", "content_length": 12},
            timestamp="2026-09-15T10:00:00",
        )

        event = from_engine_event(source, seq=7)

        assert event.kind == "tool_call_completed"
        assert (event.run_id, event.iteration, event.tool, event.target) == ("run-1", 3, "shell", "ls -la")
        assert event.details == {"mode": "direct", "content_length": 12}
        assert event.ts == "2026-09-15T10:00:00"
        assert event.seq == 7

    def test_known_kinds_documents_engine_vocabulary_but_excludes_transport_event(self) -> None:
        """KNOWN_KINDS 是引擎事件词典（文档/测试依据），传输层事件不在其中。"""
        assert {"run_started", "run_completed", "run_failed", "tool_call_blocked"} <= KNOWN_KINDS
        assert ASSISTANT_MESSAGE_KIND not in KNOWN_KINDS

    def test_missing_ts_is_filled_with_local_iso_timestamp(self) -> None:
        event = make_event("run_started", seq=1)
        assert len(event.ts) == len("2026-09-15T10:00:00")


# ══════════════════════════════════════════════════════════════════════
# JsonlSink：stdout 流与序号
# ══════════════════════════════════════════════════════════════════════


class TestJsonlSinkStream:
    def test_writes_one_json_line_per_event(self) -> None:
        stream = StringIO()
        sink = JsonlSink(stream=stream)

        sink.handle(_engine_event("run_started", run_id="r1"))
        sink.handle(_engine_event("iteration_started", run_id="r1", iteration=1))
        sink.handle(_engine_event("run_completed", run_id="r1", iteration=1))

        payloads = _lines(stream)
        assert [item["kind"] for item in payloads] == ["run_started", "iteration_started", "run_completed"]
        assert [item["seq"] for item in payloads] == [1, 2, 3]
        assert sink.seq == 3
        assert sink.writes_stdout is True
        assert sink.writes_rollout is False

    def test_seq_is_monotonic_across_engine_events_and_assistant_message(self) -> None:
        """stdout 流（或文件）里 seq 严格递增，消费方可据此判定丢行/乱序。"""
        stream = StringIO()
        sink = JsonlSink(stream=stream)
        sink.handle(_engine_event("run_started", run_id="r1"))
        sink.handle(_engine_event("run_completed", run_id="r1"))
        sink.assistant_message("final answer")

        seqs = [item["seq"] for item in _lines(stream)]
        assert seqs == sorted(seqs) == [1, 2, 3]

    def test_assistant_message_carries_content_and_last_run_id(self) -> None:
        stream = StringIO()
        sink = JsonlSink(stream=stream)
        sink.handle(_engine_event("run_completed", run_id="run-42"))

        event = sink.assistant_message("hello")

        assert event.kind == ASSISTANT_MESSAGE_KIND
        assert event.run_id == "run-42"
        assert event.details["content"] == "hello"
        assert event.details["content_length"] == 5
        assert _lines(stream)[-1]["kind"] == ASSISTANT_MESSAGE_KIND

    def test_unknown_kind_passes_through_unchanged(self) -> None:
        """开集 kind：引擎新增事件无需改协议即可被消费。"""
        stream = StringIO()
        sink = JsonlSink(stream=stream)

        sink.handle(_engine_event("brand_new_engine_event", run_id="r1", details={"a": 1}))

        payload = _lines(stream)[0]
        assert payload["kind"] == "brand_new_engine_event"
        assert payload["details"] == {"a": 1}

    def test_sink_without_targets_is_a_noop(self) -> None:
        """既无流也无 rollout 目录时，订阅它不产生任何输出（也不抛异常）。"""
        sink = JsonlSink()

        sink.handle(_engine_event("run_started", run_id="r1"))

        assert sink.writes_stdout is False
        assert sink.writes_rollout is False
        assert sink.seq == 1


# ══════════════════════════════════════════════════════════════════════
# rollout 落盘：分片、LF、失败降级
# ══════════════════════════════════════════════════════════════════════


class TestRolloutPersistence:
    def test_default_rollout_dir_is_project_internal_state(self, tmp_path: Path) -> None:
        assert default_rollout_dir(tmp_path) == tmp_path / ".heagent" / "runs"

    def test_rollout_is_sharded_per_run_and_appends(self, tmp_path: Path) -> None:
        first = JsonlSink(rollout_dir=tmp_path)
        first.handle(_engine_event("run_started", run_id="r1"))
        first.handle(_engine_event("run_completed", run_id="r1"))
        second = JsonlSink(rollout_dir=tmp_path)
        second.handle(_engine_event("run_started", run_id="r2"))

        r1 = tmp_path / "r1" / "rollout.jsonl"
        r2 = tmp_path / "r2" / "rollout.jsonl"
        assert len(r1.read_text(encoding="utf-8").splitlines()) == 2
        assert len(r2.read_text(encoding="utf-8").splitlines()) == 1

        # 同一 run_id 复跑（resume）为顺序追加，不覆盖
        third = JsonlSink(rollout_dir=tmp_path)
        third.handle(_engine_event("run_resumed", run_id="r1"))
        assert len(r1.read_text(encoding="utf-8").splitlines()) == 3

    def test_run_id_missing_falls_back_to_unknown_shard(self, tmp_path: Path) -> None:
        sink = JsonlSink(rollout_dir=tmp_path)

        sink.handle(_engine_event("run_started"))

        assert (tmp_path / "unknown" / "rollout.jsonl").exists()

    def test_rollout_uses_lf_line_endings(self, tmp_path: Path) -> None:
        """JSONL 必须 LF：Windows 上的平台行尾翻译会让按行消费的工具读到 \\r。"""
        sink = JsonlSink(rollout_dir=tmp_path)
        sink.handle(_engine_event("run_started", run_id="r1"))
        sink.assistant_message("ok")

        raw = (tmp_path / "r1" / "rollout.jsonl").read_bytes()

        assert b"\r\n" not in raw
        assert raw.endswith(b"\n")
        assert b'"kind": "assistant_message"' in raw

    def test_rollout_write_failure_is_logged_not_raised(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """写盘失败（此处以「父路径是文件」构造）只告警，不影响主循环。"""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        sink = JsonlSink(rollout_dir=blocker)

        with caplog.at_level(logging.WARNING, logger="heagent.events.sink"):
            sink.handle(_engine_event("run_started", run_id="r1"))  # 不得抛异常

        assert any("Failed to append rollout line" in record.message for record in caplog.records)

    def test_read_rollout_round_trips_the_written_events(self, tmp_path: Path) -> None:
        sink = JsonlSink(rollout_dir=tmp_path)
        sink.handle(_engine_event("run_started", run_id="r1", details={"model": "stub"}))
        sink.handle(_engine_event("tool_call_started", run_id="r1", tool_name="shell", target="ls"))
        sink.assistant_message("answer")

        events = read_rollout(tmp_path / "r1" / "rollout.jsonl")

        assert [event.kind for event in events] == ["run_started", "tool_call_started", ASSISTANT_MESSAGE_KIND]
        assert events[1].tool == "shell"
        assert events[1].target == "ls"
        assert events[0].details == {"model": "stub"}
        assert events[2].details["content"] == "answer"

    def test_read_rollout_skips_malformed_lines_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """crash 截断的尾行 / 脏行跳过并告警，不毁整次回放。"""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            make_event("run_started", seq=1, run_id="r1").to_jsonl() + "\n" + '{"kind": "run_star\n' + "\n",
            encoding="utf-8",
        )

        with caplog.at_level(logging.WARNING, logger="heagent.events.sink"):
            events = read_rollout(path)

        assert [event.kind for event in events] == ["run_started"]
        assert any("malformed rollout line" in record.message for record in caplog.records)


# ══════════════════════════════════════════════════════════════════════
# render_event（replay 的人读渲染）
# ══════════════════════════════════════════════════════════════════════


class TestRenderEvent:
    def test_tool_event_shows_tool_and_target(self) -> None:
        event = from_engine_event(
            _engine_event("tool_call_completed", run_id="r1", iteration=2, tool_name="shell", target="pytest -q"),
            seq=1,
        )

        line = render_event(event)

        assert "[tool_call_completed]" in line
        assert "shell → pytest -q" in line
        assert "iter=2" in line

    def test_run_event_shows_run_id(self) -> None:
        line = render_event(from_engine_event(_engine_event("run_started", run_id="run-9"), seq=1))
        assert "[run_started]" in line
        assert "run=run-9" in line

    def test_assistant_message_renders_content_verbatim(self) -> None:
        event = make_event(ASSISTANT_MESSAGE_KIND, seq=2, run_id="r1", details={"content": "answer\n第二行"})
        line = render_event(event)
        assert "[assistant_message]" in line
        assert "answer\n第二行" in line


# ══════════════════════════════════════════════════════════════════════
# 端到端：循环事件 ⊆ 协议词典；CLI --json / replay
# ══════════════════════════════════════════════════════════════════════


class TestEventStreamEndToEnd:
    async def test_loop_run_emits_known_kinds_as_pure_jsonl(self, tmp_path: Path, monkeypatch) -> None:
        """真实 loop 一轮的事件：全部落在 KNOWN_KINDS 内，且 stdout 流是纯 JSONL。"""
        monkeypatch.chdir(tmp_path)
        stream = StringIO()
        sink = JsonlSink(stream=stream)
        loop = AgentLoop(_StubProvider("done"), max_iterations=5)
        loop.engine.events.subscribe(sink)

        result = await loop.run("hi")
        sink.assistant_message(result)

        payloads = _lines(stream)
        kinds = [item["kind"] for item in payloads]
        assert result == "done"
        assert set(kinds) <= KNOWN_KINDS | {ASSISTANT_MESSAGE_KIND}
        assert {"run_started", "iteration_started", "provider_call_started", "run_completed"} <= set(kinds)
        assert kinds[0] == "run_started"
        assert kinds[-1] == ASSISTANT_MESSAGE_KIND
        assert [item["seq"] for item in payloads] == list(range(1, len(payloads) + 1))

    def test_replay_command_renders_human_lines(self, tmp_path: Path) -> None:
        sink = JsonlSink(rollout_dir=tmp_path)
        sink.handle(_engine_event("run_started", run_id="r1"))
        sink.handle(_engine_event("tool_call_started", run_id="r1", tool_name="shell", target="ls"))
        sink.assistant_message("final")
        path = tmp_path / "r1" / "rollout.jsonl"

        result = CliRunner().invoke(main, ["replay", str(path)])

        assert result.exit_code == 0
        assert "[run_started]" in result.output
        assert "shell → ls" in result.output
        assert "final" in result.output

    def test_replay_command_json_flag_emits_raw_jsonl(self, tmp_path: Path) -> None:
        sink = JsonlSink(rollout_dir=tmp_path)
        sink.handle(_engine_event("run_started", run_id="r1"))
        path = tmp_path / "r1" / "rollout.jsonl"

        result = CliRunner().invoke(main, ["replay", str(path), "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output.strip())
        assert payload["kind"] == "run_started"

    def test_replay_command_reports_empty_file(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("\n\n", encoding="utf-8")

        result = CliRunner().invoke(main, ["replay", str(path)])

        assert result.exit_code == 0
        assert "no events" in result.output

    def test_run_help_lists_json_option(self) -> None:
        """--json 挂在共享的 run 选项集上（默认命令 heagent "…" --json 同样可用）。"""
        result = CliRunner().invoke(main, ["run", "--help"])

        assert result.exit_code == 0
        assert "--json" in result.output


# --- Phase 5 C1：耗时/失败分类契约 ---


class TestErrorKindMapping:
    """error_kind_for：封闭映射 + exception 兜底 + explicit 覆盖。"""

    def test_known_exception_types(self) -> None:
        from asyncio import CancelledError

        from heagent.events.protocol import (
            ERROR_KIND_CANCELLED,
            ERROR_KIND_POLICY_DENIED,
            ERROR_KIND_TIMEOUT,
            ERROR_KIND_TOOL_ERROR,
            error_kind_for,
        )

        assert error_kind_for(TimeoutError("t")) == ERROR_KIND_TIMEOUT
        assert error_kind_for(CancelledError()) == ERROR_KIND_CANCELLED
        assert error_kind_for(PolicyViolation("p")) == ERROR_KIND_POLICY_DENIED
        assert error_kind_for(ToolError("x")) == ERROR_KIND_TOOL_ERROR

    def test_safety_violation_maps_to_safety_blocked(self) -> None:
        from heagent.events.protocol import ERROR_KIND_SAFETY_BLOCKED, error_kind_for
        from heagent.exceptions import SafetyViolation

        assert error_kind_for(SafetyViolation("s")) == ERROR_KIND_SAFETY_BLOCKED

    def test_unknown_exception_falls_back_to_exception(self) -> None:
        from heagent.events.protocol import ERROR_KIND_EXCEPTION, error_kind_for

        assert error_kind_for(RuntimeError("whatever")) == ERROR_KIND_EXCEPTION

    def test_explicit_overrides_type_mapping(self) -> None:
        from heagent.events.protocol import error_kind_for

        assert error_kind_for(RuntimeError("unknown tool x"), explicit="unknown_tool") == "unknown_tool"


class TestFromEngineEventPromotion:
    """from_engine_event：details 中的 duration_ms/error_kind 提升到顶层并摘除。"""

    def test_promotes_and_pops_timing_fields(self) -> None:
        from heagent.events.protocol import from_engine_event

        class _FakeEvent:
            event_type = "tool_call_completed"
            timestamp = ""
            run_id = "r1"
            iteration = 2
            tool_name = "shell"
            target = "ls"
            details: ClassVar[dict] = {"mode": "direct", "duration_ms": 1234, "error_kind": ""}

        event = from_engine_event(_FakeEvent(), seq=7)  # type: ignore[arg-type]
        assert event.duration_ms == 1234
        assert event.error_kind == ""
        assert event.details == {"mode": "direct"}  # 已摘除，不重复携带
        assert event.seq == 7

    def test_non_int_duration_falls_back_to_zero(self) -> None:
        from heagent.events.protocol import from_engine_event

        class _FakeEvent:
            event_type = "run_completed"
            timestamp = ""
            run_id = ""
            iteration = 0
            tool_name = ""
            target = ""
            details: ClassVar[dict] = {"duration_ms": "oops"}

        event = from_engine_event(_FakeEvent(), seq=1)  # type: ignore[arg-type]
        assert event.duration_ms == 0


class TestV1RolloutBackCompat:
    """v1 rollout（无 duration_ms/error_kind）被 v2 代码读取 → 缺省值。"""

    def test_read_v1_line_with_defaults(self, tmp_path) -> None:
        from heagent.events.sink import read_rollout

        path = tmp_path / "rollout.jsonl"
        v1_line = (
            '{"schema_version": "1", "seq": 1, "ts": "2026-01-01T00:00:00", "run_id": "r", '
            '"iteration": 0, "kind": "run_started", "tool": "", "target": "", "details": {}}'
        )
        path.write_text(v1_line + "\n", encoding="utf-8")
        events = read_rollout(path)
        assert len(events) == 1
        assert events[0].duration_ms == 0
        assert events[0].error_kind == ""
        assert events[0].schema_version == "1"  # 溯源：文件声明什么版本就读回什么


class TestRenderEventTiming:
    """render_event：有值时追加 [Nms] / error_kind（V3）。"""

    def test_renders_duration_and_error_kind(self) -> None:
        from heagent.events.protocol import make_event
        from heagent.events.sink import render_event

        event = make_event("tool_call_failed", seq=1, tool="shell", duration_ms=250, error_kind="timeout")
        rendered = render_event(event)
        assert "[250ms]" in rendered
        assert "error_kind=timeout" in rendered

    def test_omits_defaults(self) -> None:
        from heagent.events.protocol import make_event
        from heagent.events.sink import render_event

        rendered = render_event(make_event("run_started", seq=1))
        assert "[0ms]" not in rendered
        assert "error_kind=" not in rendered
