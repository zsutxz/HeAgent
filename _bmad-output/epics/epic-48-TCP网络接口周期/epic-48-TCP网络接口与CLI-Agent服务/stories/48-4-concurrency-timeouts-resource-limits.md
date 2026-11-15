---
id: 48-4
title: 并发、超时与资源限制
status: done
parent_epic: E48
priority: P0
depends_on: [48-3]
created: '2026-09-22'
---

# Story 48-4：并发、超时与资源限制

## 用户故事

作为服务运行者，我希望 TCP 入口对连接、消息、Agent 并发和时间都有明确上限，以便慢客户端、请求洪峰或长时间 Agent 任务不会无限消耗进程资源。

## 范围

- Settings 与 `.env.example` 中加入 TCP 配置。
- CLI 参数覆盖 Settings，最终走同一校验语义。
- 最大连接数和最大在途 Agent 数两级限制。
- 请求大小、idle timeout、request timeout、shutdown timeout。
- 超时取消与 semaphore/连接许可回收。

## 默认值

| 字段 | 默认值 | 校验 |
|---|---:|---|
| `tcp_host` | `127.0.0.1` | 非空 |
| `tcp_port` | `8765` | 1..65535 |
| `tcp_max_connections` | `32` | >=1 |
| `tcp_max_inflight_requests` | `4` | >=1 |
| `tcp_max_request_bytes` | `1048576` | >=1 |
| `tcp_idle_timeout` | `60.0` | >0 |
| `tcp_request_timeout` | `300.0` | >0 |
| `tcp_shutdown_timeout` | `5.0` | >0 |

## 边界与约束

- 达到 Agent 并发上限时立即返回 `rate_limited`，不建立无限等待队列。
- 连接上限保护 socket 生命周期；Agent semaphore 保护昂贵运行时。
- idle timeout 只覆盖读取完整消息阶段。
- request timeout 只覆盖 handler/AgentLoop，不把关闭 writer 时间算进 Agent 预算。
- 取消和超时后必须释放 semaphore 和连接登记。
- 非法环境变量由 Pydantic 配置校验显式失败，不静默变成无限制。
- 配置只影响 TCP 入口，不改变普通 CLI 默认行为。

## 任务

- [x] 在 `Settings` 新增 TCP 字段与数值约束。
- [x] 更新 `.env.example`，说明默认关闭、localhost、无认证。
- [x] CLI 参数使用 `None` 表示未覆盖，解析后合并为最终 limits。
- [x] 实现最大连接数登记与拒绝策略。
- [x] 实现非等待式 inflight admission；无名额返回 `rate_limited`。
- [x] 使用 asyncio timeout 管理 idle/request/shutdown。
- [x] 确保 timeout/cancel/error 全路径释放 permit。
- [x] 增加配置默认值、env 解析、非法值测试。
- [x] 增加并发洪峰、请求超时、shutdown timeout 和无残留 task 测试。

## 验收标准

- Given 最大 inflight=1，when 第二个请求在第一个执行期间到达，then 第二个立即收到 `rate_limited`，不无限等待。
- Given 客户端连接后不发送完整行，when 超过 idle timeout，then 连接被释放。
- Given handler 超过 request timeout，when 超时，then task 被取消、客户端收到 `timeout`、permit 被释放。
- Given 服务关闭且请求未完成，when超过 shutdown timeout，then 残留任务被取消，服务可退出。
- Given env 中端口 0、负 timeout 或连接数 0，when 加载 Settings，then 显式校验失败。
- Given CLI 提供覆盖值，when 启动，then 覆盖生效且 Settings 默认不被永久修改。

## Definition of Done

- 两级限制和三类 timeout 有确定性测试。
- 没有 pending task、writer 或 semaphore 泄漏警告。
- `.env.example` 与 Settings 字段一一对应。
- 全量相关测试在 Windows/Linux 语义下通过。

## 代码地图

- `src/heagent/config.py`：TCP Settings。
- `src/heagent/network/tcp_server.py`：连接登记、admission、timeout、shutdown。
- `src/heagent/cli.py`：参数覆盖。
- `.env.example`：配置说明。
- `tests/test_config.py`：配置校验。
- `tests/network/test_tcp_server.py`：资源限制测试。
- `tests/test_cli_tcp.py`：CLI 覆盖测试。

## 验证命令

```text
pytest tests/test_config.py tests/network/test_tcp_server.py tests/test_cli_tcp.py -q
ruff check src tests
ruff format --check src tests
mypy src --platform linux
```

## Verification

**Commands and results (2026-09-22, 本机 UTC+8 + 干净 Linux 检出)：**

- 定向：`pytest tests/network tests/test_config.py tests/test_cli_tcp.py tests/test_tcp_agent_integration.py -q` → **173 passed**
- 全量 `pytest -q --cov=heagent --cov-fail-under=87` → **2159 passed / 9 skipped / 18 deselected，覆盖率 90.97%**（门限 87%）
- 干净 Linux 检出（`git clone --depth 1` + `git apply` + `uv venv --python 3.12` + `pip install -e ".[dev]"`，无 `.env`）→ **2146 passed / 17 skipped**（CI 等价口径）
- `ruff check src tests` → All checks passed；`ruff format --check src tests` → 244 files already formatted；`mypy src --platform linux` → Success: no issues found in 134 source files

**Implemented：**

- `src/heagent/config.py`：8 个 `tcp_*` 设置（host min_length=1；port 1..65535；三个计数 ge=1；三个超时 gt=0 且 `allow_inf_nan=False`）。
- `src/heagent/network/tcp_server.py`：`TcpServerConfig.max_inflight_requests`（默认 4）+ `_admit_request()/_release_request()` 非等待式名额 + `active_inflight` + `close()` 结算残留登记；三个超时字段同样 `allow_inf_nan=False`。
- `src/heagent/cli_tcp.py`：6 个新参数（`--max-connections/--max-inflight/--max-request-bytes/--idle-timeout/--request-timeout/--shutdown-timeout`，全部 `default=None` = 未覆盖）+ `--port` 收紧为 1..65535 + `build_server_config(settings, **overrides)` 合并（不写回 Settings）+ `_reject_non_finite` 拒绝 NaN/Inf。
- `.env.example`：新增第 18 节（8 个键与代码默认值逐项一致，含「默认关闭 / 仅 localhost / 无认证无 TLS / 非法值显式失败」说明）。
- 测试：`tests/test_config.py::TestTcpSettings`（默认值/env 全字段/单例/非法值 13 例）、`tests/network/test_tcp_server.py`（在途限额立即拒绝、成功/超时/异常/关闭/空闲的名额回收、关闭超时后结算与实例重启、非有限超时拒绝、`max_inflight_requests=0`）、`tests/test_cli_tcp.py`（默认值来自 Settings、env 驱动默认、全字段覆盖且不污染 Settings、非法值 exit 2 共 11 例）。

**关键设计决策（含证据）：**

1. **名额用「任务集合」而非纯计数**：`asyncio.Semaphore` 没有 `try_acquire`，用它就退化成排队等待（违反「满即 `rate_limited`」）；纯计数在「关闭超时后残留任务迟到自己结束」时会被减成负数。集合的 `discard` 是幂等的，且 `close()` 结算后不会有容量残留。admission 的 check→add 之间无 `await`（单线程事件循环内原子）——30 并发 × 上限 3 的压测由评审确认峰值恰为 3、无第 4 个。
2. **`rate_limited` 立即返回，不排队**：测试断言第二个请求的响应延迟 < 1s（第一个仍在途）。
3. **`close()` 结算残留**（评审 Warning 1 修复）：asyncio 无法强杀忽略取消的任务；超时返回时把连接登记与在途名额复位（并 warning 说明「无法强杀」），否则同一实例重启后永久少一份容量。**负向验证**：临时移除结算三行 → 新旧两个测试都精确红在 `active_inflight == 0` / `active_connections == 0`（残留 1）。
4. **CLI 与 env 同一套校验语义**：CLI 侧 `click` range 先拦，最终仍经同一个 `TcpServerConfig`（Pydantic）校验；`--port 0` 与 `TCP_PORT=0` 两侧都失败（0 端口对客户端无意义）。
5. **NaN/Inf 显式拒绝**（评审 Warning 2 修复）：`click.FloatRange` 会放行 `nan`/`inf`——`Inf` 会让超时静默变成无限制（关闭等待无界），`NaN` 会绕过范围比较直到 Pydantic 才以 traceback 炸掉。现 CLI 侧 `_reject_non_finite`（usage error，exit 2）、env 侧 `allow_inf_nan=False`（ValidationError）。
6. **`tcp_*` 只影响 TCP 入口**：全仓唯一读取点是 `cli_tcp`；无 `TCP_ENABLED` 之类隐式开关（显式 `tcp-server` 是唯一启动方式，普通 CLI `test_plain_cli_never_creates_a_tcp_listener` 仍绿）。

**Critical review fixes（对抗式评审发现并已修）：**

- 评审结论 **Critical 0 条**；2 条 Warning 均已闭合：W1 = `close()` 超时路径不归还在途名额与连接登记（复用/重启会永久少容量，已修 + 负向验证）；W2 = NaN/Inf 绕过「非法值显式失败」（已修 + env/CLI/TcpServerConfig 三层测试）。评审的 12 条「已核实无问题」覆盖了原子性压测、逐路径名额归还探测、超时边界实测、Settings 不被污染、`.env.example` 一一对应等。

**Deviation / 已知边界：**

- **修改了 Story 48-2 的一个断言**：`test_close_returns_after_timeout_when_handler_suppresses_cancellation` 原断言「关闭超时后 `active_connections == 1`」（把残留仍在登记当契约），现改为 `== 0` + 在途名额 `== 0`，并在测试里注明改动理由（48-4 的「超时后必须释放连接登记」要求）。48-2 的其余语义（有界返回、记录未退出任务、幂等 `close()`）不变。
- **残留任务无法强杀**：handler 忽略取消时，任务会继续运行到自行结束（asyncio 限制）；`close()` 只能有界返回 + warning + 结算账目，不能真正 kill（诚实边界，已写进 `close()` docstring）。
- **`max_connections` 与 `max_inflight_requests` 无交叉校验**：两者取 `min(...)` 生效，不产生 liveness 风险，故不额外约束。
- **文档**：README / `docs/frame.md` 的 TCP 配置与使用说明按 Sprint Plan 属 Story 48-6（交付收口）；本 Story 只更新 `.env.example`（story 代码地图明确列出）。

## Review Status

实现、对抗式评审（独立子代理）与定向验证均已通过；评审 0 Critical、2 Warning 均已在当前 Story 修复（关闭超时结算、NaN/Inf 拒绝）并补回归。状态为 `done`。未提交 Git。
