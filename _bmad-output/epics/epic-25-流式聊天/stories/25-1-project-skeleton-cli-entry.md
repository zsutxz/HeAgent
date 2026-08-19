# Story 25-1: 项目骨架与 CLI 入口

> Epic 25: 流式聊天（最小可跑）
> 状态: ready-for-dev
> 依赖: 无
> 估时: 0.5-1 天

## 目标

搭建 `gui/` 包骨架、Textual App 空壳、`heagent gui` CLI 入口，并改造现有 `cli.py` 为 `click.Group` 支持子命令。到此阶段应能启动空白 TUI 并正常退出。

## AC（验收条件）

### AC1: 目录与包结构
- [ ] `src/heagent/gui/__init__.py` 存在，公开 `gui_main()` 函数签名
- [ ] `src/heagent/gui/app.py` 存在，含 `HeAgentApp(App)` 类
- [ ] `src/heagent/gui/cli.py` 存在，含 Click `gui` 子命令
- [ ] 目录 `src/heagent/gui/screens/` 和 `src/heagent/gui/widgets/` 存在（含各自 `__init__.py`）

### AC2: Textual App 空壳
- [ ] `HeAgentApp` 继承 `textual.app.App`
- [ ] 至少一个空 `Screen`（`ChatScreen`），含 Footer
- [ ] Footer 显示快捷键提示：`F1 Chat | Ctrl+Q Quit`
- [ ] 启动后显示 app title（`TITLE` 类变量或 CSS）

### AC3: CLI 子命令
- [ ] `src/heagent/cli.py` 改造：现有 `main()` 变为 `click.Group` 下的 `run` 子命令
- [ ] 新增 `gui` 子命令（`@cli.command()`），参数：`--model`、`--sandbox`
- [ ] `heagent gui` 调用 `gui_main()` → 创建 `HeAgentApp` → `app.run()`
- [ ] `heagent gui` 无 Textual 时给出友好错误："请安装: pip install heagent[gui]"

### AC4: 依赖声明
- [ ] `pyproject.toml` 新增：
  ```toml
  [project.optional-dependencies]
  gui = ["textual>=1.0,<2.0"]
  ```

### AC5: 向后兼容（核心验证）
- [ ] `heagent "prompt"` 行为与改造前完全一致（CLI 单次执行模式）
- [ ] `heagent` 无参数行为与改造前完全一致（CLI 交互模式）
- [ ] 现有 922 测试全量通过

## 实现要点

1. **`cli.py` 改造方式**：将现有 `main()` 函数体重命名为 `run` 命令的回调；`@click.group()` 作为新顶层；`run` 和 `gui` 为子命令。`--model`/`--system`/`--max-iterations`/`--soul`/`--sandbox` 等参数原样保留在 `run` 子命令上。

2. **`gui_main()` 最小实现**：
```python
# __init__.py
def gui_main(model: str | None = None, sandbox: str | None = None) -> None:
    """Launch the HeAgent TUI."""
    from heagent.gui.app import HeAgentApp
    app = HeAgentApp()
    app.run()
```

3. **`HeAgentApp` 最小实现**：
```python
# app.py
from textual.app import App, ComposeResult
from textual.widgets import Footer
from heagent.gui.screens.chat import ChatScreen

class HeAgentApp(App):
    TITLE = "HeAgent"
    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def on_mount(self) -> None:
        self.push_screen(ChatScreen())

    def compose(self) -> ComposeResult:
        yield Footer()
```

4. **不做的**：Provider 构建、AgentLoop 初始化、任何实际功能——这些属于 24-2。

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/heagent/gui/__init__.py` | 新建 | `gui_main()` |
| `src/heagent/gui/app.py` | 新建 | `HeAgentApp` |
| `src/heagent/gui/cli.py` | 新建 | Click `gui` 子命令定义 |
| `src/heagent/gui/screens/__init__.py` | 新建 | 空 |
| `src/heagent/gui/screens/chat.py` | 新建 | `ChatScreen` 空壳 |
| `src/heagent/gui/widgets/__init__.py` | 新建 | 空 |
| `src/heagent/cli.py` | 修改 | 重构为 `click.Group` |
| `pyproject.toml` | 修改 | 新增 `[gui]` optional dep |

## 不在此 Story 范围

- Provider 构建或 AgentLoop 初始化
- 任何 UI 组件（消息列表、输入框、状态栏）
- MCP 生命周期集成
- 测试（在 24-2 和 24-3 中随功能加）
