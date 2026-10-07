---
id: 51-6
title: 多 workflow 模板与创建时冻结
status: done
parent_epic: E51
priority: P1
depends_on: [51-4, 51-5]
blocks: [51-7, 51-8]
created: '2026-09-29'
---

# Story 51-6：多 workflow 模板与创建时冻结

## 用户故事

作为不同类型任务的使用者，我希望产品、工程、迁移和安全任务可选择合适流程，同时所有流程仍由同一 Runner 执行。

## 声明面（主要交付物）

**本 Story 的主要交付物就是声明包本身** —— 这是全 Epic 最纯粹的一条：

- 新增模板 workflow 包（`product` / `engineering` / `migration` / `security` 或等价的最小可验证样例），
  每个包 = `<包>/SKILL.md` + `<包>/workflow.md`（frontmatter + `## Step NN:` 内步骤或 `step-NN-*.md`）
  + `<包>/templates/{prompt-template,gate-template}.md` + 可选 `required_resources` 声明。
- `workflow.md` frontmatter 新增 **`revision`**（或由包内容推导的 hash）：创建 Goal 时连同 id 一起冻结。
- 包只能声明步骤 / Gate / 角色 / 资源；**不得**自带第二状态机、不得直接执行工具（AD-1 / AD-6）。
- **验收演示（第 0 节口径）**：新增一个模板包时 `src/` **零改动**，只新增声明目录 + 一条
  「新包可被 doctor 预检、可被 Runner 执行」的测试。

## 引擎面（最小通用能力）

- 创建时把 workflow id / revision（hash）写入 Goal 元数据；恢复时比对，漂移 fail-loud。
- 老 Goal 缺新元数据时按兼容规则绑定 `he-goal`，**不在只读路径改写原件**。
- 复用 `SkillPackage` 的 manifest / lock 完整性通道（既有能力，不新造校验）。
- **为什么声明层表达不了**：冻结与比对发生在**创建 / 恢复的运行期**，声明只能提供被冻结的值；
  「何时写、写在哪、漂移怎么办」是引擎不变量（AD-8）。本 Story 的引擎面**应当很小**：
  若既有包装载与冻结能力够用，则引擎面为零。

## 验收标准

- 创建 Goal 时可选择受支持的 workflow 包。
- workflow id、revision / hash 在创建时写入元数据并冻结。
- 执行中资源漂移、缺失或 hash 不匹配时显式阻断，不静默切换。
- 老 Goal 没有新元数据时按兼容规则绑定 `he-goal`。
- workflow 包只能声明步骤 / Gate / 角色 / 资源，不得自带第二状态机或直接执行工具。
- doctor 能预检所选 workflow 的完整依赖（复用 51-1 的声明驱动预检）。
- **新增一个模板包不需要改 `src/`**（以实测的「只改声明」增量作为证据）。

## 任务

- [x] 在声明模型与加载器补 `revision`（缺省由包内容推导，老包不声明不报错）。
- [x] 扩展创建命令与 Goal 元数据（冻结 id / revision）；补漂移阻断与旧 Goal 兼容。
- [x] 新增模板包（声明面主体）或最小可验证样例包，并复用 `SkillPackage` 完整性通道。
- [x] 补旧 Goal 兼容、漂移阻断和创建时冻结测试。
- [x] 记录「新增包 = `src/` 零改动」的实测证据。
- [x] 更新使用文档，说明 workflow 不可在运行中静默切换。

## 实测证据（2026-09-30）

**「老 Goal 兼容规则绑定 `he-goal`」的口径说明**：`src/`（engine/ 与 goal/）不出现任何包名字面量
（架构契约 `test_engine_and_goal_layers_hold_no_workflow_package_name_branches` 钉死）。兼容默认值由
**入口层**从 `Settings.goal_workflow_skill`（默认值就是 `"he-goal"`，config/__init__.py:141）注入
`resolve_bound_workflow(goal_dir, default_workflow_id)`——「绑定 he-goal」由这条配置默认值成立，
换配置即换兼容绑定目标，引擎面零包名知识。

**「新增包 = src/ 零改动」实测证据**：本 Story 新增 4 个包（`he-product` / `he-engineering` /
`he-migration` / `he-security`，各含 SKILL.md + workflow.md + templates/{prompt,gate}-template.md）
全程只新增声明目录，`src/` 改动仅为通用词汇（`revision` 字段 / `workflow_revision` 派生 / 绑定
读取与漂移比对），无任何包名分支。测试另在 tmp skills 根合成第 5 个包，走
catalog 发现 → `--workflow` 预检 → 冻结创建 → 按绑定恢复全链路
（`tests/test_goal_workflow_selection.py::test_a_fifth_synthetic_package_needs_no_src_change`）。

**51-4 递延接线**：`_goal_verify_report` 读取绑定 revision 传入 `verify_step(revision=...)`，
审查摘要已记录（`_bmad-output/implementation-artifacts/deferred-work.md`）；当前活动台账以 `deferred-work-archive.md` 为准。

**用例统计（2026-09-30，实测）**：实现轮新增/改动 26 例（selection 20 + resources +5 +
架构 +1）；三层审查合并修复轮再增 24 例（selection +18——含 13 例 dispatch 逐臂参数化、
`--workflow=` 等号形态、重复旗标、反向半键、创建臂选择、外挂步骤漂移端到端；resources +5——
frontmatter 指纹、sorted() 配方钉住、外挂步骤指纹×3；doctor +1——活动 goal 忽略 `--workflow`
提示），合计 50 例。

## 验证命令（2026-09-30 亲跑实测）

```bash
$ pytest tests/test_goal_workflow_selection.py tests/test_workflow_resources.py tests/test_skill_packages.py \
    tests/test_goal_declarative_workflow.py tests/test_goal_quality_gates.py tests/test_goal_doctor.py \
    tests/test_architecture_contracts.py -q
247 passed, 2 skipped in 6.38s

$ pytest tests/test_skill_package_integrity.py tests/test_workflow_runner.py tests/test_workflow_declarations.py -q
64 passed in 0.61s

$ pytest tests/ -q --ignore=tests/js   # 全量回归
3529 passed, 14 skipped, 18 deselected in 212.07s

$ ruff check src tests
All checks passed!

$ ruff format --check src tests
305 files already formatted

$ mypy src && mypy src --platform linux
Success: no issues found in 161 source files（两次同结果）
```
