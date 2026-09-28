# Epic 50 网页控制台周期遗留项台账（deferred-work）

> **归并来源**：`implementation-artifacts/deferred-work-archive.md` 的 **Z-D13 / Z-D14 / Z-D15**（Story 50-5 配置写入通道 ×2、Story 50-6 控制台 UI ×1）；2026-09-24 按「**条目闭合后按归属 epic 归档**」规则从活动台账的闭合归档区回填至本文件。
> **归档规则**：按条目**归属的 epic** 归档；「闭合者」注明实际完成它的批次 / commit。
> **2026-09-27 再回填 2 条**（均为「代码先修、台账后补」）：A9 运行时归因与兜底族（收口评审三镜头）、A18「共 N 个会话」在 N > 200 时少报（Story 50-8 收口后评审）。
> **只登记已闭合项**——原始长文历史不再保留，结论全部指向代码与测试。
> **活动（未闭合）遗留项**仍在 [`implementation-artifacts/deferred-work-archive.md`](../../implementation-artifacts/deferred-work-archive.md)（工作流 append-only 入口）——**本周期相关未闭合条目（2026-09-28 实测；活动区共 8 条）**：跨项目并发无全局上限（已交付可选 `HTTP_MAX_TOTAL_INFLIGHT`，默认 0 = 不限 ⇒ 仍无全局软上限）/ 控制台端点阻塞 I/O（唯一残余 `_runtime_for`，有意保留并有升级条件）/ 浏览器级 UI 验收不在 CI / 网页请求可拉起宿主 GUI 进程 / 真实原生窗口不可自动化 + `Error:` 前缀判据。**此前列出的三条已不在此列**：非回环运行姿态 + cron 跨会话后置执行（**部分闭合**：cron 部分已闭合，非回环 ① 已裁定维持现状）、R5 收敛判据失效（**裁定收紧规格**）、原生目录选择端点默认开（**裁定默认改按需**）。**编号口径（2026-09-28 统一）**：活动区条目**无编号**（正文只按 source_spec 排列）；A 编号的唯一事实源是台账的「**A 编号登记表**」（A1~A19 + A23 一一对应 20 个事项，同号异义已消除；A20~A22 为撤号）。本引言提到的条目对应号为：R5 收敛判据失效 = **A17**、原生目录选择端点默认开 = **A19**、掩码域后缀制 = **A23**；撤号（旧 A21 / A22 / A20「总结」/ 旧 A19「掩码域」）不复用，对照见登记表的「撤号 / 别名」段。

## 状态总览

| ID | 归属 | 条目 | 状态 | 闭合者 |
|----|------|------|------|--------|
| Z-D13 | Epic 50 · Story 50-5 | 写通道可把「资源旋钮」键设成无界值 | 已闭合（2026-09-24） | `config.catalog.RESOURCE_CEILINGS` 21 键上界（用户裁定「顺手闭合」） |
| Z-D14 | Epic 50 · Story 50-5 | 审计文件无保留期 / 条数上限 | 已闭合（2026-09-24） | `config.write.prune_audit` 行级裁剪至最近 500 条（同批） |
| Z-D15 | Epic 50 · Story 50-6 | 首页加载即弹出关不掉的确认遮罩（作者级 `display` 压过 `hidden` 属性） | 已闭合（2026-09-24） | `[hidden]{display:none!important}` 全局守卫 + `settleConfirm` 先隐藏再结算（用户实测发现） |
| Z-D19 | Epic 50 · 第四轮评审 | 诊断折叠标题把信息性 note 计入「需要注意」（并双计 BOM） | 已闭合（2026-09-27） | `5f4324b` 的 `INFORMATIONAL_NOTES` 分级 + BOM 去重；同日收口批 `d7f8c75` 补齐判据（探针桩自洽化 + 用例 `V`） |
| A9 | Epic 50 · 收口评审三镜头 | 运行时归因与兜底族（取消归因 / 工具卡死 / 订阅限额） | 已闭合（2026-09-27） | `a1f7c67`（三处独立修复 + 新增 `HTTP_TOOL_INFLIGHT_TIMEOUT`；变异体 3/3 精确变红） |
| A18 | Epic 50 · Story 50-8 收口后评审 | 「共 N 个会话」在 N > 200 时少报 | 已闭合（2026-09-27） | `7b9015f`（`count_sessions` + 协议 `total` + 前端 capped 分支；变异体 2/2 精确变红） |
| Z-D21 | Epic 50 · Story 50-3 并发写 | 同一会话文件的两个写者整份覆盖对方历史（静默数据丢失） | 已闭合（2026-09-27） | `SessionStore.save(base=...)` 内容基线 + 保守合并 + WARNING 回退；判据 11 条（含 run 级），变异体 5/5 精确变红 |
| Z-D22 | Epic 50 · 收口评审第二轮 | 写入通道与保真写的四类低危残余 | 已闭合（2026-09-27，四面全处置） | `a1b9403`（回滚失败文案）+ 锁作用域收窄（台账 A14③）；判据 7 条，变异体 4/4 + 4/4 |
| Z-D23 | Epic 50 · Story 50-6 AC7/UX-DR3 | 「高影响键的差异化确认」缺后端风险标记 | 已闭合（2026-09-27） | `impact_for` ← `RESOURCE_CEILINGS`（既有常量作事实源）+ 面板徽标 + 确认框点名；判据 3 条，变异体 4/4 |

---

## Z-D13 写通道可把「资源旋钮」键设成无界值

- **来源**：Story 50-5 实现期实测（2026-09-24）发现；登记于活动区「Story 50-5 实现（网页控制台配置写入通道）」条目（该条目 2026-09-24 同日闭合）。
- **问题**：`MAX_ITERATIONS` / `GOAL_MAX_ITERATIONS` / `SUBAGENT_MAX_ITERATIONS` / `MAX_OUTPUT_TOKENS` / `MAX_CONTEXT_TOKENS` 在 `Settings` 里只有下界（`ge=1`），而 `VALUE_GUARDS` 只收了 5 个弱校验键 ⇒ 一旦开启写闸门（`HTTP_CONSOLE_WRITE_ENABLED=true`），白名单内的写入就能把它们设成 `10^9`：一次 run 的迭代 / 输出 / 上下文预算变成「不可完成」。这不是安全边界问题，是「本机资源旋钮」问题（闸门默认关、只写项目 `.env`、有备份与审计）。
- **结论**：**已闭合**（2026-09-24，用户裁定「顺手闭合」）。`VALUE_GUARDS` 补 5 个上界：`MAX_ITERATIONS` / `GOAL_MAX_ITERATIONS` / `SUBAGENT_MAX_ITERATIONS` = **10000**、`MAX_OUTPUT_TOKENS` = **1000000**、`MAX_CONTEXT_TOKENS` = **16000000**。口径 = 人类尺度理性上限（迭代类 ≈ 默认值 200–500 倍；上下文 ≈ 默认 512k 的 31 倍；输出无默认值、取最大真实模型输出窗口的约 8 倍），只挡手滑与恶意极值。**同日 follow-up 把同域残余一并闭合**（用户裁定「要处理」）：新增 `config.catalog.RESOURCE_CEILINGS` 作**单一事实源**（`VALUE_GUARDS` 由它合并），上界表从 5 键扩到 **21 键**，按族给刻度 —— `days` **3650**（10 年）/ `seconds` **604800**（7 天）/ `bytes` **8388608**（8 MiB）/ `tokens` **1000000** / `count` **100**；迭代预算 **10000** 与上下文窗口 **16000000** 量纲不同，自成刻度。
- **冻结边界（逐条守住）**：① **不改 `Settings` 字段定义**（不给任何字段加 `le=`）⇒ 既有配置文件的可加载性不变；② 守卫只作用于**写入通道**（`config.write.guard_reason`）与**面板展示**（`guards_for` → `ConfigItemResponse.guards` → 前端 `guardHint`）—— 手工改 `.env` 仍不受该上界约束（该形态由 50-6 的探针用例 `test_enum_guard_renders_a_select_with_the_allowed_values` 与验收清单 A11 钉住：面板取值提示完全由后端 `guards` 派生，前端不硬编码任何键名或边界）；③ 不把它表述为安全边界（沿用全项目立场）。
- **证据**：`src/heagent/config/catalog.py::RESOURCE_CEILINGS`（21 键 → `VALUE_GUARDS` 合并，与面板同一常量）；`tests/test_config_catalog.py::TestGuards` 三条 —— `test_every_ceiling_is_generous_and_actually_applied`（遍历常量表本体：上界真的进了 `guards_for` + 「≥ 默认值的 10 倍」）、`test_no_whitelisted_numeric_key_is_left_unbounded`（**完备性**：白名单数值键一个都不能漏）、`test_the_ceiling_table_is_exactly_the_agreed_one`（**口径固化**：逐条比对键与刻度 —— 规则挡不住「604800 悄悄改成 999999999」这种仍然 ≥10 倍、仍然完备的改动）；`::test_ceilings_do_not_change_what_settings_accepts`（`Settings(max_iterations=10_000_000)` 仍可构造 ⇒ 不改 `Settings` 语义）；`tests/test_config_write.py`（11 条越界参数用例 + `test_resource_ceilings_block_only_extremes` 双侧断言 + `test_a_retention_ceiling_applies_once_it_is_not_environment_provided`）；`tests/network/test_http_console_config.py::test_panel_shows_the_resource_knob_ceilings`（**遍历同一常量表**断言面板逐条展示，前端零改动）。负向验证：`.heagent/tmp/mutate_guards_audit.py` 6 条上界类变异体全部精确变红后复原 —— 整表清空（18 红）/ 全部改成 `1e15`（16 红）/ 少给一个键（3 红）/ 上界低于默认值（2 红）/ 单键形同虚设（2 红）/ 误给 `_DAYS` 键加 `minimum=1` 破坏「0 = 禁用回收」（1 红）。**实现期两条旁证**：① `Settings` 侧只有下界的落点 = `src/heagent/config/__init__.py:121/122/129/154/158/159`（`ge=1`、无上界；原地列出的 `:126` 实测已非 `ge=1` 字段，已剔除）；Story 50-5 的 T9 参数化用例**删掉了**原计划的「`MAX_ITERATIONS=100000` 必须被拒」（实测无上界、断言本就不成立）。② 变异体 M1 首轮只红 4 条，查因发现新加的 4 个参数用例写的是 `1e9`，而 `int` 字段的候选构造**本来就会拒掉 `1e9`** ⇒「有上界」与「没上界」都通过，**用例不具区分性**；改成合法整数字面量 `1000000000` 后 5 条全部变红（教训已写进用例注释）。
- **发现并纠正的一处计数错误**：首轮盘点脚本按 `annotation` 判「数值型」，而 `int | None` 没有 `__name__` ⇒ 漏掉了 `MAX_OUTPUT_TOKENS` / `SKILL_MAX_AUTO_INVOKE_TOKENS` / `SKILL_MAX_MANUAL_LOAD_TOKENS` 三个键，于是本条目一度把残余记成「13 个」。改用守卫判据复核（`guards_for(key).kind == "range" and maximum is None`）得**真实为 16 个**（本条的 5 个 + 其余 16 = 21 键）。教训：盘点「某类键还有几个」时，判据要跟着**实际生效的那条路径**（守卫）走，不要跟着类型注解走；探针 `.heagent/tmp/ceiling_survey.py` 已改为守卫判据。
- **残余（同域）—— 2026-09-24 同日 follow-up 已闭合**：另外 16 个「只有下界」的键（磁盘保留期族 `*_RETENTION_DAYS`、字节预算族 `CONTEXT_FILES_MAX_BYTES` / `MEMORY_INJECT_MAX_BYTES`、秒级间隔与超时 `SHELL_TIMEOUT` / `CRON_TICK_SECONDS` / `PRUNE_MIN_INTERVAL_SECONDS`、技能条数与深度 `SKILL_MAX_AUTO_INVOKE` / `SUBAGENT_MAX_DEPTH`、`SKILL_*_TOKENS`、`SKILL_CURATOR_STALE_DAYS`）已由 `RESOURCE_CEILINGS` 按「同族同刻度 + ≥ 默认值 10 倍」补齐；**白名单数值键现在全部有上界**（`test_no_whitelisted_numeric_key_is_left_unbounded` 钉住完备性，`config.catalog.VALUE_GUARDS` 的 docstring 第 2 点已从「本表不是全部」改写为「完备性已闭合」）。这批键的两条**额外**理由：① 它们全都支持 `0`（= 禁用回收 / 不限制）⇒ 上界**不剥夺任何合法意图**（「永久保留」写 `0` 比写 `36500` 更明确）；② 测试环境里 7 个键被 `tests/conftest.py` 的 `os.environ.setdefault` 钉成 0 ⇒ 写通道会先按 F1 判 `field_not_writable`（对，但会掩盖守卫），故保留期族的端到端验证另有用例显式 `delenv` 后再测。

## Z-D14 审计文件无保留期 / 条数上限

- **来源**：Story 50-5 实现期实测（2026-09-24）发现；登记于活动区同名条目（2026-09-24 同日闭合）。
- **问题**：`<项目>/.heagent/console/audit.jsonl` 每次成功写入追加一行（约 300 B），只有 `append_audit` 的「失败不阻断已成功的写」语义、没有任何回收；对照之下备份目录有 `MAX_CONFIG_BACKUPS=50` + 30 天保留期。触发条件：回环客户端反复成功写入 × 长时间运行 ⇒ 审计资产反噬磁盘。
- **结论**：**已闭合**（2026-09-24，用户裁定「顺手闭合」）。新增 `config.write.prune_audit`：超 `MAX_CONFIG_AUDIT_ENTRIES=500` 行即整体重写（`pub.persist.atomic_write_bytes`）只留**最近 500 条**、保留 LF 行尾；由 `append_audit` 在追加成功后调用（无跨进程节流，理由同备份目录：一次 scandir / 一次读的代价远小于节流标记的维护成本）。
- **修正了台账原拟修法的形状**：原条目写的是「按 `.jsonl` 后缀 + 条数上限」的**文件级**回收（与 `prune_backups` 同款内核）—— 但审计是**一个持续追加的文件**：目录里永远只有 1 个 `.jsonl`，那套内核的候选集合恒为空（照做等于没做，会「闭合」在纸面上）。实际做在**行**级。
- **冻结边界（守得更紧）**：不做 glob、不做后缀扫描，只认 `console_dir / AUDIT_FILENAME` 这一个已知文件名 ⇒ 同目录的项目注册表 `projects.json` 连候选都进不去（该目录在内部状态读拒集合内，误删不会有读取报错兜底）。`max_entries=0` 的语义与 `prune_backups` 对齐（保留 0 条）。
- **失败立场**：裁剪是**维护动作** —— 任何异常只 WARNING，绝不让「已追加成功且写已生效」的响应变成错误（否则文件已改而响应 500，用户重试又撞 `config_conflict`）；调用点包 catch-all。
- **证据**：`src/heagent/config/write.py::prune_audit` / `append_audit` / `MAX_CONFIG_AUDIT_ENTRIES`；`tests/test_config_write.py::TestAuditRetention`（11 例：只留最近 N 条 / 未超限则字节不变 / 文件缺失不报错 / 读失败与写失败各自降级为 0 / 裁剪后仍是 LF + JSONL / 末行无换行也算一条 / **同目录注册表不被触碰** / 裁剪失败不改写 `audit_recorded` / 端到端追加即触发裁剪 / 写通道自身路径亦受上限约束）。负向验证：`.heagent/tmp/mutate_guards_audit.py` M3–M7（回收缺席 / 边界错位 / 方向错 / 越界删邻居 / 失败外传）→ 6 / 6 / 5 / 1 / 1 条精确变红后复原。

## Z-D15 首页加载即弹出关不掉的确认遮罩（`hidden` 属性被作者样式压过）

- **来源**：Story 50-6 交付（`f5f4c3f`）之后由**用户实测**发现（2026-09-24：打开网页即弹对话框）；非评审发现。
- **问题**：`styles.css` 的 `.overlay { display: flex }`（50-6 的 UI 改造引入）是**作者级**声明，压过 UA 样式表的
  `[hidden] { display: none }` ⇒ `#confirm-overlay` 带着 `hidden` 属性照样渲染：`position: fixed` + `inset: 0` +
  `z-index: 20` 的全屏遮罩在首页加载时就盖住整页并吞掉全部真实鼠标点击；且「取消 / 确认」都关不掉
  （`settleConfirm` 当时在隐藏遮罩**之前** `if (!pending) return;`，而加载时本就没有 pending）⇒ 只能刷新页面脱身。
  真浏览器实测（headless Edge + CDP）：属性 `hidden=true` 而计算样式 `display=flex`、有盒子；`elementFromPoint`
  （发送按钮处 / 侧栏处）= `confirm-overlay`；真实点「取消」之后 `display` 仍是 `flex`。
- **为什么 17/17 的浏览器验收没抓住（三条判据问题）**：① 清单只断言 `element.hidden`（属性），属性翻回去就算过，
  看计算样式的只有 A1（安全声明）与 A15（侧栏）；② 其 `click()` 用 `node.click()`（DOM API）——**绕过命中测试**，
  全屏遮罩吞点击在它眼里不存在；③ `app_probe.js` 是 node 的最小 DOM 替身，**没有 CSS 级联**。加之 Story 49-6 的
  人工浏览器点选验收当时并未执行，「看得见却点不动」这类问题此前没有任何一层覆盖。
- **结论**：**已闭合**（2026-09-24，用户裁定按 1/2/3 三件一并处置）。① `styles.css` 加全局守卫
  `[hidden] { display: none !important; }`（作者级 `!important` 压过其余作者规则 ⇒ 新增遮罩 / 面板不必各自再配
  `[hidden]` 分支）；② `settleConfirm` 改为**先隐藏遮罩、再处理 pending**（失败模式从「关不掉」降级为
  「点一下关掉」；CSS 守卫已使该组合不可达，属 defense-in-depth）；③ 判据补强 —— CI 内
  `tests/test_http_web_ui.py::TestHiddenAttributeSemantics`（守卫必须存在且 `!important`；交叉扫描 `index.html`
  的 10 个 `hidden` 元素与 `styles.css` 的 display 规则，任何能压过 hidden 的元素都必须有守卫兜底）+ 探针用例
  `O`（可见但无 pending 时取消 / 确认必须关掉遮罩）+ 真实浏览器验收新增 **A1b**（计算样式 `display === "none"`、
  `getClientRects().length === 0`、`elementFromPoint` 与 CDP 真实鼠标点击的落点都不是遮罩）。
- **证据（全部实跑）**：负向 —— `git checkout HEAD -- styles.css` → 恰好 2 条断言变红并报出
  `#confirm-overlay <- .overlay`（还原后 sha256 一致）；回退 `settleConfirm` 顺序 → 探针用例 O 变红
  （`afterCancel=False`）；无守卫时整份浏览器清单**只有 A1b 变红**（exit 1，其余 17 行照旧 PASS）。正向 ——
  `ACCEPTANCE {"rows":18,"failed":0}`；`pytest tests/test_http_web_ui.py tests/network -q` → 421 passed；
  `ruff check` / `ruff format --check` 全绿。
- **残余（如实标注）**：① 真实命中测试目前只有 A1b 一行 —— 其余用例仍用 `node.click()`（有意保留：真鼠标点击对
  布局变化更脆），故「全屏元素遮挡」类缺陷只有这一行覆盖；② 本条不改变「浏览器验收不进 CI」的既有立场；
  ③ 静态断言只做「守卫存在 + 是否存在能压过 hidden 的作者规则」这一层，**不解析级联优先级**：若有人显式写
  `.overlay[hidden] { display: flex !important }`（或更具体的 `[hidden]` 复合选择器），静态断言与守卫都放行 ——
  此时只有真浏览器 A1b 拦得住（而它不在 CI）。

## Z-D19 诊断折叠标题把信息性 note 计入「需要注意」（并双计 BOM）

- **来源**：Epic 50 第四轮评审发现（2026-09-26 登记于活动区，标 `intent_gap / blocked 待人裁决`）。
- **问题**：`app.js::renderDiagnostics` 把 `config.notes` **整条** push 进 `warnings`，而 notes 里混着纯信息项（`project_env_missing` = 「项目 `.env` 不存在：全部字段回退到全局 `.env` / 默认值」，新项目的**常态**）⇒ 一个刚登记、没有任何 `.env` 的项目一打开设置面板就看到红色的「1 条需要注意」；同一事实还会**双计**（BOM：前端硬编码的 `env_file.has_bom` 告警 + `project_env_bom_stripped` 这条 note 各推一条）。
- **结论**：**已闭合**（2026-09-27）。`5f4324b` 引入分级与 BOM 去重——`INFORMATIONAL_NOTES = new Set(["project_env_missing"])`（信息性 note 进 `infos`，只有非信息性 note 进 `warnings`）+ `seenBom` 跳过同源的 `project_env_bom_stripped`；同日收口批（`d7f8c75`）补上**缺失的判据**：前端探针桩自洽化（`exists: true` 不再同时给 `project_env_missing`；告警改由「重复键 + 空值键」两条真实来源产生）+ 新增用例 `V`（断言信息性 note **不计入**告警条数、`dataset.state == "idle"`、说明仍以 `.diag-info` 可见）。
- **冻结边界（守住）**：不得因此把 note 整类删掉（它是 50-6 AC5 的诊断面），只改**分级**；信息性 note 必须**仍然可见**（降级 ≠ 删除）——该侧由用例 `V` 的 `infoTexts` 断言钉住。
- **证据**：`src/heagent/web/app.js`（`INFORMATIONAL_NOTES` / `seenBom` / `warnings` vs `infos` 分流）；`tests/js/app_probe.js`（`configPayload` 的 `envMissing` 分支 + 用例 `V`）；`tests/test_http_web_ui.py::TestConsoleRefinement::test_informational_notes_do_not_count_as_warnings`。负向验证：把 `INFORMATIONAL_NOTES` 清空 → 用例 `V` 精确变红（`.heagent/tmp/e50_mutate2.py`）。

---

## A9 运行时归因与兜底族（取消归因 / 工具卡死 / 订阅限额）

- **来源**：2026-09-24 Epic 50 收口评审（三镜头）· 运行时归因与兜底族；2026-09-27 闭合后按「条目闭合后按归属
  epic 归档」规则由活动台账回填至本文件（活动区只留索引）。
- **原条目正文（保留原文以存证）**：

- source_spec: 2026-09-24 Epic 50 收口评审（三镜头）· 运行时归因与兜底族
  summary: **HTTP 运行时的三处归因/兜底薄弱点（同一族）**：① 看门狗的 `deadline_reason` 一经写入便永久保留，`_execute` 仅凭「非 None 且未在关停」判定「是超时杀的」⇒ 若 executor 吞掉第一次取消并继续跑，**之后**用户的 `DELETE` 会被记成 `timed_out` 并吞掉取消（`reopen()` 还能把 `_closing` 清回 False，理论上让旧任务上报 `timed_out`）；② `tools_in_flight` 只由 `tool_call`/`tool_result` 增减、永不衰减 ⇒ 一个**永不返回**的工具会让「静默上限」判据恒不成立，该项目的在途名额被无界占用（`HTTP_REQUEST_TIMEOUT` 默认 0）；③ SSE 订阅者上限是「先查后加」（检查在端点、登记在生成器首个 `__anext__`）⇒ 并发 `GET .../events` 可穿过限额，每个订阅者驻留一个 512 事件队列。触发条件：吞取消的 executor / 卡死的工具 / 并发订阅；严重度：中（不崩、名额最终仍可人工回收，但会静默错归因或放大内存）；冻结边界：不得改变「首位获胜」的终态语义与每项目单运行约束；①②的修法是「取消来源令牌（消费一次）」与「在途工具计龄」，③需在单次事件循环内把检查与登记合到同一步。
  evidence: `src/heagent/network/http_server.py:659`（静默判据含 `tools_in_flight == 0`）、`:665`（`record.deadline_reason = ...` 后 `task.cancel()`）、`:690`/`:710`（`deadline_reason is not None and not self._closing`）、`:780`（`record.subscribers.add(queue)`）、`:1238`（端点的先查后加）；探针证据见评审报告「镜头一④⑤ / 镜头二①②」（含实际行号与代码引用）。
  Progress（2026-09-24 登记，**未修**）：三处均**在本 Epic 增量内引入或触碰**（看门狗=commit `4f67397`），但修复后都需要新的时序测试（吞取消的 executor / 卡死工具 / 并发订阅），本次评审范围内未做——如实登记而非假装修好。

- **结论**：**已闭合**（2026-09-27，commit `a1f7c67`）。三处同族缺陷各自独立修复：
  ① **取消归因** —— `_RunRecord.user_cancel_requested` 标记「用户显式 `DELETE`」（归因时**优先**于看门狗），
  `deadline_reason` 配一次性消费器 `consume_deadline_reason()`（字段**不清空**——终态文案 / 日志 / 测试仍读它）；
  `_execute` 的 `CancelledError` 分支先看用户标记，再看待消费的原因。
  ② **工具在途无上限** —— 新增独立配置键 `HTTP_TOOL_INFLIGHT_TIMEOUT`（`Settings.http_tool_inflight_timeout`，
  默认 3600s，归因 `reason=tool`，文案 `run stalled: a tool has been in flight for over Ns`）；
  `_RunRecord.tools_in_flight_since` 记「第一条在途工具的时刻」，看门狗据它判「工具卡死」。
  **刻意不复用** `idle_timeout`：长 shell / 子代理期间同样没有事件，用静默阈值会误杀正常长调用
  （既有用例 `test_in_flight_tool_stretches_the_idle_window` 钉的正是这一点）；`_deadline_tick()` 一并把新阈值
  纳入启动判据，否则设了也不会启动看门狗。
  ③ **订阅限额「先查后加」** —— `_RunRecord.try_add_subscriber(queue, limit)` 把检查与登记合成**同步一步**
  （同步、无 `await` ⇒ 事件循环里原子）；端点先建队列再登记，`stream_events` / `_sse_stream` 接受调用方
  已登记的队列（自建路径仍保留）。
- **冻结边界（守住）**：「首位获胜」的终态语义、每项目单运行约束、`deadline_reason` 字段本身一字未动
  （只加「是否已消费」的标志）。
- **证据**：`src/heagent/network/http_server.py`（`_RunRecord.tools_in_flight_since` / `consume_deadline_reason` /
  `try_add_subscriber`；`cancel_run` 打标记；`_watch_deadlines` 第三条判据；`_deadline_message` 的 `tool` 分支；
  `_execute` 的两处归因）；`src/heagent/config/__init__.py` 的 `http_tool_inflight_timeout`；
  `src/heagent/cli/http.py` 的装配行；`.env.example` 的 `HTTP_TOOL_INFLIGHT_TIMEOUT`。
- **验证（2026-09-27 亲跑；本轮复跑）**：定向
  `pytest tests/network/test_http_run_service.py tests/network/test_http_console_sessions.py tests/test_session.py tests/test_http_web_ui.py tests/test_cli_http.py -q`
  → **357 passed**；三条判据 = `test_a_consumed_deadline_does_not_blame_a_later_delete` /
  `test_a_tool_in_flight_longer_than_its_own_limit_is_reaped` /
  `test_subscriber_limit_is_checked_and_registered_in_one_step`；变异体 **3/3 精确变红**
  （`.heagent/tmp/e50_mutate_a9.py`：用户取消不再优先 / 在途工具不再有独立上限 / 订阅限额退回「只查不登记」），
  每处字节还原后基线复绿。**文档同步**：`docs/frame.md` §4.17「限额与超时」（补第三条时限 + 取消归因 + 订阅
  限额同步登记）、「运行隔离」（补「不绑定 cron 工具」）、同节配置表新增 `http_tool_inflight_timeout` 行、
  `HttpServerConfig` 字段数 9 → 11。

## A18「共 N 个会话」在 N > 200 时少报

- **来源**：2026-09-26 Story 50-8 的收口后评审（增量轮）；2026-09-27 闭合后回填至本文件。
- **原条目正文（保留原文以存证）**：

- source_spec: `_bmad-output/epics/epic-50-网页控制台周期/stories/50-8-console-ux-refinement.md`（R1/AC12 的会话计数，2026-09-26 收口后评审发现）
  summary: **「共 N 个会话」在 N > 200 时是下界而非总数（静默少报）** —— 服务端列表硬上限 `context.session.MAX_SESSION_LIST_LIMIT` / `http_console_protocol.MAX_SESSION_LIST_ENTRIES = 200`，按时间降序截断，响应里**没有** `total` / `truncated` 字段；Story 50-8 新增的规模提示（`共 N 个会话 · 只显示最近 10 条`）与展开按钮文案（`显示全部（N）`）直接把 `sessions.length` 当总数 ⇒ 项目累计超过 200 个会话时，页面显示「共 200 个会话」并宣称「显示全部」，第 201 条起既不可达、又被这句话说成不存在（它们本来就不可达，是本次新增的**文案断言**让它变成「说错话」）。触发条件：单个项目累计 > 200 个会话；严重度：低（显示口径，不是数据丢失；CLI 与 API 仍可达）；冻结边界：**不得**因此改 `MAX_SESSION_LIST_ENTRIES` 的语义（服务端硬上限是既有契约，UI 的 10 只是展示默认值），也**不得**在前端硬编码 200（第二份事实源）。
  evidence: `src/heagent/context/session.py`（`MAX_SESSION_LIST_LIMIT = 200`、`list_metadata` 的 `entries[:limit]`、按 `(timestamp, session_id)` 降序）；`src/heagent/network/http_console_protocol.py:121`（`sessions: list[...] = Field(max_length=MAX_SESSION_LIST_ENTRIES)`，无 total）；`src/heagent/web/app.js::renderSessionCount`（`total = state.sessions.length` 直接当总数）；真浏览器清单 A11b 实测 195 档（未越界，故本条当前**无判据**）。
  Progress（2026-09-26 登记，**未修**，**intent_gap / blocked 待人裁决**）：两条修法都改变可观察行为——(a) 协议加 `total` / `truncated`（`SessionListResponse` 字段 + 入口层赋值 + UI 分支 + 探针用例），或 (b) 改文案（去掉「共」的全称含义 / 按钮不带计数）。属产品取舍，非实现方可单方决定。

- **结论**：**已闭合**（2026-09-27，commit `7b9015f`）。三条同步（缺一即漂移）：
  ① `SessionStore.count_sessions()` —— 只列目录计数、**不解析任何文件**（规模事实的唯一来源）；
  ② `SessionListResponse.total`（协议层首次携带规模事实），入口层用 `max(计数, len(sessions))` 赋值
  （容忍「列表读完后又有新会话落盘」）；
  ③ `web/app.js` 的规模取自 `payload.total`；列出条数 < 总数时文案注明「服务端仅返回最近 N 条」
  并**隐藏「显示全部」**（截断时它是假承诺）。
- **冻结边界（守住）**：`MAX_SESSION_LIST_ENTRIES = 200` 的硬上限语义未改（UI 的 10 只是展示默认值）；
  前端**零硬编码** 200 —— 规模数字全部由协议给。
- **证据**：`src/heagent/context/session.py::count_sessions`；`src/heagent/network/http_console_protocol.py`
  的 `SessionListResponse.total`；`src/heagent/cli/http_console.py::list_sessions`；`src/heagent/web/app.js`
  的 capped 分支；`tests/js/app_probe.js` 用例 `W`。
- **验证（2026-09-27 亲跑；本轮复跑补全第二条变异体）**：判据 4 条 ——
  `tests/test_session.py::test_count_sessions_counts_files_without_parsing`（`.lock` 不计入）、
  `tests/network/test_http_console_sessions.py::test_session_limits_are_mirrored_not_drifted`（协议必须带 `total`）、
  `::test_session_list_total_counts_files_not_the_page_window`（把 `count_sessions` 换成 500 后 `total` 必须跟着变）、
  `tests/test_http_web_ui.py::TestConsoleRefinement::test_session_count_never_claims_to_show_everything_when_capped`
  （capped 文案 + 按钮隐藏）。变异体 **2/2 精确变红**
  （`.heagent/tmp/e50_mutate_a18.py` 的前端 `capped` 判定被抹平、
  `.heagent/tmp/e50_mutate_a18b.py` 的「入口层退回 `total = 列表长度`」），字节还原后基线复绿。

## Z-D21 同一会话文件的两个写者整份覆盖对方历史（静默数据丢失）

- **来源**：Epic 50 Story 50-3（网页运行 → 会话落盘接进同一 `.heagent/sessions`）暴露的并发写；2026-09-26 第四轮评审登记，2026-09-27 闭合后按「条目闭合后按归属 epic 归档」规则回填至本文件。
- **原条目正文（保留原文以存证）**：

- source_spec: `src/heagent/context/session.py::save` + `src/heagent/agent/run_lifecycle.py`（Epic 50 Story 50-3 把「网页运行 → 会话落盘」接进同一 `.heagent/sessions`）
  summary: **同一会话文件的两个写者会整份覆盖对方的历史（静默数据丢失）**：运行落盘的 `save()` 不传 `expected_version`（last-write-wins），而文件锁只覆盖「单次读改写」、不覆盖 `load → … → save` 的整个跨度 ⇒ CLI 与内嵌网页入口（默认项目根 = 进程 cwd = 同一工作区，`.heagent/sessions` 同一目录）并发写同一会话时，后写者用 `_session_payload` **替换整份消息列表**，对方的整轮对话消失，且 `version` 照样单调递增（没有任何一方能发现）。触发条件：同 cwd 下 CLI 与会话页并存，且网页 `POST /api/projects/default/runs` 不带 `session_id`（`_resolve_session(None)` 取**最近**会话，往往正是 CLI 正在写的那个）；严重度：中（静默数据丢失）；冻结边界：**不得**改成「版本冲突即让运行落盘失败」（那会丢**当前**对话）；正确方向是单写者化 / 合并语义，或把冲突降级为可观测告警。
  evidence: 读码 `session.py::save`（`expected_version: int | None = None` 默认，仅非 None 时比对并抛 `SessionConflictError`）与 `run_lifecycle` 的落盘调用（只传 `session_id` + 消息列表）；`tests/network/test_http_console_sessions.py` 的替身**刻意**按「不传 `expected_version`」建模（把 last-write-wins 钉成现状），`tests/test_session.py` 只覆盖单写者覆盖。
  Progress（2026-09-26 登记）：修法需要跨 `agent/`（落盘调用点）与 `context/`（合并语义）设计，超出评审的最小修复范围。
  Progress（2026-09-27 部分改进）：**已添加可观测性机制**——`SessionStore.save()` 新增可选参数 `last_known_version`，当提供且磁盘版本跳过多个版本时（说明有其他写者介入），发出 WARNING 日志。这不会阻止写入（last-write-wins 语义保持不变），但让并发写入变得可观测，便于诊断和审计。新增 4 例测试（`TestConcurrentWriteObservability`）验证版本跳跃检测、正常递增、无参数时的行为。**根本修复仍需单写者化或合并语义**，当前为防御性改进。

- **结论**：**已闭合**（2026-09-27，commit `9860a17`）。`SessionStore.save` 新增**内容基线**参数 `base`（= 调用方 `load` 到的那份磁盘消息），运行落盘侧两处接线：`run_lifecycle.AgentState.session_base`（`init_new_run` 里**无论 prior 是否为空都记**——空也表达「我读到的是空」）+ `persist_and_cache` 把它传给 `save(base=...)`。锁内发现磁盘内容与基线不同时：
  - 能**安全**判定（三方的非 SYSTEM 投影构成同一前缀，且对方确实追加了不同内容）⇒ **保守合并**：把本次新增的消息接在对方新增的之后，**两段都保留**，并记一条点名条数的 WARNING；
  - 判不出来（磁盘共享前缀被改写 / 磁盘比基线短 / 调用方给的基线对不上 / 文件不可解析）⇒ 退回 last-write-wins + 点名原因的 WARNING（**最坏情况与改造前逐字一致，绝不更坏**）。
  SYSTEM 消息不参与比对（每次 run 重建、`load` 时剔除），合并结果只保留本次 writer 的 SYSTEM。
- **冻结边界（守住）**：① **没有**改成「版本冲突即让运行落盘失败」（那会丢当前对话）——合并/回退都不抛；② 不传 `base` 的调用方（CLI 单写者、库调用方）语义**逐字不变**（有判据钉住）；③ 显式 `expected_version` 的冲突检测**优先于**合并（有判据）。
- **残余（如实标注，未消除）**：① 判不出来时仍会丢对方那一侧（但**不再静默**：有 WARNING 点名原因）；② 只接线了**运行落盘**这一条路径（`rename` / `create` / 库调用方不传 `base`，维持 last-write-wins）；③ 2026-09-26 加的 `last_known_version` 可观测参数被更强的**内容比对**取代，本仓生产路径不再传它（保留供外部调用方，docstring 已注明）；④ 合并按「对方的分支在前、本次的分支在后」拼接——时间上通常成立（对方先写），但**同一时刻**的交叉追加无法定序（不丢数据，顺序不保证）。
- **证据**：`src/heagent/context/session.py`（`_without_system` / `_messages_from_raw` / `_merge_concurrent_writes` / `_resolve_concurrent_write` / `save(base=...)`）；`src/heagent/agent/run_lifecycle.py`（`AgentState.session_base`、`init_new_run`、`persist_and_cache`）；`docs/frame.md` 4.5 的第五条判据与 4.18 的会话持久化行。
- **验证（2026-09-27 亲跑）**：判据 **11 条**（`tests/test_session.py::TestConcurrentWriteMerge` 10 条：合并 / SYSTEM 头归属 / 前缀被改写回退 / 磁盘比基线短回退 / 基线对不上回退 / 坏文件不阻断 / 快路径零告警 / 同尾巴不重复 / `expected_version` 优先 / 不传 `base` 逐字不变；`tests/test_agent_loop.py::TestAgentLoop::test_run_save_merges_messages_appended_by_another_writer` **run 级**——让 provider 在 run 进行中写同一会话，模拟 CLI 那一侧）。变异体 **5/5 精确变红**（`.heagent/tmp/mutate_session_merge.py`：生产路径不传 `base` / 不记基线 / 合并被关掉 / 去掉「共享前缀必须一致」护栏 / 合并后取磁盘的 SYSTEM）。
  **首轮 M4 没变红**——我原来的「前缀被改写」判据里，改写后的磁盘**比基线短**，于是被另一条分支兜住了，测不出护栏本身；改成「改写后更长」并顺手删掉与切片比较**冗余**的长度判断后，M4 精确变红。教训：判据要选**能区分被测行为**的输入形状。
  全量 `pytest -q` → **3109 passed / 11 skipped / 18 deselected**；`ruff check` + `format --check`、`mypy src` + `--platform linux` 全绿。

## Z-D23 「高影响键的差异化确认」缺后端风险标记

- **来源**：Epic 50 Story 50-6 实现（AC7 / UX-DR3）；2026-09-24 登记，2026-09-27 闭合后按「条目闭合后按归属 epic 归档」规则回填至本文件。
- **原条目正文（保留原文以存证）**：

- source_spec: 2026-09-24 Story 50-6 实现（网页控制台 UI）· AC7 / UX-DR3
  summary: **「高影响键的差异化确认」缺后端风险标记**：UX-DR3 要求「写入被标记为高影响的键必须显式确认」，但 `ConfigItemResponse` 没有任何 per-key 风险/影响字段（`config_catalog` 的分组只表达来源与只读原因）⇒ 50-6 的实现口径是**所有写入都二次确认**（确认框列出将改的键、「只对下一次运行生效」、写入路径与备份语义），既不漏确认也不做分级。触发条件：写闸门开启 + 用户频繁改配置（每次都弹确认框 = 体验摩擦）；严重度：低（偏体验、不影响正确性，且「宁多确认」方向是安全的）；冻结边界：若要分级，只能**新增后端字段**（如 `ConfigItemResponse.impact` 或写进 `config_catalog` 的分类常量）并由服务端声明，**不得**在前端硬编码键名清单（那是第二个事实源，必然与白名单漂移）；分级仍是 defense-in-depth 提示，不改变写通道的 fail-closed 校验。
  evidence: `src/heagent/network/http_console_protocol.py`（`ConfigItemResponse` 字段集：无风险/影响字段）；`src/heagent/web/app.js::saveConfig`（写入前一律 `askConfirm`）；`src/heagent/config/catalog.py`（分类常量只产出 group / writable / reason）；探针用例 `TestConsoleSettingsPanel` 钉住确认框文案与「未确认不发请求」。
  Progress（2026-09-24 登记，**未闭合**）：该口径裁定记录在 story 50-6 的 Dev Agent Record（「与 story 文本的偏离」条）；若后续要分级，需先定影响分级的事实源。

- **结论**：**已闭合**（2026-09-27）。**影响分级的事实源 = `config_catalog.RESOURCE_CEILINGS`**（既有、已被测试钉死的常量）：它的语义正是这个分级要表达的东西——「有上界的键就是极端值能让一次运行不可完成的资源旋钮」。新增 `IMPACT_HIGH` / `IMPACT_NORMAL` 与 `impact_for(env_key)`，`ConfigItem.impact` → 协议 `ConfigItemResponse.impact` → 面板渲染徽标 + 写入确认框里点名「其中高影响键：…」。**刻意不新造分类表**（人工列举的清单必然与白名单 / 上界表漂移）。
- **冻结边界（守住）**：① 分级只**新增后端字段**并由服务端声明，**前端零硬编码键名**（徽标只按 `item.impact` 渲染、文案只按后端 `labels` 取；两条「按键名硬编码」的变异体都被判据精确抓住）；② 分级仍是 defense-in-depth 提示，**不改变写通道的 fail-closed 校验与既有「所有写入都二次确认」口径**（UX-DR3 只要求高影响键必须确认，不禁止全量确认）。
- **残余（如实标注）**：① 23/48 个白名单键被标为 `high`（近半数）—— 信号强度有限；更细的分级需要重新裁定事实源（可选：新增显式 `HIGH_IMPACT_KEYS` 常量 / 按「是否影响整服务而非一次运行」划分）；② 只作用于**面板**，命令行 / 库调用方看不到该标记。
- **证据**：`src/heagent/config/catalog.py`（`IMPACT_HIGH` / `IMPACT_NORMAL` / `impact_for` / `ConfigItem.impact` / `LABELS["impact_high"]` / `LABELS["impact_high_note"]`）；`src/heagent/network/http_console_protocol.py` 的 `ConfigItemResponse.impact`（`extra="forbid"` ⇒ 域模型加了字段而不镜像会立刻失败）；`src/heagent/web/app.js`（徽标 `badge-impact` + `impactOf` + 确认文案）；`docs/frame.md` §4.18 的「资源旋钮上界」行。
- **验证（2026-09-27 亲跑）**：判据 3 条——`tests/test_config_catalog.py::TestClassification::test_high_impact_is_derived_from_the_resource_ceiling_table`（**遍历上界表本体**：表内键逐个 `high`、其余全 `normal` + `labels` 有文案）、`tests/network/test_http_console_config.py::test_panel_marks_high_impact_keys_from_the_same_constant`（同款遍历，证明字段真的到达面板）、`tests/test_http_web_ui.py::TestConsoleRefinement::test_high_impact_keys_are_marked_and_named_in_the_confirm`（node 探针用例 `X`）。变异体 **4/4 精确变红**（`.heagent/tmp/mutate_a13.py`：分级不再派生 / **徽标按键名硬编码** / **确认文案按键名硬编码** / 徽标整块去掉）。
  **探针桩刻意用「倒钩值」**：桩里 `CONTEXT_STRATEGY` 报 `high`、`MAX_ITERATIONS` 报 `normal`（与真实世界相反）—— 前端任何按名字猜分级或硬编码清单的实现都会在这里翻车；文案同理用钩子值 `高影响（桩）`。

## Z-D22 写入通道与保真写的四类低危残余

- **来源**：Epic 50 收口评审（第二轮，`reviews.md#review-epic-50-closure`）· 写入通道与保真写的低危残余；2026-09-24 登记，2026-09-27 四面全部处置后按「条目闭合后按归属 epic 归档」规则回填至本文件。
- **原条目正文（保留原文以存证）**：

- source_spec: 2026-09-24 Epic 50 收口评审（第二轮）· 写入通道与保真写的低危残余（`reviews.md#review-epic-50-closure`）
  summary: **四类 low 级残余**（都在写入通道 / 保真写面上，均不阻塞收口）：① **`.env.lock` 落在用户项目根** —— `pub.persist.atomic_update_bytes` 的锁文件与目标**同目录**，故写项目 `.env` 会在**用户的项目根**留下 0 字节 `.env.lock`（评审探针实测：`['.env','.env.lock','.heagent']`）；HeAgent 自己的仓库有 `.gitignore` 条目，**用户的项目没有**。② **回滚失败时的文案不实** —— 回读不符时无条件回 `the project .env was rolled back to its previous content`，而回滚本身失败只 `logger.error`（`persist._restore_bytes`）⇒ 对直接调 API 的客户端是假话（UI 侧文案诚实：「服务端已尝试恢复备份」，且该码不在 JS 的 `DETAIL_CODES` 里、不显示服务端 message）。③ **写锁内 I/O 时长** —— `validate_candidate`（构造 `Settings` ⇒ 读候选临时文件 + 全局 `.env` + 环境）与备份目录扫描都在**跨进程锁内**完成 ⇒ 并发热点下写方可能得到 `config_write_failed`（锁超时 5s）而非 `config_conflict`（**fail-closed：无损坏、无部分写入**）。④ **无末行换行文件的追加约定** —— 追加新键沿用「文件无末行换行」这一属性（实测 `MAX_ITERATIONS=5\nSHELL_TIMEOUT=60`），是有意保真，但部分工具约定「文件必须以换行结尾」⇒ 记入备查。
  evidence: `src/heagent/pub/persist.py::atomic_update_bytes`（`lock_path = path.with_name(path.name + ".lock")`）；`src/heagent/config/write.py::_verify` 与 `_apply_locked`（候选构造 / 备份回收在 `atomic_update_bytes` 的回调内）；`src/heagent/config/envfile.py::replace_or_append`（末行换行跟随文件）；探针 `.heagent/tmp/review50_probe.py` 的 B / E / K 三例实测输出；评审报告镜头一 #1/#2/#3 与镜头二 ⑤。
  Progress（2026-09-24 登记；**2026-09-27 ① 按允许的「文档说明」修法落地**）：① 已在 `docs/frame.md` §4.18 的写通道行如实写明副作用（锁与目标同目录 ⇒ 写项目配置会在**用户项目根**留 `<项目根>/.env.lock`；HeAgent 自带 `.gitignore` 条目、用户项目没有），并重申**锁的落点语义不改**。③④ 仍未修（冻结边界；② 的改造已在 2026-09-27 落地）: ① 锁文件**刻意不删**（删除会引入「B 等旧 inode、C 拿新文件加锁成功」的竞态，见 `persist` 模块注释），挪到状态目录会改变锁语义 ⇒ 修法只能是「写入方提示 / 文档说明」，**不得**改锁的落点语义；③ 收窄需「锁外构造候选 + 锁内复检指纹」的乐观重试，属流水线结构调整。三条都超出「评审期最小修复」范围，故如实登记而非草率改动。
  Progress（2026-09-27，**② 已闭合**，commit `a1b9403`）：回滚失败不再是内部细节——`persist` 新增 `RollbackFailedError`
  （`__cause__` = 原回读异常、`rollback_error` = 回滚失败原因），`atomic_update_bytes` 在「``verify`` 抛错
  且 ``_restore_bytes`` 也抛错」时抛它；写通道据此给出**如实**文案（`post-write verification failed and the
  previous content could not be restored (<原因>)`，不再无条件宣称「已回滚」）并落 `rollback_failed` 审计。
  判据 3 条（`tests/test_persist_atomic.py::TestAtomicUpdateBytes::test_verify_failure_with_a_failed_rollback_is_reported`、
  `tests/test_config_write.py::TestFailureRecovery::test_failed_rollback_is_reported_truthfully`、
  `::test_rollback_failure_is_audited_even_without_the_readback_flag`），变异体 **4/4 精确变红**
  （`.heagent/tmp/mutate_a14_rollback.py`：吞掉回滚失败 / 不接住新异常 / 审计退回 `rolled_back` /
  审计退回「只在 `readback_failed` 时落痕」的漏记窗口）；`docs/frame.md` §4.18 的审计行与写通道行同步。
  **实现期的一处自我修正**：新 handler 起初照抄兄弟分支写了 `if state.readback_failed:`，覆盖率暴露出该 False
  分支永不执行（`RollbackFailedError` 只可能来自设过标志的 `_verify`）——与其留一条测不到的分支，改为
  **无条件落审计**并写明理由（「回滚失败」本身即足以构成留痕理由，漏记才是错），第 3 条判据钉住这一点。
  **③④ 仍未修**（冻结边界不变）。

- **结论**：**已闭合**（2026-09-27，四面各有处置）：
  ① **`.env.lock` 落在用户项目根** —— 按允许的「文档说明」修法落地（`docs/frame.md` §4.18 如实写明副作用；**锁的落点语义不改**——挪走会破坏「同一把锁贯穿读改写」）；
  ② **回滚失败时的文案不实** —— **已修**（commit `a1b9403`）：`persist` 新增 `RollbackFailedError`（`__cause__` = 原回读异常、`rollback_error` = 回滚失败原因），写通道据此给出如实文案并落 `rollback_failed` 审计；
  ③ **写锁内 I/O 时长** —— **已修**（commit `1959b9e`）：候选构造（`Settings` 读候选 / 全局 `.env` / 环境，整条流水线最贵的一步）与备份目录回收移到**锁外**；锁外用快照构造的候选在锁内复检内容基线，过期则在锁内重做（绝不把基于旧内容的候选写下去）；回收失败只告警（维护动作），不把已落盘的写改写成错误；
  ④ **无末行换行文件的追加约定** —— 维持「跟随文件属性」的保真语义，已在 §4.18 记入备查（非缺陷）。
- **冻结边界（守住）**：锁的落点语义不变；`ROLLBACK` 路径仍**不写文件**（文案与审计都不得宣称已回滚，除非真的还原成功）；写通道的 fail-closed 校验（键白名单 / 值守卫 / 候选构造 / 回读）一步未减。
- **证据**：`src/heagent/pub/persist.py`（`RollbackFailedError`）、`src/heagent/config/write.py`（`_prepare_candidate` / `_Prepared` / `_prune_backups_best_effort` / 锁内 `_update` 的基线复检）、`docs/frame.md` §4.18（写通道行：锁作用域；审计行：三个结果枚举）。
- **验证（2026-09-27 亲跑）**：② 判据 3 条 + 变异体 **4/4**（`.heagent/tmp/mutate_a14_rollback.py`）；③ 判据 4 条 + 变异体 **4/4**（`.heagent/tmp/mutate_a14_lock_scope.py`：候选构造搬回锁内 / 去掉锁内复检 / 回收搬回锁内 / 回收失败重新变成写失败）。全量 `pytest --cov` → **3116 passed / 11 skipped / 18 deselected**、覆盖率 **91.92%**（`config/write.py` 291 stmt / 0 missed）。

