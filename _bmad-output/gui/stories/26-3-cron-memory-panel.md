# Story 26-3: Cron + 记忆面板

> Epic 26: 管理面板
> 状态: ready-for-dev
> 依赖: 26-1（页面导航）
> 估时: 1 天

## 目标

Cron 任务管理面板（表格增删）和记忆/画像查看面板（只读 Markdown 展示）。

## AC（验收条件）

### AC1: Cron 任务列表
- [ ] `CronScreen` 含 `DataTable`，列：prompt（截断 40 字符）/ schedule / 状态（enabled/disabled）/ 上次执行
- [ ] 数据源：`JobStore`（从 agent 注入）
- [ ] 排序：按创建时间

### AC2: Cron 操作
- [ ] [添加任务] → Modal：prompt（必填）/ schedule（必填，cron 表达式）/ recurring（开关）
- [ ] 提交 → 调用 `cron_add` 工具 → 刷新列表
- [ ] 选中任务 → [删除] → 确认弹窗 → `cron_remove` → 刷新列表
- [ ] 操作反馈（通知）

### AC3: 记忆面板
- [ ] `MemoryScreen` 使用 `TabbedContent` 或 `ContentSwitcher` 切换两个 Tab：
  - "事实记忆" Tab → Markdown 渲染 `.heagent/memory/MEMORY.md`
  - "用户画像" Tab → Markdown 渲染 `.heagent/user/USER.md`
- [ ] 内容为只读展示（无编辑功能）
- [ ] 文件不存在时显示友好提示："暂无记忆" / "暂无画像"

### AC4: 测试
- [ ] `tests/gui/test_cron_screen.py`：列表渲染、增删操作
- [ ] `tests/gui/test_memory_screen.py`：Tab 切换、内容渲染

## 实现要点

1. **Cron 操作同技能面板——直接调 handler**，不走 Agent。
2. **记忆文件读取**：`FactStore` / `ProfileStore` 直接读文件，非异步操作。

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/gui/screens/cron.py` | 修改 | 完整 CronScreen |
| `src/heagent/gui/screens/memory.py` | 修改 | 完整 MemoryScreen |
| `src/heagent/gui/app.py` | 修改 | 注入 JobStore / FactStore / ProfileStore |
| `tests/gui/test_cron_screen.py` | **新建** | Cron 面板测试 |
| `tests/gui/test_memory_screen.py` | **新建** | 记忆面板测试 |
