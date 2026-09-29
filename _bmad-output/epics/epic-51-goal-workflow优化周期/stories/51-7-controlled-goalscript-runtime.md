---
id: 51-7
title: 受控 GoalScript 与 ScriptRuntime
status: ready-for-dev
parent_epic: E51
priority: P2
depends_on: [51-6]
blocks: [51-8]
created: '2026-09-29'
---

# Story 51-7：受控 GoalScript 与 ScriptRuntime

## 用户故事

作为可信 workflow 作者，我希望表达条件、循环和动态输入，同时不能接管状态、checkpoint 或工具治理。

## 产品裁决

- 脚本模式默认关闭。
- 第一阶段只允许可信本地 workflow 包启用。
- GoalScript 不是安全边界；第三方脚本需要后续隔离 worker。

## 声明面（主要交付物）

- 步骤 frontmatter 新增 **`executor_mode: script`**（缺省 = `subagent`，即现状）。
- 脚本是**包内资源**：`<包>/scripts/<name>.py`（或等价受完整性校验的资源路径），由该步骤声明引用。
- 条件 / 循环 / 动态输入**写在脚本资源里**，不写在 Python 引擎里；脚本的产物与状态变化仍回到
  Runner 声明的步骤顺序与 checkpoint。
- 包内脚本资源的完整性由既有的 `SkillPackage` manifest / lock 通道校验（漂移 fail-loud）。

## 引擎面（最小通用能力）

- 受控 facade：只暴露 `step` / `parallel` / `checkpoint` / `input` / `artifact` / `decision` / `validate`
  等**操作请求**；不暴露裸 shell、子进程、网络、Git commit、Runner 内部状态。
- 请求 / 响应一律 Pydantic 模型（AD-4）；每个请求映射回 `WorkflowRunner` 与既有治理链。
- 强制步骤数、深度、超时与取消上限；超限有界失败；取消与恢复回到 Runner 事件。
- **为什么声明层表达不了**：需要**执行**条件 / 循环逻辑的宿主；声明只能描述脚本位置与启用开关。
  宿主解释器不是安全边界（AD-9 / AD-12），这一点必须在文档与 CLI 提示里显式写出，不得含糊。
- 落点：`script_api.py` / `script_loader.py` / `script_runtime.py` 只是上述通用能力的实现位置，
  三者都不是「为 he-goal 写的」——不得出现任何具体 Epic / 步骤名判断。

## 验收标准

- 支持 `executor_mode: script` 与包内受完整性校验的脚本资源。
- `GoalScript` 只暴露受控 step / parallel / checkpoint / input / artifact / decision / validate API。
- 所有状态变化仍经 `WorkflowRunner`；所有 Agent / tool 调用仍经既有治理链。
- 脚本不能直接写 checkpoint、workflow / current，不能裸起子进程、裸联网、自动 commit。
- 条件分支结果基于持久化输入 / 产物，进程重启后可确定恢复。
- 强制步骤数、深度、超时和取消语义；超限有界失败。
- 资源 hash 漂移显性失败。

## 任务

- [ ] 在声明模型与加载器补 `executor_mode: script` 与包内脚本资源引用（缺省 = `subagent`）。
- [ ] 新增 `script_api.py`、`script_loader.py`、`script_runtime.py`（AD-14 证明：见「引擎面」末条）。
- [ ] 定义 Pydantic 操作请求 / 响应模型。
- [ ] 实现声明式步骤适配与幂等跳过。
- [ ] 增加越权 API 缺失、超限、恢复、漂移和治理链测试。
- [ ] 文档显著声明宿主解释器模式仅限可信包且非安全边界。
- [ ] 负向验证：脚本能拿到裸 shell / 网络 / 内部状态、超限不受控、漂移不阻断时新测试精确变红。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_goal_script_api.py tests/test_goal_script_runtime.py tests/test_goal_script_security.py -q
pytest tests/test_skill_packages.py tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
