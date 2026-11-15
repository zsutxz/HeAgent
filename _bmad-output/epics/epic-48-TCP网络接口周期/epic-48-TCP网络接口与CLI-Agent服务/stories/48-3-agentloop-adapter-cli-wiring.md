---
id: 48-3
title: AgentLoop 请求适配与 CLI 接线
status: done
parent_epic: E48
priority: P0
depends_on: [48-2]
created: '2026-09-22'
---

# Story 48-3：AgentLoop 请求适配与 CLI 接线

## 用户故事

作为 HeAgent 使用者，我希望通过 `heagent tcp-server` 启动服务，使合法 TCP prompt 走与现有 CLI 相同的 AgentLoop、Provider 和 Engine 治理链，并把最终答案返回客户端。

## 范围

- 新增 Click 子命令 `tcp-server`。
- 复用现有 Provider/Engine/AgentLoop 装配路径。
- 建立 `TcpRequest` 到 `AgentLoop.run(prompt)` 的适配 handler。
- 将最终答案、可选模型/usage 映射为协议响应。
- Provider/Agent 异常转为稳定 `agent_error`。
- 普通 CLI、交互 CLI、GUI 和 `/goal` 行为不变。

## 边界与约束

**Always**

- TCP handler 只把 `prompt` 作为用户输入。
- 现有工具执行链保持 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler。
- 组合根复用现有 wiring，不复制 Provider 构造分支。
- 保留 `heagent.cli` 的既有 monkeypatch/import seam。
- 启动消息写 stderr/log，TCP 响应只走 socket。

**Never**

- 不从请求读取 system、provider、model、tool policy、sandbox 或 max_iterations。
- 不让 network 层导入 CLI 或 Provider。
- 不直接调用 Provider SDK。
- 不在普通 `heagent` 启动时隐式监听端口。

## 关键设计问题

实现前必须用测试或源码证据确认 AgentLoop 实例是否允许并发 `run()`：

- 若可并发复用：服务级 loop + 请求级 RunContext/状态隔离。
- 若不可并发复用：组合根提供请求级 loop factory，或在 48-4 的 semaphore 内采用串行保护。
- 禁止未经验证就共享含 `last_usage`、`active_tool`、session 等可变展示态的单个实例。

## 任务

- [x] 在 `src/heagent/cli.py` 注册 `tcp-server` 子命令及基础参数。
- [x] 提取或复用入口层装配 helper，避免复制 `_build_provider`/Engine/Memory 初始化。
- [x] 构造 `TcpRequestHandler`，调用 `AgentLoop.run(request.prompt)`。
- [x] 对 `BudgetExceeded`、`HeAgentError`、Provider 异常和未知异常做稳定映射。
- [x] 保持 `CancelledError` 传播。
- [x] 在成功响应中至少返回 id/result；model/usage 作为可选字段。
- [x] 新增 `tests/test_tcp_agent_integration.py`，使用 `StubProvider`。
- [x] 新增或扩展 CLI 测试，覆盖 help、默认参数和普通 CLI 不监听。

## 验收标准

- Given `tcp-server` 使用 StubProvider，when 客户端发送合法 prompt，then 响应 id/result 正确。
- Given AgentLoop 产生工具调用，when 请求处理，then 工具仍通过现有 Engine 执行链而非网络层直调。
- Given AgentLoop/Provider 抛已知异常，when handler 捕获，then 客户端收到 `agent_error` 且服务继续。
- Given服务被取消，when handler 正在等待 AgentLoop，then 取消信号不被包装为 `agent_error`。
- Given 普通单次/交互 CLI，when 启动，then 不创建 TCP listener。
- Given 两个并发请求，when 运行，then prompt、结果和 request id 不互相污染；若架构选择不并发共享 loop，则行为由限额明确串行化。

## Definition of Done

- `heagent tcp-server --help` 可用。
- StubProvider 端到端测试通过，无真实凭据。
- 无 Provider 装配复制实现。
- CLI 既有测试和架构契约通过。
- 文档中的 handler/组合根边界与实现一致。

## 代码地图

- `src/heagent/cli.py`：Click 命令和入口生命周期。
- `src/heagent/wiring.py`：仅在需要共享 Agent 运行时装配时调整。
- `src/heagent/agent/loop.py`：只使用公开接口，不加 TCP 分支。
- `src/heagent/network/tcp_server.py`：接受注入 handler。
- `tests/test_tcp_agent_integration.py`：StubProvider E2E。
- `tests/test_cli.py` / `tests/test_cli_provider_build.py`：CLI 回归与 seam。

## 验证命令

```text
pytest tests/test_tcp_agent_integration.py tests/test_cli.py tests/test_cli_provider_build.py -q
ruff check src tests
ruff format --check src tests
mypy src --platform linux
```

## Verification

**Commands and results (2026-09-22, 本机 UTC+8 + 干净 Linux 检出)：**

- `pytest tests/test_cli_tcp.py tests/test_tcp_agent_integration.py tests/network tests/test_architecture_contracts.py tests/test_agent_loop.py tests/test_cli.py tests/test_cli_provider_build.py -q` → **185 passed**
- 全量 `pytest -q --cov=heagent --cov-fail-under=87` → **2120 passed / 9 skipped / 18 deselected，覆盖率 90.93%**（门限 87%）
- 干净 Linux 检出（`git clone --depth 1` + `git apply` 本次改动 + `uv venv --python 3.12` + `uv pip install -e ".[dev]"`，无 `.env`、无本地状态）→ **185 passed**（定向）与 **2107 passed / 17 skipped**（全量，CI 等价口径）
- `ruff check src tests` → **All checks passed**；`ruff format --check src tests` → **244 files already formatted**
- `mypy src --platform linux` → **Success: no issues found in 134 source files**

**Implemented：**

- `src/heagent/cli_tcp.py`（新，入口层）：`TcpAgentHandler`（`TcpRequest` → 一次 `AgentLoop.run` 的适配器）、`build_server_config`、`_serve_tcp`、`tcp_server_cmd`（`--host/--port/--model/--system/--max-iterations/--soul/--sandbox`）。
- `src/heagent/cli.py`：尾部注册 `main.add_command(tcp_server_cmd)`（仅新增，不动既有 seam）。
- `src/heagent/network/protocol.py`：`success_response` 增加可选 `usage`（保持既有调用点行为不变）。
- `src/heagent/agent/loop.py` + `agent/context_runtime.py`：新增并发安全的 `AgentLoop.last_model`（见下）。
- 测试：`tests/test_cli_tcp.py`（8 例）、`tests/test_tcp_agent_integration.py`（9 例，真实 loopback + StubProvider）、`tests/network/test_protocol.py`（+1 例 usage 元数据）、`tests/test_agent_loop.py`（+1 例 `last_model` 漏斗）、`tests/test_architecture_contracts.py`（+network 反向依赖断言 + 3 例导入形态断言）。

**关键设计决策（含证据）：**

1. **每请求一个 `AgentLoop`（不共享实例）**：实例持有 `last_usage` / `last_iteration` / `cumulative_tokens` / `active_tool` / `tool_activity` / 暂停 `Event` 等跨 run 可变态；共享单实例并发时会互相覆盖。handler 共享 `provider` / `engine` / 记忆存储（构造便宜、以只读为主），每请求经 `cli._build_loop`（复用装配，不复制）新建 loop，`session=None`（请求间无对话状态）。回归证据：`test_concurrent_requests_keep_their_own_result_and_usage` 断言两个并发请求各持不同 loop 实例且 result/usage 不串。
2. **响应 `model` 只取本请求的运行记录**：复审发现（Critical）原实现经 `active_model()` 读**共享** `RoutingProvider.last_decision`（实例级最近一次决策）——并发时慢请求会读到快请求的档位，把自己的模型名写错。现改为 `AgentLoop.last_model`（由 provider 响应在 `append_assistant_message` 漏斗回填，run / run_stream 两条路径共用）。回归证据：`test_concurrent_routed_requests_report_their_own_model`（真实 `RoutingProvider` + 两档 StubProvider，修复前实测 fast 请求回报 `pro-model`，修复后各自正确）。
3. **不装交互式审批处理器**：`cli._prepare_engine` 在 TTY 下装 `ConsoleApprovalHandler`（读服务进程 stdin）；网络入口无人应答，装了会把请求挂死。故直接 `EngineContainer.default(...)`（`approval_handler=None`）：需要审批的调用维持既有 fail-safe 语义（等同阻断）。测试断言 `handler.engine.approval_handler is None`。
4. **启动失败显性且干净**：绑定失败（端口占用 / 地址不可用）经 `except OSError → click.ClickException` 报一行可诊断文案，绝不打印「已监听」，也不吐 traceback（48-2 的启动语义 + CLI UX）。
5. **`usage` 只在采集到时下发**：`loop.last_usage` 为 `None` 时不发明数字（`TcpResponse.exclude_none` 省略字段）。
6. **网络入口零反向依赖**：`tests/test_architecture_contracts.py` 新增 `network` 包断言（运行期不得导入 agent/engine/providers/tools/memory/context/cron/events 与全部入口层模块），并把 `heagent.cli_tcp` 加入入口层集合。

**Critical review fixes（对抗式评审发现并已修）：**

1. 并发请求的 `model` 串味（见决策 2）：`_resolve_model(provider)` → `_resolve_model(loop)`，并新增 `AgentLoop.last_model`；修复前有实测复现（两个并发请求中快请求被回报为慢请求的档位）。
2. 反向依赖断言存在形式绕过：`from heagent import providers`（子模块名在 alias 上）此前不被识别，新增的 network 断言因此可绕。已把 `_imports` 抽为可测内核 `_module_imports`，两种写法同等识别，并只认**真实存在的子包名**（避免 Windows 大小写不敏感把 `from heagent import Agent` 误判成 `heagent/agent`）。新增 3 例断言（正向识别 / 不误伤包根符号 / network 规则生效）。

**Deviation / 已知边界（有意为之或留给后续 Story）：**

- **审批网关**：TCP 入口无交互审批（决策 3），需要审批的工具调用按 fail-safe 阻断；「网络入口要不要提供非交互审批策略」属 Story 48-5 的安全边界。
- **非 loopback 告警**：`--host` 允许非回环值，但「非 loopback 显示无认证/TLS 告警」是 Story 48-5 的范围（本 Story 只把默认值钉为 `127.0.0.1`、help 文案说明不支持公网）。
- **并发上限**：本 Story 只做请求级隔离，连接数/在途并发/超时限额由 Story 48-4 收口（当前受 48-2 的 `max_connections=32` 约束，无在途 Agent 限额）。
- **MCP 生命周期未接入**：`tcp-server` 不进入 `cli._mcp_lifecycle`，故 `.mcp.json` 的 server 不连接、MCP 工具在该入口不可用（客户端会看到 `Unknown tool: <server>__<tool>`）。MCP 连接即「运行不可信外部代码」，是否在网络入口自动连接属安全决策 → 留给 Story 48-5/48-6 显式定调（当前为**刻意不接**，非遗漏）。
- **cron 工具语义与 CLI 单次模式一致**：`session=None` 时仍会构造 `JobStore` 并把 cron 工具绑定进 loop，因此 TCP 请求可以落盘 cron job（由后续 CLI/dream 进程执行）——这与 `heagent "..."` 单次模式同形，是有意的能力对等，不是本 Story 的偏差。
- **`--max-iterations 0` 回落到设置默认值**：与既有 `run --max-iterations` 同形（`max_iterations or settings.max_iterations`），为保持一致未单独加固。
- **文档**：README / `.env.example` / `docs/frame.md` / CLAUDE.md 的 network 与 `tcp-server` 条目按 Sprint Plan 属 Story 48-6（交付收口）范围，本 Story 未改。

## Review Status

实现、对抗式评审（独立子代理）与定向验证均已通过；评审发现的 1 条 Critical（并发 `model` 串味）已修并补回归测试，2 条 Warning（架构断言可绕过 / `--max-iterations 0`）分别「已修」与「有意与 CLI 同形」处置。状态为 `done`。未提交 Git。
