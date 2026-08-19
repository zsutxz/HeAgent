# HeAgent 交互与可扩展层周期 — Epics & Stories

> 周期编号：interaction（Epic 29+）| 日期：2026-08-19
> 本周期实现范围：Epic 29（审批闭环）+ Epic 30（会话恢复）。Epic 31-35 为 backlog。

---

## Epic 29 · 运行时审批闭环（P0-①）

**目标**：让 `PolicyEngine` 的 `APPROVAL_REQUIRED` 从「死判决」（executor 等同阻断）变为
可交互授权的裁决——库消费者注入 `ApprovalHandler`，CLI 交互模式注入 stdin 询问实现。

### Story 29-1 · ApprovalHandler 协议 + 默认 deny（引擎层）

- 新增 `src/heagent/engine/approval.py`：
  - `ApprovalDecision`（`StrEnum`）：`APPROVE` / `DENY`。
  - `ApprovalRequest`（Pydantic `BaseModel`）：`tool_name`、`reason`、`call`（`ToolCall`）。
  - `ApprovalHandler`（`typing.Protocol`）：`async def request(request: ApprovalRequest) -> ApprovalDecision`。
  - `DenyAllApprovalHandler`：返回 `DENY`（显式默认，语义等价于「未配置 handler」）。
- `EngineContainer` 新增字段 `approval_handler: ApprovalHandler | None = None`。
- AC：`ApprovalRequest` 可序列化；`DenyAllApprovalHandler.request` 返回 `DENY`。

### Story 29-2 · tool_execution 审批交互接入

- `src/heagent/agent/tool_execution.py` 的 `execute_tool_call`：在 `verdict` 计算后、`executor.execute`
  前，若 `verdict.mode is APPROVAL_REQUIRED` 且 `loop.engine.approval_handler is not None`：
  1. `decision = await handler.request(...)`；
  2. `APPROVE` → 将 `call.name` 追加进 `run_context.metadata["approved_tools"]`（列表），
     重新 `evaluate_tool_call` 得新 verdict，继续走 executor；
  3. `DENY` → verdict 保持 `APPROVAL_REQUIRED`，交给 executor 转 error（现状）。
- AC：授权后同 run 内同类工具不再询问（`_approval_granted` 命中）；未配置 handler 时零回归。

### Story 29-3 · CLI 交互式审批 + Settings 配置

- `Settings` 新增 `approval_tools: str = ""`（逗号分隔）。
- `EngineContainer.default()` 读取 `settings.approval_tools` 注入 `PolicyEngine(approval_tools=...)`。
- CLI 交互模式（`_run_chat`）注入 `ConsoleApprovalHandler`（经 `asyncio.to_thread(input)` 询问 `[y/N]`）；
  单次模式非 tty 时注入 `DenyAllApprovalHandler`（保持脚本化可预测）。
- `ConsoleApprovalHandler` 放在 `engine/approval.py`（CLI/GUI 复用）。
- AC：配置 `APPROVAL_TOOLS=shell` 后交互模式执行 `shell` 前询问；拒绝则工具报 blocked。

### Story 29-4 · 测试 + 文档

- 单测：`tests/test_approval.py` 覆盖协议、`execute_tool_call` 的 approve/deny 分支、零回归。
- 更新 `docs/frame.md`（4.12 engine 表）、`CLAUDE.md`/`AGENTS.md` 已知缺口（注明审批非安全边界）。
- AC：新增测试全绿；ruff/mypy 干净。

---

## Epic 30 · 会话恢复入口（P0-②）

**目标**：CLI 支持 `--continue` / `--resume <session_id>` 复用已有会话，而非每次随机新 id。

### Story 30-1 · CLI 选项 + 装配

- `_RUN_OPTIONS` 加 `--continue`（`continue_session`, `is_flag`）与 `--resume`（`resume_session`, str）。
- `run`/`_run_cli_impl` 透传两参到 `_run_chat`。
- AC：`heagent --continue` / `heagent --resume abc123` 可解析进入交互模式。

### Story 30-2 · `_run_chat` 会话复用

- `_run_chat`：`session = SessionStore()` 提前创建；`continue_session` 时 `recent_session_ids(1)` 取最近
  id 复用（无则回退新 id 并提示）；`resume_session` 时直接复用该 id。
- AC：`--continue` 后历史消息恢复；无历史会话时提示「无历史会话，新建」。

### Story 30-3 · 测试 + 文档

- 单测：`tests/test_cli.py` 覆盖 `--continue`/`--resume` 参数解析与会话复用逻辑。
- 更新 `README.md` 常用选项表。
- AC：新增测试全绿；ruff/mypy 干净。

---

## Backlog（后续会话）

| Epic | 主题 | 优先级 | 状态 |
|------|------|--------|------|
| 31 | 斜杠命令注册表 + 用户自定义命令 | P1 | **已完成（2026-08-19）** |
| 32 | Hooks 系统（用户可配置事件钩子） | P1 | backlog |
| 33 | Plan Mode / 只读模式 | P1 | **已完成（2026-08-19）** |
| 34 | 配置文件驱动角色 + 成本估算 | P2 | **已完成（2026-08-19）** |
| 35 | CLI 体验优化 + 技术债收尾（web_fetch guard_content / cron expr 诊断 / /init / web_search） | P2 |
