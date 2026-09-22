---
id: 48-4
title: 并发、超时与资源限制
status: ready-for-dev
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

- [ ] 在 `Settings` 新增 TCP 字段与数值约束。
- [ ] 更新 `.env.example`，说明默认关闭、localhost、无认证。
- [ ] CLI 参数使用 `None` 表示未覆盖，解析后合并为最终 limits。
- [ ] 实现最大连接数登记与拒绝策略。
- [ ] 实现非等待式 inflight admission；无名额返回 `rate_limited`。
- [ ] 使用 asyncio timeout 管理 idle/request/shutdown。
- [ ] 确保 timeout/cancel/error 全路径释放 permit。
- [ ] 增加配置默认值、env 解析、非法值测试。
- [ ] 增加并发洪峰、请求超时、shutdown timeout 和无残留 task 测试。

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
