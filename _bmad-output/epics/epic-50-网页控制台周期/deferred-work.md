# Epic 50 网页控制台周期遗留项台账（deferred-work）

> **归并来源**：`implementation-artifacts/deferred-work-archive.md` 的 **Z-D13 / Z-D14 / Z-D15**（Story 50-5 配置写入通道 ×2、Story 50-6 控制台 UI ×1）；2026-09-24 按「**条目闭合后按归属 epic 归档**」规则从活动台账的闭合归档区回填至本文件。
> **归档规则**：按条目**归属的 epic** 归档；「闭合者」注明实际完成它的批次 / commit。
> **只登记已闭合项**——原始长文历史不再保留，结论全部指向代码与测试。
> **活动（未闭合）遗留项**仍在 [`implementation-artifacts/deferred-work-archive.md`](../../implementation-artifacts/deferred-work-archive.md)（工作流 append-only 入口）——本周期相关未闭合条目 = 台账 **A8 跨项目并发无全局上限 / A9 运行时归因与兜底族 / A10 控制台端点阻塞 I/O / A11 非回环运行姿态 + cron 跨会话后置执行（`blocked` 待人裁决）/ A12 浏览器级 UI 验收不在 CI / A13 高影响键缺后端风险标记 / A14 写入通道与保真写的四类低危残余**，编号与正文以台账为准。

## 状态总览

| ID | 归属 | 条目 | 状态 | 闭合者 |
|----|------|------|------|--------|
| Z-D13 | Epic 50 · Story 50-5 | 写通道可把「资源旋钮」键设成无界值 | 已闭合（2026-09-24） | `config_catalog.RESOURCE_CEILINGS` 21 键上界（用户裁定「顺手闭合」） |
| Z-D14 | Epic 50 · Story 50-5 | 审计文件无保留期 / 条数上限 | 已闭合（2026-09-24） | `config_write.prune_audit` 行级裁剪至最近 500 条（同批） |
| Z-D15 | Epic 50 · Story 50-6 | 首页加载即弹出关不掉的确认遮罩（作者级 `display` 压过 `hidden` 属性） | 已闭合（2026-09-24） | `[hidden]{display:none!important}` 全局守卫 + `settleConfirm` 先隐藏再结算（用户实测发现） |

---

## Z-D13 写通道可把「资源旋钮」键设成无界值

- **来源**：Story 50-5 实现期实测（2026-09-24）发现；登记于活动区「Story 50-5 实现（网页控制台配置写入通道）」条目（该条目 2026-09-24 同日闭合）。
- **问题**：`MAX_ITERATIONS` / `GOAL_MAX_ITERATIONS` / `SUBAGENT_MAX_ITERATIONS` / `MAX_OUTPUT_TOKENS` / `MAX_CONTEXT_TOKENS` 在 `Settings` 里只有下界（`ge=1`），而 `VALUE_GUARDS` 只收了 5 个弱校验键 ⇒ 一旦开启写闸门（`HTTP_CONSOLE_WRITE_ENABLED=true`），白名单内的写入就能把它们设成 `10^9`：一次 run 的迭代 / 输出 / 上下文预算变成「不可完成」。这不是安全边界问题，是「本机资源旋钮」问题（闸门默认关、只写项目 `.env`、有备份与审计）。
- **结论**：**已闭合**（2026-09-24，用户裁定「顺手闭合」）。`VALUE_GUARDS` 补 5 个上界：`MAX_ITERATIONS` / `GOAL_MAX_ITERATIONS` / `SUBAGENT_MAX_ITERATIONS` = **10000**、`MAX_OUTPUT_TOKENS` = **1000000**、`MAX_CONTEXT_TOKENS` = **16000000**。口径 = 人类尺度理性上限（迭代类 ≈ 默认值 200–500 倍；上下文 ≈ 默认 512k 的 31 倍；输出无默认值、取最大真实模型输出窗口的约 8 倍），只挡手滑与恶意极值。**同日 follow-up 把同域残余一并闭合**（用户裁定「要处理」）：新增 `config_catalog.RESOURCE_CEILINGS` 作**单一事实源**（`VALUE_GUARDS` 由它合并），上界表从 5 键扩到 **21 键**，按族给刻度 —— `days` **3650**（10 年）/ `seconds` **604800**（7 天）/ `bytes` **8388608**（8 MiB）/ `tokens` **1000000** / `count` **100**；迭代预算 **10000** 与上下文窗口 **16000000** 量纲不同，自成刻度。
- **冻结边界（逐条守住）**：① **不改 `Settings` 字段定义**（不给任何字段加 `le=`）⇒ 既有配置文件的可加载性不变；② 守卫只作用于**写入通道**（`config_write.guard_reason`）与**面板展示**（`guards_for` → `ConfigItemResponse.guards` → 前端 `guardHint`）—— 手工改 `.env` 仍不受该上界约束（该形态由 50-6 的探针用例 `test_enum_guard_renders_a_select_with_the_allowed_values` 与验收清单 A11 钉住：面板取值提示完全由后端 `guards` 派生，前端不硬编码任何键名或边界）；③ 不把它表述为安全边界（沿用全项目立场）。
- **证据**：`src/heagent/config_catalog.py::RESOURCE_CEILINGS`（21 键 → `VALUE_GUARDS` 合并，与面板同一常量）；`tests/test_config_catalog.py::TestGuards` 三条 —— `test_every_ceiling_is_generous_and_actually_applied`（遍历常量表本体：上界真的进了 `guards_for` + 「≥ 默认值的 10 倍」）、`test_no_whitelisted_numeric_key_is_left_unbounded`（**完备性**：白名单数值键一个都不能漏）、`test_the_ceiling_table_is_exactly_the_agreed_one`（**口径固化**：逐条比对键与刻度 —— 规则挡不住「604800 悄悄改成 999999999」这种仍然 ≥10 倍、仍然完备的改动）；`::test_ceilings_do_not_change_what_settings_accepts`（`Settings(max_iterations=10_000_000)` 仍可构造 ⇒ 不改 `Settings` 语义）；`tests/test_config_write.py`（11 条越界参数用例 + `test_resource_ceilings_block_only_extremes` 双侧断言 + `test_a_retention_ceiling_applies_once_it_is_not_environment_provided`）；`tests/network/test_http_console_config.py::test_panel_shows_the_resource_knob_ceilings`（**遍历同一常量表**断言面板逐条展示，前端零改动）。负向验证：`.heagent/tmp/mutate_guards_audit.py` 6 条上界类变异体全部精确变红后复原 —— 整表清空（18 红）/ 全部改成 `1e15`（16 红）/ 少给一个键（3 红）/ 上界低于默认值（2 红）/ 单键形同虚设（2 红）/ 误给 `_DAYS` 键加 `minimum=1` 破坏「0 = 禁用回收」（1 红）。**实现期两条旁证**：① `Settings` 侧只有下界的落点 = `src/heagent/config.py:121/122/126/129/154/158/159`（`ge=1`、无上界）；Story 50-5 的 T9 参数化用例**删掉了**原计划的「`MAX_ITERATIONS=100000` 必须被拒」（实测无上界、断言本就不成立）。② 变异体 M1 首轮只红 4 条，查因发现新加的 4 个参数用例写的是 `1e9`，而 `int` 字段的候选构造**本来就会拒掉 `1e9`** ⇒「有上界」与「没上界」都通过，**用例不具区分性**；改成合法整数字面量 `1000000000` 后 5 条全部变红（教训已写进用例注释）。
- **发现并纠正的一处计数错误**：首轮盘点脚本按 `annotation` 判「数值型」，而 `int | None` 没有 `__name__` ⇒ 漏掉了 `MAX_OUTPUT_TOKENS` / `SKILL_MAX_AUTO_INVOKE_TOKENS` / `SKILL_MAX_MANUAL_LOAD_TOKENS` 三个键，于是本条目一度把残余记成「13 个」。改用守卫判据复核（`guards_for(key).kind == "range" and maximum is None`）得**真实为 16 个**（本条的 5 个 + 其余 16 = 21 键）。教训：盘点「某类键还有几个」时，判据要跟着**实际生效的那条路径**（守卫）走，不要跟着类型注解走；探针 `.heagent/tmp/ceiling_survey.py` 已改为守卫判据。
- **残余（同域）—— 2026-09-24 同日 follow-up 已闭合**：另外 16 个「只有下界」的键（磁盘保留期族 `*_RETENTION_DAYS`、字节预算族 `CONTEXT_FILES_MAX_BYTES` / `MEMORY_INJECT_MAX_BYTES`、秒级间隔与超时 `SHELL_TIMEOUT` / `CRON_TICK_SECONDS` / `PRUNE_MIN_INTERVAL_SECONDS`、技能条数与深度 `SKILL_MAX_AUTO_INVOKE` / `SUBAGENT_MAX_DEPTH`、`SKILL_*_TOKENS`、`SKILL_CURATOR_STALE_DAYS`）已由 `RESOURCE_CEILINGS` 按「同族同刻度 + ≥ 默认值 10 倍」补齐；**白名单数值键现在全部有上界**（`test_no_whitelisted_numeric_key_is_left_unbounded` 钉住完备性，`config_catalog.VALUE_GUARDS` 的 docstring 第 2 点已从「本表不是全部」改写为「完备性已闭合」）。这批键的两条**额外**理由：① 它们全都支持 `0`（= 禁用回收 / 不限制）⇒ 上界**不剥夺任何合法意图**（「永久保留」写 `0` 比写 `36500` 更明确）；② 测试环境里 7 个键被 `tests/conftest.py` 的 `os.environ.setdefault` 钉成 0 ⇒ 写通道会先按 F1 判 `field_not_writable`（对，但会掩盖守卫），故保留期族的端到端验证另有用例显式 `delenv` 后再测。

## Z-D14 审计文件无保留期 / 条数上限

- **来源**：Story 50-5 实现期实测（2026-09-24）发现；登记于活动区同名条目（2026-09-24 同日闭合）。
- **问题**：`<项目>/.heagent/console/audit.jsonl` 每次成功写入追加一行（约 300 B），只有 `append_audit` 的「失败不阻断已成功的写」语义、没有任何回收；对照之下备份目录有 `MAX_CONFIG_BACKUPS=50` + 30 天保留期。触发条件：回环客户端反复成功写入 × 长时间运行 ⇒ 审计资产反噬磁盘。
- **结论**：**已闭合**（2026-09-24，用户裁定「顺手闭合」）。新增 `config_write.prune_audit`：超 `MAX_CONFIG_AUDIT_ENTRIES=500` 行即整体重写（`persist.atomic_write_bytes`）只留**最近 500 条**、保留 LF 行尾；由 `append_audit` 在追加成功后调用（无跨进程节流，理由同备份目录：一次 scandir / 一次读的代价远小于节流标记的维护成本）。
- **修正了台账原拟修法的形状**：原条目写的是「按 `.jsonl` 后缀 + 条数上限」的**文件级**回收（与 `prune_backups` 同款内核）—— 但审计是**一个持续追加的文件**：目录里永远只有 1 个 `.jsonl`，那套内核的候选集合恒为空（照做等于没做，会「闭合」在纸面上）。实际做在**行**级。
- **冻结边界（守得更紧）**：不做 glob、不做后缀扫描，只认 `console_dir / AUDIT_FILENAME` 这一个已知文件名 ⇒ 同目录的项目注册表 `projects.json` 连候选都进不去（该目录在内部状态读拒集合内，误删不会有读取报错兜底）。`max_entries=0` 的语义与 `prune_backups` 对齐（保留 0 条）。
- **失败立场**：裁剪是**维护动作** —— 任何异常只 WARNING，绝不让「已追加成功且写已生效」的响应变成错误（否则文件已改而响应 500，用户重试又撞 `config_conflict`）；调用点包 catch-all。
- **证据**：`src/heagent/config_write.py::prune_audit` / `append_audit` / `MAX_CONFIG_AUDIT_ENTRIES`；`tests/test_config_write.py::TestAuditRetention`（11 例：只留最近 N 条 / 未超限则字节不变 / 文件缺失不报错 / 读失败与写失败各自降级为 0 / 裁剪后仍是 LF + JSONL / 末行无换行也算一条 / **同目录注册表不被触碰** / 裁剪失败不改写 `audit_recorded` / 端到端追加即触发裁剪 / 写通道自身路径亦受上限约束）。负向验证：`.heagent/tmp/mutate_guards_audit.py` M3–M7（回收缺席 / 边界错位 / 方向错 / 越界删邻居 / 失败外传）→ 6 / 6 / 5 / 1 / 1 条精确变红后复原。

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
