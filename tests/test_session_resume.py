"""Tests for CLI session resume (Epic 30)."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from heagent.cli import _resolve_session_id, main
from heagent.context.session import SessionStore


class TestResolveSessionId:
    def test_resume_session_returns_specified_id(self, tmp_path) -> None:
        store = SessionStore(base_dir=str(tmp_path))
        assert _resolve_session_id(store, resume_session="abc123") == "abc123"

    def test_continue_returns_recent_when_present(self, tmp_path) -> None:
        store = SessionStore(base_dir=str(tmp_path))
        store.save("sess1", [])
        sid = _resolve_session_id(store, continue_session=True)
        assert sid == "sess1"

    def test_continue_falls_back_to_new_when_no_history(self, tmp_path) -> None:
        store = SessionStore(base_dir=str(tmp_path))
        sid = _resolve_session_id(store, continue_session=True)
        assert sid  # 非空
        assert len(sid) == 8  # 随机 hex 新 id

    def test_default_returns_new_id(self, tmp_path) -> None:
        store = SessionStore(base_dir=str(tmp_path))
        sid = _resolve_session_id(store)
        assert sid
        assert len(sid) == 8

    def test_resume_takes_precedence_over_continue(self, tmp_path) -> None:
        store = SessionStore(base_dir=str(tmp_path))
        store.save("sess1", [])
        sid = _resolve_session_id(store, continue_session=True, resume_session="explicit")
        assert sid == "explicit"


class TestCLISessionOptions:
    def test_run_help_shows_session_options(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "--continue" in result.output
        assert "--resume" in result.output
