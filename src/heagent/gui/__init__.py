"""HeAgent GUI — Textual terminal interface."""

from __future__ import annotations


def gui_main(model: str | None = None, sandbox: str | None = None) -> None:
    """Launch the HeAgent Textual TUI.

    Args:
        model: Override default model name.
        sandbox: Sandbox backend (``"passthrough"`` or ``"firejail"``).
    """
    from heagent.gui.app import HeAgentApp

    app = HeAgentApp()
    app.run()
