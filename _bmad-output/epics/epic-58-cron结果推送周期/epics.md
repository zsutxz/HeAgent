# Epic 58：cron 结果推送周期

- 创建：2026-10-28
- 状态：planned（story 已拆，未实现；用户批准后 story 转 ready-for-dev）
- 基线 commit：a372f2b（`a372f2b80ce308b81426be82c361827c12912676`）
- 来源：
  - 客户端实测（2026-10-28，连接窗口 16:14–16:19）：cron 于 16:05 / 16:10 / 16:15 三轮均**已触发**，
    但客户端**零帧到达**；
  - `docs/hello.txt` 结论：app↔服务端「提交→回复」正常；cron 的 hello 目前「只生成不投递」；
  - 用户 2026-10-28 裁决：走 **B 案（独立通知端点）** + **终端回显要由变量控制** + **先写 story**。

## 目标

让 cron 任务的最终答案能被**已连接的外部客户端主动收到**（服务端推送），并可选在终端回显。

## 非目标

- 不做 cron 的取消通道、审批门、历史持久化。
- **不改** `/api/runs/*`（提交 / 订阅）与 `/api/cli/ws`（终端旁路）的既有语义与端点形状。
- 不在 HTTP console 入口开 cron（`http_console` 仍 `enable_cron=False`，台账 A11②）。
- 不做「cron 结果写进网页会话历史」：`HTTP_ENABLED=false` 时该面根本不存在，且与本案的推送诉求不同型。
- 不做逐 token 流式推送（一次 cron 执行 = 一条通知）。

## 方案：B 案（独立通知流）

新增只读 WS 端点 `/api/notifications/ws`：
cron 每执行完一轮，把「最终答案 / 错误首行」投递到 `NotificationHub`（环形缓冲 + 跨轮次 seq + 游标重放），
订阅者按 `last_event_id` 续传，落后即踢（与 SSE / run-WS / CLI 旁路同一背压语义）。

服务端装配：`build_ws_servers` 在 `CRON_PUSH_ENABLED=true` 时建 `NotificationHub` 并挂到 listener 上；
入口层把「发布」接成 cron job runner 的一个回调（`cron_notifier`），runner 本身不认识网络类型。

## 冻结决策（评审时逐条确认）

| ID | 决策 | 理由 / 代价 |
|----|------|-------------|
| D1 | **新端点**而不是复用 `/api/cli/ws` | 语义分离：旁路 = 「旁观宿主的终端轮次」，通知流 = 「宿主 cron 的产物」。旁路按 Epic 56 D9 **永不出网**，而本案的跨网客户端正是诉求 ⇒ 复用会把两条不同暴露面绑在一起 |
| D2 | 端点**随 listener 注册**（本地 + 对外 + readonly 都注册） | 对外 listener 本身已强制 token（fail-closed），不再叠第二套认证；`readonly` 也注册是因为本端点天然只读。**代价**：对外绑定意味着宿主 LLM 输出会离开本机——启动时打一条 WARNING，让「开了但没意识到」不可能发生 |
| D3 | **单一中枢实现**：抽 `EventStreamHub` 通用核，`CliEventHub` / `NotificationHub` 都是薄适配 | 复制第二份「seq / 环形缓冲 / 游标 / 背压 / 关停」必然漂移（Epic 55 与 Epic 56 已出现同类教训）。**硬约束**：`CliEventHub` 的公共 API 与行为逐字不变，既有 41 例（15 + 13 + 8 + 5）不得改动 |
| D4 | 两个独立变量：`CRON_PUSH_ENABLED`（默认 **False**）、`CRON_ECHO_TO_TERMINAL`（默认 **False**） | 「推送」与「终端回显」是两件事：可以只回显不推送，也可以只推送不回显。默认关 = 不改变现行为（无人监督后台输出默认不外泄） |
| D5 | 一次 cron 执行 = **一条**通知；goal 自动推进分支**不发** | 逐 token 流式会把 cron 变成第二个 run 通道（额度、取消、会话都要跟着长）；goal 推进不是「给用户的回答」 |
| D6 | 终端回显走 **stderr**、单行、带 `[cron <job_id>]` 前缀、按 `clip_text` 口径截断 | stdout 在 `--json` 下是 JSONL 契约，不得污染；readline 提示行可能不重绘，属可接受的显示瑕疵（story 58-2 AC 明示） |
| D7 | 游标 / 重连口径沿用既有：`?last_event_id=` + `resync_required`；缓冲 256 条 | 与 SSE / run-WS / 旁路同一套恢复路径，客户端不需要第二套重连逻辑 |

## Stories

| ID | 标题 | 层 | 依赖 |
|----|------|----|------|
| 58-1 | 通知中枢与 `/api/notifications/ws` 端点（network 层） | `network/` | 无 |
| 58-2 | 入口接线：两个变量 + cron notifier + 终端回显 + 文档/契约收口 | `cli/` + `config/` + docs | 58-1 |
| 收口 | 全量门禁 + 状态回写 + 会话收尾清单 | — | 58-1/58-2 |

## 覆盖矩阵（用户诉求 → story）

| 诉求 | 落点 |
|------|------|
| cron 的 hello 能到客户端 | 58-1（中枢 + 端点）+ 58-2（发布接线） |
| 客户端要能区分「cron 结果」与自己的 run | 58-1（`WsNotificationFrame` / `NotificationPayload.kind`） |
| 终端也要看到，但要由变量控制 | 58-2（`CRON_ECHO_TO_TERMINAL`） |
| 开关要能整条链路关掉 | 58-2（`CRON_PUSH_ENABLED`：中点不建 ⇒ 端点不注册 ⇒ 客户端拿 403） |

## 风险与已接受的代价

- **暴露面 +1**：`tests/test_architecture_contracts.py::test_ws_endpoints_and_commands_stay_closed` 的
  路径集合由 3 条变 4 条——这正是「多一个端点必须走 story 评审」的机制，本 epic 即评审载体。
- **对外 listener 上会有宿主 LLM 输出**：D2 已冻结为「允许 + WARNING」，若评审要收紧为「仅本地」，
  改的是一个判据（`build_ws_app` 里的注册条件）而不是架构。
- **CLI 旁路重构（D3）**触及已被 41 例钉住的模块：以「既有测试零改动 + 全绿」为重构验收线。
