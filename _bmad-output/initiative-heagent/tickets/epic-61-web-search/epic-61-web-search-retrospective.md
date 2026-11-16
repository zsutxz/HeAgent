---
epic: epic-61-web-search
date: 2026-11-16
verdict: accepted-with-open-items
criteria: declared
headless: false
---

# Epic 61 Web 检索工具周期 — Retrospective

## Epic summary

- **Epic**: `epic-61-web-search`（信封 `epic-61-web-search.md`，2026-11-13 立项 / 2026-11-16 交付闭合）
- **Tickets**（build 顺序 = 票树顺序，全部 `done`，无 `pending_tickets`）:
  | ref | title | status | baseline | range |
  |-----|-------|--------|----------|-------|
  | 61.1 | web_search 引擎抽象层 | done | `792b5d3` | `792b5d3..66a5b9f` |
  | 61.2 | web_search 工具注册与安全面对齐 | done | `66a5b9f` | `66a5b9f..1877250` |
  | 61.3 | web_search 配置面与文档收口 | done | `1877250` | `1877250..1e20e82`（切割：止于本 epic 最后提交 `1e20e82`；区间内 `f32cab8` 为 A52 外来提交，非本 epic 产物） |
- **Evidence inventory**:
  - ✅ Epic file 全读（Requirements CAP-1..4 + Done when **declared**）
  - ✅ Entries ×3（`tickets/tickets.toml` 全读；description/verify 在 entry 未清空）
  - ✅ Plans ×3 全读（frontmatter + frozen Intent + Code Map/Tasks）
  - ✅ Diff 区间 ×3 经 `git_evidence.py`（61.1: 8 files / 61.2: 4 files / 61.3: 含外来 churn，本 epic 仅 `docs/frame.md` +6/-4）
  - ❌ Story 文件 ×0（三票未 pull 到叶子文件，`find` story_file 均 None）→ 票面记录全靠 plan + entry，不影响分析但记录形态降级
  - ❌ Run folders ×0（epic 文件夹仅有信封 + tickets/）
  - ❌ Previous retro：本 epic 是票树首位，无前序 epic → 无 follow-through 检查
  - ⚠️ Session logs：上一会话 transcript（`f6a49785`，四项裁定与交付过程）+ 本会话在案；无独立 log 文件
- **Companions**: `docs/frame.md`（61.3 diff 已取）
- **Tickets accepted retro-ing over**: 无（三票全 done 后才进 retro）

## Findings

### 聚合视图（Phase 2 inline 派生；subagent 委派未用——epic 体量小，narrowing 记录在案）

- **AV-1 架构增量 — 清洁**：新增 `tools/builtins/web_search_engine.py:21` 引 `heagent.providers.retry`（层内横向）+ `web.py` 引 `heagent.config.get_settings`（向下依赖）——`tests/test_architecture_contracts.py` 37 例全绿（2026-11-16 复跑），无层违例、无环。
- **AV-2 重复映射 — 清洁**：max_results 双钳位（引擎 [1,20] `web_search_engine.py:95`、工具面 [1,10] `web.py:206`）与空查询双校验（引擎 :90-91 / 工具面 :208-209）均为注释言明的分层预算闸（deliberate defense-in-depth），非重复实现。
- **AV-3 尺寸 — 清洁**：`web_search_engine.py` 160 行（新）、`web.py` 现约 223 行、测试 153+123 行——远低于 Epic 62 的 800 行拆分门槛，无 god-class 苗头。
- **AV-4 模式分叉 — 基本清洁，一处张力**：工具面 `RuntimeError`（`web.py:209`）与 `web_fetch` 全线 RuntimeError 口径一致（`web.py:75-171`）；引擎 `SearchEngineError(ToolError)` 是跨模块类型化错误面。**adversarial A5 张力**：同一失败条件（空白查询）在两层面抛不同异常类型，`except ToolError` 接不住工具面入口校验，且 exception_types.json 只登记 SearchEngineError——库内惯例同构（web_fetch 先例）与类型契约一致性在此冲突，处置留 Phase 4。
- **AV-5 spec-实现对账**：
  - CAP-1 ✓（引擎面空/超长显性报错 + 15 引擎测试；CAP-4 活体验证见 Behavior verification）
  - CAP-2 ✓（registry 可插拔测试 `tests/test_web_search_engine.py`）
  - **CAP-3 部分**：guard 同构 ✓（`test_web_search_tool.py::test_guard_content_wired_on_output`）；**沙箱同构缺口**——`tests/test_sandbox_mode.py:88` 参数化表含 `web_fetch` 不含 `web_search`（deterministic grep 证据）
  - CAP-4 ✓（无密钥显性报错，测试 + 活体双证）
  - Done when：替身全链 ✓ / **真实冒烟 ✗（A55 挂账，用户裁定）** / 全量+ruff+mypy ✓（61.1 plan 记录 5 环境红已定性 environmental）/ docs strict ✓
- **F1（spec 对账 → 已升级）**：61.2 frozen intent「汇总 ≤20000 字符并标注」未落地——`web.py:186-222` 无总预算闸。**初判「条数×摘要结构封顶 ≈7.2k」已被 edge-case 镜头 E2 推翻**：title/url 无任何钳位（`web.py:217` 原样透传引擎可控文本），聚合文本实际无上界，20000 预算可达。处置待定（补代码 vs 修 intent 文本——E2 后倾向补代码）。
- **F2（设计一致性，low）**：超长查询校验只在引擎面（`web_search_engine.py:92-93`），工具面只查空不查长（`web.py:208`）——400 限额属 Tavily API 契约、放引擎面有其道理，但与工具面空查询校验所声明的「可插拔引擎不保证各自校验」理由不对称。处置待定（accept / 补工具面长度闸）。
- **F3（记录面）**：61.2 plan Tasks 四框全未勾而票 mark done（工作实际已交付 `1877250`，代码与测试在库，仅记录不同步）；61.1 plan Review 节留「待独立 review 代理结论」无结论落盘。

### 代码透镜（bmad-review，五镜头）

- **structure**（docs 类 hunk，2 条）：
  - S1（CONDENSE）：`docs/frame.md` §4.4 组标题「**Web 工具（2 个，`web.py` + `web_search_engine.py`）**」打破该文件组标题 schema「N 个，`module.py` = N 个 @tool 所在模块」不变量（两个 @tool 均在 `web.py`；`web_search_engine.py` 零工具，目录树已正确标注「非 @tool」）——建议回写「（2 个，`web.py`）」
  - S2（QUESTION）：§五已知缺口行标题「Dreaming 联网注入围栏」vs 行内容已泛化为 `web_fetch`/`web_search`——标题钉死 dreaming 会把检索「围栏是否覆盖 web_search」的读者引向「仅 dreamer」误读（失衡先于本 diff 存在，但本 diff 恰在编辑该行）；建议标题泛化或行内注明围栏布线在工具面、覆盖全部调用方
- **adversarial**（15 条，已逐条对源复核属实；编号 A1-A15，重叠项并入 F1/CAP-3/F3，此处记不重叠项）：
  - **A3**：`web_search_engine.py:21` 是全 `tools/` 唯一 providers 导入（第一条 tools→providers 兄弟层边）——FORBIDDEN_RUNTIME_IMPORTS 未含、frame.md 依赖图未记载、SPEC CAP-4 原文写的是「复用 `pub/exceptions` 容错面」；边属偶然容忍而非声明允许。候选：下沉 `pub/` 或在架构契约测试显式钉死 + frame.md 补记
  - **A4**：错误分类零生产消费者——`.category`/`.status_code` 建成后无任何生产代码读取（`tool_execution.py:318` `content=f"Tool error: {exc}"` 只留 str），模型可见错误串不含可重试性信息；「重试立场归调用方」docstring 无实现对应。候选：错误消息自携分类文本，或删分类机制待真实消费者
  - **A5**：空白查询工具面 RuntimeError vs 引擎 SearchEngineError 双分类（并入 AV-4 张力）
  - **A6**（=E4 扩展）：缺 `results` 键时 `data.get("results", [])` 静默当零命中——服务端 outage 被读成「（无检索结果）」
  - **A7**：引擎名 fail-loud 晚到第一次调用——config 只验非空（`config/__init__.py:393`）、registry 大小写敏感，错名穿越启动、在无人值守 dream 中段爆；装配点启动校验候选
  - **A8**：「trust_env=False 与 web_fetch 同口径」无测试背书——`test_web_fetch.py:212-217` 断言 client kwargs（trust_env False），`test_web_search_engine.py:36-38` 丢弃 kwargs 不捕获；删掉 trust_env=False 十四例仍全绿
  - **A9**（评审输入面，并入 V-F6）
  - **A10**：`CHANGELOG.md` [Unreleased] Added 节无 web_search 条目——三笔提交均未触碰 CHANGELOG，下次发版 release notes 静默漏整条功能线
  - **A11**：双层钳位 [1,10]/[1,20] 上段死余量、分工无契约文字（协议 docstring/SPEC 均无），双层各自漂移无人察觉
  - **A12**：`web.py:204-209` 注释「入口校验先于引擎」与实际顺序不符（create_engine 在空白校验前）——错名+空白查询组合下真实问题被遮
  - **A13**：`roles.py:184-186` 围栏注释测试指针过时（指向 test_dream.py，web_search 布线钉实际在 test_web_search_tool.py）
  - **A14**：`web.py:1-11` 模块 docstring 单工具纪元（「Web fetch 工具」），web_search 安全姿态（固定端点无 SSRF 面）无模块级记载
  - **A15**：`groups.py:149` WEB_SEARCH_ENGINE 挂 `outbound_redirect` 理由「可把凭证送往往意端点（准外泄通道）」名不副实——引擎名选择器端点按引擎硬编码，无凭证外泄能力，控制台文案恐吓失真
- **verification-gap**（6 条，独立复核确认）：
  - **V-F1**（=CAP-3 沙箱同构缺口定形）：`test_sandbox_mode.py:88` 只读档放行参数化表无 web_search；read-only 档 PolicyEngine 档位裁决（schema→`_verdict`）只有 web_fetch 被钉，web_search 被误判 BLOCKED 全套测试仍绿
  - **V-F2**：`test_plan_mode.py:110-113` plan mode 只读白名单断言只列 web_fetch——白名单漏收 web_search 无人会红（`roles.py:205` 已指引「web_search 找线索」，行为今天正确、纯属缺钉）
  - **V-F3**：`test_dream.py:280` dreamer 策略裁决循环无 web_search——role 白名单有钉、策略裁决面无钉，正是 tickets.toml:18 verify「dreamer 查证链路可发起检索」的机器可验形态
  - **V-F4**（=E2/A1 同点）：title/url 零闸 + 汇总总闸未实现 + 三处测试面均无输出总长断言 + guard_content「不截断」不兜底（`mapping.py:264-265` 核实）
  - **V-F5**（=F3 独立复核确认）：61.2 plan 四框未勾 / 61.1 Review 占位无结论
  - **V-F6**（评审输入面）：送审 patch 缺 `test_config_catalog.py`（TestSecrets 钉）与 `exception_types.json`（SearchEngineError 登记）两文件——patch 视角对此两面盲评；两文件经 git_evidence（66a5b9f 区间）+ 工作树（:565 / :897）核实已在库，属「checked and clean」但非透镜级审查
- **prose**（5 条微改 + 1 条 Consider，docs hunk）：
  - P1（语义暗示）：§4.6 与 §五两处「`web_fetch` / `web_search` 返回经 guard_content（Epic 35，2026-08-19…）」读作「两工具围栏均出自 Epic 35」——web_search 当时不存在；改「机制出自 Epic 35」区分出处与各自接线时间
  - P2（自相矛盾）：目录树 `web.py # web_fetch（HTTP 抓取）+ web_search（检索工具面，read-only）` 把 read-only 从 web_fetch 挪走，与 §4.4 表 `web_fetch` 行 read_only=True 矛盾；补回
  - P3：§4.4 web_search 行「条数硬切片 **×** 摘要 600」——「×」非本表惯例（同列 web_fetch 用「+」）；「无密钥工具常在」garden-path 建议加「时」；`guard_content` 补反引号
  - P4：.env.example「空 = web_search 工具常在…」缺「未配置」打底，与 config 源注释口径对齐
  - P5：.env.example 两新行注释列对齐到 36 列、紧邻块基准是 37 列——互相对齐但取错基准
  - **P6（Consider，已复核属实）**：frame.md:539 / :1607「内置工具 26 个」陈旧——运行时 registry 实计 **29**（含 web_search）/28（不含）；epic 前已差 2，本 epic diff 未触该计数。修 docs 时一并钉计数口径
- **edge-case-hunter**（7 条，均已对源码复核属实）：
  - E1（=F1 同点）：「汇总 ≤20000 并标注」未落地（`web.py:204-222`）
  - E2：**title/url 无钳位**——600 闸只钳 snippet（`web.py:214-217`），引擎可控的 title/url 可达 MB 级直入上下文，「确定性双闸」可被绕过
  - E3：引擎静默丢弃缺 url 条目（`web_search_engine.py:126-128` `continue`），全部缺 url 时返回 `[]` 与真实零命中不可区分，违反「不静默返回空结果」自述契约
  - E4：JSON 合法但形状异常（根非对象 / results 非 list / item 非 dict）时 AttributeError 逃出 `SearchEngineError` 契约（`web_search_engine.py:115-135`），分类丢失
  - E5：3xx 重定向（httpx 默认不跟随）落入 JSON 解析分支（`web_search_engine.py:100-106`），被误分类 NON_TRANSIENT「非 JSON」——显性但分类错；同面 web_fetch 有重定向再校验
  - E6：`register_engine` 对已注册名静默 last-wins 覆盖（`web_search_engine.py:142-144`），扩展点可无声换掉默认引擎
  - E7（边际）：结果条目字段全空白时误报「（无检索结果）」与零命中混同（`web.py:220-222`）

## Behavior verification

- **活体执行（2026-11-16，本机）**：真实 `get_settings()`（engine=tavily / 无 key）+ 真实 `ToolRegistry`（schema 注册、readOnlyHint=true）→ `web_search('...')` 调用 → `SearchEngineError` 显性报错并带配置指引（`WEB_SEARCH_API_KEY` / `web_search_api_key`）。**CAP-4 活体成立**。
- **未活体执行**：检索 happy path（真实 Tavily 全链）——需真实密钥，经用户裁定挂账 A55（`_bmad-output/open-items.md`）；pytest 替身全链 26 例（engine 15 + tool 11）为该路径的替身级证据。
- pytest 通过不替代活体运行的立场按工作流如实记录：本 epic 的行为验证 = 无密钥路径活体 + happy path 替身级。

## Previous-retro follow-through

无前序 epic retro（本票树首个闭合 epic）。

## Action items

**用户裁定（2026-11-16 会话内）：批 A+B 当场修（超出 retro propose-only 边界，经用户明示），C1 钉死+补记，C2 消息自携，C3 维持惯例；C4/C5/A11/E7 留票待领。**

已执行（本会话落地，门禁证据见 Acceptance verdict）：
- AI-1（fix-now ✓）：web_search 输出预算闸补全——title ≤200 / url ≤500 钳位 + 汇总 ≤20000 总闸 + 截断标注（`web.py`），`test_title_url_clamped` / `test_total_budget_gate` 钉死
- AI-2（fix-now ✓）：三处放行面验证钉——`test_sandbox_mode.py` 参数化表 / `test_plan_mode.py` 断言 / `test_dream.py` 裁决循环各补 web_search
- AI-3（fix-now ✓）：`CHANGELOG.md` [Unreleased] Added 补 web_search 条目
- AI-4（fix-now ✓）：docs/注释批——frame.md 工具计数 26→29 钉口径（两处）+ S1 组标题回写「（2 个，`web.py`）」+ S2 行标题「Web 工具注入围栏」+ P1「机制出自 Epic 35」×2 + P2 read-only 补回 + P3 加「时」+ A12 注释顺序换位 + A13 roles.py 指针 → `test_epic35.py / test_web_search_tool.py` + A14 web.py 模块 docstring 双工具化
- B1（fix-now ✓）：响应形状契约——根非对象/缺 results/非 list → 显性报错 NON_TRANSIENT；非 dict 条目计丢弃
- B2（fix-now ✓）：缺 url 丢弃——部分丢弃 logger.warning；**全部丢弃显性报错**（不冒充零命中）；真实零命中返回 []
- B3（fix-now ✓）：`test_client_kwargs_observed` 钉死 trust_env=False + timeout 传递
- B4（fix-now ✓）：3xx 显性分支（TRANSIENT，不落 JSON 分支）
- B5（fix-now ✓）：`register_engine` 重复注册显性报错
- C1（fix-now ✓，用户裁定方向）：tools→providers.retry **唯一声明边**——`test_architecture_contracts.py::test_tools_providers_edge_is_pinned_to_retry` 钉唯一性 + frame.md §3 DAG 规则行补记例外
- C2（fix-now ✓，用户裁定方向）：错误消息自携分类指引（`_CATEGORY_HINTS` 四类确定性文案：限流/认证/临时/拒绝）

留票待领（defer，上下文自带免重勘察；是否升 open-items 台账由 Sofia/用户后续定）：
- C4（A7）：装配点引擎名校验 fail-loud（错名穿越启动、dream 中段爆）——等真实误配案例或引擎数增长再领
- C5（A15）：WEB_SEARCH_ENGINE 组理由文案失真（挂 outbound_redirect「准外泄通道」）——等控制台文案批
- A11：双层钳位 [1,10]/[1,20] 分工无契约文字——等第二引擎出现时一并写协议 docstring
- E7：空白字段条目误报「（无检索结果）」——边际，accept-as-is 观察项

记录面（retro 不改 plan；经用户指令 2026-11-16 会话内补全）：
- R1 ✓：61.2 plan 四框补勾 + 61.1 plan Review 节结论补录（工作实际已交付 `1877250` + `82388f2`，纯记录同步）

## Decision records

- 本 run 用户裁定（2026-11-16，交互确认）：批 A+B 当场修 / C1 钉死+补记 / C2 消息自携 / C3 维持 RuntimeError 惯例（accept-as-is，后续 retro 不再重提）。C1 的落盘记录 = 契约测试 + frame.md DAG 行；C2 落盘 = `_CATEGORY_HINTS`；C3 零改动记录于此。
- 不另立 ADR 文件：epic 四项原始裁定（Tavily 默认/无密钥常在显性报错/子代理同面/正式票树流）已录 `epic-61-web-search.md` 信封「裁定记录」节。

## Acceptance verdict

**accepted-with-open-items**（criteria: declared）

- pending_tickets = 空（三票全 done，机器裁定不被强制 rejected）
- CAP-1 ✓（引擎面空/超长显性报错 + 23 引擎测试）；CAP-2 ✓（registry 可插拔测试）；CAP-3 **部分→本批已补**：guard 同构 ✓，三处放行面验证钉本批补齐；CAP-4 ✓（测试 + 无密钥路径活体实证）
- Done when：替身全链 ✓（38 web_search 测试）/ 真实密钥冒烟 ✗（用户裁定挂账 A55，等 WEB_SEARCH_API_KEY）/ 全量+ruff+mypy ✓ / docs strict ✓
- Open items：A55（真实冒烟，等外部触发）；deferred 批 C4/C5/A11/E7（retro 文档留档）；R1 记录面同步
- 门禁证据（收口修复批后复跑）：定向面 157 例全绿；全量 4421 passed / 6 failed——5 红 = `test_setup_ws_external`（verify_baseline 干净 HEAD 同红 16/5，**environmental**）；1 红 = `test_parallel_full_chain_host_wiring_with_git_audit`（首跑红复跑绿未复现，改动面不涉及 goal/audit，按 flaky 记录）；ruff check + format + mypy 201 files + mkdocs strict 全绿

## Open questions

- tools 计数口径：29 = ToolRegistry 注册数（2026-11-16 实计）；若后续纳入 MCP 桥接工具需再校口径
- deferred 批（C4/C5/A11/E7）是否升 open-items 台账条目，由 Sofia/用户后续裁定
- A5 张力（工具面 RuntimeError vs 引擎 ToolError）按用户裁定维持惯例——第二引擎或程序化调用方出现时再议
