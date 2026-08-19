# Rubric Review — ARCHITECTURE-SPINE.md (MCP Client V2)

Lens: GOOD-SPINE RUBRIC (checklist walker).
Subject: `_bmad-output/mcp-client-v2/ARCHITECTURE-SPINE.md` (status: draft, 2026-07-17).
Cross-referenced against: `_bmad-output/mcp-client-v2/prd.md` and the brownfield code under `src/heagent/` (`engine/policy.py`, `engine/context.py`, `tools/mcp/manager.py`, `tools/mcp/mapping.py`, `agent/tool_execution.py`, `types.py`, `cli.py`).

## Overall verdict

**PASS-WITH-FINDINGS.** The spine is structurally sound and earns its keep: it projects onto 8 lean ADs that map 1:1 to the PRD's FR-A/B/C, ratify (never contradict) the brownfield execution chain, decide every dimension this altitude owns, and defer the right things (subscribe / templates / openWorld-consuming-裁决) with explicit revisit conditions. Tech is verified-current (mcp 1.28.0 metadata-confirmed; `ClientSession` exposes the four primitives the spine claims; `click` 8.1.8; Pydantic v2). The DAG / execution-chain invariants from `docs/frame.md` are inherited without weakening — AD-2 inserts the annotation check *inside* the existing 7-step approval step rather than reordering the chain, and AD-7 keeps the slash dispatcher on the `agent/`-side caller in `cli.py` so `tools/mcp/` still doesn't reverse-import `agent/`.

Two HIGH findings block confident builder hand-off and are cheap to fix in the spine itself; the rest are MEDIUM/LOW precision nits.

## Findings (ranked)

### H1 — AD-2 fail-safe is ambiguous on `schema=None` (builtins) vs `schema.annotations=None` (unannotated MCP) [HIGH]

AD-2 Rule step 4 reads "缺 annotations / 不可判定 → `APPROVAL_REQUIRED`", but the spine never distinguishes the two ways "缺 annotations" can arise under AD-1's optional-kwarg signature `schema: ToolSchema | None = None`:

- (a) caller passes **no schema** — the path every V1 builtin takes (`file_read`, `file_write`, `file_search`, `content_search`, plus the 15 other builtins; also the V2 Resources/Prompts bridge tools if registered without self-annotations);
- (b) caller passes a schema whose `annotations` field is `None` — an MCP tool whose server didn't declare `Tool.annotations`.

The PRD scopes fail-safe explicitly: FR-A5 Consequence 1 says "一个**未声明任何 annotation 的 MCP 工具**调用 → `APPROVAL_REQUIRED`" (emphasis mine) — i.e. PRD limits fail-safe to MCP tools. The spine's AD-2 drops that qualifier. A builder reading AD-2 literally would force every V1 builtin (`file_write`, `shell`, …) into `APPROVAL_REQUIRED` because their `schema is None` matches "缺 annotations". Two builders will resolve this differently unless the spine says which:

- Builder A (PRD-faithful): `if schema is None or schema.annotations is None: skip annotation logic, preserve V1 7-step verdict` — builtins unaffected.
- Builder B (AD-2 literal): `if schema is None or schema.annotations is None: APPROVAL_REQUIRED` — every builtin now requires approval, SM-C1 ruptures, SM-4 zero-regression likely fails.

**Fix in the spine:** add a Rule line — "AD-2 annotation 裁决**仅在 `schema is not None` 时启用**；`schema=None`（V1 内置工具路径）保留既有 7 步行为不变（V2 不给内置工具补 annotations，见 Deferred）" — and align AD-2's Binds to cite FR-A5's MCP-only scoping. While you're there, state the priority between `destructiveHint=True` and `readOnlyHint=True` when a (misbehaving) server sets both — the fixed order implies destructive wins, but it's worth one sentence.

### H2 — AD-7 cites a non-existent function `_build_mcp` and waves past a real structural change in `cli.py` [HIGH]

AD-7's `[ASSUMPTION: REPL 当前可持 manager 引用（`_build_mcp` 已构造 MCPClientManager 实例）]` is wrong on two counts against the actual `cli.py`:

1. **No `_build_mcp` exists.** The function is `_mcp_lifecycle` (line 141), and it returns an *unentered* async context manager (`MCPClientManager(config)` or `contextlib.nullcontext()`). The spine cites a symbol that does not exist in the codebase — a verification miss on a "named tech" claim.
2. **The manager instance is not currently bound inside `_run_chat` / `_run_single`.** Both functions enter via `async with mcp_ctx or contextlib.nullcontext():` (lines 219, 238) **without** `as manager:`, so even after `_mcp_lifecycle` constructs an `MCPClientManager`, the REPL body has no reference to it. For AD-7's slash dispatcher to call `manager.list_prompts()` / `manager.get_prompt(...)`, three structural changes are needed, none of which the spine surfaces:
   - bind the result: `async with mcp_ctx or contextlib.nullcontext() as manager:` (and `nullcontext()` yields `None`, so the dispatcher must handle `manager is None` — i.e. MCP disabled — without crashing);
   - thread `manager` from `_run_chat`'s `async with` into the REPL loop where the slash dispatcher lives;
   - decide whether the dispatcher is silently unavailable when `manager is None` (MCP off) or surfaces a friendly error.

A builder reading the spine's "REPL 当前可持 manager 引用" will discover at implementation time that it does not, in fact, currently hold one. This is exactly the kind of brownfield claim a spine must get right.

**Fix in the spine:** rename the assumption to `_mcp_lifecycle`, add a Rule line stating that `_run_chat` must bind the manager via `as manager` and thread it to the REPL, and specify the MCP-disabled (`manager is None`) behavior for `/mcp-prompt` (friendly error is the natural choice, consistent with AD-7's "缺必填参数 / 模板不存在 → 显式错误").

### M1 — No cross-server URI collision policy for Resources [MEDIUM]

AD-5 routes `read_resource` by `(server, uri)` internally via `_sessions[normalized_name]`, but does not fix the **LLM-facing argument shape** nor what happens when two servers expose the same URI (e.g. both expose `file:///config.yaml`). The LLM only sees a single tool `read_resource`; without a decided convention, Builder A may take just `uri` (and pick the first matching server), Builder B may require `server` + `uri`, Builder C may accept optional `server` and disambiguate by uri-prefix. Each is defensible; the spine must pick one. Also undecided: the argument schema for `list_resources` (no args? optional server filter?). These are small but they are *interface* decisions the builder cannot read from "compliant code" alone, which is the spine's stated bar.

**Fix:** add one line to AD-5 fixing the LLM-facing schema for both bridge tools (e.g. "`read_resource` 必填 `server: str`（normalized）+ `uri: str`；同名 URI 跨 server 由 caller 指定 server 消歧，无默认兜底").

### M2 — Policy classification of the Resources/Prompts bridge tools is unstated [MEDIUM]

Per `policy.py:272-274`, `_is_mcp_tool` returns True iff `"__" in call.name`. AD-5 names the new bridge tools `list_resources` / `read_resource` (no `__`), so they classify as **pure builtins**, not MCP tools. Consequences the spine doesn't make explicit:

- `block_mcp_tools` / `approval_mcp_tools` / `sandbox_mcp_tools` will **not** apply to them — a user who sets `approval_mcp_tools=True` to gate MCP access gets no gate on `read_resource`.
- Under H1's literal reading, these tools (registered without self-annotations) would also be caught by fail-safe. If H1 is fixed the PRD way (skip when `schema is None`), then `read_resource` defaults to `DIRECT` — which is the right outcome for a semantically read-only primitive, but the spine should say so, and should decide whether the bridge tools self-declare `readOnlyHint=True` on their own `ToolSchema` (cleanest) or just rely on not being in any approval list.

**Fix:** extend AD-5 with a line stating the policy classification intent (e.g. "桥接工具分类为内置工具（`_is_mcp_tool=False`，名不含 `__`）；其 `ToolSchema.annotations` 自声明 `readOnlyHint=True`，确保 AD-2 step 3 放行，不触发 fail-safe"). Tie this to H1's fix.

### M3 — SM-4 (zero-regression) is not bound [MEDIUM]

The brownfield extension's most important guardrail — SM-4 ("V1 全部 MCP 测试 + 既有 19 个内置工具测试 + 既有测试全绿，覆盖率不低于基线") — appears only as a Consistency Conventions prose line ("零回归护栏覆盖既有 V1 MCP + 19 内置工具测试"). It is absent from the spine's `binds:` frontmatter and from the Capability→Architecture Map. Given the brownfield paradigm, SM-4 is load-bearing: it is the success criterion for "ratify, don't contradict". Leaving it implicit risks a builder treating V1 MCP tests as expendable.

**Fix:** add `SM-4` to `binds:` and a row in the Map (`SM-4 零回归 | tests/ 既有套件 | Consistency Conventions 测试行 + AD-1/AD-2 保留 V1 路径`).

### L1 — AD-1 rationale "该处已用同一 registry 取 handler" is mildly misleading [LOW]

AD-1 Rule says the caller "`tool_execution.execute_tool_call` 在裁决前 `schema = loop.registry.get_schema(call.name)` 并传入——该处已用同一 registry 取 handler", implying schema-fetch and handler-fetch are co-located. They are not: in `agent/tool_execution.py:102-103` the verdict is computed *before* the handler fetch (`verdict = …evaluate_tool_call(…)` then `handler = loop.registry.get_handler(call.name)`). The new `get_schema` call must be inserted *before* the verdict, so it lands on a different line from the existing handler fetch. Seed-level imprecision; the invariant (use the same registry, optional kwarg) is correct, but the justification sentence is not.

**Fix:** drop the "该处已用同一 registry 取 handler" clause or rewrite to "（该模块已持有 `loop.registry` 引用，复用取 schema）".

### L2 — AD-7 `/mcp-prompt <server>` name form unspecified [LOW]

AD-7's `<server>` argument — is it the raw configured name or the `normalize_server_name`-shaped key? AD-4 keys `_sessions` by `normalized_name`, so the dispatcher must normalize before lookup; a builder could equally accept either form. Trivial to fix.

**Fix:** one line in AD-7 — "`<server>` 经 `mapping.normalize_server_name` 规整后查 `_sessions`（与工具命名空间同算法）".

### L3 — AD-8 leans toward seed [LOW]

AD-8 reduces in practice to "update `CLAUDE.md` and `docs/frame.md` security statements to cover写操作治理 + Resources/Prompts 返回同等不可信". This is a documentation task, not an enforceable invariant that prevents two units from diverging in code. Defensible as a stance-preservation measure (prevents the docs from drifting into "接了治理就更安全" marketing), but it is the weakest AD on the enforceability bar.

**Fix:** either keep as-is (stance-preservation is legitimate) or demote to a Consistency Conventions row. Not blocking.

## Checklist walk

1. **Real divergence points fixed, none missed?** Mostly yes for FR-A/B/C. Missed: the `schema=None` vs `schema.annotations=None` distinction (H1) and the bridge-tool policy classification (M2). The cross-server URI routing shape (M1) is also a real divergence point for Epic B builders.
2. **Every AD Rule enforceable, prevents stated divergence?** AD-1/3/4/5/6 yes. AD-2 enforceable but ambiguous (H1). AD-7 enforceable but cites a non-existent symbol and hides a structural change (H2). AD-8 borderline seed (L3).
3. **Anything in Deferred wrongly deferred?** No. `subscribe_resource` (stateless conflict), `resource templates` (marginal value), `openWorldHint` consumption, `fail-safe` 增强, DP-4 fence hardening, deployment/infra/ops — all correctly deferred with revisit conditions. The "内置（非 MCP）工具 annotation 驱动治理" deferral is correct *only if* H1 is fixed; under the literal AD-2 reading that deferral is in tension with the fail-safe Rule.
4. **Named tech verified-current?** Yes, with one exception: AD-7's `_build_mcp` does not exist (H2). All other claims verified — Python 3.11+, mcp 1.28.0 (metadata-confirmed), `ClientSession.list_resources/read_resource/list_prompts/get_prompt/list_resource_templates/subscribe_resource` all present, Pydantic v2, click 8.1.8.
5. **RATIFY not CONTRADICT brownfield?** Yes. AD-1 extends `evaluate_tool_call` with backward-compatible optional kwarg (V1 call sites at `tool_execution.py:82, 102` continue to work). AD-2 inserts *inside* the existing 7-step approval step. AD-4 extends `_sessions` alongside the existing `_registered` dict using the same lifecycle hooks (`_server_loop` registration, `_unregister_server`/`_unregister_all` teardown). AD-5 reuses `registry.register`. AD-6 reuses `bridge_result`/`_guard_injection`. AD-7 reuses `run_stream`. No execution-chain reorder, no DAG violation.
6. **PRD FR coverage?** All 15 FRs (FR-A1..A7, FR-B1..B4, FR-C1..C4) mapped in the Capability→Architecture Map, each bound to at least one AD. SM-6 mapped. **SM-4 missing from `binds:` and Map (M3)**; SM-1/2/3/5/C1 are bound transitively via FR ADs (acceptable — they validate FRs).
7. **Inherited invariants weakened?** No. All five Inherited Invariants rows are reinforced, none contradicted. The execution-chain ordering (`PolicyEngine.evaluate() → ToolExecutor → SafetyGuard.check() → handler`) is preserved verbatim; DAG (`tools/mcp/` 禁从 `agent/` 导入) holds — slash dispatcher lives in `cli.py` (the agent-side caller); Pydantic-only data convention upheld (`ToolSchema.annotations` is a self-owned Pydantic model, mcp dep stays out of `types.py`); DP-4 fence stance reinforced (AD-8); V1 mapping/bridge reused (AD-5/6).
8. **Every altitude-owned dimension decided / deferred / open?** Yes. Data model, execution governance, Resources topology, Prompts surface, security stance — all decided. Deployment/infra/ops explicitly out of altitude (Deferred last bullet) — correct per `docs/frame.md` 五. Open questions carried forward from PRD (OQ-2 → AD-1 decided; OQ-4 → AD-7 decided; OQ-5/6 → Deferred) — none silently dropped.

## Adjacent observations (non-blocking)

- The mermaid block under §Invariants & Rules is structural detail (boxes for TE/CLI/PE/MGR/MAP/TS) that leans toward seed, but it's load-bearing for understanding AD-1's data-flow, so it earns its place.
- Prose-heavy Prevents/Rationale clauses (especially AD-1, AD-2) are mostly fine — they explain *why* an AD exists — but AD-2's "Prevents" could be tightened; the "fail-safe 沦为「无脑确认每个写操作」的吵闹版本" framing belongs more in the PRD/memlog than the spine.
- `[ASSUMPTION: …]` tags in AD-5 (no server → empty list) and AD-7 (manager ref) are honest; AD-7's is wrong on verification (H2), AD-5's is benign.

## Recommended spine edits before builder hand-off

1. AD-2 — add MCP-only scoping line for fail-safe (fixes H1); clarify destructive-vs-readOnly priority when both are True.
2. AD-7 — rename `_build_mcp` → `_mcp_lifecycle`; add Rule lines for binding `manager` via `as manager`, threading into REPL, and MCP-disabled behavior (fixes H2); specify `<server>` normalization (fixes L2).
3. AD-5 — fix LLM-facing argument shape for `read_resource` (server + uri) and `list_resources` (fixes M1); state bridge tools' policy classification and self-declared `readOnlyHint=True` (fixes M2).
4. Frontmatter `binds:` + Map — add SM-4 (fixes M3).
5. AD-1 — drop/rewrite the "该处已用同一 registry 取 handler" clause (fixes L1).

None of these require reopening the PRD or the brownfield codebase; all are spine-local clarifications.
