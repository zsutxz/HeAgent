# Repository Guidelines

## 项目结构

- `src/heagent/`：Python 包源码。主要模块包括 `agent/`（编排）、`providers/`（LLM 适配与容错）、`tools/`（工具与 MCP）、`engine/`（策略、执行与审计）、`context/`、`events/`（事件流）、`memory/`、`cron/`、`network/`（TCP/HTTP 传输层）、`goal/` 与 `gui/`；入口层为 `cli*.py` / `wiring.py`。
- `tests/`：pytest 测试，按功能平铺；provider 相关测试位于 `tests/providers/`。
- `docs/`：架构与开发文档；`docs/frame.md` 是实现架构的权威说明。
- `_bmad-output/`：规划和 story 产物；运行时状态通常写入 `.heagent/`，不要提交生成文件或密钥。

## 构建、测试与本地运行

```bash
pip install -e ".[dev]"       # 可编辑安装及开发依赖
pytest                         # 默认跳过 integration、benchmark
pytest -m integration          # 显式运行外部依赖集成测试
pytest tests/test_config.py    # 运行单个测试文件
pytest tests/test_config.py::test_default_settings -v  # 运行单个测试
ruff check src tests           # lint
ruff format src tests          # 格式化
mypy src                       # 严格类型检查
python -m heagent "你的提示"   # 单次 CLI
python -m heagent              # 交互式 CLI
```

异步测试由 `pytest-asyncio` 自动模式驱动。集成测试可能需要网络或凭证，默认不纳入基础测试；修改 provider、MCP 或外部服务适配时，应显式运行对应标记并说明环境前提。

## 编码规范

使用 Python 3.11+、4 空格缩进和 120 列行宽；格式化与检查以 `ruff.toml` 为准。模块、函数和文件使用 `snake_case`，类使用 `PascalCase`。库代码保持异步，不使用同步 I/O；跨模块数据使用 `types.py` 中的 Pydantic 模型，避免裸字典。日志使用 `logging.getLogger(__name__)`。工具执行链必须保持 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler。

## 测试要求

测试文件命名为 `test_*.py`，测试函数命名为 `test_<behavior>`。新增或修改逻辑必须补充能验证意图的测试；agent loop 使用 `StubProvider`，涉及配置的测试调用 `reset_settings()`。提交前至少运行相关测试、`ruff check` 和 `mypy`；覆盖率门槛为 87%。

## 提交与 Pull Request

提交信息使用中文，并采用清晰的 Conventional Commit 前缀，例如 `feat(provider): 增加模型回退`、`fix(tools): 修复路径校验`。PR 应说明问题、实现方案、测试命令和兼容性影响；涉及 CLI 或 GUI 交互时附截图或录屏，并关联 issue。保持 PR 聚焦，避免混入无关重构。提交前确认工作树干净，必要时记录已知限制、回滚方式和后续工作。

## 安全与配置

从 `.env.example` 复制 `.env`，密钥只放环境变量，严禁提交 `.env`、token 或个人状态文件。`SafetyGuard`、`PolicyEngine` 和内置 sandbox 都是 defense-in-depth，不是真正的安全边界；处理不可信输入、shell 或 MCP server 时，必须在容器、VM 或 OS 级沙箱中运行，并收紧文件系统和网络权限。修改 `agent/`、`providers/`、`tools/` 或 `engine/` 前先阅读 `docs/frame.md`。

## 架构与文档导航

依赖方向为 `exceptions/types/config/persist/roles/frontmatter/safe_logging → providers/tools/context → engine → agent → 入口层（cli* / wiring / gui / goal）`；新增 provider 或工具不得反向导入 `agent`，MCP 工具必须经 `ToolRegistry` 注入；`network/` 是传输叶子，不得导入运行栈与配置（可执行的依赖断言见 `tests/test_architecture_contracts.py`）。跨模块接口优先查看 `src/heagent/types.py` 和 `docs/frame.md`，产品设计见 `docs/design.md`，迭代流程见 `docs/iteration.md`。参考其他 agent 项目时要适配 HeAgent 的 asyncio 与模块化结构，不要直接复制同步单文件实现。
