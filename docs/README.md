# 文档索引

本文档目录按架构、开发、测试、部署、设计、迁移和历史资料组织。代码事实以 `src/` 为准；
`_bmad-output/` 不是当前运行时配置——它分两区：`initiative-heagent/` 是**活动**规划区（票树 `tickets/`
是 Epic/Story 状态的唯一写目标），其余目录是历史规划与验收证据。

## 当前事实

| 分类 | 入口 | 维护责任与更新触发 |
| --- | --- | --- |
| 架构 | [frame.md](frame.md) | 模块变更提交者同步依赖、接口和运行行为 |
| 开发 | [项目协作规则](../AGENTS.md)、[上手说明](../README.md) | 工程维护者随命令、依赖和规范变更更新 |
| 测试 | [testing.md](testing.md)（门禁红了的怎么分诊）、[质量门禁脚本](../scripts/quality_gate.py) | 各阶段实施者验证命令、结果、限制和待办 |
| 部署 | [部署说明](../deploy/README.md) | 部署变更提交者同步环境前提并在 4 种部署姿态里核对监听身份 |
| 产品设计 | [design.md](design.md) | 产品需求变更提交者同步目标与非目标 |
| 使用问答 | [faq.md](faq.md) | 常见问题提交者补充问答与命令；机制细节仍归 frame.md |
| 错误索引 | [errors.md](errors.md) | 新增/改名错误码与常见报错时同步四张表；码的权威口径仍归 frame.md 4.17 |
| 性能调优 | [performance.md](performance.md) | 基准/阈值/常用开关变更时同步方法、瓶颈与推荐值 |
| 迁移与历史 | [迭代历程](iteration.md)（§3.3 架构沿革与参考来源） | 实施者在修改边界前核验兼容性与迁移测试；架构变更提交者追加事实和来源 |
| 外部资料 | [新闻归档](../news/news.md)（`news/` 与 `docs/news.md` 均已 gitignore，属本地运行时产物，克隆后可能不存在） | 资料提交者保留采集日期与来源，不作为项目实现依据 |
| 观测 | [frame.md 事件契约](frame.md) | 事件字段/发射点变更提交者同步逐 kind 表与黄金测试 |
| API 参考 | [docs/api/](api/)（12 个核心包的 docstring 自动生成：`::: heagent.<包>` + `show_submodules`） | 包内新增模块不用改；**新增/删除一级核心包**要同步页文件 + [mkdocs nav](../mkdocs.yml) + [api/index.md](api/index.md) 表（判据 `tests/test_api_docs_pages.py`） |
| 性能 | [性能基准](#性能基准) | 基准/阈值入口随测试基建变更更新 |

维护责任按变更角色定义，不虚构个人负责人。专题中的日期是分析或采集时间，不代表持续更新承诺。

- [架构参考](frame.md)：当前数据流、模块边界、配置、运行时治理和已知缺口。
- [常见问题](faq.md)：配置 / 使用 / 故障排查三栏问答；答案首句给结论、随后给命令，机制细节回指 frame.md。
- [错误信息索引](errors.md)：传输层 35 码 + 框架 9 异常 + CLI 常见报错的「码 → 原因 → 修法」索引，附关键词跳转表。
- [性能调优指南](performance.md)：三层分析方法、常见瓶颈判据、常用开关的推荐值与代价、benchmark 验证闭环。
- [部署说明](../deploy/README.md)：部署资产的真实适用范围和限制，含 `local` / `lan` / `external` 三种监听姿态与各自代价。
- [「Goal 工作流」专题](goal-workflow.md)：`/goal`、`workflow.md`、Epic/Story 和 checkpoint 的职责边界；v7 的 `/loop` 工作流（8 步、票树为规划真源）见 `.heagent/skills/loop/workflow.md`。
- [「沙箱机制」专题](sandbox.md)：`CommandRunner` 四档后端、端到端调用链、会话层，以及 `container` 档（2026-10-21）相对旧形态的变化。

## 推荐阅读路径

1. 先读本索引了解文档职责和权威顺序。
2. 再读 [`design.md`](design.md) 了解项目定位、目标和非目标。
3. 最后按需读 [`frame.md`](frame.md) 的数据流、模块 DAG、`engine/`、网络入口（HTTP 4.17 / 网页控制台 4.18）、`/goal` 和已知缺口。

## 快速定位

| 想了解什么 | 阅读位置 |
| --- | --- |
| LLM、工具和 Agent 如何串起来 | [`frame.md`](frame.md) 的“数据流”和“核心模块” |
| 策略、审批、ledger、沙箱 | [`frame.md`](frame.md) 的 `engine/` 与“已知缺口” |
| 沙箱到底怎么跑 / 命令有没有被隔离 | [「沙箱机制」专题](sandbox.md)（调用链、四档后端、`container` 档前提） |
| Epic/Story 如何由 Markdown 驱动 | [「Goal 工作流」专题](goal-workflow.md) 与 [`.heagent/skills/he-goal/workflow.md`](../.heagent/skills/he-goal/workflow.md) |
| 事件流 / rollout 字段含义 | [`frame.md`](frame.md) 的「事件契约」小节（4.15） |
| 网页入口 / 写浏览器端 / HTTP API | [README「HTTP 网页入口（实验性）」](../README.md) 与 [`frame.md`](frame.md) 的 4.17（SSE 重连 / 同源防线 / 限额 / 观测） |
| 网页控制台：多项目 / 会话 / 配置面板与写入 | [`frame.md`](frame.md) 的 4.18（工作区模型 / 项目注册表 / 会话持久化 / 四层配置来源 / 写通道 10 步 / 生效语义 / 安全立场与已知缺口） |
| 如何新增 provider / tool / 技能包 | [项目协作规则](../AGENTS.md) 的「新增扩展点」章 |
| GUI 如何连接 AgentLoop | [GUI 集成方案](../_bmad-output/epics/epic-25-28-GUI界面周期/gui-plan.md) 与 `src/heagent/gui/` |
| 历史为什么这样演进 | [`iteration.md`](iteration.md) 与 [`_bmad-output/`](../_bmad-output/README.md) |

## 设计与维护

- [设计说明](design.md)：项目定位、设计动机、非目标和成熟度判断。
- [迭代指南](iteration.md)：如何继续迭代，以及已完成周期的历史索引。
- [质量门禁脚本](../scripts/quality_gate.py)：冒烟、回归与覆盖率、lint、format 和类型检查的执行入口。
- [文档站点构建](../scripts/build_docs.py)：`python scripts/build_docs.py` 一条命令跑 `mkdocs build --strict`（产物落 `.heagent/tmp/mkdocs-site`，页脚版本取自 `heagent.__version__`）；`docs/api/` 的 API 参考由 `mkdocstrings` 从 docstring 生成（构建期依赖：`pip install mkdocs "mkdocstrings[python]"`）。
- [claude-updater/](claude-updater/)：外部工具更新的摘录归档（Claude 更新摘要）。参考资料，不参与「权威规则」的优先级。

## 性能基准

> 判读口径、常见瓶颈与常用开关的推荐值见 [性能调优指南](performance.md)；本节只给命令。

基准用例不进默认回归（`pyproject.toml` 的 `addopts` 已 deselect `benchmark` 标记），要显式运行：

```bash
# 跑一遍看数字
python -m pytest -m benchmark -q

# 入库基线 → 后续与它对比做阈值检查（超出即失败：数量级守护）
python -m pytest -m benchmark -q --benchmark-autosave --benchmark-storage=./benchmark-data
python -m pytest -m benchmark -q --benchmark-storage=./benchmark-data --benchmark-compare=0001 --benchmark-compare-fail=min:50%
```

`--benchmark-autosave` / `--benchmark-storage` / `--benchmark-compare` 都是**命令行选项**（pytest-benchmark 不从 `pyproject.toml` 读基准设置），因此入库与阈值检查都要显式传参；基线目录 `./benchmark-data/` 是本地产物，已在 `.gitignore`。

## 规划归档

- [`_bmad-output/README.md`](../_bmad-output/README.md)：Epic、Story、spec、retrospective 和 patch 的归档导航。
- [`_bmad-output/initiative-heagent/tickets/`](../_bmad-output/initiative-heagent/tickets/)：v7 票树，Epic/Story 状态的唯一写目标；v6 的 `sprint-status.yaml` 已归档到 [`archive-v6/`](../_bmad-output/initiative-heagent/archive-v6/)（只读历史，不再是状态真源）。
- [GUI 集成方案](../_bmad-output/epics/epic-25-28-GUI界面周期/gui-plan.md)：GUI 设计与实现对照（随 Epic 25-28 收口）。
- [BMad 设计记录](../_bmad-output/epics/epic-47-声明式BMad敏捷工作流周期/bmad-heagent-plan.md)：工作流设计的历史背景和当前实现指针；不作为待办清单。

## 权威规则

1. 运行行为：`src/`。
2. 配置默认值和 CLI 入口：`src/heagent/config/__init__.py`、`src/heagent/cli/console.py`、`pyproject.toml`。
3. 当前工作流：`/goal` 见 `.heagent/skills/he-goal/workflow.md`（v6 口径）；`/loop` 见 `.heagent/skills/loop/workflow.md`（v7 口径，规划真源是 `_bmad-output/initiative-heagent/tickets/` 票树）。
4. 设计和历史说明：本目录与 `_bmad-output/`，不得覆盖前三项。

新增或变更功能时，先更新对应的当前事实文档；历史规划只追加证据，不回写成“当前实现”。

