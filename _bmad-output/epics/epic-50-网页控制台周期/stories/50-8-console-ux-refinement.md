---
id: 50-8
title: 控制台体验优化（会话列表精简 / 原生目录选择 / 布局调整 / 设置面板瘦身 / 读取结果收敛）
status: review
baseline_commit: e4d56cf3562b75dbdcfe3d716db5dfa1b8f85181
parent_epic: E50
priority: P1
phase: F（增量优化轮；Epic 50 收口放行后的体验迭代）
depends_on: [50-1, 50-2, 50-3, 50-4, 50-5, 50-6, 50-7]
blocks: []
created: '2026-09-24'
baseline_commit: e4d56cf3562b75dbdcfe3d716db5dfa1b8f85181
---

# Story 50-8：控制台体验优化与增量需求收口

## 用户故事

作为网页控制台的使用者，我希望侧栏与设置面板**更少噪音、更少手工输入**——
会话列表只呈现最近若干条、登记项目时能用本机资源管理器挑目录、会话区不要挤在最左边、设置页不要通篇解释文案——
以便这个控制台在真实使用中顺手，而不是「功能齐了但每天用起来别扭」。

## 本 story 的特殊定位（**Epic 50 的增量需求落点**）

Story 50-1…50-7 已把 Epic 50 建完并收口放行。本 story 是**收口后的增量优化轮**，同时**充当 Epic 50 后续新需求的
统一落点**：用户后续口头/评审派生出的新需求，一律追加到本文「需求并入区」（R6、R7…），
不为此新开 story——除非用户明确要求拆分。因此本文的验收标准是**开放集**：实现时以并入区的最新内容为准。

## 侦察实证（2026-09-24 实测，非推断）

| 事实 | 证据（亲读 / 亲跑） | 含义 |
|---|---|---|
| 会话列表的服务端硬上限是 **200**，且**无分页参数** | `network/http_console_protocol.py:46` `MAX_SESSION_LIST_ENTRIES = 200`；`SessionListResponse` 只有 `sessions` 一个字段（`:121`） | 「只显示最近 20 条」是**纯 UI 侧**改动，不必改协议、不新增第二套有界口径 |
| 排序已由服务端给定（时间降序） | `context/session.py:415` `entries.sort(key=…timestamp, session_id, reverse=True)`；`cli_http.py:554 list_sessions` 原样返回 | UI 只做 `slice`，**不得**在前端重排（否则出现第二套排序事实源） |
| UI 无条件渲染全部会话 | `web/app.js:763` `for (const session of state.sessions)` | 截断点唯一，改动面小 |
| 项目登记目前是**纯手工绝对路径输入** | `web/index.html:33-37`（`#project-path` + `#project-name` + `#project-register`）；`app.js:654` `asText(el.projectPath.value).trim()` | 「选择文件夹…」只需在**同一表单**加按钮并把结果填入同一 input → `POST /api/projects` 契约与校验链**完全不变** |
| 本机原生对话框可用（tkinter 实测） | `.heagent/tmp/probe_50_8.py` 实测：Python **3.13.5**（`E:\AI\HeAgent\.venv\Scripts\python.exe`）；`tkinter` / `tkinter.filedialog` / `tkinter.ttk` spec **FOUND**、`import tkinter` OK、`askdirectory` 可调用 | tkinter 后端在本机可行；仍需 `auto` 顺序 + 不可用兜底（其他环境可能缺 `_tkinter` 或无显示） |
| Windows 第二后端可用 | 同探针：`powershell.exe` = `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.EXE`；`pwsh` **不存在**；`DISPLAY` 未设置（Windows 正常） | 第二后端只押 PowerShell 5.1，不押 `pwsh` |
| 回环门已有**单点**可复用 | `network/http_server.py:1282 _loopback_error()`（内部复用 `network.exposure.is_loopback_host`，含 `::ffff:127.0.0.1` 形式） | 新端点复用同一函数，**不新增**第二套来源判定 |
| 新端点的落点已成型 | 路由常量 `http_server.py:119-127`；项目端点闭包 `_build_project_endpoints()`（`:1319` 起）；handler 协议 `http_console_protocol.py:436 list_sessions` 等 | 增量 = 协议加 1 个方法 + 路由加 1 条 + `cli_http.HttpProjectConsole` 加 1 个实现 |
| 新错误码有**自维护**判据 | `tests/test_http_web_ui.py` 的错误码用例由 `HttpErrorCode` 枚举派生（收口评审已从 14 条扩到 **32 条**）；`app.js::ERROR_TEXT` 32 键与之逐一对齐（`review50_errorcodes.py` 实测 0 缺 0 幽灵） | 新增码必须同时补 JS 文案，否则**精确变红**（不会静默漏文案） |
| 设置面板现状 = 长文案 + 常驻诊断 | 长横幅 `app.js:1134`（文案源 `config_catalog.py:442 write_channel_disabled`）；闸门关闭时**逐项重复**同一长句 `app.js:1179`；诊断块 `app.js:1300 renderDiagnostics()`（`.env` 路径/存在/行数/指纹/BOM/重复键/空值键/notes）常驻 | 「瘦身」的靶点明确：**面板级一行短状态 + 逐项短标签 + 诊断/未知键折进 `<details>`** |
| 侧栏结构与列宽 | `web/index.html:27-52`：`.sidebar` 纵向 flex 内含「项目」「会话」两块 panel；`styles.css:25 --sidebar-width: 280px`；`.console` 两列 `styles.css:171`；设置面板打开时三列变体 `styles.css:175` | 「项目 / 会话 / 对话」的排布有既定两列/三列基础可复用；**最终口径（用户第二轮裁决）= 一列 + 参考 ChatGPT**（R3/R6） |
| 真浏览器验收清单为 **23 行** | `tests/js/console_acceptance.mjs`（2026-09-24 收口后 18/18 PASS，Story 50-8 追加 A5b/A11b/A11c/A11d/B2 后 **23/23**，Chrome 153）；其中 **A5** = 填写目录→登记、**A11** = 设置面板、**A11d** = 布局 | 本 story 改动了登记、设置与布局三处 → 清单必须同步改行 + 复跑；Z-D15 的教训是「清单不过硬就漏真缺陷」 |
| 工具结果进网页只有一个缝 | 工具原文由 `agent/stream_runtime.py:150` 填进 `StreamEvent.tool_result_content`；**网页桥** `cli_http.py:334-338` 原样交给 `RunEventPublisher.tool_result()`；服务层再用 `clip_text()`（`network/http_protocol.py:312`，默认上限 `MAX_EVENT_TEXT_CHARS`）截断；前端结果行 `app.js:405-412` 渲染「对勾 + 工具名：output」 | R5 的实现点 = **入口层 bridge 里对读取类工具把内容置空**（网页专属，不动 `events/` 与 rollout）；前端在无内容时只渲染「对勾 + 工具名 → 作用对象」。另：网页重建历史只渲染 `user`/`assistant` 两类消息（`app.js:889`）→ 刷新后本就不含工具结果，无需第二处改动 |
| 台账相关条目现况 | `implementation-artifacts/deferred-work-archive.md` 活动区含 Epic 50 收口评审 5 族条目（运行时归因 / 阻塞 I/O / 非回环姿态 blocked / 高影响键确认 / 保真写四类残余）+ 计划期 1 条（跨项目并发无全局上限） | 这些都是**候选并入**项，本文只**引用**不复制（同一事实写两处必然漂移） |

## 范围

### 本 story 明确要做的六条（R1–R6）

- **R1 会话列表精简**：侧栏会话列表默认只呈现**最近 10 条**（服务端已按时间降序给出），并给出「共 N 条」提示；
  超出部分经一次显式操作可查看（不丢可达性）。
- **R2 原生目录选择**：登记项目时提供「选择文件夹…」，调用**服务端所在机器**的原生目录选择对话框
  （Windows 资源管理器 / 桌面环境的目录选择），返回值填入既有路径输入框；**手工输入与既有校验链完全保留**。
- **R3 项目与会话同栏**（2026-09-24 用户裁决，**取代**原「会话框尽量往右挪」）：**项目与会话放在同一列**（侧栏
  纵向堆叠，项目在上、会话在下），不做多栏。
- **R6 界面布局参考 ChatGPT**（2026-09-24 追加）：左栏（项目 + 会话，一列、可滚动）+ 右栏对话区；对话内容
  是**限宽居中的阅读列**（超宽屏不把正文拉成一行长文），底部输入条与之同宽。窄屏降级沿用既有约定。
- **R4 设置面板瘦身**：移除「服务启动时未开启配置写入（…）：所有可写项在本页只读；网页无法自行开启，
  需在启动配置（系统环境变量 / 项目 .env / 全局 .env）里开启后重启服务」这条长横幅，并去掉逐项重复的
  解释性长文案与常驻诊断说明——降噪**但不丢信息**（见 AC4）。
- **R5 读取类工具的内容不上网页**（2026-09-24 追加）：网页对话区里 `file_read`（即界面上的「read 命令」）
  **只显示文件名 / 作用对象，不再显示读取到的内容**。范围严格限定在**网页侧**：会话文件、`rollout.jsonl`、
  CLI、GUI 一律不变（审计与回放仍保留全文）；**失败结果的消息照旧显示**（诊断必需，见 AC9）。

### 非目标（本 story 不做，必要时另立）

- 不做服务端「目录浏览」API（遍历目录列目录树）——那会把宿主目录结构开放给任意回环客户端，
  且真浏览器验收无法覆盖；如需（无 GUI 后端场景）先并入「需求并入区」再定。
- 不改写通道语义、白名单、备份/审计、回环门覆盖范围（那是台账里 `blocked 待人裁决` 的条目，见并入区候选）。
- 不引入前端构建链 / 第三方脚本 / playwright（沿用「零构建链、浏览器验收不进 CI」的既有立场）。

## 待确认口径（**动手前必须由用户裁决**）

| # | 问题 | 我的候选（默认建议） | 说明 |
|---|---|---|---|
| Q1 | R3「会话框尽量往右挪」的确切含义？ | **(a) 三栏布局**：`项目 ｜ 会话 ｜ 对话`——会话列表独立成中栏（比现在 300px 侧栏内更宽），窄屏（<1040px）仍降级为侧栏内上下堆叠 | 另两种可能：**(b)** 只是把「会话」面板里的控件行（新建会话/项目徽标）右对齐；**(c)** 只把侧栏加宽（300 → 360/400px）。三者工作量与观感差别很大，误判会白做一轮 |
| Q2 | R1 是否允许「显示全部（共 N 条）」展开？ | **允许**（默认 20，展开为本地 slice，不发新请求） | 若严格要求**硬性只显示 20**，则第 21 条起的会话在 UI 里不可达（只能手输 URL 或走 CLI）——需你明确接受该后果 |
| Q3 | R2 在没有图形后端的机器（容器 / 无 `_tkinter` 的 Linux）/ 远程浏览器场景下怎么办？ | 返回稳定不可用原因 + **保留手工输入**（不静默失败）；不做目录浏览 API | 「选择文件夹」只在服务端本职机器有意义；远程访问时按钮应显式说明原因 |

> **裁决方式**：把结论写在本节对应行（追加「裁决：…（日期）」即可），实现时以裁决为准；Q1 未裁决前**不动 R3**。

**执行期默认（2026-09-24，用户「开始执行」后按默认候选落地——未获逐条确认，随时可回退）**：

| # | 执行口径 | 依据 |
|---|---|---|
| Q1 | **用户已裁决（2026-09-24）**：**项目与会话同在一列**（侧栏纵向堆叠），**不做多栏**；并按 **R6 参考 ChatGPT** 布局（限宽居中的阅读列 + 同宽输入条）。第一轮的「会话独立成中栏」实现已**回退**，并用 `test_sidebar_keeps_projects_and_sessions_in_one_column` 把方向钉住（`display: contents` 不得回来） | 用户口述「项目和会话还是放到一列吧」「界面布局参考 chatgpt」 |
| Q2 | **默认 10 条 + 可展开**（本地 slice，不发新请求）；**当前会话永远可见**——它落在窗口外时自动展开并隐藏「展开」按钮（避免「点了没反应」）。若你要的是硬性 10（第 11 条起不可达），删掉展开按钮与 `sessionShowAll` 即可 | 用户口述「会话显示最近的 10 条就好」 |
| Q3 | **保留手工输入 + 明确原因**（`dialog_unavailable`，含服务端原因）；**不做**服务端目录浏览 API | 提名候选即默认 |

## 边界与约束

**Always**

- 排序/截断**不新增事实源**：降序由服务端给定，前端只 `slice`（R1）。
- 原生对话框的拉起必须**不阻塞事件循环**：`asyncio.create_subprocess_exec` + 超时 + 显式终止；argv **硬编码**、禁 `shell=True`、**无任何用户输入进 argv**。
- 对话框返回值只当作**用户输入的一种**：仍走既有 `POST /api/projects` 全套校验（存在 / 是目录 / 规范化 / 上限 / 重复登记）；选择器**不构成权限来源**。
- 该端点复用**既有** `_loopback_error()` 与 Origin 校验；单次在途上限 1（并发请求 → 稳定冲突码）；超时/取消/失败**必须释放名额**并终止子进程。
- 「只读原因可见」仍然成立（UX-DR5）：瘦身只压缩**表达**（面板一行短状态 + 逐项短标签），不静默禁用、不删除原因。
- 页面级安全声明（无认证 / 无 TLS / 非安全边界）与凭证「已配置 / 掩码」显示**保持不变**。
- 测试与验收：新面必须有可复现命令；改动 `app.js`/`index.html`/`styles.css` 后**必须**改行并复跑 18 行真浏览器清单。
- 负向验证：每组守卫都要有「去掉即变红」的变异体实证。
- 本条为新增的**宿主进程拉起面**，必须如实登记进 `docs/frame.md` 五 与活动台账（见 T10）。

**Never**

- 不把「回环来源」「原生弹窗」表述为安全边界（老立场不变：网页入口无认证、无 TLS、须 OS 级沙箱兜底）。
- 不为「简洁」删除**会影响是否生效**的信息（重复键 / 空值键 / BOM / 无效 JSON / 未知键）——只允许**折叠**（默认收起的 `<details>`），不允许丢弃。
- 不在前端硬编码键名/白名单/密码学判断（一律用服务端声明；错误码文案表除外）。
- 不改 `MAX_SESSION_LIST_ENTRIES` 的语义（服务端硬上限 200 保留；UI 的 20 是**展示默认值**，不是新的服务端契约）。
- 不用「对话框返回的路径」跳过注册表校验，也不新增第二套路径规范化。
- 不为测试方便在 UI 暴露「开启写入闸门」之类入口。
- **不把侧栏拆成多栏**（用户 2026-09-24 裁决 = 项目与会话同栏一列）；也**不为「更像 ChatGPT」引入第三方
  CSS / 字体 / 图标库**（严格 CSP + 零第三方资源是既有硬约束，观感靠自身规则做）。
- 不把未跑过的命令写进本 story 的验证段（不伪造未运行命令）。

## 任务（细分）

- [x] **T0** 口径确认：与用户敲定 **Q1 / Q2 / Q3**（写回本节），否则 R3 不动手。
- [x] **T1** R1 实现（UI 侧）：`SESSION_VISIBLE_DEFAULT = 20` 常量 + `renderSessions` 只渲染前 20 +
      「共 N 条 · 显示最近 20 条 / 显示全部」控件；**断言当前选中会话始终可见**（选了第 30 条时自动落在展开态）。
- [x] **T2** R2 服务端：
      ①新增顶层模块 `src/heagent/os_dialogs.py`（**只依赖 stdlib**）：后端探测顺序 `tkinter → powershell → 不可用`，
      经 `asyncio.create_subprocess_exec` 执行**固定脚本**，超时常量（如 300s）+ 终止 + 路径 `is_dir()` 复验 + 脏输出一律按「取消」处理；
      ②`http_console_protocol.py`：加 `DirectoryPickResponse`（`path: str | None` / `cancelled: bool` / `backend: str`）+
      `HttpConsoleHandler.pick_directory()` 协议方法 + 2 个新错误码（`dialog_unavailable` / `dialog_busy`）；
      ③`network/http_server.py`：加 `POST /api/dialogs/pick-directory` 路由（`_loopback_error` 门 + 单在途守卫）；
      ④`cli_http.py`：实现 `pick_directory()`，并加 CLI 选项 `--dialog-backend auto|tkinter|powershell|none`
      （`none` 用于容器/测试与「不可用」路径的确定性验证；**不新增 Settings 字段**）。
- [x] **T3** R2 UI：登记表单加「选择文件夹…」按钮 → 禁用/忙碌态 → 成功填入 `#project-path`（可再手工改）→
      取消/不可用/忙 三路给短提示（UX-DR5 口径：不可用时**说明原因**，手工输入始终可用）。
- [x] **T4** R3 实现（**用户裁决 = 项目与会话同栏一列**；第一轮的「会话独立成中栏」实现已回退）：布局与窄屏降级；
      `data-*` 钩子供探针断言计算样式（**判据用计算样式/盒子，不用 `hidden` 属性**——Z-D15 的教训）。
- [x] **T5** R4 实现：删除 `#settings-gate` 长横幅 → 面板级一行短状态；逐项短只读标签（如「只读：写入未开启」
      /「只读：被系统环境变量覆盖」/「只读：不在可写白名单」）；诊断块与未知键块折进默认收起的 `<details>`
      （有告警/未知键时 summary 显示计数与警示态）；逐项 `notes` 长文案压缩为短标签 + `title`。
- [x] **T6** 测试：
      ①`tests/test_os_dialogs.py`（后端选择顺序 / 固定脚本 / 超时 / 非零退出 / 脏输出 / 路径复验 / 不可用）；
      ②`tests/network/test_http_console_dialogs.py`（**假后端注入**：成功 / 取消 / 不可用 / 单在途 409 / 超时释放名额 /
      非回环 403 且无副作用 / 与项目登记的衔接）；
      ③`tests/js/app_probe.js` + `tests/test_http_web_ui.py` 新增探针用例（R1 截断与展开、R2 三路、R4 无长横幅 + details 折叠）。
- [x] **T7** 真浏览器验收：`tests/js/console_acceptance.mjs` 改行（A5 → 手工输入仍可用 + 按钮存在；新增
      「`--dialog-backend none` 时按钮给原因」与「>20 会话时只渲染 20 + 展开」；A11 改为瘦身后断言）+ 复跑，
      结果写入 `reviews/`（新增或追加验收记录）。
- [x] **T8** 契约测试：`network/` **不得** import `os_dialogs`（依赖方向：入口层才拉起宿主进程）；
      `os_dialogs` 只依赖 stdlib（+ `exceptions`）；`sprint-status.yaml` 状态流转。
- [x] **T9** 文档同步：`docs/frame.md` 4.18 增补「原生目录选择」端点与安全立场（含「回环 ≠ 可信」「弹窗 = 宿主窗口」）、
      五 已知缺口新增条目（宿主进程拉起面 / 无 GUI 后端不可用 / 远程客户端不可用）；
      `docs/README.md` 若有端点索引则同步；`.env.example` **无需**改动（不新增 Settings 字段）。
- [x] **T10** 台账：活动台账新增（或并入既有「控制台」族）条目——「网页请求触发的宿主进程拉起面（弹窗）」
      含触发条件 / 严重度 / 冻结边界与本次实现口径。
- [x] **T11** AC 回写：50-6 的 AC5 表述按 R4 收窄，并在 `stories/50-6-console-ui.md` 与
      `reviews/acceptance-50-6-console-ui.md` 加一行「2026-09-24 由 Story 50-8 调整表述」的注记（不重写其历史记录）。
- [x] **T12** 质量门与负向验证：全量 `pytest`（含覆盖率 ≥ 87%）、`ruff check` / `ruff format --check`、
      `mypy src` + `mypy src --platform linux`；变异体逐条确认变红。
- [x] **T13** R5 实现：
      ①`cli_http.py:334-338` 的事件桥对**读取类工具**（先取 `file_read`；集合用声明式常量表达，并注明这是
      **网页展示策略、非安全边界**）把 `tool_output` 置空——**错误结果不置空**（诊断必需）；
      ②`app.js::showToolResult` 在无内容时渲染「对勾 + 工具名 → 作用对象」（复用既有 `tool_target`，不新增箭头拼接口径）；
      ③探针用例：成功不显示内容 / 失败仍显示消息 / **网页侧收敛不落盘**（断言会话文件与 rollout 仍含全文）/
      CLI 与 GUI 显示不变（对照既有用例）。
- [x] **T14** R5 文档与验收：`docs/frame.md` 4.18 补一句「网页侧工具结果的展示收敛（仅 `file_read`）及其范围
      （不落盘、不影响 CLI/GUI/回放）」；真浏览器清单加一行（读取类工具结果不含内容）。
- [x] **T15** **R6 实现（2026-09-24 追加，用户裁决）**：①侧栏回到**一列**（`.sidebar` 恢复 `display:flex` +
      `flex-direction:column`，并用单测把「`display: contents` 不得回来」钉死）；②ChatGPT 式阅读列
      （`--chat-content-width: 48rem`，`.chat-log > *` 与 `.composer > *` 限宽居中；`--sidebar-width` 300 → 280px）；
      ③R1 阈值 20 → **10**；④真浏览器加 A11d（**1600px 视口**下用计算样式实测限宽与居中——视口不够宽时
      这条判据测不出来）+ 两条单测护栏。

## 验收标准

- **AC1（R1）** Given 某项目有 35 个会话，When 打开侧栏，Then **只渲染最近 10 条**且显示「共 35 条」；
  展开后可见全部 35 条；**已选中的会话在任何截断状态下都可定位**（不因截断而消失或失去选中态）。
- **AC2（R2）** Given 控制台运行在有图形后端的本机且会话来自回环客户端，When 点击「选择文件夹…」并选定一个目录，
  Then 路径被填入既有输入框、随后登记走**既有** `POST /api/projects` 校验链；When 取消，Then 无任何状态变化与副作用。
- **AC3（R2 边界）** Given ①无图形后端（`--dialog-backend none`）、②已有一次选择在途、③非回环来源，
  When 请求选择目录，Then 分别得到 `dialog_unavailable` / `dialog_busy` / `loopback_required`，且
  **不拉起进程、不写文件、不改变注册表**；UI 对不可用情形给出原因并保留手工输入。
- **AC4（R4）** Given 打开项目设置面板，When 面板加载，Then **不出现**那条「服务启动时未开启配置写入（…）」
  长横幅、**不逐项重复**长解释；同时仍可判定每项的只读原因（短标签可见）、凭证仍只显示「已配置 + 掩码」、
  影响生效的信息（重复键 / 空值键 / BOM / 未知键）**折叠可见且带计数**（默认收起，不丢信息）。
- **AC5（R3）** Given **项目与会话同在一列**的侧栏，When 在宽屏与窄屏（≤420px）两种视口查看，Then 两个面板
  **纵向堆叠在同一栏**内（计算样式 `display:flex` / `flex-direction:column`，且不出现 `display:contents` 之类多栏写法）、
  侧栏可收起、安全声明常驻、真实鼠标点击能落到目标控件（用计算样式与命中测试断言）。
- **AC6（无回归）** Given Epic 49/50 既有能力（流式、工具活动、停止、重连、会话 CRUD、配置写入、二次确认、
  来源徽标、常驻安全声明），When 运行全量测试与真浏览器清单（改行后），Then 无行为回归；
  `HTTP_CONSOLE_WRITE_ENABLED` 默认关闭时新增面只读。
- **AC7（错误码）** Given 新增 2 个错误码，When 检查 `app.js::ERROR_TEXT`，Then 枚举驱动用例（由 `HttpErrorCode` 派生）
  通过——**新码必须有可读文案**，缺失即红。
- **AC8（文档与台账）** Given 实现完成，When 检查 `docs/frame.md` 4.18 / 五、台账与 `sprint-status.yaml`，
  Then 新端点、宿主进程拉起面与已知缺口如实登记，本 story 状态与 baseline 正确。
- **AC9（R5）** Given 一次成功的 `file_read` 调用，When 观看网页对话区，Then 该行只显示工具名与文件名 / 作用对象、
  **不出现文件内容**；Given 一次失败的 `file_read`（路径越界 / 文件不存在等），Then **错误消息仍可见**；
  Given 该 run 结束后检查会话文件与 `rollout.jsonl`，Then 工具结果**逐字保留**（网页侧收敛不落盘）；
  Given 同一份事件在 CLI / GUI 上显示，Then 行为与改造前一致（只有网页侧收敛）。
- **AC10（R6 · 2026-09-24 第三轮**用户裁决撤销**）** 原「消息列限宽居中（768px）、输入条同宽且居中」已**作废**，
  由 **AC11** 取代（撤销的理由与实测见下）；该条里「窄屏（≤1000px）单列堆叠不横向溢出」仍然有效。
- **AC11（R7）** Given 1600px 视口，When 查看对话区，Then 消息**铺满该列**（实测 1288px = 该列 1320px −
  两侧内边距 16/16，且两侧余量恰等于内边距而**不是**居中余量）、底部输入条与正文**同宽**；
  Given 打开设置面板（三列），Then **对话列仍是三列里最宽的一列**（实测 812px > 设置面板 508px）。
- **AC12（R8）** Given 项目有 21 个会话（超出 10 条截断），When 查看侧栏会话面板，Then 规模提示与
  「显示全部」位于**会话列表之上**（判据是几何位置，不只看 DOM 顺序）；Given 会话不足 10 条，
  Then 只显示「共 N 个会话」、展开按钮隐藏（不出现「只显示最近 10 条」字样）。
- **AC13（R9）** Given 某项目有 **195** 个会话（提示文字最长的一档），When 查看侧栏会话面板，
  Then 展开/收起按钮**单行**且不越出面板（实测 36px 高、右边界 242 ≤ 面板 242 —— 旧形态为 87×83px、
  右边界 308 越过 280px 侧栏），`共 195 个会话 · 只显示最近 10 条` 在其**下方**（实测 gap 6px，且
  自动展开那句长提示允许换行）；Given 写入闸门关闭，When 打开项目设置面板，Then 只读状态是**跟在项目名
  徽标之后、同一行**的紧凑徽标（实测 `项目设置 ｜ 项目名 ｜ 只读 ｜ 刷新 ｜ 关闭` 全在 y≈112 一行、
  右边界 1327 ≤ 面板 1340），完整原因（`write_channel_short` + `write_channel_disabled`）挂在徽标 `title`；
  **可写项不再各自铺**「只读：未开启配置写入」（实测面板内 `.config-reason` 由 **113 → 67** 条，
  剩下的都是**键自身**的只读原因），可写项仍为不可编辑、开关自身仍无输入框。
- **AC14（R10）** Given 打开项目设置面板，When 看任一条目，Then **值跟在键名之后、同一行**
  （真机实测 `MAX_ITERATIONS` 键 y=1829 / 值 y=1830，纵向重叠且值在键右侧），不再有独占一行的值段落；
  值的展示口径（凭证掩码 `已配置 ********` / 超长截断 / `（未设置）`）与「来源」「凭证」徽标、编辑框一律不变——
  `config-value` 类名保留（验收脚本与面板自测的选择器不用改）。

## Definition of Done

**交付物**：`src/heagent/os_dialogs.py`（新）、`network/http_console_protocol.py` 与 `network/http_server.py` 增量、
`cli_http.py` 增量、`web/{index.html,app.js,styles.css}`、`tests/test_os_dialogs.py`、
`tests/network/test_http_console_dialogs.py`、`tests/js/app_probe.js` 与 `tests/test_http_web_ui.py` 增量、
`tests/js/console_acceptance.mjs`（改行）+ 复跑记录、`docs/frame.md` 4.18/五、活动台账条目、本 story 的
「需求并入区」与 Dev Agent Record。

**验证命令**（实现后按实际输出填写，**不得写未运行的数字**）：

```bash
python -m pytest -q --cov=heagent --cov-fail-under=87
python -m pytest tests/test_os_dialogs.py tests/network/test_http_console_dialogs.py -q
python -m pytest tests/test_http_web_ui.py -q            # 含 node 探针用例
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
node tests/js/console_acceptance.mjs                     # 真浏览器清单（需 Chrome/Edge + heagent[http]）
node tests/js/console_acceptance.mjs --python python --keep   # 保留工作区与截图便于人工比对
```

**负向验证**（每条都要「去掉即变红」）：

① 去掉 picker 端点的回环门 → 非回环用例变红；② 去掉单在途守卫 → 并发用例变红；③ 子进程脏输出不复验
（直接回传 stdout）→ 脏输出用例变红；④ 子进程不设超时 → 超时用例变红（并泄漏进程）；⑤ UI 去掉 20 条截断 →
JS 探针变红；⑥ 截断时不保证「选中会话可见」→ 探针变红；⑦ 把长横幅塞回设置面板 → 探针与真浏览器清单变红；
⑧ 诊断块改为**删除**而非折叠 → 探针变红（断言告警信息仍可见）。

**质量门**：以上全部通过；覆盖率与测试计数取**实测值**写入 Dev Agent Record。

## 代码地图

| 路径 | 角色 | 改动 |
|---|---|---|
| `src/heagent/os_dialogs.py`（新） | 顶层模块，stdlib only | 原生目录选择后端（tkinter / powershell / 不可用）、固定脚本、超时与终止、路径复验 |
| `src/heagent/network/http_console_protocol.py` | 协议模型 + handler 协议 | `DirectoryPickResponse`、`pick_directory()`、2 个新错误码 |
| `src/heagent/network/http_server.py` | 路由与传输层守卫 | `POST /api/dialogs/pick-directory`（回环门 + 单在途） |
| `src/heagent/cli_http.py` | 入口层实现 + CLI 选项 | `HttpProjectConsole.pick_directory()`、`--dialog-backend` |
| `src/heagent/web/index.html` / `app.js` / `styles.css` | 控制台 UI | 20 条截断、选择文件夹按钮、布局调整、设置面板瘦身 |
| `tests/test_os_dialogs.py`（新） | 单测 | 后端选择 / 超时 / 脏输出 / 取消 / 复验 |
| `tests/network/test_http_console_dialogs.py`（新） | 端到端 | 回环门 / 单在途 / 三路结果 / 无副作用 |
| `tests/test_http_web_ui.py` + `tests/js/app_probe.js` | 前端行为探针 | R1/R2/R4 三组用例 |
| `tests/js/console_acceptance.mjs` | 真浏览器验收 | 改行 + 新增行，复跑记录 |
| `docs/frame.md` | 架构权威 | 4.18 增补端点与立场；五 新增缺口 |
| `_bmad-output/implementation-artifacts/deferred-work-archive.md` | 活动台账 | 新增「宿主进程拉起面」条目 + 流水账单行 |

## 风险与未决

- **RK1（原生对话框的环境依赖）**：`tkinter` 在部分 Linux 发行版/容器需单独装 `python3-tk`，无图形后端则完全不可用
  → `auto` 顺序 + `--dialog-backend none` 的确定性不可用路径 + 手工输入常驻兜底；**不得**因为「本机可用」就假定处处可用。
- **RK2（宿主进程拉起面）**：这是 Epic 50 引入的**新面**（此前网页请求不会拉起宿主 GUI 进程）。缓解：回环门 + 单在途 +
  固定 argv + 超时终止；但它**不是安全边界**，必须如实登记（T9/T10）。
- **RK3（弹窗出现在服务端机器）**：若服务被远程客户端访问，窗口出现在**服务机**上；本设计用回环门挡掉远程，
  但「回环 ≠ 可信」（用户自己浏览器里的任意页面 peer 也是 127.0.0.1）——Origin 校验仍是既有防线，文档须写清。
- **RK4（R3 口径误判）**：Q1 三种解释工作量差一个数量级 → 未裁决前不动 R3（T0 前置）。
- **RK5（「瘦身」与信息完整性的张力）**：诊断/未知键是「影响是否生效」的信息，只能折叠不能删；
  AC4 与负向验证⑦⑧就是这条的判据。
- **RK6（真浏览器清单不进 CI）**：与 Z-D15 同构的既有缺口——UI 改动只有清单能证明「真浏览器里也没坏」，
  故 T7 是硬任务；不改「浏览器不进 CI」的立场。

## 需求并入区（后续 Epic 50 新需求统一落这里）

**机制**：新需求按 `R5`、`R6`… **编号追加**，每条须写清 ①来源与日期 ②影响面（API / UI / 文档 / 测试）
③是否改变既有 AC（改变即在本文 AC 段追加一条并注记）④是否需要新的错误码。追加后本 story 状态保持
`ready-for-dev`（已开工则保持 `in-progress`），实现完成再流转 `review`。

| 编号 | 需求 | 来源 | 影响面 | 状态 |
|---|---|---|---|---|
| R1 | 会话列表只显示最近 **10** 条 | 用户口述 2026-09-24 | UI（+ 探针 / 真浏览器清单） | **已实现**（阈值 20 → 10：用户第二轮裁决） |
| R2 | 登记项目改用本机资源管理器选文件夹 | 用户口述 2026-09-24 | API（新端点 + 2 错误码）/ UI / 文档 / 台账 | 已实现（Q3 按默认） |
| R3 | **项目与会话同在一列**（原「会话框尽量往右挪」） | 用户口述 2026-09-24（第二轮改为「放到一列」） | UI（布局 / 样式 / 验收判据） | **已实现**（三栏实现已回退；单测钉住方向） |
| R4 | 项目设置面板瘦身（去长横幅与解释长文案） | 用户口述 2026-09-24 | UI / 50-6 AC5 表述回写 | 已实现 |
| R5 | 读取类工具（`file_read`）的内容不上网页，只显示文件名 | 用户口述 2026-09-24 | 入口层事件桥（`cli_http.py`）/ UI / 探针 / 文档 / 真浏览器清单 | 已实现（范围 = 仅网页侧，不落盘） |
| R6 | **界面布局参考 ChatGPT**（一列侧栏 + 限宽居中阅读列 + 同宽输入条） | 用户口述 2026-09-24（第二轮） | UI（CSS 变量与两条规则）/ 单测护栏 / 真浏览器 A11d | **已实现**，其中「限宽居中阅读列」于 2026-09-24 **第三轮被 R7 撤销**（一列侧栏保留） |
| R7 | **对话区占满所在列**（撤销限宽居中的阅读列；设置面板打开时对话列仍是最宽的一列） | 用户口述 2026-09-24（第三轮「中间一列,显示字的可以宽,占满」） | UI（CSS：删变量与两条限宽规则 + 三列份额）/ 单测护栏 / 真浏览器 A11d | **已实现**（AC10 作废 → AC11） |
| R8 | **会话规模 / 展开控件放到最上面**（原先压在会话列表底下） | 用户口述 2026-09-24（第三轮「最左边的显示全部 要放到最上面」） | UI（`index.html` DOM 顺序）/ 单测护栏 / 真浏览器 A11d | **已实现**（AC12）——本机默认理解为**会话面板最上面**；若你要的是整个左栏最顶部（项目面板之上），一句话即可再挪 |
| R9 | **①会话规模提示与展开按钮纵向堆叠**（按钮一行、`共 N 个会话…` 提示在其**下**，提示允许换行）；**②闸门关闭的只读状态改为「项目名后面的紧凑徽标」**（不再独占一行、也**不再逐项重复**同一句） | 用户口述 2026-09-25（「"只看最近10条"，排版修改，共195个会话显示在它下面」/「"只读：未开启配置写入"不用显示…显示在项目的后面，不独立占一行」） | UI（`index.html` 结构 + `styles.css` 堆叠规则 + `app.js` 徽标）+ `config_catalog.LABELS` + 单测护栏 + 真浏览器 A11b / B1 **几何判据** | **已实现**（AC13；50-6 AC5 的「逐项说明」由本条收窄——原因改在徽标 `title` 里可达） |
| R10 | **配置项的值跟在键名后面（同一行）**，不再另起一行（澄清 R9 待确认项「默认值…不独立占一行」的确切含义） | 用户口述 2026-09-25（同批第二条：「设置中，DEEPSEEK_MODEL 默认的 deepseek-flash 放到 DEEPSEEK_MODEL 后面，不要另外起一行」） | UI（`app.js::renderConfigItem`；`.config-value` 由 `<p>` 降为 `.config-head` 内的 `<span>`）+ 探针判据 + 真浏览器 A11 **几何判据** | **已实现**（AC14；类名保留 ⇒ 既有选择器/判据零改动） |

**候选并入（来自台账，**只引用不复制**；需要时由用户点名并入为 R6…）**：

| 候选 | 台账定位（source_spec） | 严重度 | 备注 |
|---|---|---|---|
| 运行时归因与兜底族（`deadline_reason` 保留 / `tools_in_flight` 不衰减 / SSE 限额先查后加） | 活动台账 · `2026-09-24 Epic 50 收口评审（三镜头）· 运行时归因与兜底族` | 中 | 需新时序测试 |
| 控制台端点同步 I/O（`list_sessions` / `build_config_report` / `registry.list()` / `registry.touch()`） | 活动台账 · `…· 控制台阻塞 I/O 与会话列表成本` | 低-中 | 与 R1 同一片代码，可顺路评估 |
| 非回环运行姿态（`/runs`、会话写操作无回环门；`enable_cron=False` 仍绑 cron 工具面） | 活动台账 · `…· 非回环运行姿态`（**blocked 待人裁决**） | 中 / 中-高 | **须产品/安全口径拍板**，非本 story 可自决 |
| 高影响键的差异化确认（缺后端风险标记） | 活动台账 · `2026-09-24 Story 50-6 实现 · AC7 / UX-DR3` | 低 | 与 R4 同属设置面板体验 |
| 写入通道与保真写四类 low 残余（`.env.lock` 落点 / 回滚文案 / 锁内 I/O / 末行换行约定） | 活动台账 · `2026-09-24 Epic 50 收口评审（第二轮）· …低危残余` | 低 | 有冻结边界，改动需评估 |
| 跨项目并发无全局上限（32 × 1 的乘数关系） | 台账（计划期）+ `ARCHITECTURE-SPINE.md` §6 / §15 D9 | 低-中 | 属已裁定设计的缺口登记 |

## Requirement Traceability

FR-6（网页 UI）；NFR-1, NFR-4, NFR-5, NFR-9, NFR-10, NFR-11, NFR-12；UX-DR1, UX-DR3, UX-DR5, UX-DR6, UX-DR7；
脊柱 §6 / §9；brief §2（场景表）、§9（验收）。

<!-- 实现完成后在同目录追加 Dev Agent Record（Implementation Plan / Completion Notes / 验证 / File List / Change Log），
     并按仓库惯例把 frontmatter 状态改为 review + 记录 baseline_commit。 -->

## Dev Agent Record

### Implementation Plan

1. **先侦察再动手**：story 的「侦察实证」表逐条复核（行号 / 键名 / 能力）。实测新增两条事实：
   ①`file_read` 的失败是**返回值** `Error: ...`（`is_error` 仍为 `False`）——直接决定 R5 的收敛判据；
   ②本机 `.venv` 的 `tkinter` 可 import（`probe_50_8.py`），故 `auto` 后端在本机落 `tkinter`。
2. **服务端（R2）**：新增入口层模块 `cli_dialogs.py`（后端解析 / 冻结脚本 / 单在途 / 超时 kill 回收 / 标记行解析），
   协议加 `DirectoryPickResponse` + `pick_directory()` + 2 个新码，路由 `POST /api/dialogs/pick-directory`
   （复用 `_loopback_error`，POST-only），`cli_http.HttpProjectConsole.pick_directory()`，CLI `--dialog-backend`。
3. **网页桥（R5）**：收敛点选在**入口层事件桥**（`cli_http._web_tool_output`）而非事件源——会话文件 /
   rollout / CLI / GUI 因此一字不变；失败（`is_error` 或 `Error:` 前缀）保留内容。
4. **UI（R1/R2/R3/R4/R5）**：`index.html` 加 5 个元素（选择按钮、会话规模与展开、两个 `<details>`）；
   `app.js` 加 20 条截断 + 自动展开 + 选择文件夹流程 + 工具作用对象回显 + 面板瘦身；
   `styles.css` 用 `.sidebar{display:contents}` 把会话面板提成独立中栏（**不搬 DOM**）。
5. **测试**：`tests/test_cli_dialogs.py`（31 例，假子进程）、`tests/network/test_http_console_dialogs.py`（12 例，
   端点 + 真装配）、`tests/js/app_probe.js` 新增 P/Q/R/S/T 5 个探针 + `tests/test_http_web_ui.py` 新增 6 例、
   `tests/test_http_agent_api.py` 新增 2 例（R5 两半）+ 改强 2 例既有用例、`tests/test_http_security.py` 与
   `tests/network/test_http_protocol.py` 各按新契约更新。
6. **真浏览器验收**：`console_acceptance.mjs` 18 → **22 行**（+A5b / A11b / A11c / B2，`startServer` 支持附加 argv），
   首轮 A11c 变红并**因此改进判据**（见下），复跑 22/22。
7. **负向验证**：`.heagent/tmp/mutate_50_8.py` 11 条变异 **11/11 精确变红**（首轮 M7 未变红 ⇒ 加固探针假文案与
   `gateText` 相等断言后变红，见 Completion Notes）。

### Completion Notes

**与 story 文本的偏离（4 处，均有理由）**

1. **新模块落在入口层 `cli_dialogs.py` 而非顶层 `os_dialogs.py`**：story 的原计划是「顶层模块、只依赖 stdlib」，
   但实现期发现它应当复用仓库既有的子进程内核（`tools.sandbox.process.scrub_sensitive_env` 剥凭证 +
   `reap_subprocess` 有界回收）——**顶层模块不得反向依赖 `tools/`**（依赖 DAG），入口层可以。故改名并落到入口层，
   反而少了一份重复的 kill/回收逻辑。契约断言随之改为「`network/` 不得 import `cli_dialogs`」（网络层只认协议模型）。
2. **R5 的收敛判据比 story 写的多一条**：story 只写「成功结果收敛 / 失败保留」，实测发现内置工具**用返回值
   `Error: ...` 表达可预期失败**（`is_error` 仍 `False`，见 `tools/builtins/file.py`）——若只看 `is_error`，
   「文件不存在」这类诊断会从页面上消失。故加 `_looks_like_a_failure()`（前缀判据，**展示层启发式**，已在
   frame 五 与台账登记「将来改结构化错误时应退化」）。
3. **面板级文案改用新增的 `config_catalog.LABELS["write_channel_short"]`**（原长文案一字未删，改挂 `title`）——
   这样「短状态」仍是**服务端声明**，前端不硬编码第二份文案。50-6 的 AC5 表述按 R4 收窄，已在
   `reviews/acceptance-50-6-console-ui.md` 加注记。
4. **A11c 的判据首轮是瞎的（当场修）**：首轮真浏览器跑出 A11c 红，原因是断言把「重启服务」当成长解释特征——
   它其实是我方**合法**的只读原因标签（监听面键）。改成只盯横幅专属的两句（「网页无法自行开启」「需在启动配置」），
   并把失败时的**上下文**打进报错（下次再红一眼能看出是哪一段文本）。

**关键设计点（供评审复核）**

- **选择器不是权限**：返回值只当作「用户输入的一种」，登记仍走 `POST /api/projects` 全套校验；测试直接断言
  「点选择按钮**不会**产生 `POST /api/projects`」（探针 R 的 `registerCalls == 0`）。
- **单在途归属入口层**：资源在入口层（子进程 + GUI），故名额也由 `DirectoryPicker` 持有；网络层只把
  `dialog_busy` 映射成 409。两条清理路径（超时 / 外层取消）都 kill + 有界回收，各有专门用例。
- **不新增 `Settings` 字段**：超时是模块常量、后端是 CLI 选项 ⇒ `.env.example` 与 `tests/test_config.py`
  的「字段 ⊆ `.env.example`」断言不受影响（也让本 story 不必再动配置面）。
- **三栏不搬 DOM**：`.sidebar{display:contents}` 让两个面板直接参与父网格；收起侧栏 = 隐藏 `.sidebar`
  （`display:none` 作用于 contents 元素会连同子树消失）+ 把前两列收成 0。窄屏用同一条 `[data-*]` 属性还原成
  flex 盒子，故 `aria-controls` / 键盘顺序 / 既有测试选择器全不变。
- **网页侧收敛的边界**：`_WEB_QUIET_TOOLS` 只含 `file_read`（story 原文是「read 命令」）；别的工具与
  失败的读取结果**一律照旧**——探针 T 用 `shell` 断言「既有 `✔ 工具名：输出` 格式不变」。

### 第二轮调整（2026-09-24，用户裁决后）

用户看过第一轮结果后给出三条明确口径，已全部落地（R3/R6 属新增或改向，R1 改阈值）：

| 裁决 | 落地 | 证据 |
|---|---|---|
| **项目与会话放到一列**（撤销第一轮的三栏） | `styles.css` 的 `.sidebar` 恢复 `display:flex` + `flex-direction:column`，删掉 `display:contents` 与 `--sessions-width`；窄屏规则同步还原为原来的两条选择器。**并加护栏**：`test_sidebar_keeps_projects_and_sessions_in_one_column` 断言「`display: contents` 不得出现」+「两个面板都在同一 `<aside>` 内」 | 真浏览器 A11d（`侧栏 flex/column 且项目与会话同栏堆叠`）；变异 M12 精确变红 |
| **会话默认显示最近 10 条**（原 20） | `SESSION_VISIBLE_DEFAULT: 20 → 10`（提示文案与按钮文案由同一个常量派生，自动跟随） | 探针 P（渲染 10 / 「只显示最近 10 条」/ 展开 35）+ 真浏览器 A11b（21 个会话 ⇒ 渲染 10、展开 21）；变异 M14 精确变红 |
| **界面布局参考 ChatGPT** | 新增 `--chat-content-width: 48rem`；`.chat-log > *` 与 `.composer > *` 限宽居中（超宽屏不把正文拉成一行长文）；侧栏宽度 300 → **280px**。护栏：`test_chat_content_is_a_centred_reading_column` + 真浏览器 **A11d**（**1600px 视口**下实测：内容 768px、两侧余量 276/276px、容器 1320px、输入条 768px） | A11d 实测输出；变异 M13 精确变红 |

**一个值得记的坑（判据类的）**：A11d 第一版没有先放宽视口 ⇒ 容器（734px）比阅读列（768px）还窄，
「限宽」根本没触发、「居中」也恒成立——**判据看着绿，其实什么都没证明**。改成先 `Emulation.setDeviceMetricsOverride(1600×900)`
再测量，才真正验到「768px + 两侧相等」。这与 Z-D15 的教训同源：**判据必须落在会失败的条件上**。

### 验证（实测命令 + 输出）

```bash
$ .venv\Scripts\python.exe -m pytest -q --cov=heagent --cov-fail-under=87 --cov-report=term
TOTAL                                          13041    869   3546    392    92%
Required test coverage of 87% reached. Total coverage: 91.88%
3137 passed, 11 skipped, 18 deselected, 8 warnings in 166.80s (0:02:46)

$ .venv\Scripts\python.exe -m pytest tests/test_cli_dialogs.py tests/network/test_http_console_dialogs.py -q --cov=heagent.cli_dialogs
src\heagent\cli_dialogs.py     113      6     34      2    93%   108-110, 123, 127, 165
43 passed in 0.68s

$ .venv\Scripts\python.exe -m ruff check src tests            → All checks passed!
$ .venv\Scripts\python.exe -m ruff format --check src tests    → 280 files already formatted
$ .venv\Scripts\python.exe -m mypy src                         → Success: no issues found in 147 source files
$ .venv\Scripts\python.exe -m mypy src --platform linux        → Success: no issues found in 147 source files
$ .venv\Scripts\python.exe -m heagent http-server --help | findstr dialog-backend
  --dialog-backend [auto|tkinter|powershell|none]

$ node tests/js/console_acceptance.mjs --python E:/AI/HeAgent/.venv/Scripts/python.exe
ACCEPTANCE {"rows":23,"failed":0,"workspace":"…\\heagent-console-1scRxK","chrome":"Chrome/153.0.8010.48"}
# A11b: 共 21 个会话：默认渲染 10 条（「共 21 个会话 · 只显示最近 10 条」），展开后 21 条全部可见
# A11d: 侧栏 flex/column 且项目与会话同栏堆叠（1600px 视口）；对话列 768px 居中（两侧 276/276px，容器 1320px）；输入条 768px

$ .venv\Scripts\python.exe .heagent/tmp/probe_50_8_dialog_real.py     # 真机：真实拉起 tkinter 窗口，2s 后 kill
resolve_backend('auto') = tkinter
result=None elapsed=2.0s in_flight(after)=False
stderr: directory dialog timed out after 2s; treated as cancelled

$ .venv\Scripts\python.exe .heagent/tmp/mutate_50_8.py               # 负向验证
合计 14 条变异，未变红 0 条：[]
```

### 第三轮调整（2026-09-24，用户裁决：R7 / R8）

用户看过第二轮结果后给出口径：「中间一列，显示字的可以宽，占满；最左边的显示全部 要放到最上面」。
按本文「需求并入区」机制记为 **R7 / R8**，并把 **R6 的限宽居中阅读列撤销**（AC10 作废 → AC11）：

| 裁决 | 落地 | 证据 |
|---|---|---|
| **对话区（显示字的那一列）占满，不再限宽居中** | `styles.css`：删 `--chat-content-width` 与 `.chat-log > *` / `.composer > *` 两条 `max-width + margin-inline:auto`（只留 `width:100%`）；设置面板打开时的三列份额由 `1.05fr / 1.2fr`（对话列**比设置面板窄**）改为 `1.6fr / 1fr`（对话列最宽） | 真浏览器 A11d（**1600px 视口**）：正文 **1288px** = 该列 1320px − 内边距 16/16（旧口径只有恒定的 768px）、输入条同为 1288px；设置面板打开时对话 **812px > 设置 508px** |
| **会话规模 / 「显示全部」放到最上面** | `index.html`：`#session-count` + `#session-more` 那一行由 **`ul#session-list` 之后**移到**面板标题之下、列表之前**（纯 DOM 顺序调整，无 JS 改动） | 真浏览器 A11d：`显示全部` 底边 **687** ≤ 会话列表顶边 **740**；单测 `test_session_scale_controls_sit_at_the_top_of_the_sessions_panel`；变异 M15 精确变红 |
| **口径护栏（三条新单测）** | `test_chat_content_fills_the_column`（`--chat-content-width` 不得回来 + 两条规则不含 `max-width`）、`test_settings_open_keeps_the_chat_column_the_widest`（解析三列 fr 份额并比较）、`test_session_scale_controls_sit_at_the_top_of_the_sessions_panel`（面板内相对顺序） | 变异 M13 / M16 / M17 各自精确变红 |

**一处判据细节（当场踩到）**：`test_chat_content_fills_the_column` 的「变量不得出现」断言一开始被**我自己的 CSS 注释**
（写着「R6 的 `--chat-content-width` 已撤销」）判红 ⇒ 新增 `_css_without_comments()`，注释不再参与口径判据
（否则一条解释性注释就能让护栏假红）。

**一处取舍需你确认（R8 的「最上面」）**：本机默认把「最上面」落成**会话面板的最上面**（列表之上）——那个控件
属于会话列表，放到项目面板之上会造成「会话控件挂在项目区」的错位。若你要的是**整个左栏最顶部**，把那一整块
`<div class="row">` 移到 `<section aria-labelledby="projects-heading">` 之前即可（A11d 的几何断言会同步证明位置）。

### 验证（第三轮复跑，实测命令 + 输出）

```bash
$ .venv\Scripts\python.exe -m pytest -q --cov=heagent --cov-fail-under=87 --cov-report=term --no-header -p no:randomly
Required test coverage of 87% reached. Total coverage: 91.88%
3139 passed, 11 skipped, 18 deselected, 8 warnings in 169.73s (0:02:49)

$ .venv\Scripts\python.exe -m ruff check src tests            → All checks passed!
$ .venv\Scripts\python.exe -m ruff format --check src tests    → 280 files already formatted
$ .venv\Scripts\python.exe -m mypy src                         → Success: no issues found in 147 source files
$ .venv\Scripts\python.exe -m mypy src --platform linux        → Success: no issues found in 147 source files

$ node tests/js/console_acceptance.mjs --python E:/AI/HeAgent/.venv/Scripts/python.exe
ACCEPTANCE {"rows":23,"failed":0,"workspace":"…\\heagent-console-T5HOUf","chrome":"Chrome/153.0.8010.48"}
# A11d: 687 ≤ 740（控件在列表之上）；设置面板打开时对话 812px > 设置 508px；
#       1600px 视口下侧栏 flex/column 且项目与会话同栏堆叠、对话正文 1288px（= 该列 1320 − 内边距 16/16）、输入条 1288px

$ .venv\Scripts\python.exe .heagent/tmp/mutate_50_8.py
合计 17 条变异，未变红 0 条：[]
```

### 第四轮调整（2026-09-25，用户裁决：R9）

用户原文：①「"只看最近10条"，排版修改，共195个会话显示在它下面」②「"只读：未开启配置写入"不用显示，
显示在项目的后面，不独立占一行」。按「需求并入区」机制记为 **R9**，并把 **50-6 AC5 的「逐项说明」收窄**（新 **AC13**）。

**先量后改（`.heagent/tmp/ui_layout_probe.mjs`：真实 headless Edge + CDP，临时工作区里 195 个会话）**

| 靶点 | 旧形态（实测） | 新形态（实测） |
|---|---|---|
| 会话面板两个控件 | **并排**（`.row` + `justify-content: space-between`）：`.status` 是 `white-space: nowrap` ⇒ 提示不可收缩，按钮被挤成 **87×83px / 约 3 行**，右边界 **308px 越过 280px 侧栏**；提示盒子（y 507–527）**套在按钮盒子**（y 476–558）里面 | **纵向堆叠**（`.session-scale`）：按钮 **220×36px / 单行**（`align-items: stretch` 吃满面板宽度）、右边界 **242 = 面板右边界**；提示在其下 **6px**，`white-space: normal` ⇒ 自动展开那句长提示可换行 |
| 设置面板只读状态 | 面板级**独占一行**的块 `未开启配置写入：可写项在本页只读`（364×39px、y≈187）+ **逐项** `只读：未开启配置写入`（面板内 `.config-reason` = **113** 条） | 项目名后面**同一行**的紧凑徽标 `只读`（45×23px，与项目徽标同在 y≈112）；`.config-reason` → **67** 条（剩下的全是**键自身**的只读原因） |

**为什么徽标只能是「只读」两个字（宽度算术 + 实测）**：设置列内容宽 **364px**，`项目设置`(64) + 项目名徽标(96) +
`刷新`(61) + `关闭`(61) + 4 个间隙(32) 已占 **314px**；那句短状态需 ~205px ⇒ **必然换行**（`.settings-head`
是 `flex-wrap: wrap`，会把「刷新/关闭」挤到第二行——那还是「独占一行」）。故徽标显示 `只读`，
**完整原因（短状态 + 长解释）挂 `title`**（沿用 R4「降噪不丢信息」口径）；文案走服务端
`LABELS["write_channel_badge"]`（前端只做缺失兜底，不硬编码中文）。

**一处口径变更（需你知悉）**：50-6 的 **AC5** 原文要求「所有可写项…**说明**『服务启动时未开启配置写入』」。
R9 之后**可写项不再逐项说明**（同一句在 400+ 项的面板上重复纯属噪音），改为**面板级说一次**（项目名后的徽标 +
`title` 里的完整原因），逐项仍保持**不可编辑**。若你希望逐项留一个两字小标记，一句话即可加回。

**同批追问已澄清（→ R10）**：原文里「**默认值**」三字当天已问清——指的是**值那一行**（原话：「设置中，
DEEPSEEK_MODEL 默认的 deepseek-flash 放到 DEEPSEEK_MODEL 后面，不要另外起一行」）。落地见下 **R10**。

#### R10（同批第二条）：配置项的值跟在键名后面

`app.js::renderConfigItem` 里值由**独立的 `<p class="config-value">` 一行**改为**塞进 `.config-head` 的
`<span class="config-value">`**（顺序：**键 → 值 → 来源徽标 → 凭证徽标**），每个条目少一行。要点：

- **类名保留，只换标签**：验收脚本（`row.querySelector(".config-value")`）与面板自测的选择器、判据**零改动**；
  为免以后又有人靠「第几个子节点」取值，本轮顺手把探针里所有位置型判据（`children[1]` / `children[2]`）
  换成了 `findByClass`。
- **几何判据进真浏览器清单**（A11）：`键` 与 `值` 两个 rect 必须纵向重叠且值在键右侧（实测键 y=1829 / 值 y=1830）；
  这条能抓住「值又跑回下一行」——单测里的 DOM 结构断言抓不到观感。
- 值的展示口径一字未改（掩码 / 截断 / `（未设置）`）；`.config-value` 的 `white-space: pre-wrap` 保留，
  JSON 值（`ROUTING_POOLS`）里的换行照旧，长值靠 `overflow-wrap: anywhere` 断行。

**验证（R10，实测命令 + 输出）**

```bash
$ .venv\Scripts\python.exe -m pytest tests/test_http_web_ui.py -q
137 passed in 2.31s                      # +1（test_config_value_sits_on_the_key_line）

$ .venv\Scripts\python.exe -m pytest -q --cov=heagent --cov-fail-under=87 --cov-report=term --no-header -p no:randomly
Required test coverage of 87% reached. Total coverage: 91.87%
3142 passed, 11 skipped, 18 deselected, 8 warnings in 169.72s (0:02:49)

$ node tests/js/console_acceptance.mjs --port 8923 --python E:/AI/HeAgent/.venv/Scripts/python.exe
ACCEPTANCE {"rows":23,"failed":0,"workspace":"…\\heagent-console-JIb9dS","chrome":"Chrome/153.0.8010.48"}
# A11：… / 值内联（键 y=1829、值 y=1830）

$ .venv\Scripts\python.exe .heagent/tmp/mutate_50_8.py
合计 23 条变异，未变红 0 条：[]      # R10 的 M23「值退回另起一行的 <p>」精确变红（2 failed）
```

#### 第四轮（R9）文件清单

#### 验证（第四轮，实测命令 + 输出）

```bash
$ node .heagent/tmp/ui_layout_probe.mjs http://127.0.0.1:8955/      # headless Edge 153 + CDP
# 旧：more={x:221,y:476,w:87,h:83,right:308}、count={y:507,h:20}(嵌在按钮盒内)、reasonCount=113(含「只读：未开启配置写入」)
# 新：more={x:22,y:476,w:220,h:36,right:242}、count={y:518,h:20,whiteSpace:normal}(gap 6)、reasonCount=67
#     设置头一行：项目设置 968–1032 ｜[ui_layout_ws] 1040–1137 ｜[只读] 1145–1190 ｜ 刷新 1198–1259 ｜ 关闭 1267–1327（≤ 面板 1340）

$ .venv\Scripts\python.exe .heagent/tmp/venv_asset_probe.py         # 核准验收跑的确实是工作区前端
package: E:\AI\HeAgent\src\heagent\__init__.py；resources → E:\AI\HeAgent\src\heagent\web（index.html 7943 字节）

$ .venv\Scripts\python.exe -m pytest tests/test_http_web_ui.py -q
136 passed in 2.00s

$ .venv\Scripts\python.exe -m pytest -q --cov=heagent --cov-fail-under=87 --cov-report=term --no-header -p no:randomly
Required test coverage of 87% reached. Total coverage: 91.88%
3141 passed, 11 skipped, 18 deselected, 8 warnings in 165.54s (0:02:45)

$ .venv\Scripts\python.exe -m ruff check src tests            → All checks passed!
$ .venv\Scripts\python.exe -m ruff format --check src tests    → 280 files already formatted
$ .venv\Scripts\python.exe -m mypy src                         → Success: no issues found in 147 source files
$ .venv\Scripts\python.exe -m mypy src --platform linux        → Success: no issues found in 147 source files

$ node tests/js/console_acceptance.mjs --port 8922 --python E:/AI/HeAgent/.venv/Scripts/python.exe
ACCEPTANCE {"rows":23,"failed":0,"workspace":"…\\heagent-console-f61eX3","chrome":"Chrome/153.0.8010.48"}
# A11b：共 21 个会话：默认渲染 10 条（「共 21 个会话 · 只显示最近 10 条」），展开后 21 条全部可见；按钮 36px/单行、提示在其下 6px
# B1  ：项目名后「只读」徽标（title 含完整原因）、0 个可编辑控件、46 个可写项无逐项重复、开关自身只读（无输入框）

$ node tests/js/console_acceptance.mjs --port 8919      # 负向：先把会话控件 revert 回并排
ACCEPTANCE {"rows":23,"failed":1,…} → A11b「规模提示必须在展开按钮**下面**（R9）：{"moreHeight":36,"moreLines":1,"moreRight":712,"panelRight":724,"stacked":false,"gap":-28}」

$ .venv\Scripts\python.exe .heagent/tmp/mutate_50_8.py
合计 22 条变异，未变红 0 条：[]      # 原 17 条 + R9 的 M18–M22
# M18 会话控件退回并排、M19 堆叠改横排、M20 闸门退回独占一行、M21 徽标丢 title、M22 逐项原因加回 —— 5/5 精确变红
```

**判据细节（当场踩到）**：真浏览器几何断言最初用「按钮盒高 ÷ 行高 > 1.5 行 ⇒ 折行」判据，
结果把**正常的单行按钮**（36px = 11.2px padding + 23.25px 行高）判成 1.6 行而误报 ⇒ 改为
**内容盒高度**（盒子高 − padding − border）÷ 行高，才是一条不会撒谎的判据。

#### 第四轮（R9）文件清单

| 路径 | 变更 |
|---|---|
| `src/heagent/web/index.html` | 会话面板那两个控件换成 `.session-scale` 容器（按钮在前、提示在后）；`#settings-gate` 由 `<p class="notice">`（独占一行）改为 `.settings-head` 里的 `<span class="badge badge-gate" data-state="warning">`（项目名之后） |
| `src/heagent/web/styles.css` | 新增 `.session-scale`（纵向堆叠 + `align-items: stretch` + gap）与 `.session-scale #session-count { white-space: normal }`；新增 `.badge-gate { border-color: var(--warn) }`；**R10**：`.config-value` 注释改写（说明它现在是头部行内的 `<span>`），规则本身不变 |
| `src/heagent/web/app.js` | 闸门徽标：文案取 `labels.write_channel_badge`（兜底「只读」）+ `title` 拼（短状态 + 长解释）；可写项**不再** append `config-reason`；**R10**：值由独立 `<p class="config-value">` 改为 `.config-head` 内的 `<span class="config-value">`（键 → 值 → 来源 → 凭证） |
| `src/heagent/config_catalog.py` | `LABELS` +`write_channel_badge`（附「宽度是硬约束」的注释）；`write_channel_short` 的注释随 R9 改写（逐项那份重复已撤） |
| `tests/test_http_web_ui.py` | 改 `test_session_scale_controls_sit_at_the_top_of_the_sessions_panel`（顺序倒过来）；+`test_session_scale_controls_stack_and_let_the_hint_wrap`、+`test_write_gate_is_an_inline_badge_right_after_the_project_name`；两条探针用例改判据（`gateText/title` + 逐项原因计数）；**R10**：+`test_config_value_sits_on_the_key_line`、H 用例加 `valueInsideHead` 断言 |
| `tests/js/app_probe.js` | 探针 G / S 改判据：`gateText` / `gateTitle` / `gateReasonParagraphs` / `writableRowReasonParagraphs`（去掉 `reasonText` / `gatedReasonText`）；**R10**：位置型判据（`children[1]` / `children[2]`）全换成 `findByClass`，+`valueInsideHead` / `headClasses` / `valueText` |
| `tests/js/console_acceptance.mjs` | A11b 加**真实几何**判据（单行 / 不越界 / 提示在其下）；B1 改判据（徽标在项目名之后同一行 + title 可达 + 可写项无逐项原因）；**R10**：A11 加「键与值必须同一行且值在键右侧」的几何判据 |
| `.heagent/tmp/mutate_50_8.py` | M15 锚点随 R9 更新（否则锚点命中 0 次）；M7 锚点更新；+M18–M22；**R10**：+M23「值退回另起一行的 `<p>`」 |
| 本 story | 需求并入区 +R9/R10、AC +AC13/AC14、本轮记录 |

### File List

**新增**

| 路径 | 行数 | 说明 |
|---|---|---|
| `src/heagent/cli_dialogs.py` | 约 250 | 原生目录选择（后端解析 / 冻结脚本 / 单在途 / 超时 kill 回收 / 标记行解析） |
| `tests/test_cli_dialogs.py` | 约 250 | 31 例：后端选择 / spawn 纪律 / 解析 / 单在途 / 超时与取消清理 / 冻结脚本可编译 |
| `tests/network/test_http_console_dialogs.py` | 约 220 | 12 例：端点层（状态码 / 回环门 / POST-only / 路由缺席）+ 真 console 装配（成功 / 取消 / 503 / 409 / 无副作用） |
| `_bmad-output/epics/epic-50-网页控制台周期/reviews/acceptance-50-8-refinement.md` | 114 | 22 行真浏览器清单 + AC 覆盖 + 真机探针 + 11 条变异 + 质量门 + 已知缺口 |

**修改**

| 路径 | 说明 |
|---|---|
| `src/heagent/network/http_protocol.py` | +2 错误码（`dialog_unavailable` / `dialog_busy`）+ 分组文档 |
| `src/heagent/network/http_console_protocol.py` | +`DirectoryPickResponse` + `ConsoleHandler.pick_directory()` + `__all__` |
| `src/heagent/network/http_server.py` | +`_DIALOG_PICK_PATH` 路由常量与端点（`_loopback_error` + POST-only）+ `_CONSOLE_ERROR_STATUS` 两条映射 |
| `src/heagent/cli_http.py` | +`cli_dialogs` 接线 / `dialog_backend` 参数 / `pick_directory()` / `--dialog-backend` 选项 / R5 `_web_tool_output` 事件桥 |
| `src/heagent/config_catalog.py` | +`LABELS["write_channel_short"]`（面板级短状态；原长文案保留） |
| `src/heagent/web/index.html` | +`project-pick` / `session-count` / `session-more` / 两个 `<details>`（诊断、未知键）；**第三轮**：`session-count` + `session-more` 那行移到会话面板最上面（R8） |
| `src/heagent/web/app.js` | R1 20 条截断与自动展开 / R2 选择文件夹流程 / R3 事件无关 / R4 面板瘦身 / R5 作用对象回显 / +2 错误码文案（R7/R8 无需改 JS） |
| `src/heagent/web/styles.css` | R3 三栏与窄屏还原 + `.settings-details` / `.badge-note`；**第三轮**：撤销 `--chat-content-width` 限宽居中（R7）+ 三列份额 `1.05/1.2fr` → `1.6/1fr` |
| `tests/js/app_probe.js` | LABELS 补 `write_channel_short`（且 `write_channel_disabled` 用全量长文案）+ 路由 + 探针 P/Q/R/S/T + 两个 helper |
| `tests/js/console_acceptance.mjs` | 18 → 22 行（A5b / A11b / A11c / B2）+ `startServer` 支持附加 argv + B1 加「无长句」断言；**第三轮**：A11d 改判据（改为「占满该列 + 控件在列表之上 + 三列里对话最宽」，并显式 `open()` 回主控制台取证） |
| `tests/test_http_web_ui.py` | +6 例（`TestConsoleRefinement`）+ 元素清单补 5 个 id + `gateText` 相等断言；**第三轮**：`test_chat_content_is_a_centred_reading_column` → `test_chat_content_fills_the_column`（R7 护栏）+ 新增 `test_settings_open_keeps_the_chat_column_the_widest`（R7）与 `test_session_scale_controls_sit_at_the_top_of_the_sessions_panel`（R8）+ `_css_without_comments()` |
| `tests/test_http_agent_api.py` | +2 例（R5 两半：内容不进网页 / 模型仍读到）+ 改强既有工具事件用例（读真实文件并断言内容不出现在帧里） |
| `tests/test_http_security.py` | `_StubProvider` 记录消息；「工具输出不进日志」用例改为「日志 / 网页帧都没有，但模型拿到」 |
| `tests/network/test_http_protocol.py` | 错误码集合断言 +2 |
| `docs/frame.md` | 4.18（+3 行 / 错误码 32→34 / 安全声明段补宿主弹窗面）、五（+3 行缺口）、七（控制台调用链 +1 段） |
| `_bmad-output/implementation-artifacts/deferred-work-archive.md` | 活动区 14 → 16 条（+A15 / A16）+ 流水账单行 |
| `_bmad-output/consolidated-overview.md` | §17.3 / §17.4-A 计数 14 → 16 与 A15 / A16 两行、文档地图行 |
| `_bmad-output/epics/epic-50-网页控制台周期/epics.md` | Story 50.8 段补 R5 摘要与 DoD 行 |
| `_bmad-output/sprint-status.yaml` | `50-8-console-ux-refinement: ready-for-dev → review` |
| `_bmad-output/epics/epic-50-网页控制台周期/reviews/acceptance-50-6-console-ui.md` | 追加「AC5 表述由 Story 50-8 收窄」注记 |
| 本 story | frontmatter（status / baseline_commit）+ 执行期默认表 + 15 个任务勾选 + 本记录 |

### Change Log

| 日期 | 变更 |
|---|---|
| 2026-09-24 | 实现 Story 50-8（R1–R5）：新增 `cli_dialogs.py` 与 `POST /api/dialogs/pick-directory`（回环门 + 单在途 + 超时 kill，2 个新错误码）、网页侧 `file_read` 结果收敛、会话列表 20 条截断、三栏布局、设置面板瘦身；全量 **3135 passed / 覆盖率 91.87%**、ruff / format / mypy 双平台干净、真浏览器清单 **22/22**、**11/11** 变异精确变红；真机探针验证 tkinter 子进程可拉起并可被超时终止 |
| 2026-09-24 | **第二轮调整（用户裁决）**：项目与会话**回到一列**（撤销三栏 + 加口径护栏）、会话默认 **10** 条、布局**参考 ChatGPT**（新增 `--chat-content-width` 限宽居中阅读列与同宽输入条，侧栏 300 → 280px）；真浏览器清单 22 → **23 行**（+A11d，1600px 视口实测）、变异 11 → **14 条**（+M12/M13/M14，全红）；全量 **3137 passed / 91.88%** |
| 2026-09-24 | **第三轮调整（用户裁决 R7/R8）**：对话区**撤销限宽居中、改为占满所在列**（并让设置面板打开时对话列仍最宽：三列份额 `1.05/1.2fr` → `1.6/1fr`）、**会话规模与「显示全部」移到会话面板最上面**；AC10 作废 → 新增 **AC11/AC12**；`test_http_web_ui.py` 134 例（+3 护栏、-1 旧阅读列护栏）、变异 14 → **17 条**（M13 改写为「把限宽加回来」、+M15/M16/M17，17/17 全红）；真浏览器 A11d 改判据后 **23/23**（正文 1288px = 该列 1320 − 16/16；三列里对话 812 > 设置 508；控件 687 ≤ 列表 740）；全量 **3139 passed / 91.88%**、ruff / format / mypy 双平台全绿 |
| 2026-09-25 | **第四轮调整（用户裁决 R9）**：①会话面板两个控件**纵向堆叠**（按钮在上、规模提示在其下、提示允许换行）——并排时 `.status` 的 nowrap 把按钮挤成 **87×83px / 3 行**且右边界 **308px 越过 280px 侧栏**（真机实测）；②闸门关闭的只读状态改为**项目名后面的紧凑徽标 `只读`**（`title` 里是完整原因），**可写项不再逐项铺**同一句（面板内 `.config-reason` **113 → 67** 条）；新增 **AC13**、`LABELS["write_channel_badge"]`；真浏览器 A11b/B1 加**几何判据**后仍 **23/23**（负向跑：旧布局下 A11b 精确变红 `stacked:false, gap:-28`）、变异 17 → **22 条（22/22 全红）**；全量 **3141 passed / 覆盖率 91.88%**、ruff / format / mypy 双平台全绿 |
| 2026-09-25 | **第四轮补充（用户裁决 R10，与 R9 同批的第二条）**：**配置项的值跟在键名后面、同一行**（`.config-value` 由独立 `<p>` 降为 `.config-head` 内的 `<span>`，顺序 键 → 值 → 来源 → 凭证），每个条目少一行；新增 **AC14**；真浏览器 A11 加「键与值同一行」的**几何判据**（实测键 y=1829 / 值 y=1830）；顺手把探针里所有位置型判据（`children[1]`/`children[2]`）换成 `findByClass`；变异 22 → **23 条（23/23 全红）**；全量 **3142 passed / 覆盖率 91.87%**、真浏览器 **23/23**、ruff / format / mypy 双平台全绿 |
