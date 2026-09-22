---
title: 'Phase 0 基线冻结与文档治理'
type: 'refactor'
status: 'done'
created: '2026-09-21'
baseline_commit: '（spec 机制自 Phase 1 起建立，本阶段无独立 spec）'
---

## Phase 0 执行记录

### 文档变更

- [x] 更新 [文档索引](README.md)：覆盖架构、开发、测试、部署、设计、迁移、历史与资讯，并按角色明确维护责任。
- [x] 新建 [架构沿革](architecture-history.md)：独立归档参考来源与迁移索引；`frame.md` 保留当前行为和兼容约束，并修复第八节下的错误编号。
- [x] `iteration.md` 标记历史数值的适用范围；新闻归档补充状态、适用日期与维护角色。LangChain 专题在执行期间被外部删除，本次保留该删除并移除索引中的失效链接。
- [x] 纠正本方案行数口径，记录现有契约和验证结果。源码、配置和质量门禁脚本未改动。

### 序列化契约与迁移边界

| 对象 | 当前事实 | 后续变更要求 |
| --- | --- | --- |
| `types.py` 公共类型 | 没有统一 schema 版本字段 | 不向所有消息强加字段；按实际外部或持久化契约决定版本边界 |
| `RunSnapshot` / `RunContext` | 没有统一 schema 版本字段 | 加版本前覆盖旧快照读取、缺省版本和未知版本处理 |
| `RunEvent` | `events/protocol.py` 已定义 `SCHEMA_VERSION = "1"` 和 `schema_version` | 修改字段须同步消费者及 `test_events_jsonl.py`；原方案“新增事件版本”已纠正 |
| `WorkflowCheckpoint` / workflow 状态 | 没有统一 schema 版本字段 | 保留现有恢复及旧字段兼容语义；未来迁移必须验证损坏状态、重复恢复和未知版本 |

本阶段没有新增版本字段或转换已有状态文件。后续状态模型改造归 Phase 2/3，事件变更归 Phase 5；以本表替代原 Phase 0 的代码修改项。

### 验证基线

基线提交：`4cecfea`；日期：2026-09-21。文档变更在该提交基础上，测试数只作快照，不作为禁止增加测试的硬阈值。

| 检查 | 结果 |
| --- | --- |
| `python -m pytest --collect-only -q` | 2,023 / 2,037，14 deselected |
| `python -m pytest tests/test_architecture_contracts.py tests/test_artifact_contracts.py tests/test_goal_workflow_smoke.py -q` | 10 passed；首次执行遇 pytest 临时目录权限错误，获准在沙箱外重跑通过 |
| `ruff check src tests scripts` | 通过 |
| `mypy src` | 113 个源码文件通过 |
| `python scripts/quality_gate.py` | 冒烟与回归通过：2,014 passed、9 skipped、14 deselected、2 warnings；覆盖率 91.00%。lint 通过，format 失败后按 fail-fast 停止；mypy 为独立执行通过 |
| `git diff --check` | 通过 |
| docs 内 Markdown 本地文件链接 | 检查时 60 个目标全部存在；不含 URL 可用性、标题锚点或代码块中的示例路径 |

### 未关闭的验收项

- 完整门禁尚未全绿：`src/heagent/goal/naming.py`、`src/heagent/goal/workflow_loader.py`、`tests/test_goal_cross_process_lock.py`、`tests/test_goal_declarative_workflow.py` 需要 Ruff 格式化。作为现有基线问题记录，本次文档修改不包含这些源码/测试调整。
- 全新环境安装和平台集成测试未执行；本次质量结果来自已有开发环境。
- 文档环境变量表尚未逐项与全部 Settings 默认值机械对照；不能声明配置参考已全面验证。
- import 契约测试验证已有禁止依赖规则，不等于对所有图示边做完整依赖审计；原方案五层划分仍是待评审目标，不能当作当前包布局。
- 架构正文保留与当前兼容行为有关的历史注释；后续随模块拆分再精简，避免丢失恢复和安全约束。
