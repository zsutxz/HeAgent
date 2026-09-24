---
id: 50-3
title: 会话持久化、会话 API 与运行绑定
status: ready-for-dev
parent_epic: E50
priority: P0
phase: B（项目与会话闭环）
depends_on: [50-1, 50-2]
blocks: [50-4, 50-5, 50-6, 50-7]
created: '2026-09-23'
---

# Story 50-3：会话持久化、会话 API 与运行绑定

## 用户故事

作为控制台用户，我希望刷新浏览器或重启服务后仍能列出、打开并继续我已保存的对话，
并且网页与 CLI 看到的是**同一批**会话文件。

## 侦察实证（2026-09-23）

| 事实 | 证据 | 含义 |
|---|---|---|
| 会话持久化原语齐备，且**配对已处理** | `SessionStore.save()`（`context/session.py:99`）经 `atomic_update_text` 原子写 + 从磁盘读旧 `version` 递增；消息先过 `_complete_tool_transactions`（工具调用/结果配对） | 「消息顺序与配对完整」这条 AC 由既有实现保证，本 story 不必重写 |
| session_id 是**每调用参数**，不是 loop 属性 | `AgentLoop.run(prompt, *, session_id=...)`（`agent/loop.py:257`）、`run_stream`（`:277`）→ `_ensure_run_context(session_id=...)`（`:639-651`）→ `persist_and_cache(...)`（`:421`） | 网页侧只需①把 `SessionStore` 传进 loop 构造、②每次运行传 `session_id` |
| 网页运行的**根因**精确定位 | `HttpAgentHandler.new_loop()` 走 `cli._build_loop(..., None, ...)`（`cli_http.py:207-214`）⇒ `session=None`；`__call__` 调 `loop.run_stream(prompt, system=self.system)` **不带 session_id** | 这是「网页运行不写会话文件」的完整原因（不是漏了某个开关） |
| `SessionStore` 已有 id 校验 | `_validate_session_id()` + `_SESSION_ID_RE` + `_MAX_SESSION_ID_LEN`（`context/session.py`，见 `:70-72` 与 `save` 首行调用） | 「非法 id 被拒且不触碰文件系统」可直接复用既有守卫 |
| 列表所需元数据**当前取不到** | `load()`（`:126`）只返回 `list[Message]`；`list_sessions()`（`:143`）只返回 id；`recent_session_ids()`（`:149`）只读 `timestamp` | 会话列表的 `title`/`message_count`/`updated_at` 需要**新增元数据读 API**（不允许网络层自己解析 JSON） |
| `load()` 会**静默吞掉**损坏文件 | `except (json.JSONDecodeError, OSError): return []`（`:131-133`） | 陷阱：损坏的会话文件看起来像「空会话」，网页若据此继续对话会把损坏内容覆盖掉。见 **D1** |
| **`save()` 会丢弃未知字段** | `save()` 的 `data` 字典**每次新建**（`:106-111`），`update(raw)` 闭包虽能读到 `raw`（`:115-121`）但只取 `version` | 陷阱：若用「写入会话文件的可选 `title` 字段」表达重命名，下一次 `save()` 会把 `title` 抹掉。见 T4 与 AC8 |
| CLI 的会话选择语义可复用 | `cli._resolve_session_id()`（`cli.py:511-527`，`continue`/`resume` + `recent_session_ids(1)`） | 「缺省 = 该项目当前会话，无则新建」按同一口径实现 |
| 会话回收已存在 | `SessionStore.prune()`（`session.py:86`）走 `prune_entries_by_mtime`（与 logs / edit-snapshots 共用） | 多项目下每项目各自 prune，**不要**新增全局扫描 |

## 范围

- `SessionStore` 增加：可选「期望版本」冲突检测、会话元数据读 API、可选标题的**保真**读写。
- `HttpAgentHandler` 演进为「单项目运行时」：持有该项目的 `SessionStore`，运行绑定 `session_id`。
- 会话 API：列表 / 新建 / 读取消息 / 重命名 / 删除（需确认），并落 `P` 的 `.heagent/sessions/`。
- 项目内运行入口 `POST /api/projects/{id}/runs {prompt, session_id?}`。
- 在途运行保护：会话被在途 run 占用时拒绝删除。

## 边界与约束

**Always**

- 会话文件格式与 CLI **完全一致**（`session_id`/`version`/`timestamp`/`messages`），网页与 CLI 同库共用。
- 冲突检测是**增量**的：`save(..., expected_version=None)` 保持现有 last-write-wins 行为（CLI 不传 ⇒ 行为不变，I13）。
- 危险操作（删除会话 / 重命名覆盖）必须先确认；错误文案稳定且有界。
- 会话 id 必须过既有 id 校验（`../`、绝对路径、超长一律拒，不触碰文件系统）。
- 每个项目的 `prune` 只用该项目的 `WorkspacePaths`，不跨项目扫描。

**Never**

- 不在网络层解析会话 JSON（元数据解析留在 `SessionStore`）。
- 不在 HTTP 进程内构造/启动任何**后台执行**（`CronScheduler` / dreaming）——与 49-5「不装 stdin 审批、不连 MCP」同立场。
- 不把 `title` 写进 `messages`（会污染 CLI 读取路径）。
- 不静默覆盖被外部（CLI / 另一进程）修改过的会话文件。
- 不在运行中删除会话、不在会话写入在途时删除其所属项目。
- 不为「网页」引入第二套会话文件格式或第二个 sessions 目录。

## 任务（细分）

- [ ] **T1** `SessionStore.save(..., expected_version: int | None = None)`：在 `update(raw)` 闭包内比对磁盘
      `version`，不匹配则抛新异常 `SessionConflictError`（放在 `exceptions.py`，保持异常单点）；
      `None` = 现状。**注意**：异常必须在 `atomic_update_text` 之外可见（不要在闭包里吞掉）。
- [ ] **T2** 新增元数据读 API（建议 `load_metadata(session_id) -> SessionMetadata | None`，Pydantic），
      返回 `session_id` / `title`（可选字段，缺省回退派生值）/ `message_count` / `version` / `timestamp` / `updated_at`。
      `list()` 用一次目录遍历 + 逐文件元数据读实现，**列表上限**由常量约束。
- [ ] **T3** 标题派生：`derive_title(messages)`（首条 user 消息，截断 + 折叠空白；空则 `未命名会话`），纯函数、可单测。
- [ ] **T4** 重命名：新增 `SessionStore.rename(session_id, title, *, expected_version=None)`，**就地**改 `title` 字段、
      不动 `messages`；同时确保 `save()` 在重写时**保留**磁盘上已有的 `title`（T4 的两个方向都要测，
      见 AC8 与「侦察实证」第 6 行）。
- [ ] **T5** 损坏文件处置（**D1 已裁定**：新增 `session_unreadable`）：元数据读遇到不可解析 JSON 时**不得**静默当作空会话；
      返回显式状态并在 API 层映射为稳定错误码。
- [ ] **T6** `cli_http.HttpAgentHandler`：新增 `workspace_paths` / `session_store` 形参；`new_loop()` 传
      `session=self.session_store`；`__call__` 传入 `session_id`（新增形参，缺省 `None` 时行为同今日，保证 49 回归）。
      ⚠️ **评审 F2（必做）**：`cli._build_loop` 的 `session is not None and config.cron_enabled and cron_store`
      分支会在**传入 session 时顺带构造 `CronScheduler`**（实测 `cli.py:229` 条件 → `cli.py:246` 构造）⇒ 今日 HTTP 侧「无后台调度」
      是**因为 `session=None` 才偶然成立**的。传 session 后必须**显式**禁止 HTTP 侧构造/启动
      `CronScheduler`（与 49-5 的「不装 stdin 审批、不连 MCP」同一立场），并加一条测试断言
      `new_loop()` 不产生 scheduler / HTTP 进程内无 cron 任务。
- [ ] **T7** `POST /api/projects/{id}/runs`：`{prompt, session_id?}` → 缺省取该项目「当前会话」（无则新建），
      校验会话存在性（`unknown_session`）与项目可用性（`project_unavailable`），返回 `run_id` 复用既有 SSE 端点。
- [ ] **T8** 会话 API：`GET/POST /api/projects/{id}/sessions`、`GET/PATCH/DELETE /api/projects/{id}/sessions/{sid}`；
      `DELETE` 需 `?confirm=true`（缺则 `confirm_required`）+ 在途检查（`session_busy`）；
      `PATCH` 支持可选 `fingerprint`（不匹配 → `session_conflict`）。
- [ ] **T9** 在途保护：维护「会话 → 在途 run」映射（供 `session_busy`）与「项目 → 在途 run」计数（供 50-2 的 `project_busy`）。
      **并发口径（D9）**：名额**按项目各自生效**，跨项目不共享 ⇒ 全局在途上限 = 项目数 ×
      `HTTP_MAX_INFLIGHT_RUNS`（默认最多 32）。这是**有意语义**，测试须正面断言「A 项目在跑时 B 项目可起跑」，
      以及「同一项目内的第二个 run 仍被拒」（`run_conflict`）——两条一起才算钉住 D9。
- [ ] **T9b** **失败 / 取消运行的落盘口径（评审 F5，必做）**：`persist_and_cache` 在 **finally** 块里
      `if loop.session and session_id: save(...)`（实测 `agent/run_lifecycle.py:324-350`）⇒ 失败与取消的 run
      **也会写入会话文件**；而 Epic 49 的进程内投影只在 `COMPLETED` 时写历史（AD-3「失败不投影」）。
      两者并存会让「同一段对话」在 `/api/session` 与会话文件里给出**两个答案**。
      必须显式定义并实现：①失败/取消的 run 是否算「对话的一部分」（建议算——用户看到过这些消息）；
      ②UI 不得因读取来源不同而显示矛盾历史（同一页面只用一种口径，并在文案上区分「已完成 / 失败」）。
      配测试：失败 run 后 `GET .../sessions/{sid}` 与服务端投影的口径一致且可解释。
- [ ] **T10** 测试：列表 / 新建 / 继续 / 恢复（刷新与重启语义）/ 冲突 / 在途删除拒绝 / 确认缺失 / 非法 id /
      损坏文件 / 标题派生与重命名保真 / CLI 不传 `expected_version` 行为不变。
- [ ] **T11** 负向验证：去掉 `expected_version` 比对、让 `save()` 丢弃 `title`、去掉在途检查、去掉 id 校验——
      对应测试逐条变红后复原。

## 验收标准

- **AC1** Given 项目 `P`，When 客户端 `GET /api/projects/{id}/sessions`，Then 返回 `P/.heagent/sessions/` 下的会话
  （`session_id`/`title`/`message_count`/`updated_at`），按时间降序，与 CLI 在该目录看到的是**同一批文件**。
- **AC2** Given 客户端新建会话并提交提示词，When 运行结束，Then 会话文件落在 `P/.heagent/sessions/{session_id}.json`，
  内容格式与 CLI 一致，工具调用与结果配对完整。
- **AC3** Given 浏览器刷新或服务重启，When 再次打开该会话，Then 消息按序完整恢复，且运行绑定该会话
  （后续提交继续写入同一文件）。
- **AC4** Given 同一会话文件已被 CLI 或另一进程写入（磁盘 `version` 与客户端持有的版本不一致），
  When 网页提交写入，Then 返回 `session_conflict`，**不覆盖**对方内容，并提示重新加载。
- **AC5** Given 一个会话正在被运行写入，When 客户端请求删除该会话，Then 返回 `session_busy` 且文件仍在。
- **AC6** Given 客户端删除会话，When 请求缺少 `?confirm=true`，Then 返回 `confirm_required` 且不删除。
- **AC7** Given 会话 id 含路径遍历字符（`../`、绝对路径、超长），When 客户端传入，Then 被拒绝（`invalid_session_id`）
  且不触碰文件系统。
- **AC8** Given 一个已被重命名（`title` 已写入磁盘）的会话，When 继续对话并保存，Then `title` **仍保留**
  （不被 `save()` 抹掉），且 `messages` 未被 `title` 污染（CLI 读取路径不受影响）。
- **AC9** Given 磁盘上的会话文件损坏（非法 JSON），When 客户端打开该会话，Then 得到显式稳定错误
  （不得表现为「空会话」），且不会据此覆盖该文件。

- **AC10** Given 一次**失败**或**取消**的运行绑定在某会话上，When 之后打开该会话，
  Then 服务端返回的历史在同一页面内**只有一个口径**（消息可见性与「已完成 / 失败」标注自洽），
  不会因读取 `/api/session` 与会话文件而得出一致性相反的两个答案（评审 F5）。

## Definition of Done

**交付物**：`src/heagent/context/session.py`、`src/heagent/exceptions.py`、`src/heagent/cli_http.py`、
`src/heagent/network/http_server.py`、`src/heagent/network/http_console_protocol.py`、
`tests/test_session.py`（扩充）、`tests/network/test_http_console_sessions.py`（新增）。

**验证命令**（实测存在性已核对）：

```bash
pytest tests/test_session.py tests/network tests/test_http_agent_api.py tests/test_cli_http.py -q
pytest -q
ruff check src tests && mypy src && mypy src --platform linux
```

**负向验证**：T11 的 4 项回退各自精确变红；**另需**验证「CLI 不传 `expected_version` 时行为逐字节不变」
（用同一份消息跑两次 `save`，断言 `version` 递增与文件内容与改造前一致）。

**质量门**：`pytest`、`ruff check`、`ruff format --check src tests`、`mypy src`、`mypy src --platform linux` 全绿。

## 代码地图

| 路径 | 角色 | 改动 |
|---|---|---|
| `src/heagent/context/session.py` | 会话存储（既有） | `expected_version` / `load_metadata` / `rename` / 保留 `title` |
| `src/heagent/exceptions.py` | 异常单点 | 新增 `SessionConflictError` |
| `src/heagent/cli_http.py` | 单项目运行时 | 持 `SessionStore`；运行绑定 `session_id` |
| `src/heagent/network/http_server.py` | 路由 | 6 条会话路由 + 项目内运行入口 |
| `src/heagent/network/http_console_protocol.py` | 协议模型 | 会话请求/响应 + `ConsoleHandler` 扩展 |
| `tests/test_session.py` | 存储测试 | 冲突 / 元数据 / 标题保真 / 损坏文件 |
| `tests/network/test_http_console_sessions.py` | **新增** | API 层 + 在途保护 |

## 风险与未决

- **D1（已裁定 2026-09-24，见脊柱 §15）**：损坏会话文件的错误码 = **新增 `session_unreadable`**。
  理由：脊柱 §5.3 的闭集里原本没有对应语义，而「闭集里新增语义要加成员」是其自身规矩；
  `session_conflict` 语义不同（冲突 = 版本不符；不可读 = 无法解析），复用会让 UI 文案误导。
  落地点：`HttpErrorCode` + `__all__` + 错误码表 + 50-7 的文档 + UI 文案。
- **R1**：`message_count` 的来源——读 `messages` 长度需解析全文；大会话（数 MB）在列表时逐文件解析会有成本。
  实现取「列表只读轻量元数据（含 `message_count` 缓存字段或只数 JSON 顶层元素）」并在响应上限内截断；
  若性能不达标，退化为「列表不返回 `message_count`，详情返回」，该取舍须在实现记录中写明。
- **R2**：`session_busy` 与 `project_busy` 依赖在途索引（T9），跨项目共用同一 console 实例 ⇒ 索引必须是
  console 级单点（不允许每项目各一份，否则 A 项目的在途看不见 B 项目的删除请求）。
- **R3**：Epic 49 的进程内会话投影（`GET /api/session`）与新的持久化会话**并存**；`/api/session` 形状与语义
  不得改变（I13），语义上它仍代表「默认项目的当前进程投影」。
- **R4（评审 F7）**：控制台的全局 `run_id → project` 索引**没有上限与回收规则**，而 NFR-11 要求有界；
  实现须定义淘汰口径（与既有 run 记录/事件的保留期同源），并配测试。
- **R5（评审 F8）**：**运行落盘是否需要 `expected_version`**。`SessionStore.save` 新增的冲突检测默认
  `None`（= 现状 last-write-wins）；若网页侧仅 PATCH/DELETE 传期望版本、而**运行落盘不传**，
  则同一会话的两个并发 run（或 run 与 CLI）交替写仍可能**互相覆盖内容**（不损坏文件，但丢消息）。
  实现须明确运行落盘是否传版本，并在测试里覆盖「两写者交替」场景。

## Requirement Traceability

FR-3；NFR-6, NFR-7, NFR-8, NFR-10；UX-DR3, UX-DR4；脊柱 I3, I11, I13；brief §4 FR-3、§6.8、§7 D5。
