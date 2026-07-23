# Story 28-1: 事件日志面板

> Epic 28: 可观测性
> 状态: ready-for-dev
> 依赖: 24-2（EngineContainer 和 EventBus 已注入）、26-1（页面导航）
> 估时: 0.5-1 天

## 目标

实时展示引擎事件流（工具调用、迭代结束等），支持暂停/恢复滚动和清空。

## AC（验收条件）

### AC1: 事件订阅与展示
- [ ] `EventLogScreen` 订阅 `EventBus`（经 `EngineContainer.events`）
- [ ] 每条事件格式：`[HH:MM:SS] {event_type} run={run_id[:8]} iter={n} tool={name} {details}`
- [ ] 使用 `RichLog` 追加显示，自动滚动到最新

### AC2: 交互
- [ ] `Space` 键暂停/恢复自动滚动（Footer 指示当前状态）
- [ ] `Ctrl+L` 清空事件日志

### AC3: 事件过滤
- [ ] 顶部输入框可输入关键词过滤（按 event_type 或 tool_name 匹配）
- [ ] 清空过滤关键词恢复显示全部事件

### AC4: 性能
- [ ] 事件日志保留最近 500 条（`RichLog.max_lines = 500`），超出自动丢弃旧条目
- [ ] 高频事件（如多个工具并发）不卡 UI

### AC5: 测试
- [ ] `tests/gui/test_event_log.py`：订阅 EventBus → emit → 验证追加

## 实现要点

1. **EventObserver 实现**：
   ```python
   class GuiEventObserver:
       def __init__(self, app):
           self._app = app
       def handle(self, event: EngineEvent):
           self._app.post_message(EngineEventMessage(event))
   ```
   注册时机：`HeAgentApp.on_mount()` 中 `self._engine.events.subscribe(observer)`。

2. **过滤逻辑**：在 `on_engine_event()` 中判断 `filter_text in event.event_type or filter_text in event.tool_name`。

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/gui/screens/event_log.py` | 修改 | 完整 EventLogScreen |
| `src/heagent/gui/app.py` | 修改 | 注入 EventBus + 注册 Observer |
| `src/heagent/gui/bridge.py` | 修改 | 提纯 Observer 类 |
| `tests/gui/test_event_log.py` | **新建** | 事件日志测试 |
