---
id: 48-3
title: AgentLoop 请求适配与 CLI 接线
status: ready-for-dev
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

- [ ] 在 `src/heagent/cli.py` 注册 `tcp-server` 子命令及基础参数。
- [ ] 提取或复用入口层装配 helper，避免复制 `_build_provider`/Engine/Memory 初始化。
- [ ] 构造 `TcpRequestHandler`，调用 `AgentLoop.run(request.prompt)`。
- [ ] 对 `BudgetExceeded`、`HeAgentError`、Provider 异常和未知异常做稳定映射。
- [ ] 保持 `CancelledError` 传播。
- [ ] 在成功响应中至少返回 id/result；model/usage 作为可选字段。
- [ ] 新增 `tests/test_tcp_agent_integration.py`，使用 `StubProvider`。
- [ ] 新增或扩展 CLI 测试，覆盖 help、默认参数和普通 CLI 不监听。

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
