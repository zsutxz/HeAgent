# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 本文件独立于 AGENTS.md（并行维护、不互为真源、不合并）——2026-11-12 裁定，再覆盖/合并即违规。

## 常用命令

```bash
pip install -e ".[dev]"                # 开发安装（Python ≥3.11；gui/http 另有 extras）

pytest                                 # 全量测试（自动跳过 integration/benchmark）
pytest tests/test_agent_loop.py::test_basic_run   # 单个用例
pytest --cov --cov-report=term-missing # 覆盖率（门限 87%；CI 口径）
# ⚠ 本地 Py3.13 的 --cov 有 pydantic-settings×coverage 兼容 bug，本地验证用不带 cov 的 pytest

ruff check src tests scripts           # 静态检查（CI lint 同参数；bandit 只认 # nosec）
ruff format --check src tests scripts
mypy src
bandit -r src/ -ll

python scripts/quality_gate.py         # 本地全门（冒烟+回归+lint+format+mypy+bandit，fail-fast）

# 门禁红了的第一步：干净 HEAD 副本复跑同批用例，判「环境产物 vs 回归」
python scripts/verify_baseline.py tests/test_cli_http_lifecycle.py -q
# 判读口径（VERDICT: environmental / REGRESSION / clean / inconclusive）见 docs/testing.md

heagent "写一个快速排序"               # 单次执行（python -m heagent 等价）
heagent                                # 交互模式（/provider 切 provider 条目、/model 钉路由池档位）
heagent init --project                 # 初始化项目配置
heagent gui                            # TUI（需 pip install -e ".[gui]"）
heagent http-server                    # HTTP 127.0.0.1:9101 + WS 127.0.0.1:9201（需 ".[http]"）
powershell scripts/start_heagent.ps1   # Windows 推荐：cwd 钉在仓库根再启动
# ⚠ 必须在仓库根启动：workspace_root = 进程 cwd，从盘根启动会把整盘挂进容器沙箱

mkdocs build --strict                  # CI 文档门：动 docs/ 后本地先 strict 构建（mkdocs 按需装）
```

## 架构骨架

单进程异步 Python 库，编排 LLM ↔ 工具执行循环。**架构权威 = `docs/frame.md`**（完整数据流/模块详解/调用链）——改 `agent/`、`providers/`、`tools/`、`engine/` 前先读它；门禁红了的分诊手册在 `docs/testing.md`；沙箱机制在 `docs/sandbox.md`。

```
依赖方向（下层禁止反向导入）：
pub/ → config/ → providers · tools · context → engine/ → agent/ → cli · gui · goal

旁支：memory、skills（对 engine 仅 TYPE_CHECKING）；events（运行期仅依赖 pub.exceptions）；
      cron（运行期依赖 engine）；network/（仅 stdlib+pydantic，被入口层单向使用）；
      web/（静态资源，零 heagent 导入，契约测试钉死）
```

核心模块：`agent/`（AgentLoop 主循环+middleware+子 Agent）、`providers/`（LLM provider+智能路由+容错）、`tools/`（@tool 注册+SafetyGuard+path_safety+沙箱后端）、`engine/`（PolicyEngine+ToolExecutor+store/ledger/observability）、`pub/`（异常/类型/日志/持久化）、`config/`（Settings）、`context/`（压缩/会话持久化）、`network/`（HTTP+SSE+WS 传输）。

**工具执行链固定**：`PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler。

## 硬约束

- 跨模块数据一律 Pydantic 模型（`pub/types.py`），禁止原始 dict（例外：`AgentState`/`SubAgentResult` 用 dataclass）
- 新增 provider / tool 禁止从 `agent/` 导入；`network/` 不得导入运行栈（agent/engine/providers/tools/memory/skills/context/cron/events）与配置；`network/ws_server.py` 不得导入 `network/http_server.py`（共享契约住 `http_protocol.py`）
- 改包间依赖后必须同步 `tests/test_architecture_contracts.py` 的 `FORBIDDEN_RUNTIME_IMPORTS` 并跑 `pytest tests/test_architecture_contracts.py -q`
- **monkeypatch 缝是搬移红线**：搬代码前先 grep patch 字符串路径（如 `heagent.cli.console._run_prompt`）
- `heagent/cli/__init__.py` 永不放 import（`test_cli_package_shell_stays_thin`）；子模块延迟导入必须指向实模块
- 全异步：库代码无同步 I/O，CLI 经 `asyncio.run()` 桥接；日志 `logging.getLogger(__name__)` 仅标准库
- Windows 开发机：subprocess `text=True` 必须显式 `encoding="utf-8"`，否则中文输出解码炸

## 扩展与测试

- Provider 实现 `send`/`stream`/`get_metadata`；测试用 `StubProvider`，不调真实 API；provider 测试放 `tests/providers/`
- 新 Tool 放 `tools/builtins/`：`@tool(read_only=...)`、路径经 `tools/path_safety` 校验、在 `builtins/__init__.py` 注册
- Skill 包必须有带 frontmatter 的 `SKILL.md`；异步测试由 `pytest-asyncio` 自动驱动
- 发版契约由 `tests/test_release_workflow_contract.py` 钉死：`__init__.__version__` == `pyproject.toml`（纯 semver）、`CHANGELOG.md` 保有 `## [Unreleased]` 节

## 安全口径

Canonical 在 `docs/frame.md` §4.19：`SafetyGuard`/`PolicyEngine`/sandbox 后端**均非真正安全边界**（三层非边界），OS 级容器沙箱兜底；本地模式（默认）HTTP/WS 无认证，对外模式（WS 绑非回环）强制 Bearer token 且缺 token 拒绝启动；**对外能提交 run 时强烈建议 `--sandbox docker`**。已知缺口台账：`_bmad-output/implementation-artifacts/deferred-work-archive.md`。

## Git

- 提交信息用**中文** Conventional Commit（`feat(provider): 增加模型回退`）
- **每次 `git commit` 前必须呈报提交信息与文件清单，获得明确同意后才执行**
- 提交前跑相关测试 + `ruff check` + `mypy`
