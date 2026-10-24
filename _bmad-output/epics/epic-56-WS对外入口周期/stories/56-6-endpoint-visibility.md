---
title: '56-6 端点可见性与双监听安全不变量'
type: 'feature'
created: '2026-10-24'
status: 'done'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: 'bab1dc5c0f6e23f9eb397a6aaf1711803cdf9bc9'
context: []
---

<!-- 交付物与验收边界 = epics.md 期二 56-6 行；冻结决策 D9/D10/D11 见 brief.md。 -->

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 56-5 只搭骨架，两个 listener 仍按期一规则挂路由 ⇒ 对外 listener 上也会注册 `/api/cli/ws`。
那条通道推的是**终端里那一轮** run 的实时事件（工具调用参数与结果，可能含文件内容），它存在的初衷是
「本机观众席」。挂到对外 listener 上，token 只是延迟风险，不是消除风险。

**Approach:** 把「listener 身份决定端点集」写成不变量：`/api/runs/ws` 与 `/api/runs/{run_id}/ws` 两个
listener 都注册；`/api/cli/ws` **只**在 `mode == "local"` 的 listener 上注册。同一不变量覆盖期一的单对外
形态：「`WS_HOST=0.0.0.0` + `WS_CLI_BYPASS_ENABLED=true`」起改为跳过旁路并打
`ws event=cli_bypass_skipped reason=external_listener` WARNING（不是静默关闭）。

## Boundaries & Constraints

**Always:**
- 可见性判据只读 `WsServerConfig.mode`（一个真源）；`build_ws_app` 里由 `mode` 决定是否接收 `cli_hub`
- 跳过旁路必须**日志可见**（WARNING，含 `reason=external_listener`），便于用户解释「我开了开关却没这条流」
- 对外 listener 的提交席位与认证限速各自一份（已由每 app 一个实例天然满足，不得改成共享）
- 双监听 e2e 必须用真实 TCP：本地免 token 可订阅；对外无 token 被拒、有 token 可订阅**同一 run**
- 对外 listener 打 `/api/cli/ws` ⇒ 客户端拿 403（路由未注册，Starlette 直接拒）
- 端点函数体（`ws_server.py`）不动：本 story 只改「哪个 app 注册哪些路由」

**Never:**
- 不给对外 listener 任何「终端内容」通道（旁路、日志回放、历史事件都不行）
- 不把「跳过旁路」实现成静默（用户会以为开了）
- 不改本地 listener 的既有语义与额度
- 不新增配置键（跳过逻辑没有开关：对外 listener 恒不挂旁路）

</frozen-after-approval>

## I/O & Edge-Case Matrix

| 场景 | 输入/状态 | 预期行为 | 错误处理 |
|---|---|---|---|
| 双监听 + 旁路开关开 | 本地 9001 + 对外 9002 | 9001 有 `/api/cli/ws`；9002 无 | N/A |
| 双监听下订阅同一 run | 本地与对外各开一条订阅 | 两条都收到同源事件，`seq` 递进一致 | N/A |
| 对外无 token | 连 9002 不带 `Authorization` | accept 前 close（403） | 不泄露端点存在性 |
| 对外有 token | `Bearer <正确>` | 可提交 `run`、可订阅、可 `cancel` | N/A |
| 对外打旁路 | 9002 `GET /api/cli/ws`（升级） | 403（路由未注册） | N/A |
| 单对外 + 旁路开关开 | `WS_HOST=0.0.0.0` + `WS_CLI_BYPASS_ENABLED=true` | 旁路被跳过，`cli_hub is None`，WARNING 一次 | 不崩、不静默 |
| 本地 + 旁路开关关 | 9001 | 无 `/api/cli/ws`（同期一） | N/A |
| 提交席位独立性 | 本地占满 16 席 | 对外仍可提交（反之亦然） | 各自 `rate_limited` |
| 关停 | 双监听在途中 | 两个 listener 都有界关闭；在途 run 由 HTTP 侧排空 | 不取消运行 |

## Code Map

- `src/heagent/network/ws_host.py` — `build_ws_app` 的 `cli_hub` 注册条件改为 `config.mode == "local"`
- `src/heagent/cli/http.py` — `build_ws_servers` 不再把 hub 传给对外 listener（56-5 已备），补 WARNING
- `tests/network/test_ws_e2e.py` — 双监听 e2e（真实 TCP ×2）
- `tests/network/test_ws_server.py` — 路由表判据（对外 app 无 CLI 路由）
- `tests/test_architecture_contracts.py` — 钉「对外 listener 端点集 = {提交, 订阅}」（56-7 完成，本 story 先留判据）

## Tasks & Acceptance

**Execution:**
- [ ] `network/ws_host.py` — 端点可见性由 `mode` 决定
- [ ] `cli/http.py` — 跳过旁路的 WARNING（`cli_bypass_skipped`）
- [ ] 测试 — 双监听 e2e ×N + 路由表判据
- [ ] 测试 — 单对外 + 旁路 ⇒ 跳过判据

**Acceptance Criteria:**
- Given 双监听 + 旁路开，when 9002 尝试 `/api/cli/ws`，then 403（且 9001 同一路径 101）
- Given 双监听，when 本地提交一个 run 后从 9002 订阅，then 收到事件且 `seq` 与 9001 一致
- Given 9002 无 token，when 升级，then 403 且 `active_runs` 不变
- Given `WS_HOST=0.0.0.0` + 旁路开，when 启动，then `cli_hub is None` 且日志含 `cli_bypass_skipped`
- Given 本地 16 个提交连接占满，when 9002 提交，then 成功（席位独立）
- Given 全量 `pytest`，then 全绿

## Verification

**Commands:**
- `pytest tests/network/test_ws_e2e.py tests/network/test_ws_server.py -q` -- expected: 全绿
- `pytest tests/network -q` -- expected: 全绿
- `pytest -q --ignore=tests/test_cli_http_lifecycle.py` -- expected: 全绿
- `ruff check src tests && ruff format --check src tests && mypy src --platform linux && bandit -r src/ -ll` -- expected: 全绿

**实测结果（2026-10-24，容器沙箱 + `.heagent/tmp/py311-venv-linux` 取证 venv）:**
- `pytest tests/network/test_ws_e2e.py -q` → **23 passed**（本期新增双监听 5 例）
- `pytest tests/network/test_ws_server.py tests/network/test_ws_e2e.py -q` → **60 passed**
- `pytest tests/network -q` → **452 passed**
- `ruff check src tests` / `ruff format --check src tests` / `mypy src --platform linux`（174 files）/
  `bandit -r src/ -ll`（Medium 0 / High 0）→ 全绿

## Spec Change Log

<!-- Append-only. -->

## Implementation Notes

<!-- Agent-owned. Append-only during implementation. -->

- 2026-10-24 实施完成。可见性判据落在**两处**，都不靠调用方自觉：
  1. 装配层 `build_ws_servers` 从不把 hub 传给对外 listener；
  2. `build_ws_app` 自身再判 `config.mode == "local"` 才注册 `/api/cli/ws`
     （`test_external_mode_app_never_registers_the_cli_bypass_route` 直接构造
     `WsServer(cli_hub=...)` 的对外 app 并断言路由表只有两条）。
- 跳过旁路的 WARNING 在 56-5 落地（`ws event=cli_bypass_skipped reason=external_listener`），
  本期只补 e2e/路由判据，不重复实现。
- 双监听 e2e 的装配替身 `_Pair`：两个 `WsServer` 共享一个 `HttpRunService`，本地挂
  `CliEventHub`、对外 `auth_token="s3cret"` 且不挂 hub；`port=0` 让 OS 分配，避免与真实
  9001/9002 冲突（同时说明「绑定 0.0.0.0 的对外 listener 在本机测试端口可用」）。
- 断言的错误帧形状沿用既有 `{"type":"error","error":{"error":{"code":…}}}`（信封单出口），
  不新造协议。

## Review Triage Log

<!-- 三层自审（blind-hunter / edge-case-hunter / verification-gap）逐层执行后追加。 -->

| # | 发现 | 判定 | 证据 / 路由 |
|---|---|---|---|
| 1 | 只在装配层挡住「对外 listener 不挂旁路」，直接构造 `WsServer(config, cli_hub=hub)` 的人仍会把终端流推出去 | medium（真） | `build_ws_app` 里补 mode 判据（defense-in-depth）+ 路由表判据；见 Implementation Notes 第 1 条 |
| 2 | 「订阅额度按 run 共享」若两个 listener 各传不同 `ws_max_connections`，同一 run 的额度会随连接来源变化 | low（接受） | 共享的额度真源是 `record.ws_max_subscriptions`（run 记录上的值），`max_connections` 只是每次订阅的**上限参数**；双监听装配传同一个值（`build_ws_servers` 单一来源），故不会分叉。e2e `test_dual_listeners_serve_the_same_run_with_identical_event_streams` 用同源 `seq` 钉住共享 |
| 3 | 对外 listener 的 `Origin` 不校验，若将来有人把浏览器客户端指向它，会绕开 Origin 防线 | false（驳回，已冻结） | D5 冻结值：对外模式 Origin 不适用（客户端用任意主机名连，Host 白名单会全拒），防线由 token 取代；`AGENTS.md` 明确写「对外模式面向 IDE 插件/桌面客户端，不面向浏览器页面」 |
