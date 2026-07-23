# HeAgent GUI 集成计划

> 状态：规划阶段 | 最后更新：2026-07-22

---

## 一、定位与约束

GUI 是 HeAgent 的**可选交互层**，地位与 `cli.py` 平级——是库的**消费者**，不是核心的一部分。核心模块（`agent/`、`engine/`、`providers/`、`tools/` 等）**零改动**。

```
                    ┌──────────────────────┐
                    │     AgentLoop        │  ← 核心，零改动
                    │  (run / run_stream)  │
                    └──────┬───────────────┘
                           │ StreamEvent / EventBus
              ┌────────────┼────────────┐
              ▼            ▼            ▼
          cli.py       gui/         (未来 Web API)
```

设计原则（对齐项目 `design.md`）：

| 原则 | GUI 中的应用 |
|------|-------------|
| 模块边界优先 | `gui/` 是独立包，核心模块不感知 GUI 存在 |
| 声明式扩展点 | 复用 `StreamEvent` / `EventBus` / `RunStore`，不新增内部钩子 |
| 学习价值优先 | 选 Textual（async-native 终端框架），展示 asyncio + 事件驱动 UI 的完整范式 |
| 不堆砌功能 | 分阶段交付，每阶段有独立的“可演示”产物 |

---

## 二、技术选型：Textual（终端 UI）

**为什么选 Textual：**

| 维度 | Textual | Web (FastAPI+WS) | Gradio | PyQt |
|------|---------|------------------|--------|------|
| async-native | ✅ 内置 asyncio event loop | ✅ 但需额外 WS 层 | ❌ 基于队列 hack | ❌ 需 QEventLoop 桥 |
| 与现有栈一致 | ✅ 纯 Python | 需 HTML/JS/CSS | ✅ | 需 C++ 绑定 |
| 依赖重量 | 轻（~5MB） | 中 | 重（许多隐式依赖） | 重（~50MB+） |
| 终端原生 | ✅ | ❌ | ❌ | ❌ |
| 适合“学习/实验”定位 | ✅✅ | ⚠️ | ❌ | ❌ |
| 流式文本渲染 | ✅ Markdown 原生 | ✅ | ✅ | 需自绘 |

**Textual 核心概念**（方便理解后续设计）：

```
App          — 应用入口，管理 Screen 栈和事件循环
Screen       — 全屏页面（类似 Web 的 route）
Widget       — 可组合的 UI 组件（类似 React 组件）
Message      — Widget 间异步通信（类似 Redux action）
Worker       — 后台协程，不阻塞 UI
```

---

## 三、架构分层

```
src/heagent/gui/
├── __init__.py               # 公开 gui_main() 入口
├── app.py                    # Textual App（Screen 栈 + 全局状态）
├── bridge.py                 # AgentLoop ↔ GUI 异步桥接（核心胶水）
├── cli.py                    # Click 子命令组 "heagent gui"
│
├── screens/                  # 全屏页面
│   ├── chat.py               # 主聊天界面（消息列表 + 输入框）
│   ├── skills.py             # 技能管理（列表/创建/编辑/归档）
│   ├── cron.py               # Cron 任务管理
│   ├── memory.py             # 记忆/画像查看器
│   └── runs.py               # 运行历史树（RunStore.build_run_tree）
│
├── widgets/                  # 可复用组件
│   ├── message_list.py       # 聊天消息列表（Markdown 渲染 + 流式追加）
│   ├── tool_card.py          # 工具调用卡片（折叠展开 + 结果）
│   ├── status_bar.py         # 状态栏（模型名 / 迭代数 / Token / 时间）
│   ├── event_log.py          # 引擎事件实时日志
│   └── input_area.py         # 多行输入框 + 斜杠命令自动补全
│
└── state.py                  # 响应式全局状态（Pydantic 模型）
```

**依赖规则**：

```
gui/  ──依赖──▶  agent/  engine/  providers/  tools/  memory/  cron/  context/
                        ⬆ 核心模块不感知 gui/ 存在
```

---

## 四、数据流

### 4.1 核心数据流（与现有架构的关系）

```
                         ┌─ AgentLoop.run_stream() ─┐
                         │  yield StreamEvent:       │
                         │    text="Hello"           │──▶ bridge._on_text(text)
                         │    tool_call=ToolCall()   │──▶ bridge._on_tool_call(tc)
                         │    tool_result=...        │──▶ bridge._on_tool_result(tr)
                         │    type="done"            │──▶ bridge._on_done()
                         └──────────────────────────┘
                                      
                         ┌─ EventBus ────────────────┐
                         │  publish("tool.started")  │──▶ GUI 观察者 → event_log / status_bar
                         │  publish("iteration.end") │
                         └──────────────────────────┘
```

关键点：**`AgentLoop` 已经有 `run_stream()` 和 `EventBus`，GUI 只需消费这两个现成接口，不需新增任何核心钩子。**

### 4.2 bridge.py 设计（核心胶水）

```python
# bridge.py —— 伪代码示意，非实现

class AgentBridge:
    """在 Textual App 和 AgentLoop 之间桥接 async 数据流。

    职责：
    1. 把用户输入提交给 AgentLoop.run_stream()
    2. 把 StreamEvent 转为 Textual Message 投递给 widget
    3. 订阅 EventBus 投递引擎事件到 UI
    """

    def __init__(self, app: "HeAgentApp", loop: AgentLoop):
        self.app = app
        self.loop = loop

    async def submit(self, prompt: str) -> None:
        """用户输入入口——在 Worker 中跑，不阻塞 UI。"""
        async for event in self.loop.run_stream(prompt):
            self.app.post_message(StreamMessage(event))

    def subscribe_events(self, bus: EventBus) -> None:
        """把引擎事件桥接到 UI。"""
        bus.subscribe(GuiEventObserver(self.app))
```

**为什么用 `post_message` 而不是直接调 widget 方法：**

- Textual 的 UI 更新必须在主事件循环线程中执行
- `AgentLoop.run_stream()` 在 `Worker`（后台协程）中跑
- `post_message()` 是 Textual 的线程安全投递机制——Worker 投递 → 主循环消费 → UI 更新

---

## 五、界面布局

### 5.1 主聊天界面（`screens/chat.py`）

```
┌──────────────────────────────────────────────────────────┐
│  HeAgent v2.x                        模型: deepseek-chat │  ← status_bar
│──────────────────────────────────────────────────────────│
│                                                          │
│  ┌─ 用户 ─────────────────────────────────────────────┐  │
│  │ 帮我分析 docs/news.md 的 AI 新闻                     │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌─ HeAgent ──────────────────────────────────────────┐  │
│  │ 好的，让我先读取文件...                              │  │
│  │                                                     │  │
│  │ ┌─ 🔧 file_read (已完成) ────────────────────────┐  │  │
│  │ │ path: docs/news.md                              │  │  │
│  │ │ ✓ 读取完成 (2,345 字符)                          │  │  │
│  │ └────────────────────────────────────────────────┘  │  │
│  │                                                     │  │
│  │ 根据文件内容，本日 AI 新闻包括...                     │  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│──────────────────────────────────────────────────────────│
│  > 你的输入...                                [发送 ⏎] │  ← input_area
│──────────────────────────────────────────────────────────│
│ [tokens: 1234 in + 567 out = 1801]    iter 3/50  09:01  │  ← status_bar
└──────────────────────────────────────────────────────────┘
```

### 5.2 页面导航（Tab 切换）

```
 F1  Chat      聊天主界面（流式对话 + 工具调用可视化）
 F2  Skills    技能列表 / 创建 / 编辑 / 归档
 F3  Cron      Cron 任务列表 / 增删 / 日志
 F4  Memory    事实记忆 / 用户画像查看
 F5  Runs      运行历史树（supervisor → sub-agent 层级）
 F6  Log       引擎事件实时日志
```

可用 `Footer` widget 显示快捷键，或 `TabbedContent` 切换。

### 5.3 技能管理界面（`screens/skills.py`）

```
┌──────────────────────────────────────────────────────────┐
│  Skills                                     [+ 新建技能] │
│──────────────────────────────────────────────────────────│
│  ┌─────────────────────────────────────────────────────┐ │
│  │ skill          │ tags        │ 使用次数 │ 最后使用  │ │
│  │────────────────┼─────────────┼─────────┼───────────│ │
│  │ fetch_ai_news  │ ai, news    │   47    │ 07-20     │ │
│  │ code_review    │ code, git   │   12    │ 07-18     │ │
│  │ deploy_check   │ deploy, ops │    3    │ 07-10 ⚠️  │ │  ← 过期标记
│  └─────────────────────────────────────────────────────┘ │
│──────────────────────────────────────────────────────────│
│  [编辑] [归档] [删除]                                    │
└──────────────────────────────────────────────────────────┘
```

### 5.4 运行历史树（`screens/runs.py`）

利用已有的 `RunStore.build_run_tree()`：

```
┌──────────────────────────────────────────────────────────┐
│  Run History                                                 │
│──────────────────────────────────────────────────────────│
│  ▼ 2026-07-20 09:01  (a3f2)  "分析AI新闻"  ✅  3 iter    │
│     ├─ (b1c4) planner      ✅  2 iter                   │
│     ├─ (d5e6) coder         ❌  BudgetExceeded           │
│     └─ (f7g8) tester        ✅  1 iter                   │
│  ▼ 2026-07-20 08:55  (9h0i)  "重构 config"  ✅  5 iter   │
│──────────────────────────────────────────────────────────│
│  [查看详情] [恢复运行 (resume)]                           │
└──────────────────────────────────────────────────────────┘
```

---

## 六、分阶段路线图

### Phase 1 — 最小可跑（目标：2-3 天）

**目标**：能在终端里聊天，流式看到回复。

**交付物**：

- `gui/app.py` — Textual App 骨架 + 单 Screen
- `gui/bridge.py` — `AgentLoop.run_stream()` → Textual `post_message` 桥接
- `gui/widgets/message_list.py` — 流式 Markdown 消息列表（`RichLog` + 逐块 append）
- `gui/widgets/input_area.py` — 单行 `Input` + 发送
- `gui/widgets/status_bar.py` — 静态底栏（模型名 / tokens）
- `gui/cli.py` — `heagent gui` 子命令入口
- `pyproject.toml` — `[project.optional-dependencies] gui = ["textual"]`

**不做的**：工具卡片、多页面、斜杠命令、管理面板

**验证方式**：`pip install -e ".[gui]" && heagent gui`，输入 prompt，流式看到回复。

### Phase 2 — 完整对话体验（目标：2-3 天）

**目标**：工具调用可视化 + 斜杠命令 + 模型切换。

**交付物**：

- `gui/widgets/tool_card.py` — 工具调用卡片（折叠/展开，显示参数和结果）
- `gui/widgets/input_area.py` 增强 — `/model` `/mcp-prompt` 斜杠命令自动补全
- `gui/widgets/status_bar.py` 增强 — 实时迭代计数 + 动态模型名
- `gui/screens/chat.py` 增强 — 中断按钮（停止当前 Agent 运行）
- 快捷键 `Ctrl+C` 中断 Agent，`Ctrl+L` 清屏

### Phase 3 — 管理面板（目标：3-4 天）

**目标**：技能/Cron/记忆的管理 UI。

**交付物**：

- `gui/screens/skills.py` — 技能 CRUD + 归档（调用已有 `skill_*` 工具）
- `gui/screens/cron.py` — Cron 任务列表 + 增删（调用已有 `cron_*` 工具）
- `gui/screens/memory.py` — 事实记忆/用户画像查看（读 `MEMORY.md` / `USER.md`）
- 页面导航（`TabbedContent` 或侧栏 + `Footer` 快捷键提示）

### Phase 4 — 可观测性（目标：2-3 天）

**目标**：运行历史 + 事件日志 + 子 Agent 追踪。

**交付物**：

- `gui/screens/runs.py` — 运行树（复用 `RunStore.build_run_tree()` + `Tree` widget）
- `gui/widgets/event_log.py` — 引擎事件实时流（订阅 `EventBus`）
- 子 Agent 运行状态实时显示
- `resume` 功能：从运行历史恢复未完成的 run

---

## 七、关键设计决策

### 7.1 流式渲染策略

```
AgentLoop.run_stream()  ──text chunk──▶  bridge._on_text()
                                            │
                                   App.post_message(TextChunk(data))
                                            │
                                   message_list.append_chunk(data)
                                            │
                                   RichLog.write(data)  ← Textual 原生支持增量 Markdown
```

Textual 的 `RichLog` 支持 `write()` 追加内容并渲染 Markdown，天然适合流式场景。不需要自己管理缓冲区。

### 7.2 工具调用可视化

`StreamEvent` 已有 `tool_call` 和 `tool_result` 两种事件类型——在消息列表中插入折叠卡片：

```
┌─ 🔧 shell (执行中...) ──────────────────────────────┐  ← tool_card (collapsed)
│  command: pip list | grep textual                     │
└──────────────────────────────────────────────────────┘
       ↓ (收到 tool_result 后展开)
┌─ 🔧 shell (已完成, 0.3s) ───────────────────────────┐
│  command: pip list | grep textual                     │
│  ────────────────────────────────────────────────     │
│  textual    0.82.0                                    │
└──────────────────────────────────────────────────────┘
```

### 7.3 全局状态管理（`state.py`）

```python
# 伪代码
class AppState(BaseModel):
    """响应式全局状态——Textual 的 reactive 属性会自动触发 UI 更新。"""
    model_name: str = ""
    iteration: int = 0
    max_iterations: int = 50
    token_usage: TokenUsage = TokenUsage()
    is_running: bool = False        # 是否正在执行 Agent
    current_tool_calls: list[str]   # 当前活跃的工具调用名
    last_error: str | None = None
```

Textual 的 `reactive` 装饰器会在属性变化时自动通知绑定 widget 重绘——不需要手动 pub/sub。

### 7.4 中断处理

```
用户按 Ctrl+C 或点击 [停止]
       │
       ▼
bridge.cancel()  ──▶  asyncio.Task.cancel()
       │                    │
       ▼                    ▼
AgentLoop 收到 CancelledError  →  优雅退出
       │
       ▼
GUI 显示 "[已中断]" 并恢复输入
```

需要 `AgentLoop.run_stream()` 支持 `CancelledError` 的优雅处理（当前已有 `finally` 块做 session 保存，应能自动处理——需验证）。

### 7.5 `--gui` 入口设计

```
python -m heagent              # 现有：CLI 交互模式
python -m heagent "prompt"     # 现有：单次执行
python -m heagent gui          # 新增：启动 TUI
python -m heagent gui --model deepseek-chat  # 指定模型
```

用 Click 的 `Group` 把现有 `main` 和新的 `gui` 命令组合：

```python
# cli.py 改造示意
@click.group()
def cli():
    pass

@cli.command()           # heagent run "prompt"
@click.argument("prompt")
def run(prompt, ...): ...

@cli.command()           # heagent gui
def gui(...): ...
```

或者更简单：加 `--gui` flag（改动更小，但 CLI 语义略混）。

---

## 八、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Textual 版本升级 break | 中 | pin 版本；Textual 1.0 已 stable |
| `run_stream()` 的 CancelledError 未正确清理 | 中 | Phase 2 重点验证；必要时在 `AgentLoop` 加 `except asyncio.CancelledError` 清理 |
| 终端不支持（Windows cmd / PS 旧版） | 低 | Textual 支持 Windows Terminal；不支持的传统控制台报友好错误 |
| 终端窗口太小 | 低 | Textual 自适应布局；最小尺寸 80×24 |
| 用户不想装 GUI 依赖 | 无 | `[gui]` optional extra，不装就不加载 |

---

## 九、不做的事（明确非目标）

- **不做 Web 界面**（Phase 1-4 完成后可作为 Phase 5 评估，但当前定位是终端工具）
- **不改 `AgentLoop` 核心**（已有 `run_stream()` + `EventBus` 足够）
- **不做多窗口/多会话并发**（单会话单 Agent，和 CLI 交互模式一致）
- **不做图形化配置向导**（`.env` 编辑已足够，配置项多但不是 GUI 的核心价值）
- **不做移动端/远程访问**（那是 Web 版的范畴）

---

## 十、总结

| 维度 | 方案 |
|------|------|
| **技术栈** | Textual（终端 UI，async-native，纯 Python） |
| **核心桥接** | `AgentLoop.run_stream()` + `EventBus` → `post_message()` → Widget |
| **改动范围** | 仅新增 `src/heagent/gui/` + `pyproject.toml` optional dep；核心 0 改动 |
| **入口** | `heagent gui` 子命令 |
| **交付节奏** | 4 个 Phase，每个 2-4 天，每 Phase 独立可演示 |
| **总工期估算** | 约 9-13 天（单人） |
