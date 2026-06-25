"""Persistent snapshots for loop runs."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

# noqa: TC001 — RunContext/Message/ToolResult 是 Pydantic 模型字段类型，
# 需运行期导入以构建 schema（ruff TC001 为误报）。
from heagent.engine.context import RunContext  # noqa: TC001
from heagent.types import Message, ToolResult  # noqa: TC001


class RunSnapshot(BaseModel):
    """Persisted snapshot of one run."""

    context: RunContext
    prompt: str
    system: str | None = None
    messages: list[Message] = Field(default_factory=list)
    results: list[ToolResult] = Field(default_factory=list)
    final_answer: str | None = None
    error: str | None = None


class RunStore:
    """JSON-backed run checkpoint store."""

    def __init__(self, base_dir: str = ".heagent/runs") -> None:
        self._base = Path(base_dir)

    def start(self, context: RunContext, *, prompt: str, system: str | None = None) -> str:
        """Create or overwrite the initial snapshot for a run."""
        snapshot = RunSnapshot(context=context.model_copy(deep=True), prompt=prompt, system=system)
        return self.save(snapshot)

    def checkpoint(
        self,
        context: RunContext,
        *,
        prompt: str,
        system: str | None = None,
        messages: list[Message] | None = None,
        results: list[ToolResult] | None = None,
        final_answer: str | None = None,
        error: str | None = None,
    ) -> str:
        """Persist the latest state of a run."""
        snapshot = self.load(context.run_id)
        if snapshot is None:
            snapshot = RunSnapshot(context=context.model_copy(deep=True), prompt=prompt, system=system)
        snapshot.context = context.model_copy(deep=True)
        snapshot.prompt = prompt
        snapshot.system = system
        if messages is not None:
            snapshot.messages = [m.model_copy(deep=True) for m in messages]
        if results is not None:
            snapshot.results = [r.model_copy(deep=True) for r in results]
        if final_answer is not None:
            snapshot.final_answer = final_answer
        if error is not None:
            snapshot.error = error
        return self.save(snapshot)

    def save(self, snapshot: RunSnapshot) -> str:
        """Write one snapshot to disk."""
        self._base.mkdir(parents=True, exist_ok=True)
        path = self._path(snapshot.context.run_id)
        payload = snapshot.model_dump(mode="json")
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)

    def load(self, run_id: str) -> RunSnapshot | None:
        """Load one run snapshot if it exists."""
        path = self._path(run_id)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RunSnapshot.model_validate(payload)

    def list_runs(self) -> list[str]:
        """List all persisted run ids."""
        if not self._base.exists():
            return []
        return sorted(path.stem for path in self._base.glob("*.json"))

    def delete(self, run_id: str) -> bool:
        """Delete one stored run snapshot."""
        path = self._path(run_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _path(self, run_id: str) -> Path:
        return self._base / f"{run_id}.json"
