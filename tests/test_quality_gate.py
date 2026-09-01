from __future__ import annotations

from types import SimpleNamespace

from scripts import quality_gate


def test_quality_gate_stops_on_first_failure(monkeypatch) -> None:
    commands = (("first", ["first"]), ("second", ["second"]))
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(quality_gate, "COMMANDS", commands)
    monkeypatch.setattr(quality_gate.subprocess, "run", fake_run)

    assert quality_gate.main() == 7
    assert calls == [["first"]]


def test_quality_gate_reports_missing_executable(monkeypatch) -> None:
    monkeypatch.setattr(quality_gate, "COMMANDS", (("missing", ["missing"]),))

    def fake_run(command, **kwargs):
        raise OSError("not found")

    monkeypatch.setattr(quality_gate.subprocess, "run", fake_run)
    assert quality_gate.main() == 1
