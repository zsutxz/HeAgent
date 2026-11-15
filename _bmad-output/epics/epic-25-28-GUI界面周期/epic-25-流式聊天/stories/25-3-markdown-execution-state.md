# Story 25-3: Markdown 渲染与执行状态

> Epic 25: 流式聊天（最小可跑）
> 状态: ready-for-dev
> 依赖: 24-2（流式聊天引擎）
> 估时: 0.5-1 天

## 目标

完善聊天体验：Markdown 正确渲染、Agent 执行期间 UI 状态管理（输入禁用、运行指示）、异常处理。

## AC（验收条件）

### AC1: Markdown 渲染
- [ ] MessageList 使用 RichLog 的 `markup=True` + `write()` 渲染 Markdown
- [ ] 代码块（```）显示语法高亮（Textual 内置 Rich 的 Syntax 高亮）
- [ ] 列表（`-` / `1.`）正确缩进和编号
- [ ] 粗体（`**text**`）、斜体（`*text*`）、行内代码（`` `code` ``）正确渲染
- [ ] 链接（`[text](url)`）可识别但终端内不可点击（显示为 `text (url)`）

### AC2: 执行状态管理
- [ ] Agent 执行期间 `InputArea` 禁用：`Input` 变灰 + placeholder 显示 "Agent 运行中..."
- [ ] Agent 执行期间发送按钮禁用（灰色不可点击）
- [ ] Agent 完成后 `InputArea` 自动恢复可用
- [ ] 执行期间按 Enter 不触发新 prompt（输入已被禁用）

### AC3: 运行指示
- [ ] StatusBar 在 Agent 执行期间显示动态指示（如 `⏳ 运行中...` 或简单文字）
- [ ] Agent 完成后 StatusBar 恢复正常显示

### AC4: 异常处理
- [ ] `AgentBridge.submit()` 中 `HeAgentError` 被捕获 → 投递 `AgentErrorMessage`
- [ ] ChatScreen 收到 `AgentErrorMessage` → 在 MessageList 末尾显示红色错误消息
- [ ] 异常后 InputArea 恢复可用（用户可以重试）
- [ ] `BudgetExceeded` 显示友好提示："[已达到迭代上限]" 

### AC5: 测试
- [ ] `tests/gui/test_bridge.py`：模拟 `run_stream()` 抛异常 → 验证错误消息投递
- [ ] `tests/gui/test_state.py`：`is_running` 状态切换逻辑

## 实现要点

1. **Markdown 渲染**：`RichLog` 的 `write()` 方法原生支持 Rich markup。Textual 的 RichLog 默认 `markup=True`。但需要注意——流式场景下 Markdown 是逐块到达的，一段 Markdown 的中间截断可能导致渲染错误。策略：不做逐块 Markdown 解析——每个完整的 `text` chunk 原样追加，最终整体渲染由 RichLog 的累积缓冲区完成。

2. **执行状态流**：
   ```
   on_submit → state.is_running = True → InputArea.disable()
   run_stream 完成 → state.is_running = False → InputArea.enable() + StatusBar 更新
   run_stream 异常 → state.is_running = False → InputArea.enable() + 显示错误
   ```

3. **消息类型**：
   ```python
   @dataclass
   class AgentErrorMessage:
       error: str
   ```

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/gui/widgets/message_list.py` | 修改 | Markdown 渲染验证 |
| `src/heagent/gui/widgets/input_area.py` | 修改 | disable/enable + placeholder |
| `src/heagent/gui/widgets/status_bar.py` | 修改 | 运行指示 |
| `src/heagent/gui/bridge.py` | 修改 | 异常捕获 + 错误投递 |
| `src/heagent/gui/screens/chat.py` | 修改 | 错误消息展示 |
| `tests/gui/test_bridge.py` | 修改 | 异常路径测试 |
