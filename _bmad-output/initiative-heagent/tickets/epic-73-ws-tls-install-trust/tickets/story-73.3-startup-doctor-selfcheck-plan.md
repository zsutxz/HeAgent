---
title: 'Story 73.3 启动自检与 doctor 三项'
type: feature
ticket: 3
created: '2026-11-19'
status: done
baseline_revision: '7cc8baba'
route: full
route_source: auto
risk: medium
review: thorough
review_source: auto
lenses_ran: []
review_loop_iteration: 0
context:
  - 'src/heagent/cli/http_config.py'
  - 'src/heagent/cli/doctor.py'
  - 'src/heagent/network/ws_host.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** 这套方案只有两处会「静默失联」——叶证书到期、SAN 不含当前绑定地址；再加一处会
「起得来但全握手失败」——cert 与 key 不配对。现状三者全不可见：`doctor` 只有
`doctor.ws_tls_half_configured`（只配了一个键），启动期零检查。

**Approach:** 把三条做成启动期事实（到期 < 7 天 WARNING、SAN 缺当前绑定 WARNING、cert/key 不配对
拒绝启动）与 `doctor` 的三个 finding（指纹可读 / 到期余量 / SAN 覆盖），未启用 TLS 时全部跳过。

## Boundaries & Constraints

**Always:**
- 只在 TLS 真正启用（`ws_tls_cert_file` 与 `ws_tls_key_file` 都非空）时检查；未启用时零告警、零输出。
- 到期阈值集中在 `TLS_EXPIRY_WARNING_DAYS = 7` 一个常量，不散落字面量。
- 每条告警**点名可执行命令**（`heagent tls issue` / `heagent tls issue --san <addr>`）。
- `caplog` 计数判据：每次启动**恰一条**，不因多次装配叠加。
- `doctor` 退出码语义不变（WARNING 不阻断，ERROR 才非 0）。

**Never:**
- 不在启动期做网络请求、不调 `openssl` 子进程（全部走 73.1 的纯 stdlib 解析）。
- 不因 SAN 缺失而拒绝启动（内网地址漂移是常态，只能告警 + 给命令）。
- 不在日志里打印完整证书或私钥片段。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| TLS_OFF | cert/key 均为空 | 三条检查全跳过，无日志 | 无 |
| EXPIRY_SOON | 余量 3 天 | WARNING，恰一条，含 `heagent tls issue` | 不阻断 |
| EXPIRY_OK | 余量 20 天 | 无 WARNING | 无 |
| SAN_MISS | `WS_HOST` 不在 SAN | WARNING，含 `--san` | 不阻断 |
| SAN_HIT | `WS_HOST` 在 SAN | 无 WARNING | 无 |
| KEY_MISMATCH | cert 与 key 不配对 | 拒绝启动，退出码 1，点名两键 | 显性错误，无 traceback |
| HALF_CONFIG | 只配 cert | 沿用既有 `doctor.ws_tls_half_configured`；启动期不新增告警 | 既有语义 |
| DOCTOR_CODES | 正常材料 | 三条 finding（INFO/WARNING）各一次，含短指纹 | 无 |

</intent-contract>

## Code Map

- `src/heagent/cli/http_config.py` — `build_ws_servers` 装配点加 `_check_tls_identity(settings, host)`：
  返回告警列表，由装配点逐条 `logger.warning`。
- `src/heagent/network/ws_host.py` — cert/key 配对检查放在构造期 `_validate_auth_and_tls`；
  `network/` 不得 import `config/`，入参用已解析路径。
- `src/heagent/cli/doctor.py` — 新增 `doctor.ws_tls_fingerprint` / `doctor.ws_tls_expiry` /
  `doctor.ws_tls_san`；`doctor.ws_tls_half_configured` 保持不动。
- `tests/test_cli_tls_selfcheck.py`（新增，或并入 `tests/test_cli_doctor.py`）— 覆盖上表。
- `docs/errors.md` — 新增稳定 code 时同步。

## Evidence（开工前取证，交付后回填）

- 已实测：`src/heagent/cli/doctor.py:396` 现有循环只做 cert/key 半配检查。
- 已实测：`network/ws_host.py` 的 `tls_enabled` = cert 与 key 都非空；不配对时错误在握手期才出现，
  不在启动期。
