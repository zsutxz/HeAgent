---
id: 48-5
title: 网络入口安全边界与可观测性
status: ready-for-dev
parent_epic: E48
priority: P1
depends_on: [48-4]
created: '2026-09-22'
---

# Story 48-5：网络入口安全边界与可观测性

## 用户故事

作为服务运行者，我希望 TCP 入口默认只暴露给本机，并为每次请求提供有限、可关联且不泄密的诊断信息，以便实验使用时能识别风险和定位失败。

## 范围

- localhost 默认和非 loopback 告警。
- request id、连接阶段、耗时、结果状态和错误码日志。
- 日志/响应信息最小化和敏感信息边界。
- 与现有 EngineEvent、JSONL rollout 和 CLI stderr/stdout 边界说明。
- README、`docs/frame.md` 的安全声明与模块说明。

## 边界与约束

**Always**

- TCP 输入按不可信用户输入处理。
- 非 loopback 监听明确提示“无认证、无 TLS、非生产安全边界”。
- 日志包含 request id 和稳定错误码。
- 观测失败只 warning，不改写业务响应。
- 复用现有 Agent/Engine 埋点，不复制工具和 Provider 事件。

**Never**

- 不记录 API Key、凭证环境变量或完整 traceback 到客户端。
- 不默认记录完整 prompt、工具原始输出或可能含凭证的响应体。
- 不宣称 SafetyGuard、PolicyEngine 或 sandbox 能替代网络认证/OS 隔离。
- 不因“仅 localhost”而把客户端视为可信。

## 任务

- [ ] 使用 `ipaddress` 或等价标准库逻辑判断 loopback；主机名解析语义需明确测试。
- [ ] 非 loopback 启动时向 stderr 和 logger 输出一次明确告警。
- [ ] 为 accepted/rejected/processing/completed/failed 阶段添加结构化日志字段。
- [ ] 记录 elapsed_ms，不记录无界 prompt 正文。
- [ ] 将内部异常映射为协议错误码，详细 traceback 只进入受控 debug/error log。
- [ ] 明确 TCP response、CLI stdout/stderr、rollout JSONL 三条输出通道。
- [ ] 更新 README 使用示例与风险说明。
- [ ] 更新 `docs/frame.md` 模块 DAG、CLI 入口、数据流、配置表和安全边界。
- [ ] 如架构契约新增 network 依赖规则，更新可执行断言。

## 验收标准

- Given 默认 host，when 启动，then 监听 localhost 且不输出外部暴露告警。
- Given host=`0.0.0.0` 或非 loopback 地址，when 启动，then stderr/log 明确提示无认证和非生产风险。
- Given 请求成功，when 完成，then 日志可由 request id 关联 accepted→completed 并含耗时。
- Given 请求失败，when 完成，then 日志含稳定错误码，客户端不收到 traceback、API Key 或绝对路径。
- Given logger/事件 sink 抛异常，when 处理请求，then业务响应不被改成失败。
- Given `EVENTS_ROLLOUT_ENABLED` 任一状态，when TCP 请求完成，then TCP 响应不混入 rollout 事件行。

## Definition of Done

- 安全告警和日志脱敏有自动化测试。
- README/frame 与代码事实一致。
- 没有把 TCP 描述成生产级服务或安全边界。
- 现有安全声明未被削弱。

## 代码地图

- `src/heagent/network/tcp_server.py`：连接与请求日志。
- `src/heagent/cli.py`：启动告警和本地展示。
- `src/heagent/events/`：只读复用边界，不复制埋点。
- `README.md`：使用与风险。
- `docs/frame.md`：架构权威。
- `tests/test_cli_tcp.py`：告警与输出通道。
- `tests/network/test_tcp_server.py`：日志失败不影响业务。

## 验证命令

```text
pytest tests/test_cli_tcp.py tests/network/test_tcp_server.py tests/test_events_jsonl.py -q
ruff check src tests
ruff format --check src tests
mypy src --platform linux
```
