# Story 27-2: 技能管理面板

> Epic 27: 管理面板
> 状态: ready-for-dev
> 依赖: 26-1（页面导航）、24-2（需要 ToolRegistry 可调工具）
> 估时: 1-1.5 天

## 目标

技能管理面板：DataTable 展示所有技能，支持查看详情、新建、归档、删除。操作通过已有的 `skill_*` 工具执行。

## AC（验收条件）

### AC1: 技能列表
- [ ] `SkillScreen` 含 `DataTable`，列：名称 / tags / 使用次数 / 最后使用
- [ ] 数据源：`SkillStore`（从 `AgentLoop._skills` 获取）
- [ ] 过期技能（超 `stale_days` 天未使用）行显示 ⚠️ 前缀
- [ ] 排序：默认按使用次数降序

### AC2: 技能操作
- [ ] 选中行 + 底部按钮：[查看详情] [归档] [删除]
- [ ] 查看详情 → 弹出 Modal 或切换详情面板，Markdown 渲染 SKILL.md 内容
- [ ] 归档 → 确认弹窗 → 调用 `skill_archive` → 刷新列表
- [ ] 删除 → 确认弹窗 → 调用 `skill_delete` → 刷新列表

### AC3: 新建技能
- [ ] [新建技能] 按钮 → 弹窗含字段：name、description、pattern、steps、tags
- [ ] 提交 → 调用 `skill_create` 工具 → 刷新列表
- [ ] 必填字段（name、pattern）为空时不允许提交

### AC4: 操作反馈
- [ ] 操作成功后屏幕底部短暂显示绿色通知（`notify()`）
- [ ] 操作失败后显示红色错误消息

### AC5: 测试
- [ ] `tests/gui/test_skills_screen.py`：DataTable 渲染、操作流程

## 实现要点

1. **直接调 ToolRegistry 而非走 Agent**：管理面板的 CRUD 操作不需要 LLM 参与——直接 `ToolRegistry.get_handler("skill_create")` 调 handler。这样更快且不消耗 Token。
2. **Modal 弹窗**：Textual `ModalScreen` 子类，含 `Input` 字段 + `Button`。
3. **列表刷新**：操作完成后重新读 `SkillStore` → 更新 DataTable。

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/gui/screens/skills.py` | 修改 | 完整 SkillScreen |
| `src/heagent/gui/app.py` | 修改 | 注入 SkillStore 引用 |
| `tests/gui/test_skills_screen.py` | **新建** | 技能面板测试 |
