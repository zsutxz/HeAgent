---
type: epic
code: E78
parent: brief
slug: epic-78-open-items-followthrough
covers: ["R1", "R2", "R3"]
sources: ["docs/Goal-4/tickets/epic-77-remote-contract-hardening/epic-77-remote-contract-hardening-retrospective.md", "_bmad-output/open-items.md"]
after: ["epic-77-remote-contract-hardening"]
risk: low
refined: true
status: done
---

# E78 · 活动台账的仓库内跟办（幂等窗口可观测 / web_search 冒烟前置 / 三项操作卡）

## Description

E77 收口后台账 4 条活动项（A55 / A65 / A67 / A76）**全部等外部触发**：实测本容器 `docker` 不可用
（A67 硬阻塞）、`WEB_SEARCH_API_KEY` 未配置且无冒烟脚本（A55 缺前置）、宿主 `netstat` 与客户端 pin
在仓外（A76）。本 epic 只做**仓库内能做的三件**，把「等外部」的等待成本压到一条命令：

① E77 复审遗留的「幂等窗口无可观测性」补日志与判据；② 写 A55 的冒烟脚本（无 key 显性退出，
有 key 一条命令出四段结论）；③ 把 A55 / A67 / A76 的「谁在哪台机器上跑什么、期望看到什么」写进台账
正文，减少来回确认。

## Requirements

- **R1**（← E77 retrospective「可观察但未做」）幂等窗口的两个生命周期事件各有**一条 debug 日志**：
  容量淘汰 `ws event=idempotency_evicted reason=capacity`、键被移出窗口
  `ws event=idempotency_dropped reason=failed|cancelled`。**`request_id` 不进日志**（与「不回显、
  不落 `x-request-id`」同一立场），只记 `project_id` 与 reason；TTL 过期清理**不打日志**（正常回收，
  噪声）。判据 = `caplog` 断言事件名、reason、project_id，且断言日志里没有 `request_id`。
- **R2**（← A55 前置）新增 `scripts/web_search_smoke.py`：四段判据（config 解析 → 引擎调用 →
  工具面截断 → 注入围栏）逐段打印 `[OK]/[FAIL]`，**key 永不打印**（只报「已配置/未配置」与长度）。
  无 key 且未加 `--self-check` ⇒ **exit 2** + 明确提示怎么配；`--self-check` 走离线段（预算常量 +
  合成注入文本跑 `guard_content`），无 key 也能自检脚本本身。判据 = 子进程跑 `--self-check` exit 0、
  隔离 cwd 无 key 跑主流程 exit 2 且提示含 `WEB_SEARCH_API_KEY`。
- **R3**（← A55 / A67 / A76）三条台账正文各补「操作卡」：命令原文 + 期望输出 + 回填位置。
  不改活动条数与 ID 集合（仍 4 条 / `A55 A65 A67 A76`），`tests/test_deferred_id_registry.py` 三处计数
  与速读节集合不变。

## Outcome

- 线上出现「同键重复起 run」时，日志里能直接看到是**容量淘汰**还是**失败移出**，不必只靠
  `run_conflict` 现象反推。
- 用户拿到 `WEB_SEARCH_API_KEY` 后，一条 `python scripts/web_search_smoke.py --query …` 就能闭合 A55，
  不必先读实现。
- A67 / A76 的闭合动作不再需要我复述：台账正文自带命令与期望输出。

## Boundaries

- 不做指标 / 计数导出（不加 `/api/status` 字段、不做 Prometheus）：只加两条 debug 日志。
- 冒烟脚本**不落盘、不入库凭证**：不写 workspace 记忆、不写 `.heagent/`、不把 key 打印或写进日志。
- 不改 web_search 工具与引擎的行为（截断预算、钳位区间、围栏口径一律不动）。
- 不新增台账 A 号、不改活动计数；A65 仍 `frozen`（用户裁定暂停）。

## Done when

- `pytest tests/test_ws_submission_cache.py tests/test_ws_project_adapter.py tests/test_web_search_smoke_script.py -q` 全绿。
- `python scripts/web_search_smoke.py --self-check` exit 0；无 key 跑主流程 exit 2 且提示明确。
- `pytest tests/test_deferred_id_registry.py tests/test_docs_links.py -q` 全绿；`mkdocs build --strict` 0 warning。
- `ruff check` / `ruff format --check` / `mypy src` 与 HEAD 同谱。

## References

- E77 回顾「四、留给下一轮的东西」（幂等窗口可观测缺口）
- `_bmad-output/open-items.md`（A55 / A67 / A76 正文）
- `src/heagent/tools/builtins/web.py`（工具面截断与围栏）、`web_search_engine.py`（引擎注册面）

## Notes

- 2026-11-24 Decision：**不新登 A77**。可观测面在本 epic 内当场实现并闭合，立一个「立完即闭合」的 A 号
  只会给台账加一次迁移成本；闭合证据直接写进 E77 回顾的那条「可观察但未做」。
- 2026-11-24 Decision：冒烟脚本取 `scripts/` 一次性工具形态（与 `ws_manual_probe.py` 同档），
  不进 CLI 命令面——它要真打外部 API，不该出现在 `heagent --help` 里。
