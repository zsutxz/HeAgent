---
title: 'Story 71.2 部署面视图'
type: feature
ticket: 2
created: '2026-11-19'
status: built
baseline_revision: '98928cb'
route: full
route_source: auto
risk: low
review: thorough
review_source: auto
lenses_ran: ['edge-case-hunter', 'verification-gap']
review_loop_iteration: 0
followup_review_recommended: true
context:
  - 'src/heagent/cli/http_status.py'
  - 'src/heagent/network/ws_host.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** 网页端与 `/api/status` 都不知道自己连的是什么部署形态——绑定地址/端口、listener 模式（本地/对外）、TLS、沙箱后端、配置写入闸门、当前 provider 与池档位，全部只散落在启动日志与各项目 `/api/config` 里。

**Approach:** 把入口层在装配期已知的部署事实投影进 `GET /api/status`：listener 列表（http + 1–2 条 ws，含实际端口与模式）与部署标量（沙箱后端、写入闸门、当前 provider、路由池档位名）。端口必须在**请求时**读（自动顺延后只有绑定完成才知道）。

## Boundaries & Constraints

**Always:**
- 只报**名字与布尔**：绝不回显密钥值、`base_url`、项目/工作区绝对路径。
- 端口与模式取自运行中的对象（`HttpServer.port` / `WsServer.port` / `WsServerConfig.mode` / `tls_enabled`），不在 source 里重算阈值或重新判定回环。
- 集合字段一律有界（`max_length`）且顺序稳定（http 在前，ws 按装配顺序）。

**Never:**
- 不改 `/api/health`、不改认证与暴露面、不新增依赖。
- 不在端点里做 I/O（部署事实在装配期确定，端口是内存属性）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| LOOPBACK_BIND | 全部 listener 绑回环 | 每条 `mode == "local"` | 无 |
| EXTERNAL_BIND | WS 对外 listener（`0.0.0.0`） | 该条 `mode == "external"`，TLS 按 cert/key 配齐与否 | 无 |
| NO_WS | `WS_ENABLED=false` | `listeners` 只有一条 http | 无 |
| AUTO_PORT | `port=0` 经绑定顺延 | `port` 为实际监听端口（非 0） | 绑定前不得谎报 |
| SECRETS | 环境里有哨兵密钥值 | 响应体搜不到该值；无绝对路径 | 无 |
| POOLS_ABSENT | 未配 `ROUTING_POOLS` | `routing_pools == []`（不是 null） | 无 |

</intent-contract>

## Code Map

- `src/heagent/network/http_protocol.py` -- 加 `ListenerMode` / `ListenerInfo` / `RoutingPoolInfo`，并在 `StatusResponse` 上挂 `listeners` / `sandbox_backend` / `config_write_enabled` / `active_provider` / `routing_pools`；登记 `__all__`。
- `src/heagent/network/http_server/config.py` -- 加 `mode` property（`is_loopback_host(self.host)` → `"local"`/`"external"`），与 `WsServerConfig.mode` 同口径、同判定函数（`network/exposure.py`）。
- `src/heagent/cli/http_status.py` -- `build_status_source(... settings=…)` 在构造期取部署标量（`settings.sandbox_backend` / `http_console_write_enabled` / `active_provider` / `routing_pool_map` 的档位名）；新增 `bind_listeners(http_server, ws_servers)`；`status()` 在请求时读端口。
- `src/heagent/cli/http.py` -- 两处装配点把 `settings` 传进 `build_status_source`，`bind_status_source(..., http_server=…)` 传入 listener 对象。
- `src/heagent/pub/types.py::RoutingPoolSpec` -- 只读 `tiers` 的键（池内名）；`base_url` 与模型名一律不取。
- `tests/test_http_status_api.py` -- 新增 `TestDeployment`：模式判定、TLS 标志、无 WS 形态、实际端口、哨兵密钥不回显、池档位名。
- `tests/fixtures/contract_baselines/{public_exports,exception_types}.json` -- 新类入表，需重生成。

## Tasks & Acceptance

**Execution:**
- [ ] `src/heagent/network/http_protocol.py` -- 三个新模型 + 五个新字段 + `__all__` -- 协议封闭性优先。
- [ ] `src/heagent/network/http_server/config.py` -- `HttpServerConfig.mode` -- HTTP 侧也要有与 WS 同名的模式概念。
- [ ] `src/heagent/cli/http_status.py` -- 部署标量 + `bind_listeners` + `status()` 组装 -- 端口请求时读。
- [ ] `src/heagent/cli/http.py` -- 传 `settings` 与 listener 对象 -- 两处装配点同改。
- [ ] `tests/test_http_status_api.py` -- `TestDeployment` 覆盖 I/O Matrix 全部行 -- 含哨兵密钥与绝对路径断言。
- [ ] `docs/frame.md` -- 4.17「状态 API」行补部署面口径 -- 文档不落后。

**Acceptance Criteria:**
- Given 回环绑定的 http + ws, when 读 status, then 两条 `listeners` 的 `mode` 都是 `local`，`kind` 分别为 `http`/`ws`。
- Given 对外 WS listener, when 读 status, then 该条 `mode == "external"` 且 `tls` 反映 cert/key 是否配齐。
- Given `WS_ENABLED=false`, when 读 status, then `listeners` 长度为 1。
- Given `port=0` 且已绑定, when 读 status, then `port` 等于实际监听端口（非 0）。
- Given 环境含哨兵密钥与已配池, when 读 status, then 响应体不含哨兵值、`routing_pools` 只含池名与档位名。

## Implementation Notes

- 落地：路径常量与协议模型（`ListenerMode` / `ListenerInfo` / `RoutingPoolInfo`）→ `HttpServerConfig.mode`（复用 `exposure.is_loopback_host`）→ `cli/http_status.py` 的 `_deployment` / `_listener_infos` / `bind_listeners` → 两处装配点传 `settings` / `sandbox_backend` / `provider` 与 `http_server` → 用例与基线。
- **偏离（评审后收紧）**：`sandbox_backend` 与 `active_provider` 不取配置值，取**本次进程实际用的**（`--sandbox` 覆盖、provider 实例的 `.active`）；所有字符串与档位清单按协议上限截断/取前 N 条（状态面宁可截断，也不能因一条异常配置让 `/api/status` 整体 500）。
- **评审补丁**：见下方 Triage Log（6 条 medium、5 条 low 全部 patch，无 defer / reject）。

## Plan Change Log

## Review Triage Log

## Review Triage Log

### 2026-11-19 — Review pass
- verdicts: 11 findings — high 0, medium 6, low 5, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` 池档位超过协议 `max_length` 时 `RoutingPoolInfo` 校验抛错 ⇒ **入口启动失败**（`RoutingPoolSpec.tiers` 无界）— 上限放宽到 64 且 source 按 64 截断，加 17 档用例。
  - `[medium]` `[patch]` 同一缺陷（edge 镜头的另一处描述）：`max_length=16` 与无界 `tiers` 不匹配 — 同上，一处修复覆盖。
  - `[medium]` `[patch]` `--sandbox docker` 覆盖未反映：配置里仍是 `auto` 时状态报 `auto` — `build_status_source` 增 `sandbox_backend` 参数，两处装配传实际档位；加单测与装配级断言。
  - `[medium]` `[patch]` 同一缺陷（verification 镜头的 Other findings）：启动横幅与 `/api/status` 给出不同沙箱档位 — 同上。
  - `[low]` `[patch]` `active_provider` / `sandbox_backend` 超长（Settings 无上限）会让每次请求 500 — source 侧 `_clip` 截断到协议上限。
  - `[low]` `[patch]` `host` 超长（`*Config.host` 只校验非空）会让每次请求 500 — 同上，host 按 255 截断。
  - `[low]` `[patch]` claims：`active_provider` 取配置值而非生效 provider（未配置时装配会默认取首家）— 改为优先取 provider 实例的 `.active`，配置名只作兜底，并在字段注释写明语义。
  - `[medium]` `[patch]` **verification gap**：`http_server=` 的接线无装配级用例（漏传时 200 但 `listeners: []`）— 两条装配级用例各补 `listeners` 断言；变异验证：去掉 `http_server=` ⇒ RED。
  - `[medium]` `[patch]` **verification gap**：`settings=` 的接线无装配级用例（漏传时标量全空）— 补 `sandbox_backend` / `routing_pools` 断言；变异验证：去掉 `settings=` ⇒ RED。
  - `[low]` `[patch]` **verification gap**：「请求时读端口」的用例原先在绑定前就把端口设为最终值，与「绑定期快照」不可区分 — `_deployed` 改成先绑 `port=0` 再改运行期端口，`_ws_server` 让配置端口与运行期端口首次出现差异；变异验证：改回 `config.port` ⇒ RED。
  - `[low]` `[patch]` 新用例 docstring 声称「通配绑定的暴露告警依赖 `HttpServerConfig.mode`」，实测告警走 `exposure_warning(config.host)` — 注释改为说明语义，不再声称依赖。

## Auto Run Result

- **实现**：`GET /api/status` 增加部署面——`listeners`（kind / label / host / 实际端口 / `local|external` / TLS）、`sandbox_backend`（本次进程实际档位）、`config_write_enabled`、`active_provider`（生效 provider）、`routing_pools`（池名 + 池内档位名）。
- **文件**：`src/heagent/network/http_protocol.py`、`src/heagent/network/http_server/config.py`（`mode`）、`src/heagent/cli/http_status.py`、`src/heagent/cli/http.py`（两处装配）、`tests/test_http_status_api.py`、`tests/test_cli_http.py`、`tests/fixtures/contract_baselines/{public_exports,exception_types}.json`、`docs/frame.md`。
- **评审处置**：patch 11 条（medium 6 / low 5），defer 0，reject 0，intent_gap / bad_plan 0。
- **后续评审建议**：`true` —— 本轮的 6 条装配与边界用例是评审后新写的，只经自我变异验证（6 处变异各 RED），未经第二双眼睛复核强度。
- **验证**：`pytest`（`tests/network` + 相关套件 **801 passed**）；`contract_snapshot.py --check` 四份 `[OK]`；`ruff check` / `ruff format --check` / `mypy src` 全绿；变异验证 6/6 RED。
- **残差**：`active_provider` 对非「可切换/组合」provider（无 `.active` 属性）只能回落到配置名；`routing_pools` 超过 64 档会被截断（配置面正常远小于此）。

## Design Notes

`ListenerInfo.mode` 复用 `WsServerConfig.mode` 的既有判定（`network/exposure.is_loopback_host`），HTTP 侧在同一判定函数上加 `HttpServerConfig.mode`——两处若各写一套「算不算本地」，漏报暴露的那天就会两套结论不一致。

## Verification

**Commands:**
- `python -m pytest tests/test_http_status_api.py tests/network tests/test_cli_http.py tests/test_architecture_contracts.py tests/test_contract_baselines.py -q` -- expected: 全绿
- `python scripts/contract_snapshot.py --write --only public && python scripts/contract_snapshot.py --write --only exceptions && python scripts/contract_snapshot.py --check` -- expected: 全 `[OK]`
- `python -m ruff check src tests` / `python -m ruff format --check src tests` / `python -m mypy src` -- expected: 无新增告警
