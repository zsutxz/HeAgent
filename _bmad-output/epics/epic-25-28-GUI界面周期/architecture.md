# HeAgent GUI 终端界面 — Architecture

> BMad Method · Step 3: architecture
> 日期: 2026-07-23
> 输入: prd.md, docs/gui-plan.md, docs/frame.md

## 一、技术选型冻结

| 决策 | 选型 | 冻结理由 |
|------|------|----------|
| UI 框架 | **Textual 1.x**（`textual>=1.0,<2.0`） | async-native asyncio 事件循环，无需桥接层；纯 Python；终端原生 Markdown 渲染 |
| 入口方式 | **`heagent gui` 子命令**（Click `Group`） | 与现有 `heagent [prompt]` CLI 并列，启动路径独立 |
| 依赖策略 | **optional extra `[gui]`** | 不装 Textual 不影响现有 CLI |
| 流式桥接 | **`AgentLoop.run_stream()` → `App.post_message()`** | 无需新增核心钩子；`run_stream()` 已在 CLI 交互模式验证 |
| 事件订阅 | **`EventBus.subscribe(GuiEventObserver)`** | 复用引擎可观测性基础设施 |
| 状态管理 | **Textual `reactive` + Pydantic 模型** | reactive 自动触发 UI 更新；Pydantic 与项目一致 |

## 二、模块结构（冻结）

```
src/heagent/gui/
├── __init__.py               # 公开 gui_main() → Textual app 入口
├── app.py                    # Textual App 子类（Screen 栈、全局状态、快捷键）
├── bridge.py                 # AgentBridge —— AgentLoop ↔ GUI 异步数据桥
├── cli.py                    # Click 子命令 "heagent gui"（provider 构建 + 启动 app）
├── state.py                  # GuiState（Pydantic + reactive 全局状态）
│
├── screens/                  # 全屏页面
│   ├── chat.py               # ChatScreen —— 主聊天界面
│   ├── skills.py             # SkillScreen —— 技能管理
│   ├── cron.py               # CronScreen —— Cron 任务管理
│   ├── memory.py             # MemoryScreen —— 记忆/画像浏览
│   ├── runs.py               # RunsScreen —— 运行历史树
│   └── event_log.py          # EventLogScreen —— 引擎事件日志
│
├── widgets/                  # 可复用组件
│   ├── message_list.py       # MessageList —— 流式 Markdown 消息列表
│   ├── tool_card.py          # ToolCard —— 工具调用折叠卡片
│   ├── status_bar.py         # StatusBar —— 模型/Token/迭代状态
│   ├── event_log.py          # EventLog —— 引擎事件实时日志
│   └── input_area.py         # InputArea —— 多行输入 + 斜杠命令补全
│
└── tests/                    # GUI 测试（pytest + Textual 测试工具）
    ├── test_bridge.py
    ├── test_state.py
    └── ...
```

**依赖方向（冻结）**：

```
gui/  ──单向依赖──▶  agent/  engine/  providers/  tools/  memory/  cron/  context/
                        ⬆ 核心模块 **禁止** 导入 gui/
```

## 三、核心数据流（冻结）

### 3.1 用户输入 → Agent 回复

```
用户输入 "帮我分析 news.md"
       │
       ▼
InputArea (Textual Input widget)
       │  App.post_message(UserPrompt(text))
       ▼
ChatScreen.on_user_prompt()
       │  agent_task = asyncio.create_task(bridge.submit(prompt))
       ▼
AgentBridge.submit(prompt)
       │  async for event in loop.run_stream(prompt):
       │      app.post_message(StreamEventMessage(event))
       ▼
ChatScreen.on_stream_event(event)
       ├── event.type == "text"      → message_list.append_text(event.text)
       ├── event.type == "tool_call" → message_list.insert_tool_card(event.tool_call)
       ├── event.type == "tool_result" → message_list.update_tool_card(event.tool_result)
       └── event.type == "done"     → status_bar.idle(); input_area.enable()
```

### 3.2 引擎事件 → UI 更新

```
EngineContainer.events (EventBus)
       │  subscribe(GuiEventObserver)
       ▼
GuiEventObserver.handle(event)
       │  app.post_message(EngineEventMessage(event))
       ▼
StatusBar.on_engine_event(event)
       ├── "tool.started" → 显示活跃工具名
       ├── "iteration.end" → 更新迭代计数
       └── ...
EventLogScreen.on_engine_event(event)
       └── 追加到日志列表
```

### 3.3 页面导航

```
Footer 快捷键:
  F1 → ChatScreen         (聊天)
  F2 → SkillScreen        (技能)
  F3 → CronScreen         (Cron)
  F4 → MemoryScreen       (记忆)
  F5 → RunsScreen         (运行历史)
  F6 → EventLogScreen     (事件日志)
```

## 四、关键组件详解

### 4.1 AgentBridge（`bridge.py`）—— 核心胶水

```python
class AgentBridge:
    """桥接 AgentLoop 和 Textual App。

    职责：
    1. submit(prompt) — 提交用户输入，在 Worker 中消费 run_stream()
    2. 把 StreamEvent 转为 Textual Message 投递给 widget
    3. 订阅 EventBus 投递引擎事件到 UI
    4. cancel() — 取消当前 Agent 运行
    """

    def __init__(self, app: "HeAgentApp", loop: AgentLoop, event_bus: EventBus):
        self._app = app
        self._loop = loop
        self._current_task: asyncio.Task | None = None

        # 订阅引擎事件
        event_bus.subscribe(GuiEventObserver(app))

    async def submit(self, prompt: str) -> None:
        """在后台 Worker 中运行 AgentLoop.run_stream()。"""
        self._current_task = asyncio.current_task()
        try:
            async for event in self._loop.run_stream(prompt):
                self._app.post_message(StreamEventMessage(event))
        except asyncio.CancelledError:
            self._app.post_message(AgentInterrupted())
        finally:
            self._current_task = None

    def cancel(self) -> None:
        """中断当前 Agent 运行。"""
        if self._current_task:
            self._current_task.cancel()
```

**设计要点**：

- `submit()` 在 `asyncio.create_task()` 中运行（Textual Worker 机制），不阻塞 UI 主循环
- `post_message()` 是 Textual 的线程/协程安全投递接口——Worker → 主循环 → Widget
- `CancelledError` 经 `AgentLoop.run_stream()` 的 `finally` 块做 session 保存后传播，bridge 捕获并通知 UI

### 4.2 GuiState（`state.py`）

```python
from pydantic import BaseModel
from heagent.types import TokenUsage

class GuiState(BaseModel):
    """响应式全局状态（Pydantic 模型）。

    Textual 的 reactive 属性变化时自动触发绑定 widget 的 watch 方法。
    """
    model_name: str = ""           # 当前 LLM 模型名
    iteration: int = 0             # 当前迭代轮数
    max_iterations: int = 50       # 最大迭代数
    token_usage: TokenUsage = TokenUsage()  # 累计 Token
    is_running: bool = False       # Agent 是否正在执行
    active_tool: str = ""          # 当前活跃工具（空=无）
    last_error: str | None = None  # 最近错误信息
```

**为什么用 Pydantic 而非纯 Textual reactive**：与项目统一的类型体系一致；可直接从 `AgentLoop.last_usage` 等现有接口赋值。

### 4.3 MessageList（`widgets/message_list.py`）

基于 Textual `RichLog` widget：

- `write(text)` —— 流式追加 Markdown 文本（Textual 原生支持增量 Markdown 渲染）
- `insert_tool_card(call)` —— 在当前位置插入折叠卡片 widget
- `update_tool_card(call_id, result)` —— 更新工具卡片状态和结果
- `clear()` —— 清空消息列表

**工具卡片实现**：自定义 Textual `Widget`，含标题栏（图标 + 工具名 + 状态 + 耗时）和可折叠内容区（参数 + 结果）。使用 `Collapsible` 容器。

### 4.4 管理面板数据流

```
SkillScreen
  ├── 读取：SkillStore 实例（来自 AgentLoop._skills）
  ├── 创建：调用 skill_create 工具（经 ToolRegistry）
  ├── 编辑：调用 skill_update 工具
  └── 归档/删除：调用 skill_archive / skill_delete 工具

CronScreen
  ├── 读取：JobStore 实例（来自 agent._cron_store）
  ├── 添加：调用 cron_add 工具
  └── 删除：调用 cron_remove 工具

MemoryScreen
  ├── 读取：FactStore / ProfileStore 文件内容
  └── 只读展示（不提供编辑——编辑由 Agent 通过工具自主完成）
```

### 4.5 RunsScreen（运行历史树）

利用 `RunStore.build_run_tree()` 返回的嵌套结构，用 Textual `Tree` widget 渲染：

```python
# 伪代码
tree_data = RunStore().build_run_tree(limit=50)
for run in tree_data:
    node = tree.root.add(run["id"], label=f"{run['timestamp']} {run['prompt'][:40]}")
    for child in run.get("children", []):
        node.add(child["id"], label=f"{child['role']} {'✅' if child['ok'] else '❌'}")
```

选中节点时显示详情面板（原生消息/工具调用链/Token 使用）。

## 五、入口与启动流程（冻结）

### 5.1 CLI 入口（`cli.py`）

```python
# 改造 cli.py：现有 main 函数不变，新增 gui 子命令

@click.group()
def cli():
    """HeAgent CLI."""
    pass

@cli.command()
@click.argument("prompt", required=False)
# ... 现有参数 ...
def run(prompt, ...):
    """Run HeAgent in single-shot or interactive mode."""
    # 现有 main() 逻辑移入此处

@cli.command()
@click.option("--model", ...)
@click.option("--sandbox", ...)
def gui(model, sandbox, ...):
    """Launch HeAgent TUI."""
    from heagent.gui import gui_main
    asyncio.run(gui_main(model=model, sandbox=sandbox))
```

### 5.2 启动流程（`gui_main()`）

```
gui_main(model, sandbox)
  │
  ├── 加载 Settings（与 CLI 一致）
  ├── _build_provider()（复用 cli.py 的 Provider 构建逻辑）
  ├── 初始化 SkillStore / FactStore / ProfileStore / SoulStore / JobStore / EngineContainer
  ├── 构建 AgentLoop（与 CLI 一致，但 session=None——TUI 自行管理会话）
  ├── 构建 AgentBridge(app, loop, engine.events)
  ├── 创建 HeAgentApp(bridge, state) —— Textual App 实例
  └── app.run() —— 进入 Textual 事件循环（阻塞直到用户退出）
```

**与 CLI 的关键差异**：

| 维度 | CLI 交互模式 | GUI 模式 |
|------|-------------|---------|
| 会话管理 | `SessionStore`（自动保存/恢复） | 暂不持久化会话（Phase 1-4），后续可加 |
| Cron 调度 | `CronScheduler` 后台运行 | 同（Phase 3 接入） |
| MCP 生命周期 | `async with MCPClientManager` | 同（启动时加载，退出时卸载） |
| 事件循环 | `asyncio.run()` 桥接 click | Textual 原生 asyncio 事件循环 |
| 退出 | `Ctrl+C` / 空输入 | `Ctrl+Q` 或 Footer 退出按钮 |

## 六、集成点（不改动的现有接口）

| 现有接口 | GUI 使用方式 |
|----------|-------------|
| `AgentLoop.run_stream(prompt)` | 流式对话数据源 |
| `EventBus` / `EngineEvent` | 引擎事件 → UI 状态更新 |
| `RunStore.build_run_tree()` | 运行历史树数据源 |
| `SkillStore` / `FactStore` / `ProfileStore` / `JobStore` | 管理面板数据源 |
| `ToolRegistry` | 管理面板通过工具调用执行 CRUD |
| `_build_provider()` / `_build_loop()` | 复用 CLI 的 Provider/Loop 构建逻辑 |
| `SwitchableProvider.switch()` | `/model` 斜杠命令 |

## 七、测试策略

| 测试层级 | 覆盖内容 | 工具 |
|----------|----------|------|
| 单元测试 | `GuiState`、`AgentBridge`（mock AgentLoop）、`ToolCard` 渲染逻辑 | pytest + pytest-asyncio |
| 集成测试 | `AgentBridge` + 真实 StubProvider（模拟 StreamEvent 序列） | pytest + StubProvider |
| 组件测试 | Widget 的 `compose()` / `watch_*` 行为 | Textual `pilot`（内置测试工具） |
| E2E 测试 | 完整 TUI 启动 + prompt 输入 + 响应渲染 | Textual `pilot` |

**Textual pilot 示例**：

```python
async def test_chat_flow():
    app = HeAgentApp(bridge=MockBridge(), state=GuiState())
    async with app.run_test() as pilot:
        await pilot.click("#input")
        await pilot.press("hello", "enter")
        # 等待 Agent 响应渲染
        await pilot.wait_for_animation()
        assert "hello" in app.query_one("#message-list").text
```

## 八、架构决策日志

| ID | 决策 | 理由 | 日期 |
|----|------|------|------|
| AD1 | `bridge.py` 通过 `asyncio.create_task` 跑 Agent，不阻塞 UI | Textual 的 Worker 机制天然支持；CLI 已验证 `run_stream()` 可被 cancel | 2026-07-23 |
| AD2 | 管理面板直接调 `skill_create` 等工具而非直接写文件 | 复用工具层的一致语义（参数校验、SafetyGuard、事件发布）；避免管理面板绕开工具层直接操作存储 | 2026-07-23 |
| AD3 | 重用 `cli.py` 的 `_build_provider()` 逻辑 | 避免 Provider 构建逻辑分叉；extract 为共享 `_providers.py` 或在 `gui/cli.py` 中 import | 2026-07-23 |
| AD4 | 会话暂不持久化 | Phase 1-4 聚焦交互体验；会话持久化可在后续周期加 | 2026-07-23 |
| AD5 | 状态栏用 `reactive` 而非轮询 EventBus | Textual reactive 是声明式，widget 自动响应变化，代码量更少 | 2026-07-23 |
