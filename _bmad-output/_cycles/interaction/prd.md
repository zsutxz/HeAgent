# HeAgent 交互与可扩展层周期 — PRD

> 周期编号：interaction（Epic 29+）| 日期：2026-08-19

## 功能需求（FR）

### Epic 29 · 运行时审批闭环（P0-①）

| FR | 需求 | 验收要点 |
|----|------|----------|
| FR-A1 | 定义 `ApprovalHandler` 协议 + `ApprovalDecision`（APPROVE/DENY） | `engine/approval.py`；Protocol 结构化子类型，无强制继承 |
| FR-A2 | `EngineContainer` 支持注入 `approval_handler`（默认 None = auto-deny） | 默认行为与现状逐字段一致（零回归） |
| FR-A3 | `execute_tool_call` 在 `APPROVAL_REQUIRED` 且配置 handler 时，先询问；APPROVE 写入 `metadata["approved_tools"]` 后**重新裁决**并执行；DENY 等同现状阻断 | 授权后同 run 内同类工具不再重复询问 |
| FR-A4 | CLI 交互模式注入交互式审批（stdin 询问）；单次模式非 tty 时保持 auto-deny | 不阻塞脚本化调用 |
| FR-A5 | `Settings.approval_tools`（逗号分隔）→ `EngineContainer.default` 注入 `PolicyEngine.approval_tools` | 用户可声明哪些工具需审批 |

### Epic 30 · 会话恢复入口（P0-②）

| FR | 需求 | 验收要点 |
|----|------|----------|
| FR-B1 | CLI 加 `--continue`（继续最近会话）与 `--resume <session_id>`（指定会话） | 仅交互模式生效；单次模式忽略 |
| FR-B2 | `_run_chat` 复用最近/指定 session_id 而非每次随机生成 | 复用 `SessionStore.recent_session_ids`/`load` |
| FR-B3 | 无历史会话时 `--continue` 降级为新会话并提示 | 不崩溃、有提示 |

### P1/P2 展望（本周期规划、后续会话实现）

- FR-C：斜杠命令注册表 + 用户自定义命令（Epic 31）
- FR-D：Hooks 系统（Epic 32）
- FR-E：Plan Mode / 只读模式（Epic 33）
- FR-F：配置文件驱动角色 + 成本估算（Epic 34）
- FR-G：CLI 体验优化 + 技术债收尾（Epic 35）

## 非功能需求（NFR）

| NFR | 要求 |
|-----|------|
| NFR-1 | 零核心回归：未配置审批/未传 `--continue` 时行为不变 |
| NFR-2 | `AgentLoop`/`Provider`/`Tool` 核心零改动；新增代码集中在 `engine/approval.py` + `tool_execution.py` 局部 + `cli.py` 装配 |
| NFR-3 | 数据模型用 Pydantic；跨模块禁止 raw dict（审批请求用 Pydantic） |
| NFR-4 | 全 async；审批询问在 `asyncio.to_thread(input)` 中执行避免阻塞事件循环 |
| NFR-5 | 安全立场诚实：审批非安全边界（`PolicyEngine` 本就非真正边界），不制造「审批=安全」假象 |

## 覆盖矩阵

| Epic | FR | Story |
|------|-----|-------|
| 29 | FR-A1~A5 | 29-1~29-4 |
| 30 | FR-B1~B3 | 30-1~30-3 |
