---
id: 51-6
title: 多 workflow 模板与创建时冻结
status: ready-for-dev
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

- [ ] 在声明模型与加载器补 `revision`（缺省由包内容推导，老包不声明不报错）。
- [ ] 扩展创建命令与 Goal 元数据（冻结 id / revision）；补漂移阻断与旧 Goal 兼容。
- [ ] 新增模板包（声明面主体）或最小可验证样例包，并复用 `SkillPackage` 完整性通道。
- [ ] 补旧 Goal 兼容、漂移阻断和创建时冻结测试。
- [ ] 记录「新增包 = `src/` 零改动」的实测证据。
- [ ] 更新使用文档，说明 workflow 不可在运行中静默切换。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_goal_workflow_selection.py tests/test_workflow_resources.py tests/test_skill_packages.py -q
pytest tests/test_goal_declarative_workflow.py tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
