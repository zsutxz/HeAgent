---
step: step-08-system-integration-test
goal: Goal-4
status: completed（等最终放行 approve）
generated_at: 2026-11-23
head: f42ab032
---

# Step 08 · 系统集成与测试（Goal-4：WS 远程项目通道）

## 范围与方法

- 覆盖 3 个 epic / 17 条 entry（E74 5 条、E75 6 条、E76 6 条），逐 epic 集成报告落
  `tickets/<E编号>-<slug>/<E编号>-<slug>-integration-report.md`。
- 质量门禁只用**仓库自己的验证入口**：`scripts/quality_gate.py`（契约快照 → goal 冒烟 → 全量回归+覆盖率 → ruff / format / mypy / bandit）
  + `mkdocs build --strict`（文档门）+ `scripts/contract_snapshot.py --check`（五份基线）。
- 场景清单由 Step 08 子会话（角色 `tester`）按三份 epic 的 `Done when` 与架构 spine 的 AD / 不变量拟定；命令与结果由宿主亲自执行（下表即原始观察）。

## 评审发现

| # | 严重度 | 发现 | 处置 |
|---|---|---|---|
| 1 | —（规格） | E76 票面 R2 写「项目已有在途 run 回 `project_busy`」：生产 WS 链上真实回的是 `run_conflict`（WS 提交不带 `session_id`、恒续最近会话），`project_busy` 只由 HTTP 删项目端点产生 | 已在 epic Notes 记 `bad_spec`；本轮用例按 `run_conflict` 写（`test_project_runs_share_the_single_inflight_allowance` 真链路证实） |
| 2 | —（口径） | E76 R7 写「4 份契约快照」，实测 **5 份**（含 `error_codes.json`） | 已在 epic Notes 记；门禁按 5 份核 |
| 3 | —（规格） | E75 的 `project_service is None ⇒ cancel_run 被拒` 子句被裁定规格过宽、不实现 | 已在 epic Notes 记；本轮不改 |
| 4 | Low | 「通道未装配」与「帧字段拼错」共用 `invalid_request`，`message` 不进 `transport_errors` 契约面 ⇒ 客户端只能靠文案分流 | **待用户裁决**（`brief.md` 延期项 R3 M-7） |
| 5 | Low | 提交无幂等键：客户端自动重试提交帧会重复建 run | **待用户裁决**（`brief.md` 延期项 R3 M-4）；默认处置 = 只重试订阅（带 cursor） |
| 6 | Low（残余风险） | `HttpProjectConsole` 的「同项目 ≤1 在途」依赖既有 check-then-act，多入口（HTTP + WS）并发时无锁；本 epic 的判据只在单入口时序下成立 | 记录，不扩范围（架构 §7.8 已列为刻意留开项） |
| 7 | Low（残余风险） | `projects` 帧在只读 listener 上零可达路径（AD-8 与 §4.1 冲突，E75 按 §4.1 落地）；`lan` 面会暴露项目名 | 记录（E75 Notes H-2 / 架构 §7.7），未决「是否需要只读项目清单」仍待用户裁决 |

- **未决 Critical：0**。

## 质量门禁

| 门 | 命令 | 观察结果 |
|---|---|---|
| 仓库一键门（6 门，fail-fast） | `python scripts/quality_gate.py` | **all gates passed** |
| — 契约快照 | （门内第 0 门）`scripts/contract_snapshot.py --check` | 五份 `[OK]`：`public` / `routes` / `exceptions` / `transport_errors` / `error_codes` |
| — goal 冒烟 | `pytest tests/test_goal_workflow_smoke.py -q` | 2 passed in 1.81s |
| — 全量回归 + 覆盖率 | `pytest -m "not integration and not benchmark" --cov=heagent --cov-fail-under=87` | **5869 passed / 17 skipped / 30 deselected / 1 xfailed**，覆盖率 **93.50%**（阈值 87%）in 427.57s |
| — ruff lint / format | `ruff check src tests scripts examples` / `ruff format --check …` | All checks passed / 508 files already formatted |
| — mypy | `mypy src` | Success: no issues found in 240 source files |
| — bandit | `bandit -r src/ -ll` | No issues identified |
| 文档门 | `mkdocs build --strict` | 0 warning（7.52s） |
| 逐 epic 集成场景 | 见各 epic 报告 | E74 116 passed · E75 53 passed · E76 31 passed |
| 跨 epic 端到端 | `pytest tests/network/test_ws_e2e.py tests/network/test_ws_cancel_run.py tests/network/test_ws_auth.py -q` | 83 passed in 6.12s |

## 系统集成结论

**通过（等最终放行）**。三条 epic 在真实装配下互相咬合，`tickets.py status` 三棵树 `problems` 全空、无 `blocked`、无 `unknown`：

- **主路径（ADR-005 验收基线）**：列项目 → 两项目各提交 1 run → 事件流完整到终态 → 取消其一（另一条活到终态）→ 断线凭 `last_event_id` 续流无空洞。替身版（`test_ws_remote_flow.py`，精确交叉计数）与真 listener 版（`test_ws_remote_flow_live.py`，真 `WsServer` + 真 `HttpRunService` + 真 `AgentLoop`）**都跑过**——单文件跑通不等于五步全证，故两条并列记录。
- **失败路径**：未知项目 ⇒ `unknown_project` 且零副作用；注册表不可读 ⇒ 列表 fail-soft（`registry_state="unreadable"` + `default` 保留）、提交 fail-loud（`project_registry_unreadable`）；通道未装配 ⇒ `invalid_request` 且不静默按启动工作区执行；run 已清理 ⇒ 具名错误帧而非空流；名额类三码（`run_conflict` / `total_inflight_limit` / `project_busy` 属 HTTP 删项目面）逐字透传。
- **恢复路径**：`?last_event_id=N` 续流首帧 ≤ N+1 且连续到终态；窗口不足先响 `resync_required`；取消后仍可订阅并补齐至 `cancelled` 终态。

**结论**：Goal-4 的三条 epic 满足各自的 `Done when`，系统级无未决 Critical；仅剩 7 条已登记的低风险/待裁决项（见「评审发现」），其中 2 条（#4 / #5）与 1 条（#7 后半）需用户裁决，均不阻塞放行。
