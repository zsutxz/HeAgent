---
reviewer: adversary
spine: _bmad-output/mcp-client-v2/ARCHITECTURE-SPINE.md
prd: _bmad-output/mcp-client-v2/prd.md
date: 2026-07-17
verdict: PASS-WITH-FINDINGS
---

# Adversary Review — MCP Client V2 Architecture Spine

> Lens: ADVERSARY. Job: construct two units that each obey every AD to the letter yet
> build incompatibly, plus probe the four ordered holes the gate asked about. Every
> incompatibility the ADs don't already close is a hole; each finding proposes the
> new/tightened AD that would close it.

## Verdict

**PASS-WITH-FINDINGS.** The spine's load-bearing intent is right and the brownfield
framing (no new execution path, same chain) is sound. But several invariants are
under-pinned in ways that let two faithful builders produce mutually incompatible
implementations. The two most damaging are tractable with one-line AD tightenings;
the rest are similar. None require re-architecting.

## TL;DR

- **F1 (CRITICAL)**: AD-2 fail-safe + Consistency Conventions ("annotations 缺省 =
  fail-safe 触发值") + AD-1 (call site always passes `schema`) collides with SM-4
  zero-regression: every existing built-in tool's `ToolSchema.annotations` would be
  the default fail-safe value, so every built-in becomes `APPROVAL_REQUIRED`. The
  spine's own deferred item ("内置工具 annotation 驱动治理") does not save it — the
  default-value rule fires regardless of intent.
- **F2 (HIGH)**: AD-5 names the Resources bridge tools `list_resources` /
  `read_resource` (no `__`), but the inherited single classifier `_is_mcp_tool` keys
  on `"__" in call.name`. Resources/Prompts bridge tools therefore escape
  `block_mcp_tools` / `approval_mcp_tools` / `sandbox_mcp_tools` / `__mcp__` grant
  semantics. A user who flips `block_mcp_tools=True` (the V1 MCP kill-switch) still
  has `read_resource` live.
- **F3 (HIGH)**: AD-6(c) promises "三原语返回内容一律经注入启发式围栏", but the
  only fence implementation (`mapping._guard_injection`) lives inside
  `bridge_result`, which is only called from the MCP **tool handler closure**.
  Prompts bypass the handler path entirely (AD-7 sends them as a user message from
  the CLI). No AD pins where the fence runs on the Prompts path → faithful builders
  diverge on whether Prompts are fenced at all.
- **F4 (HIGH)**: AD-4 adds `self._sessions: dict[str, ClientSession]` next to V1's
  handler-closure-captured session references. On disconnect, `_unregister_server`
  pops mappings but the AD does not assign ownership of in-flight calls. A
  `read_resource` call racing a server disconnect has undefined error semantics
  (ToolError vs raw exception) and a genuine concurrency hazard (session accessed
  from two asyncio tasks during teardown).
- **F5 (MEDIUM)**: AD-5 says `read_resource` resolves session "按 `(server, uri)`",
  but the LLM-facing signature is `read_resource(uri=...)`. Two servers can expose
  the same URI scheme; nothing in the ADs fixes how `server` is derived.

Additional lower-severity holes at the end.

---

## Concrete incompatible unit pairs

### Pair A — "PolicyEngine-team" vs "Builtins-team" (the killer)

**Setup.** Both teams read the spine in good faith and obey every AD literally.

**PolicyEngine-team** implements AD-1 + AD-2 + Consistency Conventions:

- AD-1: `evaluate_tool_call(call, *, context=None, schema=None)`. The call site
  `execute_tool_call` does `schema = loop.registry.get_schema(call.name)` then
  passes `schema=...`. Per AD-1 this happens **for every tool call, built-in or
  MCP** — the AD does not scope it to MCP only.
- Consistency Conventions row 2: "`annotations` 字段缺省 = fail-safe 触发值".
- AD-2 step 4: "否则（缺 annotations / 不可判定）→ `APPROVAL_REQUIRED`（fail-safe）".

For the 19 built-in tools, `get_schema` returns a `ToolSchema` whose `annotations`
field is unset → Pydantic default → "fail-safe 触发值" by convention. PolicyEngine
reads `schema.annotations`, sees the fail-safe sentinel, fires AD-2 step 4 →
`APPROVAL_REQUIRED`. The team is obeying every AD literally.

**Builtins-team** changes nothing. Their 19 tools were governed in V1 by the
explicit `approval_tools` / `sandbox_tools` lists (empty by default) and ran as
`DIRECT`. They rely on SM-4 ("既有 19 个内置工具测试全绿，覆盖率不低于基线") —
zero regression. They too obey the spine literally.

**Collision.** With PolicyEngine-team's build, every one of the 19 built-in tool
calls hits `APPROVAL_REQUIRED` → executor's `_policy_error` → `ToolResult(is_error=True,
content="Tool 'file_read' requires approval by policy.")` → the agent loop sees every
tool result as an error → every existing built-in test that exercises a tool fails.
**SM-4 zero-regression is violated by the spine itself, with no builder error on
either side.**

**Why the ADs don't close it.** The spine's Deferred section says "内置（非 MCP）
工具 annotation 驱动治理 — V2 仅 MCP 工具透传 annotations" — but this only says
the *mapping* step (`mcp_tool_to_schema`) doesn't run for built-ins. It does not
say the *consumption* step (AD-2 fail-safe) skips built-ins. Once `ToolSchema` has
an `annotations` field with a fail-safe default, every built-in's schema carries
that default — and AD-2 step 4 fires on "缺 annotations", not on "is MCP tool".

**Closer AD.** Tighten AD-2 with an MCP-only scope clause:

> **AD-2 (tightened):** Step 4 fail-safe applies **only** when `_is_mcp_tool(call)`
> is true AND `schema.annotations` is the default. For non-MCP tools (no `__` in
> `call.name`), the annotation path is **skipped entirely** — built-ins continue to
> be governed by the existing explicit lists (`approval_tools` / `sandbox_tools`).
> `schema=None` and "non-MCP tool with default annotations" are the **same
> no-op**; fail-safe only fires for MCP tools whose annotations are absent.

Or equivalently, fix AD-1 / Consistency Conventions: make the Pydantic default for
`annotations` be `None` (not "fail-safe sentinel") and have AD-2 step 4 apply only
when `schema is not None and schema.annotations is None and _is_mcp_tool(call)`.

### Pair B — "Resources-team" vs "Lifecycle-team" (session race)

**Setup.** Both teams read the spine in good faith.

**Resources-team** implements AD-5. `read_resource` bridge tool handler closure
captures `self._sessions`; on call:

```python
async def handler(**kwargs):
    server = <derive from kwargs per AD-5 "按 (server, uri)"> 
    session = self._sessions[server]            # snapshot reference
    text = await session.read_resource(uri)     # ← await point
    return <bridge + fence>
```

The team obeys AD-4 + AD-5 to the letter.

**Lifecycle-team** implements AD-4. The existing `_server_loop` task runs `_watch`;
on ping failure it calls `_unregister_server(name)` which pops `self._sessions[name]`
and `self._registered[name]`. Per AD-4, `_unregister_server` "同步摘除" — that is
the entire specified contract. The team then returns from `_watch`; `_server_loop`'s
`finally` runs `await cm.__aexit__()` and tears down the transport. The team obeys
AD-4 to the letter.

**Collision (concrete race).** Timeline:

1. Agent-loop task: `read_resource` handler does `session = self._sessions[server]`
   (t0).
2. `_watch` task: ping fails at t1 > t0; `_unregister_server(name)` pops
   `self._sessions[name]` and `self._registered[name]`; _server_loop returns;
   transport context tears down at t2.
3. Agent-loop task: `await session.read_resource(uri)` resumes — but the session's
   transport is now closed/dead. Raises some MCP SDK exception.

**Divergent faithful readings of the ADs:**

- **Reading B1:** Any exception in the handler → wrap as `ToolError("server '%s'
  unavailable" % server)` per AD-5's "错误语义 ... 沿用 V1 `ToolError`" row. LLM
  sees a clean error result.
- **Reading B2:** Let the raw exception bubble. Executor's `except Exception`
  catches it → `ToolResult(content=f"Tool error: {exc}")`. Different message,
  different category, no WARNING log of the disconnect mid-call.
- **Reading B3:** Track in-flight calls on each session; on `_unregister_server`,
  `asyncio.task.cancel()` any in-flight handler task and convert `CancelledError`
  to `ToolError`. AD-4 does not require this, but a correctness-minded team adds
  it.

All three obey AD-4 + AD-5. They produce three different runtime behaviors for the
same race. Worse, B1/B2 have a genuine concurrency hazard: `ClientSession` is
awaited from the agent-loop task while the `_server_loop` task initiates transport
teardown — the MCP SDK's session is not designed for concurrent use across
"reader/writer closed in another task while a call is mid-flight".

**Why the ADs don't close it.** AD-4 specifies that `_unregister_server` removes
the mapping; it does not specify that it must (a) cancel in-flight calls on that
session, (b) signal them, or (c) be the single owner with the power to tear down.
AD-5 specifies `read_resource` "URI 不存在 → `ToolError`" but is silent on
"transport gone mid-call". The session ends up with **three** live references
(`_server_loop`'s `async with`, V1's per-tool closure, V2's `_sessions` dict) and
no assigned owner of in-flight cancellation.

**Closer AD.** Tighten AD-4:

> **AD-4 (tightened):** `_server_loop` is the **single owner** of the session
> transport. `_sessions` is a borrowed-reference index, not an owner. On
> `_unregister_server`:
> 1. **first** flip a per-server "disconnected" flag visible to bridge handlers,
> 2. **then** pop `_sessions[name]` and `_registered[name]`,
> 3. **then** let `_server_loop` tear down transport.
>
> Bridge handlers (`read_resource`, V1 MCP tool closures) MUST check the flag (or
> `await` with a timeout) and convert "session mid-call unavailable" to a single
> canonical `ToolError("MCP server '<name>' disconnected")`. The exact error
> string is fixed in AD-5.

And tighten AD-5's error row to enumerate that canonical case.

---

## Probe answers

### Probe 1 — Does AD-2's fixed priority prevent a destructive tool from sneaking through (annotations absent vs present)? Ordering hole?

**No, not fully.** The four-case priority is sound *inside the approval step*, but
two ordering holes exist:

**(a) Annotations vs sandbox step (post-approval).** AD-2 only governs the approval
step. After approval is granted (`metadata.approved_tools` contains the tool /
`*` / `__mcp__`), the destructive tool re-enters the existing 7-step flow at step
6 (sandbox). If `sandbox_mcp_tools=False` and `sandbox_tools=[]`, a destructive
tool that the user approved once at run start runs **`DIRECT`** for the rest of the
run — no sandbox. Two faithful builders diverge:

- Builder X: annotations drive only approval; post-approval destructive → DIRECT.
- Builder Y: annotations also push destructive tools through `SANDBOX_REQUIRED`
  post-approval.

Both comply with AD-2's literal text (which only mentions approval). The hole is
that AD-2 doesn't say "annotations affect ONLY the approval step, NEVER the sandbox
step". **Close with: AD-2 addendum pinning that annotations affect ONLY approval
mode in V2; sandbox resolution is unchanged.**

**(b) Fail-safe triggered by built-in tools' default annotations.** See F1 / Pair
A. The absent-vs-present question is fully resolved *only if* "absent annotations"
is unambiguous. The ADs currently allow "absent" to mean either "schema=None" OR
"schema.annotations is the Pydantic default", and those two meanings have wildly
different blast radii (built-ins vs MCP only).

**(c) Approval-then-revocation ordering.** AD-2 step 1 puts explicit policy
(`approval_tools`, `approval_mcp_tools`) above annotation. But there is no
explicit policy for *blocking* by annotation — if a user wants "any destructive
tool is hard-blocked regardless of approval grant", they have no knob; approval is
revoke-able per-run via `metadata.approved_tools`, but a `*` grant at run start
disables all destructive gating for the rest of the run. Not a builder-divergence
hole, just an underserved case; mention in Deferred.

### Probe 2 — AD-4 + AD-5: Resources tool call racing server disconnect; session-lifecycle ownership?

**Single-owner? No.** See Pair B above. The session has three live references in
V2:

1. `_server_loop`'s `async with _transport_and_session(...)` (V1, unchanged) —
   transport owner.
2. Each V1 MCP tool handler closure captures `session` directly (`_make_handler`,
   manager.py:241).
3. (V2 new) `self._sessions[name]` — the AD-4 index.

AD-4 adds the third without consolidating the second. `_unregister_server` only
touches `_sessions` and `_registered`; it does not invalidate the existing closure
references (and cannot — they're captured). On disconnect:

- `_sessions[name]` is popped → new `read_resource` calls fail to find the session.
- Already-registered tool closures from V1 still hold the dead session reference
  until `_unregister_server` pops them from the registry (which it does, but
  in-flight calls have already snapshot the closure).
- In-flight `read_resource`/`call_tool` calls race transport teardown.

**The hole:** AD-4 says "映射是 manager 的内部状态，不外泄给 `agent/`" but doesn't
say "the mapping is the **single** way bridge code accesses session; V1 closure
capture is deprecated/forbidden". Faithful builders can either (i) leave V1 closure
capture as-is and add `_sessions` as a *parallel* index (divergence hazard, F4), or
(ii) refactor V1 closures to look up via `_sessions` (broader change than the spine
advertises — "V2 不引入新执行路径").

**Close with:** AD-4 addendum (single-owner + in-flight call handling) as in Pair
B's closer.

### Probe 3 — AD-1: if `schema=None` is passed, does fail-safe still fire correctly, or does missing-schema silently bypass governance?

**Underspecified — silently bypasses OR silently over-blocks, depending on the
builder.** Three faithful readings:

- **Reading α (skip on None):** `schema is None` → annotations unknown → the
  entire annotation path is skipped → tool falls through to existing 7-step
  resolution. This is the "least-invasive" reading. **Risk:** a calling site that
  forgets to pass `schema` silently disables fail-safe for that call. The ledger
  cache-hit re-evaluation site (`tool_execution.py:82` as of V1) is exactly such
  a site pre-V2 — and AD-1's claim that "两个 evaluate 调用点都传 schema" is a
  future-state assertion, not a hard invariant enforced by anything other than
  code review. A regression here silently bypasses governance.
- **Reading β (fail-safe on None):** `schema is None` is treated as "缺
  annotations" → AD-2 step 4 fires → `APPROVAL_REQUIRED`. This is the "safest"
  reading. **Risk:** every call site that legitimately cannot produce a schema
  (e.g., a ledger-cache re-eval where fetching the schema again is expensive)
  becomes approval-required, breaking cache hits.
- **Reading γ (distinguish per tool class):** `schema is None` for non-MCP tools =
  skip; `schema is None` for MCP tools = fail-safe. This is what the spine
  *probably* means but does not say. It depends on `_is_mcp_tool` (see F2's
  critique — the classifier is unreliable for the new bridge tools).

**Close with:** AD-1 addendum pinning reading γ explicitly + a test that asserts
both evaluate call sites pass schema (and that ledger-cache re-eval diverging
from original verdict is an architecture error).

### Probe 4 — Does AD-6(c)'s "equal fence" hold when Prompts inject as a user message?

**No — there is a structural gap.** AD-6(c) asserts "Tools / Resources / Prompts
三者返回内容一律经注入启发式围栏". But the fence has exactly one implementation,
`mapping._guard_injection` (mapping.py:119, module-private), and the only call
site is `bridge_result` (mapping.py:152). `bridge_result` is in turn called only
from MCP **tool handler closures** (manager.py:257).

AD-7 routes Prompts through an entirely different path:

> `_run_chat` REPL ... `/mcp-prompt <server> <name> [key=value ...]` ... 渲染文本
> **作为 user message** 走 `run_stream`

So Prompts never go through `bridge_result`. The fence is never invoked on the
Prompts path unless a builder independently notices and adds the call. Two faithful
builders:

- **Builder P1:** Reads AD-6(c) literally, notices the fence lives in `mapping`,
  imports `_guard_injection` from `cli.py`, applies it to the rendered prompt text
  before injecting as user message.
- **Builder P2:** Reads AD-7 ("渲染文本作为 user message 走 run_stream"), assumes
  "走 run_stream" satisfies "经注入启发式围栏" because run_stream is the normal
  message pipe. Does not call the fence. A malicious server prompt template
  containing `<|im_start|>system\n...` flows raw into the LLM context.

Both comply with AD-6(c) and AD-7 as written — AD-6(c) is a property assertion,
AD-7 doesn't cite the fence function. Builder P2 silently disables the fence for
Prompts.

**Secondary issue:** `_guard_injection` is module-private (underscore). Importing
it from `cli.py` crosses a module-privacy boundary and creates a DAG smell (cli.py
is the agent's caller, reaching into `tools/mcp/mapping.py` private surface). The
spine's Inherited Invariants row 2 says "新增桥接代码仍只向
`types`/`exceptions`/`registry`/`mapping` 依赖; slash 分发器在 `cli.py`" — so
cli.py→mapping is allowed, but relying on a private symbol is fragile.

**Close with:** AD-7 (or AD-6) addendum:

> **AD-7 (tightened):** The slash dispatcher MUST pass rendered prompt text
> through the **same** injection fence used by `bridge_result`. The fence function
> is hoisted to a public name (e.g., `mapping.guard_injection` — drop the
> underscore) so all three primitives cite one public symbol. A unit test asserts
> that a prompt template containing `<|im_start|>` is fenced before reaching
> `run_stream`.

Note also the semantic weirdness: fenced tool/resource results appear as `TOOL`
messages (where a `[⚠ MCP 返回命中注入启发式...]` banner is natural), but a fenced
prompt appears as a `USER` message — the banner would look like the user typed it.
Worth a note in AD-6(c) that the banner template is the same regardless of channel
(intentional, observable defense-in-depth).

---

## Findings ranked

### F1 — CRITICAL — Fail-safe fires on built-in tools, breaks SM-4 zero-regression

**Severity:** CRITICAL (blocks epic A from landing without regressing 19 tools).

**Hole:** AD-1 (call site always passes schema) + AD-2 step 4 (missing annotations
→ APPROVAL_REQUIRED) + Consistency Conventions (annotations default = fail-safe
trigger value) together imply every built-in tool whose schema was constructed
without explicit annotations triggers fail-safe. The Deferred item "内置工具
annotation 驱动治理 — V2 仅 MCP 工具透传 annotations" only constrains the mapping
step, not the consumption step.

**Failure scenario:** Build epic A. Run `pytest tests/test_engine_*` + any test
that exercises built-in tools (e.g., `test_file_read`). Every call returns
`is_error=True, "requires approval by policy"`. SM-4 fails.

**Close with:** AD-2 addendum scoping fail-safe to MCP tools only (see Pair A
closer above). Hard invariant + unit test: `evaluate_tool_call(builtin_call,
schema=<default annotations>)` returns `DIRECT` (or existing explicit-list
verdict), never `APPROVAL_REQUIRED` from the annotation path.

### F2 — HIGH — Resources/Prompts bridge tools escape MCP governance (`_is_mcp_tool`)

**Severity:** HIGH.

**Hole:** AD-5 names the bridge tools `list_resources` / `read_resource` (no
`__`). AD-7 routes Prompts via the slash dispatcher (no tool name at all). The
inherited single classifier `_is_mcp_tool` (policy.py:272) keys on
`"__" in call.name` and is used in 4 places: `block_mcp_tools`, `approval_mcp_tools`,
`sandbox_mcp_tools`, `__mcp__` grant shortcuts. None of these reach Resources.

**Failure scenario:** User configures `block_mcp_tools=True` (the V1 "kill all
MCP" switch) after seeing a malicious server. They run the agent. `github__search_code`
is blocked. But `list_resources` and `read_resource` still work — the malicious
server's resources are still readable, and any prompt-injected content from them
flows into context. Conversely, `approval_mcp_tools=True` (intended "approve all
MCP") does not cover `read_resource`.

**Close with:** AD-5 addendum:

> **AD-5 (tightened):** Resources bridge tools (`list_resources` / `read_resource`)
> are **MCP-backed** and MUST be classified as MCP for policy purposes. Implementation
> MUST extend `_is_mcp_tool` (or supersede it with a registry-backed classifier
> maintained by `MCPClientManager`) so that `block_mcp_tools` / `approval_mcp_tools`
> / `sandbox_mcp_tools` / `__mcp__` grant semantics all apply to bridge tools.

### F3 — HIGH — AD-6(c) Prompts fence is not pinned to a code path

See Probe 4 above. **Close with:** AD-7 addendum mandating the fence call from
the slash dispatcher, plus hoisting `_guard_injection` to public.

### F4 — HIGH — Session lifecycle ownership + in-flight call cancellation

See Pair B above. **Close with:** AD-4 addendum (single owner + canonical
`ToolError("MCP server '<name>' disconnected")` + flag-before-pop ordering) and
AD-5 error-row enumeration of the transport-gone case.

### F5 — MEDIUM — `read_resource` URI → session routing is ambiguous

**Hole:** AD-5 says "按 `(server, uri)` 取对应 session" but the LLM-facing
signature is `read_resource(uri=...)`. `list_resources` aggregates across servers
(AD-5), so two servers can both expose `file:///foo`. The ADs don't specify how
`server` is derived from a bare `uri`. Three faithful builders:

- B-i: iterate `self._sessions.values()`, try each, first-success-wins (slow,
  side-effect-y, error-prone if reads have side effects on servers).
- B-ii: synthesize a namespaced URI like `mcp://<server>/<original-uri>` and
  require it in `read_resource`. Breaks the natural MCP URI semantics.
- B-iii: cache `uri → session_name` from the most recent `list_resources` response;
  look up in cache; fall back to error if unseen. Adds stale-cache hazard.

**Close with:** AD-5 addendum pinning one routing scheme (B-iii is closest to MCP
semantics, but require the cache to be invalidated on `_unregister_server`).

### F6 — MEDIUM — Ledger cache-hit re-evaluation may diverge from original verdict

**Hole:** AD-1 says "两个 evaluate 调用点（正常路径 + ledger 缓存命中复核）都传
schema" — but this is an assertion about future code, not an invariant the spine
enforces. The V1 code (tool_execution.py:82) calls
`loop.engine.policy.evaluate_tool_call(call, context=run_context)` for the cache-hit
re-check with no schema. If a builder forgets to add `schema=...` at this site,
the cache-hit re-evaluation sees "no annotations" → fail-safe fires → a cached
DIRECT result is bypassed and the tool is needlessly re-blocked (or, under reading
α from Probe 3, the original destructive annotation is silently dropped and a
cached APPROVAL_REQUIRED is wrongly returned as the cached result).

**Close with:** AD-1 addendum: hard invariant + a test asserting the two call
sites pass identical schema; divergence is an architecture error.

### F7 — LOW/MEDIUM — AD-2 doesn't pin whether annotations affect the sandbox step

See Probe 1(a). **Close with:** AD-2 addendum: "annotations affect ONLY the
approval mode decision in V2; the sandbox step is unchanged. `destructiveHint=true`
after approval grant does NOT force `SANDBOX_REQUIRED`."

### F8 — LOW — `_run_chat` `input()` blocks the loop, delaying `_watch` disconnect detection

**Hole:** AD-7's slash dispatcher runs between `input()` and `run_stream`. The V1
`_run_chat` uses blocking `input("> ")` which halts the asyncio loop — `_watch`
ping tasks cannot fire while the user is thinking. A server that disconnected
during user-thinking-time is not detected before the next slash command runs, so
`/mcp-prompt <disconnected_server> ...` or `read_resource` calls produce raw
transport errors instead of the canonical "disconnected" error from F4.

This is an inherited V1 issue (not introduced by V2), but it interacts with F4:
the canonical disconnect error path depends on `_watch` having flagged the server
first, which `input()` blocking delays.

**Close with:** Note in AD-7 that disconnect-detection latency under blocking
`input()` is a known inherited V1 limitation; the canonical error from F4's closer
must also cover "transport error on first call after silent disconnect".

### F9 — LOW — Minor: `approval_tools` / `blocked_tools` are exact-name; no glob

**Hole:** AD-2 step 1 ("`approval_tools` 含该名") inherits exact-string matching.
Users cannot write `approval_tools=["github__*"]` to approve-all-on-a-server.
Not a builder-divergence hole (the rule is unambiguous), just a usability gap that
becomes more visible now that annotations are another path. Mention in Deferred.

---

## What the spine gets right (so the gate can weigh severity)

- Brownfield framing — no new execution path, same chain — is correct and the
  single biggest risk-mitigator. Most "where does the fence live" / "who owns the
  session" questions inherit V1's answers.
- AD-2's four-case priority *inside the approval step* is correct; the priority
  order is right (explicit > destructive > readOnly > fail-safe).
- AD-3 (deterministic, pure-function, unit-testable) is the strongest invariant in
  the spine and correctly prevents LLM-probabilistic danger grading.
- AD-8 (honesty about non-boundary) is correctly carried forward from V1.
- Pinning annotations as a HeAgent-internal Pydantic model in `types.py` (not
  importing `mcp.types.ToolAnnotations` upward) correctly preserves the DAG.

The holes above are all "the AD says X but doesn't quite close Y"; none of them
require re-architecting. One-line addenda per AD close all of F1–F5.

## Recommended gate decision

**Pass-with-findings.** Require the author to tighten AD-1, AD-2, AD-4, AD-5, AD-7
with the addenda above before epic A stories are cut. F1 in particular must be
closed before any builder starts work, otherwise SM-4 zero-regression fails on
first integration.
