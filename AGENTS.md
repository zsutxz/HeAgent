# Repository Guidelines

## 项目结构

- `src/heagent/`：Python 包源码。最底层是公共层 `pub/`（`exceptions`/`types`/`safe_logging`/`persist`/`frontmatter`/`roles`/`workspace`/`task_shutdown`/`projects`，零运行栈依赖，任何层可依赖）与配置面 `config/`（`__init__.py` 承载 Settings + `catalog` 来源求解 + `write` 写通道 + `envfile` 保真读写）；其余模块包括 `agent/`（编排）、`providers/`（LLM 适配与容错）、`tools/`（工具与 MCP）、`engine/`（策略、执行与审计）、`context/`、`events/`（事件流）、`memory/`、`cron/`、`network/`（TCP/HTTP 传输层）、`goal/` 与 `gui/`；入口层为 `cli/` 包（`console.py` 命令层 / `composition.py` 装配 / `interactive.py` 交互执行 / `init.py` / `goal.py` / `http.py` / `http_console.py` / `tcp.py` / `dialogs.py` / `display.py` / `wiring.py` 组合根）。
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

使用 Python 3.11+、4 空格缩进和 120 列行宽；格式化与检查以 `ruff.toml` 为准。模块、函数和文件使用 `snake_case`，类使用 `PascalCase`。库代码保持异步，不使用同步 I/O；跨模块数据使用 `pub/types.py` 中的 Pydantic 模型，避免裸字典。日志使用 `logging.getLogger(__name__)`。工具执行链必须保持 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler。

## 测试要求

测试文件命名为 `test_*.py`，测试函数命名为 `test_<behavior>`。新增或修改逻辑必须补充能验证意图的测试；agent loop 使用 `StubProvider`，涉及配置的测试调用 `reset_settings()`。提交前至少运行相关测试、`ruff check` 和 `mypy`；覆盖率门槛为 87%。

## 提交与 Pull Request

提交信息使用中文，并采用清晰的 Conventional Commit 前缀，例如 `feat(provider): 增加模型回退`、`fix(tools): 修复路径校验`。PR 应说明问题、实现方案、测试命令和兼容性影响；涉及 CLI 或 GUI 交互时附截图或录屏，并关联 issue。保持 PR 聚焦，避免混入无关重构。提交前确认工作树干净，必要时记录已知限制、回滚方式和后续工作。

## 安全与配置

从 `.env.example` 复制 `.env`，密钥只放环境变量，严禁提交 `.env`、token 或个人状态文件。`SafetyGuard`、`PolicyEngine` 和内置 sandbox 都是 defense-in-depth，不是真正的安全边界；处理不可信输入、shell 或 MCP server 时，必须在容器、VM 或 OS 级沙箱中运行，并收紧文件系统和网络权限。修改 `agent/`、`providers/`、`tools/` 或 `engine/` 前先阅读 `docs/frame.md`。

## 架构与文档导航

依赖方向为 `pub/（exceptions/types/safe_logging/persist/frontmatter/roles/workspace/task_shutdown）→ config/（Settings・catalog・write・envfile）→ providers/tools/context → engine → agent → 入口层（cli / gui / goal）`；新增 provider 或工具不得反向导入 `agent`，MCP 工具必须经 `ToolRegistry` 注入；`network/` 是传输叶子，不得导入运行栈与配置（可执行的依赖断言见 `tests/test_architecture_contracts.py`）。跨模块接口优先查看 `src/heagent/pub/types.py` 和 `docs/frame.md`，产品设计见 `docs/design.md`，迭代流程见 `docs/iteration.md`。参考其他 agent 项目时要适配 HeAgent 的 asyncio 与模块化结构，不要直接复制同步单文件实现。

## 新增扩展点

新增 Provider / Tool / Skill 包时按下面走；通用前置（不反向导入 `agent/`、跨模块数据用
`pub/types.py` 的 Pydantic 模型、业务执行只读构造期配置快照）见上文与 `CLAUDE.md`。改完跑
`pytest tests/test_architecture_contracts.py -q`——新增边界必须同步维护该文件。

**Provider（`providers/`）**：实现 `providers/base.BaseProvider` 协议三件（`send` / `stream` /
`get_metadata`；最小参考 `tests/test_agent_loop.py::StubProvider`）。OpenAI 兼容端点复用
`providers/openai.py` 只加配置；新协议在 `providers/` 下新建模块（流式 `usage` / `tool_calls` 的末块
补全别漏，先例 `providers/anthropic.py`）；容错按职责挂 `chain.py`（跨 provider 回退）或
`key_rotation.py`（多密钥轮换）；中间件实现 `agent/middleware.MiddlewareFn` 经
`AgentLoop(middlewares=[...])` 注入。测试放 `tests/providers/`（agent loop 交互一律 `StubProvider`，
不打真实 API）；新增配置项同步 `.env.example` 与 `docs/frame.md` 4.10。

**Tool（`tools/builtins/`）**：新建模块，用 `@tool(read_only=...)` 装饰 async 函数，并挂到
`tools/builtins/__init__.py`（import 即注册）。治理面由 `engine/policy.py` 自动裁决（`read_only=True`
⇒ `readOnlyHint=True` 可放行；有副作用者考虑 `SANDBOX_TOOL_PROFILES` 档位或审批）。文件读写必须经
`tools/path_safety` 围栏（`resolve_workspace_path` / `open_text_under_root`；`os.open` 有 AST 白名单），
拉起子进程复用 `tools/sandbox/process.py` 的 `reap_subprocess` / `cap_channel` / `scrub_sensitive_env`。
「作用对象」摘要由 `tools/call_summary.summarize_tool_call` 单点生成。测试 `tests/test_<tool>.py`
（monkeypatch 的内部函数必须与调用方同模块）；`docs/frame.md` 4.4 的表追加一行。

**Skill 包（`.heagent/skills/<package-id>/`）**：`SKILL.md` 必需（frontmatter 含 `canonical_id` 等），
工作流包再加 `workflow.md`（`## Step NN` 从 1 连续；`role:` 指向存在的包，缺失硬失败不降级），
`templates/` / `references/` / `assets/` / `scripts/` 经 `SkillPackage.read_template` 等类型化读取。
声明契约：`input:` 只能引用 CLI 注入键（`user intent` / `user responses` / `existing project context`）
或前序步骤 `output:`，否则该步 BLOCKED；`validation: section: <标题>` 由 `WorkflowRunner` 机械校验；
`required_resources` 声明必需模板（缺失在加载期失败）。导入外部包走 `memory/skill_importer.py`。
测试 `tests/test_skill_packages.py` / `tests/test_workflow_resources.py` /
`tests/test_skill_packages_toctou.py`，技能文件禁止裸 `read_text` / `open`（AST 契约钉死）；包行为
变更改包声明，运行时进度与恢复语义见 `docs/frame.md` 4.13。
