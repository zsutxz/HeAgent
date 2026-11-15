# Story 28-2: 运行历史面板

> Epic 28: 可观测性
> 状态: ready-for-dev
> 依赖: 24-2（RunStore 可用）、26-1（页面导航）
> 估时: 1 天

## 目标

树形展示运行历史（supervisor → sub-agent 层级），利用 `RunStore.build_run_tree()` 作数据源。

## AC（验收条件）

### AC1: 运行树渲染
- [ ] `RunsScreen` 使用 Textual `Tree` widget
- [ ] 根节点：supervisor run，label 格式 `[{time}] {run_id[:8]} {prompt[:40]}... {status_icon}`
- [ ] 子节点：sub-agent run，label 格式 `{role} {status_icon} {iterations} iter`
- [ ] 状态图标：✅ COMPLETED / ❌ FAILED / ⏳ RUNNING / ⬜ 其他
- [ ] 数据源：`RunStore().build_run_tree(limit=50)`（异步读取）

### AC2: 刷新
- [ ] [刷新] 按钮或 `F5` 快捷键重新加载运行树
- [ ] 新 Agent 运行完成后运行树自动刷新（可监听 EventBus 的 `run.completed` 事件）

### AC3: 空状态
- [ ] 无运行记录时显示："暂无运行记录，开始聊天后将自动记录"

### AC4: 测试
- [ ] `tests/gui/test_runs_screen.py`：Mock RunStore → Tree widget 渲染验证

## 实现要点

1. **异步加载**：`RunStore` 操作是 async 的，`on_mount` 中用 `self.run_worker(self._load_tree())`。
2. **Tree widget API**：
   ```python
   tree = self.query_one(Tree)
   for run in tree_data:
       root_node = tree.root.add(label, expand=True)
       for child in run.get("children", []):
           root_node.add_leaf(child_label)
   ```

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/gui/screens/runs.py` | 修改 | 完整 RunsScreen |
| `src/heagent/gui/app.py` | 修改 | 注入 RunStore |
| `tests/gui/test_runs_screen.py` | **新建** | 运行树测试 |
