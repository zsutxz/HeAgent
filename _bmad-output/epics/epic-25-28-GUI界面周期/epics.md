# HeAgent GUI 终端界面 — Epic Breakdown

> BMad Method · Step 4: epics
> 日期: 2026-07-23
> 输入: prd.md, architecture.md

## Overview

4 个 Epic，24 个 FR，核心零改动。Epic 25 是硬前置，Epic 26 依赖 Epic 25，Epic 27/28 可在 Epic 26 进行中并行开发。

## FR Coverage Map

| FR | Epic | 主题 |
|----|------|------|
| FR-G1 | 25 | 启动 TUI + 主聊天界面 |
| FR-G2 | 25 | 流式 LLM 回复 |
| FR-G3 | 25 | Markdown 渲染 |
| FR-G4 | 25 | 用户/Agent 消息区分 |
| FR-G5 | 25 | 状态栏（模型/Token/迭代） |
| FR-G6 | 25 | 执行期间输入禁用 + 运行指示 |
| FR-G7 | 26 | 工具调用折叠卡片 |
| FR-G8 | 26 | 卡片展开（参数+结果） |
| FR-G9 | 26 | 工具失败红色标记 |
| FR-G10 | 26 | 工具执行耗时 |
| FR-G11 | 26 | `/model` 斜杠命令（含自动补全） |
| FR-G12 | 26 | `/mcp-prompt` 斜杠命令 |
| FR-G13 | 26 | `Ctrl+C` 中断 Agent |
| FR-G14 | 26 | `Ctrl+L` 清屏 |
| FR-G15 | 27 | 页面导航（F1-F6 快捷键） |
| FR-G16 | 27 | 技能管理表格（列表/详情/归档/删除） |
| FR-G17 | 27 | 技能创建弹窗 |
| FR-G18 | 27 | Cron 管理表格（增删） |
| FR-G19 | 27 | 记忆/画像查看 |
| FR-G20 | 28 | 运行历史树 |
| FR-G21 | 28 | 运行详情查看 |
| FR-G22 | 28 | 恢复运行 (resume) |
| FR-G23 | 28 | 事件日志实时流 |
| FR-G24 | 28 | 事件日志过滤 |

---

## Epic 25 — 流式聊天（最小可跑）

> 硬前置；目标：能在 TUI 里聊天，流式看到回复。

### Story 25-1: 项目骨架与 CLI 入口

**AC**：
- [ ] `src/heagent/gui/__init__.py` 存在，公开 `gui_main()`
- [ ] `src/heagent/gui/app.py` 存在，`HeAgentApp(App)` 类：空 Screen + Footer 快捷键提示
- [ ] `src/heagent/gui/cli.py` 存在，`gui` Click 子命令
- [ ] `pyproject.toml` 新增 `[project.optional-dependencies] gui = ["textual>=1.0,<2.0"]`
- [ ] `cli.py` 改造为 `click.Group`（`run` + `gui` 子命令），现有 `main()` 逻辑移入 `run`
- [ ] `pip install -e ".[gui]" && heagent gui` 可启动空白 TUI（按 Ctrl+Q 退出）
- [ ] 不装 `[gui]` 时 `heagent "prompt"` 行为不变

### Story 25-2: 流式聊天引擎（bridge + 核心交互）

**AC**：
- [ ] `gui/bridge.py` — `AgentBridge` 类：`submit(prompt)` 消费 `AgentLoop.run_stream()`
- [ ] `gui/state.py` — `GuiState` Pydantic 模型（model_name, iteration, token_usage, is_running）
- [ ] `gui/screens/chat.py` — `ChatScreen`：消息列表 + 输入框 + 状态栏
- [ ] `gui/widgets/message_list.py` — `MessageList(RichLog)` 支持流式文本追加
- [ ] `gui/widgets/input_area.py` — `InputArea`：单行 `Input` + 发送按钮
- [ ] `gui/widgets/status_bar.py` — `StatusBar`：模型名 + Token + 迭代数
- [ ] 用户输入 prompt → Agent 流式回复 → 文本逐字出现在消息列表
- [ ] 用户消息与 Agent 消息视觉区分（不同颜色/前缀，如 `>` 和 `🤖`）
- [ ] Token 和迭代数在 Agent 完成后更新到状态栏

### Story 25-3: Markdown 渲染与执行状态

**AC**：
- [ ] 消息列表正确渲染 Markdown（代码块高亮、列表、粗体/斜体、链接）
- [ ] Agent 执行期间输入框禁用，执行完成后自动恢复
- [ ] 状态栏在执行期间显示"运行中"指示（如旋转箭头或文字提示）
- [ ] Agent 执行期间禁止发送新消息（输入框灰色 + placeholder 提示"Agent 运行中..."）
- [ ] `AgentLoop.run_stream()` 异常时 GUI 显示错误提示而非崩溃

---

## Epic 26 — 工具可视化 + 斜杠命令

> 依赖 Epic 25；目标：完整的对话体验。

### Story 26-1: 工具调用卡片

**AC**：
- [ ] `gui/widgets/tool_card.py` — `ToolCard(Static)`：折叠/展开
- [ ] 收到 `StreamEvent(type="tool_call")` 时，在消息列表插入折叠卡片
- [ ] 卡片标题栏："🔧 {tool_name} (执行中...)"；展开后显示参数
- [ ] 收到 `StreamEvent(type="tool_result")` 时，更新对应卡片
- [ ] 执行成功：卡片变绿色 + "已完成, {duration}"；展开显示结果
- [ ] 执行失败（`is_error=True`）：卡片变红色 + "失败"；展开显示错误信息
- [ ] 卡片支持键盘导航（Tab 到卡片，Enter 展开/折叠）

### Story 26-2: 斜杠命令

**AC**：
- [ ] 输入框支持 `/model`：无参数列出可用 Provider + 当前标记；带参数切换
- [ ] `/model` 支持 Tab 自动补全（Provider 名称列表）
- [ ] 输入框支持 `/mcp-prompt`（行为对齐 CLI 交互模式）
- [ ] 输入框支持 `/clear` 清空消息列表（等价 `Ctrl+L`）
- [ ] 输入框支持 `/help` 列出所有可用命令
- [ ] 非斜杠命令的普通文本原样发送给 Agent

### Story 26-3: 中断与快捷键

**AC**：
- [ ] `Ctrl+C` 中断当前 Agent 运行：bridge.cancel() → AgentLoop 收到 CancelledError → 显示"[已中断]"
- [ ] 中断后输入框恢复可用，可发送新 prompt
- [ ] `Ctrl+L` 清空当前消息列表
- [ ] `Ctrl+Q` 退出 TUI（已有 Textual 默认行为，确认即可）
- [ ] `Escape` 取消当前输入（清空输入框）
- [ ] 中断路径测试：StubProvider 模拟无限循环 → `Ctrl+C` → Agent 中断 + UI 恢复

---

## Epic 27 — 管理面板

> 依赖 Epic 25（需要页面导航基础设施）；可与 Epic 26 并行。

### Story 27-1: 页面导航系统

**AC**：
- [ ] `HeAgentApp` 使用 `TabbedContent` 或 Screen 栈管理多页面
- [ ] Footer 快捷键：`F1` 聊天 / `F2` 技能 / `F3` Cron / `F4` 记忆 / `F5` 运行 / `F6` 日志
- [ ] 切换页面时保留各页面状态（如聊天消息不丢失）
- [ ] 从管理页面切回聊天时，输入焦点自动回到输入框

### Story 27-2: 技能管理面板

**AC**：
- [ ] `gui/screens/skills.py` — `SkillScreen`：DataTable 列出所有技能
- [ ] 表头：skill 名 / tags / 使用次数 / 最后使用时间
- [ ] 过期技能（超 `skill_curator_stale_days` 天未使用）显示 ⚠️ 标记
- [ ] 选中行后底部显示操作按钮：[查看详情] [归档] [删除]
- [ ] "查看详情"弹出 SKILL.md 内容（Markdown 渲染）
- [ ] "新建技能"按钮 → 弹窗：name / description / pattern / steps / tags
- [ ] 创建/归档/删除操作调用已有 `skill_*` 工具（经 ToolRegistry）

### Story 27-3: Cron + 记忆面板

**AC**：
- [ ] `gui/screens/cron.py` — `CronScreen`：DataTable 列出所有定时任务
- [ ] 表头：prompt（截断） / schedule / 状态 / 上次执行；排序按创建时间
- [ ] [添加任务] → 弹窗：prompt / schedule / recurring 开关
- [ ] [删除任务] → 确认弹窗
- [ ] `gui/screens/memory.py` — `MemoryScreen`：Tab 切换"事实记忆"和"用户画像"
- [ ] 事实记忆 Tab：Markdown 渲染 MEMORY.md 内容
- [ ] 用户画像 Tab：Markdown 渲染 USER.md 内容（按 section 分段）
- [ ] 记忆面板为只读展示（编辑由 Agent 通过 `fact_add`/`profile_update` 工具自主完成）

---

## Epic 28 — 可观测性

> 依赖 Epic 25（Agent 运行基础设施）+ Epic 27（页面导航）；可与 Epic 26 并行。

### Story 28-1: 事件日志面板

**AC**：
- [ ] `gui/widgets/event_log.py` — `EventLog(RichLog)`：实时追加引擎事件
- [ ] 每条日志格式：`[timestamp] [event_type] run=... tool=... details=...`
- [ ] 通过 `EventBus.subscribe(GuiEventObserver)` 接入（architecture.md §3.2）
- [ ] 支持暂停/恢复自动滚动（`Space` 键切换）
- [ ] 支持清空日志（`Ctrl+L` 在日志页面）
- [ ] 非聊天页面的 `StatusBar` 也显示最新事件摘要

### Story 28-2: 运行历史面板

**AC**：
- [ ] `gui/screens/runs.py` — `RunsScreen`：Textual `Tree` widget 渲染运行树
- [ ] 数据源：`RunStore.build_run_tree(limit=50)`
- [ ] 根节点：supervisor run（时间 + prompt 摘要 + 状态图标 ✅/❌）
- [ ] 子节点：sub-agent（role 名 + 状态 + 迭代数 + run_id 截断），缩进显示
- [ ] 点击节点展开详情面板（右侧或弹窗）：
  - 完整 prompt
  - 最终回答（截断，可展开）
  - 子任务列表（如有）
  - Token 使用量
- [ ] 未完成的运行（`RunStatus != COMPLETED`）提供 [恢复运行] 按钮
- [ ] [恢复运行] 调用 `AgentLoop.resume(run_id)` 继续执行

### Story 28-3: 运行详情与恢复

**AC**：
- [ ] 运行详情面板内容完整可滚动（长输出不截断）
- [ ] "恢复运行"时在聊天页面新开 Agent，状态栏显示 `[resume: {run_id[:8]}]`
- [ ] 恢复后运行树自动刷新（显示更新后的状态）
- [ ] 恢复失败时（如 run_id 不存在）显示错误提示
- [ ] 支持按状态过滤运行树（全部/已完成/未完成/失败）
- [ ] 测试：Mock RunStore → 构建 3 层运行树 → Tree widget 正确渲染

---

## Timeline 估算

| Epic | Story 数 | 估算 | 依赖 |
|------|---------|------|------|
| 25 | 3 | 2-3 天 | — |
| 26 | 3 | 2-3 天 | Epic 25 |
| 27 | 3 | 3-4 天 | Epic 25 |
| 28 | 3 | 2-3 天 | Epic 25 + 27 |
| **总计** | **12** | **9-13 天** | |

> Epic 27/28 可在 Epic 26 进行中并行开发（不同 Screen，零代码冲突）。

## Dependency Graph

```
                    ┌──────────┐
                    │ Epic 25  │  (流式聊天 — 硬前置)
                    └────┬─────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
       ┌──────────┐ ┌──────────┐ ┌──────────┐
       │ Epic 26  │ │ Epic 27  │ │ Epic 28  │
       │ 工具卡片 │ │ 管理面板 │ │ 可观测性 │
       │ 斜杠命令 │ │          │ │          │
       └──────────┘ └────┬─────┘ └────┬─────┘
                         └──────┬─────┘
                               │
                          (Epic 28 部分功能需 Epic 27 的页面导航)
```
