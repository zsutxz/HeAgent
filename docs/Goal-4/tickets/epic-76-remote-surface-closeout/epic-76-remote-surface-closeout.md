---
type: epic
code: E76
parent: brief
slug: epic-76-remote-surface-closeout
covers: ["R7", "R9", "R11", "R12", "R14"]
sources: ["docs/Goal-4/prd-ws-remote-project-channel/prd-ws-remote-project-channel.md", "docs/Goal-4/architecture-ws-remote-project-channel/architecture-ws-remote-project-channel.md", "docs/decisions/adr-0005-ws-remote-project-channel.md"]
after: ["epic-74-ws-frame-contract", "epic-75-project-channel-runtime"]
risk: medium
refined: true
---

# E76 · WS 远程项目通道：并发隔离与远程面收口

## Description

最后一个 epic：把并发、续流、可见面与契约一次性收口，让 ADR-005 的验收基线可以跑到底。

- 并发隔离：两项目并发各 1 run —— 事件流 `run_id` 不交叉、ack 指向正确 run、取消只作用于目标 run（另一 run 活到终态）；名额仍受全局 + per-project 双重约束，参数不动（D8 / NG11）。
- 断线续流：凭客户端持久化的 cursor 续流不丢事件。`R7` 是 PRD 中唯一的 `AC gap`，本 epic 必须把它落成可跑断言；协议面不变，`cursor` 语义以既有单 run 事件端点为唯一真源 —— 取消后仍可续读到尾部，run 已被清理则回具名错误、不静默空流（Q3）。
- 远程可见面白名单：WS 上无配置读写 / 项目注册 / 会话历史浏览的帧或端点；HTTP 侧远程注册仍 403；远程提交的审批类工具调用结果仍只见 `tool_error=True`（D4 / D6）。
- 启动告警：`external` 档 + 非 docker 沙箱每次启动**一条**固定锚点 WARNING（含 `listener=external` 与沙箱后端名；判据取启动期**实际生效后端**，Q1），docker 档 0 条，二者均不改变启动成败（D9 / NG7）。
- 契约与文档收口：golden 帧 + 4 份快照重生成，diff 只含预期新增（`transport_errors` 新增取消 / 未知项目错误码，`transport_routes` 无新端点 —— 事件流复用）；`docs/errors.md` 与远程访问口径同步；「id 随路径派生、目录移动即换键、APK 需重选」写进客户端对接说明（N3）。

## Requirements

- **R1** 两项目并发各 1 run 时事件流互不串味：两路事件帧的 `run_id` 交叉计数为 0、两个 ack 各自指向本次提交的 run、取消目标 run 后另一 run 仍存活到终态。（← PRD R9）
- **R2** 名额仍是全局 + per-project 双重约束且参数不动：项目已有在途 run 回 `project_busy`、全局名额耗尽回 `total_inflight_limit`（两者可分辨），被拒的提交不触达 `start_project_run`（不占名额），不新增配置键、不改既有并发参数。（← PRD R9）
- **R3** 断线重连凭客户端持久化 cursor 续流不丢事件：以最后收到的事件 id 作 `last_event_id` 重连，续到的首帧 id ≤ 该 id + 1，其后 id 连续递增无空洞，直到终态。（← PRD R7）
- **R4** cursor 落后于服务端重放窗口时必须显性失败而不是静默降级：收到 `resync_required` 错误帧且无任何 event 帧先于它发出；窗口重叠导致的重复事件可见、由客户端按 id 去重即可；run 记录已被清理时回具名错误帧，不回空流。（← PRD R7）
- **R5** 远程可见面白名单不扩张：WS 命令集合仍是 5 个且不含配置读写 / 项目注册 / 会话历史族；HTTP 侧远程注册仍回 403；远程提交的审批类工具调用结果仍只见 `tool_error=True`。（← PRD R11）
- **R6** `external` 档且启动期实际生效的沙箱后端非 docker 时，每次启动恰 1 条固定锚点 WARNING（含 `listener=external` 与沙箱后端名）；docker 档 0 条；两种情况都不改变启动成败与退出码。（← PRD R12）
- **R7** 契约与文档一次性收口：4 份契约快照（`tests/fixtures/contract_baselines/`）重生成后 diff 只含预期新增（`transport_errors` 新增项目侧错误码、`transport_routes` 无新端点）；`docs/errors.md`、`docs/frame.md`、`docs/framework.md` 同批同步；客户端对接说明写明「id 随路径派生、目录移动即换键、APK 需重选」。（← PRD R14）

## Outcome

- ADR-005 验收基线一次跑通到底：列项目 → 两项目各提交 1 run → 各自事件流完整 → 取消其一 → 断线重连凭 cursor 续流不丢事件。
- `R7` 不再以「客户端能力」这类不可判表述收场，而是一条可跑断言。
- 远程可见面可被安全审查者逐条对照：多一层帧或端点属显性新增，不是顺带漏出。
- 契约漂移可被 reviewer 一眼看完：4 份快照 diff 只含预期新增。

## Boundaries

- 不新增任何远程能力：无多轮续聊 / session 寻址、无远程审批、无远程配置读写与项目注册（NG3 / NG4 / NG9）。
- 不改帧族与错误码语义（E74 已定）；不动并发容量参数与 per-project 名额口径（D8 / NG11）。
- 不把沙箱告警升级为拒绝启动（NG7）；不做 per-project token（NG1）。
- 不改 HTTP 回环面语义（NG12）；不改 `project_id` 派生规则（NG13）。
- 不远程驱动 goal / loop（NG8）；不做跨项目协同（NG6）。

## 已知 Done when

- 端到端五步用例通过（含断线重连续流段），无一步以人工确认替代。
- 并发用例断言：事件帧 `run_id` 交叉计数 = 0、ack 指向正确 run、取消后非目标 run 仍到终态。
- `R11` 三判据各自可跑或可 grep：WS 无配置 / 注册 / 历史帧或端点、远程注册回 403、远程审批只见 `tool_error=True`。
- 启动日志：`external` + 非 docker 沙箱恰 1 条可 grep 的 WARNING，docker 档 0 条，两者退出码正常。
- 4 份契约快照 diff 只含预期新增；`docs/errors.md` 与客户端对接说明含新错误码与「id path-derived、目录移动需重选」口径。
- 回归面全绿：`pytest`、`ruff check`、`ruff format --check`、`mypy src`、`bandit -r src/ -ll`。
