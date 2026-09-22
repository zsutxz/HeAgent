---
id: 48-2
title: 异步 TCP Server 生命周期
status: ready-for-dev
parent_epic: E48
priority: P0
depends_on: [48-1]
created: '2026-09-22'
---

# Story 48-2：异步 TCP Server 生命周期

## 用户故事

作为服务运行者，我希望 TCP Server 能安全监听、处理一条请求、返回一条响应并可靠关闭，以便连接异常或服务停止不会泄漏 task、writer 或 socket。

## 范围

- 使用 `asyncio.start_server()` 实现可注入 handler 的 TCP Server。
- 单连接单请求单响应，完成后关闭连接。
- 有界读取、空闲读取超时、客户端断开和响应写回。
- 服务启动、停止和有限时间优雅关闭。
- 使用 fake handler 测试，不接 AgentLoop。
- 并发 Agent 限额和完整 Settings 接线留给 48-4/48-3。

## 边界与约束

**Always**

- Server 只依赖 network 协议层和标准库 asyncio。
- handler 形状为 `TcpRequest -> Awaitable[TcpResponse]`。
- 所有连接路径都在 finally 中关闭 writer 并等待 `wait_closed()`。
- `CancelledError` 保持取消语义，不转换为普通业务失败。
- 启动失败必须显性上抛，不打印虚假的 listening 状态。

**Never**

- 不构造 Provider、EngineContainer、AgentLoop 或 ToolRegistry。
- 不导入 Click 或读取 Settings。
- 不实现长连接多请求和流式响应。
- 不吞掉服务整体取消。

## 生命周期矩阵

| 场景 | 期望 |
|---|---|
| 正常请求 | handler 调用一次，响应一次，连接关闭 |
| EOF 无完整行 | 不调用 handler，释放连接 |
| 非法请求 | 返回协议错误，服务继续 |
| handler 异常 | 返回 `server_error`/边界错误，其他连接不受影响 |
| idle timeout | 返回或记录 timeout，关闭连接 |
| 客户端提前断开 | best-effort 清理，不冒泡终止主服务 |
| drain 失败 | 记录 warning，finally 关闭 writer |
| 服务 stop | 停止 accept，有限等待连接，超时取消剩余任务 |

## 任务

- [ ] 新建 `src/heagent/network/tcp_server.py`。
- [ ] 定义 `TcpRequestHandler` 类型别名或 Protocol。
- [ ] 定义 server limits/runtime 配置对象，避免裸参数散落。
- [ ] 实现 `start()`、`serve_forever()`、`close()` 或等价清晰生命周期。
- [ ] 通过 `asyncio.start_server(..., limit=max_request_bytes + framing_margin)` 限制 reader。
- [ ] 把 `LimitOverrunError`/超长行映射为 `request_too_large`。
- [ ] 实现单连接处理和 best-effort 错误响应。
- [ ] 跟踪活跃连接任务，关闭时有限等待并取消残留。
- [ ] 新增 `tests/network/test_tcp_server.py`，使用 loopback + 随机端口。

## 验收标准

- Given 注入 fake handler，when 客户端发送合法请求，then 收到一条响应且连接关闭。
- Given 请求被拆分发送，when 完整 LF 到达，then handler 只调用一次。
- Given 非法 JSON 或超长消息，when 读取，then 返回稳定错误且服务仍接受下一连接。
- Given 客户端在响应前断开，when handler 完成，then服务不崩溃且连接任务被回收。
- Given 服务关闭，when shutdown timeout 到达，then 剩余连接任务被取消、writer 被关闭且 `close()` 返回。
- Given `asyncio.start_server` 绑定端口失败，when 启动，then 调用方收到原始可诊断启动异常。

## Definition of Done

- fake handler 场景覆盖成功、协议失败、handler 失败、断开、idle timeout 和 shutdown。
- 测试结束后无 pending connection task。
- 网络模块不依赖 agent/cli/providers/engine。
- 跨平台默认测试通过。

## 代码地图

- `src/heagent/network/tcp_server.py`：服务器与连接生命周期。
- `src/heagent/network/protocol.py`：解析和响应序列化。
- `tests/network/test_tcp_server.py`：socket 生命周期测试。
- `tests/test_architecture_contracts.py`：如新增依赖规则，补网络层不得导入高层模块的断言。

## 验证命令

```text
pytest tests/network/test_protocol.py tests/network/test_tcp_server.py -q
ruff check src/heagent/network tests/network
ruff format --check src/heagent/network tests/network
mypy src --platform linux
```
