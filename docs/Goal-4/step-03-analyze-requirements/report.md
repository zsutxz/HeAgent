# Step 03 · analyze-requirements 报告

- 目标：`Goal-4`
- 执行角色：`bmad-agent-analyst`（headless 子会话）
- 输入：`brief.md`、`step-01-market-research/report.md`、`step-02-brainstorm-options/report.md`、ADR-005、仓库实测证据
- 输出：需求简报 + story 粒度工作拆分建议（**不落票树**）

## 需求简报

### 目标与非目标

**目标**

- 远程 APK 在**不新增第二条远程通道**的前提下驱动多个独立项目并行开发（2~5 个、单机 Windows）：唯一远程面 = 既有 WS 单通道。
- 在提交帧上加**可选 `project_id`**：缺省 = 启动工作区（行为逐字不变），带值 = 走项目链（per-project 围栏根 / 会话 / 产物 / ledger / memory / 并发名额）。
- WS 侧只开四件事：列项目（投影仅 `id/name/available`）、提交 run、订阅事件流（复用 `/api/runs/{run_id}/ws`）、取消 run（新增 `cancel_run` 帧）。
- 项目列表真源 = **本机注册表**（`ProjectRegistry`），不是磁盘扫描（用户 2026-11-23 裁决）。
- `network/` 侧维持「哑传输」：项目语义经**注入端口 + 投影函数**到达，传输层不 import 运行栈/配置/`pub.projects`。

**非目标（本迭代明确不做）**

- per-project token / 两段式注册确认 / 多轮续聊与 session 寻址 / 远程审批通道。
- per-project provider·model / 跨项目协同 / 沙箱 fail-closed / goal·loop 远程驱动。
- run 事件信封里加 `project_id`（客户端本地维护 run→project 映射）。
- 并发容量参数调整；HTTP 回环面任何行为变化；远程注册（维持 403）。

### 干系人

- **APK 用户** · 关注点：一次连接能列出本机已注册项目、并发跑多条、能中途取消、看得清哪个 run 属于哪个项目 · 验收口径：四件事全可达且错误可见（未知项目 / 取消已终止 run 有具名错误，不是静默成功）。
- **本机运维** · 关注点：注册表改动 / 目录删除后远程表现可预期、安全档位切换有提示 · 验收口径：external 档 + 非 docker 沙箱每次启动一条 WARNING；注册表不可读不导致提交静默落到错误项目。
- **协议契约方** · 关注点：既有帧族 `extra="forbid"` 与 golden 帧不变、`contract_baselines/transport_*` 快照无意外漂移、`network/` 依赖边界零新增 · 验收口径：`tests/test_architecture_contracts.py` + 传输契约快照测试绿；新增帧字段均为可选默认值。
- **安全审查者** · 关注点：远程可见面不因 `project_id` 扩张（不泄 `path`、不开配置/注册/历史）、审批仍 fail-safe 拒绝 · 验收口径：投影字段白名单可断言；WS 上无配置读写与注册端点；远程提交的审批类工具调用仍只见 `tool_error=True`。

### 事实（有证据）

- **提交端口当前只收 prompt**：`network/ws_server.py` 的 `RunWebSocketService.start_run(self, prompt: str)` —— 加 `project_id` 必须动协议端口签名与端点解析，不是「加个可选字段」这么轻。
- **ws_server 的 import 面已经收窄**：只 import `network/http_protocol`、`network/ws_protocol`、`network/ws_auth`（无 `http_server`、无 `pub.projects`、无 `config`）⇒ 架构契约现状成立，本需求不得破坏。
- **装配点（唯一能注入注册表读口的地方）在入口层**：`cli/http.py` 从 `cli/http_config.py` 导入 `build_ws_servers` / `build_ws_server_config`，`_serve_web(http_server, ws_servers)` 是唯一「跑到底」形态 ⇒ 项目投影与注册表访问注入落 `cli/`，network 侧只吃端口。
- **`WsServerConfig` 住 `network/ws_host.py`**，其 `readonly` 已在端点上生效（`build_ws_endpoint(readonly=...)`）⇒ 本需求实际**不需要**新增配置项。
- **`ProjectEntry` frozen + `extra="forbid"`**，字段 = `id` / `name` / `path` / `available` / `last_opened_at` / `is_default`，`Availability is computed when listing.` ⇒ 投影函数有明确白名单可剥。
- **`project_id_for(path)` = `"p" + sha256(normcase(normalize(path)))[:8]`**，`default` 的 id 是字面量 ⇒ id 是 path-derived，目录移动即换键。
- **`ProjectRegistry.list()` 实现 = `[*registered(按 last_opened_at 倒序), default]`**，与 docstring「default 在首位」不一致（既有文档缺陷）。
- **`find(id)` = 1 次注册表读 + 1 次 `is_dir`；未登记 ⇒ `None`；注册表不可读 ⇒ fail-soft 空表 + warning**；`MAX_PROJECTS = 32`。
- **既有项目链请求契约已存在**：`network/http_console_protocol.py` 的 `project_id: str = Field(min_length=1)` ⇒ WS 侧校验口径可直接对齐（非空、不做 id 格式臆断）。
- **帧族全 `extra="forbid"`** ⇒ 「事件信封不加 `project_id`」是**可执行断言**，不是口头约定。

### 假设

- **假设 A**：APK 侧可本地维护 run→project 映射（提交后由 ack 帧回带 `run_id` 即可建立）· 若不成立 ⇒ 必须回退到「事件信封带 `project_id`」，与 ADR-005 直接冲突，需重开裁决。
- **假设 B**：per-project 围栏根 / 会话 / 产物 / ledger / memory / 并发名额的既有实现在 HTTP 项目链里已可复用，WS 只需把 `project_id` 译成同一次调用 · 若不成立（HTTP 侧是散在 handler 里的编排）⇒ 需先做「帧转译共用服务」提取，S3 体量翻倍。
- **假设 C**：`available` 是列表时计算 ⇒ 列表投影不需要额外 `is_dir` 扫描 · 若不成立 ⇒ 列项目可能对 32 个条目做 32 次 `is_dir`，需评估 WS 首帧预算。
- **假设 D**：远程多项目并行仍受既有全局并发名额与 per-project 名额双重约束，本需求只是让「带 `project_id` 的 run 计入该项目的名额」· 若不成立 ⇒ 会出现「两项目各占满全局名额」或「名额记录跨项目串味」。
- **假设 E**：`external` 档 + 非 docker 沙箱的启动 WARNING 属新增启动自检项，不与既有 TLS/到期/SAN 三条 WARNING 合流成 fail-loud · 若被实现成拒绝启动 ⇒ 与「非目标：沙箱 fail-closed」相悖，须打回。

### 验收标准（可判定）

- **AC1（缺省不回落）**：提交帧不带 `project_id` 时，提交服务收到的上下文与改动前逐字等价（启动工作区围栏根/会话/产物根），既有 WS 提交与订阅测试全绿，`tests/contract_baselines/transport_*` 快照无差异。
- **AC2（依赖边界零新增）**：`pytest tests/test_architecture_contracts.py -q` 绿；全仓 grep 确认 `network/` 内无 `heagent.pub.projects` / `heagent.config` / `heagent.engine` / `heagent.agent` import；`network/ws_server.py` 仍不 import `network/http_server.py`。
- **AC3（带值走项目链）**：以两个临时注册项目各提交 1 条 run，断言围栏根、会话落点、产物、`ExecutionLedger`、工具审计根（`RunContext.state_root`）、memory 六项均指向该项目路径，且**无任一路**落启动工作区根。
- **AC4（未知 / 不可用 id 显性失败）**：`project_id` 未登记或项目目录不可用时返回具名 `WsErrorFrame` 错误（非 fail-soft 空跑、非 `ack` 成功），且不创建 run、不占用名额；错误码在 `transport_errors` 契约里有登记。
- **AC5（投影等于注册表投影）**：列项目响应字段恰为 `id` / `name` / `available`，无 `path`、无 `last_opened_at`、无 `is_default`；集合与顺序与 `ProjectRegistry.list()` 实测一致（含「default 在末位」的实现事实）；注册表含 32 项时按 `MAX_PROJECTS` 上限表现可判定。
- **AC6（两项目不串味）**：两项目并发各 1 个 run 时，事件流 `run_id` 不交叉、ack 指向正确 run、取消只作用于目标 run（另一 run 活到终态）。
- **AC7（信封无 project_id）**：`WsEventFrame` 仍 `extra="forbid"`，带 `project_id` 的事件帧被判 `WsFrameError`；golden 信封逐字未变。
- **AC8（四件事白名单不扩张）**：WS 上不存在配置读写、项目注册、会话历史浏览的帧或端点；HTTP 侧远程注册仍 403；远程提交的审批类工具调用结果仍只见 `tool_error=True`。
- **AC9（取消帧）**：新增 `cancel_run` 帧可取消指定 run 并让订阅端收到终态；对不存在 / 已终止 run 返回具名错误或显性 no-op（二者择一但必须有测试钉死），且绝不误杀其它 run。
- **AC10（运维告警）**：`external` 档 + 非 docker 沙箱时每次启动输出一条固定锚点 WARNING（可 grep 断言，含 `listener=external` 与沙箱后端名）；docker 档不输出；该 WARNING 不改变启动成败。

## 工作拆分建议（story 粒度，不落票树）

- **S1 · 帧与错误码契约** · 交付物：`cancel_run` 帧、提交帧新增**可选** `project_id`（`min_length=1`，缺省 `None`）、错误码在 `transport_errors` 契约登记、golden 帧与契约快照更新 · 验证：AC7（`extra="forbid"` 仍拒未知键）、快照 diff 只含新增项、`parse_command_frame` 拒绝畸形 `project_id` · 依赖：无。
- **S2 · 提交端口签名扩展** · 交付物：`RunWebSocketService.start_run` 增可选 `project_id` 形参；端点解析透传；`cancel_run` 接既有取消通道 · 验证：AC1、AC9、AC2 · 依赖：S1。
- **S3 · 帧转译共用服务（项目链）** · 交付物：把「`project_id` → 围栏根/会话/产物/ledger/审计根/memory/并发名额」收敛成 HTTP 项目链与 WS 共用的一次调用；未知/不可用 id 显性失败 · 验证：AC3、AC4；复用性由「HTTP 项目链既有测试无需改断言」证明 · 依赖：S2（若实测 HTTP 侧是散装编排，本 story 先做提取重构再接线）。
- **S4 · 只读项目投影与注入落点** · 交付物：`ProjectEntry → {id,name,available}` 投影纯函数 + `cli/http_config.py::build_ws_servers` 注入注册表读口；`list()` 顺序口径对齐 · 验证：AC5、AC2 · 依赖：S1（与 S3 可并行，写集不相交）。
- **S5 · 并发隔离与名额** · 交付物：两项目并发路径的名额与产物/审计根隔离端到端夹具 · 验证：AC6、AC3 六项落点断言 · 依赖：S3、S4。
- **S6 · 远程面白名单与安全口径固化** · 交付物：断言测试（WS 无配置/注册/历史端点、远程审批 fail-safe 拒绝）+ external 档非 docker 沙箱启动 WARNING + `docs/errors.md` 与远程访问口径文档同步 · 验证：AC8、AC10 · 依赖：S2、S5。
- **S7 · 远程契约交接与回归面** · 交付物：APK 对接说明（四件事 + `cancel_run` 帧 + run→project 本地映射前提 + id 稳定性告警口径）、传输契约快照重生成、全量回归 · 验证：4 份快照 diff 仅含预期新增；`pytest` 全绿、`ruff`/`mypy`/`bandit` 门禁绿 · 依赖：S1–S6 全 built。

## 开放问题（竞争解释 + 默认处置）

- **`project_id` 稳定性（path-derived，目录移动即换键）** —— A：既有设计，远程投影原样暴露，APK 把 id 消失当「项目不可用/需重选」；B：引入稳定 id（注册表增列或改算法）。· **默认处置：取 A** —— 改 id 语义会动注册表格式与三条既有站点，属破坏性且 ADR-005 未列入范围；在 S7 对接说明里显性写明「id 随路径派生、移动后需重选」，并让 AC5 覆盖「id 集合随注册表变」的可判定性。
- **`ProjectRegistry.list()` 顺序（docstring 说 default 首位，实现放末位）** —— A：以实现为准，修 docstring；B：docstring 才是期望，改实现。· **默认处置：取 A** —— 远程列表顺序不是安全或功能承载项，改实现牵动三个站点与既有测试，收益为零；S4 顺手对齐 docstring，并把「顺序 == 实现顺序」写进 AC5。
- **注册表不可读时的远程表现（fail-soft 空表 + warning）** —— A：沿用 fail-soft；B：返回具名错误。· **默认处置：分路取** —— 列项目维持 fail-soft（避免一个可读性问题把整个远程面板打成错误态），但响应需带可判定的「注册表不可用」信号并落 WARNING；**提交路径必须 fail-loud**（AC4 已有具名错误），因为静默落错项目比空列表危险一个量级。
- **`available` 的 TOCTOU（列表 true、提交时目录已删/被换）** —— A：列表结果即事实；B：提交前二次校验。· **默认处置：取 B** —— 提交路径直接走 `ProjectRegistry.find()`（已含 1 次 `is_dir`，零新依赖）做二次校验，列表结果只作提示；不引入投影缓存，以免缓存成为新的陈旧源。
- **`project_id` 缺省时的「最近会话」语义边界** —— A：缺省续「该项目最近一次会话」，从未有会话则新建；B：缺省一律新建会话。· **默认处置：取 A** —— ADR-005 已写明「对齐 HTTP 项目链（缺省续该项目最近会话）」，偏离即行为分叉；但把「从未有会话 ⇒ 新建」写进显式分支与测试，避免实现者把「查不到会话」写成错误。

## 宿主验收核对

| 核对项 | 结果 | 证据 |
|---|---|---|
| 需求有证据支撑 | 通过 | 事实 10 条，均指向仓库文件 / 契约测试 |
| 需求可验证 | 通过 | AC1–AC10 全部给可跑断言或可 grep 判据 |
| 区分事实与假设 | 通过 | 事实 10 条 / 假设 5 条（各带不成立后果） |
| 竞争解释给默认处置 | 通过 | 开放问题 5 条，均含 A/B 与默认处置理由 |
| 未落票树（Step 04 前只读边界） | 通过 | `tickets/tickets.toml` 仍为空表 |
| 事实抽检：`start_run(prompt)` 签名 | 通过（宿主实测） | `ws_server.py:89` `RunWebSocketService` 是 **Protocol**，`:110 async def start_run(self, prompt: str) -> Any` ⇒ 加 `project_id` 需同改 Protocol 与实现 |
| 事实抽检：装配注入点 | 通过（宿主实测） | `cli/http.py:449` `build_ws_servers(settings, run_service=run_service, enabled=ws_on)`、`:789` 同形态 ⇒ **run_service 已是注入参数**，项目解析器可照此注入，无需新造装配机制 |
