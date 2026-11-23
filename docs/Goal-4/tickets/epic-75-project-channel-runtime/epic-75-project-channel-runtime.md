---
type: epic
code: E75
parent: brief
slug: epic-75-project-channel-runtime
covers: ["R1", "R3", "R4", "R13"]
sources: ["docs/Goal-4/prd-ws-remote-project-channel/prd-ws-remote-project-channel.md", "docs/decisions/adr-0005-ws-remote-project-channel.md"]
after: ["epic-74-ws-frame-contract"]
risk: high
refined: false
---

# E75 · WS 远程项目通道：项目链运行时与投影注入

## Description

`project_id` 到位后的**语义归属**。本 epic 把一个 `project_id` 译成既有 HTTP 项目链的**同一次调用**（A2，抽成 HTTP 与 WS 共用的帧转译，不做第二套编排），并让远程能看到项目：

- 列表只读投影：字段恰为 `id` / `name` / `available`，不含 `path` / `last_opened_at` / `is_default`；集合与顺序以 `ProjectRegistry.list()` 实测为准（default 在末位，N4）；`MAX_PROJECTS = 32` 下表现可判定；真源是本机注册表、不做磁盘扫描（N1）。
- 带 `project_id` 的 run 六项落点全在该项目：围栏根、会话落点、产物、`ExecutionLedger`、工具审计根（`RunContext.state_root`）、memory —— 无任一路落启动工作区根。
- 会话语义：缺省续该项目**最近一次会话**，从未有会话 ⇒ **新建**（显式分支 + 测试，不是「查不到即错误」，N7）；WS 帧不回带 `session_id`（D5）。
- 注册表不可读分路（N5）：列表 fail-soft（空表 + 可判定信号 + WARNING），提交 fail-loud（复用 E74 已具名的错误）。
- `available` 沿用既有 `ProjectEntry.available` 语义（列表时计算），不新立口径、投影不加字段（Q2）；列表到提交的 TOCTOU 由提交路径二次校验兜底 —— 走 `ProjectRegistry.find()`（含 1 次 `is_dir`），不引入投影缓存（N6 / Q8）。

## Outcome

- 远程面板能列项目且**只列**三个字段：键集合 == `{id,name,available}`，`"path"` 计数为 0。
- 项目隔离是可断言的事实：同一进程内带 `project_id` 的 run 六项落点全在项目根，启动工作区根零新增。
- 「续最近会话 / 无会话即新建」两个分支各有独立用例，不靠人工确认。
- 注册表可读性只影响列表观感、不影响提交安全：一条 WARNING + 一个可判定信号 vs 一个具名错误。
- 装配仍是注入式：项目解析器照 `run_service` 先例进 `build_ws_servers`，未新造装配机制（N2）。

## Boundaries

- 不改帧定义与错误码（E74 已定）；不做并发隔离、断连续流、启动告警、快照收口（E76）。
- 不改 `project_id` 语义（仍 path-derived），不动注册表格式与三条既有站点（N3 / NG13）。
- 不改 HTTP 回环面语义（NG12）：既有项目链只被复用与抽取共用转译，不改写。
- 不做磁盘扫描发现项目（N1）；不做 per-project provider / model（NG5）；不做 per-project 名额口径调整（NG11）。

## 已知 Done when

- 列表响应键集合恰为 `{id,name,available}`、`"path"` 计数 0、顺序与 `ProjectRegistry.list()` 逐位一致。
- 单项目与两项目各一条提交用例：六项落点断言全绿，启动工作区根无新增产物、无新增 ledger 条目。
- 「有历史会话 ⇒ 续最近」与「从未有会话 ⇒ 新建」各一例；WS 帧应答中无 `session_id`。
- 注册表不可读两例：列表空表 + 可判定信号 + 恰好 1 条 WARNING；提交回 E74 的具名错误。
- `available=false` 的提交被拒且不建 run，错误码与 E74 口径一致。
