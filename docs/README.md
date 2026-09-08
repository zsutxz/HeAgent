# 文档索引

本文档目录只保留“当前事实、设计意图、迭代方法、运行配置”四类入口。代码事实以 `src/` 为准；
`_bmad-output/` 是历史规划和验收证据，不是当前运行时配置。

## 当前事实

- [架构参考](frame.md)：当前数据流、模块边界、配置、运行时治理和已知缺口。
- [敏捷工作流](workflow_intro.md)：当前 `/goal`、`workflow.md`、Epic/Story 和 checkpoint 的职责边界。
- [部署说明](../deploy/README.md)：部署资产的真实适用范围和限制。

## 推荐阅读路径

1. 先读本索引了解文档职责和权威顺序。
2. 再读 [`design.md`](design.md) 了解项目定位、目标和非目标。
3. 最后按需读 [`frame.md`](frame.md) 的数据流、模块 DAG、`engine/`、`/goal` 和已知缺口。

## 快速定位

| 想了解什么 | 阅读位置 |
| --- | --- |
| LLM、工具和 Agent 如何串起来 | [`frame.md`](frame.md) 的“数据流”和“核心模块” |
| 策略、审批、ledger、沙箱 | [`frame.md`](frame.md) 的 `engine/` 与“已知缺口” |
| Epic/Story 如何由 Markdown 驱动 | [`workflow_intro.md`](workflow_intro.md) 与 [`.heagent/workflows/workflow.md`](../.heagent/workflows/workflow.md) |
| GUI 如何连接 AgentLoop | [GUI 集成方案](../_bmad-output/epics/epic-25-28-GUI界面周期/gui-plan.md) 与 `src/heagent/gui/` |
| 历史为什么这样演进 | [`iteration.md`](iteration.md) 与 [`_bmad-output/`](../_bmad-output/README.md) |

## 设计与维护

- [设计说明](design.md)：项目定位、设计动机、非目标和成熟度判断。
- [迭代指南](iteration.md)：如何继续迭代，以及已完成周期的历史索引。

## 规划归档

- [`_bmad-output/README.md`](../_bmad-output/README.md)：Epic、Story、spec、retrospective 和 patch 的归档导航。
- [`_bmad-output/sprint-status.yaml`](../_bmad-output/sprint-status.yaml)：规划状态的单一权威。
- [GUI 集成方案](../_bmad-output/epics/epic-25-28-GUI界面周期/gui-plan.md)：GUI 设计与实现对照（随 Epic 25-28 归档）。
- [BMad 设计记录](../_bmad-output/epics/epic-47-声明式BMad敏捷工作流周期/bmad-heagent-plan.md)：工作流设计的历史背景和当前实现指针；不作为待办清单。

## 权威规则

1. 运行行为：`src/`。
2. 配置默认值和 CLI 入口：`src/heagent/config.py`、`src/heagent/cli.py`、`pyproject.toml`。
3. 当前 `/goal` 工作流：`.heagent/workflows/workflow.md`。
4. 设计和历史说明：本目录与 `_bmad-output/`，不得覆盖前三项。

新增或变更功能时，先更新对应的当前事实文档；历史规划只追加证据，不回写成“当前实现”。
