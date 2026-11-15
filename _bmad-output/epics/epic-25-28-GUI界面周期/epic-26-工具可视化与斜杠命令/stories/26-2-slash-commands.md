# Story 26-2: 斜杠命令

> Epic 26: 工具可视化 + 斜杠命令
> 状态: ready-for-dev
> 依赖: 24-2（流式聊天引擎）
> 估时: 1 天

## 目标

输入框支持 `/model`、`/mcp-prompt`、`/clear`、`/help` 等斜杠命令，行为对齐 CLI 交互模式的斜杠命令。

## AC（验收条件）

### AC1: 命令路由
- [ ] 输入框文本以 `/` 开头时，解析为斜杠命令而非 Agent prompt
- [ ] 支持的命令：`/model`、`/mcp-prompt`、`/clear`、`/help`
- [ ] 未知命令显示 `未知命令: /xxx，输入 /help 查看可用命令`

### AC2: /model 命令
- [ ] `/model` 无参数：列出所有 Provider（从 `SwitchableProvider.info()` 获取），当前活跃标记 `→`
- [ ] `/model <name>`：切换到指定 Provider，显示 `已切换到 {name} ({model})`
- [ ] 非 `SwitchableProvider` 时：显示 `仅一个 Provider 可用，无需切换`
- [ ] Tab 自动补全 Provider 名称（`Input` + `Suggester` 或自定义 `Completions`）

### AC3: /mcp-prompt 命令
- [ ] 行为对齐 `cli.py` 的 `_handle_mcp_prompt()`（list/render）
- [ ] 无 MCP 连接时显示 `无 MCP server 连接`

### AC4: /clear 和 /help
- [ ] `/clear`：清空 MessageList（等价 `Ctrl+L`）
- [ ] `/help`：显示 Markdown 格式的帮助文本（列出所有命令 + 快捷键）

### AC5: 测试
- [ ] `tests/gui/test_slash_commands.py`：各命令路由和输出验证

## 实现要点

1. **命令解析在 `InputArea` 中**：`on_input_submitted` 检测首字符 `/` → 分派到 `SlashCommandHandler`
2. **`SlashCommandHandler`**（可放 `gui/commands.py`）：纯函数 `handle(text, context) -> str`，返回响应文本
3. **`/model` 需要 Provider 引用**：通过 `GuiState` 或直接注入 `SwitchableProvider` 实例
4. **自动补全**：Textual `Input` 不支持原生 completions，用 `Suggester` API 或自定义 `AutoComplete` widget

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/gui/commands.py` | **新建** | SlashCommandHandler |
| `src/heagent/gui/widgets/input_area.py` | 修改 | 斜杠命令解析 + 补全 |
| `tests/gui/test_slash_commands.py` | **新建** | 命令测试 |
