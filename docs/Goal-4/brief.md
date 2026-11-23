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
> 2026-11-23 复核：E74 / E75 / E76 三条 epic 交付后逐条取证，只剩下面两条仍待用户裁决；其余
> （含 R1 L-1/L-2/L-3/L-4/L-5/L-6/L-7、R2 M-1/M-2/M-3、R3 M-1/M-3）已闭合，记录见 `progress.md`。

- 2026-11-23 R3 M-4（**待裁决**）：提交失败无幂等键。现口径 = 「不提供原子性、不替客户端去重」，写在 `ProjectChannelService` docstring 并有一条判据钉住文案；是否引入 `request_id`（客户端可安全重试）由用户决定。
- 2026-11-23 R3 M-7（**待裁决**）：「未装配项目通道」与「帧字段拼错」共用 `invalid_request`，`message` 不进 `transport_errors` 契约面 ⇒ 客户端只能靠文案分流。是否新增具名码（如 `project_channel_unavailable`）由用户决定。
