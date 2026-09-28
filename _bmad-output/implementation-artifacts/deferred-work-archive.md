# Deferred Work——活动条目 + 闭合归档

> 本文件自 2026-09-17 起承接两类条目（原活动台账 `deferred-work.md` 已删除，用户裁定）：
> ① **活动（未闭合）条目**——工作流的 append-only 入口，闭合后按归属 epic 归档至各周期
> `deferred-work.md`（勘察类留在本文件，索引见 `consolidated-overview.md` 13.1）；
> ② **闭合归档**——正文分两处落（2026-09-24 起）：**勘察类**（source_spec 为勘察批次、无归属 epic）留在本文件；**有归属 epic 的**按规则回填到各周期 `deferred-work.md`（`Z-D10` / `Z-D11` → [`epic-48-TCP网络接口周期/deferred-work.md`](../epics/epic-48-TCP网络接口周期/deferred-work.md)，`Z-D13`~`Z-D15` → [`epic-50-网页控制台周期/deferred-work.md`](../epics/epic-50-网页控制台周期/deferred-work.md)）。本文件仍登记**全部 `Z-Dn` 的 ID 索引**（见下状态总览），但不保留已回填条目的正文副本。

> **维护规则**：活动区是唯一的未闭合条目正文；总览与回顾只保留编号和链接。新增条目按末尾追加，闭合时保留 ID、补充 Resolution/证据，并将有明确归属的正文移入对应周期 `deferred-work.md`。`blocked` 表示需要产品或架构决策，不能由实现者自行关闭。

## 活动（未闭合）条目——8 条

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
> - 2026-09-27：**闭合 4 条裁决类条目（A19 / A20 / A21 / A22）**——① A19「掩码域后缀制」：裁定维持现状（URL 不以凭证命名 + 部分掩码破坏诊断 + 与 `safe_logging` 口径分场景），补充至 `docs/frame.md` 五；② A20「非回环运行姿态」：裁定维持现状（Epic 49 既有姿态 + 真正边界是 OS 沙箱 + 破坏既有契约），更新文档描述；③ A21「R5 收敛判据失效」：裁定收紧规格（正文以 `Error:` 开头的文件不在收敛范围），补充至文档；④ A22「目录选择端点默认开」：**裁定默认改按需**（`--dialog-backend` 默认改为 `none`，与 `HTTP_CONSOLE_WRITE_ENABLED` 惯例一致）——修改 `cli/http.py:362`（命令选项默认值）+ `cli/http_console.py:440`（`HttpProjectConsole.__init__` 默认值）+ 更新 `docs/frame.md` 已知缺口行。活动条目数 12 → 8。
> - 2026-09-27：**清理 3 条重复/已闭合条目**——① 行 78-82「非回环运行姿态」的 ① 部分已在 A20 裁定维持现状，归档为 A11（部分闭合，② cron 部分）；② 行 99-102「R5 收敛判据失效」已在 A21 闭合，从活动区移除；③ 行 104-107「目录选择端点默认开」已在 A22 闭合，从活动区移除。活动条目数 8 → 5。
> - 2026-09-27：**合并 2 条重复浏览器验收条目 + 精简残余描述**——两条 50-6/50-8 浏览器验收正文完全相同，合并为一条（source_spec 改为 `50-6/50-8`）；控制台阻塞 I/O 条目的"唯一残余"描述精简（已量化且有升级条件，删除冗余细节）。活动条目数不变（5）。
> - 2026-09-28：**计数校正（机械；条目内容一字未动）**——按本文件逐行实测（脚本 `.heagent/tmp/`：`audit_ledger.py` / `count_check.py` / `ledger_count_history.py` / `item_diff.py`）：① 本区标题 `5 条` → **8 条**；② 归档引言 `35 条 / 21 条` → **33 条 / 19 条**（= 14 + 19，与实际小节数一致）；③ 状态总览②标题 `20 条` → **19 条**；④ 本账单 2026-09-27 三行的收尾计数有误——`12 → 8` 实为 **12 → 11**（该提交只移出「掩码域后缀制」1 条）、`8 → 5` 实为 **11 → 9**、`不变（5）` 实为 **9 → 8**（合并两条浏览器验收条目），实测序列 **12 → 11 → 9 → 8**。⇒ 本区条目数**以标题为准**，上述历史行内的「活动条目数」不再可靠。

- source_spec: `_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/stories/46-1-skill-resource-toctou-assessment.md`
  summary: 技能资源读取的竞态加固——**2026-09-27 部分闭合**：POSIX **逐组件 `openat`** 已交付（中间目录 `O_DIRECTORY|O_NOFOLLOW`、叶 `O_NOFOLLOW`，围栏后替换中间目录即在该组件上失败），Windows 无 `dir_fd` ⇒ 回退整路径 `open`、窗口与硬化前一样宽；未交付面 = 可信导入 snapshot / OS sandbox。
  evidence: Story 46.2 已以 `O_NOFOLLOW` 加固支持平台上的最终路径组件，并保留不支持该标志时的兼容回退；中间目录替换、可信导入 snapshot 与 OS sandbox 仍未交付，现有路径围栏保留竞态残余风险。
  Progress（2026-09-23 复核，**保持未闭合**）：详见 `_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/assessment-toctou-residual-2026-09-23.md`。① 竞态类残余维持 Story 46.1 决策（descriptor-relative 仅 POSIX 可用、仍非边界；Windows 无 `O_NOFOLLOW` 回退窗口更宽）；② **新查出一处非竞态缺口**：`manifest.lock` 只钉 entry（`SKILL.md`）的 `source_hash`，而 `_materialize` 用 `shutil.copytree` 复制整棵包树（`references`/`templates`/`assets`/`scripts`），且运行期**从不读** lock ⇒ 包资源内容无完整性凭据、读取路径（`SkillPackage._read_text` → `open_text_under_root`）不校验；同类先例已在隔壁一层存在（`_bmad/render/*/manifest.json` + `render_skill.py::_verify_existing` 的逐文件哈希校验，仅重渲染时触发）。③ 建议方向 = 内容哈希钉 + 读时校验（跨平台、无新依赖、fail-loud，复用既有凭据形态），但会改变「手工编辑 lock/rendered 包后仍可读」的语义，**命中 Story 46.1 的 Ask First（导入物化/读取语义）**，故实施待授权；④ 本仓库当前未激活 importer 通道（`.heagent/skills/manifest.lock` 不存在），故该缺口暂属休眠暴露面。
  Progress（2026-09-23 同日实施，用户决策 = (a) 确认行为变化 / (b) 复用既有 `manifest.json`）：**非竞态缺口已闭合** —— `SkillPackage` 读时对渲染器 `manifest.json` 的 `outputs` 做逐资源校验，漂移即 `SkillPackageResourceError("content hash differs from manifest.json")`；底层新增原始字节摘要通道（`read_bytes_under_root` / `read_text_with_digest_under_root`，CRLF 文件亦可校验）；17 例测试（含改写/截断/entry/CRLF/未托管/凭据不可用/凭据探测次数/契约护栏），负向验证：拿掉校验调用 → 3 例漂移检测必红；凭据读取经 `is_file()` 门控（未托管包零额外 open——无门控会打破 `test_skill_packages_toctou.py` 的两条刻画测试，**该回归只在 Linux 暴露**，由 WSL 等价验证在 2256 passed 的跑法下抓出）。**竞态残余保持开启**：中间目录替换在 POSIX/Windows 上都未闭合（descriptor-relative 仅 POSIX 且仍是收窄），唯一真边界仍是 OS 级沙箱。
  Progress（2026-09-27，**POSIX 逐组件通道交付 + Ask First 授权记录**）：用户裁定「**授权引入专用代码**」⇒ 此前停在 Ask First 的候选 A（descriptor-relative / 逐组件 `openat`）落地：`tools/path_safety.py` 新增 `_open_walked` / `_open_dir_component` / `_is_symlink_at` 与**导入期冻结**的能力门 `_WALK_SUPPORTED`；`read_bytes_under_root` 围栏通过后按平台选通道（root 自身不加 `NOFOLLOW`，工作区经链接指向真实目录的合法布局不受影响）。**判据 7 条**（`tests/test_skill_packages_toctou.py`）：形状（root→中间→叶的 flags 与 dir_fd）、**竞态（围栏后把中间目录换成指向 root 之外的符号链接 ⇒ 必须在那个组件上失败）**、无 `dir_fd` 的回退形状、`..` 守卫纯路径判据、门与平台能力一致性，以及把旧的「总共只 open 一次」改写为「叶描述符唯一 + 中间 fd 不泄漏」（逐组件通道必然多开，旧断言会把正确实现判红）。**变异体 5/5 精确变红**（`.heagent/tmp/mutate_walk_posix.py`：中间组件不带 `NOFOLLOW` ⇒ 2 红；恒定回退 ⇒ 3 红；不带 `O_DIRECTORY` ⇒ 2 红；去掉 `..` 守卫 ⇒ 1 红；不做 ENOTDIR 归因 ⇒ 1 红）。**实测**：WSL Ubuntu/py3.12 上 `tests/test_skill_package*` **56 passed / 1 skipped**，全量 3114 passed + 3 failed（3 例全在 `test_cli_http_lifecycle.py` 的端口释放断言，**基线 HEAD 同款链路同样红** ⇒ WSL2 端口回收特性，与本条无关）；本机（win32）全量 **3126 passed / 覆盖率 91.74%**；`ruff` + `mypy`（本机与 `--platform linux`）全绿。**过程中踩到并修掉的两个真问题**：① 中间组件带 `O_DIRECTORY|O_NOFOLLOW` 撞符号链接时 Linux 回 **ENOTDIR**（不是 `ELOOP`）⇒ 归因必须两条 errno 都判；② 用 `os.open in os.supports_dir_fd` 做**每次调用**判定会被任何「包一层 `os.open`」的代码静默打回回退通道 ⇒ 冻结为导入期常量。**残余（不变）**：① Windows 仍只保护最终组件；② 组件级竞态不为零（组件之间仍有时间差）；③ 仍是收窄而非边界（真边界 = OS sandbox）；④ 未做方向 = 可信导入 snapshot / `manifest.lock` 的 `resources` 哈希（当前休眠暴露面）。

- source_spec: `_bmad-output/implementation-artifacts/arch-optimization-cycle/phase5-observability-benchmarks-docs.md`（V-系列排除项 + C3 文档收口结论）
  summary: **GUI 原生事件渲染**：GUI 观测仍走 stderr 转发（行为冻结，`gui/screens/chat.py` 自述「文案冻结」）；事件契约 v2（`RunEvent.duration_ms`/`error_kind` 顶层字段 + workflow_step_* kind）已为此铺路——GUI EventLog 可直接读事件渲染耗时/失败分类/步骤轨迹，不再受 CLI 文案约束。触发条件：GUI 观测升级需求；严重度：低-中；冻结边界：EngineEvent 模型与 GUI 既有消费面不破坏。
  evidence: `src/heagent/events/protocol.py`（v2 字段）、`src/heagent/gui/observers.py`（读 EngineEvent）、`gui/bridge.py`（StreamEvent 通道）；Phase 3 spec「不把 GUI 的 stderr 转发升级为原生渲染」排除项。

- source_spec: `_bmad-output/epics/epic-36-39-文件安全防护周期/brief.md`（`### Deferred（未来考虑）`：「路径级审批分级（若未来引入非 workspace 的受控写场景）」）
  summary: 路径级审批分级（**条件性条目，前置未发生**）：当前审批粒度是工具级（destructive → 审批），file 工具一律被限制在 workspace 内，所以「按路径分级审批」暂无触发场景。触发条件：引入「非 workspace 的受控写场景」（例如经审批向 workspace 外写）；严重度：低（前置未发生）；冻结边界：分级只能是 `PolicyEngine` 的 defense-in-depth 标记，不得表述为 OS 级边界，也不得放松 workspace 围栏默认值。
  evidence: `src/heagent/tools/path_safety.py`（`resolve_under_root`，policy 预检与 file 工具 handler 共用同一算法）；`src/heagent/engine/policy.py`（destructive 注解闸门）；`src/heagent/engine/approval.py`（审批闭环，同为非安全边界）。

- source_spec: `_bmad-output/epics/epic-50-网页控制台周期/ARCHITECTURE-SPINE.md`（§6「并发口径」+ §15 D9；对偶义务见 50-7 T10⑨）
  summary: **跨项目并发无全局上限（Epic 50 D9 采纳后的已知缺口）**：D9 裁定采纳「并发随项目数线性增长」——在途运行上限 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`（默认项目上限 32 × 1 ⇒ **最多 32 个并发 run**），跨项目不共享名额、不做全局调度；而 `HTTP_MAX_CONNECTIONS`（默认 16，由 Uvicorn `limit_concurrency` 承担）**不随项目数放大**。触发条件：登记接近上限的项目数、并对多个项目同时发起运行；严重度：低-中（资源占用线性上升——每项目一套 `EngineContainer` / 事件缓冲 512 / run 历史 64 / SSE 订阅，外加真实 LLM 并发、沙箱进程与磁盘写入；且连接层可能先于运行层成为瓶颈）；冻结边界：不得为此改回「跨项目共享在途名额」（D9 已裁定为**有意语义**），也不得改每项目内部的单运行约束与会话在途保护；若要引入上限，只允许**新增**全局限流键（如 `HTTP_CONSOLE_MAX_TOTAL_INFLIGHT`），不得复用或改写既有 `HTTP_MAX_INFLIGHT_RUNS` 的 per-service 语义。
  evidence: `ARCHITECTURE-SPINE.md` §6（并发口径：32 × 1 的乘数关系 + 已知缺口声明）；`src/heagent/network/http_server.py:150`（`max_inflight_runs` 是 **service 级**字段）、`:386`（`len(self._active) >= self.config.max_inflight_runs` 按 service 判定）；Epic 49 遗留的连接层口径（`HTTP_MAX_CONNECTIONS` 与 SSE 订阅上限复用、由 Uvicorn 在 ASGI 之前拒绝，见 `docs/frame.md` 五）；本周期内对偶义务：50-2 T4（项目数上限 32 即并发乘数，改它等于改整体资源上限）、50-3 T9（须正面断言「A 项目在跑时 B 可起跑」**且**「同项目第二个 run 仍被拒」）、50-7 T10⑨（文档须写明口径与缺口）。
  Progress（2026-09-24 登记，**计划期条目**；2026-09-27 复核）：Epic 50 已于 2026-09-27 收口（8 story 全 `done`），本条描述的缺口**已成为既成事实**——在途上限 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`（默认最多 32），`docs/frame.md` 五 的对应行已存在（对偶义务 50-7 T10⑨ 已完成）。截至本轮**仍未引入全局上限**；若要引入，只允许新增全局限流键（如 `HTTP_CONSOLE_MAX_TOTAL_INFLIGHT`），不得改写既有 per-service 语义。
  Progress（2026-09-27，**已交付可选的全局键**；本条按「部分闭合」留在活动区并逐面标注）：新增 `HTTP_MAX_TOTAL_INFLIGHT`——`config/__init__.py` 的 Settings 字段（默认 **0 = 不限**）→ `cli/http.py::build_server_config`（含 `--max-total-inflight` 旗标）→ `network/http_server.py` 的 `HttpServerConfig.max_total_inflight`；判定落在 `HttpRunService.start_run`，用 `len(self._active)`（与运行记录同源，不另建索引、也不会与 `_inflight_in_scope` 的事实分叉），跨项目共享一份名额。超限回**新稳定码** `total_inflight_limit`（409）——`HttpRunConflictError` 因此带上 `code`，两处 catch（`network/http_server.py` 的 `/api/runs` 与 `cli/http_console.py::start_project_run`）都透传 `exc.code`；前端 `web/app.js` 的码表补独立中文文案（闭集契约 `test_every_console_error_code_has_a_readable_text` 按枚举派生，漏配必红）。**判据 6 条**：单元 4（默认不限⇒跨项目各占一名额；设 1 后跨项目拒且码为 `total_inflight_limit`；名额随终结归还；匿名端点 `/api/runs` 吃同一份额且回同码）+ HTTP 级 1（真 console + 真 service 装配下跨项目 409）+ 配置/文案 2（默认 0 与 `-1` 拒绝、CLI 与 env 覆盖、前端文案内容）。**变异体 5/5 精确变红**（`.heagent/tmp/mutate_total_inflight.py`：去掉判定 ⇒ 3 红；匿名端点写死旧码 ⇒ 1 红；控制台写死旧码 ⇒ 1 红；默认改 1 ⇒ 27 红；前端漏配文案 ⇒ 2 红），每处字节还原后基线复绿（sha256 核对）。`HttpErrorCode` 成员集契约 34 → **35**（`tests/network/test_http_protocol.py` 在首轮全量里按设计报红，正是该契约生效的证据）。文档同步：`docs/frame.md`（配置表新增行、4.17 限额段、4.18 并发口径、五 缺口行、错误码计数 34→35 三处、49/50 流程图的 409 码）＋ `.env.example`。**仍开放的残余（有意，非缺陷）**：① 默认**不限**——「并发随项目数线性」是 D9 的裁定语义，本键只是运维可选上限，要把默认改成有界属产品裁决；② `HTTP_MAX_CONNECTIONS` 仍不随项目数放大（连接层先成瓶颈的可能性不因本键消失）。

- source_spec: 2026-09-24 Epic 50 收口评审（三镜头）· 控制台阻塞 I/O 与会话列表成本
  summary: **控制台端点在唯一事件循环里做同步 I/O**：`list_sessions`（逐文件全量读 + 无 title 时全量校验）、`build_config_report`（实测中位 14 ms）、`registry.list()`（每请求每条一次 `Path.is_dir()`）、`registry.touch()`（跨进程文件锁 + 原子写）都是 `async def` 体内的阻塞调用，会卡住在途 SSE 流与其余请求；且 >1 MiB 的会话仍在列表时被整份读入（`count_messages` 只跳过计数，与 `SessionMetadata` docstring 的「避免列表时校验整份历史」不符）。触发条件：会话数/体积增长、面板被频繁刷新；严重度：低-中（单用户本机场景下不致命，属可伸缩性债务）；冻结边界：不得为此改变会话文件格式或列表接口的有界口径（D6 的「列表可退化」语义保留）。
  evidence（行号于 2026-09-27 实测刷新）：`src/heagent/cli/http_console.py:516`（`runtime.sessions.list_metadata()`，已 `to_thread` 卸载）、`:626` 与 `:670`（`build_config_report` 两处，均已卸载）、`:722`/`:728`（`_project_entry` / `_runtime_for` 每请求遍历注册表——**唯一残余**）、`:774`（`registry.touch`，经 `:771` 的 `_touch` 卸载）、`:759`（dream 会话预注入，已卸载）；`src/heagent/context/session.py:620`（`info.st_size > MAX_SESSION_METADATA_BYTES` ⇒ 走 `_read_head`，元数据只读 `"messages"` 之前的区段）、`:637`（`count_messages` 只对未超限文件计数）。
  Progress（2026-09-24 登记；**2026-09-27 两轮续修，仅剩一处已量化残余**）：
  ① **会话读**离线到 `asyncio.to_thread`——`list_sessions` / `get_session`（元数据 + 整份消息）/ `start_project_run` 前的 `_resolve_session`（缺省分支会列全部会话）；不改任何公共签名（`_resolve_session` 仍是同步纯助手）；
  ② **其余落点补齐**——`build_config_report`（`get_project_config` 与写后响应两处）、`registry.touch`（`_touch`）、`list_projects` 的 `registry.list()`、`memory/dream` 的会话预注入（`_build_dream_prompt`）；
  ③ **`>1 MiB` 会话不再整份读入**——`SessionStore.list_metadata` 改走 `_read_head`（有界读 `MAX_SESSION_METADATA_BYTES` 字节 + 严格解码，cap 落在多字节字符中间时只裁掉不完整尾序列）+ `_metadata_from_head`（落盘键序保证 `session_id` / `version` / `timestamp` / `title` 都排在 `messages` 之前 ⇒ 列表所需字段照旧可得；`message_count` 恒 `None`，D6 口径与 `SessionMetadata` docstring 从此一致）。
  **验证（2026-09-27 亲跑）**：新增 6 例测试（`tests/test_session.py::TestOversizedSessionListing` 4 例——含「任何整份读即抛」的守卫、cap 落在 CJK 字符中间的容错、坏编码仍列不可读；`tests/network/test_http_console_sessions.py::test_registry_and_config_solver_run_off_the_event_loop`；`tests/test_dream.py::test_session_preload_runs_off_the_event_loop`），判据一律取**线程身份**而非耗时；变异体 **5/5 精确变红**（`.heagent/tmp/mutate_console_io.py`：回退有界读 / 回退 `list_projects` 卸载 / 回退 `_touch` 卸载 / 回退配置求解卸载 / 回退 dream 卸载），每处字节还原后基线复绿；全量 `pytest -q` **3179 passed / 11 skipped**；`ruff check` + `format --check` 与 `mypy`（本机 + `--platform linux`）全绿。
  **复审补强（2026-09-27 同日后复审）**：③ 的有界头部读再收一刀——`_extract_head_scalar` 原先在整个 1 MiB 窗口里找 `title`/`timestamp`/`version`，而窗口通常已越过 `messages`；工具参数是**未转义**的 JSON 键，消息体里的 `"title": …` 会与元数据字段同形并被当成会话标题。现限定为「`"messages"` 之前的元数据区」。回归 `tests/test_session.py::TestHeadMetadataScope`（变异体去掉作用域限定 ⇒ 精确变红）。同轮如实补记口径：大会话的 `messages` 结构**不在列表期校验**（畸形消息只在详情时报 `session_unreadable`）——这是「列表只读头部」的必然延伸，已写进 `_metadata_from_head` docstring。
  **仍未修（唯一残余，有意保留）**：`_runtime_for` → `_project_entry` 每请求一次 `registry.list()`（= 1 次注册表文件读 + ≤33 次 `Path.is_dir()`，亚毫秒量级）。停手理由：同步私有助手，改 async 连带 churn 大于收益。**升级条件**：控制台端点 P95 超过 SSE 心跳（15s）的 1%，或 `MAX_PROJECTS` 从 32 上调。

- source_spec: 2026-09-24 Story 50-6/50-8 实现（网页控制台 UI + UX 优化）
  summary: **浏览器级 UI 验收不在 CI、也不含真实 LLM 运行**：`tests/js/console_acceptance.mjs` 需要真实 Chrome/Edge（CDP）+ `heagent[http]`，而 CI 侧**没有任何浏览器**（install 步骤只装 `.[dev,http]`／lint job 装 `.[dev,gui,http]`，全程没有 node 或浏览器步骤，依赖里也没有 playwright/puppeteer）⇒ 它只能手动跑，story 50-6 的验收清单正是由它产出的；同时该次验收**没有**跑「真实模型 → SSE → 对话区流式渲染」这条链（本机无可用 provider，Ollama 未运行），该链的前端侧由 node 探针（`tests/js/app_probe.js` 用例 A/B/C/D/E/N）与 Epic 49 的服务端用例覆盖。触发条件：改 `app.js`/`index.html`/`styles.css` 后要确认「真浏览器里也没坏」；严重度：低（改动有探针兜底，但探针是 DOM 替身——CSP 是否被违反、有没有第三方请求、窄屏计算样式只有真浏览器能证明）；冻结边界：不得为让浏览器验收进 CI 而给 dev 依赖加 playwright/puppeteer（保持零构建链与「GUI / 浏览器不进 CI」的既有立场），也不得把 `console_acceptance.mjs` 的一次通过当作「UI 无回归」的充分证据。**2026-09-24 实例（这条「不够充分」的最强证据）**：50-6 的 17/17 通过之后仍漏掉「首页确认遮罩吞掉真实鼠标点击」（`hidden` 属性为真而计算样式 `display:flex`）—— 因为清单只断言属性、且 `click()` 走 DOM API（绕过命中测试）；修复后清单新增 A1b（计算样式 + CDP `Input.dispatchMouseEvent` 真实点击）为 **18 行**；Story 50-8 的增量轮再扩至 **23 行**（2026-09-25 加 A5b / A11b / A11c / A11d / B2），详见 Z-D15 与 `reviews.md#acceptance-50-8-refinement`。
  evidence: `tests/js/console_acceptance.mjs`（自起真实 http-server + headless Chrome，CDP 驱动真实点击；23 行清单含窄屏/凭证零明文/磁盘副作用断言，2026-09-25 起）；`tests/test_http_web_ui.py`（探针用例的 skipif 只要求 node，不要求浏览器）；`pyproject.toml`（可选依赖分组：`http` 与 `dev` 分离、`gui` 独立）。**2026-09-27 实测刷新**：`.github/workflows/ci.yml` 的 install 步骤为 lint `.[dev,gui,http]`（第 27 行）与 test / goal-smoke / coverage / benchmark `.[dev,http]`（65 / 83 / 101 / 130 / 182 行），全文件无 `node` / 浏览器 / playwright 字样 ⇒ 原写「CI 只装 `.[dev]`」与实测**不符**（该句写于 Epic 49 之前），缺口理由应记作「CI 不提供浏览器、也不跑 node 用例」，而非依赖分组；同轮复测本机 `127.0.0.1:11434/api/tags` 连接被拒 ⇒ 「本机无可用 provider」那句仍成立。
  Progress（2026-09-24 登记，**未闭合**；2026-09-27 复核）：验收输出见 `_bmad-output/epics/epic-50-网页控制台周期/reviews.md#acceptance-50-6-console-ui`（17/17 PASS，Chrome 153.0.8010.48）；该报告同时给出复跑命令与依赖前提。本轮只**修正证据**（CI 理由、见上），**缺口本身未变**：浏览器级验收仍不在 CI、「真实模型 → SSE → 流式渲染」这条链**至今没有被跑过**（本机无可用 provider）。

- source_spec: `_bmad-output/epics/epic-50-网页控制台周期/stories/50-8-console-ux-refinement.md`（R2 原生目录选择，2026-09-24 实现）
  summary: **网页请求可拉起宿主 GUI 进程（有意引入的新暴露面）**：`POST /api/dialogs/pick-directory` 会在**服务端所在机器**弹出一个原生目录选择窗口（子进程 `tkinter` / `powershell`）。它带来的是便利而非权限（返回值仍要过 `POST /api/projects` 全套校验），但暴露面是实打实的：**任何能连上该端口的本机进程都能让服务机弹窗**（骚扰面），而「回环 peer」不等于可信（用户自己浏览器里的任意页面 peer 也是 `127.0.0.1`，见 frame 五同名条目）。另有三种**不可用**环境：无图形后端（容器 / 缺 `_tkinter` 的 Linux）、服务在远程机器而浏览器在别处（窗口弹在服务机，对调用者无用）、`--dialog-backend none` 显式禁用。触发条件：把服务绑到可被其它本机进程访问的端口 / 在无 GUI 环境部署；严重度：低-中（不崩、不改数据，最坏是弹窗骚扰与一次失败的登记尝试）；冻结边界：**不得**把它表述为安全边界，**不得**为「更安全」而改成服务端目录浏览 API（那会把宿主目录结构开放给回环客户端），也**不得**让它绕过 `POST /api/projects` 的任何校验（选择器不是权限来源）。
  evidence: `src/heagent/cli/dialogs.py`（后端顺序 `resolve_backend` / 冻结脚本 `_TK_SCRIPT`+`_POWERSHELL_SCRIPT` / `DirectoryPicker` 单在途 + 300s 超时 + kill + 有界回收 / 只认 ASCII 标记行 + `is_dir()` 复验）；`src/heagent/network/http_server.py::_build_dialog_endpoint`（`_loopback_error` + POST-only + 新码 `dialog_unavailable` 503 / `dialog_busy` 409）；`src/heagent/cli/http_console.py::HttpProjectConsole.pick_directory`（入口层持有单在途）。实测：真机探针 `.heagent/tmp/probe_50_8_dialog_real.py`（`auto → tkinter`，2s 超时后 kill + 归还名额 + WARNING）；浏览器清单 `reviews.md#acceptance-50-8-refinement` 的 A5b / B2 两行（不可用路径端到端）。
  Progress（2026-09-24 登记，**未修**，冻结边界）：本暴露面是**有意引入**并已在 `docs/frame.md` 4.18（安全声明段）与五（已知缺口）双处如实登记；三条防线（回环门 / 单在途 / 冻结 argv + 超时）都在测试与浏览器清单里有可见判据，负向验证见 `.heagent/tmp/mutate_50_8.py` 的 M1–M4。**未做**（如实记录）：没有「谁能让服务机弹窗」的更强授权（如每会话令牌），也不打算做——那属于「把非安全边界做厚」的范畴，真正的边界仍是 OS 级沙箱。

- source_spec: `_bmad-output/epics/epic-50-网页控制台周期/stories/50-8-console-ux-refinement.md`（R2/R5 的验收与判据残余，2026-09-24 实现）
  summary: **两处「判据/验收」残余（不影响功能，但会在改动时静默失效）**：① **真实原生窗口无法自动化验收** —— 选中并确认需要人眼与人手，浏览器清单只能覆盖「按钮存在」「不可用路径」「取消/超时」；`tkinter` 子进程脚本在 CI 里**永不执行**（Linux 镜像可能无 `python-tk`），只钉了「能编译 + 标记行 / 标题插值唯一」；② **网页侧读取结果收敛依赖 `Error:` 前缀约定** —— 内置工具用**返回值** `Error: ...` 表达可预期失败（`is_error` 仍为 `False`），`file_read` 的失败消息因此靠 `_looks_like_a_failure()` 的字符串前缀识别；若将来把工具改成结构化错误（抛 `ToolError` / 返回带 `is_error` 的对象），该判据应退化为只看 `is_error`，否则前缀写成别的样式的失败会**静默从页面上消失**。触发条件：改动 `cli_dialogs` 的冻结脚本 / 改造内置工具的错误返回形态；严重度：低（都有测试兜底，但兜的是「现在的形态」）；冻结边界：不得为了「可自动化」而给 dev 依赖加 playwright/puppeteer（保持零构建链与「浏览器不进 CI」的既有立场），也不得把真实弹窗的一次人工通过当作「选择器无回归」的充分证据。
  evidence: `tests/js/console_acceptance.mjs` 的 A5b / A11b / A11c / B2（真实浏览器，无真实弹窗点击）；`tests/test_cli_dialogs.py::TestSpawnDiscipline::test_frozen_scripts_are_valid_python_syntax`（只 compile 不执行）；`src/heagent/cli/http_console.py::_looks_like_a_failure` 与 `tests/test_http_agent_api.py::test_read_tool_error_message_is_still_shown_in_web`（**明写**「内置工具返回 Error 字符串不算异常」这一约定）；浏览器清单里「真浏览器 LLM 运行」仍是既有缺口（Z-D15 同处登记）。
  Progress（2026-09-24 登记，**未修**）：两条都已在 `docs/frame.md` 五 与验收报告里如实登记；`file_read` 失败路径有专门的真实装配用例（`tool_output` 仍可见），负向验证见 `.heagent/tmp/mutate_50_8.py` 的 M10（去掉前缀判据 ⇒ 精确变红）。

---

## 闭合归档（勘察类正文 + 回填索引）

> 当前闭合归档共 33 条：14 条勘察类正文保留在本文件，19 条已按归属 Epic 回填并仅在此保留 ID 索引。活动区另有 8 条未闭合条目。

## 状态总览

**① 勘察类（正文在本文件）——14 条**

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

**② 已按归属 epic 回填（正文在各自周期目录）——19 条**

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
| A11 | Epic 50（收口评审三镜头，2026-09-24 登记；2026-09-27 部分闭合） | 非回环运行姿态 —— ② cron 部分已闭合，① 已在 A20 裁定维持现状 | 本文件下方「A11」小节 |
| A18 | Epic 50（Story 50-8 收口后评审，2026-09-26 登记） | 「共 N 个会话」在 N > 200 时少报 | `epics/epic-50-网页控制台周期/deferred-work.md` |
| Z-D21 | Epic 50（Story 50-3 的并发写，2026-09-26 登记） | 同一会话文件的两个写者整份覆盖对方历史 | `epics/epic-50-网页控制台周期/deferred-work.md` |
| Z-D22 | Epic 50（收口评审第二轮，2026-09-24 登记） | 写入通道与保真写的四类低危残余（①文档 ②文案 ③锁内 I/O ④备查） | `epics/epic-50-网页控制台周期/deferred-work.md` |
| Z-D23 | Epic 50（Story 50-6 AC7/UX-DR3，2026-09-24 登记） | 「高影响键的差异化确认」缺后端风险标记 | `epics/epic-50-网页控制台周期/deferred-work.md` |
| Z-D24 | Epic S1–S4（brief `### Deferred`：「MCP server / cron 子进程接入沙箱」，2026-09-27 裁定） | MCP stdio 子进程未接入沙箱 —— **裁定 (c) 不实施**（见周期台账） | `epics/epic-S1-S4-沙箱硬化周期/deferred-work.md` |
| A19 | Epic 50（第四轮评审，2026-09-26 登记；2026-09-27 裁决） | 掩码域后缀制 —— **裁定维持现状**（文档补充） | 本文件下方「A19」小节 |
| A20 | Epic 50（收口评审三镜头，2026-09-24 登记；2026-09-27 裁决） | 非回环运行姿态（总结） —— **裁定维持现状**（文档更新） | 本文件下方「A20」小节 |
| A21 | Epic 50（Story 50-8 收口后评审，2026-09-26 登记；2026-09-27 裁决） | R5 收敛判据失效 —— **裁定收紧规格**（文档补充） | 本文件下方「A21」小节 |
| A22 | Epic 50（Story 50-8 实现，2026-09-24 登记；2026-09-27 裁决） | 目录选择端点默认开 —— **裁定默认改按需**（代码修改） | 本文件下方「A22」小节 |

> `Z-Dn` 编号在**本文件**登记（跨文档引用如 `Z-D8` / `Z-D15` 仍以此为索引），但**正文只有一份**，在上表第二列指向的文件里；本文件不留副本（2026-09-24 回填）。

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

---

## A19 掩码域后缀制 —— 裁定维持现状

- **来源**：Epic 50 第四轮评审（2026-09-26 登记，`_bmad-output/epics/epic-50-网页控制台周期/ARCHITECTURE-SPINE.md` §288）。
- **问题**：掩码域只认 `*_API_KEY` / `*_API_KEYS` 后缀，而 `*_BASE_URL` 中的凭证（如 `https://user:token@relay/v1`）会被原样回显；`GET /api/projects/{id}/config` 无回环门 ⇒ 任何能连到服务的客户端都能读到。
- **结论**：**裁定维持现状**（2026-09-27）。理由：① URL 本身不以凭证命名；② 部分掩码会破坏诊断用途（"为什么连不上"需要完整 URL）；③ 同仓 `safe_logging` 已对 URL userinfo 脱敏，口径分场景。补充至 `docs/frame.md` 五（已知缺口）。
- **证据**：`config/catalog.py`（`is_secret_key` / `EXCLUSION_GROUPS`）；`docs/frame.md` 新增行「配置掩码域是后缀制」。

## A20 非回环运行姿态 —— 裁定维持现状

- **来源**：Epic 50 收口评审三镜头（2026-09-24 登记）。
- **问题**：项目重命名、四个会话写操作与项目内运行入口当前没有回环门（登记/移除/配置写入有）。
- **结论**：**裁定维持现状**（2026-09-27）。理由：① 这是 Epic 49 的设计姿态，Epic 50 未扩大暴露面；② 网页入口无认证无 TLS，真正边界是 OS 级沙箱；③ 添加回环门会破坏既有端点契约。更新 `docs/frame.md` 已知缺口行描述。
- **证据**：`docs/frame.md` 缺口行已从「待裁决」改为「裁定维持现状」。

## A11 非回环运行姿态（详细）—— 部分闭合

- **来源**：Epic 50 收口评审三镜头（2026-09-24 登记）。
- **问题**：两条相关的主张冲突：
  - ① 回环闸门只装在「登记/移除项目」，而危害更大的 `POST /api/projects/{id}/runs`（可跑 shell/文件工具）、会话增删改都没有闸门
  - ② `enable_cron=False` 只拒了调度器：`cron_store` 仍被绑进 loop ⇒ 网页运行可以成功写入 `<项目>/.heagent/cron/jobs.json`，任务在本进程 IDLE 永不触发，却会在后续 CLI 会话里无人监督地执行
- **结论**：
  - **② 已闭合**（2026-09-27，commit `5a8a21e`）：`cli/composition._build_loop` 在 `enable_cron=False` 时连 `JobStore` 都不构造，`HttpAgentHandler.new_loop()` 新增守卫（loop 若绑了 cron 工具即显式失败）
  - **① 已在 A20 裁定维持现状**（2026-09-27）：这是 Epic 49 的设计姿态
- **证据**：
  - `cli/composition.py:116`（JobStore 构造条件）+ `:165`（传给 loop）
  - `cli/http_console.py:260`（`enable_cron=False`）与 `:264`/`:265`（守卫）
  - `tests/test_cli_http.py::test_new_loop_refuses_to_own_a_cron_scheduler`
  - `docs/frame.md` §4.17「运行隔离」已补该不变量

## A21 R5 收敛判据失效 —— 裁定收紧规格

- **来源**：Epic 50 Story 50-8 收口后评审（2026-09-26 登记）。
- **问题**：`_looks_like_a_failure()` 用字符串前缀 `Error:` 区分失败与内容，成功读取以 `Error:` 开头的文件时，整份正文会照旧显示在网页对话区。
- **结论**：**裁定收紧规格**（2026-09-27）。在 AC9 补充「正文以 `Error:` 开头的文件不在收敛范围内」，补充至 `docs/frame.md` 五（已知缺口）。
- **证据**：`cli/http_console.py::_looks_like_a_failure`；`docs/frame.md` 缺口行已补充该限制。

## A22 目录选择端点默认开 —— 裁定默认改按需

- **来源**：Epic 50 Story 50-8 实现（2026-09-24 登记）。
- **问题**：`POST /api/dialogs/pick-directory` 默认开启（`dialog_backend="auto"`），在默认 CLI 的内嵌服务中也生效，但内嵌路径无关闭手段。与配置写入通道的 `HTTP_CONSOLE_WRITE_ENABLED` 默认 False 惯例相反。
- **结论**：**裁定默认改按需**（2026-09-27）。修改默认值为 `"none"`，需要时显式传 `--dialog-backend auto` 开启。与配置写入惯例一致。
- **修改**：
  - `cli/http.py:362`：`--dialog-backend` 选项默认值 `"auto"` → `"none"`，帮助文本同步
  - `cli/http_console.py:440`：`HttpProjectConsole.__init__` 参数默认值 `"auto"` → `"none"`
  - `docs/frame.md`：缺口行已更新为「默认关闭」
- **证据**：代码修改已提交；文档已同步更新。

