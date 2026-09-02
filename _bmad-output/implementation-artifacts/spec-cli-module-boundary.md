---
title: '收敛 CLI 展示工具与目标路由边界'
type: 'refactor'
created: '2026-09-02'
status: 'done'
review_loop_iteration: 0
baseline_commit: '18516d92bef988250e1628d9275bfb3e8b90fa46'
context: ['E:\\AI\\HeAgent\\src\\heagent\\cli.py', 'E:\\AI\\HeAgent\\tests\\test_cli.py', 'E:\\AI\\HeAgent\\tests\\test_goal_declarative_workflow.py']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `src/heagent/cli.py` 同时承担命令解析、Provider 装配、流式终端展示和两套 `/goal` 路由，已超过 2000 行；声明式路由前的旧分支不可达，增加维护噪声和误导。

**Approach:** 将终端状态/Token 展示等纯展示职责提取到独立模块，由 `cli.py` 兼容导出既有私有符号；删除 `_goal_runner` 中声明式路由之后不可达的旧 dispatch 代码，保留当前声明式 `/goal` 行为和现有调用契约。

## Boundaries & Constraints

**Always:** 保持 CLI 命令行输出、私有导入符号、`_goal_runner` 声明式分发、Provider/Engine 装配行为不变；新模块不得依赖 CLI 入口；测试结构本轮不重命名、不迁移。

**Ask First:** 若提取需要改变公开 API、工具注册方式或跨包依赖，先停止并征求确认。

**Never:** 不删除仍被测试或 GUI 使用的目标辅助函数；不重写 `/goal` 工作流；不把测试文件整理混入本轮；不引入同步 I/O 或新第三方依赖。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|-----------------------------|----------------|
| DISPLAY | text/tool/done StreamEvent | 输出与当前 CLI 完全一致，行状态正确更新 | 未知事件保持静默 |
| TOKENS | 0、千级、百万级 TokenUsage | `_format_tokens_k` 与 `_print_usage` 输出不变 | 空 usage 不输出 |
| GOAL_WORKFLOW | workflow.md 存在 | `_goal_runner` 只进入声明式 dispatch 并返回 | 声明式 workflow 缺失时显性报错 |

</frozen-after-approval>

## Code Map

- `src/heagent/cli.py:87-179` — `_print_banner`、`_print_usage`、`_LineState`、流式展示和状态格式化；当前被 CLI 主循环和测试直接使用。
- `src/heagent/cli.py:1883-1993` — `_goal_runner`；声明式分支在 `return` 后仍保留不可达 legacy dispatch。
- `tests/test_cli.py:324-390` — 状态栏和 Token 展示行为断言；应继续通过 `heagent.cli` 兼容导入验证。
- `tests/test_goal_declarative_workflow.py:40-145` — `/goal` 声明式路由、缺失 workflow 和错误状态覆盖。
- `src/heagent/gui/screens/chat.py:203-212` — GUI 通过 CLI `/goal` 路由；不能破坏声明式入口。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/cli_display.py` — 承载纯终端 Banner、Token、行状态、事件和状态栏格式化 — 降低 CLI 入口模块职责密度。
- [x] `src/heagent/cli.py` — 从展示模块导入并兼容导出既有私有符号；删除 `_goal_runner` 的不可达 legacy dispatch — 保持调用契约并消除死代码。
- [x] `tests/test_cli.py` 与 `tests/test_goal_declarative_workflow.py` — 运行既有行为测试，不迁移测试文件 — 证明边界提取没有行为回归。

**Acceptance Criteria:**
- Given 现有 CLI 和 GUI 调用私有展示/goal 符号，when 完成模块提取，then 原导入路径和输出行为保持兼容。
- Given `_goal_declarative_workflow()` 返回有效 workflow，when 调用 `_goal_runner`，then 只执行声明式 dispatch，不包含或进入旧分支。
- Given workflow 缺失或无效，when 调用 `_goal_runner`，then 仍显性输出错误并返回，不静默回退到 legacy flow。
- Given 现有 CLI、Goal 和相关单元测试，when 执行验证命令，then 测试通过且无新增第三方依赖。

## Design Notes

展示模块只依赖 `click`、`dataclasses`、`typing`、`heagent` 的稳定类型和 Token 估算函数；`cli.py` 保留别名导入，确保已有私有导入和 GUI 调用不需要同步迁移。目标旧 helper 暂不删除，因为部分测试和兼容性诊断仍直接引用它们；本轮只删除确定不可达的 dispatch 代码。

## Verification

**Commands:**
- `pytest tests/test_cli.py tests/test_goal_declarative_workflow.py -q` — expected: 全部通过。
- `ruff check src/heagent/cli.py src/heagent/cli_display.py tests/test_cli.py tests/test_goal_declarative_workflow.py` — expected: 无 lint 错误。
- `git diff --check` — expected: 无空白错误。

## Suggested Review Order

**模块边界**

- 先看展示职责的独立模块
  [`cli_display.py:1`](../../src/heagent/cli_display.py#L1)
- 再看 CLI 的兼容导入
  [`cli.py:19`](../../src/heagent/cli.py#L19)

**目标路由**

- 核对声明式 workflow 入口
  [`cli.py:1796`](../../src/heagent/cli.py#L1796)
- 核对 legacy dispatch 删除位置
  [`cli.py:1813`](../../src/heagent/cli.py#L1813)

**验证**

- 查看 CLI 回归测试
  [`test_cli.py:324`](../../tests/test_cli.py#L324)
- 查看声明式 workflow 测试
  [`test_goal_declarative_workflow.py:40`](../../tests/test_goal_declarative_workflow.py#L40)
