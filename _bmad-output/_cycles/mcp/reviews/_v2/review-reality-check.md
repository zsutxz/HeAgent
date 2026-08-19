---
review-lens: reality-check
reviewer: claude (glm-5.2)
target: _bmad-output/mcp-client-v2/ARCHITECTURE-SPINE.md
date: 2026-07-17
verdict: PASS-WITH-FINDINGS
---

# Reality-Check Review — MCP Client V2 Architecture Spine

**Lens.** Verify every committed decision in the spine was checked against the real code
(`src/heagent/`) and the real installed `mcp` SDK — not asserted from training data. Flag
anything asserted-but-unconfirmed, or out of date.

**Method.** Read the spine + PRD end to end. Read the cited code files (`engine/policy.py`,
`agent/tool_execution.py`, `tools/mcp/manager.py`, `tools/mcp/mapping.py`, `cli.py`,
`types.py`, `tools/registry.py`). Probed the installed `mcp` 1.28.0 SDK at runtime for
`ClientSession` method surface, `Tool.annotations` shape, and primitive result types.
Cross-checked `pyproject.toml` for the version pin.

**Verdict: PASS-WITH-FINDINGS.** Every load-bearing committed decision (AD-1 … AD-8) and
every prerequisite claim ("V1 sessions unreachable from manager", "no existing CLI slash
mechanism", "two evaluate call sites", "7-step verdict order", "ClientSession exposes
resources/prompts primitives") is **confirmed by code or SDK inspection**. Findings below
are LOW severity — design details / nits for story-level, not spine defects.

---

## 1. Spine claims that are CONFIRMED against code / SDK

### 1.1 mcp SDK pin (Stack table) — CONFIRMED

- Spine: `mcp >=1.28,<2` (installed 1.28.0; `ClientSession` exposes
  `list_resources`/`read_resource`/`list_prompts`/`get_prompt`/`list_resource_templates`/
  `subscribe_resource`; "本周期仅消费前四个").
- `pyproject.toml`: `"mcp>=1.28,<2"` — matches exactly.
- `python -c "import importlib.metadata; ..."` → installed `mcp 1.28.0`.
- `hasattr(ClientSession, n)` for all six methods → `True`. Spine claim accurate.
- Bonus: inspected signatures —
  `list_resources(self, cursor=None, *, params=None) -> ListResourcesResult`,
  `read_resource(self, uri: AnyUrl) -> ReadResourceResult`,
  `list_prompts(...) -> ListPromptsResult`,
  `get_prompt(self, name, arguments=None) -> GetPromptResult`. All match what AD-5/AD-7
  bridge code will need.
- Result-type field shapes (`resources` / `contents` / `prompts` / `messages`) all present.

### 1.2 AD-1 (evaluate_tool_call signature + two call sites) — CONFIRMED

- Spine: "`PolicyEngine.evaluate_tool_call(call, *, context=None, schema=None)` 增可选 kwarg
  … 调用方在裁决前 `schema = loop.registry.get_schema(call.name)` 并传入 … 两个 evaluate
  调用点（正常路径 + ledger 缓存命中复核）都传 schema."
- `engine/policy.py:125-130` — signature is **exactly**
  `def evaluate_tool_call(self, call: ToolCall, *, context: RunContext | None = None) -> PolicyVerdict`.
  Adding `schema: ToolSchema | None = None` as a keyword-only arg is mechanical; existing
  call sites continue to work unchanged during migration.
- `agent/tool_execution.py` — exactly **two** call sites, both already present:
  - **L82** (ledger cache-hit re-check):
    `cached_verdict = loop.engine.policy.evaluate_tool_call(call, context=run_context)`
  - **L102** (normal path):
    `verdict = loop.engine.policy.evaluate_tool_call(call, context=run_context)`
  - Spine's "两处" claim is literally correct.
- `tools/registry.py:62` — `def get_schema(self, name: str) -> ToolSchema | None` already
  exists (used today by `manager._discover_and_register` at L238). The lookup the spine
  prescribes is a one-liner against an existing API, not a new primitive.

### 1.3 AD-2 (7-step verdict order + metadata.approved_tools semantics) — CONFIRMED

- Spine: "`PolicyEngine` 在既有 7 步裁决的审批步内 … 授权语义沿用既有
  `metadata.approved_tools`（含 `*` / MCP `__mcp__`)."
- `engine/policy.py` module docstring (L8-17) lists exactly 7 short-circuit steps in the
  order: (1) allowlist → BLOCKED, (2) blocklist → BLOCKED, (3) `block_mcp_tools` → BLOCKED,
  (4) path fence → BLOCKED, (5) approval → APPROVAL_REQUIRED, (6) sandbox →
  SANDBOX_REQUIRED, (7) else DIRECT. The code path in `evaluate_tool_call` (L137-187)
  matches this order. AD-2's "approval step" is unambiguously step 5.
- `_requires_approval` (L225-227) returns `call.name in self.approval_tools or
  (self.approval_mcp_tools and self._is_mcp_tool(call))` — matches AD-2 Rule 1 exactly
  ("`approval_tools` 含该名 / `approval_mcp_tools` 开关且为 MCP 工具").
- `_approval_granted` (L240-248) reads `metadata.approved_tools`, accepts `"*"` or
  `call.name`, and for MCP tools accepts `"__mcp__"`. Confirmed — the spine's reuse claim
  is accurate, no new authorization channel needs to be invented.

### 1.4 AD-4 (V1 sessions unreachable from manager) — CONFIRMED REAL PREREQUISITE

- Spine: "V1 session 仅存活于 `_server_loop` task 内、被 tool 闭包捕获、manager 不可达."
- `tools/mcp/manager.py` — the manager instance state is:
  - `_server_tasks: list[Task]`, `_stops: list[Event]`, `_registered: dict[str, list[str]]`
    (server → namespaced tool names). That's it.
  - **There is NO `_sessions` dict.** The session object is created at `_server_loop` L181
    (`session: ClientSession = await cm.__aenter__()`) as a task-local, then passed as an
    argument to `_discover_and_register(name, session)` and `_watch(name, session, stop)`,
    and finally captured in the per-tool closure by `_make_handler(session, tool.name)`
    (L241, closure at L255-257).
- Therefore AD-4 is a **real prerequisite**, not imaginary: any Resources/Prompts bridge
  that wants to reach the session today has no manager-level handle. Adding
  `self._sessions: dict[str, ClientSession]` and registering in `_server_loop` after
  `session.initialize()` succeeds is the natural fix. The spine's Rule (register in
  `_server_loop` after init; pop in `_unregister_server`/`_unregister_all`) is feasible
  against the existing lifecycle — `_unregister_server` (L261) and `_unregister_all` (L266)
  are already the right hook points.

### 1.5 AD-7 (CLI REPL has no existing slash mechanism) — CONFIRMED

- Spine: "`_run_chat` REPL 在 `input()` 与 `loop.run_stream()` 之间加最小 slash 分发器 …
  无既有 slash 机制可复用——此为新增薄表面."
- `cli.py:226-272` `_run_chat` — the REPL body is:
  ```python
  user_input = input("> ")           # L248
  if not user_input.strip(): break   # L253-254
  async for event in loop.run_stream(user_input, ...):  # L257
      ...
  ```
  There is **no** `startswith("/")` branch, no command table, no dispatcher. Input flows
  straight into `run_stream`. Confirmed: the slash dispatcher is genuinely new surface,
  not a reuse opportunity being missed.

### 1.6 FR-A1 / AD-1 (ToolSchema 3-field baseline) — CONFIRMED

- Spine / PRD: "`ToolSchema` 新增可选字段 `annotations` … 不破坏 V1 既有 3 字段
  (`name`/`description`/`parameters`)."
- `types.py:94-105` — `ToolSchema` currently has **exactly** `name: str`, `description: str`,
  `parameters: dict[str, object]`. Three fields, no extras. Adding `annotations` keeps the
  default-constructed shape backward-compatible (existing `ToolSchema(...)` call sites in
  `builtins/` and `mapping.mcp_tool_to_schema` won't need touching). Confirmed.

### 1.7 mcp.types.Tool.annotations exists (foundation for all of Epic A) — CONFIRMED

- `python -c "from mcp.types import Tool, ToolAnnotations; ..."`:
  - `Tool` fields: `['name', 'title', 'description', 'inputSchema', 'outputSchema',
    'icons', 'annotations', 'meta', 'execution']`.
  - `Tool.annotations` is typed `mcp.types.ToolAnnotations | None`.
  - `ToolAnnotations` fields: `['title', 'readOnlyHint', 'destructiveHint',
    'idempotentHint', 'openWorldHint']`.
- All four hints the spine/PRD relies on (`readOnlyHint`, `destructiveHint`,
  `idempotentHint`, `openWorldHint`) exist on the SDK's `ToolAnnotations`. Epic A is not
  built on a field that doesn't exist yet.

---

## 2. Findings (LOW severity — none block the spine)

### F1 — LOW — `ToolAnnotations` has a `title` field the spine doesn't mention

- Spine AD-1/AD-2 and PRD FR-A1 enumerate "四个 hint" and say the HeAgent 自有 Pydantic
  模型 "字段覆盖四个 hint". The SDK's `ToolAnnotations` actually has **five** fields:
  `title` plus the four hints.
- This is not a spine defect — `title` is non-decision-bearing (display only) — but the
  story that introduces `ToolSchema.annotations` should make a conscious call: carry
  `title` through (cheap, useful for logs/UI) or drop it. Silent drop is fine; just don't
  let it be an accidental oversight that surfaces as a follow-up.
- **Action:** story-level design note, not a spine change.

### F2 — LOW — "7 步裁决" elides step 6' (already-granted sandbox still returns SANDBOX_REQUIRED)

- Spine AD-2 says annotations land "在既有 7 步裁决的审批步内." This is correct: the approval
  step is step 5 and is the right insertion point.
- For completeness: the code has a sub-branch at `policy.py:179-184` where a sandboxed tool
  that is *already granted* still returns `mode=SANDBOX_REQUIRED` (with empty reason). So
  there are 8 distinct return points if you count 6 and 6' separately; the module docstring
  itself numbers it as 7. AD-2's numbering aligns with the docstring, so this is consistent,
  but a reader implementing V2 should know step 6 has two branches. Doesn't affect
  annotations placement (step 5).
- **Action:** none at spine level; optionally a one-line footnote in AD-2 referencing 6'.

### F3 — LOW — Ledger cache-hit re-check only short-circuits on BLOCKED (pre-existing; V2 makes it more observable)

- `tool_execution.py:82-87` — the cache-hit path re-evaluates policy and only bypasses the
  cache when the verdict is `BLOCKED`. If V2 annotations make a cached tool's verdict become
  `APPROVAL_REQUIRED` (e.g., destructive annotation newly recognized after an approval was
  revoked mid-run), the cache-hit path would **still return the cached result** without
  re-confirming approval.
- This is pre-existing behavior (the cache-hit guard was designed for BLOCKED-only), and
  V2 doesn't *break* it. But since V2 adds a new dimension (annotations) that can flip a
  verdict toward APPROVAL_REQUIRED, story-level tests should cover the "cache hit + verdict
  tightened to APPROVAL_REQUIRED" case explicitly so the semantic is intentional, not
  accidental.
- **Action:** story-level test coverage note. Not a spine defect — the spine's AD-1 Rule
  ("两个 evaluate 调用点都传 schema") is consistent with current cache semantics; just
  flagging the observable consequence.

### F4 — NIT — `_is_mcp_tool` is a substring check (`"__" in call.name`)

- `policy.py:272-274` — `_is_mcp_tool` returns `"__" in call.name`. The spine relies on
  this (AD-2 Rule 1 "approval_mcp_tools 开关且为 MCP 工具"). Today no built-in tool name
  contains `__`, so the substring check is safe. As V2 makes the MCP path hotter, any
  future built-in whose name happens to contain `__` would be misclassified as MCP.
- Pre-existing behavior; V2 doesn't change it. Worth a note in the story so it doesn't
  surprise someone adding e.g. a `math__sum` builtin later.
- **Action:** none required; awareness-only.

---

## 3. Things specifically NOT found (negative results, recorded for confidence)

- **No asserted-without-check SDK claim found.** Every method/field the spine references
  on `ClientSession` / `Tool` / `ToolAnnotations` exists in the installed 1.28.0.
- **No imaginary prerequisite.** Both "V1 sessions unreachable" (AD-4) and "no existing
  slash mechanism" (AD-7) are literally true against the current code — these were the
  highest-risk assertions in the spine and they hold.
- **No out-of-date stack claim.** `mcp>=1.28,<2` matches `pyproject.toml` and the
  installed interpreter.
- **No DAG violation in proposed extensions.** AD-1/AD-2/AD-4/AD-5/AD-7 all land on the
  existing extension points the spine claims (evaluate signature, manager internal state,
  manager-registered bridge tools, CLI dispatcher). None require `tools/` to import from
  `agent/`.

---

## 4. Summary

The spine is **reality-checked end to end**. Every committed AD-* decision and every
load-bearing prerequisite assertion was confirmed against either the cited source file or
the installed `mcp` 1.28.0 SDK (probed at runtime via `python -c`). Findings F1-F4 are LOW
severity design/awareness notes for the story authors, not spine defects. Recommend the
spine be approved for downstream epic/story derivation with F1-F4 carried forward as
implementation notes.
