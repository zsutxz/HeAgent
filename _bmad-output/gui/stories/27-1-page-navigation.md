# Story 27-1: 页面导航系统

> Epic 27: 管理面板
> 状态: ready-for-dev
> 依赖: 24-2（流式聊天引擎）
> 估时: 0.5-1 天

## 目标

实现多页面导航：Footer 快捷键在聊天/技能/Cron/记忆/运行历史/事件日志间切换，页面状态独立保留。

## AC（验收条件）

### AC1: 多 Screen 注册
- [ ] `HeAgentApp` 维护所有 Screen 实例（懒加载或预创建）
- [ ] Screen 列表：`ChatScreen`、`SkillScreen`、`CronScreen`、`MemoryScreen`、`RunsScreen`、`EventLogScreen`
- [ ] 未实现的 Screen（Epic 27-28 的）用占位 Screen（`PlaceholderScreen(title)`）

### AC2: 导航快捷键
- [ ] Footer 显示：`F1 聊天 | F2 技能 | F3 Cron | F4 记忆 | F5 运行 | F6 日志`
- [ ] 按 F1-F6 切换到对应 Screen
- [ ] `Ctrl+Q` 始终可见（全局退出）

### AC3: 状态保持
- [ ] 切换页面后切回，聊天消息列表内容不丢失
- [ ] 切换页面后切回，输入框焦点自动恢复

### AC4: 当前页面指示
- [ ] Footer 中当前活跃页面高亮（如 `[F1 聊天]` vs `F2 技能`）

## 实现要点

1. **Screen 管理方式**：使用 `App.push_screen()` / `App.switch_screen()`。推荐 `switch_screen()` 适合 Tab 式导航——不会堆叠 Screen 栈。
2. **BINDINGS 放在 App 层**（全局），各 Screen 可覆盖自己的 BINDINGS。
3. **占位 Screen**：
   ```python
   class PlaceholderScreen(Screen):
       def compose(self):
           yield Static(f"[italic dim]{self._title} — 即将推出[/]")
   ```

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/gui/app.py` | 修改 | BINDINGS → Screen 切换 |
| `src/heagent/gui/screens/skills.py` | **新建** | 占位 |
| `src/heagent/gui/screens/cron.py` | **新建** | 占位 |
| `src/heagent/gui/screens/memory.py` | **新建** | 占位 |
| `src/heagent/gui/screens/runs.py` | **新建** | 占位 |
| `src/heagent/gui/screens/event_log.py` | **新建** | 占位 |
