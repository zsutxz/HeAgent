---
title: '56-7 文档、契约与质量门'
type: 'feature'
created: '2026-10-24'
status: 'done'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: 'bab1dc5c0f6e23f9eb397a6aaf1711803cdf9bc9'
context: []
---

<!-- 交付物与验收边界 = epics.md 期二 56-7 行；冻结决策 D14 见 brief.md。 -->

<frozen-after-approval reason="human-owned intent — do not modify unless user renegotiates">

## Intent

**Problem:** 双监听把「谁能连、能连到什么」拆成两份出口，若文档仍按期一的单监听口径写，运维会误判暴露面；
契约测试若只钉「WS server 无 HTTP 面」，则「对外 listener 不含终端通道」这条期二核心不变量没有可执行判据。

**Approach:** 把期二拓扑写进 `docs/frame.md`（配置表 +4 键、模式派生表补「主=本地 / 副=对外」行）、
`AGENTS.md` 安全声明（双监听口径，立场不变）、`deploy/README.md`（部署示例），并在
`tests/test_architecture_contracts.py` 加一条可执行契约：对外 listener 的 WebSocket 路由集恰为
`{提交, 订阅}`。

## Boundaries & Constraints

**Always:**
- 文档只写实测过的行为；任何「更安全」的扩大宣称禁止（沿用期一立场：入口面非安全边界）
- `AGENTS.md` 安全声明补双监听口径，但**不改**既有「本地模式无认证 / 对外认证不是绝对边界 / OS 沙箱兜底」三条
- 契约判据必须能在缺依赖环境（未装 starlette）下明确 skip 或 fail-loud，不得静默假绿
- 全量门禁实跑并登记**实测数字**（覆盖率百分比、passed 数），不写估算

**Never:**
- 不改 `WS_*` 既有键语义
- 不把「双监听 = 生产级多租户」写进文档（D6/期二冻结边界：仍是单用户共享状态机）
- 不为了门禁绿而放宽既有断言

</frozen-after-approval>

## I/O & Edge-Case Matrix

| 场景 | 输入/状态 | 预期行为 |
|---|---|---|
| 契约判据 | 构造对外 app | 路由集 == `{"/api/runs/ws", "/api/runs/{run_id}/ws"}` |
| 契约判据 | 构造本地 app + hub | 路由集含 `/api/cli/ws` |
| 文档检索 | `grep "WS_EXTERNAL_HOST" docs/frame.md .env.example deploy/README.md` | 三处均命中 |
| 文档检索 | `grep -n "双监听\|dual" AGENTS.md` | 命中双监听口径段 |
| 质量门 | `scripts/quality_gate.py` | 全绿（含 bandit） |

## Code Map

- `docs/frame.md` — §4.17/4.18 双监听拓扑 + 配置表
- `AGENTS.md` — 安全声明补段
- `deploy/README.md` — 部署示例
- `tests/test_architecture_contracts.py` — 端点集契约

## Tasks & Acceptance

**Execution:**
- [ ] `docs/frame.md` — 拓扑与配置表
- [ ] `AGENTS.md` — 安全声明
- [ ] `deploy/README.md` — 示例
- [ ] `tests/test_architecture_contracts.py` — 端点集契约
- [ ] 全量门禁实跑 + 登记

**Acceptance Criteria:**
- Given 契约测试，when 构造对外 app，then 路由集恰为两条（不含 CLI 旁路）
- Given 三份文档，when grep 新键，then 均命中且描述一致
- Given 全量门禁，when 运行，then `pytest` / ruff / mypy / bandit / `quality_gate` 全绿（数字登记）

## Verification

**Commands:**
- `pytest tests/test_architecture_contracts.py -q`
- `pytest -q --ignore=tests/test_cli_http_lifecycle.py`
- `python scripts/quality_gate.py`
- `ruff check src tests && ruff format --check src tests && mypy src --platform linux && bandit -r src/ -ll`

**实测结果（2026-10-24，容器沙箱 + `.heagent/tmp/py311-venv-linux` 取证 venv）:**
- `pytest tests/test_architecture_contracts.py -q` → **35 passed**（新增 2 例：对外端点集 / 四份文档同步）
- `pytest -q --ignore=tests/test_cli_http_lifecycle.py` → **3933 passed / 50 skipped / 25 deselected**（153.70s）
- `scripts/quality_gate.py` → 覆盖率 **92.43%**（门限 87%），**3940 passed**；唯一失败 = 3 条
  `test_cli_http_lifecycle.py` 端口释放探针（**已知环境红**：在 HEAD 干净 worktree `169d3f9` 复跑同样 3 条红，
  7 passed / 3 failed —— 与本轮改动无关）
- `ruff check src tests` / `ruff format --check src tests`（343 files）/ `mypy src` 与
  `mypy src --platform linux`（174 files）/ `bandit -r src/ -ll`（Medium 0 / High 0）→ 全绿

## Spec Change Log

<!-- Append-only. -->

## Implementation Notes

<!-- Agent-owned. Append-only during implementation. -->

- 2026-10-24 实施完成。文档四处同步：`docs/frame.md`（4.17.1 配置面 +4 键、端点表加两列、新增「双监听并存」
  行、4.17.1.1 装配行、4.17/调用链的「双 server」措辞）、`AGENTS.md`（安全声明新增「双监听并存」一条）、
  `deploy/README.md`（listener 表、四种部署姿态、双监听配置约束）、`.env.example`（+4 键）。
- 契约两例：`test_external_ws_listener_never_exposes_the_cli_bypass_surface`（对外路由集恰为两条）、
  `test_dual_listener_docs_stay_in_sync`（四份文档关键事实在场，不比较措辞）。
- 文档判据刻意**只钉事实**（键名 / 端点路径 / 一句不变量），不钉排版或措辞——否则每次润色都要改判据。

## Review Triage Log

<!-- 三层自审（blind-hunter / edge-case-hunter / verification-gap）逐层执行后追加。 -->

| # | 发现 | 判定 | 证据 / 路由 |
|---|---|---|---|
| 1 | `quality_gate.py` 报 3 条失败，若直接接受「环境红」结论就是自证 | medium（真） | 用 `git worktree add --detach` 取 HEAD 干净基线（`169d3f9`）复跑同一文件：同样 3 条红、7 条绿 ⇒ 与本期改动无关（retro 已登记的端口释放探针）。worktree 用完即 `worktree remove` |
| 2 | 期间 HEAD 被并发会话推进（`bab1dc5` → `169d3f9`，他人提交 skillresearch 技能） | 流程（真） | 每轮开工前 `git status --porcelain` 重测（既定纪律）；本期改动全部落在自己列出的 14 个受跟踪文件 + 4 个新产物，未触碰他人提交 |
| 3 | `deploy/README.md` 若只写「能配双监听」而不写「两条共享同一状态机」 | medium（真） | 运维会误以为对外 listener 是隔离区。已在「安全前置」写明：token 只保护「谁能连上它」，不隔离「连上后能做什么」（仍是单用户语义，能提交 run 就能执行 `shell`） |
