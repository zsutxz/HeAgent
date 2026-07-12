# Review: Rubric Walker + Fact-Check — MCP v1→v2 Upgrade-Prep Architecture Spine

**Reviewer:** architecture-spine reviewer (rubric + web-researched fact-check)
**Date:** 2026-07-12
**Subject:** `_bmad-output/mcp-v2-upgrade/architecture.md`
**Sources verified:** PyPI release history (live fetch 2026-07-12), official v2 migration guide (live fetch 2026-07-12), RC blog post (web search 2026-07-12), codebase (manager.py / mapping.py / frame.md)

---

## VERDICT: PASS-WITH-FINDINGS

The spine is structurally sound — all 7 code locations verified precise, inherited invariants strengthened not weakened, PRD capabilities fully covered, deferred items non-divergent. Three findings require attention before Epic 14+ stories consume the spine: (1) the `Client mode='auto'` addendum row is a false positive that creates a phantom 6th call point, (2) the v2 switch path has an unresolved `ClientSession`-vs-`Client` decision that could violate AD-2's "diff 为空" claim, and (3) the "initialize 删除" framing conflates protocol-level removal with SDK-level availability. All committed SDK/protocol facts verified current as of 2026-07-12.

---

## JOB 1 — RUBRIC WALKER

### R1. Fixes the real divergence points for the level below (Epic 14+ stories) — PASS-WITH-FINDING

**Finding:** All 5 breaking categories (initialize / send_ping / list_tools / call_tool / types) are mapped to 7 isolation-layer exports with precise code locations. Every line number verified against actual codebase:

| Spine claim | Codebase actual | Match |
|---|---|---|
| `session.initialize()` at manager.py:215,226 | Line 215 (StdioServerConfig), 226 (HttpServerConfig) | ✓ |
| `session.send_ping()` at manager.py:290 (`_watch`) | Line 290 in `_watch` | ✓ |
| `session.list_tools()` at manager.py:234 | Line 234 in `_discover_and_register` | ✓ |
| `session.call_tool(name, args)` at manager.py:256 | Line 256 in `_make_handler` handler closure | ✓ |
| `from mcp.types import ...` at mapping.py:18 | Line 18: `from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent, Tool` | ✓ |
| `tool.inputSchema` at mapping.py:41 | Line 41: `tool.inputSchema if isinstance(tool.inputSchema, dict)` | ✓ |
| `result.isError` at mapping.py:132 | Line 132: `if result.isError:` | ✓ |

**Severity: LOW** — The 7 exports cover the real divergence points. However, the addendum §3 table marks `Client mode='auto'` as ✓ hit at "manager.py:214,224" (`ClientSession` construction), but `mode='auto'` is a `Client` class parameter, not `ClientSession` (see fact-check F2). The spine's AD-1 table correctly omits this (no row for `Client` construction), but the addendum's ✓ marking creates a phantom 6th hit that stories might try to address. The addendum should mark it ✗ (HeAgent uses `ClientSession`, not `Client`).

### R2. Every AD's Rule enforceable and actually prevents its stated divergence — PASS-WITH-FINDING

**AD-1 (隔离层收敛):** The prohibition "禁止直接 `session.initialize()` / `send_ping()` / `list_tools()` / `call_tool()` 或 `from mcp.types import`" is enforceable via code review or grep. No import-linter rule is mandated, but the rule is clear enough for manual enforcement. **Enforceable.**

**AD-2 (切换 diff 为空):** "v2 切换只改 `session_api.py` 内部实现" — enforceable via git diff verification. However, this claim may be too optimistic: the v2 switch path says `handshake(session)` → no-op, but if HeAgent must migrate from `ClientSession` to `Client(mode='auto')` for true stateless mode, `manager.py`'s `_transport_and_session` would also need changes (it constructs `ClientSession` directly at lines 214, 224). The spine doesn't decide whether v2 keeps `ClientSession` (with legacy `initialize()`, which still works in SDK v2) or migrates to `Client`. **See finding R7 for the silent dimension.**

**AD-3 (FR-3 v2 等价):** Two-part rule — v1 ping placeholder (enforceable: `session_api.ping()` calls `send_ping`) + v2 switch to A (documented path, not implemented this cycle). The "安全立场不可退化" principle is enforceable by review. **Enforceable.**

**AD-4 (纯 v1):** "不 import v2-only API" + pin `mcp>=1.27.2,<2` — enforceable at install time (pin) and review time (grep for v2-only imports). **Enforceable.**

**AD-5 (零回归):** `tests/test_mcp_*.py` 全绿 — enforceable via CI/pytest. **Enforceable.**

**AD-6 (DAG+异步+类型):** DAG enforced by import inspection; async by review; types by convention. **Enforceable.**

**Severity: MEDIUM** — AD-2's "diff 为空" guarantee is at risk if the v2 switch requires `ClientSession`→`Client` migration. The spine should explicitly decide: does "v2 切换" mean "adapt to v2 SDK API changes while keeping `ClientSession`" (AD-2 holds, but `handshake()` is NOT a no-op) or "adopt v2 stateless mode via `Client(mode='auto')"` (AD-2 may break, `handshake()` IS a no-op)? This is the single most important undecided question for the v2 switch path.

### R3. Nothing under Deferred could let two units diverge — PASS

All 6 deferred items have clear conditions or are orthogonal:

| Deferred item | Divergence risk | Verdict |
|---|---|---|
| v2 actual switch execution | Path documented in §v2 切换路径; next task has clear steps | No divergence |
| FR-3 equivalent mechanism (A) implementation | Selection decided (A); only implementation deferred | No divergence |
| Resources/Prompts/write ops | Orthogonal to this cycle | No divergence |
| `server/discover` (B) | Reevaluation conditions specified (A insufficient in实测) | No divergence |
| Protocol upgrade (v1/v2 coexistence) | Condition specified (if灰度切换 needed) | No divergence |
| User-configurable injection signature | Orthogonal (mcp-client DP-4 deferred) | No divergence |

### R4. Ratifies rather than contradicts the brownfield codebase — PASS

The spine ratifies the actual codebase precisely. Verified against `manager.py` and `mapping.py`:

- `_transport_and_session` @asynccontextmanager yielding initialized `ClientSession` — spine's AD-1 maps this to `handshake(session)` ✓
- `_watch` race `stop.wait()` vs `session.send_ping()` — spine's AD-3 maps this to `ping(session, timeout)` ✓
- `_discover_and_register` calls `session.list_tools()` and iterates `result.tools` — spine's AD-1 maps this to `list_tools(session)` ✓
- `_make_handler` closure calls `session.call_tool(tool_name, kwargs)` — spine's AD-1 maps this to `call_tool(session, name, args)` ✓
- `mapping.py` imports from `mcp.types`, accesses `tool.inputSchema` and `result.isError` — spine's AD-1 maps these to type aliases + `input_schema_of` + `result_is_error` ✓
- `bridge_result` DP-4 injection fencing — spine's Inherited DP-4 says "不削弱 `mapping.bridge_result` 围栏" ✓
- frame.md §4.11 describes the same V1 boundaries (DP-4 halves, FR-3 ping-watch, Tools-only) — spine inherits all ✓

The per-server task architecture (avoiding anyio cancel scope cross-task) is correctly noted in Conventions ("session 生命周期仍由 MCPClientManager 持有，per-server task").

### R5. Covers the driving PRD's capabilities (FR-1~5 / NFR-1~6) — PASS

Capability → Architecture Map covers all 11 PRD requirements:

| PRD | AD | Coverage |
|---|---|---|
| FR-1 (pin 1.27.2) | AD-4 | ✓ |
| FR-2 (隔离层 5 调用点) | AD-1 / AD-2 | ✓ |
| FR-3 (断连探测 v2 等价) | AD-3 | ✓ (设计决策定，实现 deferred) |
| FR-4 (迁移测试基线) | AD-5 | ✓ |
| FR-5 (切换路径文档化) | AD-2 / AD-4 | ✓ |
| NFR-1 (零回归) | AD-5 | ✓ |
| NFR-2 (封装局部化) | AD-2 | ✓ (see R2 caveat on AD-2) |
| NFR-3 (DP-4 不退化) | Inherited DP-4 | ✓ |
| NFR-4 (纯 v1) | AD-4 | ✓ |
| NFR-5 (DAG/异步) | AD-6 | ✓ |
| NFR-6 (可观测) | Conventions | ✓ |

### R6. Inherited invariants not weakened or contradicted — PASS

All 6 inherited invariants verified against frame.md §4.11 and CLAUDE.md:

| Inherited | Spine treatment | Verdict |
|---|---|---|
| mcp-client NFR-3 (握手封装留接口) | AD-1 extends to all 5 points — strengthens | ✓ |
| mcp-client FR-3 (ping-watch 断连 auto-unregister) | AD-3 "安全立场不可退化" + A mechanism | ✓ |
| mcp-client DP-4 (工具名拦截 + 返回围栏) | Inherited table: "不削弱 bridge_result 围栏，不引入新边界" | ✓ |
| DAG (tools/mcp/ 禁从 agent/ 导入) | AD-6 explicitly enforces | ✓ |
| 异步 (库代码无同步 I/O) | AD-6 enforces; Conventions "全 async" | ✓ |
| Pydantic 模型跨模块 | Conventions: "passthrough SDK 原生类型，不新造模型" — SDK types ARE Pydantic models, so this is consistent (not a weakening) | ✓ |

No new AD contradicts any inherited invariant.

### R7. Every dimension the altitude owns is decided / deferred / open-question — PASS-WITH-FINDING (silent dimension flagged)

**Decided dimensions:**
- Structural: `session_api.py` location, DAG direction, module layout ✓
- Behavioral: 5 call points, FR-3 mechanism (A selected) ✓
- Data: passthrough SDK types, no new Pydantic ✓
- State: stateless isolation layer, session lifecycle by MCPClientManager ✓
- Error: ToolError, no swallow ✓
- Observability: logging, NFR-6 ✓
- Operational: Python 3.11+, mcp >=1.27.2,<2, pytest+pytest-asyncio ✓

**Silent dimension — `ClientSession`-vs-`Client` choice for v2 switch:**
The spine's AD-1 functions take a `session` parameter and call `session.initialize()`, `session.send_ping()`, `session.list_tools()`, `session.call_tool()`. In v1, `session` is a `ClientSession`. In v2 SDK, `ClientSession` still supports all these methods (the migration guide confirms "ClientSession's public surface is unchanged — same constructor apart from timeout parameters, typed methods, manual `initialize()`"). But the v2 stateless mode (no `initialize`, `server/discover` probe) is a `Client(mode='auto')` feature, not a `ClientSession` feature.

The v2 switch path says `handshake(session)` → no-op ("initialize 删除"), but:
- If `session` stays `ClientSession`: `initialize()` is NOT deleted in SDK v2 — it still works. Making `handshake()` a no-op means skipping initialization, which would leave the session uninitialized for 2025-11-25 servers. This is likely wrong.
- If `session` migrates to `Client`: `Client` handles handshake internally via `mode='auto'`, so `handshake()` IS a no-op. But `manager.py`'s `_transport_and_session` (which constructs `ClientSession` directly) would need changes, violating AD-2.

This decision is neither made, deferred, nor listed as an open question. Two stories could diverge: one assumes `ClientSession` stays (AD-2 holds, `handshake()` still calls `initialize()`), another assumes migration to `Client` (AD-2 breaks, `handshake()` is no-op).

**Severity: MEDIUM** — Recommend adding an explicit AD or open-question: "v2 切换保留 `ClientSession`（`handshake()` 仍调 `initialize()`，AD-2 成立）还是迁移到 `Client(mode='auto')`（`handshake()` 真正 no-op，但 `manager.py` 需改 `_transport_and_session`）？" The current v2 switch path assumes the latter but doesn't reconcile with AD-2.

**Minor testing dimension gap:**
AD-5 says existing tests must stay green, but doesn't specify whether new unit tests for `session_api.py` itself are required this cycle. Two stories could diverge on test scope (one adds unit tests for the isolation layer, another only relies on existing integration tests). The v2 switch path step 4 mentions "新增 v2 断连探测用例" for the switch (deferred), but the v1 isolation layer's own test coverage is unspecified.

**Severity: LOW** — Recommend a one-line convention: "`session_api.py` 须有单元测试覆盖各导出函数（v1 实现正确性），纳入 AD-5 零回归基线。"

---

## JOB 2 — FACT-CHECK (web-researched, 2026-07-12)

### F1. mcp SDK v1.27.2 latest stable (2026-05-29) — CONFIRMED ✓

**Source:** PyPI project page, live fetch 2026-07-12 (https://pypi.org/project/mcp/#history)
**Finding:** PyPI release history shows:
- `1.27.2` — May 29, 2026 — marked with blue cube "Latest release"
- `2.0.0a1` — Jun 11, 2026 — marked "pre-release" (white cube)
- `1.27.1` — May 8, 2026
- `1.27.0` — Apr 2, 2026
- No `1.28.x` versions exist in the release history.

The spine's claim "v1 线最新 stable 2026.05-29" is correct. The addendum's note "mcp-client prd §6 写「v1.28.0 stable」为笔误（无此版本）" is also correct — no 1.28.x exists on PyPI as of 2026-07-12.

**Note:** The official v2 migration guide (https://py.sdk.modelcontextprotocol.io/v2/migration/) references "v1.28.1" in its dependency comparison table (`| Dependency | v1.28.1 | v2 | Change |`) and code examples (`"mcp==1.28.1"`). This appears to be a forward-looking reference to a version that doesn't exist yet at the time of writing (2026-07-12). The addendum's dismissal of "1.28.0 as a typo" is correct for now, but 1.28.x might be released before v2 stable (2026-07-27). This does not affect the spine's pin (`mcp>=1.27.2,<2` allows future 1.28.x).

### F2. mcp SDK 2.0.0a1 v2 alpha — CONFIRMED ✓

**Source:** PyPI release history (same as F1)
**Finding:** `2.0.0a1` — Jun 11, 2026 — the only v2 pre-release. Matches addendum §2 exactly.

### F3. v2.0.0 stable target 2026-07-27 — CONFIRMED ✓

**Source:** Web search 2026-07-12, GitHub repo (https://github.com/modelcontextprotocol/python-sdk)
**Finding:** "Stable v2 is targeted for 2026-07-27." Multiple sources confirm this target date. Note: this is a forward-looking target (~15 days from review date); not yet released.

### F4. Protocol 2025-11-25 stable — CONFIRMED ✓

**Source:** Web search 2026-07-12, modelcontextprotocol.io specification page and GitHub releases
**Finding:** "2025-11-25 is the current stable release of the Model Context Protocol specification." Confirmed by multiple sources.

### F5. Protocol 2026-07-28 RC (breaking: stateless, delete initialize handshake + Mcp-Session-Id) — CONFIRMED ✓

**Source:** Web search 2026-07-12, official RC blog post (https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/)
**Finding:** "MCP is now stateless at the protocol layer, and the `initialize` / `initialized` handshake is removed." The blog post confirms: stateless protocol, `initialize` handshake removed, session management removed from protocol layer. This is a release candidate (→final), consistent with the addendum's "RC→final" notation.

### F6. `initialize`/`initialized` handshake deleted — CONFIRMED with important nuance ⚠️

**Source:** Official v2 migration guide, live fetch 2026-07-12 (https://py.sdk.modelcontextprotocol.io/v2/migration/)
**Finding:** The migration guide's "Client defaults to mode='auto'" section states:

> "In v1, connecting to a server always performed the `initialize` handshake. In v2, `Client` defaults to `mode='auto'`: on enter it probes `server/discover` and, if the server doesn't support it, falls back to the `initialize` handshake."

And under "ClientSession now runs on JSONRPCDispatcher":

> "ClientSession's public surface is unchanged — same constructor apart from timeout parameters, typed methods, manual `initialize()`, and async context-manager lifecycle"

**Nuance:** The PROTOCOL (2026-07-28 spec) removes the `initialize` handshake. But the SDK v2 does NOT delete `ClientSession.initialize()` — it's still available as a legacy method. The `Client` class defaults to `mode='auto'` which probes `server/discover` and falls back to `initialize`. The spine's claim "initialize 删除" is about the protocol, not the SDK API.

**Impact on spine:** The v2 switch path says `handshake(session)` → no-op ("initialize 删除，stateless 每请求 `_meta` 协商"). But if HeAgent keeps using `ClientSession` (as in v1), `initialize()` is NOT deleted — it still works. Making `handshake()` a no-op would mean skipping initialization for 2025-11-25 servers, which is likely wrong. The no-op approach is only valid if HeAgent migrates to `Client(mode='auto')`, which handles handshake internally. (See rubric finding R7.)

**Severity: MEDIUM** — The spine's stated reason for making `handshake()` a no-op ("initialize 删除") conflates protocol-level removal with SDK-level availability. The migration guide explicitly says `ClientSession` retains `manual initialize()`.

### F7. `send_ping()` deprecated — CONFIRMED ✓

**Source:** Official v2 migration guide (same as F6)
**Finding:** The migration guide states: "`Client.send_ping()` is deprecated (ping is removed in 2026-07-28); pin `mode='legacy'` if you need it."

**Note:** The migration guide specifically says `Client.send_ping()` is deprecated, not `ClientSession.send_ping()`. HeAgent uses `session.send_ping()` (`ClientSession`). The migration guide doesn't explicitly say `ClientSession.send_ping()` is deprecated, but it's implied by "ping is removed in 2026-07-28." The addendum's claim is essentially correct.

### F8. `list_tools` params=PaginatedRequestParams — CONFIRMED ✓

**Source:** Official v2 migration guide, section "cursor parameter removed from ClientSession list methods"
**Finding:**

> "The deprecated `cursor` parameter has been removed from the following `ClientSession` methods: `list_resources()`, `list_resource_templates()`, `list_prompts()`, `list_tools()`. Use `params=PaginatedRequestParams(cursor=...)` instead."

The migration guide confirms `ClientSession.list_tools()` is affected. HeAgent's `session.list_tools()` (no cursor param) would still work in v2 (no cursor to remove), but the return type's field names change (snake_case). The spine's AD-1 correctly captures this.

### F9. `inputSchema`→`input_schema` — CONFIRMED ✓

**Source:** Official v2 migration guide, section "Field names changed from camelCase to snake_case"
**Finding:** The migration guide's rename table includes:
- `inputSchema` → `input_schema`
- `isError` → `is_error`
- `nextCursor` → `next_cursor`
- `mimeType` → `mime_type`

The spine's AD-1 captures `inputSchema→input_schema` and `isError→is_error` correctly. The note about `block.text` not changing is correct — `text` is already lowercase, so snake_case conversion is a no-op.

### F10. `mcp.types` → `mcp-types` package — CONFIRMED ✓

**Source:** Official v2 migration guide, section "mcp.types moved to the mcp-types package"
**Finding:**

> "The protocol wire types now live in a standalone distribution, `mcp-types`, imported as `mcp_types`. ... The `mcp` package depends on `mcp-types` and continues to re-export the type names at the top level, so `from mcp import Tool` is unchanged. Only the `mcp.types` submodule and `mcp.shared.version` were removed."

**Note:** The spine's AD-1 says the v2 switch changes `from mcp.types import ...` to `from mcp_types import ...`. This is correct. However, an alternative — `from mcp import Tool, CallToolResult, ...` — also works in v2 (re-exported at top level). The spine's choice of `mcp_types` is valid but not the only option. This is a minor note, not a finding.

### F11. `Client` mode='auto' — CONFIRMED as v2 feature, but addendum's ✓ marking is a FALSE POSITIVE ⚠️

**Source:** Official v2 migration guide, section "Client defaults to mode='auto'"
**Finding:** The migration guide confirms `mode='auto'` is a `Client` class feature:

> "In v2, `Client` defaults to `mode='auto'`: on enter it probes `server/discover` and, if the server doesn't support it, falls back to the `initialize` handshake."

**False positive:** The addendum §3 table marks this as ✓ hit at "manager.py:214,224" (`ClientSession` construction). But `mode='auto'` is a `Client` class parameter, NOT a `ClientSession` parameter. HeAgent uses `ClientSession` directly (manager.py:214: `ClientSession(read, write)`, manager.py:224: `ClientSession(transport[0], transport[1])`), not the `Client` wrapper class. Therefore, `Client mode='auto'` does NOT hit HeAgent's current code.

The spine's AD-1 table correctly omits a row for `Client` construction. But the addendum's ✓ marking is misleading — it should be ✗ (HeAgent doesn't use `Client`). The "5 命中" count in the addendum/brief is actually correct (5 real hits), but the addendum table shows 6 ✓ rows (one false positive).

**Severity: LOW** — The spine itself is correct (AD-1 has no row for `Client mode='auto'`). The addendum's ✓ marking should be corrected to avoid confusion for story authors who read the addendum.

### F12. timeout timedelta→float — CONFIRMED ✓ (not a hit for HeAgent)

**Source:** Official v2 migration guide, section "Timeouts take float seconds instead of timedelta"
**Finding:**

> "Every timeout parameter that took a `datetime.timedelta` in v1 now takes plain seconds as a `float`."

HeAgent's code doesn't pass timeout parameters to SDK methods (`ClientSession()`, `call_tool()`, `list_tools()`, `streamable_http_client()` all called without timeout params). The addendum's "✗ 未显式传 timeout" is correct.

### F13. Mcp-Session-Id deletion — CONFIRMED ✓ (not a direct hit)

**Source:** Official v2 migration guide, section "get_session_id callback removed from streamable_http_client"
**Finding:** `streamable_http_client` returns a 2-tuple `(read, write)` instead of 3-tuple `(read, write, get_session_id)` in v2. HeAgent captures the tuple as `transport` and accesses `transport[0]`, `transport[1]` — works with both 2-tuple and 3-tuple. Not a direct hit, as the addendum correctly omits it.

**Additional v2 changes not listed in the addendum (minor omissions, all non-hits for HeAgent):**
- `streamablehttp_client` (old spelling) removed — HeAgent already uses `streamable_http_client` (new spelling) ✓
- `StreamableHTTPTransport` parameters (`headers`, `timeout`, `sse_read_timeout`, `auth`) removed — HeAgent passes `http_client=` only ✓
- `opentelemetry-api` becomes a new hard dependency in v2 — relevant for v2 switch, not this cycle
- `stdio_client` shutdown reworked (Windows: Job Object deterministic kill; POSIX: children left alive) — HeAgent runs on win32, could affect `_await_shutdown` behavior in v2 switch
- Every outbound request carries `_meta` envelope — wire format change, SDK-handled, not a code hit

These are all v2-switch concerns (deferred) or non-hits, so they don't affect the spine's correctness for this cycle. The v2 switch path documentation could mention them for completeness.

---

## SUMMARY OF FINDINGS

| # | Severity | Finding |
|---|---|---|
| R7/F6 | **MEDIUM** | `ClientSession`-vs-`Client` choice for v2 switch is an undecided dimension. The v2 switch path says `handshake()` → no-op ("initialize 删除"), but `ClientSession.initialize()` is NOT deleted in SDK v2 (migration guide confirms it's retained as manual method). The no-op is only valid if migrating to `Client(mode='auto')`, which would change `manager.py` and potentially violate AD-2's "diff 为空". |
| R2 | **MEDIUM** | AD-2's "v2 切换只改 `session_api.py` 内部实现" guarantee is at risk if the v2 switch requires `ClientSession`→`Client` migration. The spine should explicitly decide or flag as open-question whether v2 keeps `ClientSession` or adopts `Client`. |
| F11 | **LOW** | Addendum §3 marks `Client mode='auto'` as ✓ hit at "ClientSession construction", but `mode='auto'` is a `Client` class parameter. HeAgent uses `ClientSession` directly — false positive. The spine's AD-1 correctly omits this row, but the addendum should be corrected to ✗. |
| R7 | **LOW** | Testing dimension for `session_api.py` itself is under-specified — whether new unit tests for the isolation layer are required this cycle is not stated. Two stories could diverge on test scope. |
| F6 | **LOW** | "initialize 删除" framing in the v2 switch path conflates protocol-level removal (2026-07-28 spec removes the handshake) with SDK-level availability (`ClientSession.initialize()` still works in v2 as legacy). |

**All committed SDK/protocol facts verified current as of 2026-07-12:**
- mcp 1.27.2 latest v1 stable (2026-05-29) ✓ (PyPI)
- mcp 2.0.0a1 v2 alpha (2026-06-11) ✓ (PyPI)
- v2.0.0 stable target 2026-07-27 ✓ (GitHub)
- Protocol 2025-11-25 stable ✓ (modelcontextprotocol.io)
- Protocol 2026-07-28 RC, stateless, initialize removed ✓ (RC blog post)
- All 7 v2 breaking changes verified against official migration guide ✓
