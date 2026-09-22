---
id: 48-6
title: TCP 回归测试与开发文档
status: ready-for-dev
parent_epic: E48
priority: P1
depends_on: [48-5]
created: '2026-09-22'
---

# Story 48-6：TCP 回归测试与开发文档

## 用户故事

作为维护者，我希望 TCP 能力具备完整的跨层回归证据和可复制文档，以便确认协议、生命周期、Agent 接线和原有功能均未回归，并让使用者可以安全启动和调用。

## 范围

- 收口协议、TCP Server、CLI、AgentLoop 适配的测试矩阵。
- 增加真实 loopback 进程内 E2E，不调用真实外部 Provider。
- 验证跨平台、覆盖率、ruff、format、mypy。
- 完成 README、文档索引、frame 和 `.env.example` 一致性检查。
- 不新增第二套实现功能。

## 回归矩阵

| 层 | 必测项 |
|---|---|
| Protocol | 字段、错误码、UTF-8、CRLF、超限、黄金 JSONL |
| TCP lifecycle | 启停、半包、断开、idle、drain、shutdown |
| Resources | 连接上限、inflight、request timeout、permit 回收 |
| Agent integration | StubProvider 成功、异常、取消、并发隔离 |
| CLI | help、默认值、覆盖值、普通模式不监听、非 loopback 告警 |
| Compatibility | 原 CLI/GUI/goal 构造路径与架构契约 |
| Docs | 命令/配置/安全说明与实现一致 |

## 任务

- [ ] 审计 48-1~48-5 的 AC 是否各有自动化测试，补遗漏而不复制测试。
- [ ] 增加端到端 loopback 测试：启动 server→发送 JSONL→StubProvider→接收响应→关闭。
- [ ] 增加并发两个请求的隔离测试。
- [ ] 增加客户端断开和服务 shutdown 后 pending task 检查。
- [ ] 增加协议黄金响应测试，防字段漂移。
- [ ] 运行默认全量测试与 coverage gate。
- [ ] 运行 Linux 平台语义 mypy；必要时使用现有 CI 等价方法复核。
- [ ] 更新 README 快速示例、配置、限制和安全声明。
- [ ] 更新 `docs/README.md` 导航和 `docs/frame.md` 架构事实。
- [ ] 回读 `.env.example`，确保每个 TCP Settings 字段都有说明且名称一致。
- [ ] 在 Epic 文档中记录实际验证结果，不伪造未运行命令。

## 验收标准

- Given 干净测试环境和 StubProvider，when 运行 TCP E2E，then 完成一条真实 socket 请求响应且不需凭据。
- Given 48-1~48-5 的每条关键 AC，when 审计测试矩阵，then 都有至少一个意图级测试证据。
- Given 全量默认测试，when 执行，then 无新增失败且 coverage >=87%。
- Given ruff、format 和 mypy Linux 语义检查，when 执行，then 全绿。
- Given README 示例，when 用户按示例启动和发送请求，then 字段、端口和响应格式与代码一致。
- Given安全文档，when 检查，then 明确无认证/TLS、默认 localhost、非生产边界和 OS/网络隔离要求。

## Definition of Done

- 所有已执行验证命令和结果写入 Story 验证段。
- 全量质量门禁通过或显式记录非本变更阻塞证据。
- 文档没有旧路径、旧字段名或与代码冲突的默认值。
- Epic 48 所有 Story 完成后才可把 `epic-48` 标为 done。
- 不自动 git commit；等待用户确认。

## 代码地图

- `tests/network/test_protocol.py`
- `tests/network/test_tcp_server.py`
- `tests/test_tcp_agent_integration.py`
- `tests/test_cli_tcp.py`
- `tests/test_architecture_contracts.py`
- `README.md`
- `.env.example`
- `docs/README.md`
- `docs/frame.md`
- `_bmad-output/sprint-status.yaml`

## 验证命令

```text
pytest tests/network tests/test_tcp_agent_integration.py tests/test_cli_tcp.py -q
pytest --cov=heagent --cov-fail-under=87
ruff check src tests scripts
ruff format --check src tests scripts
mypy src --platform linux
```
