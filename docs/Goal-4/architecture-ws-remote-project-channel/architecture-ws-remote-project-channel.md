# 架构 spine · WS 远程项目通道

- goal：`Goal-4`（`docs/Goal-4/`）
- 需求真源：`prd-ws-remote-project-channel/prd-ws-remote-project-channel.md`（R1–R14）
- 决策真源：`docs/decisions/adr-0005-ws-remote-project-channel.md`（ADR-005）
- 口径：本 spine 只固定「各自独立构建会不一致」的决策；采纳方式是 epic 文件把它记进 `sources:`

## 1. 上下文与约束

- 远程客户端只有 WS 一条通道（HTTP listener 没有对外模式），所以「选哪个项目提交 run」必须在帧面上表达，不能靠 URL。
- `network/` 是**哑传输**：不 import `heagent.config` / `pub.projects` / `engine` / `agent`，不认注册表、不认项目路径、不做 `is_dir`（R10）。
- 提交编排的唯一真源是入口层 `HttpProjectConsole.start_project_run()`（`cli/http_console.py:642`，实现 `ConsoleHandler` Protocol）；WS 不得有第二套编排（A2）。
- 名额、并发、隔离、会话归属全在运行栈侧，传输层只**转译**错误码，不新增调度（R9）。
- 本 spine 只固定「各自独立构建会不一致」的决策：帧面字段、Protocol 形状、错误码集合、注入点、不变量与判据。

## 2. 模块归属与依赖方向

### 2.1 谁定义 / 谁实现 / 谁装配

| 关切 | 定义（声明处） | 实现（行为处） | 装配（接线处） |
|---|---|---|---|
| 帧模型、命令枚举、字段白名单 | `network/ws_protocol.py` | — | — |
| 项目通道端口 `ProjectChannelService` | `network/ws_server.py`（与 `RunWebSocketService` 并列） | `cli/ws_project_adapter.py::ProjectChannelAdapter` | `cli/http.py` 两处 `build_ws_servers(...)` |
| 项目编排（六项落点、会话续接、配额） | `cli/http_console.py::HttpProjectConsole`（经 `ConsoleHandler`） | 同左 | 同一个实例既给 `HttpServer` 也给适配器 |
| 注册表真源 + 可判定健康信号 | `pub/projects.py::ProjectRegistry` | 同左 | 只被 `cli/` 消费 |
| 错误码字面值 | `network/http_protocol.py::HttpErrorCode` | — | — |

依赖方向：`cli/ws_project_adapter.py`（入口层）→ `network.ws_protocol`（帧模型）+ `cli.http_console`（编排）+ `pub.projects`（健康探针）；`network/*` 不反向导入任何一项。新增 cli 子模块要同步 `tests/test_architecture_contracts.py::test_cli_package_layout_is_pinned` 白名单与 `docs/frame.md` 的 cli 表/目录树。

### 2.2 哑传输的具体形态

- `network/ws_server.py` 只认识三个结构：帧模型、两个 Protocol、注入回调。它拿到的 `project_id` 是**不透明短 id**，拿到的 `prompt` 是纯文本，除此之外不传任何参数 —— 尤其不传路径、`workspace_root`、`session_id`。
- 「项目内 run 的六项落点」（R3）由 `HttpProjectConsole` 保证，网络层连表达它的字段都没有。这条是**结构保证**，不是纪律要求：`ProjectChannelService` 的方法签名里不存在路径类参数（判据 I5）。

### 2.3 实测发现与已定落点的偏差（显性记录，不静默绕过）

1. **engine 里没有并发名额。** 实测 `src/heagent/engine/` 只有 `checkpoint.py` 的 `tool_in_flight`（工具在飞闸门），没有任何信号量 / 名额计数。R9 的「名额」不在 engine：全局判定在 run 服务（`HttpRunService.start_run` 抛 `HttpRunConflictError`，`run_conflict` / `total_inflight_limit`，`ws_server.py::_submit_run` 已逐条映射），项目内判定在 `ConsoleHandler.start_project_run`（「已有在途 run 时抛 `ConsoleOperationError`，不排队」）＋现成的 `project_has_inflight_run(project_id)` 探针（`cli/http_console.py:544`）。⇒ 已定落点「engine 查并发名额」**不成立**，改判为「run 服务（全局）+ console（项目内）」，见 AD-6。
2. **`RunWebSocketService` 不扩展，改为并列新 Protocol。** 它现在声明 6 个成员（`run` / `needs_resync` / `start_run` / `cancel_run` / `register_ws` / `unregister_ws` + `_closing`），唯一实现方是 run 服务。往里加 `start_project_run` 等于让 run 服务认项目，与 A2 的单源精神相反。⇒ 新增 `ProjectChannelService`（AD-1）。这偏离 R10 的字面「同改 `RunWebSocketService` Protocol 与实现」，但满足其意图（声明与实现必须同批改，不许只改一边）；偏离理由与替选写在 AD-1。
3. **`HttpProjectConsole` 可被 WS 复用**（它是入口层的 `ConsoleHandler` 实现，全 async、无 FastAPI/Starlette 依赖），但**不能把它的返回模型直接当 WS 投影**：`ProjectListResponse` / `ProjectEntryResponse` 带 `path` / `last_opened_at` / `is_default`（`network/http_console_protocol.py:69` 起逐字有这三字段），直接下发就是 R1 明令排除的泄漏面。⇒ 必须经适配器投影到 3 字段（AD-3）。
4. **`build_ws_servers` 有两个调用点**（`cli/http.py:449` 与 `:789`）。只改一处会让另一条装配分支静默缺项目通道 —— 这不是可选细节，写进 AD-1 的判据。
5. **`parse_command_frame` 的字段白名单是二元 if/else**（`ws_protocol.py:226` `allowed_keys = {"command","prompt"} if RUN else {"command"}`）。再加两条命令会变成四分支重复，且 `cancel_run` 需要 `run_id`、`run` 需要 `project_id`，现结构无法承载 ⇒ 升级为单一映射表（AD-4）。
6. **`start_project_run` 的返回带 `session_id`**（`cli/http_console.py:642` → `ProjectRunResponse(run_id, session_id, status)`）。WS 侧必须收窄，否则 R4「帧不回带 `session_id`」被实现层无意破坏。

## 3. 架构决策

### AD-1 项目能力经新的 `ProjectChannelService` Protocol 注入，`network/` 保持哑传输

- **决策**：在 `network/ws_server.py` 新增 `ProjectChannelService` Protocol（3 个 async 方法，见 §4.3），与 `RunWebSocketService` 并列；`build_runs_collection_endpoint` / `build_ws_endpoint` 各加**关键字参数** `project_service: ProjectChannelService | None = None`（默认 `None`），由 `cli/http_config.py::build_ws_servers` 透传，`cli/http.py` 的两处调用点注入同一个 `ProjectChannelAdapter` 实例。
- **理由**：R10 要求依赖边界可执行断言；Protocol 是唯一既能「声明在 network、实现却在 cli」又不让依赖边逆流的手段。默认 `None` 让测试装配与旧调用零改动。
- **被拒替代**：(a) 扩展 `RunWebSocketService`（见 §2.3-2，把项目编排塞进 run 服务腹地）；(b) `network/` 内直接 `from heagent.pub.projects import ProjectRegistry`（破 R10，契约测试当场红）；(c) 只用 HTTP 项目端点、WS 不开放项目（远程客户端根本到不了，R2 无从落地）。
- **落点**：`src/heagent/network/ws_server.py::ProjectChannelService`、`::build_runs_collection_endpoint`、`::build_ws_endpoint`；`src/heagent/cli/http_config.py::build_ws_servers`；`src/heagent/cli/http.py`（`:449` 与 `:789` 两处）；`src/heagent/cli/ws_project_adapter.py::ProjectChannelAdapter`（新文件，职责边界 = 只做「console 模型 ↔ WS 帧模型」翻译，不含任何判据与编排，目标 ≤150 行）。
- **不变量**：
  - I1 `grep -rn "heagent\.config\|heagent\.pub\.projects\|heagent\.engine\|heagent\.agent\|heagent\.cli" src/heagent/network/` 恒 0 命中。
  - I2 `grep -rn "is_dir" src/heagent/network/` 恒 0 命中（可用性判定只发生在入口层 / 注册表）。
  - I5 `ProjectChannelService` 的方法参数名集合恰为 `{project_id}` / `{project_id, prompt}`（反射断言，无 path / workspace / session）。
- **验证判据**：`pytest tests/test_architecture_contracts.py -q`；新增 wiring 断言「两处 `build_ws_servers` 调用都传了 `project_service`（生产装配）」，落 `tests/test_cli_http_lifecycle.py` 同族用例。

### AD-2 帧转译单源：适配器包同一个 `HttpProjectConsole`，WS 与 HTTP 共用同一次调用

- **决策**：`ProjectChannelAdapter.__init__(console: ConsoleHandler, registry_health: Callable[[], str])`；`start_project_run(project_id, prompt)` 的唯一动作是 `await console.start_project_run(project_id, ProjectRunRequest(prompt=prompt))` 并把 `ProjectRunResponse` 收窄为 `SubmittedRun(run_id, status)`（**丢掉 `session_id`**，R4）。缺省 `project_id` 的提交**完全不走适配器**，逐字沿用今天的 `await service.start_run(prompt)`（R2「行为逐字不变」）。
- **理由**：A2 已冻结。缺省路径绕开适配器是为了让「不传 `project_id`」的语义等于「与既有 WS 提交完全同一条代码路径」，而不是「等效但经过新分支」。
- **被拒替代**：(a) 适配器内自己调 run 服务并拼 workspace（第二套编排，直接违反 A2）；(b) 缺省 `project_id` 也走 console 的 default 项目（形状上更统一，但把一条稳定路径换成新分支，违背「逐字不变」）。
- **落点**：`cli/ws_project_adapter.py::ProjectChannelAdapter.start_project_run`；`network/ws_server.py::_submit_run`（新增 `project_id` 分支，旧分支不动）。
- **不变量**：
  - I6 无 `project_id` 的 `run` 帧：`HttpProjectConsole.start_project_run` 调用次数 == 0 且 `HttpRunService.start_run` == 1（spy 断言）。
  - I9 带 `project_id` 的 `run` 帧：`HttpProjectConsole.start_project_run` 调用次数 == 1，且传入的 `ProjectRunRequest` 只有 `prompt`（`session_id is None`）。
  - 适配器内不出现 `Path` / `os` / `is_dir` / 任何注册表方法调用（grep 断言）。
- **验证判据**：`tests/network/test_ws_project_submit.py`（spy 注入 fake console）+ 既有 `run` 帧用例全绿。

### AD-3 帧面扩张的最小集：只加「远程客户端必须有、且不能从既有字段推出」的东西

- **决策**：
  - `WsCommand` 增加 `PROJECTS = "projects"`、`CANCEL_RUN = "cancel_run"`（+2，封闭集合逐字固定为 5 值）。
  - `WsCommandFrame` 增加两个可选字段 `project_id`（仅 `run`）、`run_id`（仅 `cancel_run`）。
  - `WsFrameType` 增加 `PROJECTS = "projects"`；新增 `WsProjectsFrame` + `ProjectChannelEntry`（**恰 3 字段** `id` / `name` / `available`，不复用 `ProjectEntryResponse`）。
  - `WsAckFrame` / `WsEventFrame` **零改动**（R6 的 `extra="forbid"` 仍拒 `project_id`）。
- **理由**：R11 要求远程白名单不扩张，所以项目清单只能作为 WS 帧；而「列出 id 才能提交」是硬前提。收窄到 3 字段是因为 `path` / `last_opened_at` / `is_default` 对远程客户端无决策价值，却把服务端目录结构暴露给网段内任何持 token 的客户端。
- **被拒替代**：(a) 复用 `ProjectEntryResponse`（泄漏 `path`，R1 明令排除）；(b) 把 `available` 做成提交时才回的错误（客户端无法预先置灰，R1 要的正是「先看得见可用性」）；(c) 新开 HTTP 项目端点（远程不可达 + 破 R11）。
- **落点**：`network/ws_protocol.py::WsCommand`、`::WsCommandFrame`、`::WsFrameType`、`::ProjectChannelEntry`、`::WsProjectsFrame`。
- **不变量**：
  - I3 `WsCommand` 成员集合 == `{"cancel","cancel_run","ping","projects","run"}`（集合相等断言，非 ⊆）。
  - I4 `WsAckFrame.model_fields` == `{type, command, run_id, status}`、`WsEventFrame.model_fields` == `{type, event}`（R4/R6 的契约钉子）。
  - I10 `WsProjectsFrame` 的每个 entry 序列化后键集 == `{"id","name","available"}`（`extra="forbid"` + 键集断言双重钉）。
  - I7 所有 server 帧仍是单行 JSON，`type` ∈ `WsFrameType` 值集。
- **验证判据**：`pytest tests/network -q -k "ws_protocol or ws_server"`；`python scripts/contract_snapshot.py --write` 后 review 四份基线的 diff。

### AD-4 `parse_command_frame` 的字段白名单升级为「命令 → 允许键集合」单一映射表

- **决策**：把 `parse_command_frame` 里的 `allowed_keys = {...} if command == RUN else {...}`（`ws_protocol.py:226`）与 `WsCommandFrame` 的 prompt 必带校验合并为模块级 `_FRAME_FIELDS: dict[WsCommand, frozenset[str]]` 单一事实源；模型校验器按同一张表判「必带 / 禁带」。
- **理由**：`cancel_run` 要 `run_id`、`run` 要 `project_id`，二元 if/else 会膨胀成四个几乎相同分支（本仓明确反对这类对称破缺的手抄重复）。一张表能被测试直接读出来断言，重复不会再回来。
- **被拒替代**：每命令一个 `WsXxxCommandFrame` 联合体（`parse_command_frame` 返回类型变成 Union，`_next_command` 与四个调用点全要改，破坏面远大于收益）。
- **落点**：`network/ws_protocol.py::_FRAME_FIELDS`、`::parse_command_frame`、`::WsCommandFrame` 的校验器（原 prompt 专用校验改名）。
- **不变量**：`_FRAME_FIELDS` 覆盖 `WsCommand` 的全部成员（`set(_FRAME_FIELDS) == set(WsCommand)`，新增命令不登记即红）；`WS_MAX_COMMAND_CHARS` 仍作用于所有非 `run` 命令（含 `cancel_run` / `projects`）。
- **验证判据**：`tests/network/` 里「未知字段 ⇒ `malformed`」「`run` 缺 prompt ⇒ `malformed`」「`cancel_run` 缺 `run_id` ⇒ `malformed`」「`cancel_run` 带 `project_id` ⇒ `malformed`」四例。

### AD-5 R7 的可判定形态 = at-least-once + 客户端按事件 id 去重 + `resync_required` 兜底

- **决策**：不引入应用层 AC / 服务端重传；把「不丢事件」表述为三条可断言事实：(a) 每个 `event` 帧携带单调递增的整型事件 id（`replay_then_follow` 的游标语义）；(b) 重连带 `?last_event_id=<最后收到>` ⇒ 首帧 id ≤ `last_event_id + 1`，其后连续无空洞；(c) 游标落后于 ring buffer 窗口 ⇒ `needs_resync` 判真、回 `resync_required` 错误帧并关闭，**绝不静默从最旧一条开始**（客户端须按会话快照重建）。
- **理由**：客户端断线时服务端无法知道它处理到哪一条，只有客户端自己知道 ⇒ 唯一诚实形态是「可能重复、绝不缺失、超出窗口必须显式失败」。这套语义在 `http_protocol.replay_then_follow` + `RunWebSocketService.needs_resync` 里已经存在，本项是**验收**而非新建。
- **被拒替代**：(a) 加 AC 帧（协议面扩张、需要服务端保留未确认队列，与 `_closing` / 关停语义纠缠）；(b) 服务端推定「发出去就算送到」（丢事件无声）。
- **落点**：`network/http_protocol.py::replay_then_follow`（既有，不改）、`network/ws_server.py::_parse_cursor` / `::_prepare_subscription` / `::_send_event_stream`（既有，不改）；本 spine 只新增判据。
- **不变量**：重放与实时队列的接缝不重复也不跳号；`resync_required` 与「订阅成功但窗口不足」互斥（不得先订阅再报 resync）。
- **验证判据**：`tests/network/test_ws_resume.py` 三例（见 §6.2）。

### AD-6 名额分层：全局沿用 run 服务、项目内沿用 console，不新增信号量、不动任何参数

- **决策**：带 `project_id` 的提交把它收到的 `HttpRunConflictError.code` **逐字透传**给错误帧（`project_busy` / `run_conflict` / `total_inflight_limit` / `unknown_project` / …）；`network/` 不做任何计数，不新增配置键，不改既有并发参数。
- **理由**：实测名额判定已有两处且语义互补（全局在 run 服务、项目内在 console），在传输层再放一个计数就是第三份真相。R9 因此是**验收项**：只要 WS 与 HTTP 走同一次 `start_project_run`，双重约束自动成立。
- **被拒替代**：(a) WS 侧自建 per-project 信号量（与 console 的 `project_has_inflight_run` 双计数，必然漂移）；(b) 新增 `WS_PROJECT_MAX_INFLIGHT` 配置（R9 明令参数不动）。
- **落点**：`network/ws_server.py::_submit_run`（`except HttpRunConflictError` 分支已存在，扩到 `project_id` 分支复用）；`cli/ws_project_adapter.py`（把 `ConsoleOperationError.code` 与 `ProjectRegistryError.code` **原样**包成 `HttpRunConflictError`，不改写 code）。
- **不变量**：适配器可能抛出的每个 code 字面值都 ∈ `HttpErrorCode` 值集（反射断言）；`network/ws_server.py` 不出现任何新增 `int` 计数状态（除既有的 `_SubmissionSlots`，`:263`）。
- **验证判据**：`tests/network/test_ws_project_admission.py` 四例（见 §6.3）。

### AD-7 错误码三分 + 注册表可判定信号：读径保持 fail-soft，写径与提交径 fail-loud

- **决策**：
  - `HttpErrorCode` 增加 `PROJECT_UNAVAILABLE = "project_unavailable"`、`PROJECT_REGISTRY_UNREADABLE = "project_registry_unreadable"`；`unknown_project` / `project_busy` / `run_conflict` / `total_inflight_limit` 若已存在则复用。
  - `ProjectRegistry` 新增只读探针 `health() -> ProjectRegistryHealth`（`code: Literal["ok","unreadable"]` + 一句 `detail`），实现复用一次私有读径：`OSError` / `UnicodeError` / `_RegistryCorrupt` 一律映射 `unreadable` 并保持既有日志口径；`load()` / `find()` / `list()` 语义**不动**（仍 fail-soft）。
  - `projects` 帧用 `registry_state ∈ {"ok","unreadable"}` 承载该信号（R13 的「可判定信号」）；提交径遇 `unreadable` 回 `project_registry_unreadable`（区别于「id 打错」的 `unknown_project`）。
- **理由**：R13 要求「列表 fail-soft + 可判定信号」，而今天注册表不可读与「注册表为空」在响应里完全同形（`_decode` 打 WARNING 后返回 `[]`），客户端只能靠读日志猜。区分「你 id 打错了」（4xx）与「服务端注册表坏了」（5xx）也决定客户端该重试还是该改输入。
- **被拒替代**：(a) 让 `list()` 抛异常（破既有 fail-soft 口径，网页控制台会 500）；(b) 在 `network/` 里读 JSON 判健康（破 R10）；(c) 不区分 `unknown_project` 与 `project_registry_unreadable`（重试语义错）。
- **落点**：`pub/projects.py::ProjectRegistry.health`；`network/http_protocol.py::HttpErrorCode`；`cli/ws_project_adapter.py`（把 `registry_health()` 结果填进帧、把注册表异常译成 `project_registry_unreadable`）。
- **不变量**：`health()` 是**纯读**（不写盘、不改 `_RegistryCorrupt` 的 fail-closed 写径语义）；`_decode_or_raise` 路径逐字不变；每次判定不可读只打 1 条 WARNING（不随请求数刷屏）。
- **验证判据**：`tests/test_project_registry_health.py`（坏 JSON / BOM / 超 32 条 / 目录不可读四例：`health().code == "unreadable"`、`list()` 仍回 default 一条、`caplog` 恰 1 条 WARNING）。

### AD-8 远程暴露面不扩张 + 启动 WARNING + 契约与文档收口

- **决策**：
  - 只读 listener 上 `projects` 帧**允许**（纯读，与「通知流对所有 listener 注册」同档），`cancel_run` 与 `cancel` 同样回 `invalid_request` 且不断连；集合级端点仍不在只读 listener 注册（既有行为）。
  - `external` 档（非回环 + token）且沙箱后端非 docker 时，启动打**一条** WARNING，落 `cli/http_config.py` 的启动自检族（与 `_check_tls_identity` 同处），文案进入 `cli/http.py::_ws_access_note` 的访问说明。
  - `docs/frame.md`（cli 新模块 + WS 帧面）、`docs/framework.md` 的 WS 段、`tests/fixtures/contract_baselines/` 四份快照同批更新。
- **理由**：远程能提交带项目围栏的 run 之后，「宿主直连执行」的风险等级变了；但这是提示不是闸门（三层非边界立场不因本 epic 改变）。
- **被拒替代**：(a) 把 `projects` 也拒给只读 listener（客户端失去可用项目清单）；(b) 非 docker 时拒绝启动（超出 R12 的「一条 WARNING」）。
- **落点**：`cli/http_config.py::_warn_external_without_sandbox`（新增，紧跟 `_check_tls_identity`）；`cli/http.py::_ws_access_note`；`network/ws_server.py` 的 readonly 分支。
- **不变量**：WS 命令面不新增任何改配置 / 改注册表 / 删文件的命令（R11）；`_ws_access_note` 的既有三段文案逐字不变，只在尾部追加一行。
- **验证判据**：`pytest tests/test_cli_http_lifecycle.py -q`（WARNING 计数 == 1 / 启动一次）；`python scripts/contract_snapshot.py --write` + 基线 diff review；`mkdocs build --strict`（动过 `docs/` 时）。

## 4. 接口契约

### 4.1 客户端 → 服务端（`network/ws_protocol.py`）

```python
class WsCommand(StrEnum):
    CANCEL = "cancel"
    CANCEL_RUN = "cancel_run"   # 新增
    PING = "ping"
    PROJECTS = "projects"       # 新增
    RUN = "run"

class WsCommandFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: WsCommand
    prompt: str | None = None                                                  # 仅 run，必带
    project_id: str | None = Field(default=None, min_length=1, max_length=16)  # 仅 run，可选
    run_id: str | None = Field(default=None, min_length=1, max_length=64)      # 仅 cancel_run，必带

_FRAME_FIELDS: dict[WsCommand, frozenset[str]] = {
    WsCommand.RUN:        frozenset({"command", "prompt", "project_id"}),
    WsCommand.CANCEL:     frozenset({"command"}),
    WsCommand.CANCEL_RUN: frozenset({"command", "run_id"}),
    WsCommand.PING:       frozenset({"command"}),
    WsCommand.PROJECTS:   frozenset({"command"}),
}
```

- `project_id` / `run_id` **不做 strip**：id 由 `project_id_for()` 产出（`"p" + sha256[:8]`）或字面量 `"default"`，客户端必须原样回传；strip 会造出第二个合法拼写。
- `project_id` 缺省（键不出现或 `null`）= 启动工作区、走旧路径；`project_id: ""` ⇒ `malformed`（`min_length=1`）。
- 接收端点：`projects` 与 `cancel_run` 只在**集合级**端点 `WS /api/runs/ws` 接受；`cancel_run` 在单 run 端点上也接受，但 `run_id` 必须等于该连接绑定的 run（否则 `invalid_request` 不断连），且受 `readonly` 闸门约束（R8）。`projects` 在单 run / CLI 旁路 / 通知流上一律 `invalid_request` 不断连。

### 4.2 服务端 → 客户端（新增帧，既有四类零改动）

```python
class WsFrameType(StrEnum):
    HELLO = "hello"; EVENT = "event"; ACK = "ack"; ERROR = "error"
    NOTIFICATION = "notification"; PROJECTS = "projects"   # 新增一项

class ProjectChannelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=16)
    name: str = Field(min_length=1, max_length=64)   # 镜像 pub.projects.MAX_PROJECT_NAME_CHARS
    available: bool

class WsProjectsFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: WsFrameType = WsFrameType.PROJECTS
    registry_state: Literal["ok", "unreadable"] = "ok"
    projects: tuple[ProjectChannelEntry, ...] = Field(default=(), max_length=32)  # 镜像 MAX_PROJECTS
```

- 条目顺序 = 注册表 `list()` 的顺序（已登记项按 `last_opened_at` 倒序、`default` 固定末尾），客户端**不得重排**。
- `registry_state == "unreadable"` 时 `projects` 仍可含 `default`（`list()` fail-soft 的既有结果），客户端据此把列表标为「可能不完整」。

### 4.3 注入端口（`network/ws_server.py`）

```python
class SubmittedRun(BaseModel):
    """提交成功的收窄结果：刻意不含 session_id（R4：帧不回带会话）。"""
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1)
    status: RunStatus

class ProjectChannelService(Protocol):
    async def list_projects(self) -> WsProjectsFrame: ...
    async def start_project_run(self, project_id: str, prompt: str) -> SubmittedRun: ...
    async def ensure_available(self, project_id: str) -> str: ...
        # 成功返回 project_id 原样；失败抛 HttpRunConflictError
```

- **异常契约**：三个方法失败一律抛 `HttpRunConflictError(code, message)`（`network/http_protocol.py` 已有，`ws_server` 已 import），code 取自 `HttpErrorCode`。适配器把 `ConsoleOperationError.code` / `ProjectRegistryError.code` **逐字**搬进 code，不改写。
- `ensure_available` 供提交前置校验复用；R5 的「不占名额」由「先 `ensure_available` 后 `start_project_run`」的次序保证。
- 端点构造器签名（**新增参数一律关键字、默认 `None`**）：

```python
def build_runs_collection_endpoint(
    service: RunWebSocketService, *, origin_violation: OriginCheck, max_connections: int,
    authorize: AuthCheck | None = None, version: str = "",
    project_service: ProjectChannelService | None = None,
) -> Callable[[WebSocketLike], Awaitable[None]]: ...

def build_ws_endpoint(
    service: RunWebSocketService, *, origin_violation: OriginCheck, max_connections: int,
    authorize: AuthCheck | None = None, readonly: bool = False, version: str = "",
    project_service: ProjectChannelService | None = None,
) -> Callable[[WebSocketLike], Awaitable[None]]: ...
```

- `project_service is None` 时：`run` 帧带 `project_id` ⇒ `invalid_request`（"project addressing is not available on this listener"）；`projects` / `cancel_run` 同码。生产装配恒注入（wiring 断言），`None` 只出现在测试装配。

### 4.4 错误码集合（进 `HttpErrorCode` 与 `transport_errors.json`）

| 场景 | code | 是否不断连 | 名额 |
|---|---|---|---|
| `project_id` 不在注册表 | `unknown_project` | 不断连 | 不占 |
| 项目目录已消失（`available=False`） | `project_unavailable` | 不断连 | 不占 |
| 注册表文件不可解析 | `project_registry_unreadable` | 不断连 | 不占 |
| 项目已有在途 run | `project_busy` | 不断连 | 不占 |
| 全局名额耗尽 | `total_inflight_limit` | 不断连 | 不占 |
| 同工作区 / 同名在途冲突 | `run_conflict` | 不断连 | 不占 |
| prompt 全空白 | `empty_prompt` | 不断连 | 不占 |
| 只读 listener 收到 `cancel` / `cancel_run` | `invalid_request` | 不断连 | — |
| `cancel_run` 目标不存在 | `unknown_run` | 不断连 | — |
| 单 run 端点上 `cancel_run` 的 `run_id` ≠ 绑定 run | `invalid_request` | 不断连 | — |
| 帧非法 / 未知命令 / 超长 | `invalid_request`（超长走 close 1009） | 关闭 | — |

状态码语义沿用 HTTP 项目端点既有映射（`unknown_project` 4xx、`project_busy` 409、`project_registry_unreadable` 5xx），WS 只复用 code。

## 5. 失败处理

- **未知 `project_id`**：`ensure_available` 抛 `unknown_project` ⇒ 错误帧，连接保留，客户端可改 id 重试；不建 run、不占名额、不 touch 注册表。
- **目录消失**：`ProjectEntry.available=False`（`list()` / `find()` 现场 `is_dir`）⇒ `project_unavailable`。`projects` 帧里该条同时置 `available=False`，客户端可先置灰 —— 两条通道给同一事实。
- **注册表不可读**：列表径 fail-soft（`registry_state="unreadable"` + WARNING 一条）；提交径 fail-loud（`project_registry_unreadable`），**绝不**退化成「当成 default 项目」。
- **`cancel_run` 目标已终止**：`service.run(run_id)` 非空但 `service.cancel_run(run_id)` 回 `None` ⇒ 重新读一次 `service.run(run_id)` 并回 `WsAckFrame(command=CANCEL_RUN, run_id=…, status=<终态>)`（幂等、不误报错误、不断连）。目标完全不存在 ⇒ `unknown_run` 错误帧且**不断连**（区别于单 run 端点上 `cancel` 的「不存在即关连接」—— 那里的连接本身就是那个 run 的订阅）。
- **并发冲突**：`project_busy` / `run_conflict` / `total_inflight_limit` 逐字透传，客户端能分辨「这个项目在跑」与「整机满了」；不排队、不占名额。
- **超长帧**：`cancel_run` / `projects` 受 `WS_MAX_COMMAND_CHARS`（4096）约束，超限走 `too_large` ⇒ close 1009（既有口径不改）。
- **`project_service is None`**：见 §4.3，回 `invalid_request` 而不是静默按 default 处理（静默降级会把「装配漏了」变成「跑错项目」）。

## 6. 验证路径

### 6.1 命令面

```bash
pytest tests/network -q                          # 帧解析 / 端点 / 续流
pytest tests/test_architecture_contracts.py -q   # I1/I2 + cli 布局白名单
pytest tests/test_cli_http_lifecycle.py -q       # 装配与启动 WARNING
pytest tests/test_project_registry_health.py -q  # AD-7
python scripts/contract_snapshot.py --write      # 重生成 4 份基线，人工 review diff
ruff check src tests && mypy src && bandit -r src/ -ll
```

### 6.2 R7 断连续流 → 可跑断言

`tests/network/test_ws_resume.py`（fake `RunWebSocketService`，不跑真 run）：

1. **无空洞**：连收 N 帧后断开 → 用第 N 帧的事件 id 作 `?last_event_id=` 重连 → 断言续到的首帧 id ≤ N+1 且后续 id 连续递增至终态。
2. **窗口不足必须响**：把 record 的 ring buffer 置 1、cursor 落后 ≥2 ⇒ 断言收到 `resync_required` 错误帧且**没有**任何 event 帧先于它发出。
3. **重复可见、可去重**：服务端重放窗口重叠 ⇒ 断言客户端按 id 去重后条数 == 服务端事件总数（说明「至少一次」成立、无静默丢失）。

### 6.3 R9 两项目并发不串味 → 可跑断言

`tests/network/test_ws_project_admission.py`（注入 fake console，两个项目 A/B）：

1. **并发不串味**：两条集合级连接各提交 A、B ⇒ 断言 console 收到 `(A, prompt_a)` 与 `(B, prompt_b)`，两个 ack 的 `run_id` 不同，且**没有**任何一次调用的 `project_id` 与 prompt 交叉。
2. **项目内上限**：A 已有在途时再提交 A ⇒ 错误帧 code == `project_busy`，且第二次调用未触达 `start_project_run`。
3. **全局上限**：A、B 都在跑、全局名额耗尽 ⇒ 第三次提交回 `total_inflight_limit`（与 `run_conflict` 可分辨）。
4. **不占名额**：`unknown_project` / `project_unavailable` / `project_registry_unreadable` 三条路径下断言 console 的 `start_project_run` 调用次数 == 0。

### 6.4 R3 六项落点 → 判据分工（不重复测）

- **传输层**只断言「只传 `project_id`」：`ProjectChannelService.start_project_run` 实参集合 == `{project_id, prompt}`（I5 + I9）。
- **编排层**断言六项落点全在项目根：`HttpProjectConsole.start_project_run` 的既有 / 新增用例断言 `context.workspace_root`、会话文件、产物目录、`ExecutionLedger` 行、`RunContext.state_root`、memory 根都落在该项目路径下（不落在启动工作区）。
- 两条合起来即 R3 的端到端保证，且 WS 侧不会随编排演进反复改测试。

### 6.5 不变量判据速查

| id | 判据形态 |
|---|---|
| I1 / I2 | `content_search` 断言 0 命中（`network/` 内 `heagent.cli` / `pub.projects` / `is_dir`） |
| I3 / I4 / I10 | 集合相等 / `model_fields` 键集 / 序列化键集断言 |
| I5 / I9 | `inspect.signature` 参数名集合断言 |
| I6 | spy 计数断言（缺省路径零触达 console） |
| I7 | 帧 `model_dump_json()` 单行 + `type` ∈ `WsFrameType` |

## 7. 刻意留开的项

1. **提交命令无幂等键 ⇒ ack 丢失会重复提交。** 触发条件：客户端自动重试提交帧。默认处置：客户端**只重试订阅**（带 cursor），提交失败交用户重试；要闭合需在帧上加 `request_id` 并在 console 侧去重（不在本 epic 范围）。
2. **项目内并发上限固定为 1（沿用 console 现状），不参数化。** 触发条件：需要同项目并行 N 条 run（R9「参数不动」）。默认处置：先只做全局名额，项目内 1 条；将来放开时改 console 判据，不改帧面。
3. **WS 提交不 `touch()` 项目、不刷新 `last_opened_at`。** 触发条件：产品要求「远程提交后项目跃到列表前面」。默认处置：不动（传输层不写盘）；要改就改在 `HttpProjectConsole.start_project_run` 内部一次调用。
4. **`registry_state` 只区分 `ok` / `unreadable`，不带具体原因。** 触发条件：客户端要提示「BOM / 超 32 条 / 重复 id」。默认处置：原因留在服务端 WARNING 日志；要外露则给帧加 `notes: tuple[str, ...]`（稳定码）。
5. **事件帧不含 `project_id`（R6 冻结）。** 订阅者只拿得到 `run_id`。触发条件：客户端只握 WS、需要按项目聚合。默认处置：客户端在提交时自存 `run_id → project_id` 映射。
6. **ack 不回 `session_id`（R4 冻结）。** 触发条件：纯 WS 客户端要「续该项目的同一会话」而不是默认最近会话。默认处置：走 HTTP 会话端点（本机）或后续新增 WS `sessions` 命令。
7. **`projects` 帧在只读 listener 上开放（含项目名）。** 触发条件：安全评审认为项目名本身构成信息泄漏。默认处置：允许（与通知流同档，均在 token 之后 / `lan` 无认证面）；若收紧则退化为只回 `id` + `available`。
8. **`HttpProjectConsole` 的并发写安全未在本 spine 复核。** 触发条件：WS 提交与 HTTP 控制台同时 `start_project_run` 同一项目。默认处置：依赖 console 既有的 `project_has_inflight_run` 判据；若实测存在 check-then-act 竞态，在 console 内加项目级锁（不改传输层）。

## 8. 给实现期的三条硬提醒（实测得出，最容易踩）

- `network/` 里连 `is_dir` 都不能出现；`available` 只能由入口层算好塞进帧。
- `build_ws_servers` 有 `cli/http.py:449` 与 `:789` 两个调用点，漏一处就是「一条装配分支静默没有项目通道」。
- 新增 `cli/ws_project_adapter.py` 必须同批改 `tests/test_architecture_contracts.py` 的 cli 布局白名单与 `docs/frame.md`，否则契约测试当场红。
