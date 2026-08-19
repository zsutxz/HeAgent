# Retrospective — engine P5 批次（结构化结果 / 树形聚合 / resume 流式）

> **事后补做**（2026-06-29）。engine 是 epic 外 P 批增量（非 sprint-status 标准 epic），不走 `bmad-retrospective` 的 epic discovery，直接按同一 retro 模板生成。
> 证据来源：`docs/frame.md` 4.12 + `git log`（2026-06-25 P5 三件套、2026-06-26 P5-1/P5-2 评估）+ memory `heagent-loop-engine-expansion`。
> 适配 CLI/库项目——省略 sprint velocity / incidents / deployment / stakeholder（不适用，不编造）。

## 批次概览

| 项 | 内容 |
|----|------|
| 批次 | engine P5（epic 外增量，接 P0–P4） |
| 已交付 | P5-3 结构化子任务结果（`SubTaskOutcome`，含 run_id/iterations）、P5-4 `parent_run_id` 树形 checkpoint 聚合（`RunStore.build_run_tree`）、P5-5 resume 流式版（`resume_stream`） |
| Deferred | P5-1（反转 D1，Schema 级工具隐藏）、P5-2（反转 D4，子 agent resume）—— 2026-06-26 评估后**维持冻结** |
| 性质 | 干净增量三件套，不动既有 `run`/`run_stream` 契约 |

## 成果（What went well）

1. **干净增量落地**：三件套均为可叠加增量，不破坏既有 `AgentLoop` 契约（与 NFR-2 零回归理念一致）。
2. **deferred 决策有据可查**：P5-1/P5-2 不是偷懒不做，是评估后收益/成本比差，依据写进 `frame.md` 4.12。
3. **实证修正了计划估计**：发现原 plan **高估** P5-1 成本——`registry.py` 已有 `_disabled`/`enabled_schemas()` schema 级隐藏设施，真要做只需 `loop.py:304/623` 叠加一行 `allowed_tools` 过滤，不必把单例重构为 per-agent。

## 挑战（Challenges）

1. **评估带不确定性**：P5-1/P5-2 的「暂不反转」结论基于**静态代码分析，未跑真实 LLM 实测**——需要观测真实使用数据后再评估。
2. **反转副作用链复杂**：P5-2 反转不只是实现成本，还有运行时副作用——`.heagent/runs/` checkpoint 文件爆炸（`task_parallel` 并行放大）+ 嵌套 resume 级联 + 与 compressor/window_reset 互斥断言冲突。

## 教训（Key lessons）

1. **反转 deferred 前先核实既有代码是否已提供半成品**：P5-1 被 plan 高估，因为 registry 已有 schema 级隐藏设施。计划阶段的成本估计要由代码实证修正。
2. **deferred 反转绑定可观测触发条件，避免 YAGNI**：P5-1「误调率高才做」、P5-2「实测需要才开放」——把「做不做」挂在可观测指标上，而非拍脑袋。
3. **增量要保持干净**：P5 三件套都是叠加式，不动既有契约；新能力尽量经 DI（`EngineContainer`）/ metadata 扩展，不改核心方法签名。
4. **评估结论要记录依据（含不确定性）**：`frame.md` 明写「基于静态分析，未实测」——诚实暴露不确定性，便于日后重新评估，而非把假设当结论。

## 技术债 / 遗留（Deferred）

| 项 | 触发条件 | 状态 |
|----|----------|------|
| P5-1 Schema 级工具隐藏（反转 D1） | 真实高误调率 | deferred；`loop.py:304/623` 加一行过滤即可，待触发 |
| P5-2 子 agent resume（反转 D4） | 子 agent 实测需清窗重建 | deferred；代价大（checkpoint 爆炸 + 级联 + 互斥冲突） |
| engine sandbox 接真实后端 | — | `execute_in_sandbox` 默认透传，未接真实沙箱（`frame.md` 五已知缺口） |

## 行动项（Action items）

| # | 行动 | Owner | 触发 / 时机 |
|---|------|-------|-------------|
| A1 | 观测子 agent 工具误调率，达标则启动 P5-1（`loop.py:304/623` 加 `allowed_tools` 过滤） | tan | 误调率升高 |
| A2 | 子 agent 任务量级增长到频繁撞 context 上限时，重新评估 P5-2 | tan | 子 agent 频繁触发清窗 |
| A3 | engine sandbox 接真实后端作为独立 P 批候选 | tan | 已记入 `docs/iteration.md` 第四章 |

## 下一步

见 [`docs/iteration.md`](../../docs/iteration.md) 第四章「路线图与下一步」——engine 增量方向（P5-1/P5-2 反转、sandbox 后端）均为 epic 外增量候选。

## 不适用字段（CLI/库项目）

sprint velocity / 实际-vs-计划 story points / production incidents / deployment / stakeholder acceptance —— 省略，不编造。
