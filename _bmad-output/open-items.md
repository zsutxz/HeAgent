# Open Items — 活动台账（未闭合问题清单）

> 活动项正文真源（2026-11-15 由 `implementation-artifacts/open-items.md` 上移根目录；同一 ID 的正文只在此一处，不得两处并存）。
> 状态语义：`active`（有触发条件、未排期）／`scheduled`（已挂到 story 或 sprint）／`frozen`（挂起待裁定，**必须带裁定指针**——没有指针的「挂起」不是状态，是遗忘）。
> `retired`（显式退役，5 字段齐备）的规范与历史记录在 [`retrospective-all-cycles.md`](retrospective-all-cycles.md) §三。
> 当前状态总览与 epic 总目录见 [`epic-overview.md`](epic-overview.md)。

## 活动（未闭合）条目

当前活动项：**5 条**（`frozen` 2：A34 / A41；`active` 3：A54 / A55 / A56）。

| ID | 主题 | 状态 | 说明 |
| --- | --- | --- | --- |
| A34 | 会话文件并发写残余：不可安全判定形态回退时丢对方一侧 | `frozen` | 主害已闭合（Z-D21，commit `9860a17`）。残余形态：共享前缀被改写 / 磁盘比基线短 / 基线对不上 / 文件不可解析 ⇒ 回退时丢对方一侧（WARNING 点名原因，不静默）。候选加固 = 把不可判形态的对方侧隔离进 sidecar 而非丢弃。**裁定指针：OQ-5 未裁定（「隔离 vs 丢弃」语义）**，故本轮只补确定性并发写回归测试（S-8），不改语义。触发条件 = 出现真实触发案例或用户裁定升级 |
| A41 | 兄弟 Story 越集写互相误归因（`goal/write_audit.py:146-157`） | `frozen` | 共享工作区审计无法按写者归属，兄弟 Story 越集写会落入本 Story 的 Δ 判负（连带置闩）。**裁定指针：AD-20（OQ-4 未裁）**；短期靠围栏预防层降低概率。**2026-11-05 收窄（用户裁定：一并处理至可行边界）**：判负消息与 `workflow_write_audit` 事件如实披露「写者无法归属到本 Story」（`shared_workspace` + `a sibling may be the author`），不再默认归因到本 Story；判负语义（FAILED + 撤闩）不变——写集并集对批内每个成员同形，越集写同样会被**写者自己**的审计判负，故误伤面 = 「无辜兄弟也失败 + 闩」，根因仍需 AD-20 物理隔离（判据 `tests/test_story_write_audit.py::test_violation_discloses_shared_workspace_attribution` / `::test_solo_batch_violation_has_no_attribution_caveat` + 变异 `scripts/mutation/mutate_write_audit_content_delta.py` M4） |
| A54 | /simplify 清理批（2026-11-14）缓修残差：真重构 8 项（2026-11-15 起 ①④⑤ 已落） | `active` | **origin=新增（2026-11-14 /simplify 四视角审查）**。2026-11-14 `/simplify` 四视角审查（REUSE 7 / SIMPLIFICATION 6 / EFFICIENCY 4 / ALTITUDE 5，去重后 19 机制）的「立即修」机械批已落 `954f9d4`；以下**缓修**项超出一次清理的体量，逐条留档（origin = 四份审查报告，`git log 954f9d4` 前的会话）：① ws_server 双胞胎端点构造器与会话骨架（两对 ~95 行孪生构造器）② cli/http 服务编排合一 ③ `SandboxDecision` 加类型化派生字段取代 agent 层 `isinstance(dict)` 鸭子解析（`agent/loop.py:453` `_bound_container_workdir`）④ WS/SSE「快照重放+水位去重」双写收敛到 `http_protocol.py` ⑤ http_server 的 register_ws/unregister_ws/close_websockets/needs_resync 登记面坐上 `EventStreamHub`（`http_server.py:640-696`）⑥ story 批基线一次采集 ⑦ 流式 token 重编码：`agent/stream_runtime.py:95` 每次流式调用全量 re-encode 且 usage 缺失分支再全量算一次（按消息 memoize / 复用 `stream_estimated`）⑧ policy 可用性预热 + WS 帧预序列化（帧对订阅者恒同，但预序列化点在三 hub 的 backlog/队列协议面，与 ④⑤ 同族同批）。**2026-11-15 网络族推进（用户裁定：收敛到 SSE 语义 / ⑧ 本批不做）**：① = ws_server 四构造器收 `_ws_session` 会话骨架（握手门→accept/hello→closing→会话体→异常收敛→有界收尾，日志事件名逐字节保持）；④ = `http_protocol.replay_then_follow` 单源（WS 侧终态判定改**快照时刻捕获**——微竞态窗口内 WS 客户端改收终态事件，对齐 AD-4；SSE 心跳经参数注入）；⑤ = `cursor_out_of_window` 算术单源（三流 + WS）+ `WsRegistry` 连接登记与有界关停唯一实现（http_server 组合接入；其 close_websockets 日志去 close_code 字段，与 hub 口径统一，无测试钉死）。判据 `tests/network/test_http_protocol.py::TestReplayThenFollow`（6 例直钉）+ 既有 WS/SSE/hub 面全绿；⑧ 复核：'policy 可用性预热' 位点在代码/审查报告/台账均不可考（claude-mem 不可达、报告未落盘），帧预序列化经评估收益趋零（单用户 1–2 订阅者）且需改两条流的队列形状——**缓做**，待性能专项周期携原始报告复核。②③⑥⑦ 维持触发条件（下一轮性能/网络专项周期按项领取；动手前过两道红线） |
| A55 | Epic 61 web_search 真实 Tavily 冒烟（61.3 验收残差） | `active` | **origin=新增（2026-11-16 Epic 61 收口，用户裁定跳过冒烟先闭合）**：61.1 引擎层（`66a5b9f`）/61.2 工具面（`1877250`）/61.3 文档收口已交付，三票 mark done；web_search 全链（config 解析→引擎调用→截断→围栏）未经真实密钥验证。闭合动作 = 用户提供 WEB_SEARCH_API_KEY 入 `.env` 后跑一次全链冒烟（参照 57-4 先例：临时 workspace，不触碰仓库记忆；key 不入 transcript/不入库/不入日志），通过后闭合 A55 并四处计数 7→6 |
| A56 | Epic 64 收口残差：任务进度跨进程不可见 / `examples/` 不在代码门禁范围 | `active` | **origin=新增（2026-11-18 Epic 64 收口）**，两项均为实测事实：
① **跨进程不可见**：`GET /api/tasks` 读的是**进程内**单例注册表（`engine/tasks.py::default_task_registry`），生产者当前只有上下文压缩（`agent/context_runtime.py::maybe_compress` 与 CLI `/compact`）⇒ 同进程的网页/内嵌入口能读到，跨进程（如另起的 `http-server` 实例、cron 子进程）读不到。判据 `tests/test_cli_epic64_wiring.py`（同进程 200）与 `tests/network/test_http_tasks.py`（注入式来源）。闭合动作 = 真需要跨进程时再上 IPC/落盘投影；触发条件 = 出现真实的「网页端看不到别的进程在跑什么」诉求。
② ~~**`examples/` 不在门禁范围**~~ → **2026-11-18 已闭合**：`ruff check` / `ruff format --check` 的路径面已加 `examples`（`scripts/quality_gate.py`、`ci.yml`、`.pre-commit-config.yaml`、`docs/testing.md` 同步；`ruff.toml` 为 `examples/**` 只放行 RUF001/002/003 全角标点，其余规则同标准）⇒ 现存 112 条告警清零（修 7 条实质问题、105 条为中文标点）；**`mypy src` 仍不含 examples**（示例是自包含演示脚本，纳入需单独定口径，不属本项闭合范围）。 |

### 速读（按行动姿态分组）

- **等外部触发**：A35（重启丢 run 困扰 ≥2 次 / 长 run 常态化）、A36（实际写自定义签名且需跨项目共享）、A53（hook stdout 喂回模型的真实需求）、A55（用户提供 WEB_SEARCH_API_KEY 后跑一次真实冒烟）
- **有明确修法等排期**：A54 残余 ②③⑥⑦（下一轮性能/网络专项周期领取；动手前过两道红线：monkeypatch 缝 grep + 本机可验证面）
- **等用户裁定**：A34（OQ-5「隔离 vs 丢弃」）、A41（AD-20 / OQ-4 物理隔离）

### 维护规则（活动项）

- 新增未闭合项**只写本节**：先登记 ID、状态（active / scheduled / frozen）、触发条件、裁定与验收证据，再开始实施；不要另建活动清单或复活历史档案活动区。
- `frozen` 必须带裁定指针（哪个 OQ / 哪份记录）。
- 闭合时把正文迁入 [`retrospective-all-cycles.md`](retrospective-all-cycles.md) §三（台账），或按归属 Epic 进 `epics/<周期>/deferred-work.md`，并从本表移除；**同一 ID 不得两处并存**。显式退役（裁定永不修）走 §三 的 `retired` 5 字段规范。
- `blocked` 需要产品或架构裁定，不能由实现者静默关闭。
