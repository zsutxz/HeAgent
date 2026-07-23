# Story 25-2: 流式聊天引擎（bridge + 核心交互）

> Epic 25: 流式聊天（最小可跑）
> 状态: ready-for-dev
> 依赖: 24-1（项目骨架）
> 估时: 1-1.5 天

## 目标

实现 GUI 的核心数据流：用户输入 → `AgentBridge` 消费 `AgentLoop.run_stream()` → 流式文本显示在消息列表。这是 GUI 的"心跳"——后续所有功能都基于这条路径。

## AC（验收条件）

### AC1: AgentBridge
- [ ] `gui/bridge.py` — `AgentBridge` 类：
  - `__init__(app, loop, event_bus)` 注入依赖
  - `submit(prompt)` 是 async 方法，在后台消费 `loop.run_stream(prompt)`
  - 每个 `StreamEvent` 经 `app.post_message()` 投递给主循环
  - `cancel()` 取消当前运行的 task
- [ ] `submit()` 内的 `asyncio.CancelledError` 被捕获并投递 `AgentInterrupted` 消息

### AC2: GuiState
- [ ] `gui/state.py` — `GuiState(BaseModel)`，字段：
  - `model_name: str`（默认 `""`）
  - `iteration: int`（默认 `0`）
  - `max_iterations: int`（默认 `50`）
  - `token_usage: TokenUsage`（默认 `TokenUsage()`）
  - `is_running: bool`（默认 `False`）

### AC3: 消息列表（MessageList）
- [ ] `gui/widgets/message_list.py` — `MessageList(RichLog)` widget
- [ ] `append_text(text: str)` 方法——追加文本（供流式场景逐块调用）
- [ ] `new_message(role: str)` 方法——开始新消息块（带角色前缀）
- [ ] 用户消息前缀 `> `（绿色），Agent 消息前缀 `🤖 `（蓝色）——CSS class 区分
- [ ] `clear()` 清空全部消息

### AC4: 输入区域（InputArea）
- [ ] `gui/widgets/input_area.py` — `InputArea` widget（水平布局）
- [ ] 包含 `Input` widget（占大部分宽度）+ `Button("发送")` 
- [ ] Enter 或点击发送按钮 → 触发 `Submitted(text)` message
- [ ] `disable()` / `enable()` 控制输入状态

### AC5: 状态栏（StatusBar）
- [ ] `gui/widgets/status_bar.py` — `StatusBar(Static)` widget
- [ ] 初始显示：`模型: - | tokens: 0 in + 0 out | iter 0/50`
- [ ] 监听 `GuiState` 变化自动更新（通过 `watch_*` 或 message）

### AC6: ChatScreen 集成
- [ ] `gui/screens/chat.py` — ChatScreen 完整布局：
  - 上部：MessageList（占据主要空间）
  - 下部：InputArea
  - 底部：StatusBar
- [ ] 用户提交 prompt → 创建后台 task 调用 `bridge.submit()`
- [ ] 收到 `StreamEventMessage` → MessageList 追加文本
- [ ] Agent 完成后 StatusBar 更新 Token + 迭代数，InputArea 恢复

### AC7: 端到端可跑
- [ ] `heagent gui` 启动 → 显示聊天界面
- [ ] 输入 "hello" → Agent 流式回复 → 文本出现在消息列表
- [ ] Token 计数在 Agent 完成后显示在状态栏

### AC8: 测试
- [ ] `tests/gui/test_bridge.py`：Mock AgentLoop → `submit()` → 验证 `post_message` 被调用
- [ ] `tests/gui/test_state.py`：GuiState 字段默认值校验

## 实现要点

1. **gui_main() 升级**：在 24-1 的空壳中注入真实的 Provider 构建 + AgentLoop 创建（复用 `cli.py` 的 `_build_provider()` 和 `_build_loop()` 逻辑）。

2. **Provider 构建逻辑提取**：`cli.py` 中的 `_build_provider()` / `_build_key_rotated()` / `_build_openai_providers()` / `_build_anthropic_providers()` / `_build_soul()` / `_build_loop()` 被 `cli.py`（run 命令）和 `gui/cli.py`（gui 命令）共同使用。有两种方案：
   - **方案 A（推荐）**：提取到 `src/heagent/_bootstrap.py`，`cli.py` 和 `gui/cli.py` 各自 import
   - **方案 B**：`gui/cli.py` 直接 `from heagent.cli import _build_provider, _build_loop`
   
   方案 A 更干净但涉及移动现有代码；方案 B 最小改动。选 A——移动后 `cli.py` import 路径更新，语义等价。

3. **StreamEventMessage**：
```python
@dataclass
class StreamEventMessage:
    """从 bridge 投递到主循环的 StreamEvent 包装。"""
    event: StreamEvent
```

4. **Agent 执行策略**：`ChatScreen` 中用 `self.run_worker(bridge.submit(prompt), exclusive=True)` —— `exclusive=True` 确保同一时间只有一个 Agent 在运行。

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/_bootstrap.py` | **新建** | 提取 Provider/Loop 构建逻辑 |
| `src/heagent/cli.py` | **修改** | `from _bootstrap import ...` 替换本地函数 |
| `src/heagent/gui/__init__.py` | 修改 | `gui_main()` 实际初始化 |
| `src/heagent/gui/app.py` | 修改 | 注入 bridge/state |
| `src/heagent/gui/bridge.py` | **新建** | AgentBridge |
| `src/heagent/gui/state.py` | **新建** | GuiState |
| `src/heagent/gui/cli.py` | 修改 | Provider 构建 + 启动 |
| `src/heagent/gui/screens/chat.py` | 修改 | 完整 ChatScreen |
| `src/heagent/gui/widgets/message_list.py` | **新建** | MessageList |
| `src/heagent/gui/widgets/input_area.py` | **新建** | InputArea |
| `src/heagent/gui/widgets/status_bar.py` | **新建** | StatusBar |
| `tests/gui/__init__.py` | **新建** | |
| `tests/gui/test_bridge.py` | **新建** | bridge 单元测试 |
| `tests/gui/test_state.py` | **新建** | state 单元测试 |

## 不在此 Story 范围

- Markdown 渲染（24-3）
- 工具调用卡片（25-1）
- 斜杠命令（25-2）
