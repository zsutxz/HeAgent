# Step 06 · refine-stories 报告

- 目标：`Goal-4`
- 执行角色：`bmad-agent-po`（headless，三个 epic 并行细化）
- 产物：三个 epic 的 `## Requirements` 段 + `refined: true`；三个 epic 的 `tickets/tickets.toml`（共 17 条 entry）
- 状态：**审批门待确认**

## Epic 细化

### E74 · 协议与帧契约（7 条 Requirements）

| R | 条款 | 来源 |
|---|---|---|
| R1 | `run` 新增可选 `project_id`（`min_length=1`/`max_length=16`/不 strip）；缺省解析逐字等价，`""` ⇒ `malformed`；白名单升级为 `_FRAME_FIELDS` 单一映射表 | PRD R2；AD-4 |
| R2 | `ProjectChannelService` Protocol（声明在 `network/ws_server.py`）+ `SubmittedRun`（无 `session_id`）；端点构造器关键字参数 `project_service=None`；`None` 时带 id 提交回 `invalid_request` 且不启动 | PRD R10；AD-1 |
| R3 | 次序固定「先 `ensure_available` 后 `start_project_run`」；code 逐字透传；失败零副作用 | PRD R5 |
| R4 | 项目侧错误码均为 `HttpErrorCode` 既有成员（宿主实测：`http_protocol.py:58` 起已含 `unknown_project` / `project_unavailable` / `project_busy` / `run_conflict` / `total_inflight_limit` / `unknown_run` / `resync_required`），本 epic 不新增码、不重生成快照 | PRD R5 |
| R5 | `cancel_run` 帧（`run_id` 必带）与既有 `cancel` 同源；单 run 端点校验绑定、readonly 回 `invalid_request`、幂等终态、`unknown_run` | PRD R8 |
| R6 | 事件面零变更（`WsAckFrame` / `WsEventFrame` 字段集不变、golden 逐字、路由不增） | PRD R6 |
| R7 | `network/` 哑传输不变量（零 import / `is_dir` 零命中 / 架构契约测试绿） | PRD R10 |

Outcome / Done when 回读：五条 Outcome 全部可判；done when 的「错误码已登记进 `transport_errors`」收窄为「既有码在册」（新增 `project_registry_unreadable` 归 E75，快照重生成归 E76）。

### E75 · 项目链运行时与投影注入（7 条 Requirements）

| R | 条款 | 来源 |
|---|---|---|
| R1 | `projects` 帧 entry 键集恰 `{id,name,available}`、`path` 计数 0、顺序与 `list()` 逐位一致、上限 32 | PRD R1 |
| R2 | 真源 = 注册表、不做磁盘扫描；`network/` 内 `is_dir` 与运行栈 import 零命中 | PRD R1 |
| R3 | 六项落点（围栏根/会话/产物/ledger/state_root/memory）全在项目根，启动工作区零新增 | PRD R3 |
| R4 | 会话二分（续最近 / 新建）各有独立用例；ack 无 `session_id` | PRD R4 |
| R5 | 注册表不可读分路：列表 fail-soft（`registry_state="unreadable"` + 1 条 WARNING）、提交 fail-loud（`project_registry_unreadable`） | PRD R13 |
| R6 | 帧转译单源（spy 计数钉 I6/I9）；`project_service=None` 三命令回 `invalid_request` | PRD R3 |
| R7 | 两处 `build_ws_servers` 注入同一适配器；code 逐字透传；`available=false` 被拒且不占名额 | PRD R3、R13 |

Outcome / Done when 回读：需补三条判据（ack 无 `session_id`、`project_service=None` 三例、两处装配注入断言），已分别落进 R4 / R6 / R7 与对应 entry 的 `verify`。

### E76 · 并发隔离与远程面收口（7 条 Requirements）

| R | 条款 | 来源 |
|---|---|---|
| R1 | 两项目并发事件流不串味（`run_id` 交叉 0、ack 各自正确、取消只打目标） | PRD R9 |
| R2 | 名额全局 + per-project 双重约束、参数不动、被拒不占名额 | PRD R9 |
| R3 | cursor 续流首帧 ≤ N+1 且连续无空洞 | PRD R7 |
| R4 | 窗口不足必须 `resync_required`、重复可见可去重、run 已清理回具名错误 | PRD R7 |
| R5 | 白名单不扩张（WS 5 命令封闭 / HTTP 注册 403 / 审批只见 `tool_error=True`） | PRD R11 |
| R6 | `external` + 非 docker 沙箱恰 1 条锚点 WARNING、不改启动成败 | PRD R12 |
| R7 | 4 份基线（`tests/fixtures/contract_baselines/`）只含预期新增 + 三份文档同步 + 客户端对接口径 | PRD R14 |

## Story 拆分

| ref | 标题 | covers | after | risk | 组 |
|---|---|---|---|---|---|
| 74.1 | E74-S01 · 命令帧白名单单一映射表与可选 `project_id` 字段（含 Protocol / `SubmittedRun` 定义） | R1,R2 | — | medium | — |
| 74.2 | E74-S02 · 项目通道端口接线与带项目提交的端点转译 | R2,R3 | 1 | medium | wave-2 |
| 74.3 | E74-S03 · `cancel_run` 帧与只读口径 | R5 | 1 | medium | — |
| 74.4 | E74-S04 · 事件面零漂移契约钉子 | R6 | 1 | low | wave-2 |
| 74.5 | E74-S05 · 错误码台账与哑传输边界收口 | R4,R7 | 2,3 | low | — |
| 75.1 | E75-S01 · 注册表健康探针与项目错误码 | R5,R7 | epic-74 | medium | P1 |
| 75.2 | E75-S02 · network 侧 `project_id` 提交分支 | R6,R7 | epic-74 | high | P1 |
| 75.3 | E75-S03 · `cli/ws_project_adapter.py` 帧转译单源（含 cli 白名单 + `docs/frame.md`） | R1,R2,R7 | 2 | medium | P2 |
| 75.4 | E75-S04 · 控制台编排：六项落点与会话续接/新建 | R3,R4 | 1, epic-74 | high | P2 |
| 75.5 | E75-S05 · 装配注入：`build_ws_servers` 透传与两处注入 | R6,R7 | 3,4 | medium | — |
| 75.6 | E75-S06 · 契约基线与文档收口 | R1,R5,R7 | 1–5 | low | — |
| 76.1 | E76-S01 · 断连续流三判据 | R3,R4 | — | medium | e76-a |
| 76.2 | E76-S02 · 两项目并发不串味与名额分层 | R1,R2 | — | medium | e76-a |
| 76.3 | E76-S03 · 远程可见面白名单收口 | R5 | — | low | e76-a |
| 76.4 | E76-S04 · external 档非 docker 沙箱启动 WARNING | R6 | — | low | e76-a |
| 76.5 | E76-S05 · ADR-005 五步验收串跑 | R1,R3,R4 | 1,2 | medium | — |
| 76.6 | E76-S06 · 契约快照与文档收口 | R7 | 1,2,4,5 | low | — |

- 并行批候选：`75.1 ‖ 75.2`（P1，写集不相交）、`75.3 ‖ 75.4`（P2）、`76.1 ‖ 76.2 ‖ 76.3 ‖ 76.4`（e76-a，四条写集两两不相交）。批大小上限 3（`e76-a` 四条需分两批）。
- 全部 `hitl = false`（无一步需人工操作或人工决策）。

## 宿主裁决（把 12 条「需裁决」按默认处置关闭）

| 议题 | 裁决 | 理由 |
|---|---|---|
| E74 的 R2 跨 74.1 / 74.2 | 接受 | 74.1 必须先有关键字参数与 `None` 护栏，否则「解析出 `project_id` 却没人认」会静默跑启动工作区 |
| `ProjectChannelService` / `SubmittedRun` 定义归属 | **归 74.1** | 74.1 就要用该类型做注解；放 75.2 会造成跨 entry 前向依赖。已改写 74.1 与 75.2 的 description |
| E74 不新增错误码、不重生成快照 | 接受（宿主已实测） | `HttpErrorCode` 已含全部项目侧错误码，仅 `project_registry_unreadable` 需 E75 新增 |
| `projects` 命令 / `WsProjectsFrame` 归 E75 | 接受 | E74 的 `set(_FRAME_FIELDS) == set(WsCommand)` 在 4 值时自洽，E76 的 5 值断言在 E75 后成立 |
| E74 期间文档滞后 | 接受 | 文档与快照统一由 E76 收口，避免三处各改一遍 |
| `after` 形态（字符串数组混用兄弟 id 与 epic slug） | 接受 | `tickets.py status` 实测通过，`problems` / `unpinned_after` / `undeclared_after` / `order_conflict` 全空 |
| 契约快照目录 | **修正为 `tests/fixtures/contract_baselines/`** | 实测仓内只有该目录（子会话与 spine 原写 `tests/contract_baselines/`，已全库替换修正） |
| `project_unavailable` 产出方 | 归 console（75.4） | 该码已存在，由 `ConsoleOperationError(code="project_unavailable")` 产出，传输层只透传 |
| 「续最近会话」的判据 | 默认按会话落点 mtime | 与 `ProjectRegistry.touch` 的 `last_opened_at` 口径一致；实现期在 75.4 的 plan 里写明 |
| E76-S05 测试文件名 | 接受 `tests/network/test_ws_remote_flow.py` | 沿用 `test_ws_*.py` 惯例 |
| E76-S01 允许对 `ws_server.py` 做最小修复 | 接受 | 先取证：现状若是空流则补具名错误帧，否则该文件零 diff |
| E76-S03 并入既有 `test_ws_protocol.py` | 接受 | 不新造断言文件，避免与 76.6 争同一批文件 |

## 宿主验收核对

| 核对项 | 结果 | 证据 |
|---|---|---|
| `tickets.py status` 的 `problems` 为空 | 通过 | `problems` = null |
| `unpinned_after` / `undeclared_after` / `order_conflict` 全空 | 通过 | 三者均为 `[]` |
| 三个 epic 均 `refined: true` | 通过 | `epics` 输出 `refined` 全 True |
| 每条 entry 单一目标、`verify` 可判定、`after` 只引用更早交付 | 通过 | 17 条逐条核对（见上表） |
| `covers` 指向所属 epic 的 R 编号 | 通过 | 74 用 R1–R7、75 用 R1–R7、76 用 R1–R7，均在本 epic Requirements 范围内 |
| 无 `unknown` | 通过 | 三个 toml 均无 `unknown` 字段；需裁决项已由宿主裁决关闭 |
| 未实现代码、未建 plan / leaf | 通过 | `git status` 只含 `docs/Goal-4/` 下的规划产物 |
