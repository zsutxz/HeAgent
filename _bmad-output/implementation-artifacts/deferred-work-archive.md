# Deferred Work Archive

> 跨周期 deferred 的唯一总账。活动区只记录未闭合条目；已闭合且有 Epic 归属的正文移入对应周期的 `deferred-work.md`，本文件只保留 ID、状态和链接。当前活动项为 3 条（2026-10-20，A34–A36 均挂起）。

## 活动（未闭合）条目

| ID | 主题 | 状态 | 说明 |
| --- | --- | --- | --- |
| A34 | 会话文件并发写残余：不可安全判定形态回退 last-write-wins 时丢对方一侧 | 挂起待裁定（2026-10-20） | 主害已闭合（Z-D21，commit `9860a17`）。残余形态：共享前缀被改写 / 磁盘比基线短 / 基线对不上 / 文件不可解析 ⇒ 回退时丢对方一侧（有 WARNING 点名原因，不静默）。候选加固 = 把不可判形态的对方侧隔离进 sidecar 文件而非丢弃。实施前置：须先裁定「隔离 vs 丢弃」语义；触发条件 = 出现真实触发案例或用户裁定升级 |
| A35 | HTTP 入口会话/事件持久化（进程内在途 run 与 SSE 缓冲重启即丢） | 挂起待触发（2026-10-20） | 会话历史已落盘（SessionStore，CLI 与网页共用），重启只丢**在途 run** 与 SSE 事件缓冲（重连有 `resync_required`→快照兜底）。最小收敛路径 = 复用既有钩子 `EVENTS_ROLLOUT_ENABLED`（per-run `rollout.jsonl`，默认关，本机未开启）做重连回放，**不**新做投影持久化架构。触发条件 = 重启丢在途 run 实际困扰 ≥2 次，或长 run（>10min）常态化。来源：frame.md §4.17/§4.18 既有延后决策 |
| A36 | 全局级 MCP 注入签名配置入口 | 挂起待触发（2026-10-20） | 项目级 `.heagent/injection_signatures.json` 已接入并进程内缓存；2026-10-20 查证本机项目级与全局级文件**均不存在**（零使用）⇒ 现在加全局入口属 YAGNI。触发条件 = 实际开始写自定义签名且需跨项目共享；届时照 skills 双根 / `setting.md` 既有模式接线。注意：签名围栏非真正安全边界，加码不改变「须 OS 沙箱兜底」立场。来源：frame.md 五「用户可配置 MCP 签名入口」行 |

## 已按 Epic 归档

| ID | 主题 | 状态 | 正文 |
| --- | --- | --- | --- |
| Z-D10 / Z-D11 / Z-D18 / Z-D20 | Epic 48 TCP 入口与日志审查 | 已闭合 / OBSOLETE | [`epic-48.../deferred-work.md`](../archive/epics/epic-48-TCP网络接口周期/deferred-work.md) |
| Z-D13 / Z-D14 / Z-D15 / Z-D19 / Z-D21 / Z-D22 / Z-D23 / A8 / A9 / A10 / A12 / A15 / A16 / A17 / A18 / A19 / A23 | Epic 50 网页控制台审查 | 已闭合或裁定维持现状 | [`epic-50.../deferred-work.md`](../epics/epic-50-网页控制台周期/deferred-work.md) |
| Z-D24 / A2 | Epic S1-S4 沙箱裁定 | 已闭合（裁定不实施） | [`epic-S1-S4.../deferred-work.md`](../archive/epics/epic-S1-S4-沙箱硬化周期/deferred-work.md) |
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
