# PRD · WS 远程项目通道（多项目控制）

- 目标 id：`ws-remote-project-channel`
- 角色：John（Product Manager），headless
- 依据：`brief.md`（原始需求 + 总结的需求 = ADR-005 收口版）、`step-01` 市场综述、`step-03` 需求简报 + 宿主实测（2026-11-23）
- 写作口径：**只陈述用户原话与 ADR-005 已有内容**，不引入新承诺（不设远程审批、不做多轮续聊、不做 per-project token）

## 1. 问题与价值

**问题（现状事实）**

- 远程唯一可提交通道是 WS `external` 档（Bearer token + TLS pin + 节流 + slot 池）；提交帧只有 `prompt` 一个字段且帧族全 `extra="forbid"` ⇒ **远程无法指定项目**。
- 项目编址与按项目运行时**已经存在且完备**，但只挂在回环 HTTP 控制台面（`POST /api/projects/{id}/runs` → `HttpProjectConsole`；`network/http_console_protocol.py:389/455` 已有 `project_id`）。
- 该面只绑回环 ⇒ 移动端（自研 APK）**没有任何可达路径**驱动多项目。
- 「认证」与「项目编址」因此分居两条通道：外部 WS **有认证无编址**、回环 HTTP **有编址无认证**。

**价值**

- 用**最小协议扩张**（一个可选帧字段 + 一个取消帧）把已有能力开放到远程，不新增第二条远程通道、不新增端口、不新增证书物料。
- 单机 Windows 上以「一次连接 + 请求级编址」驱动 2~5 个项目真并行，替代「每项目一条连接 / 一套端口」的编队方案。
- 认证面（token / TLS pin）与既有 WS 完全复用 ⇒ 远程安全模型零新增信任锚。

**代价（已显式接受）**

- 帧族 `extra="forbid"` ⇒ 新增字段属**破坏性变更**，必须同步帧模型与传输契约快照。
- 传输层需新增注入端口（项目解析器 / 投影函数），`network/` 的「哑传输」边界要靠这个端口维持而不是靠 import 运行栈。

## 2. 目标用户与场景

| 用户 | 场景 | 期望 |
|---|---|---|
| **APK 用户（首要）** | 人在外面，用手机连本机 `wss` 入口 | 一次连接内：列出本机已注册项目 → 同时给两个项目各提交一条任务 → 各自看事件流 → 中途取消其中一个 → 断线重连后凭 cursor 续上不丢事件 |
| 本机运维 | 改注册表 / 删目录 / 切安全档位 | 远程表现可预期；`external` 档 + 非 docker 沙箱每次启动有 WARNING |
| 协议契约方 | 改帧 / 发版 | golden 帧与 4 份契约快照无意外漂移；`network/` 依赖边界零新增 |
| 安全审查者 | 审远程可见面 | `project_id` 不扩张可见面（不泄 `path`、不开配置/注册/历史）、审批仍 fail-safe 拒绝 |

**验收基线的用户叙事（ADR-005）**：APK 列项目 → 两项目**同时**各提交 1 条 run → 各自收完整事件流 → 取消其一 → 断线重连凭 cursor 续流不丢事件。

## 3. 范围（In Scope）

- WS 提交帧新增**可选** `project_id`（`min_length=1`；缺省 `None` = 启动工作区，行为逐字不变）。
- 带值提交走**项目链**：per-project 围栏根 / 会话 / 产物 / ledger / memory / 项目独立并发名额。
- WS 远程面**只开四件事**：列项目（远程投影仅 `id` / `name` / `available`）、提交 run、订阅事件流（**复用**既有 `/api/runs/{run_id}/ws`，不新增端点）、取消 run（新增 `cancel_run` 帧）。
- 断线重连凭客户端持久化的 cursor 续流（协议不变，客户端侧持久化）。
- `external` 档 + **非 docker 沙箱**时的一条启动 WARNING。
- 帧 / 错误码 / 契约快照 / `docs/errors.md` 与客户端对接说明的同步。
- 传输层注入端口（项目解析器 + 项目投影纯函数）在**入口层**装配（`cli/`），`network/` 只吃端口。

## 4. 非目标（Out of Scope，含 ADR-005 挂账清单）

| 编号 | 非目标 | 说明 |
|---|---|---|
| NG1 | per-project token | 认证仍是单一 Bearer token；安全边界不按项目切分 |
| NG2 | 两段式注册确认 | 不做「先申请后确认」的设备注册流程 |
| NG3 | 多轮续聊 / session 寻址 | 帧不暴露 `session_id`；客户端不能指定会话 |
| NG4 | 远程审批通道 | 审批维持 fail-safe 拒绝，远程端只见 `tool_error=True` 的 tool_result |
| NG5 | per-project provider / model | 路由与 provider 选择不按项目分叉 |
| NG6 | 跨项目协同 | 无跨项目共享上下文 / 跨项目任务编排 |
| NG7 | 沙箱 fail-closed | 非 docker 沙箱不拒绝启动，只补 WARNING |
| NG8 | goal / loop 远程驱动 | 远程只提交 run，不驱动 goal 或 loop 工作流 |
| NG9 | 远程配置读写 / 项目注册 / 会话历史浏览 | 维持现状：远程注册 403，其余端点不存在 |
| NG10 | 事件信封加 `project_id` | 客户端本地维护 run→project 映射 |
| NG11 | 并发容量参数调整 | 全局名额与 per-project 名额口径不动 |
| NG12 | HTTP 回环面任何行为变化 | 回环控制台语义零变更，仅「复用」，不改写 |
| NG13 | 项目 id 语义变更（稳定 id） | id 仍 path-derived，见 Q5 / R14 |

## 5. 需求清单

| ID | 需求 | 优先级 | 验收标准引用 |
|---|---|---|---|
| **R1** | WS 提供项目列表，远程投影字段**恰为** `id` / `name` / `available`；不含 `path` / `last_opened_at` / `is_default`；集合与顺序与 `ProjectRegistry.list()` 实测一致（含「default 在末位」的实现事实）；`MAX_PROJECTS = 32` 上限下表现可判定 | P0 | AC5 |
| **R2** | 提交帧新增**可选** `project_id`（`min_length=1`，缺省 `None`）；缺省时提交上下文与改动前**逐字等价**（启动工作区围栏根 / 会话 / 产物根） | P0 | AC1 |
| **R3** | 带 `project_id` 的提交走项目链：围栏根、会话落点、产物、`ExecutionLedger`、工具审计根（`RunContext.state_root`）、memory 六项均指向该项目，且**无任一路**落启动工作区根 | P0 | AC3 |
| **R4** | 缺省续该项目**最近一次会话**；从未有会话则**新建**（显式分支，不是错误）；WS 帧不回带 `session_id` | P0 | AC3 |
| **R5** | 未知 / 不可用 `project_id`：返回具名 `WsErrorFrame`，**不创建 run、不占用名额**；错误码登记进 `transport_errors` 契约；提交前经 `ProjectRegistry.find()` 二次校验（含 1 次 `is_dir`） | P0 | AC4 |
| **R6** | 事件流订阅**复用**既有 `/api/runs/{run_id}/ws`，不新增端点；事件信封**不加** `project_id`（帧仍 `extra="forbid"`，带该键判 `WsFrameError`）；golden 信封逐字未变 | P0 | AC7（+AC6） |
| **R7** | 断线重连凭客户端持久化的 cursor 续流，**不丢事件**（协议面不变，能力由客户端持久化 + 既有单 run 事件端点语义共同承载） | P0 | **AC gap**（AC1–AC10 无一条覆盖重连续流） |
| **R8** | 新增 `cancel_run` 帧：取消指定 run 并让订阅端收到终态；对不存在 / 已终止 run 返回具名错误**或**显性 no-op（二者择一，必须由测试钉死）；绝不误杀其它 run；readonly listener 下与既有 cancel 同源回 `invalid_request` | P0 | AC9 |
| **R9** | 两项目并发各 1 run：事件流 `run_id` 不交叉、ack 指向正确 run、取消只作用于目标 run（另一 run 活到终态）；名额仍受全局 + per-project 双重约束，参数不动 | P0 | AC6（+AC3） |
| **R10** | 传输层保持哑传输：`network/` **不新增**对 `heagent.config` / `heagent.pub.projects` / `heagent.engine` / `heagent.agent` 的 import；`network/ws_server.py` **不 import** `network/http_server.py`；`RunWebSocketService` 是 Protocol ⇒ 加 `project_id` 必须**同改 Protocol 与实现** | P0 | AC2 |
| **R11** | 远程面白名单不扩张：WS 上无配置读写 / 项目注册 / 会话历史浏览的帧或端点；HTTP 侧远程注册仍 403；远程提交的审批类工具调用结果仍只见 `tool_error=True` | P0 | AC8 |
| **R12** | `external` 档 + **非 docker 沙箱**：每次启动输出**一条**固定锚点 WARNING（可 grep，含 `listener=external` 与沙箱后端名）；docker 档不输出；**不改变启动成败** | P1 | AC10 |
| **R13** | 注册表不可读时**分路**：列表 fail-soft（空表 + 可判定的「注册表不可用」信号 + WARNING）；提交 fail-loud（即 R5 的具名错误） | P1 | AC5、AC4 |
| **R14** | 契约与文档同步：golden 帧 + `tests/contract_baselines/transport_{errors,routes}.json` 重生成，diff **只含预期新增**；`docs/errors.md` 与远程访问口径文档同步；「id 随路径派生、目录移动即换键、APK 需重选」写进客户端对接说明 | P1 | AC7、AC4、AC5 |

**覆盖检查（AC → R）**

- AC1 → R2｜AC2 → R10｜AC3 → R3、R4｜AC4 → R5、R13、R14｜AC5 → R1、R13、R14
- AC6 → R6、R9｜AC7 → R6、R14｜AC8 → R11｜AC9 → R8｜AC10 → R12
- **唯一无 AC 的需求 = R7**（重连 cursor 续流），已在表中标 `AC gap`；其判据需在 Step 06 架构步落成可跑断言，否则 ADR 验收基线第 5 步不可判定。

## 6. 产品决策与假设

### 6.1 决策（Decision）

**已由 ADR-005 冻结（本轮不得重开）**

- **D1 远程面收敛为 WS 单通道**：否决「认证化 HTTP 项目链对外」（方案 B）与「per-project 端口 / 多实例编队」（方案 C）。
- **D2 帧级可选 `project_id`**：缺省 = 启动工作区，行为不变；不做连接级项目绑定。
- **D3 远程只开四件事**：列项目 / 提交 run / 订阅事件流 / 取消 run。
- **D4 不开放配置读写、项目注册（维持 403）、会话历史浏览**。
- **D5 帧不暴露 `session_id`**；带 `project_id` 的 run 缺省续该项目最近会话（对齐 HTTP 项目链语义）。
- **D6 审批维持 fail-safe 拒绝**，不加远程审批通道。
- **D7 事件信封不加 `project_id`**，客户端本地维护 run→project 映射。
- **D8 并发容量参数不动**。
- **D9 `external` 档非 docker 沙箱补启动 WARNING**。
- **D10 非目标清单（NG1–NG13）** 见 §4。

**本 PRD 新定**

- **N1 项目列表真源 = 本机注册表 `ProjectRegistry`**，不做磁盘扫描（依据用户 2026-11-23 裁决）。理由：磁盘扫描会把「看到的目录」当成「可提交的项目」，与项目链的注册语义分叉，且天然泄 `path`。
- **N2 传输层注入式接线，不新增装配机制**：项目解析器照 `run_service` 先例注入 `build_ws_servers`（`cli/http.py:449` / `:789` 已是 `run_service=…` 注入形态），`network/` 只吃端口 + 投影函数。理由：架构契约禁止 `network/` import 运行栈 / 配置，而唯一能注入的位置在入口层。
- **N3 id 语义保持 path-derived**（`"p"+sha256(normcase(path))[:8]`，`default` 为字面量），不引入稳定 id；客户端把 id 消失当「项目不可用 / 需重选」。理由：改 id 会动注册表格式与三条既有站点，ADR-005 未列入范围。
- **N4 `ProjectRegistry.list()` 顺序以实现为准**（default 在末位），修 docstring 而不是改实现。理由：列表顺序不承载安全或功能语义，改实现牵动三个站点与既有测试，收益为零。
- **N5 注册表不可读分路处置**：列表 fail-soft、提交 fail-loud。理由：一个可读性问题不该把整个远程面板打成错误态，但静默落错项目比空列表危险一个量级。
- **N6 提交路径二次校验，不做投影缓存**：直接走 `ProjectRegistry.find()`（已含 1 次 `is_dir`，零新依赖），列表结果只作提示；不引入缓存以免成为新的陈旧源。
- **N7 「缺省续最近会话」的边界显式化**：从未有会话 ⇒ 新建，作为**显式分支 + 测试**，不得被实现成「查不到即错误」。
- **N8 `cancel_run` 与既有单 run 端点 `cancel` 同源** ⇒ readonly listener 下回 `invalid_request`，不另立一套取消权限口径。

### 6.2 假设（Assumption，均带不成立后果）

- **A1** APK 可本地维护 run→project 映射（提交后由 ack 回带 `run_id` 即可建立）。若不成立 ⇒ 必须回退到「事件信封带 `project_id`」，与 D7 直接冲突，需重开裁决。
- **A2** per-project 围栏根 / 会话 / 产物 / ledger / memory / 名额在 HTTP 项目链里已可复用，WS 只需把 `project_id` 译成同一次调用（**本 PRD 新定：该「一次调用」抽成 HTTP 与 WS 共用的帧转译服务**）。若实测是散在 handler 里的编排 ⇒ 先做提取重构再接线，工作量上升。
- **A3** `available` 在列表时计算（`ProjectEntry` 注释：`Availability is computed when listing.`）⇒ 列表投影不需额外扫描。若不成立 ⇒ 32 条目可能触发 32 次 `is_dir`，需评估 WS 首帧预算。
- **A4** 远程多项目并行仍受「全局名额 + per-project 名额」双重约束，本需求只让带 `project_id` 的 run 计入该项目名额。若不成立 ⇒ 出现「两项目各自吃满全局名额」或名额记录跨项目串味。
- **A5** `external` 档非 docker 沙箱的 WARNING 是**新增启动自检项**，不与既有 TLS / 到期 / SAN 三条 WARNING 合流成 fail-loud。若被实现成拒绝启动 ⇒ 与 NG7 相悖，须打回。
- **A6** 既有单 run 事件端点的 cursor 语义足以支撑「断线续流不丢事件」（R7），无需新协议。若不成立 ⇒ R7 从 P0 的「客户端能力」升级为协议改动，需重新过 ADR。

## 7. 约束

### 7.1 架构约束（宿主实测，2026-11-23）

- `network/ws_server.py:89` 的 `RunWebSocketService` 是 **Protocol**，`:110 async def start_run(self, prompt: str) -> Any` ⇒ 加 `project_id` **必须同改 Protocol 与实现**。
- `cli/http.py:449` / `:789`：`build_ws_servers(settings, run_service=run_service, enabled=ws_on)` ⇒ **装配层已是注入式**，项目解析器可照 `run_service` 先例注入，不需要新造装配机制。
- `src/heagent/pub/projects.py`：`ProjectEntry`（frozen + `extra="forbid"`）= `id` / `name` / `path` / `available` / `last_opened_at` / `is_default`；`available` 在列表时计算；`project_id_for()` 为 path-derived；`default` 的 id 是字面量；`MAX_PROJECTS = 32`；注册表不可读时 fail-soft 空表 + warning。
- **`network/` 不得 import** `heagent.config` / `heagent.pub.projects` / `heagent.engine` / `heagent.agent`；**`ws_server.py` 不得 import `http_server.py`**（共享契约住 `http_protocol.py`）。
- 工具执行链不变：`PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler。
- 全异步，库代码无同步 I/O。

### 7.2 安全约束

- 远程可见面 = **四件事白名单**（R11）；`project_id` 到位不扩张可见面：投影不带 `path`，不开配置 / 注册 / 历史。
- 审批 **fail-safe 拒绝**（D6）：远程端只见 `tool_error=True`，不开远程审批。
- 信任锚仍是 TLS **SPKI-SHA256 pin**（`heagent tls fingerprint`；重签叶证书不改 pin，`rotate-key` 是唯一改 pin 动作）。本需求**不新增**任何信任锚或端口。
- `external` 档 token 只读用户级 `~/.heagent/setting.md`，项目 `.env` 无效；缺 token 拒绝启动（fail-closed）不变。
- 非 docker 沙箱的告警**只是 WARNING**（D9/NG7），不得升级为拒绝启动。
- 已知缺口沿用：`A55`（`WEB_SEARCH_API_KEY` 未配 ⇒ 本轮外部市场证据全 gap）；`A76`（客户端 pin 交付在另一仓）。

### 7.3 兼容约束

- 帧族全 `extra="forbid"`（`ws_protocol.py` 6 处）⇒ 新字段**可选 + 有默认值**是硬要求；golden 帧逐字不变。
- 契约快照 4 份（`tests/contract_baselines/` 的 `exception_types` / `public_exports` / `transport_errors` / `transport_routes`）重生成后 diff 只含预期新增；`transport_errors.json` 顶层是 `{entries, envelope, status_sources, unmapped_codes}`。
- HTTP 回环控制台面**语义零变更**（NG12）：既有项目链请求模型 `project_id: str = Field(min_length=1)` 是 WS 校验口径的对齐源（非空、不做 id 格式臆断）。
- 缺省路径（不带 `project_id`）必须与改动前逐字等价（R2 / AC1）。
- 架构契约测试 `tests/test_architecture_contracts.py` 为可执行断言，改依赖面必须同步 `FORBIDDEN_RUNTIME_IMPORTS`。

### 7.4 运维约束

- WARNING 需**固定锚点可 grep**（含 `listener=external` 与沙箱后端名），且不改变启动成败（R12）。
- 「沙箱是否 docker」的判据取**启动期实际生效后端**（见 Q1 默认处置），配置值在降级路径下可能说谎。
- 客户端对接需显性写明：id 随路径派生、目录移动需重选；run→project 映射与 cursor 由 APK 本地维护（A1）。
- 客户端 pin 交付落在另一仓（`A76`）；不支持 pin 的客户端连不上属预期，不是服务端故障。

## 8. 未决产品决策（需后续步骤关闭的 open question）

逐条给默认处置与理由；关闭时机统一为 **Step 06 架构**（产品侧不阻塞）。

| ID | 问题 | 默认处置 | 理由 |
|---|---|---|---|
| **Q1** | 「非 docker 沙箱」判据取 `SANDBOX_BACKEND` 配置值还是启动期**实际生效后端**？（brief ①） | **取「启动期实际生效后端」**；若启动期暂无统一读口，允许退化为读配置值，但须在 Step 06 记偏离 | 安全告警要讲**实际保护等级**；配置值在「daemon 不可用 ⇒ 显性降级为宿主执行」路径下会说谎 |
| **Q2** | 列项目的 `available` 判定口径（目录存在 / 配置完整 / 围栏根可解析）？（brief ②） | **沿用既有 `ProjectEntry.available` 语义（列表时计算，`is_dir` 级）**，不新立口径、投影不加字段；提交路径另做二次校验（R5/N6） | 远程投影应是既有语义的**只读投影**，不是第二套真源；二级判据交给提交路径 fail-loud |
| **Q3** | run 被取消后 cursor 与尾部事件的续流语义？（brief ③） | **cursor 语义不变**（既有单 run 事件端点是唯一真源）：取消后订阅端照常收到终态，仍可凭 cursor 续读到尾部；若该 run 已被清理则回具名错误，**不静默空流** | 取消是 run 生命周期事件，不是事件流的终止规则；静默空流会让客户端无法区分「没有更多事件」与「连接坏了」 |
| **Q4** | `cancel_run` 是否继承「readonly listener 下 cancel 回 `invalid_request`」？（brief ④） | **继承**（N8）：与既有单 run `cancel` 同源，readonly listener 下回 `invalid_request` | 不为「远程便于取消」新开一条与既有安全口径不同的权限路径；判据并入 R8/AC9 |
| **Q5** | `project_id` 稳定性：path-derived（目录移动即换键）是否可接受？ | **接受（N3）**：远程原样暴露既有 id 语义，APK 把 id 消失当「不可用 / 需重选」，并在对接说明显性写明 | 引入稳定 id 会动注册表格式与三条既有站点，ADR-005 未列入范围 |
| **Q6** | `ProjectRegistry.list()` 顺序（docstring 说 default 首位，实现放末位） | **以实现为准（N4）**，修 docstring，并把「顺序 == 实现顺序」写进 AC5 | 顺序不承载安全或功能语义，改实现牵动三站点与既有测试，收益为零 |
| **Q7** | 注册表不可读时的远程表现（fail-soft 空表 vs 具名错误） | **分路（N5）**：列表 fail-soft + 可判定信号 + WARNING；提交 fail-loud（具名错误） | 面板不该因可读性问题整体错误态；但静默落错项目比空列表危险一个量级 |
| **Q8** | `available` 的 TOCTOU（列表 true、提交时目录已删/被换） | **提交前二次校验（N6）**：走 `ProjectRegistry.find()`，列表结果只作提示，不引入投影缓存 | 缓存会变成新的陈旧源；二次校验零新依赖 |
| **Q9** | 缺省 `project_id` 时的「最近会话」语义边界（无会话怎么办） | **续该项目最近会话；从未有会话 ⇒ 新建**（N7），并写成显式分支 + 测试 | ADR-005 已写明对齐 HTTP 项目链，偏离即行为分叉；但「查不到会话」不得实现成错误 |

## 9. 成功度量（可观察）

**验收基线（P0 全绿才算交付）**

- 一条端到端用例：列项目 → 两项目各提交 1 run → 各自事件流完整 → 取消其一 → 断线重连凭 cursor 续流不丢事件（最后一步落在 `AC gap`，需 Step 06 补判据）。
- `AC1`–`AC10` 逐条有可跑断言或可 grep 判据，无一条以「人工确认」替代。

**可观测指标（命令级）**

- `pytest tests/test_architecture_contracts.py -q` 绿；全仓 `grep -rn "pub.projects\|heagent.config\|heagent.engine\|heagent.agent" src/heagent/network/` 零命中（AC2）。
- 4 份契约快照 `diff` **只含预期新增**：`transport_errors` 新增取消/未知项目错误码，`transport_routes` 无新端点（事件流复用）。
- 列项目响应 JSON 的键集合 == `{id,name,available}`，`grep -c '"path"'` = 0（AC5）。
- 两项目并发用例断言：事件帧 `run_id` 交叉计数 = 0；取消只让目标 run 到终态（AC6）。
- 启动日志 grep 锚点：`external` + 非 docker 沙箱 ⇒ 恰好 1 条 WARNING/启动；docker 档 ⇒ 0 条；两者退出码均正常（AC10）。
- 回归面：`pytest` 全绿；`ruff check` / `ruff format --check` / `mypy src` / `bandit -r src/ -ll` 绿。
- 缺省路径等价性：不带 `project_id` 的既有 WS 提交与订阅测试**断言逐字未改**且全绿（AC1）。

**不作为成功度量**

- 「APK 能跑通」不是本仓度量（客户端 pin 与联调在另一仓，`A76`）。
- 外部同类产品的对比结论不进入度量（`A55`：本轮无 web 检索，全部外部论断为 gap）。

## 10. 来源

**需求与决策真源**

- `docs/Goal-4/brief.md`（原始需求段冻结；「总结的需求」= ADR-005 收口版；4 条开放问题）
- `docs/decisions/adr-0005-ws-remote-project-channel.md`（ADR-005，决策日期 2026-11-23；D1–D10 与 NG1–NG13 来源）
- 用户 2026-11-23 裁决：项目列表真源 = 本机注册表（记于 `step-03` 报告，本 PRD 落为 N1）

**分析与证据产物**

- `docs/Goal-4/step-01-market-research/report.md`（市场综述 9 条：本地证据 3 条 + gap 6 条；本轮**无 web 检索**）
- `docs/Goal-4/step-03-analyze-requirements/report.md`（事实 10 条 / 假设 5 条 / AC1–AC10 / 7 条 story 建议 / 5 条开放问题及默认处置）

**宿主实测代码位置（2026-11-23）**

- `src/heagent/network/ws_server.py:89`、`:110`
- `src/heagent/cli/http.py:449`、`:789`
- `src/heagent/pub/projects.py`
- `src/heagent/network/http_console_protocol.py:389`、`:455`
- `src/heagent/network/ws_protocol.py`
- `src/heagent/network/ws_host.py`
- `tests/test_architecture_contracts.py`
- `tests/contract_baselines/`

**台账**

- `A55` —— `WEB_SEARCH_API_KEY` 未配，本轮市场证据全 gap
- `A76` —— 客户端 TLS pin 交付在另一仓
