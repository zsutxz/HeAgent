# 文档索引

本文档目录按架构、开发、测试、部署、设计、迁移和历史资料组织。代码事实以 `src/` 为准；
`_bmad-output/` 是历史规划和验收证据，不是当前运行时配置。

## 当前事实

| 分类 | 入口 | 维护责任与更新触发 |
| --- | --- | --- |
| 架构 | [frame.md](frame.md) | 模块变更提交者同步依赖、接口和运行行为 |
| 开发 | [项目协作规则](../AGENTS.md)、[上手说明](../README.md) | 工程维护者随命令、依赖和规范变更更新 |
| 测试 | [质量门禁脚本](../scripts/quality_gate.py) | 各阶段实施者验证命令、结果、限制和待办 |
| 部署 | [部署说明](../deploy/README.md) | 部署变更提交者同步环境前提 |
| 产品设计 | [design.md](design.md) | 产品需求变更提交者同步目标与非目标 |
| 迁移记录 | [架构沿革](architecture-history.md) | 实施者在修改边界前核验兼容性与迁移测试 |
| 历史 | [迭代历程](iteration.md)、[架构沿革](architecture-history.md) | 架构变更提交者追加事实和来源 |
| 外部资料 | [新闻归档](news.md) | 资料提交者保留采集日期与来源，不作为项目实现依据 |
| 观测 | [frame.md 事件契约](frame.md) | 事件字段/发射点变更提交者同步逐 kind 表与黄金测试 |
| 性能 | [基准入口](#诊断命令速查不适用请看-troubleshooting) → [troubleshooting.md](troubleshooting.md) | 基准/阈值入口随测试基建变更更新 |

维护责任按变更角色定义，不虚构个人负责人。专题中的日期是分析或采集时间，不代表持续更新承诺。

- [架构参考](frame.md)：当前数据流、模块边界、配置、运行时治理和已知缺口。
- [部署说明](../deploy/README.md)：部署资产的真实适用范围和限制。
- [扩展指南](extending.md)：新增 Provider / Tool / Skill 包的步骤与契约自检。
- [故障排查](troubleshooting.md)：症状 → 诊断命令 → 相关模块速查。
- [「Goal 工作流」专题](goal-workflow.md)：`/goal`、`workflow.md`、Epic/Story 和 checkpoint 的职责边界。

## 推荐阅读路径

1. 先读本索引了解文档职责和权威顺序。
2. 再读 [`design.md`](design.md) 了解项目定位、目标和非目标。
3. 最后按需读 [`frame.md`](frame.md) 的数据流、模块 DAG、`engine/`、网络入口（TCP 4.16 / HTTP 4.17 / 网页控制台 4.18）、`/goal` 和已知缺口。

## 快速定位

| 想了解什么 | 阅读位置 |
| --- | --- |
| LLM、工具和 Agent 如何串起来 | [`frame.md`](frame.md) 的“数据流”和“核心模块” |
| 策略、审批、ledger、沙箱 | [`frame.md`](frame.md) 的 `engine/` 与“已知缺口” |
| Epic/Story 如何由 Markdown 驱动 | [「Goal 工作流」专题](goal-workflow.md) 与 [`.heagent/skills/he-goal/workflow.md`](../.heagent/skills/he-goal/workflow.md) |
| 事件流 / rollout 字段含义 | [`frame.md`](frame.md) 的「事件契约」小节（4.15） |
| 把 agent 暴露成 TCP 服务 / 写外部客户端 | [README「TCP 入口（实验性）」](../README.md) 与 [`frame.md`](frame.md) 的 4.16（协议 / 限额 / 安全立场） |
| 网页入口 / 写浏览器端 / HTTP API | [README「HTTP 网页入口（实验性）」](../README.md) 与 [`frame.md`](frame.md) 的 4.17（SSE 重连 / 同源防线 / 限额 / 观测） |
| 网页控制台：多项目 / 会话 / 配置面板与写入 | [`frame.md`](frame.md) 的 4.18（工作区模型 / 项目注册表 / 会话持久化 / 四层配置来源 / 写通道 10 步 / 生效语义 / 安全立场与已知缺口） |
| 如何新增 provider / tool / 技能包 | [扩展指南](extending.md) |
| 报错/行为异常先查哪 | [故障排查](troubleshooting.md) |
| GUI 如何连接 AgentLoop | [GUI 集成方案](../_bmad-output/epics/epic-25-28-GUI界面周期/gui-plan.md) 与 `src/heagent/gui/` |
| 历史为什么这样演进 | [`iteration.md`](iteration.md) 与 [`_bmad-output/`](../_bmad-output/README.md) |

## 设计与维护

- [设计说明](design.md)：项目定位、设计动机、非目标和成熟度判断。
- [迭代指南](iteration.md)：如何继续迭代，以及已完成周期的历史索引。
- [质量门禁脚本](../scripts/quality_gate.py)：冒烟、回归与覆盖率、lint、format 和类型检查的执行入口。

## 规划归档

- [`_bmad-output/README.md`](../_bmad-output/README.md)：Epic、Story、spec、retrospective 和 patch 的归档导航。
- [`_bmad-output/sprint-status.yaml`](../_bmad-output/sprint-status.yaml)：规划状态的单一权威。
- [GUI 集成方案](../_bmad-output/epics/epic-25-28-GUI界面周期/gui-plan.md)：GUI 设计与实现对照（随 Epic 25-28 归档）。
- [BMad 设计记录](../_bmad-output/epics/epic-47-声明式BMad敏捷工作流周期/bmad-heagent-plan.md)：工作流设计的历史背景和当前实现指针；不作为待办清单。

## 权威规则

1. 运行行为：`src/`。
2. 配置默认值和 CLI 入口：`src/heagent/config.py`、`src/heagent/cli.py`、`pyproject.toml`。
3. 当前 `/goal` 工作流：`.heagent/skills/he-goal/workflow.md`。
4. 设计和历史说明：本目录与 `_bmad-output/`，不得覆盖前三项。

新增或变更功能时，先更新对应的当前事实文档；历史规划只追加证据，不回写成“当前实现”。

---

## Goal 工作流

声明式 `/goal` 工作流的职责边界、权威关系、八步流程、写权限边界与产物布局已迁至专题文档
[`goal-workflow.md`](goal-workflow.md)（一处定义，他处链接）。可执行契约的唯一来源仍是
[`.heagent/skills/he-goal/workflow.md`](../.heagent/skills/he-goal/workflow.md)。
