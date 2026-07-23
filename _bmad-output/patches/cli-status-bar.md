---
story_id: "patch"
story_key: "cli-status-bar"
status: done
created: '2026-07-23'
completed: '2026-07-23'
---

# Patch: CLI 交互模式状态栏

Status: done

## Story

As a 开发者,
I want CLI 交互模式的输入提示符显示当前模型和 Token 用量,
So that 我能一目了然地看到当前使用的模型、已用 Token 和最大可用 Token 数。

## Acceptance Criteria

1. 交互模式 (`heagent` 无参数) 的 `>` 提示符前显示状态栏：`[模型名 | 已用/最大 tokens]` ✅
2. 首次进入时显示 `token: 0/max`，每次交互后自动更新 ✅
3. `/model` 切换模型后状态栏模型名同步更新 ✅
4. Token 数字使用千位分隔符格式化 (如 `1,234`) ✅
5. 单次模式 (`heagent "prompt"`) 保持原有行为不变 ✅

## Tasks / Subtasks

- [x] Task 1: 实现 `_format_status(loop)` 辅助函数 (AC: #1, #4)
- [x] Task 2: 修改 `_run_chat` 输入提示符 (AC: #1, #2, #3, #5)
- [x] Task 3: 验证 `/model` 切换后状态栏联动 (AC: #3)
- [x] Task 4: 验证无回归 (AC: #5)

## Dev Notes

### Implementation
- 新增 `_format_status(loop: AgentLoop) -> str`（`src/heagent/cli.py` L70-L82）
  - 从 `loop.provider.get_metadata().model` 读取当前模型名（实时，切换立即可见）
  - 从 `loop.last_usage.total_tokens` 读取已用 token（首次为 0）
  - 从 `get_settings().max_context_tokens` 读取最大 token 上限
  - 使用 `:,` 千位分隔符格式化数字
- 修改 `_run_chat()` 输入提示（`src/heagent/cli.py` L377-L378）
  - `input("> ")` → `input(f"{status}\n> ")`，状态栏占一行，`>` 占下一行
- 单次模式 `_run_single()` 未改动，保持原有输出行为
- 无需新增依赖、无需修改 `agent/` / `providers/` / `types.py`

### Architecture Constraints (verified)
- 仅修改 `src/heagent/cli.py`
- 不新增模块依赖，不修改 `agent/`、`providers/` 等
- `AgentLoop.last_usage` 为 None 时显示 `0`

### File Location
- 修改：`src/heagent/cli.py`（新增 `_format_status` + 修改 `_run_chat` 的 input prompt）

## Dev Agent Record

### Agent Model Used

Claude (claude-sonnet-4-20250514)

### Completion Notes List

- 945 tests pass, 0 failures; ruff lint clear
- `/model` 切换后 `_format_status` 通过 `loop.provider.get_metadata()` 实时读取新模型名
- 首次进入 `last_usage=None` → 显示 `0/128,000 tokens`
