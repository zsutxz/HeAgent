---
id: 51-3
title: 结构化执行证据模型
status: done
parent_epic: E51
priority: P0
depends_on: [51-2]
blocks: [51-4, 51-8]
created: '2026-09-29'
baseline_commit: 25a5d6d838448a3f358e84c734a69e89d781dfcd
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
- **「老包零行为变化」的准确边界（实现口径，如实声明）**：零变化的条件是步骤声明里
  **没有** ``<Word>:`` 形态的段——形如 `coverage: 85%` 或 `subsection: x` 的段首单词冒号
  会被当作未知子句而在加载期 fail-loud（这是「未知子句不静默忽略」的直接后果）；
  多词前缀（``Given a user: …``）与纯中文散文不受影响。`section:` 值提取与既有
  `required_sections` 同源（同一正则，含段中内嵌形态与引号值），两处解析不漂移。
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

- [x] 在步骤 `validation:` 上补证据子句的解析与模型（未知子句 fail-loud，不做静默忽略）。
- [x] 证据模型 + 持久化位置：在 `goal/evidence.py` 定义版本化模型（AD-14 证明：见「引擎面」末条）。
- [x] 从现有受治理执行结果生成证据，不新增绕过 `ToolExecutor` 的命令入口。
- [x] 只读 Git 端口（含工作区冲突查询），按 Story 口径只落**端口**（工作区危险状态作为 doctor 声明词汇的接线留给预检词汇 Story；`conflict_state()` 已可被 `goal/doctor.py` 直接消费）。
- [x] 增加证据与报告互相定位、跨 Story 拒绝、脱敏和上限测试。
- [x] 变异验证退出码、cwd、Story 绑定与脱敏守卫（共 10 条，全部精确变红）。

## 实测证据（2026-09-29，本机亲跑；含 review patch 26 项修复后的复跑）

```text
pytest tests/test_goal_evidence.py tests/test_engine_p0.py tests/test_safe_logging.py \
  tests/test_workflow_resources.py tests/test_architecture_contracts.py -q   → 252 passed
pytest -q（全量）                          → 3375 passed, 14 skipped, 18 deselected in 149.38s
ruff check src tests                       → All checks passed!
ruff format --check src tests              → 300 files already formatted
mypy src / mypy src --platform linux       → 159 files，均 no issues
python .heagent/tmp/neg51_3.py             → 10/10 变异体精确变红（还原后恢复绿）
```

负向变异（`.heagent/tmp/neg51_3.py`，每条只改一处守卫、还原后恢复）：
M1 非零退出码读成成功 → 红；M2 丢 cwd → 红；M3 去掉跨 Story 绑定校验 → 红；
M4 去掉命令脱敏 → 红；M5 去掉大小上限 → 红；M6 Git 端口只读白名单去掉 → 红；
M7 未知子句静默忽略 → 红；M8 原始 dict 伪装证据 id 被接受 → 红；
M9 schema 版本门去掉 → 红；M10 「成功 + 非零退出码」矛盾证据被接受 → 红。

**声明解析与既有 section 解析的一致性判据**（防两处解析漂移；`section:` 提取复用同一正则）：
`parse_validation_clauses(...).sections == required_sections(...)` 对 9 组串（含段中内嵌
`must include section: X` 与引号值 `section: "A"`）+ 真实 he-goal 包全量步骤成立
（`test_clause_sections_agree_with_the_existing_section_parser` /
`test_real_workflow_package_parses_its_declared_sections`）。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_goal_evidence.py tests/test_engine_p0.py tests/test_safe_logging.py -q
pytest tests/test_workflow_resources.py tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```

## Suggested Review Order

**声明面：证据子句解析（入口）**

- section 提取单一真源：两个解析器共用，`required_sections` 也委托到此
  [`workflow_resource.py:21`](../../../../src/heagent/engine/workflow_resource.py#L21)

- 声明 → 模型主入口：五类子句、未知子句加载期 fail-loud
  [`workflow_loader.py:56`](../../../../src/heagent/goal/workflow_loader.py#L56)

- 引号感知切段：引号内 `,`/`;` 不拆段、不平衡引号显性报错
  [`workflow_loader.py:106`](../../../../src/heagent/goal/workflow_loader.py#L106)

- 证据子句模型；路径守卫经共享判定，直构造也逃不掉
  [`workflow_resource.py:58`](../../../../src/heagent/engine/workflow_resource.py#L58)

- 工作区相对路径判定单一真源（loader 与模型同规）
  [`workflow_resource.py:33`](../../../../src/heagent/engine/workflow_resource.py#L33)

- 既有文本门禁改为委托 section_titles，杜绝双解析漂移
  [`workflow_runner.py:67`](../../../../src/heagent/engine/workflow_runner.py#L67)

**引擎面：证据模型与追加式存储**

- 五态命令结果分类：rc=0 先短路 SUCCEEDED，再判超时文案
  [`evidence.py:176`](../../../../src/heagent/goal/evidence.py#L176)

- 只消费受治理 ToolCall/ToolResult 生成证据（无绕行命令入口）
  [`evidence.py:201`](../../../../src/heagent/goal/evidence.py#L201)

- 追加式存储：schema 版本门 + 独占创建（append-only 不被并发覆盖）
  [`evidence.py:243`](../../../../src/heagent/goal/evidence.py#L243)

- list_records 的 UNFILTERED sentinel：两个 None 不再两种含义
  [`evidence.py:72`](../../../../src/heagent/goal/evidence.py#L72)

**引擎面：只读 Git 端口**

- 固定旗标模板 + rev 模式：调用方传不进任何旗标，只读纵深
  [`git_port.py:42`](../../../../src/heagent/goal/git_port.py#L42)

- 证据查询：base/head/变更集，从不 commit（AD-11 有测试钉住）
  [`git_port.py:117`](../../../../src/heagent/goal/git_port.py#L117)

- 工作区冲突状态（51-1 递延预检的共用端口）
  [`git_port.py:133`](../../../../src/heagent/goal/git_port.py#L133)

**外围：测试与文档**

- 63 条证据/端口/解析判据 + 10 条变异锚点
  [`test_goal_evidence.py:1`](../../../../tests/test_goal_evidence.py#L1)

- 子句解析一致性（外置/内嵌/未知子句 fail-loud）
  [`test_workflow_resources.py:1`](../../../../tests/test_workflow_resources.py#L1)
