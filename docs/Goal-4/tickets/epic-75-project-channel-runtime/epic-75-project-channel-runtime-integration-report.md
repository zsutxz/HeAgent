---
type: integration-report
code: E75-INT
epic: epic-75-project-channel-runtime
generated_at: 2026-11-23
step: step-08-system-integration-test
head: f42ab032
---

# E75 集成报告 · 项目通道运行时与投影注入（Step 08）

## 集成场景（跨 story）

| # | 场景目标 | 验证的 Done when / 不变量 | 判据命令 | 观察结果 |
|---|---|---|---|---|
| 1 | 列表投影只三字段（`id` / `name` / `available`），`path` 零回传 | R1 + AD-3 I10 + AD-7 | `pytest tests/test_ws_project_adapter.py -q` | passed |
| 2 | 顺序与注册表真源逐位一致（`default` 末位） | R1 | 同上 | passed |
| 3 | `MAX_PROJECTS=32` 边界（满表判 unreadable 而不溢出帧） | R1 | `pytest tests/test_project_registry_health.py -q` | passed |
| 4 | 六项落点全在项目根、启动工作区零新增 | R3 + §6.4 + Done when 2 | `pytest tests/test_http_console_project_run.py -q` | passed |
| 5 | 会话二分：续最近 / 无历史即新建 | R4 + Done when 3 | 同上 | passed |
| 6 | 提交 ack 收窄成 `SubmittedRun`（无 `session_id`） | R4 + §2.3-6 | `pytest tests/test_ws_project_adapter.py -q` | passed |
| 7 | 注册表不可读：列表 fail-soft（`registry_state="unreadable"` + default 仍在 + WARNING×1） | R5 + AD-7 | `pytest tests/test_project_registry_health.py tests/test_ws_project_adapter.py -q` | passed |
| 8 | 提交径 fail-loud（`project_registry_unreadable`），`default` 豁免 | R5 + AD-7 | 同上 | passed |
| 9 | 项目侧码逐字透传、不改写不折叠；未登记码不折叠成通用码 | R7 + AD-6 | `pytest tests/network/test_ws_project_submit.py tests/test_ws_project_adapter.py -q` | passed |
| 10 | 两处装配（嵌入服务 / `http-server`）注入**同一个**适配器实例 | R7 + AD-1 | `pytest tests/test_cli_http_lifecycle.py -q` | passed（本轮另加 `sandbox_backend` 注入断言） |
| 11 | `available=false` 的提交被拒且不建 run | R7 + Done when 5 | `pytest tests/test_http_console_project_run.py tests/network/test_ws_project_submit.py -q` | passed |

- 场景合并命令：`pytest tests/network/test_ws_project_commands.py tests/network/test_ws_project_submit.py tests/network/test_ws_project_admission.py tests/network/test_cli_ws_e2e.py -q` = **53 passed in 4.08s**。

## 质量门禁

- `python scripts/quality_gate.py`：**all gates passed**；`ruff` / `ruff format` / `mypy src`（240 files）/ `bandit -r src/ -ll`（No issues）。
- 契约快照五份 `[OK]`；覆盖率门 93.50%（阈值 87%）。

## 系统集成结论

**通过**。E75 的六条 entry 在真实控制台上咬合：投影只出三字段、注入点在两条启动路径同源、注册表坏时「列表 fail-soft / 提交 fail-loud」分工成立，无未决 Critical。
