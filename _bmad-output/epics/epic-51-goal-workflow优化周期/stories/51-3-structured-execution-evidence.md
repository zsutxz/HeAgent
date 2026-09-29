---
id: 51-3
title: 结构化执行证据模型
status: ready-for-dev
parent_epic: E51
priority: P0
depends_on: [51-2]
blocks: [51-4, 51-8]
created: '2026-09-29'
---

# Story 51-3：结构化执行证据模型

## 用户故事

作为交付审核者，我希望 Story 报告能引用真实命令和 Git 变更证据，以便「测试通过」不是模型自述。

## 声明面（主要交付物）

在**步骤** frontmatter 的 `validation:` 里扩展证据子句（与既有 `section:` 同处一个字符串、同一分隔符，
老包不写新子句即零行为变化）：

| 子句 | 含义 | 载体 |
|---|---|---|
| `section: <标题>` | 输出必须含该标题（**既有，不变**） | 步骤 frontmatter `validation:` |
| `command: <命令>` | 必须存在匹配的命令证据（cwd 为项目根、退出码 0） | 同上 |
| `artifact: <相对路径>` | 必须存在该产物文件 | 同上 |
| `git: <相对路径>` | 该路径必须有 Git 变更证据 | 同上 |
| `gate: <名字>` | 命名质量门（51-4 消费） | 同上 |

- 子句语法与解析归 `workflow_loader`（声明 → 模型），**不新增平行的顶层配置键**。
- 未声明任何证据子句的步骤 = 不要求证据（老包语义不变）。
- 顺带接住 51-1 递延项：**工作区危险状态预检**需要只读 Git 端口，落在本 Story（它是 Git 证据的同一端口）。

## 引擎面（最小通用能力）

- 证据记录的版本化 Pydantic 模型（`EvidenceRecord` / `CommandEvidence` / `GitEvidence` /
  `QualityGateEvidence`）与持久化位置；跨模块只传模型，不传原始 dict（AD-4）。
- 从**既有受治理执行结果**生成证据：不新增绕过 `ToolExecutor` 的命令入口（AD-6）。
- 只读 Git 端口：产出 base / head / 变更集与工作区冲突状态；**从不 commit**（AD-11）。
- **为什么声明层表达不了**：「执行结果 → 证据」是运行期数据通道，Markdown 只能声明**要什么**，
  无法承载记录、digest 与脱敏；模型与端口因此必须存在于引擎，但词汇表保持通用、与 Epic 无关。

## 验收标准

- 证据以版本化 Pydantic 模型记录并可定位；相关模型名与字段是引擎面交付物，不在声明里出现。
- 成功、失败、超时、取消、策略阻断均形成明确证据。
- 命令证据含 cwd、退出码、耗时、命令摘要、输出 digest / 有界脱敏摘要和失败分类。
- Git 证据含 base / head、tracked diff、未跟踪文件；**不执行 commit**。
- 证据与 `goal_id` / `story_id` / `workflow_id` / `revision` 绑定，不能跨 Story 冒用。
- 明文凭证不进入证据；输出有大小上限。
- Markdown 报告只能引用证据 id，不能构造等价原始 dict 伪装。
- 步骤未声明证据子句时不要求证据（老包零行为变化）。

## 任务

- [ ] 在步骤 `validation:` 上补证据子句的解析与模型（未知子句 fail-loud，不做静默忽略）。
- [ ] 证据模型 + 持久化位置：在 `goal/evidence.py` 定义版本化模型（AD-14 证明：见「引擎面」末条）。
- [ ] 从现有受治理执行结果生成证据，不新增绕过 `ToolExecutor` 的命令入口。
- [ ] 只读 Git 端口（含工作区冲突查询），供证据与 51-1 递延的预检项共用。
- [ ] 增加证据与报告互相定位、跨 Story 拒绝、脱敏和上限测试。
- [ ] 变异验证退出码、cwd、Story 绑定与脱敏守卫。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_goal_evidence.py tests/test_engine_p0.py tests/test_safe_logging.py -q
pytest tests/test_workflow_resources.py tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
