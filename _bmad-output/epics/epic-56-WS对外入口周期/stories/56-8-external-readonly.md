---
title: '56-8 对外 listener 只读旁观'
type: 'feature'
created: '2026-10-24'
status: 'done'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: 'bab1dc5c0f6e23f9eb397a6aaf1711803cdf9bc9'
context: []
---

<!-- 来源：epic-56 retro 期二 P2-A3（用户 2026-10-24 裁定「三条都要做」）。 -->

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 期二 D2 冻结「对外 listener 可提交 run」，双监听因此只有一种对外姿态：给了 token 的人既能看也能下命令
（提交 run、取消 run）。真实场景里常见「只给同事看进度、不给下命令」——没有这个开关时，唯一的办法是不给 token，
连看都不行。

**Approach:** 新增 listener 级开关 `readonly`（入口层暴露为 `WS_EXTERNAL_READONLY`，默认 **关**）：
只读 listener **不注册**提交端点 `/api/runs/ws`；已订阅连接上的 `cancel` 回 `invalid_request` 且**不断连**
（事件流照常、运行不受影响）；`ping` 正常。默认关 = 保持期二已交付语义，开启是显式收紧动作。

## Boundaries & Constraints

**Always:**
- 只读是**路由级 + 命令级**，不是「注册了再拒」：提交端点在路由表里就不存在（客户端拿 403，与「没有这个端点」不可区分）
- `cancel` 拒绝必须**不断连**（观众席可继续看），且**绝不**影响运行（`executor` 不收到 `CancelledError`）
- `readonly` 与 listener 模式**正交**：`WsServerConfig.readonly` 本地/对外都可设；入口层只为对外 listener 暴露配置键
- CLI 覆盖是三态（`--ws-external-readonly/--ws-external-writable`，`None` = 用设置值）——否则设置里的 `true` 无法被命令行关掉
- 订阅额度、认证限速、TLS、端点路径全部不变

**Never:**
- 不做「只读也能提交但排队」、不做按命令的粒度授权（细粒度权限属期二冻结边界外）
- 不给本地 listener 暴露该配置键（没有产品场景，先不开口子）
- 不改期二已交付的对外可提交默认行为

</frozen-after-approval>

## I/O & Edge-Case Matrix

| 场景 | 输入/状态 | 预期行为 |
|---|---|---|
| 只读 listener 提交 | 带正确 token 连 `/api/runs/ws` | 403（路由不存在） |
| 只读 listener 订阅 | 带 token 连 `/api/runs/{id}/ws` | 101，事件流正常 |
| 只读 listener `cancel` | 已订阅连接发 `{"command":"cancel"}` | `invalid_request` 错误帧（含 `read-only`），连接保持 |
| 只读 listener `ping` | 同上发 `{"command":"ping"}` | 正常 ack |
| 只读 listener `run`（订阅连接上） | 同上发 `{"command":"run","prompt":…}` | `invalid_request`（既有口径：提交只在集合端点） |
| 默认配置 | 不设 `WS_EXTERNAL_READONLY` | 对外 listener `readonly=False`（期二语义） |
| 设置 + CLI 覆盖 | 设置 `true` + `--ws-external-writable` | `readonly=False` |
| 主 listener | 任何配置 | `readonly=False`（该键只作用于对外 listener） |

## Code Map

- `src/heagent/network/ws_host.py` — `WsServerConfig.readonly`；`build_ws_app` 按它决定是否注册提交端点
- `src/heagent/network/ws_server.py` — `_handle_commands(..., readonly=)` / `_run_connection_tasks(..., readonly=)` /
  `build_ws_endpoint(..., readonly=)`
- `src/heagent/config/__init__.py` — `ws_external_readonly: bool = False`
- `src/heagent/cli/http.py` — `build_external_ws_server_config(..., readonly=)` / `build_ws_servers(..., external_readonly=)` /
  `--ws-external-readonly/--ws-external-writable` / 公告文案 `; read-only`
- `.env.example` / `docs/frame.md` / `deploy/README.md` — 配置与部署说明
- `tests/network/test_ws_server.py` — 路由表 + 配置映射
- `tests/network/test_ws_e2e.py` — 只读 listener 真实 TCP 判据
- `tests/test_cli_http.py` — `--ws-external-readonly` 落地
- `tests/test_architecture_contracts.py` — 只读路由集契约

## Tasks & Acceptance

**Execution:**
- [x] `ws_host.py` — `readonly` 字段 + 路由条件
- [x] `ws_server.py` — 命令面只读分支
- [x] `config/__init__.py` — `ws_external_readonly`
- [x] `cli/http.py` — 三态 CLI 覆盖 + 公告
- [x] 文档三处 + `.env.example`
- [x] 测试四层（路由表 / 配置映射 / e2e / 契约）

**Acceptance Criteria:**
- Given 只读 listener，when 带 token 连提交端点，then 403
- Given 只读 listener 订阅中，when 发 `cancel`，then `invalid_request` 且运行未取消（`executor.cancelled == 0`、记录非终态）
- Given 设置 `WS_EXTERNAL_READONLY=true`，when CLI 传 `--ws-external-writable`，then `readonly=False`
- Given 默认配置，when 构造服务，then 对外 listener `readonly=False`（零行为变化）
- Given 全量门禁，then 全绿

## Verification

**Commands:**
- `pytest tests/network/test_ws_server.py tests/network/test_ws_e2e.py tests/test_cli_http.py tests/test_architecture_contracts.py -q`
- `python scripts/quality_gate.py`

**实测结果（2026-10-24）:**
- `pytest tests/network/test_ws_server.py tests/test_cli_http.py -q` → **89 passed**
- `pytest tests/network/test_ws_e2e.py -q` → **24 passed**
- `pytest tests/test_architecture_contracts.py -q` → **35 passed**
- `pytest tests/network -q` → **455 passed**
- `python scripts/quality_gate.py` → **六门全过**，覆盖率 **92.43%**（门限 87%），**3947 passed / 50 skipped /
  25 deselected**（与期二 retro 的最终一轮同一份运行）

## Spec Change Log

<!-- Append-only. -->

## Implementation Notes

<!-- Agent-owned. Append-only during implementation. -->

- 只读落在**两层**：`build_ws_app` 不注册提交路由（客户端拿 403）+ `_handle_commands` 拒 `cancel`（不断连）。
  没有选「注册后回错误帧」——那会让「这个 listener 能提交吗」变成需要试一次才知道。
- `readonly` 放在 `WsServerConfig`（listener 级）而不是端点参数：它是 listener 的属性，装配层读一次即可；
  端点函数因此只多一个透传参数，不引入新的判定分支。
- CLI 用 `--ws-external-readonly/--ws-external-writable`（`default=None`）而不是 `is_flag`：`is_flag` 只能表达
  「打开」，一旦设置文件写了 `true` 就再也关不掉（覆盖语义残缺）。

## Review Triage Log

| # | 发现 | 判定 | 证据 / 路由 |
|---|---|---|---|
| 1 | 若只读 listener 仍注册提交端点、只在命令层拒绝，客户端得先「试一次」才知道能不能提交 | low（真） | 改为路由级不注册；判据 `test_readonly_app_registers_only_the_subscription_route` + e2e 403 |
| 2 | `is_flag=True` 的布尔选项无法覆盖设置里的 `true` | medium（真） | 用 flag 对（`--ws-external-readonly/--ws-external-writable`）+ `default=None` 三态；判据 `test_readonly_flag_reaches_the_external_listener_config` |
| 3 | 只读 listener 上 `cancel` 若返回成功 ack，客户端会误以为取消了 | medium（真） | 显式 `invalid_request` 且不断连，e2e 同时断言 `executor.cancelled == 0` 与记录非终态 |
