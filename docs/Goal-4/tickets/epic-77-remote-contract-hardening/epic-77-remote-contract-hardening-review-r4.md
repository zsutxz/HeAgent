---
type: review
code: E77-R4
epic: epic-77-remote-contract-hardening
review_loop_iteration: 1
lens: 已提交代码复审（实现质量 / 接线点 / 与既有同名字段的语义边界）
reviewed_at: 2026-11-24
head: 95945586
---

# E77 提交后代码复审 · R4

## 范围

`95945586`（E77 全部交付）的**已提交代码**，按「新增大模块 + 其接线处」优先级读：

| 面 | 文件 | 结论 |
|---|---|---|
| 新增模块 | `cli/ws_submission_cache.py`（82 行） | 无死代码、无超限、纯内存、时钟可注入；**60/256 无判据**（见 R4-M-2） |
| 适配器 | `cli/ws_project_adapter.py`（147 行，≤150 预算） | `shield` / `drop` / `future.done()` 三处守卫逐条走通，异常路径与 R2 结论一致 |
| 命令层 | `network/ws_commands.py::_start_project_run` / `_submit_run` | `request_id` 只在项目径下传；**不带 `project_id` 时被静默忽略**（见 R4-M-1） |
| 帧模型 | `network/ws_protocol.py` | 白名单实测：`projects` / `cancel_run` 带 `request_id` 一律 `malformed`，只有 `run` 收（探针实跑） |
| 错误码 | `network/http_protocol.py` + `web/app.js` | 新码 HTTP 面永不返回（`status: null` / `unmapped`），WS 两路径各一处；Web 文案由既有参数化判据覆盖 |

## 发现

### R4-M-1（Medium，已落改）`request_id` 不带 `project_id` 时被**静默忽略**

- 复现（探针实跑）：连续两次 `_submit_run(..., request_id="req-1")`（不带 `project_id`）
  ⇒ `start_run` 被调 **2 次**、ack 两个不同 `run_id`。
- 判定：行为本身可接受（幂等窗口住项目通道适配器，启动工作区径没有它），但**静默**是这个仓明确
  反对的形态（同族先例：「只读 listener 用『不支持』而不是『静默忽略』」）。客户端只要漏了
  `project_id`（或将来改成默认项目提交），就会以为去重生效而实际每次新起 run。
- 处置：**已落改**（不改行为、只把边界显性化 + 钉判据）：
  - `ws_protocol.py::WsCommandFrame` docstring 写明「只在带 `project_id` 的项目径生效；带键不带
    `project_id` 的帧合法却不去重」；
  - `ws_commands.py::_submit_run` docstring 指回同一口径；
  - `docs/framework.md` 提交 run 行同步；
  - 判据 `tests/network/test_ws_project_submit.py::test_request_id_without_project_id_never_reaches_the_idempotency_window`
    （同帧重发两次 ⇒ `start_run` 2 次、项目端口 0 次、2 个 ack）。

### R4-M-2（Medium，已落改）文档写的 60s / 256 没有判据，两个常量的 `__all__` 导出也无人消费

- 现象：`IDEMPOTENCY_TTL_SECONDS = 60.0` / `IDEMPOTENCY_MAX_ENTRIES = 256` 在 `__all__` 里，
  但全仓**没有任何消费者**（只作构造默认值）；`docs/framework.md` 把 60s / 256 写成对外口径，
  改数字不会红任何用例。
- 处置：**已落改** 新增 `tests/test_ws_submission_cache.py::test_window_defaults_match_the_documented_numbers`
  —— 常量 == 文档数字、构造默认值 == 常量。注入反证：把 `60.0` 改 `30.0` ⇒ **2 failed**
  （该用例 + 过期用例），复原即绿。

### R4-L-1（Low，已落改）WS `request_id` 与 HTTP `request_id` 同名不同义，文档未点明

- 位置：`docs/framework.md:1376` 的可观测性行已有「不透明 `request_id` / `x-request-id` 追踪」，
  与本 epic 的 WS 帧 `request_id`（幂等键）同名。两者无任何关系（WS 那个不回显、不进日志、
  不落 `x-request-id`）。
- 处置：**已落改** 在提交 run 行写明「与 HTTP 的 `x-request-id` 追踪 id 同名不同义、互不填充」，
  帧模型 docstring 同句——避免客户端把两个 id 当同一个用。

### R4-L-2（Low，记录不改）`if not future.done()` 在正常路径不可达

- 唯一能让 `Future` 在 owner 落结果前变成 done 的路径是「合流者直接取消它」，而合流者只经
  `shield` 等（取消的是自己不是 `Future`）⇒ 该守卫实际只兜意外。保留作防御，但**它正是 R2-M-1 那条
  docstring 误述的成因**（作者据此以为 `set_result` 会撞 `InvalidStateError`）。措辞已在 R2 纠正。

### R4-L-3（Low，记录不改）同一句错误文案在两处硬编码

- `ws_commands.py` 的提交径与列表径各写一次 `"project addressing is not available on this listener"`。
  提模块常量收益约 2 行、且要新增一处跨函数引用；本仓对「三行以内重复」的既有立场是不抽公共层
  ⇒ 不动，留作记录。

## 复核项（无问题）

- `request_id` 长度界 1–64 与 `run_id` 同档；不 strip（既有用例钉住 `" req-1 "` 原样保留）。
- `SubmissionCache.reserve` 的查表与登记之间无 `await`（A9③ 老坑未复发）。
- 适配器只用 `ConsoleOperationError` / `ProjectRegistryError` 翻译，其余异常直冒 ⇒ 连接骨架收敛
  `server_error`（漏译显性）。
- `cli/` 对 `network/ws_protocol` 的 `SubmittedRun` 是 `TYPE_CHECKING` 导入 ⇒ 无运行期跨层依赖。
- 传输层零命中 `SubmissionCache`（`grep` 0），「幂等是提交语义不是传输语义」这条结构保证成立。

## 结论

C0 / H0 / **M2** / L3，两条 Medium 当轮落改并配注入反证；三条 Low 中 1 条落改（文档同义消歧）、
2 条记录。落改后门禁：`pytest tests/network tests/test_ws_submission_cache.py
tests/test_ws_project_adapter.py tests/test_architecture_contracts.py tests/test_contract_baselines.py
tests/test_docs_links.py tests/test_http_web_ui.py -q` = **978 passed**；`ruff check` / `format --check`
（512 files）/ `mypy src`（242）全绿；五份契约基线 `[OK]`；`mkdocs build --strict` exit 0、0 WARNING。
