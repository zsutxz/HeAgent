# Epic 47 声明式 BMad 敏捷工作流周期遗留项台账（deferred-work）

> **归并来源**：`_bmad-output/patches/_meta/deferred-work.md`（原跨周期技术债台账，2026-09-15 整理后退役）。
> **归档规则**：按条目**归属的 epic / 归属层**归档；本周期同时承担 epic 外 **engine 运行时治理增量**
> 的归档（与 `epic-47-声明式工作流与产物治理/spec-runtime-hygiene.md` 同域，engine 层不挂 Epic 编号，
> 进度另见 `docs/frame.md` 4.12）。
> **只登记已闭合项**——原始长文历史不再保留，结论全部指向代码、测试与 commit。
> **活动（未闭合）遗留项**仍在 [`implementation-artifacts/deferred-work.md`](../../implementation-artifacts/deferred-work.md)
> （例：bmad-build Step 07 未声明 step 级 `max_iterations`、Epic 46 资源读取的中间目录竞态后续）。

## 状态总览

| ID | 归属 | 条目 | 状态 | 闭合者 |
|----|------|------|------|--------|
| E47-D1 | engine 运行时治理（`ExecutionLedger` + 工具执行链） | ledger 记录在途被删（长时工具调用）：机制已证、施动者未定 | 已修复 2026-09-15 | commit `cc8cb3f` + `95ae3e6` |

---

## E47-D1 ledger 记录在途被删（长时工具调用）

- **来源**：线上故障取证——`logs/heagent-20260915-105024.log`，run `d435c6c5d5eb442f9c01330a474b0759`，2026-09-15 11:03–11:16。
- **现象**：`shell` 调 pytest 跑 385s，超 120s 租约后记录被「过期 `RUNNING` = 孤儿」规则删除；工具跑完回写 `complete()` 抛 `ValueError: Cannot complete non-existent key`，`execute_tool_call` 的兜底 `except` 把**成功的 18KB pytest 输出整段替换成** `Tool error: ...`，模型只好重跑（第二次 384s 同样死法）——**白跑约 13 分钟 + 结果丢失**。
- **取证**（施动者未能唯一归因，但机制已证）：
  1. 该 run **2/2 长调用**（385s / 384s）记录缺失，**8/8 短调用**记录均在且 `status=completed`——只有 `prune` 的「`RUNNING` + 租约过期」规则会呈现「只挑跑超租约的那两条删」的模式，整目录清理 / 外部删除无法只删这两条；
  2. 当天全部 `ledger prune` 日志为 08:51 / 08:53 / 08:54 / 09:53 / 10:21 / 10:31 / 10:32 / 10:36 / 10:50 / 11:17，**两个故障窗口（11:03:38–11:10:03、11:10:05–11:16:29）内没有任何一条**（11:17:04 属本会话启动，晚于两次失败）；
  3. 已排除：会话自身进程（唯一 prune 在 10:50:36，早于记录产生）、机器环境无 `*_RETENTION_*` 变量、`src` 从不把 `Settings` 导出到 `os.environ`、测试不 spawn CLI 子进程（全用 `CliRunner` 且 conftest 已置 `LEDGER_RETENTION_DAYS=0`）→ 施动者是**未写日志的进程**（直连 engine 的脚本，或某个 retention≠0 的测试进程），事后无法唯一归因。
- **处置（2026-09-15，commit `cc8cb3f` + `95ae3e6`）**——三层缓解，残余风险 LOW：
  1. **在途续租（根因已封）**：`agent/tool_execution._renew_ledger_lease` 在工具在途期间每 40s `heartbeat(lease_seconds=120)` 续租（`_LEDGER_LEASE_RENEW_INTERVAL=40` / `_LEDGER_LEASE_SECONDS=120`，acquire 亦显式传该租约）→ 让「租约过期 = 真孤儿」这个 `prune` 前提成立；heartbeat 返回 `None` 或 I/O 失败只 warning、不抛错。
  2. **回写容错**：`_record_ledger_outcome` 把回写包在独立 try 里，失败只 `logger.warning`——**绝不改写工具结果**；`ExecutionLedger.complete(..., recreate_if_missing=True)` 提供「容错完成」（记录被清则按「本次确实完成」重建为 `COMPLETED`，已 `COMPLETED` 时为幂等命中），**只在工具调用这一个调用点开启**，默认严格语义（防误键凭空建记录）不变。
  3. **可诊断性**：`complete`/`fail` 区分「真不存在」与「文件在但读不出来（损坏）」。
- **证据**：`src/heagent/agent/tool_execution.py:49,50,53,78,192,220`、`src/heagent/engine/ledger.py:170`；
  `tests/test_window_reset.py::test_inflight_tool_call_keeps_its_lease_fresh`、
  `::test_expired_orphan_is_prunable_but_result_and_cache_survive`（含「禁用续租时记录仍被删但结果存活」+ 告警断言）、
  `::test_complete_failure_keeps_successful_result`、`::test_fail_writeback_failure_keeps_error_result`、
  `::test_renewal_stops_when_record_is_gone`、`::test_renewal_survives_heartbeat_io_failure`；
  `tests/test_coverage_ledger.py::test_complete_recreate_if_missing_restores_idempotency_cache`、
  `::test_complete_recreate_if_missing_is_idempotent_on_completed`、`::test_complete_distinguishes_corrupt_record_from_missing`。
- **残留（低优先）**：若再出现「未写日志的进程 prune 真实 ledger」，可据新增的
  `ledger record ... vanished before completion` / `recreating as COMPLETED` warning 拿到精确时点再反查当时进程
  （当前证据链不足以回溯 2026-09-15 那次）。

### 契约（改工具执行链 / ledger 前必读）

`src/heagent/agent/tool_execution.py` 模块 docstring 已固化两条硬性约定：

1. **ledger 只是幂等缓存，不拥有工具结果**——回写失败（记录被 prune / 锁冲突 / 磁盘故障）必须只 warning，
   **绝不把成功的工具结果换成 error `ToolResult`**；
2. **长时工具在途期间必须续租**，否则任何进程的 `ExecutionLedger.prune()` 都会把记录当过期孤儿删除
   （prune 语义：`RUNNING` + 租约过期 = 孤儿，立即删，**不看保留期**）。

排查同类现象的手法：错误 `Cannot complete non-existent key: '<run_id>:<call_id>'` 意味着「acquire 时写过的记录在
工具跑完前消失了」——用 `sha1(key)` 反查 `.heagent/ledger/<sha1>.json` 是否存在、看 `logs/` 里工具耗时是否 >120s、
以及同一时段是否有别的进程 / 嵌套 pytest prune 过该目录（`findstr /s /n "Ledger pruned" logs\*.log`）。
