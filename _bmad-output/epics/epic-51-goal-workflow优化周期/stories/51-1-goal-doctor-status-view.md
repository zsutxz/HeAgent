---
id: 51-1
title: Goal 预检与统一状态视图
status: done
parent_epic: E51
priority: P0
depends_on: []
blocks: [51-2, 51-3, 51-5]
created: '2026-09-29'
---

# Story 51-1：Goal 预检与统一状态视图

## 用户故事

作为 `/goal` 使用者，我希望在执行前知道 workflow、角色、模板和状态目录是否可用，并在执行中看到统一状态，
以便失败发生在可定位的预检阶段。

## 声明面（主要交付物）

- `workflow.md` frontmatter 新增 **`doctor_checks`**：有序列出本 workflow 要跑的预检项，
  取值来自引擎已注册的检查词汇 `package` / `required_resources` / `roles` / `checkpoint_dir` / `templates`。
  **未声明 = 引擎内置默认全集**（老包不声明即零行为变化）。
- `workflow.md` frontmatter 新增 **`status_fields`**：有序列出 `/goal status` 展示哪些字段，
  取值来自引擎已注册的字段词汇 `step` / `epic` / `story` / `reason` / `failures` / `decisions` / `next`。
  **未声明 = 引擎内置默认集**；进度首行（`declarative progress: n/m status=… step=…`）是固定基线，不参与声明。
- `.heagent/skills/he-goal/workflow.md` 显式写出上述两项 —— 这是本 Story 的「只改声明、`src/` 不动」演示。

## 引擎面（最小通用能力）

- **声明校验**：`doctor_checks` / `status_fields` 出现未知取值 → 加载期 `SkillWorkflowError`（fail-loud，
  不静默忽略、不静默降级）。
- **通用预检执行器**：按声明顺序调用「检查函数注册表」，每项产出结构化 `GoalDoctorReport`
  （`DoctorFinding` 分级 `pass` / `warn` / `fail`）。
- **通用字段渲染器**：按声明顺序渲染固定字段词汇；同一事实只有一个渲染实现。
- **状态视图只投影持久态**：当前 Epic 由 runner 在 story 循环处记录（`WorkflowRunnerState.active_epic`）
  并随 checkpoint 持久化（`WorkflowCheckpoint.active_epic`，**追加的可选字段**，旧 checkpoint 缺它就为空）；
  视图不读文档、不推断层级、不猜。
- **checkpoint 目录只有一个解析点**：`goal/application.checkpoint_store()`；预检经
  `WorkflowCheckpointStore.base_dir` 取同一目录，不另算一份。
- **为什么声明层表达不了**：新增一种「检查种类」或「字段种类」属于**新词汇**，必须有通用实现；
  声明只决定「跑哪些、按什么顺序」，不决定「怎么跑」。新增词汇必须（①对所有 workflow 通用、
  ②与具体 Epic 无关、③老包不声明时行为不变）——与 AD-14 一致。**禁止**在 `src/` 出现
  「he-goal 才跑的检查」「step-07 才展示的字段」这类内容知识。

## 验收标准

- 有效 workflow、必需资源、角色包和状态目录可用时返回结构化 PASS。
- 缺失角色、模板、资源 hash 漂移或不可写 checkpoint 目录时返回结构化问题列表。
- doctor 只读：不推进状态、不写 checkpoint、不改 Goal 文档；可写性探针不得留下产物（含不创建目录）。
- **预检项与状态字段由 workflow 声明决定**；声明未知项时加载期显性失败；未声明的包沿用默认集。
- `GoalStatusView` 展示当前 Step / Epic / Story、状态、阻塞原因、未决决策、最近失败和推荐命令。
- CLI、GUI、cron 消费同一个 Pydantic 状态模型。
- `/goal doctor` 的用户输出必须走 `_echo` 漏斗。
- **状态视图是纯持久态投影**：`/goal status` 不打开任何文档；当前 Epic 来自 runner 记录并持久化的字段，
  恢复后仍可见（旧 checkpoint 缺该字段时显示为空，不回读文档补齐）。
- **预检目录与写入目录同源**：doctor 探的目录就是 `WorkflowCheckpointStore` 实际写入的目录。

## 任务

- [x] 在声明模型与加载器补 `doctor_checks` / `status_fields` 词汇（未知取值 fail-loud、缺省默认集）。
- [x] `goal/doctor.py` 改为按声明顺序执行通用检查注册表；保留结构化报告与稳定的一行渲染。
- [x] `goal/status_view.py` 改为按 `status_fields` 渲染固定字段词汇；保持纯投影、零 IO。
- [x] `.heagent/skills/he-goal/workflow.md` 显式声明两项（声明面演示）。
- [x] 补 CLI 命令、GUI sink 与 cron 路径的一致性测试。
- [x] 当前 Epic 改由 runner 记录并持久化（`WorkflowRunnerState.active_epic` → `WorkflowCheckpoint.active_epic`），
      删除读文档的 `active_story_epic`；`/goal status` 不再打开任何文档。
- [x] checkpoint 目录收敛为单一解析点（`checkpoint_store` + `WorkflowCheckpointStore.base_dir`），
      删除自由函数 `resolve_checkpoint_dir`。
- [x] 负向验证：22 条变异体（6 条声明机制 + 16 条检查 / 投影 / 持久化 / 入口）全部精确变红。

## 实测证据（2026-09-29，本机亲跑）

```text
pytest tests/test_goal_doctor.py tests/test_goal_status_view.py tests/test_workflow_declarations.py \
  tests/test_workflow_resources.py tests/test_goal_declarative_workflow.py tests/test_goal_message_sink.py \
  tests/test_architecture_contracts.py -q
→ 143 passed
pytest -q（全量）                                → 3268 passed, 14 skipped, 18 deselected, 8 warnings in 147.62s
ruff check src tests                             → All checks passed!
ruff format --check src tests                    → 297 files already formatted
mypy src / mypy src --platform linux             → 157 files，均 no issues
python .heagent/tmp/neg51_1.py                   → 16/16 变异体精确变红
python .heagent/tmp/neg51_1b.py（声明机制）       → 6/6 变异体精确变红
```

**「只改声明、`src/` 不动」实证**（`python .heagent/tmp/decl_demo.py`，本 Story 的核心验收）：

```text
声明的 doctor_checks 收窄为 package、status_fields 收窄为 step 后：
  doctor 只跑 package 检查（role / 模板 / 可读性检查不再出现）
  状态输出只剩进度行 + current step 行
恢复声明后回到完整输出（step / reason / next）
src 树摘要 before=7b32c3a9f6cba894 after=7b32c3a9f6cba894   ← 全程零 src 改动
```

**真机冒烟**（非合成 fixture）：

```text
python .heagent/tmp/doctor_smoke.py → ok=True；7 个 role 包全 pass；两个 required 模板 present；检查顺序 = 声明顺序
python .heagent/tmp/status_smoke.py → [goal] declarative progress: 2/8 status=waiting_user step=2 等 4 行
```

**状态视图不再打开文档**：`/goal status` 的 Epic 来自 runner 记录并随 checkpoint 持久化的
`active_epic`；判据 `test_story_loop_records_the_epic_and_a_checkpoint_restores_it`（含恢复）+ 
`test_cli_status_shows_the_epic_without_reading_any_document`（断言 goal 目录里根本没有 story 文档）。

**两处实现期自查抓到的假绿**（同一类错误：把「什么都没发生」读成「通过」）：

1. `status_smoke.py` 最初未传 `fields=`，于是「改声明后输出不变」——脚本走的是默认字段集而不是声明路径。
   补上 `fields=workflow.status_fields` 才复现出真正的声明驱动行为。
2. 删掉 `active_story_epic` / `resolve_checkpoint_dir` 后，两个冒烟脚本仍 import 旧符号 ⇒ 脚本崩掉、
   **stdout 为空**，而 `decl_demo.py` 只打印 stdout ⇒ 演示「成功」而证据是空的。已给演示脚本加
   「非零 rc 或空输出即显式报错」。
   教训：判据必须锚在**被测代码的动作**上，且「空结果」永远不能当通过。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_goal_doctor.py tests/test_goal_status_view.py tests/test_workflow_resources.py -q
pytest tests/test_goal_declarative_workflow.py tests/test_goal_message_sink.py tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
