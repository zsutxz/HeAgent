# PRD Quality Review — HeAgent MCP Client 集成 V2

## Overall verdict

A well-crafted single-operator dev-tool PRD that earns its shape: sharp thesis, honest scope, high done-ness bar, accurate brownfield anchors (every cited V1 extension point — `mcp_tool_to_schema` / `PolicyVerdict` / `evaluate_tool_call` / `approved_tools` / `__mcp__` / `bridge_result` — verified against `src/heagent/`). The main risk is a **decision-readiness framing contradiction on P4**: FR-A5 is labeled "（P4 定稿）" while the same FR's ASSUMPTION blockquote and §8 OQ-1 both say "待 review" with live alternatives — an engineer writing stories from FR-A5 has crisp testable consequences, but a PM reading OQ-1 will reasonably wonder whether the base decision is actually settled. Secondary ding: FR-B5 is a deferred non-goal dressed as an FR with a consequence that is itself a deferred ASSUMPTION. Both are small fixes; neither blocks architecture handoff.

Calibration applied (per task): single-operator dev tool → UJ light-to-medium is correct, SM operational is correct, persona/innovation theater dimensions read as substance-positive here, not flagged.

## Decision-readiness — adequate

P1 (Resources on-demand) is genuinely settled: FR-B3 carries an explicit "P1 定稿" marker and no OQ reopens the *model* choice. P2 (Prompts as CLI slash) is settled in practice — §4.3 commits to `/mcp-prompt` consistently and no OQ offers the alternative (expose-as-tool) — but is less explicit than P1/P4 (no "P2 定稿" tag). P3/P5 already confirmed in brief (2026-07-17 checkpoint). Trade-offs are surfaced honestly: the security stance (annotations = untrusted server self-attestation, "非真正安全边界", needs OS sandbox) is repeated faithfully across Vision / Glossary / FR-A notes / NFRs — arguably over-faithful (same paragraph in 4 places) but not theater.

The real weakness is P4. FR-A5 is titled "（P4 定稿）" with crisp consequences, then an ASSUMPTION blockquote says "本 PRD 定稿，**待 tan 在 review 时确认保守度**——若嫌「缺 annotations 全要确认」太吵，备选见 §8 OQ-1" — and OQ-1 reopens the same question with two live alternatives ("白名单放行 / per-server 关闭 fail-safe. 本 PRD 取最保守，**待 review**"). You cannot simultaneously call something 定稿 and 待 review. Either own the decision (then OQ-1 becomes a V3 enhancement consideration and drops "待 review") or admit it is provisional (then strip "定稿" from FR-A5's title). The 5 OQs themselves are genuinely open — not rhetorical questions with built-in answers — this is a framing issue, not a fake-OQ issue.

The 5 OQs are also correctly scoped: OQ-2 (annotations 接入点), OQ-4 (CLI slash 机制), OQ-5 (订阅 defer) are legitimately architecture-stage decisions and the PRD is right not to lock them. OQ-1 and OQ-3 are the only two that touch PRD-level product behavior, and OQ-3 (策略优先级, "显式策略 vs annotation") overlaps with FR-A4's ASSUMPTION-tagged consequence — see done-ness finding.

### Findings
- **high** P4 self-contradiction: "定稿" vs "待 review" (§4.1 FR-A5 title + ASSUMPTION blockquote; §8 OQ-1). The most important FR cluster (写操作治理) carries a framing contradiction that makes it ambiguous whether the base decision is actually settled. *Fix:* pick one framing. Recommended: keep "P4 定稿" in FR-A5, strip "待 tan 在 review 时确认保守度" from the ASSUMPTION, and rewrite OQ-1 as a V3 enhancement consideration (whitelist / per-server relaxation) with the "待 review" language removed — OR rename FR-A5 title to "（P4 暂定保守）" and let OQ-1 keep its current form.
- **medium** P2 settlement is implicit (§4.3 Epic C). P1 and P4 carry explicit "定稿" markers; P2 (CLI slash vs expose-as-tool) does not, even though it is settled in practice. *Fix:* add a one-line "（P2 定稿）" tag in FR-C2 or §4.3 Description, mirroring FR-A5/FR-B3, for symmetry and PM scannability.

## Substance over theater — strong

No persona theater (the only "persona" is tan himself, stated honestly as "我既是这个 agent 的作者、也是它的主操作者" in §2.1 JTBD 情感). No innovation theater — §1 Vision's claimed novelty ("让危险等级的判定始终在代码层、不在 LLM 层") is earned by being tied directly to the硬约束 "确定性逻辑交给代码、不交给概率模型" and operationalized in FR-A6 with a testable pure-function单测 shape. No NFR theater — feature-specific NFRs are concrete ("裁决纯函数化，无 LLM 参与" / "on-demand 模型确保 resources 不侵蚀上下文窗口"), not boilerplate scalability/security/reliability copies. No Vision theater — the Vision is specific to HeAgent's V1 frozen gaps, would not swap cleanly into another PRD. The repeated "DP-4 同构 / 非真正安全边界" disclaimer (Vision, Glossary, FR-A notes, NFR, Non-Goals) is deliberate emphasis for a security-stanced doc, not furniture — acceptable.

## Strategic coherence — strong

Clear thesis: 补全 V1 刻意冻结的三处缺口 (写操作治理 + Resources + Prompts), with a unified mechanism story ("落在 V1 既有扩展点上，不引入新机制"). Prioritization follows value, not ease: Epic A (写操作治理) first because it directly resolves a硬约束 conflict ("LLM 选了就执行" vs "确定性逻辑交给代码"); Epic C (Prompts) last because it is explicitly the weakest leg ("价值/成本比最低", §4.3 Notes / §6.2). SMs validate the thesis (SM-1/2/3 cover the three features; SM-5 validates the 确定性 sub-thesis). Counter-metric present and genuinely thoughtful: SM-C1 "不过度审批只读工具" directly catches the failure mode of SM-1's conservative bias and is tied back to UJ-1's emotional job ("避免这个"). MVP scope is coherent problem-solving/platform shape.

## Done-ness clarity — adequate

This dimension applied unforgivingly as instructed. 12 of 13 FRs carry genuinely testable consequences with explicit failure semantics — no "gracefully / 合理 / 友好" soft language anywhere in FR bodies. Highlights: FR-A3 specifies the authorization mechanism verbatim ("metadata.approved_tools 含该工具 / * / __mcp__") and I verified this matches `engine/policy.py:243-248` exactly. FR-A6 even specifies the test shape ("构造 destructive / readOnly / 缺省三种 annotations → 断言 APPROVAL_REQUIRED / 非 approval / APPROVAL_REQUIRED, 全程无 LLM 调用"). FR-B2 specifies explicit failure ("指定 URI 不存在 → ToolError, 不静默空返"). FR-A5 distinguishes the verdict from DIRECT ("→ APPROVAL_REQUIRED（不是 DIRECT）"). Excellent bar.

Three real dings:
1. **FR-B5 is a non-goal dressed as an FR.** Its Consequence is itself an ASSUMPTION ("V2 不实现... 架构阶段须评估订阅是否纳入 V2 — 若 stateless 迁移使其失效... 确认 defer 并记入 Open Items"). An FR whose consequence is "decide whether to do this" is not done-ness — it belongs in §5 Non-Goals (which already lists it) or should be deleted as duplicate.
2. **FR-A4 second consequence is an open assumption.** The priority between explicit policy (`approval_tools` / `approval_mcp_tools`) and annotation is `[ASSUMPTION: 显式策略优先于 annotation]` and reopened at OQ-3 ("待确认"). An engineer writing the story for FR-A4 cannot write the priority test without picking a side. I verified the current code (`policy.py:227`) uses `approval_mcp_tools OR in approval_tools` with no annotation concept yet, so either direction is implementable — but the PRD should lock the priority or move it out of FR-A4's consequence.
3. **FR-A2 "缺省时留空/保守标记" is an either/or.** "（缺省时留空/保守标记）" presents two different default representations as a slash without picking one. FR-A5 then consumes "缺 annotations" downstream, so the FR-A2 default must align with FR-A5's "fail-safe" semantics — currently the two FRs could be read as inconsistent (留空 ≠ 保守标记). Minor but fixable.

### Findings
- **medium** FR-B5 is a deferred non-goal dressed as an FR with a deferred consequence (§4.2 FR-B5). An FR that says "default not doing X, architecture will decide" fails the done-ness contract. *Fix:* delete FR-B5 from §4.2 (it duplicates §5 Non-Goals "不做 Resources 订阅" and OQ-5) OR rewrite as a positive FR with a testable consequence if subscription is in scope.
- **medium** FR-A4 priority consequence is an open assumption (§4.1 FR-A4 Consequence 2 + §8 OQ-3). Cannot write the priority test until settled. *Fix:* either lock "显式策略优先" as the decision (strip "待确认" from OQ-3 and downgrade it to a closed decision record) or move the priority question fully out of FR-A4 consequence to OQ-3 and leave FR-A4 with only the readOnly→非 APPROVAL_REQUIRED consequence.
- **low** FR-A2 default representation ambiguous (§4.1 FR-A2 "缺省时留空/保守标记"). *Fix:* pick one — recommend "保守标记" (mark as fail-safe) to align with FR-A5 semantics, drop the slash.

## Scope honesty — strong

Exemplary §5 Non-Goals section: 10 explicit non-goals, inherits V1 Out, marks `[NON-GOAL for MVP]` on the one omission (Resources 自动全量注入) that could otherwise be silently assumed. `[ASSUMPTION]` index roundtrip is clean — all 7 inline ASSUMPTION tags (FR-A1, FR-A4, FR-A5, FR-B2, FR-B3, FR-B5, FR-C2) appear in §9, and every §9 entry points back to a real inline tag. `[NOTE FOR PM]` callouts land at real tensions: §4.1 annotations 接入点 deferral, §4.3 Prompts 最弱腿 defer candidate, §6.2 Epic C 首选 defer. De-scoping is proposed honestly (§6.2 Epic C defer candidate stated upfront, not buried). Open-items density (~5 OQ + 7 ASSUMPTION + 3 NOTE FOR PM ≈ 15) is moderate for a 3-epic PRD — not a blocker for a single-operator dev tool, and most OQs are correctly deferred to architecture rather than fake-settled.

## Downstream usability — strong

Glossary present (§3), explicitly designated "全文唯一词汇源，禁止引入同义词," and terms are used consistently downstream (写操作治理 / PolicyVerdict / fail-safe / on-demand / namespace / DP-4 围栏 / destructive 工具 all verbatim across FRs/UJs/SMs). FR ID scheme (FR-A1…A7 / FR-B1…B5 / FR-C1…C4) is contiguous and unique; letter prefixes map to brief's P5 structure and the PRD states this mapping explicitly in the §0 preamble. UJ IDs (UJ-1/2/3) each have a named protagonist (tan) carrying context inline, and each UJ back-links via "Realizes FR-Xn" in feature Descriptions; SMs back-link via "Validates FR-Xn." Cross-refs resolve. Each section reads cleanly pulled out alone — no floating "see above" dependencies. This PRD is source-extractable for `bmad-architecture` and `bmad-create-epics-and-stories` without re-reading brief.

## Shape fit — strong

Single-operator dev tool / internal library shape, correctly calibrated. UJ density (3, light-to-medium) is appropriate — not over-formalized (no multi-persona theater), not under-formalized (FRs are crisp with testable consequences, SMs are operational not vanity). SMs are behavioral ("走 APPROVAL_REQUIRED, 不裸调" / "E2E 可断言" / "单测可证") not DAU/MAU — correct for the product type. Brownfield correctness is high: every cited V1 extension point verified in `src/heagent/` (`mapping.mcp_tool_to_schema`, `mapping.bridge_result`, `mapping.normalize_server_name`, `PolicyVerdict`, `evaluate_tool_call`, `metadata.approved_tools`, `_is_mcp_tool`, `__mcp__` authorization, `approval_mcp_tools`) — the PRD's FR-A3 authorization claim matches `policy.py:243-248` line-for-line. Chain-top downstream usability covered in dim 6.

## Mechanical notes

- **Builtins count drift**: PRD §7 SM-4 and brief both cite "18 内置工具测试" / "18 内置工具"; project `CLAUDE.md` says "builtins/（19 工具）"; actual count of `@tool` decorators under `src/heagent/tools/builtins/` is 20 (some may be helpers/aliases). Not load-bearing for V2 PRD scope, but the regression-baseline number in SM-4 should match the actual test count or SM-4 becomes un-falsifiable. *Recommend:* recompute and pin the number at story-creation time.
- **Security disclaimer repetition**: the "annotations = server 自声明、不可信 / 非真正安全边界 / 须 OS 级沙箱兜底" stance appears in §1 Vision, §3 Glossary (DP-4 围栏 entry), §4.1 Description + Feature-specific NFR + Notes, §5 Non-Goals. Deliberate emphasis is fine, but the §5 Non-Goals entry "不做 用户可配置注入签名入口" re-explains the stance — could trim to a one-line cross-ref to §1/§3.
- **`[NOTE FOR PM]` tagging consistency**: §4.1 Notes uses a bare "`[NOTE FOR PM]`：" inline colon form; §4.3 Notes and §6.2 use the same form. Consistent — no drift. (Noting because checklist asks.)
- **OQ-1 ↔ FR-A5 link is explicit** but OQ-1's "待 review" language is the only OQ that contradicts a "定稿" claim elsewhere — see decision-readiness HIGH finding. Other 4 OQs are clean.
- **UJ protagonist naming**: all three UJs name "tan" consistently and carry context inline. No floating UJs. (Mechanical check passes.)
- **FR-A6 "非 approval"** is slightly looser than naming the actual mode (`DIRECT` / `SANDBOX_REQUIRED`) — the test could assert a specific mode rather than "非 APPROVAL_REQUIRED". Minor tightening opportunity, not a finding.
