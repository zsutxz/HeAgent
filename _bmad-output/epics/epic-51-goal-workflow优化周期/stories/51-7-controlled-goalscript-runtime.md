---
id: 51-7
title: 受控 GoalScript 与 ScriptRuntime
status: done
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

- [x] 在声明模型与加载器补 `executor_mode: script` 与包内脚本资源引用（缺省 = `subagent`）。
- [x] 新增 `script_api.py`、`script_loader.py`、`script_runtime.py`（AD-14 证明：见「引擎面」末条）。
- [x] 定义 Pydantic 操作请求 / 响应模型。
- [x] 实现声明式步骤适配与幂等跳过（A1 `WorkflowRunner.run_declared_step` + A2 `advance` 消费持久化计划）。
- [x] 增加越权 API 缺失、超限、恢复、漂移和治理链测试（`tests/test_goal_script_declarations.py`、`tests/test_goal_script_runtime.py`、`tests/test_goal_script_step.py`）。
- [x] 文档显著声明宿主解释器模式仅限可信包且非安全边界（`docs/frame.md` §4.13.1）。
- [x] 负向验证：脚本能拿到裸 shell / 网络 / 内部状态、超限不受控、漂移不阻断时新测试精确变红。

## 交付边界（实况）

已交付（可测）：

- `executor_mode` / `script_resource` 声明词汇，缺省 `subagent` 零行为变化。
- 脚本资源经 `SkillPackage.read_script()` 读取 → 复用 manifest.json / manifest.lock 内容完整性凭据。
- 未声明 `revision` 的包把脚本内容纳入 `workflow_revision` 指纹（改脚本 = 流程漂移）。
- 加载期 AST 形态校验（`SCRIPT_ENTRYPOINT = build_workflow`；拒 import / while / 辅助函数 /
  私有属性 / 进程与 eval 家族）。
- 受控 facade 七个操作 + Pydantic 请求 / 响应模型。
- `ScriptRuntime` 请求数上限、深度上限、协作式超时。
- **两阶段提交（A 语义）**：脚本执行期只**声明**，宿主在脚本返回后按序**提交**。
  - 阶段一只读同步作答；其余五个操作只校验不落态；不可兑现的声明（未注册门 / 未声明步骤名 /
    自指）**当场** fail-loud。
  - 阶段二：`checkpoint` / `decision` 落本步证据（`WorkflowStepResult.evidence` →
    `runner.state.acceptance_evidence`，由 Runner 持久化）；`validate` 复用 51-4 求值器跑该命名门，
    未过 → 步骤 `BLOCKED`；`step` / `parallel` 收集为后续步骤计划。
- **A1：`WorkflowRunner.run_declared_step(name)`** —— 跑指名的**已声明**步骤（状态机仍归 Runner）：
  已完成 → 幂等跳过（`WorkflowRunResult.skipped`，不重跑、不写新 checkpoint）；只允许向前选择；
  挂起 / 失败 / 已完成时不改状态。
- **A2：`advance` 消费计划** —— 计划存 `WorkflowRunnerState.requested_steps`（FIFO）并**随
  checkpoint 持久化**（`WorkflowCheckpoint.requested_steps`，AD-2 修订版允许的可选追加字段）：
  重启后按同一选择恢复，**不退回声明顺序**（这才满足「确定恢复」）。累计计划超过声明步骤数 →
  Runner 落 `BLOCKED`（有界失败，不静默截断）。

**已知边界（不是缺口，是设计边界）**：

- 脚本可以**声明**一组后续步骤（含用有界 Python 循环声明），但不能**重跑**已完成的步骤——那被
  当作幂等跳过。因此「按状态反复重试某一个声明步骤」不在此设计内（已被跳过的声明步骤保持未执行，
  `completed_steps` 出现缺口，由 `/goal status` 照实投影）。

## 验证命令（亲跑，2026-09-30）

```bash
pytest tests/test_goal_script_declarations.py tests/test_goal_script_runtime.py \
       tests/test_goal_script_step.py tests/test_goal_script_recovery.py -q           # 30 passed
pytest -q                                                                             # 3588 passed, 14 skipped, 18 deselected
ruff check src tests && ruff format --check src tests                                 # 通过（311 files already formatted）
mypy src && mypy src --platform linux                                                 # 164 files, no issues
python .heagent/tmp/neg51_7.py                                                        # 21/21 变异体精确变红
```

> 规划里的 `tests/test_goal_script_api.py` / `test_goal_script_security.py` 未创建；本轮判据收敛在
> `test_goal_script_declarations.py`（声明 / 漂移 / 门禁声明）、`test_goal_script_runtime.py`（facade /
> 限额 / 越权 / 有界失败）、`test_goal_script_step.py`（CLI 接线：真执行、产物落盘、操作提交、完成门）
> 与 `test_goal_script_recovery.py`（计划持久化 + 重启后按同一选择恢复）四个文件，按 story 约定
> 「引用不存在的文件按实测更正」。

## 验证命令（规划原文，已被上节实测取代——保留供对照）

```bash
# 规划时设想的文件名（test_goal_script_api/security 未创建，见上节说明）
pytest tests/test_goal_script_api.py tests/test_goal_script_runtime.py tests/test_goal_script_security.py -q
pytest tests/test_skill_packages.py tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
