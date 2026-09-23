# TCP 网络接口周期 · Retrospective（Epic 48）

> 日期：2026-09-23（**补做**：`_bmad-output/sprint-status.yaml` 中 Epic 48 交付时未登记 `epic-48-retrospective` 行，与 epic-40..47 先例不一致）
> 范围：`_bmad-output/epics/epic-48-TCP网络接口周期/`（Epic 48，6 个 story：`48-1-tcp-protocol-message-boundary`、`48-2-async-tcp-server-lifecycle`、`48-3-agentloop-adapter-cli-wiring`、`48-4-concurrency-timeouts-resource-limits`、`48-5-network-entry-security-observability`、`48-6-tcp-regression-tests-docs`）
> 动机：为 HeAgent 增加**可选**的 TCP 服务入口——CLI 作为 TCP Server 经 UTF-8 JSON Lines 接收外部客户端请求，交给现有 `AgentLoop` 处理并回传结构化结果（`epics.md` Epic Goal）。明确非生产级 Web/API 服务。

## 一、做了什么

| Story/交付项 | 核心交付 |
|------|----------|
| 规划 · commit `6825628` | PRD / Architecture / Sprint Plan / 6 个 story 同日建立（13 files，+1853/−1，2026-09-22） |
| 48-1 + 48-2（FR 协议与传输）· commit `792826a` | `network/protocol.py`（请求/成功/失败模型 + 黄金 JSONL）+ `network/tcp_server.py`（`asyncio.start_server` 生命周期）；`network/` 运行期不依赖 cli/agent/providers/engine（8 files，+810/−18） |
| 48-3 + 48-4（接线与资源治理）· commit `a948a9e` | `cli_tcp.py`（`TcpAgentHandler` + `build_server_config` + `tcp-server` 子命令）+ `AgentLoop.last_model`（修并发档位串味）+ 8 个 `tcp_*` 设置 + 非等待式在途名额（18 files，+1609/−47） |
| 48-5 + 48-6（安全、观测、收口）· commit `ec2047d` | `network/exposure.py`（回环判定单点）+ `_safe_log` 阶段日志（8 个 event）+ `id` 有界（≤128、禁控制字符）+ 黄金报文/字段集冻结 + README「TCP 入口（实验性）」+ frame §4.16（19 files，+1203/−76） |
| 版本与横幅 · commit `c85a013` / `d0d39b6` | 0.6.2 版本引用补齐；横幅改读源码 `__version__`，不再依赖可能滞后的 dist-info |

## 二、做对的

1. **提交按 Story 依赖对合并，每个中间态都能独立验证**——`792826a`（48-1+2）、`a948a9e`（48-3+4）、`ec2047d`（48-5+6）。两个 Story 的改动交织在同一批测试文件与 `sprint-status.yaml` 里（强拆需 hunk 级切片），合并前已在各 story 的 Verification 段说明理由，而非默默合并。
2. **协议/传输层与 Agent 彻底解耦并被契约测试钉住**——`network/` 运行期不导入 `cli`/`agent`/`providers`/`engine`，48-3 顺带把 `tests/test_architecture_contracts.py` 的反向依赖断言覆盖到 `heagent.network`（并修掉 `from heagent import providers` 这类写法不被识别的绕过）。
3. **三个危险默认值都被实测证伪过一次**——① 在途限额用任务集合而非 `Semaphore`（后者无 `try_acquire`，限额会退化成排队）；② `click.FloatRange` 放行 `nan`/`inf`，补 `_reject_non_finite` + Pydantic `allow_inf_nan=False`；③ 裸 `logger.*` 抛异常时兜底 `except` 会把 `agent_error` 改写成 `server_error`，改走 `_safe_log`。
4. **「观测故障不污染协议」有注入式测试背书**——48-5 的 7 个 + 48-6 的 3 个，共 10 个变异体全部精确红（去掉告警 / 记录 prompt 正文 / 绕过 `_safe_log` / 取消无终态 / reason 分裂 / `id` 无约束 / 裸 logger / 去掉 `exclude_none` / 吞掉绑定失败 / 不归还名额），跑完按 sha256 逐字节还原。
5. **收口坚持「先跑后写」**——sprint-plan 的「实测结果」表与 story 的 Verification 段全部是实测数字；48-6 一度先写了估算值（118/166/90.99%），被自己纠正为实测（119/165/90.97%）。
6. **交付即给出可复制的使用文档**——README 新增实验性章节（含 8/8 错误码与 NUL 边界），并明说 TCP JSONL 与 `rollout.jsonl` 是**不同通道**。

## 三、可改进的

1. **5 条新缺口只进 `docs/frame.md` 五，未登记活动台账**——`_bmad-output/implementation-artifacts/deferred-work-archive.md` 的活动条目（6 条）**零处**提到 epic-48 / TCP（实测 `content_search "epic-48|48-5|TCP"` 命中 0）。于是「TCP 入口不写 rollout」「运行栈日志非观测故障免疫」「TCP 日志含工具摘要（未脱敏）」这三条**有明确触发条件与冻结边界**的后续工作，失去 append-only 追踪入口，违反台账约定。
2. **规划文档状态字段未随交付回写**——`architecture.md` / `prd.md` frontmatter 仍为 `status: planning`，`epics.md` 仍「状态：in-progress」，`sprint-plan.md` 仍「Epic 状态：in-progress」，而 `sprint-status.yaml` 已是 `epic-48: done`（**2026-09-23 已一并回写**：`architecture.md` / `prd.md` → `status: final` 并更新正文「当前状态」，`epics.md` → `状态：done` 与收口后的「规划阶段」，`sprint-plan.md` → `Epic 状态：done`）。
3. **跨 Story 契约变更缺少反向指针**——48-4 修改了 48-2 的既有断言：`test_close_returns_after_timeout_when_handler_suppresses_cancellation` 由「关闭超时后 `active_connections == 1`」改为 `== 0`（48-4 契约要求超时后必须释放连接登记）。变更已在 48-4 story 与测试注释注明，但 48-2 story 侧没有反向指针，回看 48-2 的 AC 会读到旧语义。
4. **一个 Epic 的交付流里夹带主题外改动**——`d0d39b6`（横幅版本改读 `__version__` + dist-info 滞后治理）与 TCP 无关；`c85a013`（0.6.2 引用补齐）属发布杂务。它们在 Epic 收口窗口内提交，回滚粒度与 Epic 语义不完全对齐。
5. **`epic-48` 未登记 retrospective 行**——所有 epic 里唯一缺此行的（本次补做并补登）。

## 四、教训

1. **「非等待式」是限额的语义要求，不是实现细节**——并发限额若用 `Semaphore`（无 `try_acquire`）会变成排队，与「超限立即拒绝」的契约相反；名额记账必须用幂等集合（`discard`），用整数计数会在「关闭超时后残留任务迟到结束」时减成负数。
2. **「库已做校验」的假设必须用非法值实测**——`click.FloatRange` 不拦 `nan`/`inf`；`inf` 会让超时静默变成无限制、NaN 让异常出口与其它非法值不一致（exit 2 vs exit 1）。
3. **`close()` 必须「有界返回 + warning + 结算登记」**——handler 吞掉取消时 asyncio 无法强杀，若不结算，复用/重启同一实例会**永久少一份容量**；「无法强杀」是诚实边界，要写进 docstring 而不是假装干净。
4. **相近命名必须在文档里显式区分**——TCP JSONL 与 rollout JSONL 名字相似，必须写明网络入口不写 rollout（`EVENTS_ROLLOUT_FOR_TCP` 这类开关是**死开关**，实测 `JsonlSink` 唯一构造点在 `cli._build_event_sink`）。
5. **`continue-on-error` 会把失败步骤的 job 结论仍标 success**（跨周期既有教训）——判断 CI 矩阵必须看**步骤级**结论，`3.14-dev` 格的绿不构成证据。
6. **「观测层免疫」需要注入式测试，不是代码走查**——只有让 logger 真的抛异常，才能证明响应不被改写。

## 五、遗留项状态

- **已闭合**：48-1 ~ 48-6 全部 `done`（`sprint-status.yaml` 与 6 个 story frontmatter 实证一致）；`epic-48: done`（`ec2047d` 收口，工作区干净）。
- **仍开（仅记于 `docs/frame.md` 五，未入活动台账）**：
  - TCP 入口非安全边界（无认证、无 TLS；回环判定与启动告警只是提示）；
  - TCP 入口不接 MCP（48-5 有意决策，非缺口但需保持）；
  - TCP 入口不写 rollout（`EVENTS_ROLLOUT_ENABLED` 对该入口是死开关，接入属后续工作）；
  - 运行栈（`agent`/`engine`）自身 logger 不在「观测故障免疫」范围（CPython `Handler.handle` 不捕获 emit 异常，与 `raiseExceptions` 无关）；
  - TCP 日志含工具摘要（默认 `LoggingObserver` 打印 `tool=… target=…`，`shell` 的 target 不截断）——日志脱敏属后续工作。
- **跨周期活动台账**（`deferred-work-archive.md`，6 条）**无一条来自 Epic 48**——见「三、可改进的」第 1 条。
- **未建 story**：TCP Client CLI、长连接多轮会话、流式响应、认证/TLS（`epics.md`「MVP 不包含」段，均为有意排除）。

## 六、结论

Epic 48 在一天内从规划走到收口，并把「非生产边界」这条项目立场同时落进代码（默认绑回环 + 启动告警 + 入口不连 MCP + 明确不引入 `TCP_ENABLED`）与文档（README 实验性章节 + `frame.md` 五），这是本周期最扎实的部分；**三个危险默认值都被实测证伪过一次**，是比实现本身更值钱的产出。

短板不在实现而在收口纪律：缺口只写进 `frame.md` 未进活动台账、规划文档状态字段滞后、跨 Story 契约变更缺少反向指针、主题外改动夹在 Epic 窗口内。**下一轮同类周期的 Definition of Done 应加两条**：① 交付时把触发条件明确的缺口登记进活动台账（不能只写 frame）；② 规划文档的状态字段随 sprint-status 一并回写。
