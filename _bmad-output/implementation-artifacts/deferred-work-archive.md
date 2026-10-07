# Deferred Work——活动条目 + 闭合归档

> 本文件自 2026-09-17 起承接两类条目（原活动台账 `deferred-work.md` 已删除，用户裁定）：
> ① **活动（未闭合）条目**——工作流的 append-only 入口，闭合后按归属 epic 归档至各周期
> `deferred-work.md`（勘察类留在本文件，索引见 `consolidated-overview.md` 13.1）；
> ② **闭合归档**——正文分两处落（2026-09-24 起）：**勘察类**（source_spec 为勘察批次、无归属 epic）留在本文件；**有归属 epic 的**按规则回填到各周期 `deferred-work.md`（`Z-D10` / `Z-D11` → [`epic-48-TCP网络接口周期/deferred-work.md`](../epics/epic-48-TCP网络接口周期/deferred-work.md)，`Z-D13`~`Z-D15` → [`epic-50-网页控制台周期/deferred-work.md`](../epics/epic-50-网页控制台周期/deferred-work.md)）。本文件仍登记**全部 `Z-Dn` 的 ID 索引**（见下状态总览），但不保留已回填条目的正文副本。

> **维护规则**：活动区是唯一的未闭合条目正文；总览与回顾只保留编号和链接。新增条目按末尾追加，闭合时保留 ID、补充 Resolution/证据，并将有明确归属的正文移入对应周期 `deferred-work.md`。`blocked` 表示需要产品或架构决策，不能由实现者自行关闭。

## 活动（未闭合）条目——9 条

> **流水账单**（每次新增 / 闭合都往下接一行；本区**只留未闭合条目**——条目一闭合即连同正文移入下方「勘察类闭合归档」，不在本区留副本）
>
> - 2026-09-17：自活动台账 `deferred-work.md` 迁入 6 条
> - 2026-09-18：闭合 2 条 → Z-D8 / Z-D9
> - 2026-09-22：架构优化周期新增 2 条（本文旧编号 A7 / A8，现按下列顺序编号）
> - 2026-09-23：Epic 48 收口新增 3 条，其中「运行栈日志非观测故障免疫」「入口日志未脱敏」同日随可观测性与日志卫生批次闭合 → Z-D10 / Z-D11；代码评审新增 1 条，同日以 fail-soft 闭合 → Z-D12
> - 2026-09-24：Epic 50 规划评审新增 1 条（跨项目并发无全局上限——D9 采纳后的已知缺口，计划期登记，待 Epic 50 实现后复核）；Epic 50 收口评审新增 3 条（运行时归因与兜底族 / 控制台阻塞 I/O 与会话列表成本 / 非回环运行姿态**待裁决**；报告 `epics/epic-50-网页控制台周期/reviews.md#review-epic-50-implementation`）
> - 2026-09-24：Story 50-5 实现新增 2 条（写通道可把无上界的「资源旋钮」键设成极端值 / 审计文件无保留期上限），同日闭合 → Z-D13 / Z-D14；Story 50-6 实现新增 2 条（浏览器级 UI 验收不在 CI 且不含真实 LLM 运行 / 「高影响键的差异化确认」缺后端风险标记）；Story 50-6 收口后由用户实测发现并当日修复 1 条（首页加载即弹出关不掉的确认遮罩，`.overlay{display:flex}` 压过 `hidden` 属性）→ Z-D15；Epic 50 收口评审（第二轮）新增 1 条（写入通道与保真写的四类低危残余；报告 `epics/epic-50-网页控制台周期/reviews.md#review-epic-50-closure`）
> - 2026-09-24：**整理**——删除 5 条已闭合条目在本区的副本（Z-D10 / Z-D11 / Z-D12 / Z-D13 / Z-D14），正文并入下方同名小节（**Z-D12 小节此前缺失**，本次由副本改写补建）
> - 2026-09-24：**回填**——`Z-D10` / `Z-D11`（Epic 48）与 `Z-D13` / `Z-D14` / `Z-D15`（Epic 50）的**正文**按「归属 epic」移入各自周期 `deferred-work.md`（本文件只留 ID 索引，不再留副本）
> - 2026-09-24：**Story 50-8（Epic 50 收口后的体验优化轮）实现新增 2 条**——①「网页请求可拉起宿主 GUI 进程」的新暴露面（弹窗，有意引入，含不可用环境与「回环 ≠ 可信」口径）；②真实原生窗口的验收不可自动化 + 网页侧读取结果收敛所依赖的 `Error:` 前缀判据是展示层启发式。报告与实测见 `epics/epic-50-网页控制台周期/reviews.md#acceptance-50-8-refinement`
> - 2026-09-26：**Story 50-8 的收口后评审（增量轮）新增 2 条**（均为 `intent_gap / blocked 待人裁决`）——① R5 的收敛判据对「正文以 `Error:` 开头的文件」失效（AC9 两句话在该输入类上互斥）；②「共 N 个会话」在 N > 200 时静默少报（服务端硬上限截断且协议无 `total`）。报告见 `epics/epic-50-网页控制台周期/reviews.md#review-epic-50-story-50-8`；同轮就地修复 4 处判据/口径（含 AC13 的 195 档进可复跑清单），负向验证 5/5 精确变红
> - 2026-09-26：**Epic 50 收口后第四轮评审**（对 HEAD 全量复核：`pytest` 3144 passed / 覆盖率 92% / ruff·mypy 双平台全绿 均为亲跑；报告 `epics/epic-50-网页控制台周期/reviews.md#review-epic-50-round4`）**新增 5 条**——① 会话 id 放行 Windows 保留设备名（`--resume NUL` 读成空历史、`save` 写向空设备 ⇒ 整段对话静默丢弃；既有）；② `.heagent/sessions/<id>.json.lock` 无回收方（`prune` 只认 `.json`）；③ 同一会话文件的两个写者（CLI 与内嵌网页共享同一 cwd 工作区）**整份覆盖**对方历史（**中**，静默数据丢失）；④ 诊断「N 条需要注意」把信息性 note 计入告警且 BOM 一事双计（`intent_gap`）；⑤ `*_BASE_URL` 等非后缀载体的值原样回显（掩码域 = `_API_KEY(S)` 后缀；`intent_gap`，文档口径同轮已补）。同轮**就地修复 2 处并带负向验证**：跨项目配置写入（`web/app.js` 面板归属守卫——无修复时桩实测 `writeCalls=1`，把 A 的未保存改动写进 B 的 `.env`）、会话 id 正则 `$`→`\Z`（两处同源校验，尾随 `\n` 实测被双放行）
> - 2026-09-27：**闭合 1 条 → Z-D17**（会话 `.json.lock` 无回收方）——`persist.reap_dangling_locks`（三条判据：同名记录不存在 + mtime 超限 + 非阻塞加锁证明无人持有）接入 `SessionStore.prune`；同时修正 `persist` 里「过期 `.lock` 由各自 prune 随记录一并回收」那句对 sessions 不成立的注释；变异体 **4/4 精确变红**，全量 3183 passed；**残余**：Windows 先 close 再 unlink 的 µs 级窗口（如实记录，彻底消除需改锁的落点协议）
> - 2026-09-27：**续修 1 条（第二轮）**——「控制台阻塞 I/O 与会话列表成本」补齐其余落点（`build_config_report` / `registry.touch` / `list_projects` 的注册表读 / dream 会话预注入），并把 >1 MiB 会话改为**有界头部读**（列表不再整份读入）；新增 6 例线程身份用例，变异体 **5/5 精确变红**，全量 3179 passed；唯一残余 = `_runtime_for` 每请求一次注册表读（已量化、有意保留，升级条件写在条目里）
> - 2026-09-27：**部分闭合 1 条（第一轮）**——同一「控制台阻塞 I/O 与会话列表成本」的**会话读**三处离线到 `asyncio.to_thread`（含 `start_project_run` 前的会话解析）+ 线程身份回归用例（负向验证 1 failed → 恢复 101 passed，全量 3154 passed）
> - 2026-09-27：**证据路径刷新**（对照 `src/` 实测）——活动条目里 2026-09-26 包化重构前的路径（`cli_http.py` / `cli.py` / `cli_dialogs.py` / `config_catalog.py` / `config_write.py` / `envfile.py` / `persist.py` / `config.py`）与逐点行号更新为现名现址；同步 `epics/epic-50-网页控制台周期/deferred-work.md` 的 Z-D13 / Z-D14 两处
> - 2026-09-27：**闭合 1 条 → Z-D16**（会话 id 放行 Windows 保留设备名）——存储侧 `WINDOWS_RESERVED_DEVICE_NAMES` + 校验器转公开、网络层镜像同判据、CLI `--resume` 早期 fail-loud；新增 19 例测试，变异体负向验证 **4/4 精确变红**，全量 3173 passed；正文见下方同名小节
> - 2026-09-26：**闭合 1 条 → A3**（入口层职责再拆）。分两批交付：七个平铺 `cli*.py` 收进 `heagent/cli/` 包（`__init__.py` 零 import、入口脚本改指 `heagent.cli.console:main`、契约按包根收敛），再把 `cli.py` 拆为 `console.py`/`composition.py`/`interactive.py`、`cli_http.py` 拆为 `http.py`/`http_console.py`；正文移入下方「A3」小节（本区不留副本）。实测：全量 3149 passed / 覆盖率 92% / ruff·mypy 双平台全绿 / 拆分批负向验证 3/3 精确变红
> - 2026-09-27：**标记 1 条为 OBSOLETE**（TCP 入口不写 rollout）——Epic 48 TCP 网络接口已于 commit `4217b5d` 完全删除，本条目随之失效。
> - 2026-09-27：**归档 1 条 → Z-D18**（TCP 入口不写 rollout，OBSOLETE）——正文按归属移入 `epics/epic-48-TCP网络接口周期/deferred-work.md`，本区不再留副本。
> - 2026-09-27：**闭合 1 条 → Z-D19**（诊断折叠标题把信息性 note 计入「需要注意」并双计 BOM）——`5f4324b` 已实现 `INFORMATIONAL_NOTES` 分级与 BOM 去重，本轮补上缺失的判据（前端探针桩自洽化 + 新用例 `V`：信息性 note 不计入告警、说明仍可见；变异体精确变红）；正文移入 `epics/epic-50-网页控制台周期/deferred-work.md`。活动条目数 21 → 19。
> - 2026-09-27：**闭合 2 条 → A9 / A18**（★ 均为**代码先修、台账后补**）——A9 运行时归因与兜底族（`a1f7c67`：用户 `DELETE` 优先归因 + `deadline_reason` 一次性消费 / 新增 `HTTP_TOOL_INFLIGHT_TIMEOUT` 独立阈值 / 订阅限额检查与登记同步一步）、A18「共 N 个会话」在 N > 200 时少报（`7b9015f`：`count_sessions` + 协议 `total` + 前端 capped 分支）。正文按归属移入 `epics/epic-50-网页控制台周期/deferred-work.md`；活动条目数 19 → 17。
> - 2026-09-27：**部分闭合 1 条 → A11②**（cron 跨会话后置执行，`5a8a21e`：`enable_cron=False` 时连 `JobStore` 都不构造 + `new_loop` 守卫）；**① 非回环运行姿态仍 `blocked`**，故本条**留在活动区**。
> - 2026-09-27：**闭合 1 条 → A5**（观测粒度残余）——两半其实早在 `1f99cc0`（2026-09-23「补齐事件耗时与 逐 story 观测粒度」）就已修掉并带判据，只是台账一直没同步；本轮复核后按勘察类移入下方闭合归档，活动条目数 17 → 16。
> - 2026-09-27：**闭合 2 条 → A13 / A14**（均为 Epic 50 的收口评审遗留）——A13「高影响键缺后端风险标记」（事实源 = `RESOURCE_CEILINGS`，新增 `impact` 后端字段 + 面板徽标 + 确认框点名，前端零硬编码；变异体 4/4，其中两条专门抓「按键名硬编码」）；A14 写入通道与保真写的四类残余**四面全部处置**（① 文档说明、② 回滚失败文案、③ 写锁内 I/O 收窄、④ 备查）。正文移入 `epics/epic-50-网页控制台周期/deferred-work.md`；活动条目数 15 → 13。
> - 2026-09-27：**闭合 1 条 → Z-D21**（同一会话文件的两个写者整份覆盖对方历史）——运行落盘改为带**内容基线**（`save(base=...)`）落盘：能安全判定的形态**保守合并**（两段都保留），判不出来退回 last-write-wins + WARNING；判据 11 条（含 run 级），变异体 **5/5 精确变红**（其中 M4 首轮没红，暴露出我原来那条判据的输入形状不具区分度）。正文按归属移入 `epics/epic-50-网页控制台周期/deferred-work.md`；活动条目数 16 → 15。
> - 2026-09-27：**归档 1 条 → Z-D20**（TCP 入口删除后的活文件残留，当日勘察 + 当日闭合）——`4217b5d` 只清了 `docs/frame.md`，README 整节 / CLAUDE.md 命令表 / `.env.example` 8 个 `TCP_*` 键 / 12 处 docstring 仍在宣告该入口（全仓 493 处命中、非历史面 40 余处）；分层清理后新增可执行判据（变异体 3/3 精确变红）。正文移入 `epics/epic-48-TCP网络接口周期/deferred-work.md`。活动条目数不变（17）——该条**登记即闭合**，未进活动区。
> - 2026-09-27：**交付 1 条（部分闭合）→「跨项目并发无全局上限」**——新增可选的 `HTTP_MAX_TOTAL_INFLIGHT`（Settings → `HttpServerConfig.max_total_inflight`，默认 **0 = 不限** ⇒ D9 的按项目语义逐字不变；设正数后跨项目共享一份名额；超限回**新稳定码** `total_inflight_limit`（409），与「本项目已有运行」的 `run_conflict` 分开）。判据 6 条新增、变异体 **5/5 精确变红**（含「默认改成 1」⇒ 27 红）、`HttpErrorCode` 成员集契约 34 → **35**、`ruff` / `format --check` / `mypy`（本机 + `--platform linux`）全绿。**残余**：默认不限是 D9 的裁定语义，改默认属产品裁决。同轮**修正 1 条滞后证据**（浏览器级 UI 验收条的「CI 只装 `.[dev]`」与实测不符）。活动条目数不变（13）——该条为**部分闭合**，留在活动区并逐面标注。
> - 2026-09-27：**实施 1 条（部分闭合）→ 技能资源 TOCTOU 残余**——用户裁定「**授权引入专用代码**」后交付 POSIX **逐组件 `openat`**（中间目录 `O_DIRECTORY|O_NOFOLLOW`、叶 `O_NOFOLLOW`，导入期冻结的能力门），Windows 回退整路径 `open`（窗口仍宽）。判据 7 条（含「围栏后替换中间目录」的竞态用例）+ 变异体 **5/5 精确变红**；WSL Ubuntu 上 56 passed / 1 skipped 与全量 3114 passed（3 例 `test_cli_http_lifecycle.py` 端口断言经**基线对照**确认是 WSL2 环境特性）、本机 3126 passed / 覆盖率 91.74%。活动条目数不变（13）。
> - 2026-09-27：**闭合 1 条 → Z-D24**（MCP stdio 子进程未接入沙箱，**裁定 (c) 不实施**）——裁定理由是「长命双向管道 vs 短命命令捕获的形状冲突 +隔离档属产品取舍 + Windows 无创建期缝 + 仍非边界」；正文按归属移入 `epics/epic-S1-S4-沙箱硬化周期/deferred-work.md`，本区只留 ID 索引。活动条目数 13 → 12。
> - 2026-09-27：**复核 2 条 + 修正 1 条证据**（#2 技能资源 TOCTOU / #3 MCP stdio 入沙箱）——① #3 的 env 面经 SDK 实测排除（`mcp/client/stdio/__init__.py` 只给 `DEFAULT_INHERITED_ENV_VARS`：win32 12 项 / POSIX 6 项，显式 `env` 合并）⇒ 原 evidence「其 `env` 亦不经 `scrub_sensitive_env`」会被读成「继承全部环境变量」而与实测不符，已改写并补上「真缺口只剩 spawn 面 + 为什么不是加个 wrapper」（后端只实现短命命令捕获的 `CommandRunner`、MCP 需长命双向管道、隔离档需产品裁决、Windows 无创建期缝、仍非边界）；② #2 复核维持开启——Story 46.1 已裁定 assessment-only，逐组件 `openat` 命中 **Ask First（平台专用代码）**，故其门在授权而非实现。活动条目数不变（13）。
> - 2026-09-27：**闭合 4 条裁决类条目（A23 / A11 / A17 / A19；2026-09-28 号归一前记作 A19 / A20 / A21 / A22）**——① A23「掩码域后缀制」：裁定维持现状（URL 不以凭证命名 + 部分掩码破坏诊断 + 与 `safe_logging` 口径分场景），补充至 `docs/frame.md` 五；② A11「非回环运行姿态」：裁定维持现状（Epic 49 既有姿态 + 真正边界是 OS 沙箱 + 破坏既有契约），更新文档描述；③ A17「R5 收敛判据失效」：裁定收紧规格（正文以 `Error:` 开头的文件不在收敛范围），补充至文档；④ A19「目录选择端点默认开」：**裁定默认改按需**（`--dialog-backend` 默认改为 `none`，与 `HTTP_CONSOLE_WRITE_ENABLED` 惯例一致）——修改 `cli/http.py:362`（命令选项默认值）+ `cli/http_console.py:440`（`HttpProjectConsole.__init__` 默认值）+ 更新 `docs/frame.md` 已知缺口行。活动条目数 12 → 8。
> - 2026-09-27：**清理 3 条重复/已闭合条目**——① 行 78-82「非回环运行姿态」的 ① 部分已裁定维持现状（号统一后记作 A11），归档为 A11（部分闭合，② cron 部分）；② 行 99-102「R5 收敛判据失效」已闭合（号统一后记作 A17），从活动区移除；③ 行 104-107「目录选择端点默认开」已闭合（号统一后记作 A19），从活动区移除。活动条目数 8 → 5。
> - 2026-09-27：**合并 2 条重复浏览器验收条目 + 精简残余描述**——两条 50-6/50-8 浏览器验收正文完全相同，合并为一条（source_spec 改为 `50-6/50-8`）；控制台阻塞 I/O 条目的"唯一残余"描述精简（已量化且有升级条件，删除冗余细节）。活动条目数不变（5）。
> - 2026-09-28：**计数校正（机械；条目内容一字未动）**——按本文件逐行实测（脚本 `.heagent/tmp/`：`audit_ledger.py` / `count_check.py` / `ledger_count_history.py` / `item_diff.py`）：① 本区标题 `5 条` → **8 条**；② 归档引言 `35 条 / 21 条` → **33 条 / 19 条**（= 14 + 19，与实际小节数一致）；③ 状态总览②标题 `20 条` → **19 条**；④ 本账单 2026-09-27 三行的收尾计数有误——`12 → 8` 实为 **12 → 11**（该提交只移出「掩码域后缀制」1 条）、`8 → 5` 实为 **11 → 9**、`不变（5）` 实为 **9 → 8**（合并两条浏览器验收条目），实测序列 **12 → 11 → 9 → 8**。⇒ 本区条目数**以标题为准**，上述历史行内的「活动条目数」不再可靠。
> - 2026-09-28（第三轮）：**登记并闭合 1 条 → A24**（GUI 事件日志在环形缓冲满后永久停止渲染 + 暂停即丢事件）——当日发现、当日修：差分改走观察者**单调总数**（纯逻辑落 `pub/event_lines.EventCursor`，14 例判据 + 变异体 4/4 精确变红）；同轮把 A10 的 stat 面收敛（新增 `ProjectRegistry.find`，`_project_entry` 改走它：≤33 stat → **1 stat**）并在 A16 的判据上写明迁移条件。① 由 14 条变 **15 条**、闭合归档总数 32 → **33 条**。
> - 2026-09-28（第四轮）：**闭合 1 条 → A4**（GUI 原生事件渲染）——两片交付：**A4a** 事件驱动渲染（含同轮发现的 A24）与 **A4b** 消息 sink 替掉 stderr 全量捕获（`cli/goal.py` 40+ 处输出收敛到 `_echo`，`_goal_runner(on_message=…)` 用 ContextVar 绑定；GUI 日志改只落文件）。**A4c**（纯事件流自绘 `/goal` 进度）**有意不做**。活动条目数 8 → **7**；① 由 15 条变 **16 条**、闭合归档总数 33 → **34 条**。
> - 2026-09-28（第二轮）：**A 编号统一 + 计数再校正**——① 新增「**A 编号登记表**」作为 A 编号唯一事实源（A1~A19 + A23，共 20 个事项；撤号 A20/A21/A22 **不复用**；旧 A19「掩码域后缀制」属**让号**——该号已由 2026-09-24 先登记的「原生目录选择端点默认开」持有，故改取 A23）；② 状态总览②、四个闭合小节标题、流水账单历史行的编号全部归一（旧 A19/A20/A21/A22 → **A23/A11/A17/A19**，其中旧 A20「非回环运行姿态（总结）」是 A11 的重复登记，撤号并入 A11）；③ **计数再校正**：② 原 19 行里 A11 与 A20 是**同一事项的两行**，去重后 ② = **18 条**、闭合归档总数 **33 → 32 条**（= 14 + 18；上一轮把重复登记计了两次）；④ 新增可执行护栏 `tests/test_deferred_id_registry.py`。
> - 2026-09-28（第五轮）：**复核活动项 + 补判据 + 状态归一**——① 逐条对 7 个活动项（A1 / A6 / A8 / A10 / A12 / A15 / A16）按登记落点取证复核（未发现「代码已修、台账未同步」项）；② **补 3 例判据**覆盖 A19 的默认值裁定（`HttpProjectConsole` 默认 / `http-server` 旗标默认 / 内嵌服务默认——此前**无任何用例**覆盖默认值，改回 `auto` 不会变红），变异体 **2/2 精确变红**；③ 修 `docs/frame.md` 4.18 与 A19 裁定自相矛盾的过期段（「默认姿态 = 开…内嵌路径没有关闭手段…待裁决」→ 默认关 + 把 2026-09-26 实测降为历史记录），并同步 4.18 表格行 / 五 的两行 / 流程图一行 / CI 装机口径一行；④ A15 条目的触发条件按 A19 收紧（默认关 ⇒ 须显式 opt-in）；⑤ **A11 状态归一**（① 裁定维持现状 + ② cron 已修 ⇒ 两半都已了结，「部分闭合」属误标）：登记表 / 状态总览 / 正文标题 / 总览 §17.4-A / epic-50 引言五处同步，② 表 18 → 17 行、① 表 16 → 17 行。活动条目数不变（**7 条**）。
> - 2026-09-28（第六轮）：**产品裁定闭合 5 条 → A8 / A10 / A12 / A15 / A16**（均「维持现状」类，理由与冻结边界逐条写入下方同名小节）——A8（D9 的有意语义 + 服务级总额已作可选键交付）、A10（其余落点全部离线，仅剩 `_runtime_for` 的 1 读 + 1 stat，有意保留 + 升级条件）、A12（浏览器验收**保持手动**：冻结边界禁 playwright，真浏览器这一步不可省略）、A15（A19 之后默认关闭 ⇒ 显式 opt-in 才出现，不做更强授权）、A16（人工验收为唯一路径 + 迁移条件已进判据本体）。**活动区 7 → 2 条**（仅剩 **A1** 技能资源 TOCTOU 后续的休眠面 ④ 待授权、**A6** 路径级审批分级的条件性前置未发生）；① 表 17 → 22 行、闭合归档总数 34 → **39 条**；跨文档 7 处计数声明同步为 **2 条**。
> - 2026-09-28（第七轮）：**实施 1 条（部分闭合）→ A1④**（导入形态的内容钉 + 读时校验；用户裁定「继续」＝实施授权）——`SkillLockEntry.resources`（逐文件 sha256）+ **落地前复核**（关掉「算钉 → 复制」之间被改写的窗口，失败不留半成品）；`SkillPackage` 读侧除渲染器凭据外新增**包外兄弟文件** `manifest.lock` 凭据（先按规范化 `destination_path`、再按 `canonical_id` 兜底；两者并存时渲染器优先；老 lock 静默升级；未托管包只多一次 stat、不 open）。新增判据 **18 例（收集 20）**、**变异体 6/6 精确变红**、`ruff check` / `format --check` / `mypy`（本机 + `--platform linux`）全绿；全量分 4 块实跑 **3189 passed / 14 skipped / 18 deselected / 0 failed**（= 859 + 918 + 721 + 691；较上一轮 3169 多出的 20 正是新增判据的收集数）；两个改动模块在 skill 子集下实测 88% / 92%。活动条目数不变（**2 条**）——A1 残余只剩平台/形态固有项与「可信导入 snapshot」。
> - 2026-09-28（第八轮）：**裁定闭合 1 条 → A1**（技能资源读取 TOCTOU 后续）——产品裁定「维持现状」：① POSIX 逐组件 `openat`、② 导入形态的内容钉 + 读时校验（A1④，同轮交付）均已落地，其余为平台/形态固有（Windows 只护最终组件 / 组件之间仍有时间差 / 凭据与包由同一写者掌控 / 仍非边界）；「可信导入 snapshot」作为正文内的未闭合面保留、不另立条目。正文移入下方「A1」小节；**活动区 2 → 1 条**（仅剩 **A6** 路径级审批分级：条件性，前置未发生）；① 表 22 → 23 行、闭合归档总数 39 → **40 条**；跨文档 7 处计数声明同步为 **1 条**。
> - 2026-09-28（第九轮）：**裁定归档 1 条 → A6**（路径级审批分级）——裁定「**维持条件性**」：前置（非 workspace 的受控写）未发生，审批是工具级、越界路径在 workspace 围栏处即 `BLOCKED`，**无分级对象**；触发条件、若实现时的判据草案与冻结边界移入 `docs/frame.md` 五。**活动区 1 → 0 条（首次清空）**；① 表 23 → 24 行、闭合归档总数 40 → **41 条**；7 处「活动条目数」声明同步为 **0 条**。
> - 2026-10-07：**登记 4 条**（Story 51-8 未 push 提交的 /simplify 清理轮：复用 / 简化 / 效率 / 层次四角度并行审查，修 6 处并全量验证后，对 4 处「跨 diff 消费面 / 属设计变更 / 受 checkpoint id 兼容约束」的跳过项按纪律补录）——A25 checkpoint id 残留 `-parallel-` 分支、A26 `active_stories` 可派生镜像、A27 门事件 emit 隔离包装双份、A28 goal-verify 台账生命周期 CLI 手写。活动条目数 0 → **4**。
> - 2026-10-07（第二轮）：**登记 5 条**（同日全项目 /simplify 四角度清理轮：22 项发现修 8 项提交 `5e963db`，14 项跳过发现按主题归并为 5 条补录）——A29 会话/运行热路径四处重优化（效率族）、A30 goal 域两处重复收敛（复用族）、A31 引擎层方法论与解析错位（层次族一）、A32 治理与互斥的层级归属（层次族二）、A33 可派生镜像与边际重复（简化族）。活动条目数 4 → **9**。
> - 2026-10-07（第三轮）：**部分闭合 1 条 → A32①②**（用户裁定「三写方法全自锁 / 读不加锁 / 只收敛只读表」后实施）——① 只读判定删 `_READ_ONLY_TOOLS` 名称表收敛注册表注解单源（缺 schema fail-closed；勘察证实收敛前 13=13 零漂移；`_PATH_FIELDS`/`_DENY_*` 无注册表孪生不在双源范畴）；② 新增 `goal/mutex.goal_mutex()`（可重入复合锁）下沉 `advance`/`pause_resume`/`record_decision` 三写方法，顺带收口勘察发现的 `/goal pause` 漏网写路径，CLI 外层持锁保留（薄别名）、`decisions.py` 并发论证与 `docs/frame.md` 同步、`test_declarative_resume_advances_once_under_goal_lock` 等 4 处测试缝迁指新模块。变异体 3+1 处精确变红，全量 3607 passed；③（CLI 引用例层私有符号）仍活动——条目留活动区逐面标注。**另**：同轮按用户裁定（有意删除）调整 `test_architecture_contracts.py` 的 TCP 残留扫描对缺席活文件跳过（CLAUDE.md 已从工作树移除）。活动条目数不变（**9**）。

## A29 会话/运行热路径的四处重优化（效率族）

- source_spec: `src/heagent/engine/store.py` / `src/heagent/context/session.py` / `src/heagent/context/tokens.py`（2026-10-07 全项目 /simplify「效率」角度发现，提交 `5e963db` 后补录）
  summary: **四个热路径上的真实浪费，均为重优化级、非顺手修**：① `RunStore.checkpoint` 每次落盘前 `load()` 整份快照（读 + parse + 校验 + 深拷贝 + `json.dumps(indent=2)` 全在事件循环内），而两个调用方恒传全量 messages/results/system ⇒ 每 run O(N²)：2 MB 历史、30 轮 ≈ 60 MB 读 + 60 MB 写 + ~120 次全量 parse，每工具往返注入 100–300 ms；② `recent_session_ids` 为读一个 `timestamp` 字段全量 parse 目录内每个会话 JSON（本项目实测 84 天 = 409 文件 / 83 MiB），`cli/interactive` 还在事件循环内同步调 ⇒ 交互启动秒级阻塞；③ `_metadata_from_data` 在无 title 会话上回退 `derive_title` 时构造**整条历史**的 Message 列表 ⇒ 列表页与每次无显式 session 的 run POST 都是 O(所有会话 × 所有消息)；④ 默认 token 估算器逐字符分支链（tiktoken 不在依赖里，即生产路径），2 MB 历史 ≈ 2M 次/调用、100–200 ms，每 LLM 调用 1–2 次。触发条件（逐面）：① 恢复语义重构或建立 benchmark 时（checkpoint 改写只读、load 仅留 resume）；② 交互启动 P95 超标或会话目录过百 MiB 时（scandir + mtime 预排序 + 只 parse top-K，或复用 `_read_head`）；③ 列表页卡顿时（标题只取首条用户消息，或 (path, mtime, size) 缓存）；④ 上下文压缩成为瓶颈时（逐消息缓存增量计）；严重度：中（可感延迟，无正确性风险）；冻结边界：① 不得破坏 resume 语义（`final_answer`/`error` 的 None 合并行为须带判据）；② mtime 排序与 timestamp 字段可能在文件复制场景分歧，选型时显性裁定；④ 缓存必须逐字节等价（估算值不得变化）。
  evidence: `engine/store.py:118/133-135/145-146`（load + 深拷贝 + 事件循环内 dumps）+ `agent/run_lifecycle.py:255/263`、`agent/stream_runtime.py:132/157`（每轮 2 次 + finish）；`context/session.py:663-682`（全量 parse）+ `cli/interactive.py:230`（事件循环内同步调）+ `memory/dream.py:339`；`context/session.py:317`（整历史构造）+ `cli/http_console.py:558/803/640`（每请求消费面）；`context/tokens.py:218-246`（逐字符链）+ `agent/loop.py:549`、`context/context_runtime.py:133`、`agent/stream_runtime.py:99`（调用面）。效率审查同时核实干净面：provider 流式累积、EventBus 扇出、工具执行链、系统提示组装、子 agent 闭包均无发现。
  Progress（2026-10-07 登记，未修——属性能重构，须带 benchmark 与判据做）

## A30 goal 域两处重复的收敛（复用族）

- source_spec: `src/heagent/goal/decisions.py` / `src/heagent/goal/evidence.py` / `src/heagent/goal/doctor.py`（同轮「复用」角度发现）
  summary: **① `DecisionStore` 与 `EvidenceStore` 约 90 行孪生**（id 围栏含同款 `_WINDOWS_DEVICE_NAMES`、`_require_current_schema`、`append` 的 exists→load→corrupt/already-exists 流程、`_create_exclusive` 逐字节相同、`load`/`list_records`），且已实际漂移：EvidenceStore 持 `asyncio.Lock` 而 DecisionStore 不持——**漂移是有意还是疏漏须先裁定**再收敛（建议 `goal/_record_store.py` 泛型基类，参数化记录类 / id 字段 / 错误工厂 / 过滤键）；**② `doctor._declared_required` 重写 loader `_resource_list` 的 frontmatter 列表解析**（同款 `strip("[]").split(",")`），但宽容度分叉：doctor 错型返回 `[]`、loader 抛 `SkillWorkflowError`——`workflow_loader.py:575` 自己警告过「同一 frontmatter 两种宽容度」。触发条件：① 任一 store 再加方法时；② doctor 或 loader 的声明解析再变时；严重度：低-中；冻结边界：① 收敛必须保留两店各自的并发语义（锁差异裁定前不动）；② 统一时不得静默改 doctor 的容错行为（老工作流 doctor 仍须能跑）。
  evidence: `goal/decisions.py:97-184/41-42` 对照 `goal/evidence.py:234-331/60-61`；`goal/doctor.py:151-160` 对照 `goal/workflow_loader.py:545-551/575`。
  Progress（2026-10-07 登记，未修）

## A31 引擎层的方法论与解析错位（层次族一）

- source_spec: `src/heagent/engine/artifacts.py` / `src/heagent/engine/workflow_runner.py` / `src/heagent/tools/builtins/subagent.py`（同轮「层次」角度发现）
  summary: **三处「声明应在 md 包、机制应在 goal/」的错位**：① `engine/artifacts.py` 的 `parse_artifact`/`validate_hierarchy`/`validate_sprint_status_path` 把 BMad 方法论（Given/When/Then 强制、「Definition of Done」节、`_bmad-output/sprint-status.yaml` 权威路径）硬编码进引擎治理层，且 src 运行期零调用方（仅 `engine/__init__` 再导出与测试）——违反「文案/策略进 md 包声明、代码零副本」立场，构成第二份分叉的契约源；② story/epic 制品形状解析（`StorySpec` + `_STORY_*`/`_EPIC_*` 正则含 `父 Epic` 字段）住在引擎，唯一 src 调用方是 `goal/application.load_stories`，而 `run_step` 本就接受预解析 stories——S-1/E1 约定被冻结进通用引擎，第二个工作流域将被迫继承 story 机器；③ `subagent._DELEGATION_FALLBACK` 把 BMad 专属评审分层与仓内路径写进通用 tools 层内建的深度限制错误文案——每个非 BMad 消费者都会收到 BMad 建议。触发条件：① 出现第二个工作流方法论消费方或引擎契约再收敛时；② story 机制需要第二域复用时；③ 任何非 BMad 分发场景实际触达该文案时；严重度：低-中；冻结边界：①② 迁移方向是 goal/（或 md 包声明化），引擎只留确定性结构——**不得反向给引擎加「方法论开关」参数**；③ 结构化错误先行、兜底文案迁 md/role 包，不得直接删文案留下无指引的裸错误。
  evidence: `engine/artifacts.py:196-298/242/288`（+ `engine/__init__` 再导出面）；`engine/workflow_runner.py:84-184` + `goal/application.py:437`（唯一调用方）；`tools/builtins/subagent.py:138-142/158`。
  Progress（2026-10-07 登记，未修）

## A32 治理与互斥的层级归属（层次族二）——①② 已闭合（2026-10-07），③ 活动

- source_spec: `src/heagent/engine/policy.py` / `src/heagent/goal/application.py` / `src/heagent/cli/goal.py`（同轮「层次」角度发现）
  summary: **三处归属错位**：① 【已闭合 2026-10-07】`policy._READ_ONLY_TOOLS` 名称表与 `@tool(read_only=True)` 注册表注解的双事实源——已删表收敛注解单源，缺 schema/注解即 fail-closed 阻断；勘察证实收敛前零漂移（13=13）；`_PATH_FIELDS`/`_DENY_*` 经查无注册表孪生（`ToolAnnotations` 仅 4 个 bool hint），属引擎侧单源策略数据，**不在双源范畴、保持现状**。② 【已闭合 2026-10-07】单推进者互斥下沉内核：新增 `goal/mutex.goal_mutex()`（进程内 asyncio.Lock + `.heagent/goal.lock` 文件锁复合，同 task 可重入），`advance`/`pause_resume`/`record_decision` 三写方法自持；CLI 外层组合持锁保留（`_goal_mutex()` 薄别名）；勘察顺带发现并收口 `/goal pause` 漏网写路径（dispatch 不持锁直写状态）。③ 【活动】`cli/goal.py` 从用例层 import 约 10 个下划线私有符号（`_GOAL_SKILLS_ROOT`/`_GoalAdvanceContext`/`_goal_document*` 等）——无导入契约，goal/ 内部重构会静默破坏入口层。触发条件：③ goal/ 下次内部重构时（先声明公共端口）；严重度：③ 低；冻结边界：② 已按「重入不死锁」交付（同 task 判别，全部 5 条 advance 生产路径即此形态）；③ 只加公共端口声明，不为入口层保留私有别名。
  evidence: ① `engine/policy.py` `_is_read_only` 单注解判定 + 新判据 `test_sandbox_mode.py::test_missing_schema_fail_closed_even_for_known_names`（变异体：恢复名称表兜底 ⇒ 红）；② `goal/mutex.py`（新）+ `goal/application.py` 三外壳 + 新判据 `test_goal_cross_process_lock.py`（重入死锁看门狗 / 并发串行化）与 `test_goal_decisions.py`（pause/decision/advance 三观察点，变异体：撤任一外壳锁 ⇒ 红）；`goal/decisions.py` 并发论证已改指 `goal.mutex`；③ `cli/goal.py:33-80`（未动）。
  Progress（2026-10-07 登记；同日①②闭合——全量 3607 passed、ruff/mypy 双平台全绿、变异体 3+1 处精确变红；③ 留活动区）

## A33 可派生镜像与边际重复（简化族）

- source_spec: `src/heagent/engine/checkpoint.py` / `src/heagent/engine/workflow_runner.py` / `src/heagent/cli/goal.py`（同轮「简化」角度发现）
  summary: **① `artifact_refs` 是 `outputs` 键表的可派生镜像**：全部写点恒 `list(self.state.outputs)`（不变量已核实），跨 `WorkflowCheckpoint`/`GoalWorkflowState` 两模型重复维护，`from_checkpoint` 的 `{reference: None ...}` 兜底在该不变量下不可达——与已登记的 A26（`active_stories`）同性质，派生化须与旧 checkpoint 容忍读一并做（模型无 `extra="forbid"`，旧盘字段天然容忍，主要工作是确认无旧写者依赖）；**② `_goal_declarative_dispatch` 的 11 处 `resolved = await _goal_resolve_bound(); if resolved is not None:` 前导**——收敛为返回 `resolved[1]` 的小助手只省一个索引、不减行数，本轮判为边际。触发条件：① 与 A26 的派生化同批做（共享同一份 checkpoint 兼容评估）；② 该路由下次增删子命令时；严重度：低；冻结边界：① 不得只删字段留旧快照读者崩；② 不得为收敛改变任何分支的互斥语义（`resume`/`next`/`reset` 的 `_goal_mutex` 持有面一字不动）。
  evidence: `engine/checkpoint.py:67/232`（两模型字段）+ `engine/workflow_runner.py:374`（不可达兜底）+ 写点恒 `list(self.state.outputs)`；`cli/goal.py` 的 `_goal_declarative_dispatch`（11 处前导）。
  Progress（2026-10-07 登记，未修——①候并与 A26 同批）

## A25 checkpoint id 的 `-parallel-` 残留分支（批次机制遗物）

- source_spec: `src/heagent/engine/workflow_runner.py`（`_checkpoint_id` 的 `step.max_parallel_stories > 1` 分支；2026-10-07 Story 51-8 未 push 提交的 /simplify 四角度清理轮发现，「简化」与「层次」两角度同报）
  summary: **批次机制移除后 `-parallel-` 后缀成了无读者的仪式**：Story 51-8 已把 story 执行收口为 fail-closed 串行（引擎不再读 `max_parallel_stories`，loader 只告警），但 `_checkpoint_id` 仍按声明值 `>1` 追加 `-parallel-{len(completed_stories)}`——该分支是已删机制在引擎里的最后运行期读者，让读者误以为并行面仍存在。触发条件：下次动 checkpoint id 或恢复语义时一并处置；严重度：低（2 行，误导性大于成本）；冻结边界：**删除会改 checkpoint id 格式**——声明过 `max_parallel_stories>1` 的存量 goal 跨版本恢复时对不上旧快照（步骤级进度可见丢失），故必须与 id 兼容策略（迁移 / 容忍读）一并做，**不得单独顺手删**。
  evidence: `src/heagent/engine/workflow_runner.py:1019-1020`（分支本体；story_part 已含 `-story-{index}` 与 sanitized story label，串行下 id 唯一性由二者承担）；`src/heagent/goal/workflow_loader.py:615-625`（解析期显性告警「declared value does not raise parallelism」）；串行为有意设计：`_bmad-output/epics/epic-51-goal-workflow优化周期/brief.md`（「写集无法证明安全时自动串行」）。
  Progress（2026-10-07 登记，未修）

## A26 `active_stories` 是 `active_story` 的可派生镜像（六写点同步税）

- source_spec: `src/heagent/engine/workflow_runner.py`（`WorkflowRunnerState.active_stories` 全部写点；同轮 /simplify 清理轮「简化」角度发现）
  summary: **`active_stories` 的每个写点都只写 `[]` 或 `[active_story]`，`from_checkpoint` 还要用 `active_story` 重建它——纯派生状态**：串行化后「复数视图」永远至多单元素，却要 6 处写点（runner 4 处 + checkpoint 往返 + status_view 投影）永久保持镜像同步。触发条件：下次动 story 状态模型或 checkpoint 兼容层时一并派生化（checkpoint 字段保留容忍读）；严重度：低（无行为风险，纯维护税）；冻结边界：派生化触及**本轮 diff 之外**的消费面（`engine/checkpoint.py` / `goal/status_view.py`）与旧快照兼容，不得只删字段不接消费方。
  evidence: `src/heagent/engine/workflow_runner.py:282`（字段）+ `:387-389`（`from_checkpoint` 由 `active_story` 重建 = 派生性自证）+ `:458/824/872/891`（写点）+ `:966/991`（投影）；`src/heagent/engine/checkpoint.py:74/190/229`；`src/heagent/goal/status_view.py:44/98/149`。
  Progress（2026-10-07 登记，未修）

## A27 门事件 emit 隔离包装双份（CLI 与 runner 各一份）

- source_spec: `src/heagent/cli/goal.py`（`_emit_goal_gate_event`）对照 `src/heagent/engine/workflow_runner.py`（`_emit_step_event`）；同轮 /simplify 清理轮「复用」角度发现
  summary: **同一「emit-None 守卫 + try/except + `safe_log` 忽略」观测隔离契约存在两份实现**（goal.py 的 docstring 自证「对齐 `WorkflowRunner._emit_step_event`」）；将来收紧契约（如 error_kind 进 details、payload 结构）要两处同改，漏一处即漂移。触发条件：下次改引擎事件契约（error_kind / payload）时一并统一；严重度：低；冻结边界：统一方向 = 放宽 `_emit_step_event` 的 `step` 类型约束（`WorkflowStepResource` → 鸭子契约）并把 payload 构造挪进隔离内，但 CLI 侧 step/story 是**宿主鸭子契约**——不得为统一而给引擎模型加 CLI 专属字段，也不得让 CLI 绕过隔离直接 emit。
  evidence: `src/heagent/cli/goal.py:557`（本侧：payload 含 source/rerun/verdict，构造在隔离内——评审 LOW 的有意强化）；`src/heagent/engine/workflow_runner.py:42`（engine 侧：`step` 强类型，payload 构造在隔离外）。
  Progress（2026-10-07 登记，未修——统一需放宽引擎助手类型，本轮判断为净损失）

## A28 goal-verify 台账审计生命周期 CLI 手写（第三份 claim/execute/finalize 拷贝）

- source_spec: `src/heagent/cli/goal.py`（`_verify_ledger_acquire` / `_verify_ledger_complete` / `_verify_ledger_fail` 三助手 + `_run_verify_command` 接线）；同轮 /simplify 清理轮「层次」角度发现
  summary: **ledger 的 acquire→execute→complete/fail 配对序列在仓里已有两份**（`agent/tool_execution.py` 的 `_claim_ledger`/`_renew_ledger_lease`、`cron/scheduler.py` 的 loud-fail 先例），Story 51-8 在 CLI 添了第三份，并把 lease 策略（`timeout+60`）编码进 CLI——按模块 DAG，ledger/observability 归 engine 所有，入口层应是薄组合。且本份**无租约续租**：慢于静态租约的 verify 命令会让台账租约过期（审计面与执行面失配）。触发条件：第四份配对序列出现时，或 verify 命令实测超租约时；严重度：中低；冻结边界：正确落点是 `ToolExecutor` 的 audit-only（幂等去重禁用）模式——CLI 只传 `scope="goal-verify"`；**不得在 CLI 里补续租逻辑**（那是把第四份拷贝写进错误的层）；cron 的 loud-fail 是有意分歧（不属重复），收敛时须保留语义差异并有护栏测试钉住（同 Z-D3「有意分歧被护栏钉死」的教训）。
  evidence: `src/heagent/cli/goal.py:1153/1172/1185`（三助手）；`src/heagent/agent/tool_execution.py:55/184`（带续租的先例）；`src/heagent/cron/scheduler.py`（loud-fail 先例，语义不同）。
  Progress（2026-10-07 登记，未修——引擎新 API 属设计变更，超出清理范畴）

---

## 闭合归档（勘察类正文 + 回填索引）

> 当前闭合归档共 41 条：24 条勘察类正文保留在本文件，17 条已按归属 Epic 回填并仅在此保留 ID 索引。活动区另有 9 条未闭合条目（2026-10-07 两轮 /simplify 清理登记 A25~A33；2026-09-28 曾首次清空——A6 按裁定归档）。

## 状态总览

**① 勘察类（正文在本文件）——24 条**

| ID | 条目 | 结论 | 闭合 commit |
|----|------|------|-------------|
| Z-D1 | memory→engine 残余反向边（dream.py） | 已闭合 | `7b1b16b` |
| Z-D2 | 六处手写 frontmatter 解析器漂移 | 已闭合（实为 6 处，台账原记 4） | `e0d05cb` |
| Z-D3 | provider 三套回退骨架收敛 | **评估结论 = 不收敛**（有意分歧被护栏测试钉死），补四点互指注释 | `beea1a2` |
| Z-D4 | JsonlSink 逐事件同步落盘 | **评估结论 = 保持现状**（replay 契约天然满足），仅 docstring 如实化 | `4b5f037` |
| Z-D5 | CronScheduler 同步 store 调用 | 已闭合（4 处 to_thread，台账漏记 1 处） | `a633c5c` |
| Z-D6 | SafetyGuard/PolicyEngine 拦截零日志 | 已闭合（_block 单点 warning + policy 分级） | `3dd1050` |
| Z-D7 | GoalWorkflowState 三死字段 | 已闭合（容错忽略兼容策略） | `4b5f037` |
| Z-D8 | `RoleSpec.sandbox_profile` 死字段 | 已闭合（取**删除**方向，非激活） | 已提交 `dfe6eef`（2026-09-18） |
| Z-D9 | 沙箱无进程数限额 + WinJob 常量误写 | 已闭合（`SANDBOX_NPROC_LIMIT` + 修正 `PROCESS_TIME=0x2`） | 已提交 `8de6c63`（2026-09-18） |
| Z-D12 | MEMORY.md 非 UTF-8 让整个 run 起不来 | 已闭合（fail-soft：跳过注入 + **点名文件**的告警；文件字节一字不动） | `b01e09c`（2026-09-23） |
| Z-D17 | 会话 `.json.lock` 无回收方（随会话数单调增长） | 已闭合（孤儿 + 年龄超限 + **非阻塞加锁证明无人持有**三判据；残余 µs 级竞态如实记录） | `8c3cbc1`（2026-09-27） |
| Z-D16 | 会话 id 放行 Windows 保留设备名（静默丢数据） | 已闭合（存储侧 + 网络层镜像 + CLI 三处；字符集不放宽，只**追加**保留名拒绝） | `8c3cbc1`（2026-09-27） |
| A3 | 入口层（`cli.py` / `cli_goal.py`）职责再拆 | 已闭合（2026-09-26：收进 `heagent/cli/` 包 + 包内再拆三个模块；正文见下方「A3」小节） | `49168b4` + `42d7331`（另 `ea2e347` 收纳入口辅助）（2026-09-26） |
| A5 | 观测粒度残余（facade `run_failed` 恒 `duration_ms=0` / 并行批次只发整批一条事件） | 已闭合（2026-09-23 修为 + 2026-09-27 台账复核；正文见下方「A5」小节） | `1f99cc0` |
| A24 | GUI 事件日志在环形缓冲满后**永久停止渲染**（并「暂停即丢事件」） | 已闭合（2026-09-28 当日发现、当日修；正文见下方「A24」小节） | 见下方小节（`tests/test_event_lines.py` 14 例 + 变异体 6/6） |
| A4 | GUI 原生事件渲染（事件驱动渲染 + 消息 sink） | 已闭合（2026-09-28，A4a + A4b；A4c 有意不做） | 本文件下方「A4」小节 |
| A11 | 非回环运行姿态 + cron 跨会话后置执行 | 已闭合（② cron 2026-09-27 修：`enable_cron=False` 时连 `JobStore` 都不构造 + `new_loop` 守卫；① 非回环姿态 2026-09-27 裁定维持现状；2026-09-28 状态归一——此前误标「部分闭合」）；正文见下方「A11」小节 | `5a8a21e`（cron）+ 裁定（2026-09-27） |
| A8 | 跨项目并发无全局上限 | **裁定维持现状**（2026-09-28：D9 的有意语义；服务级总额已作可选 `HTTP_MAX_TOTAL_INFLIGHT` 交付，默认 0 = 不限）；正文见下方「A8」小节 | 见下方小节（6 例 + 变异体 5/5） |
| A10 | 控制台端点在唯一事件循环里做同步 I/O | **裁定维持现状**（2026-09-28：仅剩 `_runtime_for` 的 1 读 + 1 stat，有意保留并写明升级条件）；正文见下方「A10」小节 | 见下方小节（6 + 1 例 + 变异体 5/5） |
| A12 | 浏览器级 UI 验收不在 CI、也不含真实 LLM 运行 | **裁定维持现状**（2026-09-28：**保持手动**——冻结边界禁 playwright，真浏览器这一步不可省略）；正文见下方「A12」小节 | 见下方小节（`tests/js/console_acceptance.mjs` 23 行，手动） |
| A15 | 网页请求可拉起宿主 GUI 进程 | **裁定维持现状**（2026-09-28：A19 后默认关 ⇒ 显式 opt-in 才出现；不做更强授权）；正文见下方「A15」小节 | 见下方小节（默认值判据 3 例 + 变异体 2/2） |
| A16 | 真实原生窗口不可自动化 + 网页侧 `Error:` 前缀判据 | **裁定维持现状**（2026-09-28：人工验收为唯一路径 + 迁移条件已进判据本体）；正文见下方「A16」小节 | 见下方小节（结构性用例 + 变异体） |
| A1 | 技能资源读取 TOCTOU 后续（descriptor-relative open / 可信导入 snapshot / OS sandbox） | **裁定维持现状**（2026-09-28：① 逐组件 `openat`、② 导入形态内容钉 + 读时校验均已交付，其余为平台/形态固有）；正文见下方「A1」小节 | 见下方小节（变异体 5/5 + 6/6） |
| A6 | 路径级审批分级（前置未发生） | **裁定维持条件性**（2026-09-28：审批是工具级、越界路径在围栏处即硬阻断 ⇒ 无分级对象；触发条件与判据草案移入 `docs/frame.md` 五）；正文见下方「A6」小节 | 见下方小节（条件性，无实现） |

**② 已按归属 epic 回填（正文在各自周期目录）——17 条**

| ID | 归属 epic | 条目 | 正文位置 |
|----|-----------|------|----------|
| Z-D10 | Epic 48（Story 48-5 评审 C-1） | 运行栈日志的观测故障免疫 | `epics/epic-48-TCP网络接口周期/deferred-work.md` |
| Z-D11 | Epic 48（Story 48-5 评审 C-2） | 日志行的凭证脱敏 | 同上 |
| Z-D13 | Epic 50（Story 50-5 实现） | 写通道可把「资源旋钮」键设成无界值 | `epics/epic-50-网页控制台周期/deferred-work.md` |
| Z-D14 | Epic 50（Story 50-5 实现） | 审计文件无保留期 / 条数上限 | 同上 |
| Z-D15 | Epic 50（Story 50-6 实现，用户实测发现） | 首页加载即弹出关不掉的确认遮罩 | 同上 |
| Z-D18 | Epic 48（Story 48-5 评审 W-2） | TCP 入口不写 rollout（**OBSOLETE**，随入口删除失效） | `epics/epic-48-TCP网络接口周期/deferred-work.md` |
| Z-D19 | Epic 50（第四轮评审发现，2026-09-26 登记） | 诊断折叠标题把信息性 note 计入「需要注意」（并双计 BOM） | `epics/epic-50-网页控制台周期/deferred-work.md` |
| Z-D20 | Epic 48（删除后的收尾勘察，2026-09-27 发现并当日闭合） | TCP 入口删除后活文件仍在宣告该入口（README / CLAUDE.md / `.env.example` / docstring） | `epics/epic-48-TCP网络接口周期/deferred-work.md` |
| A9 | Epic 50（收口评审三镜头，2026-09-24 登记） | 运行时归因与兜底族（取消归因 / 工具卡死 / 订阅限额） | `epics/epic-50-网页控制台周期/deferred-work.md` |
| A18 | Epic 50（Story 50-8 收口后评审，2026-09-26 登记） | 「共 N 个会话」在 N > 200 时少报 | `epics/epic-50-网页控制台周期/deferred-work.md` |
| Z-D21 | Epic 50（Story 50-3 的并发写，2026-09-26 登记） | 同一会话文件的两个写者整份覆盖对方历史 | `epics/epic-50-网页控制台周期/deferred-work.md` |
| Z-D22 | Epic 50（收口评审第二轮，2026-09-24 登记） | 写入通道与保真写的四类低危残余（①文档 ②文案 ③锁内 I/O ④备查） | `epics/epic-50-网页控制台周期/deferred-work.md` |
| Z-D23 | Epic 50（Story 50-6 AC7/UX-DR3，2026-09-24 登记） | 「高影响键的差异化确认」缺后端风险标记 | `epics/epic-50-网页控制台周期/deferred-work.md` |
| Z-D24 | Epic S1–S4（brief `### Deferred`：「MCP server / cron 子进程接入沙箱」，2026-09-27 裁定） | MCP stdio 子进程未接入沙箱 —— **裁定 (c) 不实施**（见周期台账） | `epics/epic-S1-S4-沙箱硬化周期/deferred-work.md` |
| A23 | Epic 50（第四轮评审，2026-09-26 登记；2026-09-27 裁决） | 掩码域后缀制 —— **裁定维持现状**（文档补充；2026-09-28 由旧 A19 改号——**A20/A21/A22 是撤号，不复用**） | 本文件下方「A23」小节 |
| A17 | Epic 50（Story 50-8 收口后评审，2026-09-26 登记；2026-09-27 裁决） | R5 收敛判据失效 —— **裁定收紧规格**（文档补充；2026-09-28 由 A21 归一为 A17） | 本文件下方「A17」小节 |
| A19 | Epic 50（Story 50-8 实现，2026-09-24 登记；2026-09-27 裁决） | 目录选择端点默认开 —— **裁定默认改按需**（代码修改；2026-09-28 由 A22 归一为 A19） | 本文件下方「A19」小节 |

> `Z-Dn` 编号在**本文件**登记（跨文档引用如 `Z-D8` / `Z-D15` 仍以此为索引），但**正文只有一份**，在上表第二列指向的文件里；本文件不留副本（2026-09-24 回填）。**A 编号**自 2026-09-28 起统一登记于下方「A 编号登记表」（A1~A19 + A23/A24 一一对应 21 个事项；A20~A22 为撤号，不复用），本表中的 A 行只给正文位置、号以登记表为准。

## A 编号登记表（A-ID 唯一事实源，2026-09-28 统一）

> **规则**：① A 编号**只在本表登记**，跨文档（含 `src/`、`tests/`、`docs/`、各周期台账）引用一律以本表为准；② 一个事项只有一个号，
> **同号异义已全部消除**（历史冲突：旧 A19 曾同时指「掩码域后缀制」与「原生目录选择端点默认开」，旧 A17/A21 同指 R5）；③ **撤号不复用**——撤下的号只留在下表「旧号对照（撤号 / 让号）」段供旧引用追溯（**让号**是另一类：号被更早登记的事项先占，
> 条目改取新号，故该号在登记表里仍属活着的事项）；④ 活动区条目的正文仍只写在活动区，本表不复制。
> **与 `Z-Dn` 的关系**：`Z-Dn` 是勘察 / 归档序号（`Z-D1`~`Z-D24`），与 A 号**互不覆盖**；A2 / A7 / A13 / A14 与 Z-D24 / Z-D18 / Z-D23 / Z-D22
> 是**同一事项的双号**（见下表备注列）——这是「同事项双序列」，不是「同号异义」。

| 号 | 条目 | 状态 | 正文位置 |
|----|------|------|----------|
| A1 | 技能资源读取 TOCTOU 后续（descriptor-relative open / 可信导入 snapshot / OS sandbox） | 已闭合（2026-09-28 **裁定维持现状**：逐组件 `openat` + 导入形态内容钉均已交付；残余为平台/形态固有） | 本文件下方「A1」小节 |
| A2 | MCP stdio 子进程未接入沙箱 | 已闭合（2026-09-27 **裁定 (c) 不实施**） | `epics/epic-S1-S4-沙箱硬化周期/deferred-work.md`（同事项 **Z-D24**） |
| A3 | 入口层（`cli.py` / `cli_goal.py`）职责再拆 | 已闭合（2026-09-26） | 本文件下方「A3」小节 |
| A4 | GUI 原生事件渲染（事件驱动渲染 + 消息 sink） | 已闭合（2026-09-28，两片交付：A4a/A4b；A4c 有意不做） | 本文件下方「A4」小节 |
| A5 | 观测粒度残余（`run_failed` 无耗时 / 并行批次不逐 story 发事件） | 已闭合（2026-09-23） | 本文件下方「A5」小节 |
| A6 | 路径级审批分级（前置未发生） | 已闭合（2026-09-28 **裁定维持条件性**：前置未发生；触发条件与判据草案移入 `docs/frame.md` 五） | 本文件下方「A6」小节 |
| A7 | TCP 入口不写 rollout | OBSOLETE（2026-09-27 随入口删除失效） | `epics/epic-48-TCP网络接口周期/deferred-work.md`（同事项 **Z-D18**） |
| A8 | 跨项目并发无全局上限 | 已闭合（2026-09-28 **裁定维持现状**：D9 的有意语义，服务级总额已作可选项交付） | 本文件下方「A8」小节 |
| A9 | 运行时归因与兜底族（取消归因 / 工具卡死 / 订阅限额） | 已闭合（2026-09-27，`a1f7c67`） | `epics/epic-50-网页控制台周期/deferred-work.md` |
| A10 | 控制台端点在唯一事件循环里做同步 I/O | 已闭合（2026-09-28 **裁定维持现状**：唯一残余 `_runtime_for` 有意保留 + 量化升级条件） | 本文件下方「A10」小节 |
| A11 | 非回环运行姿态 + cron 跨会话后置执行 | 已闭合（2026-09-27：② cron 已修 + ① 裁定维持现状；2026-09-28 状态归一——此前误标「部分闭合」，而两半其实都已了结） | 本文件下方「A11」小节 |
| A12 | 浏览器级 UI 验收不在 CI、也不含真实 LLM 运行 | 已闭合（2026-09-28 **裁定维持现状**：保持手动，冻结边界禁 playwright） | 本文件下方「A12」小节 |
| A13 | 「高影响键的差异化确认」缺后端风险标记 | 已闭合（2026-09-27） | `epics/epic-50-网页控制台周期/deferred-work.md`（同事项 **Z-D23**） |
| A14 | 写入通道与保真写的四类低危残余 | 已闭合（2026-09-27，四面全处置） | `epics/epic-50-网页控制台周期/deferred-work.md`（同事项 **Z-D22**） |
| A15 | 网页请求可拉起宿主 GUI 进程（Story 50-8 R2 有意引入的暴露面） | 已闭合（2026-09-28 **裁定维持现状**：A19 后默认关 ⇒ opt-in 暴露面） | 本文件下方「A15」小节 |
| A16 | 真实原生窗口不可自动化 + 网页侧读取结果收敛依赖 `Error:` 前缀判据 | 已闭合（2026-09-28 **裁定维持现状**：人工验收为唯一路径；迁移条件已进判据本体） | 本文件下方「A16」小节 |
| A17 | R5 收敛判据失效（AC9 两句话互斥） | 已闭合（2026-09-27 裁定收紧规格） | 本文件下方「A17」小节 |
| A18 | 「共 N 个会话」在 N > 200 时少报 | 已闭合（2026-09-27，`7b9015f`） | `epics/epic-50-网页控制台周期/deferred-work.md` |
| A19 | 原生目录选择端点默认开 | 已闭合（2026-09-27 裁定默认改按需） | 本文件下方「A19」小节 |
| A23 | 掩码域后缀制 | 已闭合（2026-09-27 裁定维持现状） | 本文件下方「A23」小节 |
| A24 | GUI 事件日志在环形缓冲满后永久停止渲染（+ 暂停即丢事件） | 已闭合（2026-09-28，当日发现当日修） | 本文件下方「A24」小节 |
| A25 | checkpoint id 的 `-parallel-` 残留分支（批次机制遗物） | 活动（未闭合，2026-10-07 登记） | 活动区（本文件上方） |
| A26 | `active_stories` 是 `active_story` 的可派生镜像（六写点同步税） | 活动（未闭合，2026-10-07 登记） | 活动区（本文件上方） |
| A27 | 门事件 emit 隔离包装双份（CLI 与 runner 各一份） | 活动（未闭合，2026-10-07 登记） | 活动区（本文件上方） |
| A28 | goal-verify 台账审计生命周期 CLI 手写（第三份 claim/execute/finalize 拷贝） | 活动（未闭合，2026-10-07 登记） | 活动区（本文件上方） |
| A29 | 会话/运行热路径的四处重优化（checkpoint O(N²) / 会话列表全量解析 / 无 title 整历史校验 / token 估算逐字符） | 活动（未闭合，2026-10-07 登记） | 活动区（本文件上方） |
| A30 | goal 域两处重复收敛（DecisionStore/EvidenceStore 孪生 / doctor·loader frontmatter 解析宽容度分叉） | 活动（未闭合，2026-10-07 登记） | 活动区（本文件上方） |
| A31 | 引擎层的方法论与解析错位（artifacts BMad 硬编码 / story 解析错层 / subagent BMad 文案） | 活动（未闭合，2026-10-07 登记） | 活动区（本文件上方） |
| A32 | 治理与互斥的层级归属（policy 名称表双事实源 / advance 无锁 / CLI 引用例层私有符号） | 部分闭合（2026-10-07：①② 已修，③ CLI 引用例层私有符号仍活动） | 活动区（本文件上方） |
| A33 | 可派生镜像与边际重复（artifact_refs 镜像 / dispatch 前导 11 处） | 活动（未闭合，2026-10-07 登记） | 活动区（本文件上方） |

**旧号对照（撤号 / 让号）**

| 旧号 | 类别 | 归一为 | 说明 |
|------|------|--------|------|
| 旧 A19（掩码域后缀制） | **让号**（该号已由「原生目录选择端点默认开」在 2026-09-24 先占） | **A23** | 2026-09-27 曾把「掩码域后缀制」登记为 A19，而「原生目录选择端点默认开」早在 2026-09-24 已占 A19 ⇒ 掩码域改号；因 A20/A21/A22 当日已撤（分别归一为 A11/A17/A19），按「撤号不复用」取未用过的 **A23** |
| 旧 A20（非回环运行姿态「总结」） | **撤号**（重复登记） | **A11** | 与 A11 是同一事项的重复登记（A11 有条目本体与代码引用）⇒ 撤号并入 A11 |
| 旧 A21（R5 收敛判据失效） | **撤号**（同事项双号） | **A17** | 同一事项两个号 ⇒ 归一为 A17 |
| 旧 A22（目录选择端点默认开） | **撤号**（同事项双号） | **A19** | 同一事项两个号 ⇒ 归一为 A19 |
| 旧 A1~A6（2026-09-18 版） | **撤号**（条目已闭合） | 见 `consolidated-overview.md` §17.4-A 脚注 | 该版 A5（`RoleSpec.sandbox_profile` 死字段）/ A6（沙箱进程数限额）已于 2026-09-18 闭合，号随条目撤 |


---

## Z-D1 memory→engine 残余反向边（dream.py）

- **来源**：2026-09-17 架构收敛批次（persist/roles 迁出 engine 包）遗留登记。
- **问题**：`memory/dream.py:47` 运行期整包导入 `heagent.engine.EngineContainer`（触发条件：engine 包级 `__init__` 将来依赖 memory 包级 `__init__`；当前无环，架构文本性违规）。
- **结论**：**已闭合**（2026-09-17，commit `7b1b16b`）。EngineContainer 移入 TYPE_CHECKING（经 `engine.container` 子模块）、构造参数 `engine` 改必传、删除 `EngineContainer.default()` 缺省回退——cli.py 与全部测试本就显式注入，零调用方受影响；FORBIDDEN_RUNTIME_IMPORTS 为 memory 补 `heagent.engine` 断言。DreamScheduler 入口层装配现状未变（冻结边界）。
- **证据**：`tests/test_dream.py` 全绿 + `tests/test_architecture_contracts.py` 新契约。

## Z-D2 六处手写 frontmatter 解析器漂移

- **来源**：2026-09-17 架构与代码优化勘察（原登记 4 处，收敛时发现实为 **6 处**——漏记 `roles.py _parse_role_md` 与 `skill_packages._parse_metadata`）。
- **问题**：各模块独立维护 `---` frontmatter 正则与键值解析，同一文档在不同模块可能解析出不同结果。
- **结论**：**已闭合**（2026-09-17，commit `e0d05cb`）。新建零 heagent 依赖顶层模块 `frontmatter.py`（persist/roles 同层）：两个分隔符变体（EOF / 须尾随换行，有意并存）+ 严档 `parse_strict_pairs` / 宽档 `parse_inline_pairs` / 标量 `parse_scalar`；六处调用方改指向共享模块，公开 API、异常类型与消息文案逐字保持；`skills._FRONTMATTER_RE` 常量名保留（就地改写字节跨度依赖）；架构契约新增「frontmatter 正则只允许出现在 frontmatter.py」断言。
- **证据**：`tests/test_frontmatter.py`（直测）+ 六个调用方既有测试全绿。

## Z-D3 provider 三套回退骨架收敛

- **来源**：2026-09-17 架构与代码优化勘察（原设想「回退模板 + sticky/reset 策略参数」收敛）。
- **问题**：chain / key_rotation / switchable（加 router 实为四套）各自维护平行 send/stream 回退循环。
- **结论**：**评估结论 = 不收敛**（2026-09-17，commit `beea1a2`）。勘察推翻收敛设想：分歧是有意设计且被护栏测试钉死——`retry.py` docstring 明言「不要合并成一套」（判据矩阵三方不同：chain 回退一切非 NON_TRANSIENT 含 AUTH_FAILED 跨 provider；key_rotation 仅 RATE_LIMITED+AUTH_FAILED；switchable/router 仅 RATE_LIMITED+TRANSIENT），索引语义各异（chain 复位 / key_rotation 成功即粘 / switchable 回退成功才粘 / router 无状态单兄弟重试），`test_retry.py::TestPoolFallbackPolicy` 钉死分歧。按冻结边界交付最低要求：switchable 与 router 的 send/stream 补齐互指注释（chain↔key_rotation 原有），形成四点互指网；行为零改动。

## Z-D4 JsonlSink 逐事件同步落盘

- **来源**：2026-09-17 架构与代码优化勘察。
- **问题**：`_append` 每事件 mkdir+open+write+close，docstring 自称「只做一次 write/flush」与实际不符。
- **结论**：**评估结论 = 保持逐事件 append，不改实现**（2026-09-17，commit `4b5f037`）。close 即 flush 天然满足 replay 契约（crash 已写前缀可回放）；缓冲/常驻句柄引入句柄生命周期与丢失窗口，当前吞吐（LLM 工具循环级）下开销可忽略。仅 docstring 如实化并记录决策理由。

## Z-D5 CronScheduler 同步 store 调用

- **来源**：2026-09-17 架构与代码优化勘察。
- **问题**：store 的 list/update/remove 在 async 调度路径上同步执行（同步文件 I/O + Windows 替换退避）。
- **结论**：**已闭合**（2026-09-17，commit `a633c5c`）。实为 4 处（台账漏记 one-shot 的 `remove`）：全部经 `asyncio.to_thread` 卸载（对齐 273cb89 与 WorkflowCheckpointStore 先例），JobStore 语义零改动。
- **证据**：`tests/test_cron.py::TestCronSchedulerTickPath`（tick 路径集成测试 ×2；两测试用不同 job_id——ledger key 含分钟级时间戳且共享默认 ledger 路径，同分钟重复 id 会被幂等 lease 跳过）。

## Z-D6 SafetyGuard/PolicyEngine 拦截零日志

- **来源**：2026-09-17 架构与代码优化勘察（台账原记「48/108 文件无 logger」，实测已 61/108）。
- **问题**：拦截只抛异常 + 发事件，日志零轨迹，事后无法审计。
- **结论**：**已闭合**（2026-09-17，commit `3dd1050`）。`safety.py` `_block()` 单点收口落 warning（覆盖全部 5 个拦截分支）；`policy.py` 5 处 BLOCKED 落 warning、APPROVAL_REQUIRED 落 info（SANDBOX_REQUIRED 常规路由不记防刷屏）；拦截语义零改动。
- **证据**：`tests/test_safety.py` / `tests/test_engine_p0.py` 各补 caplog 断言。

## Z-D7 GoalWorkflowState 三死字段

- **来源**：2026-09-17 架构与代码优化勘察（读者已随 RecoveryEnvelope 删除）。
- **问题**：`segment_index` / `segment_tokens` / `cumulative_tokens` 三字段无人读，仅落盘 schema 保留。
- **结论**：**已闭合**（2026-09-17，commit `4b5f037`，兼容策略 = 容错忽略）。三字段删除；pydantic 默认 `extra='ignore'` 保证旧 workflow.json 仍可加载；`test_engine_workflow.py` 新增含三键旧文件的加载测试固化契约。

## Z-D8 `RoleSpec.sandbox_profile` 死字段

- **来源**：2026-09-17 沙箱硬化勘察（第二轮优化批次）；2026-09-18 处置。
- **问题**：字段**既无消费方也无写入方**——全仓检索仅 `roles.py` 字段定义与 `sandbox.py` 一句 docstring；`_parse_role_md` 的 `keys=("name", "description", "tools", "max_iterations")` 从未解析它，故连从角色 `.md` 都设不了；`SubAgent._build_engine` 克隆父 policy 时不读该字段。
- **结论**：**已闭合**（2026-09-18，取「**删除**」方向而非「激活」）。① 删除 `roles.py` 字段与其注释；② 改写 `tools/sandbox.py:260` docstring——profile 的真正入口是 `PolicyEngine` 裁决出的 profile 名（`SANDBOX_PROFILES` / `SANDBOX_TOOL_PROFILES`，2026-09-17 硬化批），不再谎称来自角色字段；③ 修正 `docs/frame.md` 4.4 里「使 `RoleSpec.sandbox_profile` 死字段激活」这句**从未成立**的旧表述。**未选激活**的理由：谓词为「角色声明了 profile 但沙箱未授权」时必须 fail-safe 阻断（冻结边界），于是该字段只剩「沙箱已强制时换参数集」这点表达力，低于维护成本（YAGNI）。
- **证据**：`tests/test_roles.py` / `tests/test_architecture_contracts.py` / `tests/test_sandbox*.py` 全绿；`docs/frame.md` 4.4 与本文件引用同步。

## Z-D9 沙箱无进程数限额 + WinJob 常量误写

- **来源**：2026-09-17 沙箱硬化勘察（兑现资源限额 Resolution「进程数限额另立条目」）；2026-09-18 处置。
- **问题**：① 沙箱 shell 无**进程数**上界——firejail 未映射 `--rlimit-nproc`，WinJob 的 `ActiveProcessLimit` 字段虽已内联定义却从未赋值；fork bomb 只被 `tools/safety.py` 黑名单正则启发式覆盖（非资源上界）。② **顺带查出的既有 bug**：`WinJobBackend.run()` 把 `JOB_OBJECT_LIMIT_PROCESS_TIME` 误写为 `0x00000008`——按 Windows SDK（winnt.h）该位是 `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`，`PROCESS_TIME` 的正确值是 `0x00000002`。后果：配了 `SANDBOX_CPU_SECONDS` 时置位的是 ACTIVE_PROCESS 而 `ActiveProcessLimit` 仍为 0——**CPU 时间限额完全不生效，反而施加了「活动进程上限 0」**。
- **结论**：**已闭合**（2026-09-18，取「补齐」方向）。① 新增 `Settings.sandbox_nproc_limit`（`SANDBOX_NPROC_LIMIT`，默认 0=关闭），经 `container.default()` 同时透传两个后端；② `FirejailBackend._build_argv` 在 `--rlimit-cpu` 之后注入 `--rlimit-nproc`（0 时零参数，默认 argv 逐字节不变）；③ `WinJobBackend.run()` 置 `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` + `ActiveProcessLimit`；④ 修正 ②的常量误写（`PROCESS_TIME = 0x2`）。触发行为与内存/CPU 限额一致：**显性失败**（子进程被终止 → 非零退出码），不静默。⚠ **两个后端语义不对称（如实标注，不掩盖）**：firejail 的 `--rlimit-nproc` 底层是 `setrlimit(RLIMIT_NPROC)`，Linux 按**真实 UID** 计数（非 cgroup/job 作用域），设小了会波及同一用户的其他进程；WinJob 的 `ActiveProcessLimit` 才是 job 作用域——故默认关闭。
- **证据**：`tests/test_sandbox_mode.py`（默认值 / 两后端装配 / argv 注入与零参数三条）、`tests/test_coverage_sandbox.py::test_run_applies_resource_limits`（0x2 与 0x8 分开断言，钉死常量区分）；`docs/frame.md` 4.4 与配置表、`.env.example` 同步。

## Z-D12 MEMORY.md 非 UTF-8 让整个 run 起不来

- **来源**：2026-09-23 代码评审（commit `7b95e56`，`<memory>` 注入字节预算）。**本节 2026-09-24 由活动区同名条目的副本改写而成**——此前状态总览表已有 Z-D12 行、正文却缺该小节。
- **问题**：`FactStore._load_facts` 以 `read_text(encoding="utf-8")` 读取，文件若被非 UTF-8 编辑器（如 GBK）保存即抛 `UnicodeDecodeError`；`_memory_block` 不捕获 ⇒ 异常经 `build_system_prompt` 逃到 `run_lifecycle` 的新 run 初始化，该 run 直接失败。触发条件：用户手工编辑 `.heagent/memory/MEMORY.md` 并以非 UTF-8 保存；严重度：低（记忆是非关键资产，却造成硬失败）；冻结边界：加载失败必须 fail-loud **且错误可定位到该文件**，但不得吞掉内容或改写文件本体（与「超预算绝不静默」同立场）。
- **结论**：**已闭合**（2026-09-23，**用户裁定 = fail-soft**）。`_load_facts` 捕获 `UnicodeDecodeError` → WARNING（**点名该文件**）+ 返回空列表 ⇒ `<memory>` 块不注入、run 照常完成；文件字节一字不动（只降级注入、不改写内容）。**冻结边界更新**：原「必须 fail-loud」改为「注入路径 fail-soft + 可定位告警；写路径（`fact_add` → `FactStore.add`）的同类失败已由 `ToolExecutor` 的 catch-all 兜成 `is_error=True` 的工具错误、不中断循环」——两条路径都不得吞掉或改写文件内容。
- **证据**：探针 `.heagent/tmp/gbk_probe.py` 实测 `RAISED UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd6 in position 2`；改动 = `src/heagent/memory/facts.py`（+19/−2）+ 4 例测试（`tests/test_memory.py::TestFactStoreNonUtf8File` 3 例 + `tests/test_agent_loop.py::TestAgentLoop::test_run_survives_undecodable_memory_file` run 级端到端），commit `b01e09c`；`src/heagent/agent/run_lifecycle.py`（`asyncio.to_thread(loop._build_system, …)` 无捕获）。负向验证：回退该守卫（HEAD 版 `facts.py`）+ 新 4 例 → **4 failed**，run 级用例的 traceback 正是本条目声称的链路（`run_lifecycle.init_new_run` → `_build_system` → `build_system_prompt` → `_memory_block` → `read_text`）；全量 `pytest -q` 2530 passed。**非本次改动引入**（改动前同样直调 `facts.load()`），故按 defer 记录。
- **同域后续（非本条范围，仅备查指针）**：`95fe8f6` 修「MEMORY.md 带 UTF-8 BOM 时首条事实被静默丢弃」（新增 `_strip_bom`，读路径与写路径统一剥离、写回归一化为 UTF-8 无 BOM）；`1b8aa8f` 单点修 frontmatter 层同类 BOM（两个分隔符变体的正则容忍文件头 BOM，skills/slash/roles/artifacts/goal/skill_packages/workflow 一次覆盖）；两者均**未另立台账条目**（2026-09-23 用户裁定）。

---

## A3 入口层职责再拆（cli.py / cli_goal.py）

- **来源**：2026-09-17 架构与代码优化勘察（活动编号 A3；原编号见该轮勘察表）。
- **问题**：`cli.py`（2026-09 中旬 1163~1565 行，6+ 类职责：Click 命令层 / provider 装配 / REPL 与斜杠命令 / 会话与展示辅助）与 `cli_goal.py`（1150+ 行）职责混杂，难读难测；`wiring.py` 先例（docstring 记录拆分理由）已给出拆分范式。
- **冻结边界**：只挪代码不改行为；大量测试 monkeypatch **模块路径缝**（`heagent.cli._run_prompt`、`cli.sys`、`cli_goal._goal_session` 等）——被 patch 的目标函数**及其调用方**必须留在同一模块。
- **结论**：**已闭合**（2026-09-26；commits `49168b4`（收进包）+ `42d7331`（包内再拆），另 `ea2e347` 收纳入口辅助 `slash`/`terminal`/`wiring`/`housekeeping`）。分两批交付：
  1. **收进包**：七个平铺 `cli*.py` → `heagent/cli/` 包（`console.py`/`init.py`/`goal.py`/`http.py`/`tcp.py`/`dialogs.py`/`display.py`），`__init__.py` **零 import**，入口脚本改指 `heagent.cli.console:main`；契约测试按**包根** `heagent.cli` 收敛入口层判据，并新增「包壳零 import」「布局钉死」「入口点可导入」三条断言。
  2. **包内再拆**：`cli.py`（1252 行）拆为 `console.py`（443：命令层 + 启动编排）/ `composition.py`（322：装配）/ `interactive.py`（587：单次/交互执行 + 斜杠命令族）；`cli_http.py`（1139 行）拆为 `http.py`（454：服务与生命周期装配）/ `http_console.py`（740：项目/会话/配置面）。缝按**调用方**分模块落位：`_run_prompt`/`_run_single` 在 interactive（console 侧用函数内导入读 `_run_single`）、`_build_loop` 在 composition（网络侧函数内导入）、`_run_cli_impl`/`_mcp_lifecycle`/`_build_provider` 留在 console（其调用方在此）。
- **验证（实测）**：全量 `pytest` **3149 passed** / 覆盖率 **92%**（门限 87；`interactive.py` 按交互层口径 omit）/ `ruff check`+`format --check` 全绿 / `mypy src` 与 `--platform linux` 双绿（151 files）；拆分批次的负向验证 **3/3 精确变红**（① console 把函数内导入改成模块级 ⇒ `test_cli_tcp` 红；② `cli/http_console.py` 的 `_build_loop` 延迟导入改指 interactive ⇒ `test_cli_http` 3 例红；③ interactive 多导入 `_goal_session` ⇒ 缝钉死用例红），全部字节还原并复核 sha256。
- **剩余口径**：`console.py` 仍是命令层与启动杂务的合理归处（443 行）；`composition.py`/`interactive.py` 如需再分，须同样按「缝随调用方」迁移并同步 `tests/test_architecture_contracts.py` 的布局表。

---

## Z-D16 会话 id 放行 Windows 保留设备名（静默丢数据）

- **来源**：2026-09-26 Epic 50 第四轮评审（探针 `.heagent/tmp/rev50_probe.py`）。按「非本 Epic 引起的既有问题」登记——`_SESSION_ID_RE` 由 2026-07-21 `cc7fd5d` 引入，Epic 50 只是把同一字符集镜像进 `http_console_protocol`。
- **原条目正文（保留原文以存证）**：

- source_spec: `src/heagent/context/session.py`（`_SESSION_ID_RE`，2026-07-21 `cc7fd5d` 引入；Epic 50 第四轮评审发现——Epic 50 只把同一字符集镜像进 `http_console_protocol.SESSION_ID_PATTERN`，故按「非本 Epic 引起的既有问题」登记）
  summary: **会话 id 放行 Windows 保留设备名 ⇒ 整段对话静默丢弃**：`[a-zA-Z0-9_-]+` 字符集天然放行 `NUL` / `CON` / `PRN` / `AUX` / `COM1`，而 Windows 把 `NUL`（含 `NUL.json` 这类带扩展名的形式）解析为**空设备**：`exists()` 恒 True、读取得空串 ⇒ `load()` 静默返回「空历史」（伪装成没有历史），`save()` 写向空设备 ⇒ 对话既不落盘、也永远不出现在 `list_metadata`（既不列表也不在盘上）。触发条件：`heagent --resume NUL`（或 `CON` / `PRN` / `AUX` / `COM1`，`cli.py` 的 `--resume` 不过任何额外校验）；严重度：低（需用户显式输入保留名；无权限后果，是**静默丢数据**）；冻结边界：**不得**因此放松 id 字符集（那是路径遍历防线），只允许在字符集之外**追加**保留名拒绝。
  evidence: 实测（2026-09-26 亲跑 `.heagent/tmp/rev50_probe.py`）：`os.path.exists('NUL.json') = True`、`os.path.exists('CON.json') = True`（`PRN` / `AUX` / `COM1` 为 False）、`SessionStore.path_for('NUL')` 通过校验；`session.py::_validate_session_id` 只查字符集与长度，`cli.py` 的 `--resume` 无额外守卫。
  Progress（2026-09-26 登记，**未修**）：修法很小（追加一个保留名元组 + 单测），但属既有缺陷类，第四轮评审按纪律只登记不顺手改（评审不做范围外重构）。

- **结论**：**已闭合**（2026-09-27）。三处同步（缺一即漂移）：① `context/session.py` 新增 `WINDOWS_RESERVED_DEVICE_NAMES`（22 项 = `CON` / `PRN` / `AUX` / `NUL` + `COM1-9` + `LPT1-9`，用 `.upper()` 比较承担大小写不敏感），私有 `_validate_session_id` 转公开 `validate_session_id`（存储内 7 处调用点同源），**在字符集之外追加**保留名拒绝——字符集与长度判据一字未动；② `network/http_console_protocol.py` 加镜像 `SESSION_ID_RESERVED_NAMES` 并让 `is_valid_session_id` 用同一判据（网络层不得 import 运行栈 ⇒ 只能各持一份，靠测试钉住逐元素相等）；③ `cli/console.py::_run_cli_impl` 对 `--resume` 早期校验，非法时命令层给 `ClickException`（可读错误 + exit 1）而非 traceback，且校验发生在 provider 构造**之前**（零副作用、无密钥也能复现）。
- **验证（实测）**：新增 19 例测试（`tests/test_session.py::TestReservedDeviceNames` 14 例 + `::TestValidateSessionIdShape` 1 例；`tests/network/test_http_console_sessions.py` 语料扩到含全部保留名与 `nul` / `Con` 大小写变体 + 集合相等断言；`tests/test_cli.py` 正反对照 2 例）。**变异体负向验证 4/4 精确变红**（`.heagent/tmp/mutate_reserved_names.py`）：M1 存储侧集合清空 → 11 failed；M2 删除拒绝分支 → 9 failed；M3 网络层退回纯字符集 → 1 failed；M4 删除 CLI 校验 → 1 failed；每处字节还原后基线复绿。全量 `pytest -q` **3173 passed / 11 skipped / 18 deselected**；`ruff check` + `ruff format --check`（285 files）全绿；`mypy src --platform linux` 无 issue。
- **残余（同族，已核实无落地点，仅备查）**：会话**标题**是 JSON 字段、不参与文件名构造；项目 **id** 由路径规范化派生（`p` + 8 位十六进制）⇒ 两处都不受保留设备名影响，无需同类检查。

---

## Z-D17 会话 `.json.lock` 无回收方（随会话数单调增长）

- **来源**：2026-09-26 Epic 50 第四轮评审（探针 `.heagent/tmp/rev50_probe2.py`）。按「非本 Epic 引起的既有问题」登记。
- **原条目正文（保留原文以存证）**：

- source_spec: `src/heagent/context/session.py`（`prune` / `delete` 只认 `.json`；Epic 50 第四轮评审发现）
  summary: **`.heagent/sessions/<id>.json.lock` 没有回收方，随会话数单调增长**：每次 `save` / `create` / `rename` 都经 `pub.persist.atomic_update_text` 建一个 0 字节锁文件，而 `SessionStore.prune` 走 `prune_entries_by_mtime(suffix=".json")`（`str.endswith(".json")` 对 `X.json.lock` 为 False）、`delete()` 也只删 `.json` ⇒ 锁文件永久留存。触发条件：任何会话写入；严重度：低（inode / 目录项累积，无功能影响；历史同类账：runs 目录曾累积 6 万文件 / 703 MB）；冻结边界：**不得**用「删掉锁文件」当回收手段——`persist` 的注释已写明删除会引入「B 等旧 inode、C 拿新文件加锁成功」的竞态；要修就得给锁文件定寿命策略（例如按 `st_mtime` 判「无人持有」后删除），属 `persist` 层设计决策。
  evidence: 实测（`.heagent/tmp/rev50_probe2.py`）：构造 400 天前的 `deadbeef.json` + `deadbeef.json.lock` 后 `prune(retention_days=30)` 返回 1，目录残留 `['deadbeef.json.lock']`；`pub/persist.py` 注释声称「过期 `.lock` 由各自的 prune 随记录一并回收」——对 sessions 不成立（`engine/store.py` 才是正确做法的先例）。

- **结论**：**已闭合**（2026-09-27）。新增 `pub/persist.reap_dangling_locks(directory, *, min_age_seconds, limit)`（三条判据**全中**才回收：① 同名记录已不存在；② 锁文件自身 mtime 早于门槛；③ **当前无人持有**——`timeout=0` 非阻塞排他加锁证明，拿不到即跳过，沿用 `persist`「不猜测」的立场），由 `SessionStore.prune` 以 `min_age_seconds=retention_days × 86400` 调用（`retention_days <= 0` = 关闭时不回收，与 prune 语义一致）。**冻结边界守住了**：回收只作用于**孤儿**（在用会话的锁两条门槛都不满足：同名记录仍在、且年龄未超限），且不使用「按 mtime 猜持有状态」这种弱判据——这正是原冻结点名的方向（「给锁文件定寿命策略」）的强化版。顺带修正 `persist` 注释里一句**不成立**的论断（原称「过期 `.lock` 由各自的 prune 随记录一并回收」，对 sessions 为假；runs / ledger 才是「随记录同批回收」，sessions 走本条的孤儿回收）。
- **证据（2026-09-27 亲跑）**：探针 `.heagent/tmp/lock_probe3.py` 实测——50 次 `save` ⇒ 50 个 `.json` + 50 个 `.json.lock`（各 1 字节，Windows 侧哨兵）；记录老化后 `prune(30 天)` 删除 50 条记录、锁**因年龄未到而保留**（符合设计）；`delete()` 不回收（新锁，年龄门槛挡住）；一个老化到 2001 年的孤儿锁 `deadbeef.json.lock` 在 `prune` 后被回收（`存在=False`）。真实工作区（同日只读统计）：`.heagent/sessions` 341 目录项 / 322 个 `.lock` / **12 个孤儿**；对照 `.heagent/runs` 40 096 个锁、孤儿 0，`.heagent/ledger` 37 000 个锁、孤儿 2 —— 与「runs/ledger 随记录同批回收、sessions 不回收」的判断一致。
- **验证（2026-09-27 亲跑）**：新增 4 例测试（`tests/test_file_locking.py::TestReapDanglingLocks` 3 例：只回收超龄孤儿 / **持有中的锁绝不回收** / 缺目录与空目录返回 0；`tests/test_session.py::TestSessionPruneReapsOrphanLocks` 1 例：prune 回收超龄孤儿锁且不动在用会话的锁）。变异体 **4/4 精确变红**（`.heagent/tmp/mutate_reap_locks.py`）：M1 去掉孤儿判据 / M2 去掉年龄门槛 / M3 去掉「无人持有」证明 / M4 去掉 prune 接线；**M3 首轮不红**——Windows 上「持有句柄的文件本就 unlink 不掉」把缺证明的形态遮住了，故给该用例加一条 spy 断言（回收前必须发生 `timeout=0` 的加锁尝试），据此 M3 变红；每处字节还原后基线复绿。全量 `pytest -q` **3183 passed / 11 skipped / 18 deselected**；`ruff check` + `format --check`（285 files）与 `mypy`（本机 + `--platform linux`）全绿。
- **复审补强（2026-09-27 同日后复审）**：回收前先 `is_symlink()` 跳过——与本项目其它 GC（沙箱会话目录、编辑快照）同立场「符号链接一律不动、绝不穿透」：删除链接会误伤别人的锁，跟随链接还会删到目标。回归 `tests/test_file_locking.py::TestReapDanglingLocksSymlinkGuard`（本机无法建真符号链接，判据钉在 `Path.is_symlink` 桩上）；变异体去掉该护栏 ⇒ 精确变红。
- **残余（如实记录，未消除）**：Windows 无法在持有句柄时 `os.unlink`（句柄会让 unlink 报 `PermissionError`），故先 `close` 再 `unlink`，其间存在 **µs 级窗口**；POSIX 则在持有期内 unlink。两种形态都仍需「写入方已打开旧 inode 但尚未加锁」与「第三个写入方落在同一窗口」同时成立，且对象必须是孤儿 id（记录已回收、锁年龄超限）才会失效。触发概率极低、后果仅是该 id 的一次并发写覆盖，故按低危接受。**要彻底消除需改变锁的落点协议**（每目录固定分桶锁：锁文件数恒定、永不需要回收），属独立设计决策，未在本次擅自实施。

## A5 观测粒度残余（facade `run_failed` 无耗时 / 并行批次不逐 story 发事件）

- **来源**：架构优化周期 phase5（`arch-optimization-cycle/phase5-observability-benchmarks-docs.md` 的 Change Log ② + C1 测试注释）；2026-09-27 复核时按「条目闭合后归入勘察类闭合归档」规则由活动区移入本文件。
- **原条目正文（保留原文以存证）**：

- source_spec: `_bmad-output/implementation-artifacts/arch-optimization-cycle/phase5-observability-benchmarks-docs.md`（Change Log ② + C1 测试注释）
  summary: **观测粒度残余**：① `AgentLoop._on_run_failed` façade 包装路径的 `run_failed` 事件恒 `duration_ms=0`（未计时；真实路径 `execute_run`/`stream_run` 已带全程耗时）；② workflow story batch（`max_parallel_stories>1`）路径事件为**整批一条** started/completed，非逐 story。触发条件：消费方（GUI/replay 分析）需要该粒度时；严重度：低；冻结边界：不加字段不改既有事件语义，仅补测量与发射。
  evidence: `src/heagent/agent/loop.py:_on_run_failed`（未透传 duration）；`engine/workflow_runner.py:_run_story_batch`（批内 gather 不逐 story emit）。

- **结论**：**已闭合**（2026-09-23，commit `1f99cc0`「补齐事件耗时与逐 story 观测粒度」）——**两半都在那一次交付里修掉了，只是台账未同步**：
  ① `AgentLoop._on_run_failed` 增加 `duration_ms: int | None = None`，缺省时由 `run_lifecycle.on_run_failed` 用 `run_elapsed_ms(loop)` **现算**（run 起点记在 `_run_started`，注释明确写「含 facade 的 `_on_run_failed` 路径」）⇒ façade 路径不再恒报 0；
  ② `WorkflowRunner._run_story_batch` 在**批级事件之外**为批内每条 story 各发一组 `workflow_step_started/completed/failed`（带自己的 `story` / `duration_ms` / `error_kind`）。
- **冻结边界（守住）**：不加字段、不改既有事件语义，只补测量与发射——**批级那条 started/completed 仍在**（它标记「这一步」，测试注释写明「整批一条」），逐 story 事件是**新增的另一组**，不是替换。
- **证据**：`tests/test_run_status_contract.py::TestRunStatusContract::test_failed_run_reports_measured_duration`（provider 睡 30ms 后抛错 ⇒ `duration_ms >= 20`）与 `::test_facade_on_run_failed_reports_measured_duration`（直接调 façade 的同名断言）；`tests/test_story_loop.py::test_parallel_batch_emits_per_story_events`（同时断言批级一条与逐 story 两条）与 `::test_parallel_batch_failed_story_reports_its_own_failure_event`；文档已记在 `docs/frame.md` 的事件契约表（`run_failed` 的「duration（缺省由 `run_elapsed_ms(loop)` 现算——facade `_on_run_failed`…」与 `workflow_step_*` 行）。
- **本轮复核（2026-09-27 亲跑）**：`pytest -q` 全量 3097 passed；`grep` 复核台账原登记的三个落点（`agent/loop.py:_on_run_failed`、`engine/workflow_runner.py:_run_story_batch`、事件契约表）均已符合结论。
- **证据迁移（2026-10-07，Story 51-8 fail-closed 串行化）**：并行批次机制整体移除（`_run_story_batch` 已删），其两个测试随之删除；**逐 story 事件粒度由串行路径天然继承**——`run_step` 每执行一条 story 各发一组 started/completed/failed（`story` 非空，带 duration/error_kind），frame.md 契约表 `workflow_step_*` 行已同步。本条闭合结论不受影响。

---

## A23 掩码域后缀制 —— 裁定维持现状

- **来源**：Epic 50 第四轮评审（2026-09-26 登记，`_bmad-output/epics/epic-50-网页控制台周期/ARCHITECTURE-SPINE.md` §288）。
- **问题**：掩码域只认 `*_API_KEY` / `*_API_KEYS` 后缀，而 `*_BASE_URL` 中的凭证（如 `https://user:token@relay/v1`）会被原样回显；`GET /api/projects/{id}/config` 无回环门 ⇒ 任何能连到服务的客户端都能读到。
- **结论**：**裁定维持现状**（2026-09-27）。理由：① URL 本身不以凭证命名；② 部分掩码会破坏诊断用途（"为什么连不上"需要完整 URL）；③ 同仓 `safe_logging` 已对 URL userinfo 脱敏，口径分场景。补充至 `docs/frame.md` 五（已知缺口）。
- **证据**：`config/catalog.py`（`is_secret_key` / `EXCLUSION_GROUPS`）；`docs/frame.md` 新增行「配置掩码域是后缀制」。

## A11 非回环运行姿态（详细）—— 已闭合

- **来源**：Epic 50 收口评审三镜头（2026-09-24 登记）。
- **问题**：两条相关的主张冲突：
  - ① 回环闸门只装在「登记/移除项目」，而危害更大的 `POST /api/projects/{id}/runs`（可跑 shell/文件工具）、会话增删改都没有闸门
  - ② `enable_cron=False` 只拒了调度器：`cron_store` 仍被绑进 loop ⇒ 网页运行可以成功写入 `<项目>/.heagent/cron/jobs.json`，任务在本进程 IDLE 永不触发，却会在后续 CLI 会话里无人监督地执行
- **结论**：
  - **② 已闭合**（2026-09-27，commit `5a8a21e`）：`cli/composition._build_loop` 在 `enable_cron=False` 时连 `JobStore` 都不构造，`HttpAgentHandler.new_loop()` 新增守卫（loop 若绑了 cron 工具即显式失败）
  - **① 已裁定维持现状**（2026-09-27；同日曾另立 A20「非回环运行姿态（总结）」，**2026-09-28 编号统一时并入本条**）：这是 Epic 49 的设计姿态（项目重命名 / 四个会话写操作 / 项目内运行入口没有回环门），Epic 50 未扩大暴露面；网页入口无认证无 TLS，真正边界是 OS 级沙箱；加回环门会破坏既有端点契约。`docs/frame.md` 缺口行已从「待裁决」改为「裁定维持现状」。
- **证据**：
  - `cli/composition.py:116`（JobStore 构造条件）+ `:165`（传给 loop）
  - `cli/http_console.py:260`（`enable_cron=False`）与 `:264`/`:265`（守卫）
  - `tests/test_cli_http.py::test_new_loop_refuses_to_own_a_cron_scheduler`
  - `docs/frame.md` §4.17「运行隔离」已补该不变量

## A17 R5 收敛判据失效 —— 裁定收紧规格

- **来源**：Epic 50 Story 50-8 收口后评审（2026-09-26 登记）。
- **问题**：`_looks_like_a_failure()` 用字符串前缀 `Error:` 区分失败与内容，成功读取以 `Error:` 开头的文件时，整份正文会照旧显示在网页对话区。
- **结论**：**裁定收紧规格**（2026-09-27）。在 AC9 补充「正文以 `Error:` 开头的文件不在收敛范围内」，补充至 `docs/frame.md` 五（已知缺口）。
- **证据**：`cli/http_console.py::_looks_like_a_failure`；`docs/frame.md` 缺口行已补充该限制。

## A19 目录选择端点默认开 —— 裁定默认改按需

- **来源**：Epic 50 Story 50-8 实现（2026-09-24 登记）。
- **问题**：`POST /api/dialogs/pick-directory` 默认开启（`dialog_backend="auto"`），在默认 CLI 的内嵌服务中也生效，但内嵌路径无关闭手段。与配置写入通道的 `HTTP_CONSOLE_WRITE_ENABLED` 默认 False 惯例相反。
- **结论**：**裁定默认改按需**（2026-09-27）。修改默认值为 `"none"`，需要时显式传 `--dialog-backend auto` 开启。与配置写入惯例一致。
- **修改**：
  - `cli/http.py:362`：`--dialog-backend` 选项默认值 `"auto"` → `"none"`，帮助文本同步
  - `cli/http_console.py:440`：`HttpProjectConsole.__init__` 参数默认值 `"auto"` → `"none"`
  - `docs/frame.md`：缺口行已更新为「默认关闭」
- **证据**：代码修改已提交；文档已同步更新。

## A24 GUI 事件日志在环形缓冲满后永久停止渲染（+ 暂停即丢事件）—— 已闭合

- **来源**：2026-09-28 A4（GUI 原生事件渲染）评估期的只读勘察发现——不在原台账内，当日登记、当日闭合。
- **问题**（两处，均在 `gui/widgets/event_log.py`）：
  - ① **差分冻结**：`_poll` 用「缓冲窗口长度 − 已渲染数」做差（`recent[: len(recent) - self._last_rendered_idx]`），
    而窗口一旦到达 `get_recent(limit=200)` 的上限，两者恒相等 ⇒ 差为 0，**此后永久不再渲染**
    （长 run 里的 `tool_call_*` / `run_failed` 全部不显示）；
  - ② **暂停即丢事件**：暂停分支在 return 前照样推进了索引 ⇒ 恢复后那段事件永久丢失
    （`paused` 的语义是「暂停渲染/滚动」，不该丢数据）。
  - 附带：`details.get("tool_name")` 恒为空（观察者没把 `tool_name` 放进展示字典）⇒ `tool=` 从未显示过。
- **结论**：**已闭合**（2026-09-28）。修法：
  - 差分改走事件生产者侧的**单调总数**：`GuiEventObserver.total` + `snapshot()`；纯逻辑（`EventCursor`）
    与行格式化（`format_event_line`）落在 `heagent.pub.event_lines` —— **不放 GUI 包**，因为
    `heagent.gui.*` 的导入要求 textual（可选依赖），写在 GUI 里则 CI（test job 不装 textual）永远跳过判据；
  - 暂停期间不推进游标（恢复时补渲染），窗口溢出时显式提示「丢了几条」；
  - 渲染补齐耗时 / 失败分类 / 迭代 / 作用对象 / workflow 步骤与 story，且整行经 `rich.markup.escape`
    （事件值不可信，防 RichLog 标记注入）。
- **冻结边界**：事件契约（`EngineEvent` 字段集 / `kind` 开集）未动，只改**展示层**如何读它；
  GUI 仍是 GUI（不改 CLI 文案，也不碰 `/goal` 的 stderr 转发 —— 那是 A4 的另一片，需另行裁决）。
- **证据**：`src/heagent/pub/event_lines.py`（新增）；`src/heagent/gui/observers.py`（`total` / `snapshot` /
  补 `tool_name`）；`src/heagent/gui/widgets/event_log.py`（薄壳）；`tests/test_event_lines.py`（14 例，
  含「缓冲满后仍持续渲染」的回归判据与「GUI 薄壳不得退回索引差分」的结构性判据）。
- **验证（2026-09-28 亲跑）**：`pytest tests/test_event_lines.py -q` → 14 passed；变异体 **6/6 精确变红**
  （`.heagent/tmp/mutate_a4a.py`：GUI 薄壳退回索引差分 / 游标退回旧公式 `len(available) - seen` /
  去掉耗时渲染 / 游标不推进 `seen` / `_project_entry` 退回遍历 `list()` / 删掉 A16 的迁移条件 docstring），
  每处按 sha256 字节还原后基线复绿。
## A4 GUI 原生事件渲染（事件驱动渲染 + 消息 sink）—— 已闭合

- **来源**：架构优化周期 Phase 5 的 V-系列排除项（「不把 GUI 的 stderr 转发升级为原生渲染」）+ C3 文档收口结论；2026-09-28 交付并闭合。
- **原问题**：GUI 的观测面有两处「借 CLI 的」：① 事件日志只渲染 `event_type`/`tool_name`/`error`/`run_id`（
  `EngineEvent.details` 里现成的 `duration_ms` / `error_kind` / `iteration` / `target` / workflow 步骤字段一律不读）；
  ② `/goal` 的进度靠 `contextlib.redirect_stderr` 截获 CLI 文案——那是**整个 stderr**，把 `logging` 记录与第三方输出
  一并吞进对话区（GUI 的日志 handler 正挂在 stderr 上）。
- **结论**：**已闭合**（2026-09-28，两片交付）：
  - **① 事件驱动渲染**：差分改走观察者侧**单调总数**（`pub/event_lines.EventCursor`），渲染补齐耗时 / 失败分类 /
    迭代 / 作用对象 / workflow 步骤与 story；同轮修掉「缓冲满 200 条后永久冻结」与「暂停即丢事件」（→ **A24**），
    以及 `tool_name` 从未进展示字典、整行未 `escape`（RichLog 标记注入）两处既有缺陷；
  - **② 替掉 stderr 转发**：`cli/goal.py` 的 40+ 处输出收敛到单一出口 `_echo`，`_goal_runner(on_message=…)` 用
    ContextVar 绑定 **消息 sink**；GUI 传 sink（文案与 CLI 逐字相同，只是不经 stderr），并让 GUI 日志**只落文件**
    （TUI 独占终端，日志不再写 stderr，也不再进对话区）。
- **冻结边界（守住）**：`click.echo(..., err=True)` 的默认路径**逐字保留**（CLI 行为零变化，`_echo` 仅在绑定 sink 时改投递）；
  EngineEvent 模型与 `kind` 开集未动；`/goal` 的 CLI 文案（冻结契约）未改一字。
- **有意不做（残余）**：**A4c** = 丢掉 CLI 文案、纯由事件流自绘 `/goal` 进度 —— 与「文案冻结」冲突且必然出现两份措辞漂移，**不做**；
  保留 CLI 文案为唯一措辞来源。**未做项**：GUI 聊天区的「工具结果行」显示耗时需要 `StreamEvent` 新增字段（当前只有 EngineEvent 侧有），
  属新增小项，未登记。
- **证据**：`src/heagent/pub/event_lines.py`（新增）、`src/heagent/gui/{observers.py,widgets/event_log.py}`、
  `src/heagent/cli/goal.py`（`_MESSAGE_SINK` / `_echo` / `_goal_runner` 薄包装）、`src/heagent/gui/screens/chat.py`（sink）、
  `src/heagent/gui/cli.py`（日志只落文件）；判据 `tests/test_event_lines.py`（14 例）、`tests/test_goal_message_sink.py`（6 例）、
  `tests/test_gui_goal.py`（5 例，含「日志 / 原始 stderr 不进对话区」）。
- **验证（2026-09-28 亲跑）**：变异体 **A24 组 6/6 + A4b 组 5/5 精确变红**（`.heagent/tmp/mutate_a4a.py` / `mutate_a4b.py`：
  GUI 薄壳退回索引差分 / 游标退回旧公式 / 去掉耗时渲染 / 游标不推进 `seen` / `_project_entry` 退回遍历 `list()` /
  删掉 A16 迁移条件 / GUI 不传 sink / 退回 stderr 全量捕获 / `_echo` 忽略 sink / runner 不绑 sink / GUI 日志回写 stderr），
  每处按 sha256 字节还原；定向 12 + 136 passed；全量 `pytest -q` → 3159 passed / 14 skipped / 18 deselected（0 failed）；
  `ruff` 与 `mypy`（本机 + `--platform linux`）全绿。

## A8 跨项目并发无全局上限 —— 裁定维持现状（2026-09-28）

- **来源**：Epic 50 规划评审（D9 采纳后的已知缺口，2026-09-24 计划期登记；对偶义务见 50-7 T10⑨）。
- **问题**：D9 裁定「并发随项目数线性增长」——在途运行上限 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`（默认项目上限 32 × 1 ⇒ **最多 32 个并发 run**），跨项目不共享名额、不做全局调度；而 `HTTP_MAX_CONNECTIONS`（默认 16，由 Uvicorn `limit_concurrency` 承担）**不随项目数放大** ⇒ 多项目并行时**连接层可能先于运行层成为瓶颈**。
- **结论**：**裁定维持现状**（2026-09-28）。理由：① 「并发随项目数线性」是 D9 的**有意语义**（多项目并行是有意能力，代价是资源占用线性上升）；② 服务级总额已作为**可选键**交付（`HTTP_MAX_TOTAL_INFLIGHT`，默认 **0 = 不限**，超限 409 `total_inflight_limit`，与 per-service 的 `run_conflict` 分开）⇒ 要收口时运维可显式设置，把默认改成有界属产品裁决，本轮不改。**冻结边界**：不得为它改回「跨项目共享在途名额」，不得改写既有 `HTTP_MAX_INFLIGHT_RUNS` 的 per-service 语义（只允许**新增**全局限流键），也不得把 `HTTP_MAX_CONNECTIONS` 随项目数放大。
- **证据**：`config/__init__.py:359`（`http_max_total_inflight: int = Field(default=0, ge=0)`）；`network/http_server.py:187`（`HttpServerConfig.max_total_inflight`）+ `:513`（判定单点 `len(self._active)`，与运行记录同源）；`cli/http.py:83/130/307`（`--max-total-inflight` 与 Settings 接线）；`network/http_protocol.py` 的 `TOTAL_INFLIGHT_LIMIT`；`web/app.js` 的码表中文文案（闭集契约按枚举派生）。判据 6 条、变异体 **5/5 精确变红**（`.heagent/tmp/mutate_total_inflight.py`）。
- **文档落点**：`docs/frame.md` 五「跨项目并发默认无全局上限（**D9 已裁定**）」+ 4.18（并发口径）。

## A10 控制台端点在唯一事件循环里做同步 I/O —— 裁定维持现状（唯一残余有意保留，2026-09-28）

- **来源**：2026-09-24 Epic 50 收口评审（三镜头）·「控制台阻塞 I/O 与会话列表成本」。
- **问题**：`list_sessions`（逐文件全量读 + 无 title 时全量校验）、`build_config_report`、`registry.list()`（每请求每条一次 `Path.is_dir()`）、`registry.touch()`（跨进程文件锁 + 原子写）都是 `async def` 体内的**阻塞**调用，会卡住在途 SSE 流与其余请求；且 >1 MiB 的会话在列表时被**整份读入**。
- **结论**：**裁定维持现状**（2026-09-28）——三轮续修后只剩一处残余，且**有意保留**：
  - **已闭合面**：会话读（`list_metadata` / `load` / `start_project_run` 前的 `_resolve_session`）、`build_config_report` 两处、`registry.touch`、`list_projects` 的 `registry.list()`、dream 会话预注入**全部**离线到 `asyncio.to_thread`（判据取**线程身份**而非耗时）；>1 MiB 会话改**有界头部读**（`_read_head` + `_metadata_from_head`，`message_count` 恒 `None`，与 D6「列表可退化」口径一致；`"messages"` 之前的区段才认元数据字段，避免工具参数的 `"title"` 被当标题）。
  - **残余（有意保留）**：`_runtime_for` → `_project_entry` 解析项目仍是同步调用。**2026-09-28 已把 stat 面收敛**：新增 `ProjectRegistry.find`（1 次注册表读 + **1 次** `Path.is_dir()`；此前每请求遍历 `registry.list()` = 1 读 + ≤33 stat），剩余即这 1 读 + 1 stat。停手理由：同步私有助手改 async 要连带改 10 个 `_runtime_for` 调用点，churn 大于收益。**升级条件**：控制台端点 P95 超过 SSE 心跳（15s）的 1%，或 `MAX_PROJECTS` 从 32 上调。
- **证据**：`cli/http_console.py:482/521/523/553/558/603/615/630/655/669`（各 `to_thread` 落点）、`:727`（`_project_entry` 走 `registry.find`）、`:735`（`_runtime_for`，保留）；`context/session.py:620/637`（有界头部读）。判据 6 + 1 例，变异体 **5/5 精确变红**（`.heagent/tmp/mutate_console_io.py`）。

## A12 浏览器级 UI 验收不在 CI、也不含真实 LLM 运行 —— 裁定维持现状（保持手动，2026-09-28）

- **来源**：2026-09-24 Story 50-6 / 50-8 实现（浏览器验收与 UI 优化轮）。
- **问题**：`tests/js/console_acceptance.mjs` 需要真实 Chrome/Edge（CDP）+ `heagent[http]`，而 CI 侧**没有任何浏览器**（workflow 里没有 node / 浏览器步骤，依赖也不含 playwright/puppeteer；install 步骤只装 `.[dev,gui,http]`（lint job）与 `.[dev,http]`（test / coverage / benchmark / goal-smoke））⇒ 只能**手动**跑；另该次验收**没有**跑「真实模型 → SSE → 对话区流式渲染」这条链（本机无可用 provider）。**2026-09-24 实例（「一次通过 ≠ UI 无回归」的最强证据）**：50-6 的 17/17 通过之后仍漏掉「首页确认遮罩吞掉真实鼠标点击」（`hidden` 属性为真而计算样式 `display:flex`）——清单只断言属性、且 `click()` 走 DOM API **绕过命中测试**；修复后清单扩至 18 行，Story 50-8 增量轮再扩至 **23 行**。
- **结论**：**裁定维持现状 = 保持手动**（2026-09-28，用户裁定）。理由：① 冻结边界明确禁止「为让浏览器验收进 CI 而给 dev 依赖加 playwright/puppeteer」（保持零构建链与「GUI / 浏览器不进 CI」的既有立场）；② 真浏览器这一步**不可省略**（CSP 是否生效、有无第三方请求、窄屏计算样式只有真浏览器能证明），但它是**发布前的人工关卡**，不进 CI 门；③ 「真实模型 → SSE → 流式渲染」的前端侧由 node 探针（`tests/js/app_probe.js` 用例 A/B/C/D/E/N）覆盖、服务端由 Epic 49 用例覆盖；本机无可用 provider，不把它升级为门禁。
- **证据**：`tests/js/console_acceptance.mjs`（自起真实 http-server + headless Chrome，CDP 驱动真实点击；23 行清单含窄屏 / 凭证零明文 / 磁盘副作用断言）；`tests/test_http_web_ui.py`（探针用例的 skipif 只要求 node，不要求浏览器）；`tests/test_cli_http_lifecycle.py`；验收输出 `epics/epic-50-网页控制台周期/reviews.md#acceptance-50-6-console-ui`（17/17 PASS，Chrome 153.0.8010.48）与 `#acceptance-50-8-refinement`（23 行）。
- **文档落点**：`docs/frame.md` 五「控制台 UI 无自动化回归」。

## A15 网页请求可拉起宿主 GUI 进程 —— 裁定维持现状（opt-in 暴露面，2026-09-28）

- **来源**：2026-09-24 Story 50-8（R2 原生目录选择）实现，**有意引入**的新暴露面。
- **问题**：`POST /api/dialogs/pick-directory` 会让**服务端所在机器**弹出一个原生窗口（子进程 `tkinter` / `powershell`）⇒ **任何能连上该端口的本机进程都能让服务机弹窗**（骚扰面），而「回环 peer」不等于可信（用户自己浏览器里的任意页面 peer 也是 `127.0.0.1`）。返回值**不是权限**（仍要走 `POST /api/projects` 的全套校验）。
- **结论**：**裁定维持现状**（2026-09-28）。理由：① A19 已把默认值改为 `none`（2026-09-27）⇒ 本暴露面从「默认开」降级为「**显式 opt-in 才出现**」，两个入口（`http-server` 与默认 CLI 的内嵌服务）默认都不装可用选择器；② 更强的授权（每会话令牌一类）属于「把非安全边界做厚」，**不做**——真正的边界仍是 OS 级沙箱。**冻结边界**：不得把它表述为安全边界，不得改成服务端目录浏览 API（那会把宿主目录结构开放给回环客户端），也不得让它绕过 `POST /api/projects` 的任何校验。
- **证据**：`cli/dialogs.py`（`resolve_backend` / 冻结脚本 `_TK_SCRIPT`+`_POWERSHELL_SCRIPT` / `DirectoryPicker` 单在途 + 300s 超时 + kill + 有界回收 / 只认 ASCII 标记行 + `is_dir()` 复验）；`network/http_server.py::_build_dialog_endpoint`（回环门 + POST-only + `dialog_unavailable` 503 / `dialog_busy` 409）；`cli/http_console.py::HttpProjectConsole.pick_directory`；**默认值判据 3 例**（控制台默认 / `http-server` 旗标默认 / 内嵌服务默认，2026-09-28 补——此前默认值**无任何用例覆盖**，改回 `auto` 不会变红；变异体 2/2 精确变红）；浏览器清单 `reviews.md#acceptance-50-8-refinement` 的 A5b / B2。
- **文档落点**：`docs/frame.md` 4.18（安全声明段）+ 五「网页请求可拉起**宿主 GUI 进程**」。

## A16 真实原生窗口不可自动化 + 网页侧 `Error:` 前缀判据 —— 裁定维持现状（2026-09-28）

- **来源**：2026-09-24 Story 50-8（R2/R5 的验收与判据残余）。
- **问题**：① **真实原生窗口无法自动化验收**——选中并确认需要人眼与人手，浏览器清单只能覆盖「按钮存在」「不可用路径」「取消 / 超时」；`tkinter` 子进程脚本在 CI 里**永不执行**（Linux 镜像可能无 `python-tk`），只钉了「能编译 + 标记行 / 标题插值唯一」；② **网页侧读取结果收敛依赖 `Error:` 前缀约定**——内置工具用**返回值** `Error: …` 表达可预期失败（`is_error` 仍为 `False`），`file_read` 的失败消息因此靠 `_looks_like_a_failure()` 的字符串前缀识别；若把工具改成结构化错误而漏改判据，失败会**静默从页面上消失**。
- **结论**：**裁定维持现状**（2026-09-28）。① **人工验收是唯一路径**（冻结边界禁止为此给 dev 依赖加 playwright/puppeteer；也不得把真实弹窗的一次人工通过当作「选择器无回归」的充分证据）；② 迁移条件已**写进判据本体**（`cli/http_console.py::_looks_like_a_failure` docstring：「一旦工具错误结构化（抛 `ToolError` / `is_error=True`），本判据退化为只看 `event.tool_error` 并删除本函数，不要两套判据并存」），并有**结构性用例**钉住该 docstring 存在（删掉即精确变红）。
- **证据**：`tests/js/console_acceptance.mjs` 的 A5b / A11b / A11c / B2（真实浏览器，无真实弹窗点击）；`tests/test_cli_dialogs.py::TestSpawnDiscipline::test_frozen_scripts_are_valid_python_syntax`（只 compile 不执行）；`cli/http_console.py:138`（`_looks_like_a_failure` + 迁移条件）；`tests/network/test_http_console_sessions.py::test_failure_prefix_criterion_documents_its_migration_condition`；`tests/test_http_agent_api.py::test_read_tool_error_message_is_still_shown_in_web`。
- **文档落点**：`docs/frame.md` 五「网页侧读取结果收敛是**展示策略**，不是数据边界」。

## A1 技能资源读取 TOCTOU 后续 —— 裁定维持现状（2026-09-28）

- **来源**：Epic 46.1/46.2（技能资源并发替换安全评估，`_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/`）+ 2026-09-23 复核新增的非竞态缺口。
- **问题**（两条线）：
  - **竞态**：围栏解析之后、真正 `open` 之前的时间窗内，路径组件（最终组件或中间目录）可被替换成指向包根之外的符号链接；
  - **非竞态**：包资源**无内容凭据**——`manifest.lock` 只钉入口（`SKILL.md`）的 `source_hash`，而物化用 `copytree` 复制整棵包树（`references`/`templates`/`assets`/`scripts`），且读路径**从不读** lock ⇒ 包内漂移无人发现。
- **结论**：**裁定维持现状 = 本条闭合**（2026-09-28）。三条都已落地或已归为固有：
  1. **POSIX 逐组件 `openat`**（2026-09-27）：`_WALK_SUPPORTED` **导入期冻结**的能力门；中间目录 `O_DIRECTORY|O_NOFOLLOW`、叶 `O_NOFOLLOW`；撞符号链接时 `ENOTDIR`/`ELOOP` 双 errno 归因；
  2. **导入形态的内容钉 + 读时校验**（2026-09-28，A1④）：`SkillLockEntry.resources`（逐文件 sha256）+ **落地前复核**（关掉「算钉 → 复制」窗口，失败不留半成品）+ `SkillPackage` 读侧校验**包外** `manifest.lock`（老 lock 静默升级、未托管包零额外 open、渲染器凭据优先）；
  3. **其余为平台/形态固有**：Windows 无 `dir_fd` ⇒ 只保护最终组件；组件之间仍有时间差；凭据与包由同一写者掌控时可被同时改写。
  **冻结边界**：以上全部是 **defense-in-depth**，不得表述为安全边界（真边界 = OS 级沙箱，hostile filesystem/process context）；不得为「更干净」而放松 workspace 围栏或去掉 fail-loud 校验。
- **证据**：`tools/path_safety.py`（`_WALK_SUPPORTED` / `_open_walked` / `_open_dir_component` / `_is_symlink_at` / `read_bytes_under_root`）；`memory/skill_packages.py`（`_pinned_hashes` / `_renderer_hashes` / `_imported_hashes` / `_lock_entry` / `_verify_pinned_hash`）；`memory/skill_importer.py`（`SkillLockEntry.resources` / `_tree_hashes` / 落地前复核）。判据：`tests/test_skill_packages_toctou.py`（形状 + 「替换中间目录」竞态，仅 POSIX 跑；变异体 **5/5**）、`tests/test_skill_package_integrity.py`（两类凭据的读侧语义 + 未托管包零行为变化；变异体 **6/6**）、`tests/test_skill_importer.py`（钉整包 / 源侧漂移拒导 / 老 lock 补齐 / 落地前复核）。
- **文档落点**：`docs/frame.md` §4.14（两类凭据、两个加固通道、残余口径）。
- **仍未闭合面（如实保留在正文，不另立条目）**：**可信导入 snapshot**——物化**来源自身**的可信性；导入通道当前未激活（本仓 `.heagent/skills/manifest.lock` 实测不存在），若将来激活，按 Story 46.1 的 Ask First 重新评估。**Ask First 授权记录**：2026-09-27「授权引入专用代码」（逐组件 `openat`）、2026-09-28「继续」＝授权实施 A1④（导入物化/读取语义变更：手工编辑过的导入包将拒读）。

## A6 路径级审批分级 —— 裁定维持条件性（2026-09-28）

- **来源**：Epic 36–39 文件安全防护周期 brief 的 `### Deferred（未来考虑）`：「路径级审批分级（若未来引入非 workspace 的受控写场景）」。
- **问题**：审批粒度是**工具级**（`PolicyEngine.approval_tools` ∪ MCP `schema.annotations.destructiveHint`），**不看路径**；而 workspace 围栏（`evaluate_tool_call` 第 4 步 `_validate_paths`）对越界路径一律**硬阻断**（`ToolExecutionMode.BLOCKED`）⇒ 今天**不存在**「被批准的 workspace 外写」这个对象，故「按路径分级审批」**无触发场景**。
- **结论**：**裁定维持条件性 = 本条归档**（2026-09-28）。触发条件、判据草案与冻结边界一并移入 `docs/frame.md` 五（已知缺口）同名行；本区不再留条目。
- **触发条件（前置）**：引入「**非 workspace 的受控写**」能力（例如经审批向 workspace 外写）。届时改法 = 让第 4 步的越界结果按**声明式路径策略**在 `allow / ask / deny` 之间分级（未配置 = 现状逐字节不变；默认仍 fail-closed）。
- **若实现，判据草案**（写给届时实现者，含变异体要求）：workspace 内写与今天逐字节相同；越界且未声明策略 ⇒ 仍 `BLOCKED`（**不得**因「有审批」而默认放宽）；越界且声明 `ask` ⇒ `APPROVAL_REQUIRED`，拒绝后不落盘、不留半成品；凭证 basename 与内部状态目录**永远 deny**（不可被审批放行）；`..` / 符号链接 / 8.3 短名等按**解析后真实路径**分级（复用 `path_safety.resolve_under_root` 同一算法，禁止两套）；不得改变 `sandbox_mode` 语义（`read-only` 档仍是不可绕过的硬上限）。变异体：默认由 `BLOCKED` 改成 `ask` ／ 允许审批放行 `.env` ／ 用未解析路径分级 —— 三者都必须**精确变红**。
- **冻结边界**：分级只能是 `PolicyEngine` 的 **defense-in-depth 标记**，**不是** OS 级边界，也不得放松 workspace 围栏默认值。
- **证据**：`src/heagent/engine/policy.py`（`evaluate_tool_call` 第 4/5 步；`_requires_approval` 只看工具名与注解）；`src/heagent/tools/path_safety.py`（`resolve_under_root`，policy 预检与 file handler 共用同一算法）；`src/heagent/engine/approval.py`（审批闭环，同为非安全边界）。
- **文档落点**：`docs/frame.md` 五（本裁定的触发条件与判据草案就写在那里）。
