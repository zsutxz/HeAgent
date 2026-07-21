"""Tests for SwitchableProvider."""

from __future__ import annotations

import pytest

from heagent.types import Message, ProviderResponse, Role, TokenUsage


class _FakeProvider:
    """A fake provider that returns a canned response tagged with its name."""

    def __init__(self, name: str, model: str = "fake-model", supports_streaming: bool = True) -> None:
        self._name = name
        self._model = model
        self._streaming = supports_streaming
        self._send_count = 0

    async def send(self, messages, *, tools=None):
        self._send_count += 1
        return ProviderResponse(
            content=f"response from {self._name}",
            tool_calls=[],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model=self._model,
            finish_reason="stop",
        )

    async def stream(self, messages, *, tools=None):
        yield ProviderResponse(
            content=f"stream from {self._name}",
            tool_calls=[],
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model=self._model,
            finish_reason="stop",
        )

    def get_metadata(self):
        from heagent.providers.base import ProviderMetadata

        return ProviderMetadata(
            name=self._name,
            model=self._model,
            supports_streaming=self._streaming,
            supports_tools=True,
        )


@pytest.fixture
def fake_providers() -> dict:
    """Return a dict of three fake providers."""
    return {
        "alpha": _FakeProvider("alpha", model="alpha-v1"),
        "beta": _FakeProvider("beta", model="beta-v2"),
        "gamma": _FakeProvider("gamma", model="gamma-v3"),
    }


# ------------------------------------------------------------------
# Construction
# ------------------------------------------------------------------


def test_requires_at_least_one_provider() -> None:
    """Empty dict should raise ValueError."""
    from heagent.providers.switchable import SwitchableProvider

    with pytest.raises(ValueError, match="at least one"):
        SwitchableProvider({}, default="x")


def test_default_must_exist_in_pool() -> None:
    """Default name must be in the provider dict."""
    from heagent.providers.switchable import SwitchableProvider

    with pytest.raises(ValueError, match="not in provider pool"):
        SwitchableProvider({"a": _FakeProvider("a")}, default="b")


def test_construction_with_single_provider(fake_providers) -> None:
    """Single provider pool still works."""
    from heagent.providers.switchable import SwitchableProvider

    sp = SwitchableProvider({"alpha": fake_providers["alpha"]}, default="alpha")
    assert sp.active == "alpha"
    assert sp.names == ["alpha"]


# ------------------------------------------------------------------
# Switch
# ------------------------------------------------------------------


def test_switch_valid(fake_providers) -> None:
    """Switching to a valid provider updates active."""
    from heagent.providers.switchable import SwitchableProvider

    sp = SwitchableProvider(fake_providers, default="alpha")
    assert sp.active == "alpha"

    sp.switch("beta")
    assert sp.active == "beta"

    sp.switch("gamma")
    assert sp.active == "gamma"


def test_switch_invalid(fake_providers) -> None:
    """Switching to an unknown name raises."""
    from heagent.providers.switchable import SwitchableProvider

    sp = SwitchableProvider(fake_providers, default="alpha")
    with pytest.raises(ValueError, match="Unknown provider"):
        sp.switch("delta")


# ------------------------------------------------------------------
# Info / names
# ------------------------------------------------------------------


def test_info_returns_all_with_active_marker(fake_providers) -> None:
    """info() returns metadata for all providers, marking the active one."""
    from heagent.providers.switchable import SwitchableProvider

    sp = SwitchableProvider(fake_providers, default="alpha")
    info = sp.info()

    assert set(info.keys()) == {"alpha", "beta", "gamma"}
    assert info["alpha"].active is True
    assert info["beta"].active is False
    assert info["gamma"].active is False

    sp.switch("beta")
    info = sp.info()
    assert info["alpha"].active is False
    assert info["beta"].active is True


def test_names_returns_list(fake_providers) -> None:
    """names returns a list of all provider names."""
    from heagent.providers.switchable import SwitchableProvider

    sp = SwitchableProvider(fake_providers, default="alpha")
    assert sorted(sp.names) == ["alpha", "beta", "gamma"]


# ------------------------------------------------------------------
# send delegation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_delegates_to_active(fake_providers) -> None:
    """send() calls the active provider and returns its response."""
    from heagent.providers.switchable import SwitchableProvider

    sp = SwitchableProvider(fake_providers, default="alpha")
    msg = [Message(role=Role.USER, content="hello")]

    resp = await sp.send(msg)
    assert resp.content == "response from alpha"
    assert fake_providers["alpha"]._send_count == 1
    assert fake_providers["beta"]._send_count == 0

    sp.switch("beta")
    resp = await sp.send(msg)
    assert resp.content == "response from beta"
    assert fake_providers["beta"]._send_count == 1


# ------------------------------------------------------------------
# stream delegation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_delegates_to_active(fake_providers) -> None:
    """stream() yields chunks from the active provider."""
    from heagent.providers.switchable import SwitchableProvider

    sp = SwitchableProvider(fake_providers, default="alpha")
    msg = [Message(role=Role.USER, content="hello")]

    chunks = [c async for c in sp.stream(msg)]
    assert len(chunks) == 1
    assert chunks[0].content == "stream from alpha"

    sp.switch("gamma")
    chunks = [c async for c in sp.stream(msg)]
    assert len(chunks) == 1
    assert chunks[0].content == "stream from gamma"


# ------------------------------------------------------------------
# get_metadata
# ------------------------------------------------------------------


def test_get_metadata_reflects_active(fake_providers) -> None:
    """get_metadata returns the active provider's metadata with switchable prefix."""
    from heagent.providers.switchable import SwitchableProvider

    sp = SwitchableProvider(fake_providers, default="alpha")
    meta = sp.get_metadata()
    assert meta.name == "switchable:alpha"
    assert meta.model == "alpha-v1"

    sp.switch("beta")
    meta = sp.get_metadata()
    assert meta.name == "switchable:beta"
    assert meta.model == "beta-v2"
