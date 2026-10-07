# Deferred Work Archive

> 跨周期 deferred 的唯一总账。活动区只记录未闭合条目；已闭合且有 Epic 归属的正文移入对应周期的 `deferred-work.md`，本文件只保留 ID、状态和链接。当前活动项为 0 条（2026-10-07）。

## 活动（未闭合）条目

无。

## 已按 Epic 归档

| ID | 主题 | 状态 | 正文 |
| --- | --- | --- | --- |
| Z-D10 / Z-D11 / Z-D18 / Z-D20 | Epic 48 TCP 入口与日志审查 | 已闭合 / OBSOLETE | [`epic-48.../deferred-work.md`](../epics/epic-48-TCP网络接口周期/deferred-work.md) |
| Z-D13 / Z-D14 / Z-D15 / Z-D19 / Z-D21 / Z-D22 / Z-D23 / A8 / A9 / A10 / A12 / A15 / A16 / A17 / A18 / A19 / A23 | Epic 50 网页控制台审查 | 已闭合或裁定维持现状 | [`epic-50.../deferred-work.md`](../epics/epic-50-网页控制台周期/deferred-work.md) |
| Z-D24 / A2 | Epic S1-S4 沙箱裁定 | 已闭合（裁定不实施） | [`epic-S1-S4.../deferred-work.md`](../epics/epic-S1-S4-沙箱硬化周期/deferred-work.md) |
| A25 / A26 / A27 / A28 / A33 | Epic 51 Goal/workflow 收口优化 | 已闭合 | [`epic-51.../deferred-work.md`](../epics/epic-51-goal-workflow优化周期/deferred-work.md) |

## 跨周期勘察与裁定索引

以下条目没有唯一 Epic 归属，保留在总账中作为历史索引；详细当前边界以 `docs/frame.md`、`docs/goal-workflow.md` 和源码为准。

| ID | 主题 | 结论 |
| --- | --- | --- |
| Z-D1 / Z-D2 / Z-D4 / Z-D5 / Z-D6 / Z-D7 / Z-D8 / Z-D9 / Z-D12 / Z-D16 / Z-D17 | 架构、解析、日志、沙箱和会话存储勘察 | 已闭合或裁定维持现状 |
| Z-D3 | provider 回退骨架是否统一 | 评估结论为不收敛：chain、key_rotation、switchable、router 的回退条件、粘性和索引语义有意不同；补充互指注释，行为不变 | `providers/{chain,key_rotation,switchable,router,retry}.py`；`tests/test_retry.py::TestPoolFallbackPolicy`；提交 `beea1a2` |
| A3 / A4 / A5 / A11 / A24 | 入口、GUI、观测与运行姿态 | 已闭合，正文留在相关周期记录或提交证据中 |
| A1 / A6 | 技能资源与路径级审批前置裁定 | 裁定维持现状或维持条件性；边界见 `docs/frame.md` 五 |
| A29 / A30 / A31 / A32 | 2026-10-07 架构简化与层次收敛 | 已闭合；证据见提交记录、源码和测试 |

## 维护规则

- 新增未闭合项先登记 ID、触发条件、裁定和验收证据，再开始实施。
- 已闭合项按 Epic 归档正文；不要在本文件复制完整 review 报告。
- `blocked` 需要产品或架构裁定，不能由实现者静默关闭。
