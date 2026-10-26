---
title: '57-3 端到端围栏贯通冒烟测试（52-3 AC1）'
type: 'test'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
baseline_commit: '54aa99e9a988839b1c4cd05b200069f1b350e9c9'
context: []
---

<!-- 闭环 sprint-status：epic-52-retro-item-3（可落地子项口径，见 epics.md 范围裁定）。 -->

## Intent

**Problem:** epic-52 的写允许集围栏只有分段覆盖：BLOCKED 判定由 52-1 单测（打桩层）、宿主参数传递由 52-3 断言——「工具链真的拦截越集写」这一贯通路径无单一测试。台账登记为「52-3 AC1 端到端围栏贯通冒烟」，是审计语义 5 项中唯一不需要前置设计决策即可落地的子项。

**Approach:** 补一条贯通测试：真实 `@tool` 注册的写工具（不走 mock handler）经完整执行链 `PolicyEngine.evaluate() → ToolExecutor → SafetyGuard → handler`，对允许集内路径写成功、对集外路径写被围栏拒绝（BLOCKED），断言判负语义（FAILED + 撤销闩）由链路真实产生而非打桩。落点遵循既有 52 系测试文件布局。其余 4 项审计语义项维持 `implementation-artifacts/deferred-work.md` 挂账（触发条件不变）。

## Acceptance Criteria

1. 新增测试覆盖「链路真实拦截越集写」：无打桩的 handler 层，拒绝来自围栏而非 mock。
2. 允许集内写入在同测试中验证仍畅通（防拦截过宽的回归）。
3. 台账 `52-3 AC1` 行闭合；52-retro item-3 以「e2e 落地 + 4 项挂账确认」口径转 done。
