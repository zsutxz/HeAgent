---
title: 'Story 67.2 增强工具执行审计日志'
type: feature
ticket: 2
created: '2026-11-18'
status: done
baseline_revision: '0b1b156'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'src/heagent/pub/audit.py'
  - 'src/heagent/engine/executor.py'
  - 'src/heagent/cli/audit_cmd.py'
  - 'tests/test_audit_log.py'
---

## Intent

工具执行已有 `engine/observability.py` 的事件总线与 rollout jsonl，但**没有可导出的审计面**：
事件在进程内有界 deque 里、rollout 是 run 级快照，缺「时间戳 / 操作者 / 工具名 / 参数 / 结果」
的稳定结构，也没有查询/导出接口。

**Approach：** 在 `pub/` 层新增追加式审计写入（JSONL，逐行 Pydantic 模型），把工具执行完成事件
镜像进去；提供 `heagent audit` 子命令（list / export），支持按时间窗与工具名过滤。

## Verify

- 每次工具执行落一行：`ts` / `operator`（会话或进程标识）/ `tool` / `args`（脱敏）/ `status` /
  `duration_ms` / `error_kind`；
- 参数脱敏走既有 `pub/safe_logging`（密钥不落盘），有测试钉死；
- `heagent audit export --since ... --tool ...` 输出 JSON 行可被 `json.loads` 逐行解析；
- 写入失败不影响工具执行（fail-soft），且日志明示。

## Boundaries

- 不替换 observability 事件总线（审计是旁路消费者，不改事件契约）。
- 审计文件默认落 `<项目状态根>/audit/`，不进版本库。

## Implementation（实测）

- 落点：`pub/audit.py`（追加式 JSONL + `redact_mapping` 脱敏 + `record_tool_execution` / `resolve_audit_path`）、
  `cli/audit_cmd.py`（`heagent audit list|export|verify`）、`engine/executor.py::ToolExecutor.execute` 的审计包围。
- 一次执行一行：`ts` / `operator`（`<user>@pid<pid>` + session/run 后缀）/ `tool` / 脱敏参数 / `status`（ok/error/blocked）
  / `duration_ms` / `error_kind`；写入 fail-soft（异常只 WARNING，不改返回值，也不改异常面）。
- `run_context` 是鸭子契约：缺 `session_id` / `workspace_root` 的替身按「无该归属」处理（既有并发测试用它）。
- 实测：`pytest tests/test_audit_log.py -q` → 13 例全绿；`heagent audit export --since … --tool …` 输出逐行可 `json.loads`。
