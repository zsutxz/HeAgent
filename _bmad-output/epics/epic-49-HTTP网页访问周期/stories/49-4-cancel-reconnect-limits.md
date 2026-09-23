---
id: 49-4
title: 运行取消、SSE 重连与资源限制
status: backlog
parent_epic: E49
priority: P0
depends_on: [49-3]
created: '2026-09-23'
---

# Story 49-4：运行取消、SSE 重连与资源限制

## 用户故事

作为网页用户，我希望能停止卡住或不再需要的运行，并在浏览器短暂断线后继续接收进度，以便网页操作不会留下失控任务或错误状态。

## 范围

- 实现 `DELETE /api/runs/{run_id}` 的协作式取消。
- 为每个 run 维护有界事件 ring buffer 和单调事件序号。
- 支持 SSE `Last-Event-ID` 续读与缓存窗口外的明确重同步错误。
- 实施 HTTP 请求体、连接、SSE 订阅、在途运行、事件缓存和运行时长限制。
- 处理客户端断线、取消竞态、运行超时和服务关闭的任务清理。

## 边界与约束

**Always**

- 取消只作用于指定 run；不得取消其他 run 或关闭整个服务。
- 客户端断开 SSE 不自动取消 Agent；取消必须通过 DELETE 或服务 shutdown。
- 所有限制在协议边界和运行时边界均有校验，满额时明确失败，不无限排队。
- 事件丢失时显式要求 session 重同步，不发送不连续的伪完整流。

**Never**

- 不用无界队列、无限缓存或无限等待来“保证”事件送达。
- 不吞掉 `CancelledError`，不把取消误报为普通 Agent 成功。
- 不让迟到的任务重新占用已释放的并发名额。
- 不改变 TCP server 已有的限额和关闭语义。

## 任务

- [ ] 定义 run 终态和取消/超时状态转换。
- [ ] 实现有界事件缓存、事件 id 和 Last-Event-ID 解析。
- [ ] 实现 DELETE 取消、运行 timeout 和 SSE 断线清理。
- [ ] 实现 HTTP 连接、请求体、订阅、并发和事件大小限制。
- [ ] 增加取消、断线重连、缓存淘汰、超限和 shutdown 测试。
- [ ] 在网页 UI 中显示取消中、已取消、重连中和需重新同步状态。

## 验收标准

- Given 一个运行正在执行，When 客户端请求 `DELETE /api/runs/{run_id}`，Then Agent task 收到取消信号，SSE 最终发送 `cancelled`，并释放在途运行名额。
- Given 客户端已收到事件序号 N 后断线，When 客户端带 `Last-Event-ID: N` 重新订阅，Then 服务从 N 之后的有界缓存继续发送，事件不重复且顺序稳定。
- Given 客户端请求的序号早于已淘汰的缓存窗口，When 客户端重新订阅，Then 服务返回明确的 `resync_required`，客户端可以通过 session 快照恢复，不伪造完整事件流。
- Given 请求体、连接数、SSE 订阅数、在途运行数或单次运行超过配置上限，When 客户端发起请求或运行持续，Then 服务返回稳定限流/超时错误或取消运行，不无限排队、不耗尽进程资源。
- Given SSE 客户端断线、取消竞态或服务关闭，When 清理逻辑执行，Then 订阅者、任务和并发登记最终释放，后续运行可正常开始。

## Definition of Done

- run 状态机明确区分 running、completed、failed、cancelled、timed_out。
- 事件 buffer 有界且事件 id 单调递增；Last-Event-ID 处理有覆盖测试。
- DELETE 取消、SSE 断线、超时和 shutdown 的 task ownership 不产生 orphan task。
- 资源限制和稳定错误码在 API 测试中覆盖，现有 TCP 限额行为不受影响。

## 代码地图

- `src/heagent/network/http_server.py`：取消、超时、订阅和关闭生命周期。
- `src/heagent/network/http_protocol.py`：终态事件、错误码和重同步响应。
- `src/heagent/cli_http.py`：run task factory 与服务级限额注入。
- `src/heagent/web/`：SSE 重连、取消和重同步 UI 状态。
- `tests/test_http_run_lifecycle.py`：取消、断线、重连、超时和清理测试。

## Review Status

Story 范围与验收标准已确认，待实现验证。

## Requirement Traceability

FR6–FR9; NFR5, NFR8; UX-DR3, UX-DR4, UX-DR6。
