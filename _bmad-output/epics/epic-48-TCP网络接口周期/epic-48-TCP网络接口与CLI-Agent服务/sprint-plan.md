# Epic 48 Sprint Plan：TCP 网络接口与 CLI Agent 服务

> 制定日期：2026-09-22（中国标准时间）
> Epic 状态：in-progress
> 执行策略：单 Story WIP=1；依赖完成后再进入下一 Story

## Sprint Goal

以最小、可验证、默认安全的方式，为 HeAgent 增加显式 TCP Server CLI 入口，使外部客户端能通过 UTF-8 JSON Lines 发送 prompt，并接收 AgentLoop 的结构化最终结果。

## Definition of Ready

Story 进入实现前必须：

- 前置 Story 为 done。
- Story 文件中的范围、Never、AC、DoD、代码地图和验证命令已完整。
- 不存在需要重新决定的产品方向；如发现 PRD/Architecture 冲突，先修规划而不是边写边猜。
- 工作树中的既有用户改动已识别，不混入本 Story。

## 执行顺序

| 顺序 | Story | Sprint | 优先级 | 依赖 | 可演示切片 |
|---:|---|---|---|---|---|
| 1 | 48-1 TCP 协议模型与消息边界 | Sprint 1 | P0 | 无 | 纯函数解析请求并产出黄金 JSONL 响应 |
| 2 | 48-2 异步 TCP Server 生命周期 | Sprint 1 | P0 | 48-1 | fake handler 完成真实 loopback 请求响应 |
| 3 | 48-3 AgentLoop 请求适配与 CLI 接线 | Sprint 2 | P0 | 48-2 | `heagent tcp-server` + StubProvider 端到端 |
| 4 | 48-4 并发、超时与资源限制 | Sprint 2 | P0 | 48-3 | 并发洪峰/超时可控且无资源泄漏 |
| 5 | 48-5 网络入口安全边界与可观测性 | Sprint 3 | P1 | 48-4 | 非 localhost 告警与 request id 诊断 |
| 6 | 48-6 TCP 回归测试与开发文档 | Sprint 3 | P1 | 48-5 | 全量质量门禁 + 可复制使用文档 |

## Sprint 1：协议与传输骨架

### 目标

建立完全独立于 AgentLoop 的协议和 TCP 生命周期，使 fake handler 能通过真实 loopback 完成单请求单响应。

### 进入准则

- PRD 与 Architecture 已完成。
- Story 48-1/48-2 为 ready-for-dev。

### 退出准则

- 协议黄金测试通过。
- 半包、非法 JSON、超限、客户端断开和 shutdown 有测试。
- `network/` 运行期不依赖 cli/agent/providers/engine。
- 无 pending task/writer 泄漏。

### 风险

- `StreamReader` limit 与 `readline()` 超限异常语义在不同 Python 版本下需实测。
- 错误响应写回时客户端可能已断开，必须 best-effort。

## Sprint 2：Agent 接线与资源治理

### 目标

让 CLI TCP Server 使用现有 Agent 运行时，并对昂贵请求施加明确并发和时间上限。

### 进入准则

- Sprint 1 退出准则全部满足。
- AgentLoop 并发复用能力有源码/测试证据。

### 退出准则

- `heagent tcp-server --help` 可用。
- StubProvider TCP E2E 通过。
- 普通 CLI 不监听端口。
- connection/inflight/idle/request/shutdown 限制生效。
- 取消后 permit 和任务全部回收。

### 风险

- AgentLoop 含 `last_usage`、`active_tool` 等可变状态，不能未经验证跨请求并发共享。
- CLI 组合根 monkeypatch seam 较多，抽装配 helper 时须保留调用路径。

## Sprint 3：安全、观测与交付收口

### 目标

明确实验性网络入口的安全边界，提供最小可诊断性，并完成跨层回归和文档。

### 进入准则

- Sprint 2 可演示切片稳定。
- 默认限制与 Settings/CLI 字段名已冻结。

### 退出准则

- 默认 localhost；非 loopback 显示无认证/TLS 告警。
- 日志可关联 request id、状态和耗时，且不新增无界敏感正文日志。
- 全量 pytest、coverage、ruff、format、mypy 通过。
- README、`.env.example`、docs/frame 与实现一致。

### 风险

- 不能把 localhost 或 SafetyGuard 描述为认证/安全边界。
- TCP JSONL 与 rollout JSONL 名称相似，文档必须明确通道不同。

## Story 状态推进规则

```text
ready-for-dev → in-progress → review → done
```

- 同时最多一个 Story 为 `in-progress`。
- Story 验证失败不得标 done。
- Critical 评审发现必须在当前 Story 修复并重跑受影响测试。
- 跨 Story 改动仅在阻塞当前 Story 且符合依赖边界时允许，否则记录到后续 Story。
- Epic 仅在 48-1~48-6 全部 done 后改为 done。

## 总体验收

- 外部客户端通过 TCP JSON Lines 调用 HeAgent 并收到对应最终结果。
- 非法、超长、超时、断开和并发请求不会使服务崩溃或泄漏资源。
- TCP 输入不能修改服务端 Provider、system prompt、工具或沙箱配置。
- 原有 CLI、GUI、`/goal`、Python API 和质量门禁无回归。
- 安全边界与非生产定位在代码、CLI 和文档中一致。
