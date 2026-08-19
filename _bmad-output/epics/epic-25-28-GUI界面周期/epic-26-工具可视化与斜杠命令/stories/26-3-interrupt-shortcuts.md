# Story 26-3: 中断与快捷键

> Epic 26: 工具可视化 + 斜杠命令
> 状态: ready-for-dev
> 依赖: 24-2（流式聊天引擎）
> 估时: 0.5 天

## 目标

支持 `Ctrl+C` 中断 Agent、`Ctrl+L` 清屏等快捷键，确保中断后 UI 正确恢复。

## AC（验收条件）

### AC1: Ctrl+C 中断 Agent
- [ ] Agent 执行期间按 `Ctrl+C` → `bridge.cancel()` 被调用
- [ ] Agent 的 `asyncio.Task` 被 cancel → `CancelledError` 传播
- [ ] MessageList 末尾追加 `[已中断]` 提示（灰色文字）
- [ ] InputArea 恢复可用，可立即发送新 prompt

### AC2: Ctrl+L 清屏
- [ ] 聊天页面按 `Ctrl+L` → MessageList.clear()
- [ ] 不影响其他页面状态

### AC3: Esc 取消输入
- [ ] 输入框有内容时按 `Escape` → 清空输入框
- [ ] 输入框为空时 `Escape` 不做任何事

### AC4: BINDINGS 声明
- [ ] `ChatScreen.BINDINGS` 声明以上快捷键，Footer 自动显示

### AC5: 测试
- [ ] `tests/gui/test_bridge.py`：cancel() → CancelledError 传播 + 消息投递验证
- [ ] `tests/gui/test_chat.py`（Textual pilot）：模拟 `Ctrl+C` → 验证 UI 恢复

## 实现要点

1. **BINDINGS 放在 ChatScreen**：
   ```python
   BINDINGS = [
       Binding("ctrl+c", "interrupt", "中断", priority=True),
       Binding("ctrl+l", "clear_screen", "清屏"),
       Binding("escape", "cancel_input", "取消", key_display="Esc"),
   ]
   ```
2. **priority=True** 确保 Ctrl+C 在 Input 焦点时也生效（Textual 默认 Input 吞掉 ctrl+c）

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/gui/screens/chat.py` | 修改 | BINDINGS + action 方法 |
| `src/heagent/gui/bridge.py` | 修改 | cancel() 增强 |
| `tests/gui/test_chat.py` | **新建** | Textual pilot 测试 |
| `tests/gui/test_bridge.py` | 修改 | cancel 路径测试 |
