# 故障排查

> 状态：当前实现指南（2026-09-22，Phase 5 C3）。症状 → 诊断命令 → 相关模块。
> 安全立场提醒：`SafetyGuard` / `PolicyEngine` / sandbox 后端均为 defense-in-depth、
> **非真正安全边界**（见项目根 `CLAUDE.md`）——排查安全类问题时勿把降级当隔离成功。

| 症状 | 先跑什么 | 看哪里 |
| --- | --- | --- |
| 启动即 `SystemExit(1)`，报 `[mcp config error]` | 检查 `.mcp.json`：JSON 合法性、stdio server 有 `command`、http server 有 `url`、`${VAR}` 已在环境设置 | `tools/mcp/config.py`（fail-fast 契约） |
| MCP server 连不上 / 工具没出现 | 看 stderr 是否有 `[mcp] server 'X' 连接/发现失败，已隔离：<原因>`（其余 server 不受影响） | `tools/mcp/manager.py`（per-server 隔离 + `discovery_failures`）、`tools/mcp/client.py`（transport） |
| MCP 工具调用报 `MCP server 'X' disconnected` | server 运行中断连（ping 健康探测失败即注销其工具） | `manager.py:_watch`；重进会话或修 server |
| shell 命令返回 `exit_code=-1 ... timed out` | 命令超过工具 timeout；长任务拆步或调大该工具超时参数 | `tools/sandbox/process.py`（`_supervise_subprocess`，超时/取消都先杀进程树） |
| Windows 上沙箱行为像"没沙箱" | 看日志 `WinJobBackend not available; falling back to Passthrough`（WinJob 仅进程级隔离，本就无 FS/网络隔离） | `tools/sandbox/winjob.py`、`docs/frame.md` 4.4 安全声明 |
| `Tool error: ...` 进了 LLM 上下文 | 正常路径：工具异常转 `is_error=True` 结果而非中断循环；`error_kind` 字段给失败分类 | `engine/executor.py`、事件 `tool_call_failed` |
| 工具被拦：`safety_blocked` / 策略阻断 | SafetyGuard 黑名单（shell 命令）或 PolicyEngine 裁决；blocked 事件 details 有 `reason`/`mode` | `tools/safety.py`、`engine/policy.py` |
| `Path escapes current workspace` | 文件工具路径越出工作区围栏；检查相对路径基准（cwd 锚定）与符号链接 | `tools/path_safety.py` |
| skill 读取报 `final path component is a symlink` / `not a regular file` | safe-open 内核拒绝符号链接替换 / 非常规文件（安全加固，非 bug） | `tools/path_safety.open_text_under_root` |
| `/goal` 步骤 BLOCKED：`output is missing section: ...` | 输出缺 `validation:` 声明的章节（标题须独占一行）；prompt 的 "Gate requirements" 段已提前告知 | `engine/workflow_runner.py`（`required_sections`）、`goal/application.py` |
| `/goal` 恢复报 checkpoint 不匹配 | `workflow.json` 与当前 `workflow.md`/brief.md 引用关系落空 → `WorkflowCheckpointError` 显性失败（不回退 legacy） | `engine/checkpoint.py`、`goal/application.py:restore_runner` |
| replay 打不开 rollout | `heagent replay <path>`；坏行跳过并告警（crash 前缀可回放）；字段版本见 `schema_version` | `events/sink.py`、`events/protocol.py` |
| 覆盖率门禁失败（本地 Py3.13 --cov） | 已知 pydantic-settings + coverage 组合 bug，非代码问题；CI（3.11）不受影响 | `scripts/quality_gate.py`、memory/项目记录 |
| GUI 看不到工具进度 | GUI 读 EngineEvent 总线（非 RunEvent）；确认入口把 GuiEventObserver 挂上了 `engine.events` | `gui/observers.py`、`gui/widgets/event_log.py` |
| GUI 显示与 CLI 文案不一致 | GUI 经 stderr 重定向转发 CLI 文案（行为冻结）；workflow 推进文案由 `cli_goal` 渲染 | `gui/bridge.py`、`cli_goal._goal_declarative_advance` |

## 诊断命令速查

```bash
# 全量质量门禁（pytest + 覆盖率 + ruff + mypy，fail-fast）
python scripts/quality_gate.py

# 只跑架构契约（反向依赖 / os.open 白名单 / 事件黄金契约等）
python -m pytest tests/test_architecture_contracts.py tests/test_events_jsonl.py -q

# 性能基准（不进默认回归；基线 autosave 到 ./benchmark-data/）
python -m pytest -m benchmark -q
# 回归阈值检查（对比首轮基线，超 50% 即失败——数量级守护）
python -m pytest -m benchmark -q --benchmark-compare=0001 --benchmark-compare-fail=min:50%

# 回放一次 run 的事件流
python -m heagent replay <rollout.jsonl>          # 人读渲染（含 [Nms] / error_kind）
python -m heagent replay <rollout.jsonl> --json   # 原始 JSONL
```
