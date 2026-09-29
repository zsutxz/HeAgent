---
id: 51-4
title: 真实质量 Gate 与 goal verify
status: done
parent_epic: E51
priority: P0
depends_on: [51-3]
blocks: [51-6, 51-8]
created: '2026-09-29'
baseline_commit: 8b4c761cd3c35ffeebbedd6c538b4ca6ed8838be
---

# Story 51-4：真实质量 Gate 与 `/goal verify`

## 用户故事

作为 Goal 负责人，我希望完成判定依赖真实 Evidence，以便未运行测试或运行失败的 Story 不能推进。

## 声明面（主要交付物）

- **门禁规则全部来自 51-3 的 `validation:` 子句**，本 Story 不引入新的顶层配置键：
  - `command:` → 必须有匹配的计划证据（退出码 0、cwd 正确、未过期、属于当前 Story / 步骤）；
  - `artifact:` → 必须有该产物；
  - `git:` → 必须有该路径的 Git 变更证据；
  - `section:` → 输出必须含该标题（**既有文本门禁，保留**）；
  - `gate: <名字>` → 命名质量门（宿主内置门，工作流只能**引用**不能削弱）。
- `gate:` 的可用名字由引擎注册表提供（通用词汇）；workflow 只能引用已注册名字，
  写出未注册名字 = 加载期 fail-loud。
- **老包不声明结构化子句时保持原文本门禁行为**（零行为变化）。

## 引擎面（最小通用能力）

- 通用求值器：把声明子句逐条匹配到当前步骤 / Story 的证据与产物上，产出结构化的通过 / 失败与原因。
- `/goal verify`：只检查或**受控重跑**声明里列出的验证，绝不重新执行实现步骤、绝不伪造完成状态。
- 失败 / 超时 / 取消 / 策略阻断都算「未通过」，不区分「没跑」与「跑了没过」的写法。
- **为什么声明层表达不了**：求值器需要读取证据记录、访问文件系统与只读 Git；声明只能表达**规则**。
  求值器本身通用（不认 Epic、不认步骤名）；`gate:` 注册表是通用词汇表，新增门 = 新词汇（AD-14）。

## 验收标准

- workflow 可声明必需产物、命令、Git 路径和质量门（经 `validation:` 子句）。
- 声称命令通过但没有匹配的命令证据时 Gate 失败。
- 非零退出码、错误 cwd、过期证据或证据不属于当前 Story 时进入 `BLOCKED`。
- `/goal verify` 只重跑 / 检查声明的验证，不重新执行实现步骤，不伪造完成状态。
- 旧 workflow 未声明结构化 Gate 时保持原文本 Gate 行为。
- workflow 不能降低宿主强制质量门或绕过工具治理链；引用未注册 `gate:` 名字时加载期显性失败。

## 任务

- [x] 扩展 `WorkflowStepResource` 的 `validation` 模型（向后兼容：老字符串仍可解析）——51-3 已落
  `StepValidationClauses`；本 Story 接管遗留标记：`gate:` 名字经宿主注册表在加载期校验（未注册 fail-loud）。
- [x] 在 `goal/quality_gates.py` 实现通用求值器（AD-14 证明：见「引擎面」末条）。
- [x] 实现 `/goal verify` 与结构化报告（输出继续走 `_echo` 漏斗）。
- [x] 增加缺证据、失败证据、错误归属、旧语义兼容测试。
- [x] 负向验证「只写 Markdown 就通过」「引用未注册 gate」「失败证据当通过」的变异体必须红。

## 实测证据（2026-09-29，本机亲跑；含三层审查 20 项修复后的复跑）

```text
pytest tests/test_goal_quality_gates.py tests/test_goal_evidence.py tests/test_workflow_resources.py -q   → 182 passed
pytest tests/test_workflow_runner.py tests/test_architecture_contracts.py -q                              → 51 passed
pytest -q（全量）                                                                                          → 3434 passed, 14 skipped, 18 deselected
ruff check src tests                                                                                       → All checks passed!
ruff format --check src tests                                                                              → 302 files already formatted
mypy src / mypy src --platform linux                                                                       → 160 files，均 no issues
python .heagent/tmp/neg51_4.py                                                                             → 3/3 变异体精确变红（字节级还原后恢复绿）
```

负向变异（`.heagent/tmp/neg51_4.py`，每条只改一处守卫、字节级还原）：
M1「只写 Markdown 就通过」（缺匹配命令证据不再失败）→ 红；M2「引用未注册 gate」（加载器注册表校验失效）→ 红；
M3「失败证据当通过」（非成功 outcome 不再判缺陷）→ 红。

## 交付说明（实现口径，如实声明；含三层审查修复批次）

- **求值器**（`goal/quality_gates.py`）：`command:`（最新匹配证据必须成功 + cwd 等于工作区根 + 未过期，
  未来时间戳视同过期；声明命令先 `redact_secrets` 归一再比对，与证据侧同规；截断证据前缀命中多条声明
  命令时显性判「无法定位匹配」，不任配；缺证据不能用报告文本补齐）/ `artifact:`（必须命中**文件**，
  目录不算）/ `git:`（实时只读查询优先，回落最新记录 Git 证据；路径比对归一 `./` 前缀 / 大小写 /
  引号 / 目录前缀）/ `gate:`（宿主注册表，**名字 → 语义 + 求值函数分派表**、无名字级兜底：
  `tests-pass` = 每条声明命令的最新证据都通过——须与 command: 同用，加载期拒绝单独声明；
  `git-changes` = 存在非空变更集）/ `section:`（复验既有文本门禁判定，单一真源
  `output_contains_section`）。失败 / 超时 / 取消 / 策略阻断与「缺证据」同归「未通过」，理由逐条进
  结构化 `VerificationReport`。证据范围按 goal + 步骤 + **确切** story 绑定（步骤级记录对 Story 求值
  不可见）；workflow/revision 绑定漂移显性排除并进 report.errors。
- **完成门**：步骤产物落盘后按声明子句求值（含声明验证命令的**受控重跑**——经 `PolicyEngine →
  ToolExecutor → SafetyGuard → shell handler` 治理链并落证据，AD-6 不绕行；显式 timeout 600s，不用
  120s 默认钉死长套件）；声明命令在**工作区根**执行（`cd` 前缀包装，工作区根唯一解析点
  `_goal_verify_workspace`——执行定位、证据 cwd 记录与求值期望三方同源）；未通过经 `WorkflowRunner`
  的 `GATE_FAILED` 事件进 `BLOCKED`，本层不直接改状态；求值自身的 `EvidenceError`/`OSError` 同归
  BLOCKED 理由（不崩 run、不放行）。未声明子句的步骤零行为变化。
- **`/goal verify`**：只检查（读证据 / 产物 / 只读 Git）或 `verify run` 受控重跑声明验证；不重跑实现
  步骤、不改 Runner 状态、不伪造完成状态；对 BLOCKED / FAILED 状态可用；done / 无活动步显性早退；
  求值路径的 `OSError` 收口为本命令失败，不落「锁竞争」误诊文案。`engine` 缺席时受控重跑显性报
  「无治理端口」，不静默放行。治理＝PolicyEngine + ToolExecutor + SafetyGuard + shell handler 四层，
  **不经** agent/tool_execution 的 hooks（如实声明）；shell 未注册记 `POLICY_BLOCKED`。
- **证据时效缺省 24h**（`DEFAULT_EVIDENCE_MAX_AGE`，模块常量，不新增顶层配置键）；workflow 冻结
  （`workflow_id` / `revision` 绑定漂移）显性排除——完整冻结语义仍归 51-6。
- **51-3 测试的一处更正**：`test_quoted_separator_stays_one_clause_value` 的 `gate: x` 换成注册名
  `tests-pass`——「未注册名字加载期 fail-loud」是本 Story 的预期行为变化，该用例的解析意图不变。
- **递延（本轮不动）**：revision 接线（51-6）；emit/ledger 观测接线（51-8）；声明验证命令随完成门与
  verify run 各执行一次的重复执行（51-8）。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_goal_quality_gates.py tests/test_goal_evidence.py tests/test_workflow_resources.py -q
pytest tests/test_workflow_runner.py tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```

## Suggested Review Order

**入口：工作区解析唯一真源**

- 受治理执行定位、证据 cwd 记录、求值期望三方共用的唯一解析点
  [`cli/goal.py:499`](../../../../src/heagent/cli/goal.py#L499)

**引擎面：通用求值器**

- verify_step 主入口：五类子句逐条匹配证据/产物/只读 Git，产出结构化报告
  [`quality_gates.py:290`](../../../../src/heagent/goal/quality_gates.py#L290)

- gate: 注册表：QualityGateSpec 显式绑定求值函数，无名字级兜底
  [`quality_gates.py:254`](../../../../src/heagent/goal/quality_gates.py#L254)

- tests-pass = 最新证据投影（latest-match），失败→修复→放行可达
  [`quality_gates.py:163`](../../../../src/heagent/goal/quality_gates.py#L163)

- 受控重跑：经入口注入的治理端口执行并 append-only 落证据，绝不静默放行
  [`quality_gates.py:376`](../../../../src/heagent/goal/quality_gates.py#L376)

- 结构化报告模型（逐条 passed/reason/evidence_ids + errors）
  [`quality_gates.py:83`](../../../../src/heagent/goal/quality_gates.py#L83)

**CLI 接线：完成门与 /goal verify**

- 完成门：产物落盘后求值，未通过经 GATE_FAILED 进 BLOCKED（不直写状态）
  [`cli/goal.py:546`](../../../../src/heagent/cli/goal.py#L546)

- /goal verify：只检查或受控重跑声明验证，不改 Runner 状态
  [`cli/goal.py:515`](../../../../src/heagent/cli/goal.py#L515)

- 治理链端口：PolicyEngine → ToolExecutor → SafetyGuard → shell（显式 600s timeout）
  [`cli/goal.py:661`](../../../../src/heagent/cli/goal.py#L661)

**声明面：gate 注册表加载期校验**

- 未注册 gate: 名与单独声明死路组合在加载期 fail-loud
  [`workflow_loader.py:28`](../../../../src/heagent/goal/workflow_loader.py#L28)

**外围：测试与文档**

- 59 条判据（真实治理链端到端、失败→修复→放行、cwd 分叉、变异锚点）
  [`test_goal_quality_gates.py:1`](../../../../tests/test_goal_quality_gates.py#L1)
