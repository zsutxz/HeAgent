---
epic: E50（网页控制台）
scope: Epic 50 收口后**增量轮**评审——Story 50-8（控制台体验优化 R1–R10）+ 对 50-1…50-7 面的回归式复核；含**续轮**（前端探针桩保真度 / 真实原生弹窗独立复现 / 新端点的入口宽度与默认姿态）
diff_range: e4d56cf..bb436b8（Story 50-8 的两条提交 cc717f8 / bb436b8；本轮修复另见「就地修复清单」）
review_loop_iteration: 0
reviewer: code_review 契约（三镜头 + 定级 + 分诊）
prior_rounds: reviews/review-epic-50-implementation.md（第一轮，50-1…50-4）· reviews/review-epic-50-closure.md（第二轮，50-1…50-7 收口放行）
verdict: 放行（Story 50-8 与 Epic 50 全量；4 处判据/口径已就地修复并带负向验证；新增 2 条 low 级 blocked 待人裁决，不阻塞）
created: '2026-09-26'
---

# Epic 50 · Story 50-8 收口后评审（第三轮）

按 `code_review` 契约执行：**对抗式 / 边界追踪 / 验证缺口** 三镜头独立成段；定级前逐条打开源码读调用点与守卫
（不只看 diff hunk）；`medium` 及以上与判据类发现一律就地最小修复 + **负向验证**并重跑受影响测试。

## 为什么还有第三轮（评审范围）

- 第一轮（`review-epic-50-implementation.md`）是**增量轮**，只覆盖 50-1…50-4；
- 第二轮（`review-epic-50-closure.md`，2026-09-24）是**收口轮**，覆盖 50-1…**50-7**，结论「放行」；
- **Story 50-8 在收口之后才落地**（`cc717f8` 2026-09-24、`bb436b8` 2026-09-25），它自我定位为「Epic 50 的增量
  需求落点」（R1–R10 十轮追加），**从未被任何一轮评审覆盖过**。本轮即以 50-8 的**新增面**为主靶
  （`cli_dialogs.py` 新模块 + 新端点 + 网页侧事件桥收敛 + 8 处前端改动），并对 50-1…50-7 的面做回归式复核。

## 评审范围

- **Epic 产物**：`_bmad-output/epics/epic-50-网页控制台周期/`（脊柱 + 8 份 story + 4 份验收/评审产物）。
- **diff 范围**：`git diff e4d56cf..bb436b8` —— 26 文件 / **+2784 −96**（src 约 +396、tests 约 +1258、产物与文档约 +1130）。
- **新增可执行面**：`src/heagent/cli_dialogs.py`（257 行，新）、`POST /api/dialogs/pick-directory`、
  2 个新错误码、`cli_http._web_tool_output`、`web/{index.html,app.js,styles.css}` 的 8 处改动。
- **执行方式**：三镜头由我逐处读真实源码 + 亲跑命令；对抗式与边界镜头另用一次性探针直接打真实模块
  （`.heagent/tmp/review50_8_probe_test.py` / `review50_8_badge_probe.py` / `review50_8_mutate.py`），不靠读 diff 猜。

### 我实际执行过的命令与结果（全部亲跑）

| 命令 | 结果 |
|---|---|
| `pytest -q`（HEAD，修复前） | **3142 passed / 11 skipped / 18 deselected**；覆盖率 **91.87%** —— 与 story R10 段自报数字**逐字一致** |
| `pytest -q`（本轮修复后） | **3144 passed / 11 skipped / 18 deselected**；覆盖率 **91.86%**（+2 例新判据） |
| `pytest tests/test_cli_dialogs.py tests/network/test_http_console_dialogs.py tests/test_http_web_ui.py -q` | 180 passed |
| `pytest tests/test_http_web_ui.py tests/test_config_catalog.py tests/test_http_agent_api.py tests/js -q` | 209 passed（含 node 前端探针） |
| `ruff check src tests` / `ruff format --check src tests` | All checks passed! / 280 files already formatted |
| `mypy src` / `mypy src --platform linux` | 均 `Success: no issues found in 147 source files` |
| `node tests/js/console_acceptance.mjs --port 8941`（修复前 HEAD） | `ACCEPTANCE {"rows":23,"failed":0}`（Chrome 153） |
| `node tests/js/console_acceptance.mjs --port 8951`（修复后，A11b 改用 **195** 档） | `ACCEPTANCE {"rows":23,"failed":0}`；A11b「共 **195** 个会话：默认渲染 10 条…按钮 36px/单行、提示在其下 6px」 |
| `python .heagent/tmp/mutate_50_8.py` | 23 条变异 **23/23 精确变红**（M2「去掉单在途守卫」耗时 **300.78s**——见镜头一 #11） |
| `python .heagent/tmp/review50_8_mutate.py`（本轮新增） | 5 条变异 **5/5 精确变红**（见「就地修复清单」） |
| `python -m heagent ...` / 枚举核对 | `HttpErrorCode` 成员 **34** 个，与 `docs/frame.md` 4.18 的「34 = 14 + 20」一致 |

---

## 镜头一 · 对抗式（找「缺什么」）

| # | 位置 | 问题 | 证据（亲读 / 亲跑） | 严重度 | 处置 |
|---|---|---|---|---|---|
| 1 | `cli_http.py:227-231` `_web_tool_output` + `_looks_like_a_failure` | **成功**读取一份**正文以 `Error:` 开头**的文件时收敛失效——整份正文照旧进网页对话区（AC9 第一句「成功的 `file_read` 不出现文件内容」被打破）。根因：AC9 的两句话在该输入类上**互斥** | 探针实测：`tool_error=False`、`tool_output='Error: SENTINEL-LEAK-50-8\nstack trace follows\n'`，哨兵确实进了网页帧；对照组（路径不存在）`tool_output.startswith("Error:")` 且诊断可见 | low | **intent_gap → blocked**（台账 **A17**）：要裁「收紧 AC9」还是「改内置工具的错误信号」，两者都在实现方权限之外 |
| 2 | `web/app.js::renderSessionCount` | 规模提示把 `state.sessions.length` 当**总数**，而服务端列表硬上限 200 且按时间降序截断、协议**无** `total`/`truncated` ⇒ 项目累计 > 200 时「共 200 个会话」「显示全部（200）」是**静默少报** | `context/session.py:49,402`（`MAX_SESSION_LIST_LIMIT = 200` + `entries[:limit]`）、`http_console_protocol.py:121`（无 total）、读码确认 UI 直接取 `length` | low | **intent_gap → blocked**（台账 **A18**）：修法要么加协议字段、要么改文案，属产品取舍 |
| 3 | `web/app.js:869` 注释 | 注释写「默认只显示最近 **20** 条」，而 `SESSION_VISIBLE_DEFAULT` 第二轮已改 **10**（第三轮还专门为阈值 20→10 加过变异 M14） | 读码：常量 10、注释 20 | low | **patch 已修**（改成 `SESSION_VISIBLE_DEFAULT` 引用，避免第三个数） |
| 4 | `tests/js/console_acceptance.mjs` A11b vs AC13 | AC13 的判据点名「某项目有 **195** 个会话（提示文字最长的一档）」，而**可复跑**的清单只造到 **21**（2 位数）；195 档当时只有一次性探针 `ui_layout_probe.mjs` 的证据 | 读码：`for (let index = 0; index < 21; ...)`；验收报告 R9 段引用一次性探针 | low | **patch 已修**（清单改为造到 195 后复跑 **23/23**，按钮 36px/单行、提示在其下 6px） |
| 5 | `cli_dialogs.py:98` `parse_marked_path` | 复验用 `Path(candidate).is_dir()`，**相对路径**会相对服务进程 cwd 解析 ⇒ 病态后端可让它回一个「恰好存在的相对目录」 | 读码；两个冻结脚本都回绝对路径（tkinter `askdirectory` / PS `SelectedPath`） ⇒ 不可达 | low | **reject**（不可达 + 返回值仍过登记校验，且校验链只有一条） |
| 6 | `cli_dialogs.py:127` `_command_for` | `[_powershell_path() or "", ...]` —— 若被直接以不可用后端调用会得到**空 argv[0]**（报 `FileNotFoundError` 而非清晰错误） | 读码：`resolve_backend` 先门控，公共路径不可达 | low | **reject**（防御性写法，不可达） |
| 7 | `http_console_protocol.py` `DirectoryPickResponse.path` 的 `max_length` | 选到超长路径（> `MAX_PROJECT_PATH_CHARS`）时，**响应模型构造**在入口层抛 `ValidationError` ⇒ 端点的 `except Exception` 兜成 **500 `server_error`**，而不是稳定码 `invalid_project_path` | 读码 `cli_http.pick_directory` 直接 `DirectoryPickResponse(path=path, ...)`；`_build_dialog_endpoint` 的 catch-all | low | **reject**（量级罕见 + 500 方向 fail-safe；同一路径在 `POST /api/projects` 也会被拒） |
| 8 | `DirectoryPickResponse` 的 `cancelled` / `backend` | 两个字段 UI 未消费（`pickProjectDirectory` 只看 `path`）——协议字段「声明了没人用」 | 读码 `app.js::pickProjectDirectory`；两字段均被单测断言（协议契约本身） | low | **reject**（协议完整性；`backend` 是「为什么弹不出来」的诊断面） |
| 9 | `web/styles.css` `.chat-log > * { width: 100% }` / `.composer > * { width: 100% }` | 两条规则与 column flex 的默认 `align-items: stretch` **等价**（冗余）——R7 的「占满」实际由**撤销 `max-width`** 实现 | 读码：`.chat-log{display:flex;flex-direction:column}`、`.composer{display:flex;flex-direction:column}`；真浏览器实测 1288px | low | **reject**（显式口径，可读性收益；不是缺陷） |
| 10 | `docs/frame.md` 4.18「前端纪律…**前端零硬编码**」vs `app.js:1227` | 新代码引入了一份**与真值逐字相同**的硬编码中文兜底（`|| "只读"`）——该声明在此处不再成立，且**因为逐字相同而没有判据**能发现服务端声明的丢失 | 变异实测：把兜底写死 ⇒ `tests/test_http_web_ui.py` **137 passed / 0 failed**（全绿） | medium | **patch 已修**：桩里改用**钩子值**（`只读（桩）`）让「渲染的是服务端文案」可判 + 服务端补一条「声明存在且够短」的判据 |
| 11 | `tests/network/test_http_console_dialogs.py::test_second_request_while_a_dialog_is_open_is_busy` | 撤掉单在途守卫后，该用例会**跑满默认 300s 超时**才变红（实测 M2 = **300.78s**）——判据本身没问题，但负向验证成本 5 分钟 | 亲跑 `mutate_50_8.py`：`M2 ... 300.78s` | low | **reject**（记录：迟红的成因是假子进程「永不返回」+ 默认超时；改小超时需注入 `DirectoryPicker(timeout=…)`，而那会削弱「接线用的是默认值」这一断言面） |
| 12 | `DirectoryPicker.pick()` 的客户端断开 | 关标签页后 ASGI 未必立即取消协程 ⇒ 子进程与名额活到 300s 超时。**无专门释放路径** | 读码：只有 `TimeoutError` / `CancelledError` 两条清理；全套用例无「断开」场景 | low | **reject**（有意的语义：窗口是**服务端**的真实 UI，用户关页面 ≠ 放弃选择；超时兜底已存在） |
| 13 | `cli_dialogs.py::DEFAULT_TIMEOUT_SECONDS` | 300s 是模块常量、后端由 CLI 选项给、**不新增 `Settings` 字段** —— 与「配置面越少越好」一致，但意味着运维无法在 `.env` 里调 | 读码 + `http-server --help` 实测 `--dialog-backend [auto|tkinter|powershell|none]` | — | **已核无问题**（story 明确取舍：不动 `.env.example` / 配置字段断言） |

> 镜头一合计 **13 条发现**（含 10 条具名问题 + 3 条已核记录），满足契约「至少 10 条」。
> 另有三项「已核无问题」记录在镜二（见下），避免「没写就是没查」。

## 镜头二 · 边界追踪（真实调用链）

| # | 边界输入 → 行为 | 证据 | 严重度 | 处置 |
|---|---|---|---|---|
| ① | 成功的 `file_read`，**内容以 `Error:` 开头** → 整份正文进网页（收敛失效） | 探针 P1（亲跑） | low | 见镜一 #1（blocked A17） |
| ② | 失败的 `file_read`（路径不存在 / 越界）→ `tool_error=False` 但 `tool_output="Error: ..."` **照旧可见** | 探针 + 既有用例 `test_read_tool_error_message_is_still_shown_in_web` | — | **已核无问题**（诊断不消失，正是收敛判据避开的坑） |
| ③ | **恰好 10** 个会话（等于阈值）→ `overflows = total > 10` 为假 ⇒ 只显示「共 10 个会话」、按钮隐藏（AC12 的「不足 10 条」按 `>10` 判定，恰 10 与 <10 同形） | 读码 + 探针 P/Q（35 / 12 两档）；**恰 10 无单列用例**（判据是一行比较，如实记录） | — | **已核无问题**（并注明证据粒度） |
| ④ | 会话数 201（越过服务端 200 上限）→ 计数少报 | 读码 | low | 见镜一 #2（blocked A18） |
| ⑤ | 并发第二次选择 → 409 `dialog_busy`；用例**等可观测条件**（`_picker.in_flight`）而非固定墙钟 | `test_second_request_while_a_dialog_is_open_is_busy`（含 `for _ in range(100)` 轮询） | — | **已核无问题**（时序纪律正确） |
| ⑥ | `--dialog-backend none` → 503 `dialog_unavailable` + UI 给出**服务端原因**、手工输入保留、不登记 | 真浏览器 B2 端到端（亲跑） | — | **已核无问题** |
| ⑦ | **非回环**来源 → 403 `loopback_required`，且**不 spawn**（拉起进程之前就被拒） | `TestEndpoint` + `TestRealAssembly` 各一例（`_Spawn` 零调用） | — | **已核无问题** |
| ⑧ | 后端进程**非零退出** → `DialogUnavailableError`（**不**伪装成「用户取消」）→ 503 + 原因 | 单测 `test_nonzero_exit_is_unavailable_not_cancel` | — | **已核无问题** |
| ⑨ | 子进程 stdout 脏输出 / 无标记行 / 非 UTF-8 字节 → 一律按「取消」 | `parse_marked_path` 四例单测（含 `b"\xff\xfe not utf-8"`） | — | **已核无问题** |
| ⑩ | 超时 / **外层取消** → `kill()` + 有界回收（`reap_subprocess`）+ 归还名额（`finally`） | 两例单测各断言 `killed is True` 与 `in_flight is False` | — | **已核无问题** |
| ⑪ | 子进程环境：`scrub_sensitive_env()`（**返回副本**，不污染父进程）+ `PYTHONIOENCODING=utf-8`；无 `shell` 键 | 单测 `test_kwargs_are_pipe_only_and_never_use_shell`（额外断言 `"shell" not in kwargs`） | — | **已核无问题** |
| ⑫ | `pick()` 的 check-then-set **之间无 `await`** ⇒ 单事件循环内不存在重入窗口；`resolve_backend` 抛错时名额未被占用 | 读码 | — | **已核无问题** |
| ⑬ | 写通道 / 会话 CRUD / 配置面板（50-2…50-5 的面）本 story **零改动** | `git diff --numstat`：`config_write.py` / `projects.py` / `context/session.py` 均不在 50-8 的改动集内 | — | **已核无问题**（回归面收窄到前端与事件桥） |

## 镜头三 · 验证缺口（对照 AC 与测试报告）

| # | AC / 声称 | 实际证据 | 严重度 | 处置 |
|---|---|---|---|---|
| ① | AC9「run 结束后检查**会话文件**与 `rollout.jsonl`，工具结果逐字保留」 | **此前没有任何判据**（实现报告给的「模型仍拿到全文」走的是 `state.messages`，与 `SessionStore.save` 不是一回事；非项目 `/api/runs` 的 `_project` 只投影 user/assistant，根本无会话文件） | medium | **patch 已修**：新增项目内运行用例（网页帧空 / 会话文件含哨兵）；负向 N4 精确变红 |
| ② | AC13 的 **195** 档 | 可复跑清单只造 21（见镜一 #4） | low | **patch 已修**（改成 195 + 复跑 23/23） |
| ③ | 「`write_channel_badge` 是服务端声明、前端只做缺失兜底」 | 判据**空转**：桩未提供该键、前端兜底与真值逐字相同 ⇒ 写死后 137 passed / 0 failed | medium | **patch 已修**（钩子值 + 服务端短文案判据）；负向 N1/N2 同时变红 |
| ④ | 「收敛范围**只有** `file_read`」（用例名 + story 声称） | 用例名说「其它工具保留内容」，实际那条 `file_edit` 调用**失败**（kwargs 拼错）⇒ 断言靠 `or tool_error is True` 成立；实测**把 `file_edit` 加进收敛集该用例仍绿** | medium | **patch 已修**（改用**成功**的 `file_write` + 断言 `tool_error is False`）；负向 N3 精确变红 |
| ⑤ | 50-8 的 23 行真浏览器清单 | 本轮**亲跑** 23/23（修复前后各一次，Chrome 153） | — | **已核无问题** |
| ⑥ | 「`cli_dialogs.py` 覆盖率 93%」 | 亲跑定向覆盖率：93%（`108-110, 123, 127, 165` 未覆盖，均为 `# pragma: no cover` 的回收/防御分支） | — | **已核无问题** |
| ⑦ | 全量 3142 passed / 91.87% | 亲跑逐字一致（修复后 3144 / 91.86%） | — | **已核无问题** |
| ⑧ | 「23 条变异全红」 | 亲跑 23/23 全红（M2 耗时 300.78s） | — | **已核无问题** |
| ⑨ | AC9「同一份事件在 CLI / GUI 上显示与改造前一致」 | 无**新**判据，但收敛点唯一地落在 `cli_http` 的网页桥（`HttpAgentHandler` 不被 CLI/GUI 使用），且多例既有用例仍绿（全量 3144 passed） | — | **已核无问题**（收敛点的**单点性**本身就是判据） |

---

## 就地修复清单（最小修复 + 负向验证）

| # | 文件 | 修复 | 受影响测试（重跑） | 负向验证（`.heagent/tmp/review50_8_mutate.py`） |
|---|---|---|---|---|
| A | `tests/js/app_probe.js` + `tests/test_http_web_ui.py` + `tests/test_config_catalog.py` | 闸门徽标改判**服务端声明**：桩用钩子值 `只读（桩）`（与兜底不同），两条探针断言改为依赖它；服务端补 `test_write_gate_badge_label_is_declared_and_stays_short`（声明存在 + `len <= 4` 的宽度硬约束） | `pytest tests/test_http_web_ui.py tests/test_config_catalog.py` → 全绿 | **N1**：把 `app.js` 的徽标写死 ⇒ **2 failed**（修复前同一变异 **0 failed**，见镜一 #10）；**N2**：删掉 `LABELS["write_channel_badge"]` ⇒ **1 failed** |
| B | `tests/test_http_agent_api.py` | 「其它工具保留内容」改用**成功**的 `file_write`，并把断言从 `output != "" or tool_error is True` 收紧为 `tool_error is False and output != ""` | `tests/test_http_agent_api.py` → 14 passed | **N3**：把 `file_write` 加进 `_WEB_QUIET_TOOLS` ⇒ **1 failed**（修复前把 `file_edit` 加进去 **0 failed**） |
| C | `tests/test_http_agent_api.py` | 新增 `test_read_content_is_hidden_from_the_web_but_still_persisted_on_disk`：项目内运行 + `file_read` ⇒ 网页帧 `tool_output == ""` **且**会话文件的 TOOL 消息含哨兵 | `tests/test_http_agent_api.py` → 14 passed | **N4**：落盘时滤掉 TOOL 消息（`persist_and_cache`）⇒ **1 failed**；**N5**（对照）：网页桥不收敛 ⇒ **2 failed** |
| D | `src/heagent/web/app.js:869` | 注释「最近 20 条」→ 引用 `SESSION_VISIBLE_DEFAULT`（消除第三个数） | 全量 | 纯注释（无法变异）；以「常量是唯一事实源」的方式修掉 |
| E | `tests/js/console_acceptance.mjs` | A11b 造数 21 → **195**（AC13 点名的档位；改用「按 API 计数补到 195」的循环），并同步两处过时注释 | 真浏览器复跑 → **23/23**（A11b 实测 195 档几何仍成立） | 清单不在 CI；以**复跑**取证（负向见验收报告的既有 A11b 几何判据 + M18） |

**删除检查**：`e4d56cf..bb436b8` 未删除任何既有守卫或契约。被改写的既有测试两处，均为**改强**：
① `test_http_security.py::test_tool_output_is_not_logged` 把「客户端能拿到」改成「网页帧里也没有 + 但模型拿到了」；
② `test_http_agent_api.py::test_real_loop_streams_tool_events` 补建真实文件（原先读的是**不存在**的
`pyproject.toml`，虽名为「流式工具事件」实为失败路径）。本轮未再改写它们的语义。

## 处置汇总

| 严重度 | 条数 | 处置 |
|---|---|---|
| high | **0** | — |
| medium | **3** | **patch 已修 3**（镜一 #10 = 镜三 ③ 徽标判据空转 / 镜三 ① 会话文件证据缺失 / 镜三 ④「其它工具」判据无牙） |
| low | **11** | **patch 已修 2**（镜一 #3 注释漂移、镜一 #4 = 镜三 ② AC13 的 195 档）；**intent_gap → blocked 2**（镜一 #1 → A17、镜一 #2 → A18）；**reject 7**（#5 相对路径 / #6 空 argv / #7 超长路径 500 / #8 未消费字段 / #9 冗余 CSS / #11 迟红成本 / #12 断开语义） |
| 已核无问题 | **17 条** | **记录在案**（镜一 #13 配置面取舍 1 + 镜二 ① 与 ④ 之外的 11 行 + 镜三 ⑤–⑨ 5 行）——避免「没写就是没查」 |
| reject | 7 | —（逐条给出「为什么不构成问题」的理由，不静默丢弃） |

> **去重口径**：镜三 ② 与镜一 #4（同一主张 + 同一动作：把 AC13 的 195 档写进可复跑清单）、镜三 ③ 与镜一 #10
> （同一主张：新服务端声明键的判据空转）各合并为一条；镜二 ① / ④ 是镜一 #1 / #2 的调用链视角，同条目。

新增台账条目 **2 条**（A17 / A18，均 `intent_gap / blocked`；活动区 16 → 18），已同步
`deferred-work-archive.md`（计数 + 流水账单行 + 正文）与 `consolidated-overview.md`（§17.3 / §17.4-A 计数、
A17/A18 两行、目录地图行、文首「生成」行）。
`review_loop_iteration: 0` —— 本轮无「回实现阶段重新推导」的情形（全部为就地最小修复或如实登记）。

## 续轮（同一评审的第二批探测：桩保真度 / 真实弹窗 / 入口宽度）

第一轮把重点放在 50-8 的 diff 面。续轮沿三条**没有任何一轮探过**的线继续：

| # | 探测 | 结论 | 严重度 | 处置 |
|---|---|---|---|---|
| 1 | 前端探针桩（`tests/js/app_probe.js` 的最小 DOM 替身）**能证明什么** | 四处**保真边界**此前没有文档化：① **没有 DOM 树**（`els[id]` 是扁平注册表，index.html 的嵌套关系不存在）；② **不含 HTML 静态文本**（`<summary id="…">项目 .env 诊断</summary>` 在替身里初始 `textContent` 是空串）；③ **没有 CSS**（`hidden` 与作者样式的相互作用只能靠真浏览器，Z-D15 类）；④ `children` **含文本节点**（真 DOM 只含元素）。任一被误用即得**假绿** | low | **patch 已修**（边界写进桩首注释）。并**逐条复核现有断言**：30+ 处 `children` / `textContent` 取值全部落在 app.js **动态创建**的结构上（`li` / config row / chat entry / group），静态结构类断言一律直接读 `_HTML` ⇒ **当前无假绿**；`app.js` 也不使用任何替身未实现的 API（无 `querySelector*` / `.style` / `classList` / `.remove()` / `insertBefore`）——「两侧同时收窄」是这套挂具成立的前提，已写进注释 |
| 2 | 「唯一不能自动化的那一步」：**真实原生弹窗** | **独立复现通过**：`resolve_backend('auto') = tkinter` → 真拉起子进程 → **2.0s 超时** → kill + 归还名额（`in_flight=False`）+ WARNING；并补测了作者探针没测的一点：**名额归还后第二次调用不再 busy** | — | **已核无问题**（探针 `.heagent/tmp/review50_8_dialog_real_probe.py`，两次调用各留一条 WARNING） |
| 3 | 新端点的**入口宽度与默认姿态** | 故事 T2 只把 `--dialog-backend` 接到 `heagent http-server`；`HttpProjectConsole` 的默认值 `"auto"` 因此也进了**默认 CLI 的内嵌服务**（`python -m heagent` 交互 / 单次模式各起一份），而内嵌路径**没有** CLI 选项、也没有 `Settings` 字段 ⇒ **无法关闭**。与写通道 `HTTP_CONSOLE_WRITE_ENABLED` 默认 **False** 的惯例相反 | low | **intent_gap → blocked**（台账 **A19**）+ **patch 已修文档**（`docs/frame.md` 4.18 安全声明段与五 的缺口行按实测补正：默认开 / 两个入口都生效 / 内嵌路径无开关） |

**续轮实测命令（全部亲跑）**

```bash
$ .venv\Scripts\python.exe .heagent/tmp/review50_8_embedded_probe.py   # 真实 build_http_service 装配 + 假 spawn
内嵌服务监听：127.0.0.1:8791
GET  /api/health                  -> 200
POST /api/dialogs/pick-directory  -> 200 {"path":null,"cancelled":true,"backend":"auto"}
实际拉起过对话框子进程吗？ True   argv=[['E:\\AI\\HeAgent\\.venv\\Scripts\\python.exe', '-c']]

$ .venv\\Scripts\\python.exe .heagent/tmp/review50_8_dialog_real_probe.py   # 会短暂闪一个 tkinter 窗口 ≈2s
resolve_backend('auto') = tkinter
result=None elapsed=2.0s in_flight(after)=False
再调一次（名额已归还 ⇒ 不应 busy）
second call ok: result=None in_flight(after)=False
LOG WARNING heagent.cli_dialogs: directory dialog timed out after 2s; treated as cancelled   （×2）
```

**续轮处置汇总**：high 0 / medium 0 / **low 2**（patch 1 文档 + blocked 1）/ 已核无问题 1。
台账活动区 **18 → 19**（+A19），`docs/frame.md` 4.18 与五**两处**补正，`consolidated-overview.md` 计数同步。

## 结论

- **Story 50-8：放行。** 主功能面（新端点 + 源码模块 + UI 收敛 + 8 处前端改动）与第二轮收口时的 50-1…50-7 面
  均无 high 残留；数字类声称（3142 passed / 91.87% / 23 条变异 / 23 行真浏览器）**逐条亲跑复现一致**；
  新模块的纪律（无 shell、冻结 argv、凭证剥离、超时 kill、单在途、回环门先于 spawn）在源码与用例两侧都成立。
- **Epic 50（8 条 story）：放行。** 本轮把三处**判据空转**修成有牙的判据（并各自留下「修复前全绿 / 修复后变红」的对照），
  AC9 缺失的那一半证据补齐，AC13 的 195 档进可复跑清单。
- **不阻塞收口但需人裁决的 2 项**（已进台账，均 low）：**A17** R5 收敛判据对「正文以 `Error:` 开头的文件」失效
  （AC9 两句话互斥）；**A18**「共 N 个会话」在 >200 时为下界而非总数。两条都属「改规格 / 改协议」的口径，非实现方可自决。
- **给下一次评审的备忘**：本轮最有效的两招——① **「判据空转」探针**：对任何「后端声明 + 前端逐字相同兜底」的
  文案契约，先做一次「把消费端写死」的变异，全绿即说明判据是瞎的；② **对「用例名声称的行为」做一次反向变异**
  （把新工具加进收敛集、把落盘滤掉），能立刻区分「用例在验行为」与「用例在走过场」。
