---
title: '目标工作流 checkpoint 决策控制'
type: 'feature'
created: '2026-09-05'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'fe2b1da6250a2a8ff54f1f08f33ff07f1c198793'
context: ['E:/AI/HeAgent/src/heagent/cli.py', 'E:/AI/HeAgent/src/heagent/config.py', 'E:/AI/HeAgent/src/heagent/memory/skill_packages.py', 'E:/AI/HeAgent/src/heagent/engine/workflow_runner.py']
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** `/goal` 在每个声明式 checkpoint 后固定进入 `waiting_user`，用户无法为工作流选择自动推进，也没有在交互式 CLI 中直接确认继续的入口。

**Approach:** 增加可验证的 checkpoint 决策模式。工作流 frontmatter 可声明 `checkpoint_mode: auto|prompt`，环境变量 `GOAL_CHECKPOINT_MODE` 提供全局默认覆盖；`prompt` 模式在交互终端询问是否继续，`auto` 模式自动恢复并推进，非交互输入不猜测用户意图而保持暂停。

## Boundaries & Constraints

**Always:** 默认行为保持 `prompt`；只在 checkpoint 已成功完成且无错误时推进；所有状态变化继续通过现有 `WorkflowRunner` checkpoint 持久化；无效模式显式报错；自动模式不能绕过工作流顺序或输出校验。

**Ask First:** 无。

**Never:** 不删除 `waiting_user` 状态；不把自动模式作为安全边界；不在非交互 stdin 下隐式同意；不改变 provider、工具执行和既有 checkpoint 文件格式。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 自动模式 | workflow `checkpoint_mode: auto` 或环境变量为 `auto`，步骤完成 | 自动恢复并执行下一步骤，直到下一个 checkpoint、完成或失败 | 任何执行/校验失败保持显式失败状态 |
| 交互模式同意 | 终端可交互，checkpoint 步骤完成，用户选择继续 | 记录恢复并推进一个下一步骤 | Ctrl+C 保留 checkpoint，提示使用 `/goal resume` |
| 交互模式暂停 | 终端可交互，用户选择停止/默认否 | 保持 `waiting_user`，不调用下一步骤 | 提示 `/goal resume [回复]` |
| 非交互模式 | stdin 非 TTY 且状态为 `waiting_user` | 不自动同意，保持暂停 | 输出明确的恢复命令 |
| 配置错误 | `checkpoint_mode` 不在 `auto,prompt` | 工作流加载失败 | 抛出明确的配置错误，不静默回退 |

</frozen-after-approval>

## Code Map

- `src/heagent/config.py` -- 增加 `goal_checkpoint_mode` 设置和 `GOAL_CHECKPOINT_MODE` 环境变量解析，默认 `prompt`。
- `src/heagent/memory/skill_packages.py` -- 将工作流 frontmatter 的 `checkpoint_mode` 映射到 `WorkflowResource`，保留原始 frontmatter。
- `src/heagent/cli.py` -- 校验模式；在 `/goal new`、`next`、`run` 和 `resume` 的 checkpoint 边界统一处理自动推进或交互确认；非 TTY 保持暂停。
- `.heagent/workflows/workflow.md` -- 声明默认 `checkpoint_mode: prompt`，作为可复制的工作流配置示例。
- `tests/test_config.py` -- 覆盖默认值和环境变量配置。
- `tests/test_goal_declarative_workflow.py` -- 覆盖 auto、prompt 同意/拒绝、非 TTY 和非法配置，确保 checkpoint 不重复执行。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/config.py` -- 添加 checkpoint 模式设置并限制为 `auto` 或 `prompt` -- 提供统一全局配置入口。
- [x] `src/heagent/memory/skill_packages.py` -- 扩展 `WorkflowResource` 并解析 `checkpoint_mode` -- 支持工作流自声明模式。
- [x] `src/heagent/cli.py` -- 实现确定性的模式解析和交互确认，在所有 goal 推进入口复用 -- 避免不同入口行为漂移。
- [x] `.heagent/workflows/workflow.md` -- 写入 `checkpoint_mode: prompt` -- 保持现有默认并展示配置点。
- [x] `.env.example` -- 增加 `GOAL_CHECKPOINT_MODE` 配置说明 -- 让全局模式入口可发现。
- [x] `tests/test_config.py` -- 添加配置解析测试 -- 验证 `.env` 覆盖和默认值。
- [x] `tests/test_goal_declarative_workflow.py` -- 添加两种模式及边界测试 -- 验证状态、调用次数和显式失败。

**Acceptance Criteria:**
- Given 未配置任何模式，when 一个 checkpoint 步骤完成，then CLI 在交互终端询问继续且默认不继续。
- Given 工作流声明 `checkpoint_mode: auto`，when `/goal new` 或 `/goal run` 执行，then checkpoint 后自动推进且每个步骤最多执行一次。
- Given `GOAL_CHECKPOINT_MODE=auto`，when 工作流未声明模式，then 使用 auto；工作流显式声明模式时优先使用工作流声明。
- Given stdin 非 TTY 或用户拒绝，when checkpoint 完成，then 状态保持 `waiting_user` 并显示 `/goal resume` 提示。
- Given 非法模式值，when 加载 workflow，then 返回包含允许值的显式错误。

## Design Notes

模式优先级固定为：工作流 frontmatter `checkpoint_mode` > `GOAL_CHECKPOINT_MODE` > `prompt` 默认值。自动模式只负责在当前 checkpoint 完成后调用现有 `resume`/推进路径，不修改 Runner 的状态机和 checkpoint 语义。

## Verification

**Commands:**
- `pytest tests/test_config.py tests/test_goal_declarative_workflow.py -q` -- expected: all targeted tests pass。
- `ruff check src/heagent/config.py src/heagent/memory/skill_packages.py src/heagent/cli.py tests/test_config.py tests/test_goal_declarative_workflow.py` -- expected: no violations。

## Suggested Review Order

**Checkpoint routing**

- Resolve workflow and environment policy
  [`cli.py:1020`](../../src/heagent/cli.py#L1020)

- Advance only after explicit checkpoint decision
  [`cli.py:1163`](../../src/heagent/cli.py#L1163)

**Configuration contract**

- Parse strict global mode values
  [`config.py:109`](../../src/heagent/config.py#L109)

- Parse and validate workflow override
  [`skill_packages.py:54`](../../src/heagent/memory/skill_packages.py#L54)

- Document default and environment override
  [`workflow.md:6`](../../.heagent/workflows/workflow.md#L6)

**Verification**

- Cover auto, prompt, non-TTY, and invalid modes
  [`test_goal_declarative_workflow.py:226`](../../tests/test_goal_declarative_workflow.py#L226)

- Cover environment validation and defaults
  [`test_config.py:76`](../../tests/test_config.py#L76)
