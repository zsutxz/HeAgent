# WS 远程项目通道（多项目控制）

## 原始需求（Original Request）

读取 docs/decisions/adr-0005-ws-remote-project-channel.md 进行开发

## 总结的需求（Derived Requirements）

- **事实（现状）**：远程唯一可提交通道是 WS external 档（Bearer token + TLS pin + 节流 + slot 池），提交帧只有 `prompt` 一个字段且 `extra="forbid"`，指不了项目。
- **事实（现状）**：项目编址与按项目运行时已在回环 HTTP 控制台面完备（`POST /api/projects/{id}/runs` → `HttpProjectConsole`；`src/heagent/network/http_console_protocol.py:389/455` 已有 `project_id` 字段），但该面只挂回环、无远程可达性。
- **需求**：远程面收敛为 **WS 单通道**；提交帧新增**可选 `project_id`**——缺省 = 启动工作区（行为不变），带值 = 走项目链（per-project 围栏根 / 会话 / 产物 / ledger / memory / 项目独立并发名额）。
- **需求**：远程只开放四件事——列项目（远程投影仅 `id/name/available`，不带 path）、提交 run、订阅事件流（复用 `/api/runs/{run_id}/ws`）、取消 run（新增 `cancel_run` 帧）。
- **需求**：远程不开放配置读写、项目注册（维持 403）、会话历史浏览；WS 帧不暴露 `session_id`，带 `project_id` 的 run 缺省续该项目最近会话（对齐 HTTP 项目链语义）。
- **需求**：审批维持 fail-safe 拒绝（远程端只见 `tool_error=True` 的 tool_result），不加远程审批通道；external 档非 docker 沙箱时补一条启动 WARNING。
- **需求**：run 事件信封**不加** `project_id`（客户端本地维护 run→project 映射）；并发容量参数不动。
- **假设**：自研 APK 能在本地维护 run→project 映射并对 cursor 做持久化（否则「断线续流不丢事件」不成立）。
- **假设**：「缺省续该项目最近会话」在既有 HTTP 项目链里已有等价语义，可直接对齐而不新增状态机；复用单 run 事件端点无需改动事件协议。
- **假设**：新 `cancel_run` 帧与既有单 run 端点 `cancel` 同源，因此 readonly listener 下仍回 `invalid_request`。
- **验收基线**：APK 列项目 → 两项目**同时**各提交一 run → 各自收完整事件流 → 取消其一 → 断线重连凭 cursor 续流不丢事件。
- **明确不做**：per-project token、两段式注册确认、多轮续聊 / session 寻址、远程审批通道、per-project provider/model、跨项目协同、沙箱 fail-closed、goal/loop 远程驱动。
- **开放问题（4 条，Step 04/06 前需裁决）**：
  - ① 「非 docker 沙箱」判据取 `SANDBOX_BACKEND` 配置值还是启动期实际生效后端？
  - ② 列项目的 `available` 判定口径（目录存在 / 配置完整 / 围栏根可解析）？
  - ③ run 被取消后 cursor 与尾部事件的续流语义？
  - ④ `cancel_run` 是否继承「readonly listener 下 cancel 回 `invalid_request`」的既有约束？

## 用户补充（User Responses）

<工作流中记录的补充决策或用户回答；裁决原文一并写进 `progress.md` 的决策日志>

## 目标与产出

### Requirements

- R1 WS 提供项目列表，远程投影字段恰为 `id` / `name` / `available`（不含 `path` / `last_opened_at` / `is_default`），集合与顺序以 `ProjectRegistry.list()` 实测为准，`MAX_PROJECTS = 32` 下表现可判定（来源：PRD §5 R1）
- R2 提交帧新增可选 `project_id`（`min_length=1`，缺省 `None`），缺省时提交上下文与改动前逐字等价（来源：PRD §5 R2）
- R3 带 `project_id` 的提交走项目链：围栏根、会话落点、产物、`ExecutionLedger`、工具审计根（`RunContext.state_root`）、memory 六项均指向该项目，无任一路落启动工作区根（来源：PRD §5 R3）
- R4 缺省续该项目最近一次会话；从未有会话则新建（显式分支，不是错误）；WS 帧不回带 `session_id`（来源：PRD §5 R4）
- R5 未知 / 不可用 `project_id` 返回具名 `WsErrorFrame`，不创建 run、不占用名额；错误码登记进 `transport_errors` 契约；提交前经 `ProjectRegistry.find()` 二次校验（含 1 次 `is_dir`）（来源：PRD §5 R5）
- R6 事件流订阅复用既有 `/api/runs/{run_id}/ws`，不新增端点；事件信封不加 `project_id`（带该键判 `WsFrameError`），golden 信封逐字未变（来源：PRD §5 R6）
- R7 断线重连凭客户端持久化的 cursor 续流不丢事件（协议面不变，能力由客户端持久化 + 既有单 run 事件端点语义共同承载）（来源：PRD §5 R7）
- R8 新增 `cancel_run` 帧：取消指定 run 并让订阅端收到终态；不存在 / 已终止 run 回具名错误或显性 no-op（二者择一，由测试钉死）；绝不误杀其它 run；readonly listener 下与既有 cancel 同源回 `invalid_request`（来源：PRD §5 R8）
- R9 两项目并发各 1 run：事件流 `run_id` 不交叉、ack 指向正确 run、取消只作用于目标 run；名额仍受全局 + per-project 双重约束，参数不动（来源：PRD §5 R9）
- R10 传输层保持哑传输：`network/` 不新增对 `heagent.config` / `heagent.pub.projects` / `heagent.engine` / `heagent.agent` 的 import；`network/ws_server.py` 不 import `network/http_server.py`；`RunWebSocketService` 是 Protocol ⇒ 加 `project_id` 必须同改 Protocol 与实现（来源：PRD §5 R10）
- R11 远程面白名单不扩张：WS 上无配置读写 / 项目注册 / 会话历史浏览的帧或端点；HTTP 侧远程注册仍 403；远程提交的审批类工具调用结果仍只见 `tool_error=True`（来源：PRD §5 R11）
- R12 `external` 档 + 非 docker 沙箱：每次启动输出一条固定锚点 WARNING（可 grep，含 `listener=external` 与沙箱后端名）；docker 档不输出；不改变启动成败（来源：PRD §5 R12）
- R13 注册表不可读时分路：列表 fail-soft（空表 + 可判定的「注册表不可用」信号 + WARNING）；提交 fail-loud（即 R5 的具名错误）（来源：PRD §5 R13）
- R14 契约与文档同步：golden 帧 + `tests/fixtures/contract_baselines/transport_{errors,routes}.json` 重生成，diff 只含预期新增；`docs/errors.md` 与远程访问口径文档同步；「id 随路径派生、目录移动即换键、APK 需重选」写进客户端对接说明（来源：PRD §5 R14）

### Constraints

- 架构边界机器可判：`network/` 不得 import `heagent.config` / `heagent.pub.projects` / `heagent.engine` / `heagent.agent`；`network/ws_server.py` 不得 import `network/http_server.py`（共享契约住 `http_protocol.py`）；判据 = `tests/test_architecture_contracts.py`。
- 帧兼容：帧族全 `extra="forbid"`（`ws_protocol.py` 6 处）⇒ 新增字段必须可选 + 有默认值；golden 帧逐字不变；事件信封不加 `project_id`。
- HTTP 回环控制台面零行为变更（NG12）：既有项目链请求模型 `project_id: str = Field(min_length=1)` 只作 WS 校验口径的对齐源，不改写。
- 全异步：库代码无同步 I/O；工具执行链 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler 不变。
- 契约快照 4 份（`exception_types` / `public_exports` / `transport_errors` / `transport_routes`）重生成后 diff 只含预期新增；`transport_errors.json` 顶层为 `{entries, envelope, status_sources, unmapped_codes}`。
- 安全面零新增信任锚：认证仍是单一 Bearer token（`external` 档只读用户级 `~/.heagent/setting.md`，缺 token 仍 fail-closed），TLS 信任锚仍是 SPKI-SHA256 pin，不新增端口与证书物料。

### Done when

- 一条端到端用例走完 ADR-005 五步：列项目 → 两项目各提交 1 run → 各自事件流完整 → 取消其一 → 断线重连凭 cursor 续流不丢事件。
- `AC1`–`AC10` 每条都有可跑断言或可 grep 判据，无一条以人工确认替代；R7 的 `AC gap` 已落成可跑断言。
- 缺省路径等价性成立：不带 `project_id` 的既有 WS 提交 / 订阅测试断言逐字未改且全绿。
- 依赖边界零新增：`pytest tests/test_architecture_contracts.py -q` 绿，`network/` 对运行栈 / 配置 grep 零命中。
- 契约漂移可一眼看完：4 份快照 diff 只含预期新增（`transport_errors` 新增取消 / 未知项目错误码，`transport_routes` 无新端点）。
- 远程投影不泄路径：列项目响应键集合 == `{id,name,available}`，`"path"` 计数为 0。
- 启动告警可判定：`external` + 非 docker 沙箱恰 1 条固定锚点 WARNING/启动，docker 档 0 条，两者退出码均正常。
- 回归面全绿：`pytest`、`ruff check`、`ruff format --check`、`mypy src`、`bandit -r src/ -ll`。

### Boundaries

- 认证与注册面不扩张：不做 per-project token、两段式注册确认、远程配置读写 / 项目注册 / 会话历史浏览（NG1 / NG2 / NG9）。
- 会话与交互面不扩张：帧不暴露 `session_id`、不做多轮续聊 / session 寻址、不开远程审批通道、不动 per-project provider / model（NG3 / NG4 / NG5）。
- 运行编排面不扩张：无跨项目协同、不做沙箱 fail-closed、不远程驱动 goal / loop（NG6 / NG7 / NG8）。
- 既有语义保持：事件信封不加 `project_id`、并发容量参数不动、HTTP 回环面语义零变更、项目 id 仍 path-derived（NG10 / NG11 / NG12 / NG13）。

### Notes

- 2026-11-23 Decision: 切 3 个 epic（契约 / 运行时 / 收口），切分轴 = 验收面而非代码目录；本需求改动横跨 `network/` · `agent/` · `cli/` 且层内文件高度重叠，按目录切会把一次协议变更拆成多次构建。
- 2026-11-23 Decision: 否掉「单 epic 全包」（14 条需求混一次构建，红的层次定位不到）与「每个 R 一个 epic」（多数只有单 story 量级，构建顺序失去意义）。
- 2026-11-23 Decision: 否掉「按远程四件事切」（列 / 提交 / 订阅 / 取消各一 epic）—— 四者共用同一帧族与同一注入端口，拆开即四次快照漂移与四次回归。
- 2026-11-23 Decision: `R1` 列项目随 E75 而非 E74 —— 帧与端口形状归 E74，投影真源（`ProjectEntry.available` 语义、`MAX_PROJECTS`、`list()` 顺序）归 E75。
- 2026-11-23 Decision: `R8 cancel_run` 归 E74（与既有单 run `cancel` 同源，属帧与权限口径），E76 只验证并发下「不误杀其它 run」。
- 2026-11-23 Decision: `R14` 契约快照重生成与文档同步一次性放 E76 收口，避免 E74 / E75 各自重生成同一批快照互相覆盖。
- 2026-11-23 Decision: epic 目录形态用 `epic-<编号>-<slug>`（非纯 `<e编号>-…`）—— 票树脚本 `EPIC_RE` 只认 `epic-*`、`epic_folders()` 只 glob `epic-*`，纯编号形态需改脚本且补丁会被角色包重装覆盖；人读编号仍写 `code` / `title` 前缀 / frontmatter 三处。

## 延期项

> 三审（R1/R2/R3）与 Step 07 期间发现的**不在本轮落改**项。逐条给来源轮次、位置与为何延后。

- 2026-11-23 R1 M-1：epic `Done when` 第 2 条「名额计数不变」缺直接判据 —— `tests/network/test_ws_project_submit.py:213-234` 只断言两条启动路径调用次数为 0。转 E75（`75.2` / `75.3` 适配器落地时连带补 inflight 计数断言）。
- 2026-11-23 R1 M-2：`E74-S05` 的 `## Verification` 命令一次性出现 5 红谱（`test_ws_event_contract.py`×3 + `test_ws_error_codes.py::test_network_never_imports_the_runtime_stack_or_config` + `test_ws_protocol.py::test_event_frame_round_trip_preserves_nested_sse_payload`），随后 4 次全绿 709。判环境产物（9p 缓存 / 首跑冷导入），归档不改代码；同一谱再现时按 `docs/testing.md` 分诊而不是当新回归。
- 2026-11-23 R1 L-1：单 run 端点 `cancel_run` 命中「绑定 run 已消失」时断连（`ws_commands.py:132-134`），与 epic R5 字面「不断连」有差；plan 74.3 已登记为刻意分层。E76 文档收口时统一措辞。
- 2026-11-23 R1 L-2：集合级端点的 `cancel_run` 分支无 `readonly` 判据，readonly 由「只读 listener 不注册集合端点」结构兜住 —— 该前提应在端点 docstring 明示（E76）。
- 2026-11-23 R1 L-3：`ProjectChannelService` 声明在 `network/ws_protocol.py` 并重导出，与 epic R2 字面「声明在 `ws_server.py`」不同（74.3 拆模块所致；epic Requirements 冻结，不回改）。后续 entry 按 `ws_protocol.py` 定位。
- 2026-11-23 R1 L-4：`project_id` 的 `max_length=16` 无判据（`run_id` 侧有对称用例）。补一例 17 字符 ⇒ `malformed`。
- 2026-11-23 R1 L-5：epic `Done when` 第 4 条字面「判 `WsFrameError`」，实际是出站帧模型的 pydantic `ValidationError`（入站才是 `WsFrameError`）。E76 统一口径。
- 2026-11-23 R1 L-6：单 run 端点接受 `project_service` 形参但从不使用（`ws_server.py:362`）。E75 装配时再决定是否收窄签名。
- 2026-11-23 R1 L-7：`story-e74-s03-cancel-run-plan.md:46` 记 `ws_protocol.py` 425 行，实测 426 —— 冻结段不回改，行数口径以实测为准。
- 2026-11-23 R2 M-1：`docs/framework.md:1771` 的架构目录树缺新增模块 `network/ws_commands.py`（253 行）；`network/` 没有 cli/pub 那样的目录白名单守卫，只能人工同步。转 **76.6**（文档收口），并考虑为该包补一条目录白名单。
- 2026-11-23 R2 M-2：`ws_commands.py:191-192` 把适配器异常的 `str(exc)` 原样放进错误帧 —— E74 无适配器故当前无泄漏，但 E75 适配器若把路径 / 工作区名写进消息即外泄。转 **75.2 / 75.3**：适配器侧约束 + 一条「错误帧不含路径形态」判据。
- 2026-11-23 R2 M-3：`docs/framework.md` 六处（`:1353` / `:1390` / `:1397` / `:1771` / `:1984` / `:1985`）命令集仍写 `{run, cancel, ping}`，实际已 4 值。转 **76.6**。
- 2026-11-23 R3 M-1：生产装配（`ws_host.py:268-289` → `build_ws_servers`）从不传 `project_service`，也没有 wiring 判据 ⇒ 当前生产行为是「带 `project_id` 恒回 `invalid_request`」。转 **75.5**：注入点 + 一条 wiring 判据（参照 `version=` 的既有判据形态）。
- 2026-11-23 R3 M-3：项目端口两次 await 无时间上界，集合级端点无 `_supervise`：端口挂起即占提交席位且断连不被感知。转 **75.2 / 75.3**：端口契约写明「必须有内部超时」+ 一条挂起用例。
- 2026-11-23 R3 M-4：「零副作用」只在 `ensure_available` 失败时成立；`start_project_run` 建 run 后抛错无幂等键（重试即双 run）。转 **75.2**：`ProjectChannelService` docstring 明确「提交失败不做原子性保证」，是否引入 `request_id` 由 E75 决定。
- 2026-11-23 R3 M-7：「未装配项目通道」与「帧字段拼错」共用 `invalid_request`，而 message 不在 `transport_errors` 契约面内 ⇒ 客户端只能靠文案分流。转 **76.6**：裁定是否新增具名 code。
- 2026-11-23 R3 M-8：集合级端点的 `cancel_run` 可取消任意 `run_id`（无所有权判定）——**这是设计意图**，但文档必须写成「入口口径：谁能连上谁就能取消，不是授权」（与安全声明第 3 条同型风险）。转 **76.6**。
- 2026-11-23 R3 L-4：`ws_protocol.py:97` 的 `_OPTIONAL_FRAME_FIELDS` 粒度是字段名而非 (命令, 字段)，将来若某命令的 `run_id` 变可选，唯一表达方式是放宽全局集合并连带放开 `cancel_run` 的必带语义。转 **75.6**。
- 2026-11-23 R3 L-5：`tests/network/test_ws_command_fields.py:23` 直接 import 私有 `_FRAME_FIELDS`（实现细节耦合）。转 **75.6**：加 `frame_fields(command)` 公开读口后测试改读。
- 2026-11-23 R1(E75) M-1：`projects` 帧的「条目 ↔ `registry_state` 同源快照」未成立 —— `list()` 走线程池读一次、健康探针 `health()` 再读一次（`cli/http.py:377-379` 的闭包），两次读之间注册表可被外部改动。当轮只把探针挪进线程池（不占事件循环），**单次读单源**未做。转 E76（若要收，形态 = `ProjectChannelService.list_projects` 一次读产出 `(entries, state)`）。
- 2026-11-23 R1(E75) M-2：R3 的「带 `project_id` 的 run 六项落点」缺 **WS 端到端**用例（现有判据停在 console 层：`tests/test_http_console_project_run.py`；adapter→console 只在假 console 上验）。转 E76-S05（ADR-005 五步串跑同面，端点级 fixture 一次建好）。
- 2026-11-23 R1(E75) L-1：epic R7 正文的「`cli/http.py` 两处 `build_ws_servers` 调用（`:449` / `:789`）」是改动前行号，改后为 `:492` / `:843`。epic Requirements 冻结不回改；后续按符号定位（`build_http_service` / `http_server_cmd`）。
- 2026-11-23 R1(E75) L-2：`tests/network/test_ws_server.py::test_build_ws_server_config_autofind_starts_from_ws_port` 首跑红、单跑与二次全跑绿（端口自动探测对环境敏感，非本 epic 引入）。按 `docs/testing.md` 当环境噪声。
- 2026-11-23 R1(E75) L-3：`run` / `projects` 的「only accepted on the run collection endpoint」文案在四个端点各写一份（`ws_server.py:508/622` + `ws_commands.py:113`，`run` 同款另三处）；用例只断言 `in` 子串 ⇒ 文案漂移不会红。可提取 `_only_on_collection(command)`，属跨 E74/E75 的既有形态。
- 2026-11-23 R1(E75) L-4：`ensure_available` 借 `get_project_config` ⇒ 每次提交多跑一次 `build_config_report` + 构 per-project 引擎（探针确认无落盘副作用，但这是巧合而非契约）。宜写进端口 docstring 的可 grep 义务。
- 2026-11-23 R2(E75) M-1：一次提交现在读注册表 3 次（`_guard_registry` 的健康探针 + `ensure_available` / `start_project_run` 各一次 console 解析），两次读之间注册表被改会看到不同快照。最坏退化回 `unknown_project`（旧行为），**不会**「跑错项目」，故不阻塞收口。与 R1 M-1 同根（单次读单源）。
- 2026-11-23 R2(E75) M-2：`_project_channel` 闭包（`cli/http.py:355-380`）无测试直调 —— 探针真被打到的只有经 75.5 wiring 用例的间接断言。补一条「闭包真调一次 `health()`」即可钉住。
- 2026-11-23 R2(E75) L-1：`project_service` 在 `ws_host.build_ws_app` / `WsServer.__init__` / `build_ws_servers` 三处声明成 `Any | None`（同类 `run_service` 是具体 Protocol）。宜收窄成 `ProjectChannelService | None`（同层 import，无循环风险）。
- 2026-11-23 R2(E75) L-2：端口异常的 `str(exc)` 原样进错误帧，当前生产文案都不含路径，但「不含路径」无集中守卫（与 E74 R2 M-2 同一缺口）。
- 2026-11-23 R3(E75) H-2 延伸（**需用户裁决**）：架构 AD-8 想要「只读 listener 也能看项目清单」，但只读 listener 不注册集合级端点（E74 端点集契约）+ 其余端点一律拒 `projects` ⇒ 该能力当前不可达，E75 按 §4.1 落地。要支持它需要新增一种只读端点形态（或给单 run 端点开 `projects` 白名单），属结构扩张、超出 E75 / E76 的 Boundaries ⇒ 记在此处，等 E76 收口或用户裁定。
- 2026-11-23 R3(E75) M-1：一次提交读注册表 4 次（守卫 health + 两次 console `find`，见 R2 M-1 同根），且守卫读与 console 读之间仍有窗口（那时损坏 ⇒ 仍旧 `unknown_project`）。窗口收窄但不闭合；单次读单源才能闭合。
- 2026-11-23 R3(E75) M-2：提交成功但 ack 发送失败时 run 已建、客户端拿不到 `run_id`（重试得 `run_conflict`），`ws event=submit_failed` 日志不记 `run_id`。宜补日志字段 + 端口 docstring 写明「成功后的 ack 丢失不在原子性保证内」。
- 2026-11-23 R3(E75) M-3：同一项目两客户端并发提交时回 `run_conflict`（会话级冲突），而 `docs/errors.md` 把「同一项目同时跑多个运行」写成 `project_busy`（后者只由删项目端点产生）⇒ 码的语义与文档不符，随 E76 文档收口统一。
- 2026-11-23 R3(E75) M-4：`ProjectChannelEntry.name` / `WsProjectsFrame.projects` 的上下界与 `registry_state` 默认值已按 AD §4.2 补齐（`name` 1–64、`projects` ≤32、默认 `ok`）；**时区混合的时间戳排序**（字符串序 vs 时间序）仍是缺口 —— `touch()` 恒写 UTC，只有手改文件触发，暂不修。
- 2026-11-23 R3(E75) L-1：`ProjectRegistryHealth.detail` 生产侧零消费者（只进模型与契约基线）。要么接进日志/诊断，要么收回导出面，择一。
- 2026-11-23 R3(E75) L-2：`HTTP_ENABLED=false` 时 console 现仍被构造 ⇒ `write_enabled` 时会为一个不存在的端口打「配置写通道已开启」的 stderr 告警。宜惰性化或把 echo 挪到 listener 真建之后。
- 2026-11-23 E76-R1 M-2：`_warn_external_without_sandbox` 只覆盖 `external`；`lan` 档（**无认证** + 明文 + 同网段可提交 run）在宿主执行时零告警 —— 风险高于 external（少一层 token）却无声音。R6 冻结只写 external，补喊需用户裁定（新增一条 `lan` 专属 WARNING，文案点名「无认证」）。
- 2026-11-23 E76-R1 M-3：`cli/http.py` 的 `http_server_cmd` 回落链在 `handler.engine` 未建时取**请求值**而非生效值 ⇒ 请求 `docker` 但引擎没建起来时不告警、实际远端 run 落宿主。需先确认 `engine` 为空的触发条件，再决定「取不到生效值就按请求值喊」或文案标 `(requested)`。
- 2026-11-23 E76-R1 M-4：`test_ws_remote_flow.py` 的 ADR-005 五步串跑仍在**端口替身**上；真 listener + 真 `HttpRunService` + 真 `AgentLoop` 的端到端未验（承 E75 登记的同名缺口）。属 Step 08 之后 / 后续 epic 的活。
