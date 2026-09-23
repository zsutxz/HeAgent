---
id: 49-2
title: 默认 CLI 自动启动与生命周期
status: done
parent_epic: E49
priority: P0
depends_on: [49-1]
created: '2026-09-23'
---

# Story 49-2：默认 CLI 自动启动与生命周期

## 用户故事

作为 HeAgent 用户，我希望正常启动 CLI 时网页入口自动可用，以便不必额外维护一个 HTTP 后台命令。

## 范围

- 在默认 CLI 交互模式中自动启动 HTTP 服务。
- 在默认 CLI 单次模式中让 HTTP 服务与一次性 Agent run 共存，并在 run 结束后关闭。
- 识别显式子命令，避免 `gui`、`tcp-server`、`http-server`、`init`、`replay` 重复启动 HTTP。
- 统一处理 HTTP 启动失败、Ctrl+C、取消和服务关闭。
- 保留显式 `heagent http-server` 的独立启动语义。

## 边界与约束

**Always**

- HTTP 服务与默认 CLI 使用同一进程和 asyncio 生命周期管理。
- 启动失败显式传播，不能静默跳过网页入口。
- 关闭时有界等待并释放 listener、订阅和在途 HTTP 任务。
- 默认 CLI 的 Provider、Agent、工具治理和现有输出语义保持不变。

**Never**

- 不让 `gui`、`tcp-server` 或 `http-server` 再自动派生第二个 HTTP 实例。
- 不把 HTTP server 放入后台 daemon，使 CLI 退出后继续监听。
- 不把端口冲突降级为仅打印 warning 后继续运行。
- 不将 HTTP 会话与 CLI 终端会话错误地共享同一个可变 `AgentLoop`。

## 任务

- [x] 抽取可复用的 HTTP server 生命周期上下文/任务管理器。
- [x] 接入 `_run_cli_impl` 的交互与单次路径。
- [x] 增加显式子命令排除/注册边界，保持 Click 命令解析兼容。
- [x] 实现启动失败、取消信号和有界关闭的错误与资源语义。
- [x] 增加 CLI 启动矩阵和端口冲突回归测试。

## 验收标准

- Given 用户执行 `heagent` 进入交互模式，When CLI 初始化完成，Then HTTP 服务在同一 asyncio 生命周期内启动，stderr 显示本地访问地址，REPL 与网页入口可以同时存活。
- Given 用户执行 `heagent "prompt"` 或 `heagent run "prompt"`，When 单次 Agent 运行开始，Then HTTP 服务已可用；When 单次运行结束或失败，Then HTTP 服务随 CLI 生命周期关闭并释放端口。
- Given 用户执行 `heagent gui`、`heagent tcp-server`、`heagent http-server`、`heagent init` 或 `heagent replay`，When 子命令启动，Then 不额外自动创建第二个 HTTP 服务实例。
- Given 默认 CLI 自动启动 HTTP 服务时绑定失败，When CLI 初始化，Then 命令显式失败，不继续进入看似正常的聊天状态，也不遗留 Provider、任务或 socket 资源。
- Given 用户发送 Ctrl+C 或 CLI 收到取消信号，When 进程退出，Then HTTP listener、SSE 订阅和在途 HTTP 任务按有界超时收尾。

## Definition of Done

- `_run_cli_impl` 的默认路径和 HTTP 服务生命周期在同一个 asyncio 管理边界内。
- 交互、单次和显式子命令的启动矩阵有测试覆盖。
- 端口冲突、初始化异常、取消和关闭路径不吞错、不泄漏资源。
- 现有 CLI/TCP/GUI 测试保持通过。

## 代码地图

- `src/heagent/cli.py`：默认 CLI 生命周期接入点。
- `src/heagent/cli_http.py`：HTTP 入口装配与服务上下文。
- `src/heagent/network/http_server.py`：listener、关闭和任务收尾。
- `tests/test_cli_http_lifecycle.py`：默认/显式子命令和异常路径。
- `tests/test_cli.py`：既有 CLI 回归。

## Review Status

**已实现并验证（2026-09-23）。** 范围与验收标准实现前确认；实现后按「意图级」核对。

### 实现记录

| 变更 | 说明 |
| --- | --- |
| `src/heagent/cli_http.py` | 新增 `EmbeddedHttpService`（内嵌服务生命周期：`start` / `close` / `failure` / async CM）、`build_http_service(settings)`、`embedded_http_error_message(exc)`（把 `HttpStartupError` / `HttpDependencyError` 转成命令级文案）；新增 `_safe_log`（生命周期日志故障不影响行为） |
| `src/heagent/cli.py` | 新增 `_embedded_http_service(settings)`（async CM，函数内导入 `build_http_service` 以保留测试缝）与 `_run_with_embedded_http(factory)`（`asyncio.run` + HTTP 启动失败 → `ClickException`，exit 1）；`_run_single` / `_run_chat` 的既有主体整段纳入 HTTP 生命周期（`_run_chat` 绑定 `http` 并在每轮 REPL 前检查 `http.failure`）；`_run_cli_impl` 两个分支改走 `_run_with_embedded_http` |
| `tests/conftest.py` | 新增 autouse 替身：默认把 `cli_http.build_http_service` 替换为只记录生命周期的 `_StubEmbeddedHttp`（否则每个 CLI 测试都会抢 8766 端口），并提供 `embedded_http_services` fixture；需要真实绑定者用 ``@pytest.mark.embedded_http_service`` opt-in |
| `pyproject.toml` | 注册 `embedded_http_service` 标记 |
| `tests/test_cli_http_lifecycle.py`（新增 12 例） | 单次模式「run 进行中 HTTP 可用 + 结束释放端口」、交互模式「REPL 与网页共存」、绑定失败（不进入 run、exit 1、无 traceback）、缺 extra 安装提示、run 抛异常也关闭、默认 CLI 经内嵌服务、serve 循环挂掉时交互模式如实报出并退出、显式子命令不派生、真实 `EmbeddedHttpService` 幂等关闭 |
| `tests/test_cli_http.py` | `test_plain_cli_never_creates_an_http_listener`（49-1 契约）替换为 `test_explicit_subcommand_paths_do_not_go_through_the_embedded_service` |
| `docs/frame.md` | 4.17 表新增「默认 CLI 自启动」行；调用链的 HTTP 段说明默认 CLI 内嵌启动与显式命令的差异 |

### 验证证据（本机 2026-09-23，Windows 3.13）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 定向测试 | `pytest tests/test_cli_http_lifecycle.py tests/test_cli_http.py tests/test_cli.py` | **76 passed** |
| 全量回归 + 覆盖率 | `pytest --cov=heagent --cov-fail-under=87` | **2368 passed, 9 skipped, 18 deselected；90.87%** |
| Lint / 格式 / 类型 | `ruff check`；`ruff format --check`（258 files）；`mypy src --platform linux` | 全部通过（140 source files） |
| 端到端冒烟 | 真实子进程 `python -m heagent`（随机 `HTTP_PORT`，stdin 关闭后退出） | stderr 公告 `[http] web UI: http://127.0.0.1:<port>`；**会话期间** `/api/health` = 200；退出码 0、无 traceback、端口立即可重绑（脚本 `.heagent/tmp/smoke_embedded_http.py`） |

### 偏差与边界（如实记录）

1. **HTTP 生命周期在 `_run_single` / `_run_chat` 内部，而不是 `_run_cli_impl` 外层**：这两个函数各自持有自己的 asyncio 主体，包在内层才能让服务与 REPL / run 真正并行；代价是「整体打桩这两个入口」会连带把 HTTP 启动打桩——第一版测试正是这样踩坑（fake 掉 `_run_single` 后服务没起，断言只看到 `ConnectError`），已改为**替换 provider**（`tests/test_cli_http_lifecycle.py` 顶部有说明）。
2. **测试默认替换内嵌服务为替身**（`tests/conftest.py` autouse）：真实绑定只在 12 个 opt-in 用例里发生。若将来新增依赖「默认 CLI 真的监听端口」的断言，必须带 `@pytest.mark.embedded_http_service`。
3. **`failure` 检查只在交互模式的每轮 REPL 前**：单次模式的 run 通常很短，serve 循环中途挂掉只会在关闭时记一条 ERROR（不做逐轮检查）；这条边界写在 `EmbeddedHttpService` docstring 里。
4. **默认 CLI 不新增 HTTP 选项**（brief：不做含糊的参数透传）：绑定地址与限额全部来自 `HTTP_*` 设置；需要覆盖请用显式 `heagent http-server`。
5. **Ctrl+C 的真实控制台行为**仍待 49-6 手工验收（自动化环境用 `CTRL_BREAK_EVENT` 只能验证「立即退出、端口释放、无 traceback」，见 49-1 的边界记录）。

## Requirement Traceability

FR1, FR2, FR9; NFR1, NFR4, NFR8, NFR9; UX-DR3, UX-DR6。
