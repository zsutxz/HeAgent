# HeAgent GUI 终端界面 — PRD

> BMad Method · Step 2: prd
> 日期: 2026-07-23
> 输入: brief.md, docs/gui-plan.md

## 一、功能需求（FR）

### 流式聊天（Phase 1）

- **FR-G1**：启动 `heagent gui` 进入全屏 TUI，显示主聊天界面（消息列表 + 输入框 + 状态栏）
- **FR-G2**：用户在输入框输入 prompt 按 Enter 后，Agent 开始执行，LLM 文本流式逐字显示在消息列表中
- **FR-G3**：消息列表支持 Markdown 渲染（代码块、列表、粗体、链接等）
- **FR-G4**：用户消息与 Agent 消息视觉上可区分（不同颜色/前缀）
- **FR-G5**：状态栏实时显示当前模型名、迭代数（如 `iter 3/50`）、Token 使用量（`1234 in + 567 out`）
- **FR-G6**：Agent 执行期间输入框禁用，执行完成后恢复；状态栏显示"运行中"指示

### 工具调用可视化（Phase 2）

- **FR-G7**：Agent 调用工具时，消息列表中插入折叠卡片，显示工具名 + 状态（执行中/已完成/失败）
- **FR-G8**：点击或自动展开工具卡片后，显示调用参数（如 `command: pip list`）和执行结果
- **FR-G9**：工具执行失败时卡片显示红色标记，展开后显示错误信息
- **FR-G10**：工具卡片显示执行耗时（如 `已完成, 0.3s`）

### 斜杠命令与中断（Phase 2）

- **FR-G11**：输入框支持 `/model` 命令：无参数列出可用 Provider，带参数（如 `/model deepseek`）切换
- **FR-G12**：输入框支持 `/mcp-prompt` 命令（行为与 CLI 交互模式一致）
- **FR-G13**：`Ctrl+C` 中断当前 Agent 运行，显示"[已中断]"，恢复输入框
- **FR-G14**：`Ctrl+L` 清空当前消息列表

### 管理面板（Phase 3）

- **FR-G15**：提供页面导航（Tab 切换或快捷键 F1-F6），可在聊天/技能/Cron/记忆/运行历史/事件日志间切换
- **FR-G16**：技能管理面板：表格列出所有技能（名称/tags/使用次数/最后使用时间），支持查看详情、归档、删除
- **FR-G17**：技能管理面板：支持创建新技能（弹窗输入 name/description/pattern/steps/tags）
- **FR-G18**：Cron 管理面板：表格列出所有定时任务（prompt/schedule/状态/上次执行），支持增删
- **FR-G19**：记忆面板：查看事实记忆列表（MEMORY.md 内容）和用户画像（USER.md 内容）

### 可观测性（Phase 4）

- **FR-G20**：运行历史面板：树形结构展示运行记录（supervisor → sub-agent 关系），含状态、迭代数、时间
- **FR-G21**：运行历史面板：可选中某次运行查看详情（prompt、结果、工具调用链）
- **FR-G22**：运行历史面板：对未完成的运行提供"恢复运行 (resume)"操作
- **FR-G23**：事件日志面板：实时显示引擎事件流（`tool.started` / `tool.completed` / `iteration.end` 等）
- **FR-G24**：事件日志面板：支持暂停/恢复滚动、按事件类型过滤

## 二、非功能需求（NFR）

- **NFR-G1**：核心模块（`agent/`、`engine/`、`providers/`、`tools/` 等）**零行改动**
- **NFR-G2**：GUI 依赖通过 `[project.optional-dependencies] gui` 声明，不装不影响现有功能
- **NFR-G3**：Textual ≥ 1.0，pin 主版本号（`textual>=1.0,<2.0`）
- **NFR-G4**：GUI 代码全部位于 `src/heagent/gui/`，不侵入现有模块
- **NFR-G5**：现有 922 测试全量通过（GUI 代码不改变任何现有行为路径）
- **NFR-G6**：TUI 在 80×24 终端窗口下可正常使用（Textual 自适应布局）
- **NFR-G7**：Agent 执行期间 UI 不卡顿（Agent 在后台 Worker 中运行，UI 主循环独立）
- **NFR-G8**：GUI 代码覆盖率 ≥ 50%（TUI 测试受限于 Textual 框架的 DOM 交互模拟，核心 bridge 层和状态管理逻辑必须覆盖）

## 三、FR 与 Epic 预映射

| Epic | FR | 主题 |
|------|----|------|
| Epic 24 | FR-G1~G6 | 流式聊天（最小可跑） |
| Epic 25 | FR-G7~G14 | 工具可视化 + 斜杠命令 + 中断 |
| Epic 26 | FR-G15~G19 | 管理面板（技能/Cron/记忆） |
| Epic 27 | FR-G20~G24 | 可观测性（运行历史/事件日志） |

## 四、Epic 依赖关系

```
Epic 24 (流式聊天) ──┬──▶ Epic 25 (工具可视化 + 斜杠命令)
                     │
                     └──▶ Epic 26 (管理面板) ──▶ Epic 27 (可观测性)
                              (Epic 26/27 可在 Epic 25 进行中并行开发)
```

- Epic 24 是所有后续 Epic 的**硬前置**——必须先有可跑的聊天界面
- Epic 25 依赖 Epic 24 的消息列表和输入框基础设施
- Epic 26 可与 Epic 25 并行（管理面板是独立 Screen，不依赖工具卡片）
- Epic 27 的部分功能（事件日志）可在 Epic 24 后随时接入，运行历史树需要 Epic 24 的 Agent 运行基础设施

## 五、UX 设计要点

- **配色**：暗色主题（Textual 默认 dark theme），与终端环境协调；工具卡片使用不同颜色区分状态（绿=完成、黄=执行中、红=失败）
- **导航**：Footer 栏显示 F1-F6 快捷键对应各页面，`Tab` 在输入框和消息列表间切换焦点
- **响应式**：窗口缩小时消息列表自动收缩，状态栏保持一行高度
- **加载状态**：Agent 执行期间显示旋转指示器或"思考中"动画
