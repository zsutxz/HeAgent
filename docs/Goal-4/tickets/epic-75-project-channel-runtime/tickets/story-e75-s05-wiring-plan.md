---
ticket: 5
title: E75-S05 · 装配注入：`build_ws_servers` 透传与两处注入
status: done
baseline_revision: 63cd3528
covers: [R6, R7]
---

## Story

`build_ws_servers` 新增 `project_service` 入参并原样透传到集合级端点与单 run 端点；`cli/http.py`
的两条装配路径（内嵌服务 / `http-server` 命令）都注入 `ProjectChannelAdapter`（同一个
`HttpProjectConsole` 实例 + 注册表健康探针），缺省 `None` 时行为逐字不变。

## Design Notes

- **票面与实测的偏差（1）**：`build_ws_servers` 并**不**直接调用
  `build_runs_collection_endpoint` / `build_ws_endpoint`——那两个构造函数住
  `network/ws_host.py::build_ws_app`（由 `WsServer.app` 延迟调用）。真实透传链路是
  `build_ws_servers → WsServer.__init__ → WsServer.app → build_ws_app → 两个端点构造`
  （见 `## Code Map`）。按票面字面接线只能得到一个「收下就丢」的形参，正是本 entry 要消灭的
  「静默缺项目通道」形态，因此按真实链路接线。
- **票面与实测的偏差（2）= write_set 溢出**：`network/ws_host.py` 的 `build_ws_app` 与
  `WsServer.__init__` 原本没有 `project_service` 缝，透传链路在 `network/` 侧断掉。本 entry 的
  write_set 只列了 `cli/http_config.py` / `cli/http.py` / `tests/test_cli_http_lifecycle.py`，
  **不够**。已做最小加点（`build_ws_app` + `WsServer.__init__` + `.app` 转发 + 两处端点构造
  各传 `project_service=project_service`，共 10 行，纯加性、默认 `None`）。溢出 1 个文件，须由
  orchestrator 追认或另立 entry（见 `## Gap`）。
- **「同一个实例」的两种读法**：`build_http_service`（内嵌）与 `http_server_cmd`
  （`http-server`）是**互斥的两条进程入口**，进程内不会同时跑，因此「两次 `build_ws_servers`
  调用收到同一对象」在物理上不成立。落实的口径是：
  1. 每条路径只建**一份** `HttpProjectConsole`（`_project_console` 是唯一构造点），HTTP 面与
     WS 面共用它 —— 否则两份注册表缓存 / 运行期缓存在配置写入后各自失效；
  2. 每条路径的**同一个适配器实例**同时进 listener 的两个端点构造点（集合级 + 单 run）。
     跨路径共享会需要进程级 console 单例，等于把写闸门与运行时缓存变成全局状态，不取。
- **缺省不改变行为**：`project_service` 全链默认 `None`；`None` 时 `WsServer.project_service`
  为 `None`，两个端点拿到的仍是 `None`（`invalid_request` 语义与 75.2 一致）。既有
  `build_ws_servers` 调用点（测试与非 cli 消费者）一个都没被迫改。
- **控制台构造上移**：`_http_listener_for` 原本就地建 console，现在接受可选的 `console=` 注入
  （`None` 时按同参数就地建，保留直接调用它的测试路径）；`HttpProjectConsole(...)` 的参数拼装
  抽到 `_project_console`，避免 HTTP 面与 WS 面各拼一份而参数漂移。
- **HTTP 关闭时**：console 仍会建（WS 项目通道独立于 HTTP listener 的装配开关），
  `_http_listener_for` 回 `None`，WS 侧照常注入 —— 这是刻意的：`WS_ENABLED` 与 `HTTP_ENABLED`
  是两个开关，项目通道属 WS 面能力。
- 探针 `lambda: console.registry.health().code`：`registry` 是 `HttpProjectConsole` 的公开属性，
  `health()` 是 75.1 的纯读探针，返回 `ok` / `unreadable` 两值。

## Code Map（透传链路逐跳）

1. `cli/http.py::build_http_service`（内嵌入口，原 `:449` 调用点）
   → `_project_console(...)` 建 console → `_http_listener_for(..., console=console)`（HTTP 面复用）
   → `build_ws_servers(..., project_service=_project_channel(console))`。
2. `cli/http.py::http_server_cmd`（原 `:789` 调用点）同形态：console 先建，再喂 `_http_listener_for`
   与 `build_ws_servers`。
3. `cli/http_config.py::build_ws_servers(project_service=...)`
   → `WsServer(..., project_service=project_service)`。
4. `network/ws_host.py::WsServer.__init__` → `self.project_service`；
   `WsServer.app` → `build_ws_app(..., project_service=self.project_service)`。
5. `network/ws_host.py::build_ws_app`
   → `build_runs_collection_endpoint(..., project_service=project_service)`（集合级，`readonly=False` 才注册）
   → `build_ws_endpoint(..., project_service=project_service)`（单 run，按协议忽略并记 debug）。
6. `network/ws_server.py::_handle_submit_commands` → `{"command":"projects"}` 走
   `_send_projects_frame(websocket, project_service)` 回 `WsFrameType.PROJECTS` 帧。

## Tasks & Acceptance

- [x] `build_ws_servers` 增 `project_service: Any | None = None` 并原样交给 `WsServer`。
- [x] `network/ws_host.py` 两处注入缝（`build_ws_app` / `WsServer`）+ `.app` 转发 + 两端点传参。
- [x] `cli/http.py`：`_project_console` 单构造点、`_project_channel` 适配器工厂、
      `_http_listener_for(console=...)` 复用、两条装配路径各注入一次。
- [x] `tests/test_cli_http_lifecycle.py` 三例 wiring 判据（见 Verification）。
- [ ] orchestrator 追认 `network/ws_host.py` 的 write_set 溢出（或另立 entry）。

## Verification

基线 `63cd3528`；全部用 `.heagent/tmp/py311-venv-linux/bin/python`。

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_cli_http_lifecycle.py -q` | **14 passed**（原 11 + 新 3），5.1 s |
| `pytest tests/test_cli_http_lifecycle.py -q -k project_channel` | **3 passed**, 11 deselected, 1.71 s |
| `pytest tests/network -q` | **706 passed**, 1 warning, 20.89 s |
| `pytest tests -q -k "cli_http or http_lifecycle"` | **65 passed**, 5799 deselected, 12.97 s |
| `pytest tests -q -k "ws or http"` | **1233 passed / 37 skipped**, 4594 deselected, 42.19 s |
| `pytest tests/test_architecture_contracts.py -q` | **40 passed**, 9.59 s |
| `ruff check src tests` | All checks passed! |
| `ruff format --check src tests` | 504 files already formatted |
| `mypy src` | Success: no issues found in 240 source files |

新增三例（`tests/test_cli_http_lifecycle.py`，`_record_ws_wiring` 记录 `build_ws_servers` 的
kwargs 与每次装配建出的 console）：

1. `test_embedded_entry_injects_the_project_channel`：`build_http_service` 恰一次装配、
   `project_service` 是 `ProjectChannelAdapter` 且非 `None`、console 恰 1 个且 `adapter._console is
   consoles[0]`、`service._http.console is consoles[0]`、`service._ws_servers[0].project_service is adapter`。
2. `test_http_server_command_injects_the_project_channel`：`CliRunner().invoke(main, ["http-server"])`
   （`_serve_web` / `_build_provider` 打桩，不真绑定）同样恰好一次注入、同一 console。
3. `test_project_channel_reaches_both_endpoints_of_the_listener`：在
   `network.ws_server.build_runs_collection_endpoint` / `build_ws_endpoint` 上记录 kwargs，取
   `WsServer.app` 触发装配 ⇒ 两个端点的 `project_service` 均 `is` 同一个 adapter（证明注入越过
   `build_ws_servers` 形参、到达端点构造点）。

**证据强度说明**：「真 listener + 向 `/api/runs/ws` 发 `{"command":"projects"}` 收 `PROJECTS` 帧」
未在本文件新增（成本高且易 flake，本文件其余用例已覆盖真 listener 生命周期）。端点级语义由
`tests/network/test_ws_project_commands.py`（端点直驱，含 `projects` 帧与 `registry_state`）与
`tests/test_ws_project_adapter.py` 覆盖；本 entry 补的是「端点之前那一跳的接线」。

## Gap

- **write_set 溢出（待追认）**：`src/heagent/network/ws_host.py` +10 行（`build_ws_app` /
  `WsServer.__init__` 各一个 `project_service=None` 形参、`self.project_service` 一行、`.app`
  转发一行、两处端点构造各一行）。没有这些，`build_ws_servers` 收到的 `project_service` 无处可去，
  entry 的 verify 第 2 层（注入到达端点）不可能成立。票面把端点构造误记在 `build_ws_servers` 名下，
  说明票面少切了一个 network 内部 entry。
- **跨路径同一对象不成立**（设计澄清，非缺陷）：两条装配路径互斥，各自建一份 console+adapter。
  判据改为「路径内一份 console、一份 adapter、两端点同一实例」。

## 宿主复核（2026-11-23，串行门禁）

- **写集溢出追认**：`src/heagent/network/ws_host.py`（+10 行，两形参 + `WsServer.project_service` + `.app` 转发 + 两处端点传参）。票面写的「`build_ws_servers` 直接透传给端点构造器」与实际链路不符——两个构造器由 `ws_host.build_ws_app` 在 `WsServer.app` 里延迟调用，不加这 10 行 `project_service` 会变成「收下却无处可用」的参数，正是本 entry 要消灭的形态。改动纯加性、默认 `None` ⇒ 既有调用点零改动。
- **口径澄清采纳**：两条装配路径（内嵌服务单元 / `http-server` 命令）是互斥入口，进程内不会同时跑 ⇒ 判据落实为「路径内一份 console、一份 adapter、两端点同一实例」，而非「跨路径同一对象」。
- `pytest tests/test_cli_http_lifecycle.py -q` → 14 passed（原 11 + 新 3）
- 宿主合成复跑 `tests/test_cli_http_lifecycle.py tests/test_cli_http.py tests/network tests/test_architecture_contracts.py tests/test_http_console_project_run.py tests/test_ws_project_adapter.py tests/test_project_registry_health.py tests/test_contract_baselines.py -q` → **848 passed, 1 warning**
- `ruff check` / `ruff format --check`（504 files）/ `mypy src`（240 files）全绿；`cli/http.py` 906 行、`ws_host.py` 625 行（上限 1000）
