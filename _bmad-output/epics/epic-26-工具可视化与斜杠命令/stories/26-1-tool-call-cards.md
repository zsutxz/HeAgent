# Story 26-1: 工具调用卡片

> Epic 26: 工具可视化 + 斜杠命令
> 状态: ready-for-dev
> 依赖: 24-2（流式聊天引擎）
> 估时: 1-1.5 天

## 目标

Agent 调用工具时，在消息列表中插入可折叠的工具卡片，展示工具名、参数、状态（执行中/成功/失败）、耗时和执行结果。

## AC（验收条件）

### AC1: ToolCard widget
- [ ] `gui/widgets/tool_card.py` — `ToolCard(Static)` widget
- [ ] 初始状态（执行中）：折叠显示，标题栏 `🔧 {tool_name} (执行中...)`，黄色/灰色边框
- [ ] 完成状态：标题栏 `✅ {tool_name} (已完成, {duration}s)`，绿色边框
- [ ] 失败状态：标题栏 `❌ {tool_name} (失败)`，红色边框
- [ ] 展开后显示调用参数（JSON 格式化或键值对列表）
- [ ] 完成后展开区域追加执行结果（截断到 2000 字符，超出显示 `... (共 N 字符)`）

### AC2: 插入与更新
- [ ] 收到 `StreamEvent(type="tool_call")` → 在 MessageList 当前位置插入 ToolCard
- [ ] 卡片插入时自动滚动到可见区域
- [ ] 收到 `StreamEvent(type="tool_result")` → 按 `tool_call_id` 查找对应卡片并更新状态
- [ ] 多个并发工具调用 → 多个卡片插入，各自独立更新

### AC3: 交互
- [ ] 点击卡片标题栏 → 展开/折叠（toggle）
- [ ] 键盘导航：`Tab` 可聚焦到卡片，`Enter` 展开/折叠
- [ ] 卡片默认折叠（避免刷屏）

### AC4: 耗时计算
- [ ] `tool_call` 到达时记录时间戳
- [ ] `tool_result` 到达时计算差值，显示秒级耗时（如 `0.3s`、`2.1s`）

### AC5: 测试
- [ ] `tests/gui/test_tool_card.py`：创建卡片 → 验证初始状态 → 更新 → 验证完成状态
- [ ] `tests/gui/test_bridge.py`：模拟 `run_stream()` 产出 tool_call + tool_result event → 验证卡片插入和更新

## 实现要点

1. **卡片布局**（CSS）：
   - 使用 `Static` + 自定义 `compose()` 内部布局
   - 标题栏：水平布局 `[图标] [工具名] [状态] [耗时]`
   - 内容区：`Collapsible` 容器，内含 `RichLog` 或 `Static`

2. **tool_card_id 关联**：
   - 卡片以 `StreamEvent.tool_call.id` 为 key 存入 `ChatScreen` 的 dict
   - `tool_result.tool_call_id` 匹配后更新

3. **结果截断策略**：
   ```python
   MAX_RESULT_LENGTH = 2000
   if len(content) > MAX_RESULT_LENGTH:
       display = content[:MAX_RESULT_LENGTH] + f"\n... (共 {len(content)} 字符)"
   ```

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/gui/widgets/tool_card.py` | **新建** | ToolCard widget |
| `src/heagent/gui/screens/chat.py` | 修改 | tool_card 插入/更新逻辑 |
| `src/heagent/gui/bridge.py` | 修改 | tool_call/tool_result 事件分类投递 |
| `tests/gui/test_tool_card.py` | **新建** | ToolCard 单元测试 |
| `tests/gui/test_bridge.py` | 修改 | tool event 路径测试 |
