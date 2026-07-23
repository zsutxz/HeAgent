# Story 27-3: 运行详情与恢复

> Epic 27: 可观测性
> 状态: ready-for-dev
> 依赖: 27-2（运行历史面板）
> 估时: 1 天

## 目标

从运行树中选择某次运行查看详情（prompt、结果、工具调用链），并对未完成的运行提供"恢复运行"功能。

## AC（验收条件）

### AC1: 运行详情面板
- [ ] 选中运行树节点 → 右侧或弹窗显示详情面板
- [ ] 详情内容：
  - 完整 prompt（可滚动）
  - 最终回答（或错误信息）
  - 迭代数 + Token 使用量
  - 子任务列表（如有）
  - 工具调用链摘要（如有）

### AC2: 详情数据源
- [ ] 从 `RunStore` 加载 `RunSnapshot`（异步）
- [ ] 详情面板内容完整可滚动（长文本不截断）

### AC3: 恢复运行
- [ ] 未完成的运行（status != COMPLETED）详情面板显示 [恢复运行] 按钮
- [ ] 点击 → 切换到聊天页面 → 调用 `AgentLoop.resume(run_id)` 继续执行
- [ ] 恢复期间状态栏显示 `[resume: {run_id[:8]}]`
- [ ] 恢复完成后运行树自动刷新

### AC4: 过滤
- [ ] 顶部过滤栏：全部 / 已完成 / 未完成 / 失败，点击过滤运行树
- [ ] 默认显示"全部"

### AC5: 错误处理
- [ ] 恢复的 run_id 不存在时显示错误提示
- [ ] `resume()` 失败时显示错误消息

### AC6: 测试
- [ ] `tests/gui/test_runs_screen.py`：详情加载、过滤、恢复流程

## 实现要点

1. **详情展示方式**：推荐用 `Screen` 内的水平分割——左侧 Tree、右侧详情 `RichLog`。比弹窗更好——用户可以同时看树和详情。
2. **resume 集成**：`resume()` 是 AgentLoop 的方法，需要在聊天页面创建一个独立的 AgentLoop 实例或重用现有实例。策略：`AgentBridge` 增加 `resume(run_id)` 方法。
3. **过滤实现**：维护一个 `_filter_status` 变量，`_load_tree()` 时过滤 `RunStatus`。

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/gui/screens/runs.py` | 修改 | 详情面板 + 过滤 + 恢复 |
| `src/heagent/gui/bridge.py` | 修改 | 新增 `resume()` 方法 |
| `src/heagent/gui/screens/chat.py` | 修改 | 支持 resume 模式 |
| `tests/gui/test_runs_screen.py` | 修改 | 详情 + 恢复测试 |
