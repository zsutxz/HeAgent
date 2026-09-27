# Repository Guidelines

## 项目结构

- `src/heagent/`：Python 3.11+ 源码。`pub/` 是零运行栈依赖的公共层；`config/` 管理配置来源与写入；`providers/`、`tools/`、`context/`、`engine/`、`agent/` 依次承担适配、工具、上下文、治理和编排。
- `cli/`、`gui/`、`goal/` 是入口层；`network/` 是只依赖标准库、Pydantic 和 `pub` 的传输叶子。
- `tests/` 为 pytest 测试（provider 测试在 `tests/providers/`）；`docs/frame.md` 是实现架构的权威说明，`docs/design.md` 和 `docs/iteration.md` 分别说明产品设计与迭代流程。
- `.heagent/`、`_bmad-output/`、日志和本地状态属于运行或规划产物，不要提交密钥、`.env` 或生成文件。

## 构建、测试与开发

```bash
pip install -e ".[dev]"                 # 可编辑安装
pytest                                  # 默认跳过 integration/benchmark
pytest tests/test_config.py             # 单文件
pytest -m integration                   # 需要网络或凭证
ruff check src tests && ruff format src tests
mypy src
python -m heagent "提示"                # 单次 CLI
python -m heagent                       # 交互式 CLI
```

提交前运行相关测试、`ruff check` 和 `mypy`；覆盖率门槛为 87%。异步测试由 `pytest-asyncio` 自动驱动。

## 编码与架构约定

使用 4 空格缩进、120 列；模块、函数和文件用 `snake_case`，类用 `PascalCase`。保持库代码异步，跨模块数据使用 `pub/types.py` 的 Pydantic 模型，日志使用 `logging.getLogger(__name__)`。

依赖方向为 `pub → config → providers/tools/context → engine → agent → cli/gui/goal`。下层不得反向导入入口层；`network/` 不得导入运行栈。工具执行必须经过 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler。

## 扩展与测试

- Provider 实现 `send`、`stream`、`get_metadata`；测试使用 `StubProvider`，不要调用真实 API。
- Tool 放在 `tools/builtins/`，使用 `@tool(read_only=...)`，文件路径经 `tools/path_safety` 校验，并在 `builtins/__init__.py` 注册。
- Skill 包必须包含带 frontmatter 的 `SKILL.md`；工作流资源使用 `SkillPackage` 类型化读取。新增边界后运行 `pytest tests/test_architecture_contracts.py -q`。

修改 `agent/`、`providers/`、`tools/` 或 `engine/` 前先阅读 `docs/frame.md`。详细安全边界和 MCP 风险见 `CLAUDE.md`：SafetyGuard、PolicyEngine 和内置 sandbox 都不是 OS 级安全边界，不可信输入或 MCP server 必须在容器、VM 或 firejail 中运行。

## 提交与 Pull Request

提交信息使用中文 Conventional Commit，例如 `feat(provider): 增加模型回退`。PR 应说明问题、方案、测试命令和兼容性影响；涉及 CLI/GUI 时附截图或录屏并关联 issue，保持变更聚焦。
