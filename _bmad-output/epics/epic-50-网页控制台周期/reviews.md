---
epic: E50（网页控制台）
scope: Epic 50 全周期评审与验收 —— 规划评审 → 实现增量 → 全量收口 → Story 50-8 → 第四轮；Story 50-6 / 50-7 / 50-8 验收（原 `reviews/` 目录 8 份文档单文件合并）
reviewer: code_review 契约（三镜头 + 定级 + 分诊）· 规划期三镜头对抗评审 · 真实浏览器验收（CDP）
merged_from: reviews/（8 份）
merged_at: '2026-09-26'
verdict: 见各章；Epic 50 全量 8 条 story 放行
---

# Epic 50 · 评审与验收合集

> **本文件 = `reviews/` 目录 8 份文档的单文件合并（2026-09-26）**，按时间/轮次排列。
> **保真口径**：正文**逐字保留**，只做两处机械处理——① 每份文档的标题层级整体下移一级（`#`→`##`；代码围栏内的 `#` 行原样未动）；
> ② 正文中指向**同目录旧文件**的 Markdown 链接改指本文件锚点（全文仅 2 处，见下方各章）。
> 各文档原有 frontmatter 以代码块逐字保留在所属章节开头；正文中作为**记录**提及的旧文件名（如 `prior_rounds:`）保持原样，
> 锚点规则 = 旧文件名去掉 `.md`（如旧路径 `reviews/review-epic-50-closure.md` → 本文件 `#review-epic-50-closure`）。
>
> 章节锚点：`#review-planning-adversarial` · `#review-epic-50-implementation` · `#review-epic-50-closure` · `#review-epic-50-story-50-8` · `#review-epic-50-round4` · `#acceptance-50-6-console-ui` · `#acceptance-50-7-epic-acceptance` · `#acceptance-50-8-refinement`

## 索引

| 章节（原文件） | 轮次 / 类型 | 日期 | 规模 | 结论 |
|---|---|---|---|---|
| [`review-planning-adversarial.md`](#review-planning-adversarial) | 规划评审（计划期 · review_loop_iteration 1） | 2026-09-24 | 170 行 / 12409 字节 | 放行（阻塞项已关闭）：F1/F2/F3/F5/F6/F10/F11 已就地修复，F4 裁决为「并发随项目数线性增长」，F7/F8/F9 记入 story，F12 reject |
| [`review-epic-50-implementation.md`](#review-epic-50-implementation) | 第一轮 · 实现增量评审（Story 50-1…50-4） | 2026-09-24 | 133 行 / 16096 字节 | 有条件放行（Epic 收口不放行：还差 50-5/50-6/50-7 与 1 条待裁决 intent_gap） |
| [`review-epic-50-closure.md`](#review-epic-50-closure) | 第二轮 · 全量收口评审（Story 50-1…50-7） | 2026-09-24 | 149 行 / 20009 字节 | 放行（Epic 50 收口通过；3 条 low 级 deferred 与 2 条 blocked 待人裁决不阻塞收口） |
| [`review-epic-50-story-50-8.md`](#review-epic-50-story-50-8) | 第三轮 · Story 50-8 收口后评审（含续轮） | 2026-09-26 | 181 行 / 25440 字节 | 放行（Story 50-8 与 Epic 50 全量；4 处判据/口径已就地修复并带负向验证） |
| [`review-epic-50-round4.md`](#review-epic-50-round4) | 第四轮 · HEAD 独立复核 + 新面深挖 | 2026-09-26 | 161 行 / 25074 字节 | 放行（Epic 50 全量 8 条 story；1 medium + 1 low 已就地修复；新增 3 deferred + 2 blocked 待裁决） |
| [`acceptance-50-6-console-ui.md`](#acceptance-50-6-console-ui) | 验收 · Story 50-6（真实浏览器 CDP） | 2026-09-24（补记 09-24） | 98 行 / 9753 字节 | 首次交付 17 / 17 PASS；收口后补记 A1b（首页无阻塞遮罩）后 18 / 18 PASS |
| [`acceptance-50-7-epic-acceptance.md`](#acceptance-50-7-epic-acceptance) | 验收 · Story 50-7（brief §9 逐条） | 2026-09-24 | 68 行 / 9731 字节 | §9 的 9 条全部有可复现命令与实测输出；全量质量门与真实浏览器验收同时通过 |
| [`acceptance-50-8-refinement.md`](#acceptance-50-8-refinement) | 验收 · Story 50-8（真实浏览器 + 负向验证） | 2026-09-24（第四轮复跑 09-25） | 187 行 / 18278 字节 | 23 / 23 PASS（18 → 22 → 23 行，A11b/A11d 判据经用户裁决重写） |

---

*以下 5 份为评审报告（计划期 + 四轮）：*

<a id="review-planning-adversarial"></a>

## Epic 50 规划评审报告（三镜头）

> **原文件**：`reviews/review-planning-adversarial.md` ｜ **轮次 / 类型**：规划评审（计划期 · review_loop_iteration 1） ｜ **日期**：2026-09-24

**原 frontmatter（逐字保留）**

```yaml
scope: Epic 50 网页控制台周期 · 规划产物（brief / epics / ARCHITECTURE-SPINE / 7 份 story）
review_type: adversarial-planning-review
review_loop_iteration: 1
date: 2026-09-24
reviewer_stance: 对抗式（不采信产物自述，结论只来自亲自读过的文件与亲自跑过的命令）
```


### 评审范围

| 项 | 内容 |
|---|---|
| 评审对象 | `brief.md`(131 行)、`epics.md`(449 行)、`ARCHITECTURE-SPINE.md`(约 410 行)、`stories/50-1..50-7`（7 份） |
| 代码基线 | 工作区 `HEAD`（未跟踪的 epic-50 目录 + `M _bmad-output/sprint-status.yaml`） |
| 涉及代码面 | `config.py`、`network/http_server.py`、`network/http_protocol.py`、`network/exposure.py`、`cli.py`、`cli_http.py`、`agent/loop.py`、`agent/run_lifecycle.py`、`cron/scheduler.py`、`engine/container.py`、`engine/policy.py`、`tools/path_safety.py`、`context/session.py`、`persist.py` |

**实际执行过的命令与结果**（评审证据，非自述）：

| 命令 / 探针 | 结果 |
|---|---|
| `epic50_probe8.py` | 白名单 46 键全部存在；**110 = 46 白名单 + 64 排除，残留 0** |
| `epic50_review_probe.py` | §5.3 码数 = 18（17 + `session_unreadable`）✓；**候选非法值在系统 env 存在时不报错**；非法 JSON `ROUTING_POOLS` 不被构造拒绝；`LOG_LEVEL=BANANA` 不被构造拒绝 |
| `epic50_review_probe2.py` | **带 BOM 的 `.env`：来源层键为 `'\ufeffmax_iterations'`，生效值退化为默认（123 → 50），无告警** |
| `git grep "os.getcwd()" src/heagent` | 8 处装配点，与 50-1 的清单一致 |
| `pytest tests/test_artifact_contracts.py tests/test_config.py tests/test_architecture_contracts.py -q` | **124 passed**（修复后复跑） |
| `epic50_selfcheck.py` | PASS（7/7；修复后 **77 任务 / 67 AC**） |

### 镜头一：对抗式（12 条）

#### F1 — 写流水线缺「系统环境变量覆盖 ⇒ 不可写」检查　**high**　`bad_spec` → 已就地修复

- **位置**：`ARCHITECTURE-SPINE.md` §8 流水线第 3 步（原） / `50-5` AC4 邻域
- **证据**：探针实测——候选文件含 `MAX_ITERATIONS=abc` 且系统 env 提供 `MAX_ITERATIONS=5` 时，
  `Settings(_env_file=候选)` **不抛异常**（env 优先级更高，候选值根本没被解析）。
  而 §8 原第 3 步只查「在白名单内」，**没有任何一步**检查「该键是否被系统 env 提供」；
  50-4 只在**读**侧标 `writable=false`。⇒ 写通道会接受一个「面板显示只读」的键，
  写进去的是**当下无效、日后生效**的坏值（用户哪天 unset 该 env，进程起不来）。
- **处置**：§8 第 3 步改为「必须在显式白名单内**且不得被系统环境变量提供**（与 50-4 的 `writable=false`
  同一求解器、同一常量，不得只在 UI 层拦）」；新增 `50-5` **AC12** 与 T9 测试项。

#### F2 — 传 `session` 会顺带在 HTTP 进程内构造 `CronScheduler`　**medium**　`patch` → 已就地修复

- **位置**：`cli.py:229`（`if session is not None and config.cron_enabled and cron_store:`）→ `cli.py:246`（构造 <code>CronScheduler</code>）
- **证据**：今日 HTTP 侧「无后台调度」**是因为 `session=None` 才偶然成立**（`cli_http.py:207-214`）；
  50-3 T6 要求把 `SessionStore` 传进 `_build_loop` ⇒ 每次 `new_loop()` 都会构造一个 `CronScheduler`
  （`new_loop` 丢弃返回值，`__init__` 无副作用，但**没有任何守卫或测试**保证它不被启动）。
  与 49-5 已确立的「不装 stdin 审批、不连 MCP」立场同源，却缺少对应条款。
- **处置**：50-3 T6 增硬要求 + 测试断言；Never 列表新增「不在 HTTP 进程内构造/启动后台执行」。

#### F3 — `WorkspacePaths.projects_file` 作用域错配（项目级类型承载服务级路径）　**medium**　`patch` → 已就地修复

- **位置**：`ARCHITECTURE-SPINE.md` §3.1（`projects_file = console_dir/"projects.json"`）vs §4（「落点 = `<服务启动工作区>/.heagent/console/projects.json`」）；`50-1` T1 把 `projects_file` 列入 `WorkspacePaths`
- **证据**：`WorkspacePaths` 是**项目级**的；对已登记项目 `P`，`WorkspacePaths(P.root).projects_file`
  ⇒ `P/.heagent/console/projects.json`，即**每个项目一个注册表**。任何按「项目 → WorkspacePaths → 注册表」
  的写法都会读到空注册表或写出分叉数据。
- **处置**：§3.1 新增「作用域警告」：注册表路径**只能**由控制台从启动工作区 + 覆盖解析一次，
  禁止从任意项目的 `WorkspacePaths` 取，须配测试。

#### F4 — 跨项目并发被「顺带」放开，与 brief §5 冲突　**medium**　`intent_gap` → **blocked，交人裁决**

- **位置**：§6（每项目一个 `HttpRunService`，持有「在途名额」）vs `brief` §5（「扩大跨项目并发运行能力」不在本周期）
- **证据**：`max_inflight_runs` 是 **service 级**（`network/http_server.py:150`、`:386` 用 `self.config`），
  每项目一个 service ⇒ 总并发 = 项目数 × 1；即「A 在跑时 B 也能起跑」。brief 明写「沿用既有运行限额，
  多项目切换不等于并行运行」。
**已裁决（2026-09-24，选 **b**）→ 关闭**：采纳「并发随项目数线性增长」。
处置：`intent_gap` → **已转 D9 并落地**（脊柱 §6 新增「并发口径」、§12 改写、§15 决策登记表新增 D9 行；
`brief` §5 该行作废并标注；`epics.md` Additional Requirements 增并发语义条目；50-2 T4 / 50-3 T9 / 50-7 T10⑨ 同步）。
已知缺口如实登记：无全局并发软上限、`HTTP_MAX_CONNECTIONS` 不随项目数放大。

#### F5 — 失败/取消的 run 也写会话文件，与 49-3「失败不投影」形成双口径　**medium**　`patch` → 已就地修复

- **位置**：`agent/run_lifecycle.py:324-350`（`persist_and_cache` 在 finally 里 `if loop.session and session_id: save(...)`）
- **证据**：进程内投影只在 `COMPLETED` 时写历史（49-3 AD-3「失败不投影」），而文件侧**成功/失败/取消都落盘**
  ⇒ 同一段对话在 `/api/session` 与会话文件里给出**两个答案**，UI 若各取一半就会自相矛盾。
- **处置**：50-3 新增 **T9b** + **AC10**（必须显式定义失败/取消是否算对话的一部分，且同一页面只用一种口径）。

#### F6 — BOM 的 `.env` 让首个键静默失效（读 + 写两侧）　**medium**　`patch` → 已就地修复

- **位置**：50-4 读路径 / 50-5 `envfile.parse_index`
- **证据**：探针实测——带 BOM 的 `.env` 经 `DotEnvSettingsSource` 返回键 `'\ufeffmax_iterations'`，
  `Settings` 因而回落到默认值（文件写 123 → 实际 50），**无任何告警**；写侧若按行取键名，
  首键会定位不到 ⇒ 追加一条重复行（死行）。这与 2026-09-23 刚修过的 frontmatter / MEMORY.md **BOM 缺陷族同源**。
- **处置**：50-4 增 **T9b** + **AC12**；50-5 T1 增 BOM 剥离要求 + **AC11**（首行须替换而非追加，BOM 保留）。

#### F7 — 全局 `run_id → project` 索引无上限与回收　**low**　`patch`（记入 story）

- **位置**：§5.1 / 50-3 T9；NFR-11 要求「有界」
- **处置**：记入 50-3 **R4**，要求定义淘汰口径（与既有 run 保留期同源）并配测试。

#### F8 — 运行落盘是否传 `expected_version` 未定义　**low-medium**　`patch`（记入 story）

- **位置**：50-3 T1（`save(..., expected_version=None)` 默认 = 现状）
- **证据**：若仅 PATCH/DELETE 传期望版本、**运行落盘不传**，则同一会话的两个并发 run 交替写仍可能
  互相覆盖内容（文件不损坏，但**丢消息**）。
- **处置**：记入 50-3 **R5**，要求明确并覆盖「两写者交替」测试。

#### F9 — 「回环来源」不防用户自己浏览器里的跨站写入　**low**　`patch`（记入文档义务）

- **位置**：§9 / 50-5 T4（用 `is_loopback_host(request.client.host)`）
- **证据**：用户浏览器访问的任意网页，其到 `127.0.0.1:8766` 的 peer 也是 `127.0.0.1` ⇒ 回环门**不构成防护**；
  真正的防线是 49-5 的 Origin/Host 校验。
- **处置**：记入 50-7 T10 ⑧（已知缺口声明），避免「回环 = 可信」错觉。

#### F10 — 注册表无长度上限（NFR-11）　**low**　`patch` → 已就地修复

- **位置**：50-2 T4（原只写条目数上限）
- **处置**：T4 增显示名（≤64）与路径（≤4096）显式校验。

#### F11 — 项目移除无服务端确认（与会话删除不对称）　**low**　`patch` → 已就地修复

- **位置**：§5.2 `DELETE /api/projects/{id}` / 50-2 AC6 vs 50-3 会话删除要求 `?confirm=true`
- **处置**：§5.2 与 50-2 AC6 统一为「缺 `?confirm=true` → `confirm_required`」（危险操作的确认放服务端，不只靠 UI）。

#### F12 — 18 个新错误码无「全部可达」断言　**low**　`reject`

- 判断：各码由对应 story 的 AC 分别覆盖；「可达性总表」属噪声，非可执行主张。

### 镜头二：边界追踪（7 条）

| # | 边界 | 结论 | 严重度 | 处置 |
|---|---|---|---|---|
| E1 | `.env` 为**空文件** | 来源层返回 0 键 → 全字段落 `default` ✓（AC7 覆盖「不存在/不可读」） | — | reject |
| E2 | `.env` 是**目录** | `is_file()` 探测可挡住（50-4 T3）✓ | low | defer（DoD 未单列，实现时顺手断言） |
| E3 | `.env` **只读**（ACL/permission） | 写入会失败 → 50-5 AC8「回读失败自动恢复」覆盖；但**权限位继承**未验证 | low | 已记录于 50-5 R2 |
| E4 | 重复键 / 行内注释 / 无末行换行 / CRLF | §7 坑 5/6 + 50-5 T10 四变体保真断言 ✓ | — | reject |
| E5 | 会话 JSON 缺 `messages` | `data.get("messages", [])` ✓（`context/session.py:137`） | — | reject |
| E6 | 会话文件损坏 | D1 已裁定 `session_unreadable` + AC9 ✓ | — | reject |
| E7 | **超长输入**（项目路径 / 显示名 / session id） | session id 有既有守卫 ✓；项目路径与显示名原**无上限** | low | patch（= F10） |

### 镜头三：验证缺口（6 条）

| # | 缺口 | 严重度 | 处置 |
|---|---|---|---|
| V1 | **50-4 AC11（返回守卫约束）无对应任务**，且 `ConfigItem` 字段表没有承载字段 ⇒ AC 不可实现 | medium | patch → T1 增 `guards` 字段（已就地修复） |
| V2 | 50-2 AC6 的 `project_busy` 需 50-3 的索引（**story 前向依赖**，BMAD step-03 明令禁止） | low | reject（已记录于 50-2 R2，端到端断言归 50-3/50-7） |
| V3 | 「BOM 读路径」无测试 | medium | patch（= F6） |
| V4 | 「系统 env 覆盖的键被写」无测试 | medium | patch（= F1） |
| V5 | 手工浏览器验收无 CI 覆盖 | low | reject（50-6 R2 / 50-7 T10④ 已如实登记） |
| V6 | `.env` 权限位继承未验证 | low | defer（50-5 R2 已登记为待核实） |

### 处置汇总

| 严重度 | 计数 |
|---|---|
| high | 1（F1） |
| medium | 5（F2、F3、F4、F5、F6）+ 镜头三 3 条（V1、V3、V4——与 F6/F1 同源） |
| low | 6（F7–F11、E7）+ 镜头二/三的低危项 |

| 处置 | 计数 | 明细 |
|---|---|---|
| `bad_spec` → 已就地最小修复 | 1 | F1 |
| `patch` → 已就地修复 | 8 | F2、F3、F5、F6、F10、F11、V1（+F6 双落点） |
| `patch` → 记入 story「风险与未决」 | 2 | F7、F8 |
| `patch` → 记入文档义务 | 1 | F9 |
| `intent_gap` → **已裁决并落地（D9）** | 1 | F4（跨项目并发＝b：随项目数线性增长） |
| `reject` | 4 | F12、V2、V5、E1/E4/E5/E6（同类合并） |
| `defer` | 2 | E2、E3/V6 |

**删除检查**：本次评审未删除任何既有条款；`50-4` T10（负向验证）在一次编辑中被误替换后已**复原并扩充**
（新增「去掉 BOM 剥离」一项）。

### 结论

**放行（阻塞项已关闭）**：唯一阻塞 F4（跨项目并发语义）已于 2026-09-24 裁决为 **(b) 并发随项目数线性增长**，
并已转为 **D9** 落地（脊柱 §6/§12/§15、brief §5、epics.md、50-2 T4、50-3 T9、50-7 T10⑨）。
其余发现已在本次评审内就地修复或登记到对应 story 的「风险与未决」。

可进入 50-1 实现。`review_loop_iteration = 1`（未超回环上限 5）。

---

<a id="review-epic-50-implementation"></a>

## Epic 50 实现增量 · 收口评审报告

> **原文件**：`reviews/review-epic-50-implementation.md` ｜ **轮次 / 类型**：第一轮 · 实现增量评审（Story 50-1…50-4） ｜ **日期**：2026-09-24

**原 frontmatter（逐字保留）**

```yaml
epic: E50（网页控制台）
scope: Epic 50 全部增量（Story 50-1 / 50-2 / 50-3 / 50-4）
diff_range: 33adba0..3ff9d8d（评审时 HEAD；修复后另起提交）
review_loop_iteration: 0
reviewer: code_review 契约（三镜头 + 定级 + 分诊）
verdict: 有条件放行（Epic 收口**不放行**：还差 50-5/50-6/50-7 与 1 条待裁决 intent_gap）
created: '2026-09-24'
```


按 `code_review` 契约执行：**对抗式 / 边界追踪 / 验证缺口** 三镜头各自独立成段；定级前逐条打开源码读调用点
与守卫；Critical（high）就地最小修复并重跑受影响测试 + 负向验证。

### 评审范围

- **Epic**：`_bmad-output/epics/epic-50-网页控制台周期/`（脊柱 + 7 份 story）。
- **覆盖的 story**：50-1（工作区一等化）、50-2（项目注册表 API）、50-3（会话持久化 / 会话 API / 项目内运行）、
  50-4（配置来源求解与只读配置 API）。50-5/50-6/50-7 尚未实现，不在本次代码面内。
- **diff 范围**：`git diff 33adba0..HEAD` —— 47 文件 / +6235 −217。其中 src 约 3.9k 行、tests 约 2.3k 行。
- **改动文件（评审对象）**：`workspace.py`、`projects.py`、`context/session.py`、`network/http_protocol.py`、
  `network/http_console_protocol.py`、`network/http_server.py`、`cli_http.py`、`cli.py`、`config_catalog.py`、
  `tools/path_safety.py`、`housekeeping.py`、`engine/container.py`、`agent/loop.py`（cron 绑定）、
  `agent/run_lifecycle.py`（失败落盘）；测试面 9 个文件。
- **三镜头并行执行**：两个隔离子代理负责「对抗式」「验证缺口」的广度扫描，边界镜头首轮超迭代上限后**收窄重跑**；
  三条发现的**定级与处置由我逐条打开被引用的源码/配置后给出**（下表凡标「已核」者均为亲读）。

#### 我实际执行过的命令与结果

| 命令 | 结果 |
|---|---|
| `python -m pytest -q` | 评审开始时 **2735 passed / 10 skipped**；本轮全部修复与证据补齐后 **2747 passed / 10 skipped** |
| `python -m pytest -q --cov` | 评审开始时 TOTAL **91.33%**；收口时 **91.44%**（门限 87%） |
| `python -m ruff check src tests` | All checks passed（两轮） |
| `python -m ruff format --check src tests` | 272 files already formatted |
| `python -m mypy src` / `python -m mypy --platform linux src` | 均 `Success: no issues found in 144 source files` |
| `python .heagent/tmp/mutate_50_review.py` | **7/7** 变异体精确变红（本轮全部修复与新增证据的可执行判据） |

---

### 镜头一 · 对抗式（找「缺什么」）

| # | 位置 | 问题 | 证据（亲读） | 严重度 | 处置 |
|---|---|---|---|---|---|
| 1 | `context/session.py:224` | 畸形消息条目让**整页会话列表 500**，与自身 docstring 的 fail-soft 承诺矛盾 | `title = derive_title([Message(**item) for item in message_list if isinstance(item, dict)])`，而 `list_metadata` 只 `except SessionUnreadableError`（`:404`）⇒ pydantic `ValidationError` 穿透 | **high** | **patch 已修**（A 变异体） |
| 2 | `projects.py:213-226` + `:137/:164/:184/:203` | 注册表解析失败 ⇒ 空表被回写 ⇒ **一次坏字节清空全部已登记项目**（只留一行 WARNING） | `_decode` 解析失败 `return []`，而 4 条写路径都 `entries = self._decode(raw)` → `_encode(entries)` 写回 | **high** | **patch 已修**（B 变异体；同时改写了把该行为钉成预期的既有用例） |
| 3 | `network/http_server.py:1320` vs `:1332/:1400/:1420/:1433/:1447` | 回环闸门只装在登记/移除，危害更大的「起 run」与会话增删改无闸门 | `register_project` 有 `_loopback_error`，其余写路由没有 | medium | **defer**（49 的 `/api/runs` 本无闸门 ⇒ 暴露面未扩大；已登记台账） |
| 4 | `network/http_server.py:659/665/690/710` | `deadline_reason` 一经写入永久保留 ⇒ 用户的 `DELETE` 可能被误报 `timed_out` 并吞掉取消；`reopen()` 可让旧任务上报 `timed_out` | 看门狗先写 `deadline_reason` 再 `cancel()`；`_execute` 只判「非 None 且未关停」 | medium | **defer**（与镜头二②同族；已登记台账） |
| 5 | `network/http_server.py:659` | `tools_in_flight` 永不衰减 ⇒ 一个**永不返回**的工具让静默判据恒不成立，名额被无界占用 | 计数只由 `tool_call`/`tool_result` 增减；`http_request_timeout` 默认 0 | medium | **defer**（需「在途工具计龄」策略；已登记台账） |
| 6 | `cli.py:226/:275` + `agent/loop.py:686` | `enable_cron=False` 只拒调度器，**cron 工具面仍绑定** ⇒ 网页运行可写 `jobs.json`，任务在后续 CLI 会话无人监督执行 | `cron_store = JobStore(...) if config.cron_enabled else None` 仍进 loop；`cli_http.new_loop` 的 `scheduler is not None → raise` 对 `enable_cron=False` 恒不可达 | medium | **intent_gap → blocked**（两条互斥修法都要改可观察行为，交人裁决；已登记台账） |
| 7 | `cli_http.py:595` vs `new_loop`/`for_workspace` | 配置面板按**项目** `.env` 报来源与取值，而运行端读的是**服务器 cwd** 的 `.env` ⇒ 同一键两个口径 | 面板显式 `build_config_report(root/".env")`；运行端共享 `self.settings`（`env_file=[global, ".env"]` 按进程 cwd 解析） | **high** | **bad_spec 已修**（脊柱 §7 明确要求「项目运行时必须显式传 `_env_file`」；C 变异体） |
| 8 | `cli_http.py:499/595/600/651` | 唯一事件循环里做同步 I/O（会话列表 / 配置求解 / `registry.list()` / 加锁重写） | 均为 `async def` 体内的阻塞调用 | medium | **defer**（已登记台账） |
| 9 | `context/session.py:388/401` | >1 MiB 会话仍整份读入（只跳过了「数消息」） | `read_text` 无视 `info.st_size` | low | **defer**（已登记台账） |
| 10 | `cli_http.py:505-508`、`:571-583` | ① `create()` 的 `SessionConflictError`（非 `ValueError` 子类）漏捕 ⇒ 500；② 名额冲突前已落一个空会话文件 | `except ValueError` 一处；`_resolve_session` 先 `create()` 再 `start_run()` | low | ① **patch 已修**；② **defer**（失败请求留下空会话，登记台账） |
| 11 | `tools/path_safety.py:310` vs `:318` | 新增 `root` 形参只参与相对解析，deny 集仍取全局 `workspace_root()` ⇒ 接缝级绕过 | `build_internal_state_dirs() \| build_internal_state_dirs(workspace_root())` | low | **defer**（当前调用方同根；已登记台账） |
| 12 | `docs/frame.md:1014` | 文档写 `HttpErrorCode` 封闭 **22** 码，实测 **27** | `len(list(HttpErrorCode)) == 27` | low | **patch 已修**（文档） |
| 13 | `.env.example:339` | `HTTP_MAX_INFLIGHT_RUNS` 已是**每项目**口径，文档仍写「全局上限」 | `_inflight_in_scope(project_id)` | low | **patch 已修**（文档） |
| 14 | `config_catalog.py:329` | 「控制台自身」排除规则声明了两个**尚不存在**的 `Settings` 键 | 全仓引用核对：只出现在常量表与测试里 | low | **reject**（有意为之：常量先就位，50-5 新增该两键后即生效，见 50-4 的 T6 边界说明） |

### 镜头二 · 边界追踪（真实调用链）

| # | 位置 | 边界输入 → 行为 | 证据 | 严重度 | 处置 |
|---|---|---|---|---|---|
| ① | `http_server.py:1238` vs `:780` | N 个并发 `GET /api/runs/{id}/events` → 限额「先查后加」可被穿过（不崩、不泄漏，但每订阅者驻留 512 事件队列） | 检查在端点，登记在生成器首个 `__anext__` | medium | **defer**（已登记台账） |
| ② | `http_server.py:607/690/710` | 关停与看门狗同 tick 到达 → 归因偏向 `cancelled`（终态唯一、名额正确，仅「为什么结束」由谁先跑决定） | `self._closing = True` 先置位 | low | **defer**（与镜头一④同族） |
| ③ | `config_catalog.py:783` + `:926` | 项目 `.env` 值非法 ⇒ 整层被摘 ⇒ **文件里的未知键也一起消失**（AC5 的诊断恰在最需要它时丢失） | 实测：`notes=('project_env_invalid',) unknown_keys=()` | medium | **patch 已修**（改依据行级扫描 + 非 UTF-8 门；D 变异体） |
| ④ | `config_catalog.py:786` | 四层候选全败 → 抛 `ValidationError` → 不透明 500 无稳定码 | 仅在**系统环境变量**非法时可达（进程级配置错误） | low | **defer**（有意抛：此时运行期 `Settings()` 同样失败） |
| ⑤ | `config_catalog.py:611-634` | 0 字节 `.env` → `line_count=1`（按 `split("\n")` 段数计） | 实测 | low | **patch 已修**（改 `splitlines()` + 0 字节用例） |
| 已核无问题 | — | 同一项目第二个 run / 跨项目并发（`http_server.py:458` 按项目计名额）；DELETE 幂等且 `wait(timeout)` 有界（`:563`）；断线在 `finally` 释放（`:805`）；关停由 `_finalize` 兜底（`:530`）；一万行 / 5000 未知键 / 全重复键均线性且有界（`MAX_UNKNOWN_KEYS` 与协议 `max_length` 同源） | 附行号 | — | — |

### 镜头三 · 验证缺口（对照 AC 与测试）

| # | AC / 声称 | 实际证据 | 严重度 | 处置 |
|---|---|---|---|---|
| ① | 50-3 AC10「失败/取消的 run 也写会话文件」 | 唯一相关用例用替身 handler「先 `save` 再 `raise`」= **循环论证**；`persist_and_cache` 所在的 `finally`（`run_lifecycle.py:278`）零覆盖 | high→medium（实现正确、证据缺失） | **patch 已补证据**：新增真实 `AgentLoop` + 真实 `SessionStore` 的失败落盘用例（F 变异体证明有牙） |
| ② | 50-2 AC9「上限后返回 `project_limit_reached`」 | 网络层项目用例**全用假 console**，真实 `HttpProjectConsole` 的注册表方法无 HTTP 级证据 | medium | **patch 已补证据**：真实 console + 31 条登记 + HTTP POST → 409 |
| ③ | 脊柱 I1「网络层不得 import config/projects」 | `FORBIDDEN_RUNTIME_IMPORTS["network"]` 只列**子包** ⇒ 顶层模块写法可绕过（契约形同虚设） | medium | **patch 已修**：加 `heagent.config/config_catalog/projects/workspace` + 顶层模块名识别器 + 识别器单元测试（E 变异体） |
| ④ | 50-3 AC4「PATCH 持旧 fingerprint ⇒ 409 且不覆盖」 | 只有「假 console 直接抛码」用例；真实 `fingerprint → expected_version → 409` 链路零证据 | medium | **patch 已补证据**（H 变异体证明有牙） |
| ⑤ | 50-3 AC2/AC3「工具调用配对」「第二次运行写回同一文件」 | HTTP 端到端只跑无工具调用的 prompt；「写回同一文件」无断言 | medium | **defer**（需要 tool-calling 替身走 HTTP；登记台账） |
| ⑥ | 50-2 Dev Record「110 passed, 1 skipped」 | 同一命令在当前树实测 **294 passed**；按用例增量反推该命令在 `7ef2c92` 时 ≥238 ⇒ 该数字不可复现 | medium | **defer**（文档准确性；原因见下） |
| ⑦ | 50-2 T7「新增码同步文档」 | `docs/frame.md:1014` 写 22 码、实测 27（与镜头一⑫同处） | low | **patch 已修**（文档） |
| ⑧ | 脊柱 §8「110 = 46 + 64」；§3.1 `config_backups` 路径 | 实测 111 = 46 + 65（残留 0）；代码是 `state_dir/"backups"`（无 `/env`） | low | **patch 已修**（脊柱就地校正 + §14 补 C9/C10 校正行，遵守其「要改先改本文件」规则） |

> ⑥ 的补充说明：该数字出自 50-2 当时的环境，我无法在不 `checkout` 历史提交（评审纪律禁止写操作）的前提下复现，
> 故只登记「不可复现 + 反推下界」，不擅自改写他人 story 的验证记录。

---

### 就地修复清单（最小修复，逐条带负向验证）

| 文件 | 修复 | 回归用例 | 变异体 |
|---|---|---|---|
| `context/session.py` | 消息项不合法 ⇒ `SessionUnreadableError`（与「JSON 坏了」同档），列表 fail-soft、详情回稳定码 | `test_list_metadata_treats_invalid_message_entry_as_unreadable` 等 2 例 | A（RED） |
| `projects.py` | 读写分工：读 fail-soft（不变）、写 **fail-closed**（解析不了就拒绝改写，`server_error`） | `test_corrupt_registry_is_read_fail_soft_but_never_overwritten` 等 2 例 | B（RED，4 处一起回退） |
| `cli_http.py` | 派生 runtime 按**项目** `.env` 解析 settings（脊柱 §7），坏文件回退 + WARNING | `test_for_workspace_resolves_settings_from_the_project_env` 等 2 例 | C（RED） |
| `cli_http.py` | `create_session` 补捕 `SessionConflictError` → `session_conflict` | 覆盖于会话路由用例集 | — |
| `config_catalog.py` | 未知键改依据行级扫描（+ 非 UTF-8 门）；`line_count` 改 `splitlines()` | `test_unknown_keys_survive_layer_degradation` 等 3 例 | D（RED） |
| `network/http_server.py` | `_CONSOLE_ERROR_STATUS` 补 `SERVER_ERROR: 500`（服务端状态类失败不再落到默认 400） | 见 B 的 HTTP 通道 | — |
| `tests/test_architecture_contracts.py` | I1 契约覆盖顶层模块 + 识别器单元测试 | `test_forbidden_import_detection_covers_top_level_modules` | E（RED） |
| `tests/test_agent_loop.py` | AC10 真实链路证据 | `test_failed_run_still_persists_the_history` | F（RED） |
| `tests/network/test_http_console_sessions.py` | AC4 真实指纹冲突证据 | `test_stale_fingerprint_conflicts_through_the_real_store` | H（RED） |
| `tests/network/test_http_console_projects.py` | AC9 真实上限证据 | `test_project_limit_is_reported_with_a_stable_code_over_http` | — |
| `docs/frame.md` / `.env.example` / 脊柱 / 台账 | 数字与语义校正（22→27 码、每项目上限、111/65、备份落点、C9/C10、3 条 deferred） | —（纯文档） | — |

**删除检查**：本次改动未删除任何既有守卫或契约；改动的既有测试只有一条
（`test_corrupt_registry_warns_and_recovers_empty` → `test_corrupt_registry_is_read_fail_soft_but_never_overwritten`），
原因是它的断言把「一次坏字节清空全部已登记项目」钉成了预期行为——**断言被改强而非削弱**（新断言额外要求原字节保留）。

### 处置汇总

| 严重度 | 条数 | 处置 |
|---|---|---|
| high | 3 | 全部 **patch/bad_spec 就地修复**（会话列表 500、注册表被清空、运行端读错配置），0 条残留 |
| medium | 13 | **patch 已修 6**；**defer 6**（运行时归因与兜底族、阻塞 I/O、cron 工具面、工具配对证据、50-2 数字、大面积会话读）；**intent_gap/blocked 1**（cron 工具面 + 非回环运行姿态，待人裁决） |
| low | 8 | **patch 已修 6**（含文档 4 处、`line_count`、`create_session` 码映射）；**defer 2** |
| reject | 1 | 镜头一⑭（有意为之的常量先就位） |

- 新增 deferred 台账条目 **3 条**（活动区 8 → 11 条，`ledger_count.py` 复核 11 open / 3 closed）。
- `review_loop_iteration: 0` —— 本轮无「回去重新推导」的情形：所有 Critical 都是**就地最小修复**（契约允许范围）。

### 结论

- **Story 层（50-1…50-4）：放行**。三条 high 已就地修复并通过负向验证；`pytest` **2747 passed**、覆盖率 **91.44%**、
  ruff/format/mypy 双平台全绿。
- **Epic 50 收口：不放行**，阻塞项两条：
  1. **待裁决（blocked）**：`enable_cron=False` 只拒调度器、cron 工具面仍可写任务（后续 CLI 会话会无人监督执行）
     —— 两条修法互斥，需产品/安全口径拍板（台账第 3 条）。
  2. **未完成面**：50-5（配置写入通道）、50-6（控制台 UI）、50-7（安全验收与文档）尚未实现；其中 50-5 直接复用
     本次校正后的白名单/守卫/指纹常量，50-7 需把台账第 1、3 条写进 `docs/frame.md` 五 与验收文档。
- **给 50-5 的两条硬前提**（本次评审发现）：① `HTTP_CONSOLE_*` 两键新增后会自动落入「控制台自身」排除规则
  （无需改分类逻辑）；② 备份落点只有一个来源 `WorkspacePaths.config_backups`（脊柱 §3.1 已按代码校正为 `backups`，
  不得另拼 `backups/env`）。

---

<a id="review-epic-50-closure"></a>

## Epic 50 · 全量收口评审（第二轮）

> **原文件**：`reviews/review-epic-50-closure.md` ｜ **轮次 / 类型**：第二轮 · 全量收口评审（Story 50-1…50-7） ｜ **日期**：2026-09-24

**原 frontmatter（逐字保留）**

```yaml
epic: E50（网页控制台）
scope: Epic 50 全量收口（Story 50-1 / 50-2 / 50-3 / 50-4 / 50-5 / 50-6 / 50-7 全部 7 条）
diff_range: 33adba0..1ca29cf（含第一轮 33adba0..3ff9d8d 与后续 50-5/50-6/50-7 增量）
review_loop_iteration: 0
reviewer: code_review 契约（三镜头 + 定级 + 分诊）
first_round: reviews/review-epic-50-implementation.md（增量轮，覆盖 50-1..50-4）
verdict: 放行（Epic 50 收口通过；3 条 low 级 deferred 与 2 条 blocked 待人裁决不阻塞收口）
created: '2026-09-24'
```


按 `code_review` 契约执行：**对抗式 / 边界追踪 / 验证缺口** 三镜头各自独立成段；定级前逐条打开源码读
调用点与守卫（不只看 diff hunk）；Critical / `patch` 就地最小修复并重跑受影响测试 + 负向验证。

**与第一轮的关系**：第一轮（`review-epic-50-implementation.md`）是**增量轮**，只覆盖 50-1…50-4，并在结论里
写明「Epic 50 收口**不放行**：还差 50-5/50-6/50-7」。本轮是**收口轮**，覆盖 Epic 50 **全部 7 条 story**，
并逐条复核第一轮的发现（见「第一轮发现复核」）。两文件并存：前者记录增量轮的发现与修复，本文件给出收口裁决。

### 评审范围

- **Epic**：`_bmad-output/epics/epic-50-网页控制台周期/`（脊柱 + 7 份 story + 三份验收/评审产物）。
- **覆盖的 story**：50-1（工作区一等化）、50-2（项目注册表）、50-3（会话持久化 / 会话 API / 项目内运行）、
  50-4（配置来源求解与只读面板）、50-5（配置写入通道）、50-6（控制台 UI + 浏览器验收）、50-7（安全收口与文档）。
- **diff 范围**：`git diff 33adba0..1ca29cf` —— **75 文件 / +15535 −465**（src 约 7.6k 行、tests 约 6.2k 行、
  产物与文档约 1.7k 行）。
- **本轮重点**：50-5/50-6/50-7 的**新增面**（写入流水线 / 保真写 / 覆盖层面板 / 两栏 UI / 契约与验收），
  并对 50-1..50-4 的面做**回归式复核**（第一轮的修复是否仍在、断言是否仍有效）。
- **执行方式**：三镜头由我逐处读取真实源码 + 亲跑命令；对抗式与边界镜头另用一次性探针直接打真实模块
  （`.heagent/tmp/review50_probe.py`、`review50_errorcodes.py`），不靠读 diff 猜。

#### 我实际执行过的命令与结果

| 命令 | 结果 |
|---|---|
| `python -m pytest -q` | **3076 passed / 11 skipped / 18 deselected**（含本轮补的 19 例：1 例真实装配 + 18 例枚举驱动参数） |
| `python -m pytest -q --cov=heagent --cov-fail-under=87` | TOTAL **92%**；`Total coverage: 91.83%`（门限 87%） |
| 逐模块覆盖率（全量测试集） | `envfile.py` **100%**、`workspace.py` **100%**、`config_write.py` **99%**、`config_catalog.py` **98%**、`http_console_protocol.py` 94%、`cli_http.py` **89%**、`context/session.py` **90%**（补证前 85%）、`projects.py` 85% |
| `ruff check src tests` / `ruff format --check src tests` | All checks passed! / 277 files already formatted |
| `mypy src` / `mypy src --platform linux` | 均 `Success: no issues found in 146 source files` |
| `node tests/js/console_acceptance.mjs` | `ACCEPTANCE {"rows":18,"failed":0}`（真浏览器 Chrome 153） |
| `python .heagent/tmp/review50_probe.py` | 11 组边界探针（大小写键 / 锁文件落点 / 重复键 / 空值键 / 目标为目录 / 无等号行 / 裸 CR-LF / 注释行同名键 / 无末行换行追加 / 进程环境） |
| `python .heagent/tmp/review50_errorcodes.py` | `HttpErrorCode` 32 码 ↔ `app.js::ERROR_TEXT` 32 键**完全对齐**（0 缺 0 幽灵） |
| `python .heagent/tmp/mutate_50_review2.py` | 3 组（含 1 组**负对照**）全部符合预期 |

---

### 第一轮发现复核（是否仍成立 / 是否已闭合）

| 第一轮条目 | 本轮复核 | 结论 |
|---|---|---|
| high#1 会话列表 500（畸形消息条目） | 读 `context/session.py` 现状：`SessionUnreadableError` 已覆盖「消息项不合法」；`test_list_metadata_treats_invalid_message_entry_as_unreadable` 在位并通过 | **已闭合** |
| high#2 注册表被一次坏字节清空 | `projects.py` 写侧 `_decode_or_raise` 在位；`test_corrupt_registry_is_read_fail_soft_but_never_overwritten` 通过 | **已闭合** |
| high#3 面板与运行端配置口径不一致 | `cli_http._project_settings()` 显式传 `_env_file=[全局, 项目]`；`test_for_workspace_resolves_settings_from_the_project_env` 通过 | **已闭合** |
| medium 6 条 defer（运行时归因 / 在途工具计龄 / SSE 限额竞态 / 阻塞 I/O / 工具配对证据 / 50-2 数字） | 逐条比对台账：6 条**仍在活动台账**且描述与本轮实测一致，无一条被静默关闭 | **仍成立（已登记）** |
| medium intent_gap 1 条（`enable_cron=False` 仍绑 cron 工具面） | 台账标 `blocked`；代码未变（`cli.py` 仍构造 `cron_store` 并在 `enable_cron=False` 时传给 loop） | **仍成立（blocked）** |
| low 8 条（含文档 4 处、`line_count`、`create_session` 码映射、`path_safety` 接缝、>1MiB 会话读） | 文档 4 处已修且本轮未回退；`line_count` 用 `splitlines()` 在位；`path_safety` / 大文件读**仍在**（已登记） | **已闭合 6 / 仍成立 2** |

---

### 镜头一 · 对抗式（找「缺什么」）

| # | 位置 | 问题 | 证据（亲读 / 亲跑） | 严重度 | 处置 |
|---|---|---|---|---|---|
| 1 | `config_write.py:530-560`（`_verify` + `except ConfigWriteRejection`） | 回读不符时无条件宣称「the project .env **was rolled back** to its previous content」——若**回滚本身也失败**（`persist._restore_bytes` 抛错只 `logger.error`），对客户端的文案就是**假的** | `_verify` 先设 `state.readback_failed` 再抛固定文案；回滚发生在 `persist.atomic_update_bytes` 内部，成败不回流到消息 | low | **defer**（`config_write_failed` 的**用户可见**文案在 UI 侧本就是诚实的「服务端已尝试恢复备份」，且该码不在 JS 的 `DETAIL_CODES`（不显示服务端 message）⇒ 实际只影响直接调 API 的客户端。精确文案需把回滚结果回传，非最小改动） |
| 2 | `persist.py::atomic_update_bytes`（`lock_path = path.with_name(path.name + ".lock")`） | 写项目 `.env` 会在**用户项目根**留下一个 0 字节 `.env.lock`（探针 B 实测：`['.env','.env.lock','.heagent']`）。HeAgent 自己的仓库有 `.gitignore` 条目，但**用户的项目**没有 | 探针 B | low | **defer**（锁文件刻意不删——删除会引入「B 等旧 inode、C 拿新文件加锁成功」的竞态，见 `persist` 注释；挪到状态目录会改变锁的语义。登记后由「是否给写入方加一条 README 提示」决定） |
| 3 | `config_write._apply_locked` | **全部**写入 I/O 在跨进程锁内完成，包括 `validate_candidate`（构造 `Settings` ⇒ 读候选临时文件 + 全局 `.env` + 环境）与备份目录扫描 ⇒ 锁持有时间随文件与环境规模增长 | 读码：`atomic_update_bytes(target, _update, ...)` 内的回调包含候选构造与 `prune_backups` | low | **defer**（失败模式是 fail-closed：并发写最坏得到 `config_write_failed`（锁超时 5s）而非 `config_conflict`，**不会**产生损坏或部分写入。要收窄需「锁外构造 + 锁内复检指纹」的乐观重试，属改造） |
| 4 | `cli_http.py:565-569`（`create_session` 的两个 except） | 分支**不可达**（`session_id = uuid.uuid4().hex` 不可能撞已存在文件；标题边界协议层已挡）⇒ 覆盖率为 0。第一轮报告曾把这处修复记为「覆盖于会话路由用例集」——**该主张不成立** | 逐模块覆盖率（全量集）显示 565-569 未执行；读码确认 `uuid4` 唯一性 | low | **低风险（防御性代码）**：分支本身正确且方向 fail-closed，**不补造用例**（补了也只是对着 unreachable 断言）；在本报告如实纠正第一轮的覆盖主张 |
| 5 | `network/http_server.py` 的写路由面 | 项目**重命名**、四个**会话**写操作、项目内**运行入口**均**无**回环门（登记 / 移除 / 配置写入有） | 读 `_loopback_error` 调用点 + `test_non_loopback_clients_cannot_register_or_remove_projects` 的 docstring | medium | **intent_gap → blocked**（沿用第一轮；两条修法都改变可观察行为，交人裁决） |
| 6 | `network/http_server.py:659/665/690/710` | `deadline_reason` 一经写入永久保留 ⇒ 用户的 `DELETE` 可能被误报 `timed_out` 并吞掉取消 | 沿用第一轮（本轮复核代码未变） | medium | **defer**（已登记） |
| 7 | `network/http_server.py:659` | `tools_in_flight` 永不衰减 ⇒ 一个永不返回的工具让静默判据恒不成立，名额被无界占用 | 沿用第一轮（代码未变） | medium | **defer**（已登记） |
| 8 | `cli_http.py` 的会话/配置读路径 | 唯一事件循环里做同步 I/O（会话列表 / 配置求解 / 注册表列举） | 沿用第一轮（代码未变；50-5 写了一处 `to_thread`，读路径未动） | medium | **defer**（已登记） |
| 9 | `tests/test_http_web_ui.py::TestConsoleApiContract` | **测试名说 every、实际只枚举 14/32 个错误码** ⇒ 「每个码都有文案」这一声称没有自维护判据 | `review50_errorcodes.py`：枚举 32 ↔ JS 32 键完全对齐，但用例只覆盖 14 | medium | **patch 已修**：参数改为由 `HttpErrorCode` 枚举派生（32 条），负向验证见下 |
| 10 | `cli_http.py:764-765`（`_resolve_session` 的 `SessionUnreadableError`） | 「用**损坏会话**起 run」这条**可达**路径零覆盖 ⇒ 若分支失效，会在损坏文件上继续写而无人察觉 | 覆盖率实测该行未执行；读码确认可达（`POST …/runs` + `session_id`） | medium | **patch 已修**：新增真实装配用例（409 `session_unreadable` + 损坏文件字节不变 + 无新会话文件） |
| 11 | `web/app.js::askConfirm` | 第二个确认框到来时直接覆盖 `confirmPending` ⇒ **前一个 promise 永不结算**（那次危险操作既没执行、也不会走到 `await` 之后的代码） | 读码：`confirmPending = { resolve, wantsInput }` 覆盖式赋值；无并发守卫 | low | **patch 已修**（1 行：被顶掉者以「取消」结算）。**如实标注：无可观察差异**（两种写法都不删/不改），修的是「未来任何 `await askConfirm` 之后的代码会静默不执行」的陷阱，故**没有新增断言** |
| 12 | `tests/test_config_write.py::TestAuditRetention` 与 `RESOURCE_CEILINGS` | 上界表 / 审计回收的**取值口径**只由「规则用例」钉（≥10× 默认、完备性） | 复核：`test_the_ceiling_table_is_exactly_the_agreed_one` **已在**（50-7 前的批次补的），逐条比对键与刻度 ⇒ 规则之外还有数值钉 | — | **已核无问题**（记录为「已具备」，非缺项） |
| 13 | `docs/frame.md` 4.18 与代码 | 文档声称「条目上限 32 / id 为 `p`+8 位十六进制 / 写侧 fail-closed / 凭证只回掩码」等 12 条事实 | 逐条对照 `projects.py` / `config_catalog.py` / `config_write.py` 与测试 | — | **已核无问题**（12 条全部与代码一致；本轮唯一发现的文档偏差是本轮自己修的 27→32 与 111/65→113/67） |
| 14 | `envfile.parse_index` 的键大小写 / 无等号行 / 注释行 | 写 `MAX_ITERATIONS` 而文件里是 `max_iterations=5`：**原地替换**（不留死行）；无等号行不入索引；注释行同名键**追加**新行而不动注释 | 探针 A / F / J | — | **已核无问题**（这三处是保真写最容易出错的地方，现为正确行为） |

> 镜头一合计 **11 条发现**（另 3 条为「已核无问题」记录）——满足契约「至少 10 条」。

### 镜头二 · 边界追踪（真实调用链）

| # | 边界输入 → 行为 | 证据 | 严重度 | 处置 |
|---|---|---|---|---|
| ① | 同一键在文件里出现两次（真实 `.env` 就有）：写一次只重写**最后一行**，第一行原样留下（值仍以后者生效） | 探针 C：`…=4000\n…=4096` → 写 8192 后为 `…=4000 / …=8192` | — | **已核无问题**（「后者生效」语义与解析一致，且面板 `duplicate_keys` 会告警） |
| ② | 空值键（`KEY=`）被写通道接着写：原地替换为 `KEY=4096`，不产生重复行 | 探针 D | — | **已核无问题** |
| ③ | 目标是**目录**（病态输入）：`ConfigWriteRejection: config write failed: [Errno 13] Permission denied`，**零副作用** | 探针 E | — | **已核无问题**（fail-closed；锁文件除外，见镜头一 #2） |
| ④ | 值含裸 `CR` / 裸 `LF`：`EnvWriteError: contains a control character` 拒 | 探针 G | — | **已核无问题**（否则可破坏行结构） |
| ⑤ | 文件**无末行换行**时追加新键：保持「无末行换行」这一文件属性 | 探针 K：`MAX_ITERATIONS=5\nSHELL_TIMEOUT=60`（新行同样无末行换行） | low | **defer**（有意保真：跟文件既有风格；但某些工具有「必须末行换行」的约定 ⇒ 记入台账备查） |
| ⑥ | 写成功后**进程环境**不受影响（`.env` 不是环境变量） | 探针 I：`os.environ.get("MAX_ITERATIONS") == "<未设置>"` | — | **已核无问题**（面板的 `system_env` 层由此天然区分） |
| ⑦ | 32 个错误码 ↔ UI 文案表：0 缺 0 幽灵 | `review50_errorcodes.py` | — | **已核无问题** |
| ⑧ | 项目根被删 + 写请求：闸门 → 项目解析 ⇒ `project_unavailable`（409），不触碰文件 | 读码 + 既有用例（`test_real_console_reports_unavailable_project`） | — | **已核无问题** |
| ⑨ | 写入期间并发第二个写：唯一胜者，败者 `config_conflict`（**跨进程**由文件锁兜底） | 既有用例 `test_concurrent_writers_only_one_wins` + 读 `atomic_update_bytes` | — | **已核无问题**（附带镜头一 #3 的锁时长隐患） |

### 镜头三 · 验证缺口（对照 AC 与测试报告）

| # | AC / 声称 | 实际证据 | 严重度 | 处置 |
|---|---|---|---|---|
| ① | 「每个控制台错误码都有可读文案」（用例名 + 50-6 记录） | 用例只枚举 **14/32**；JS 表实际齐全 ⇒ 声称成立但**判据不覆盖** | medium | **patch 已修**（枚举驱动；负对照证明旧清单是瞎的） |
| ② | 50-3 AC9 / D1「损坏会话」的**运行入口**侧 | `_resolve_session` 分支零覆盖（可达） | medium | **patch 已修**（新增真实装配用例） |
| ③ | 50-7 验收表称 `cli_http.py`「计入总量并由测试覆盖」 | 实测 **89%**（41 条未覆盖）：其中 `194-201`（`http-server` 命令的 serve 主体，测试桩掉了 `_serve_http`）、`831-863`（serve 收尾/关闭的错误路径）、`519/611/785/1058`（日志与防御分支）为**合理的**未覆盖；`531-535/546-550/565-569/764-765` 为**错误分支**（565-569 不可达） | low | **patch 部分**（②已补 764-765，实测 cli_http 89% / session 85→90%）；其余如实记入本报告，`cli_http.py` 不 omit 的口径**不变** |
| ④ | 50-5 的「审计不含值」 | 既有用例 + `TestAuditRetention` 的哈希断言 + 50-7 的五面用例（变异体⑥证明有牙） | — | **已核无问题** |
| ⑤ | 50-6 的浏览器验收 18 行 | 本轮亲跑：`ACCEPTANCE {"rows":18,"failed":0}`（新工作区，Chrome 153） | — | **已核无问题**（不进 CI 的缺口已登记） |
| ⑥ | 50-2 Dev Record 的「110 passed, 1 skipped」 | 沿用第一轮结论（不可复现，反推下界 ≥238） | low | **defer**（已登记；不改写他人 story 记录） |
| ⑦ | 50-7 的「6 条变异体全部精确变红」 | 本轮复核：`mutate_50_7.py` 6/6 仍全红 | — | **已核无问题** |

---

### 就地修复清单（最小修复 + 负向验证）

| 文件 | 修复 | 受影响测试（重跑） | 负向验证 |
|---|---|---|---|
| `tests/test_http_web_ui.py` | 错误码参数改为**由 `HttpErrorCode` 枚举派生**（32 条，自维护） | `tests/test_http_web_ui.py` → **117 passed** | `M1`：从 `app.js` 删 `server_error` 文案 ⇒ **1 failed**；**`M1b` 负对照**：同一变异 + 旧手写清单 ⇒ **0 failed**（证明修复有牙） |
| `tests/network/test_http_console_e2e.py` | 新增 `test_a_run_cannot_be_started_in_an_unreadable_session`（真实装配） | `tests/network/test_http_console_e2e.py` → **10 passed** | `M2`：把该分支的 `except SessionUnreadableError` 换成别的类型 ⇒ **1 failed** |
| `src/heagent/web/app.js` | `askConfirm` 被顶掉时把前一个按「取消」结算（1 行 + 注释） | `tests/test_http_web_ui.py`（含 14 个 node 探针用例）→ 全绿 | **无可观察差异**（已分析：两种写法都不执行危险操作）⇒ 无新增断言，如实标注 |
| `docs/frame.md` / `docs/README.md` / 脊柱 / 总览 / 状态 / story | 50-7 的文档同步（27→32 码、111/65→113/67、4.18 小节、Epic 49/50 两行等） | 全量 `pytest` | 纯文档（50-7 的 6 条变异体已覆盖文档契约面） |

**删除检查**：`33adba0..1ca29cf` 未删除任何既有守卫或契约。被改写的既有测试只有两处，均为**改强**：
① `test_corrupt_registry_warns_and_recovers_empty` → `…_is_read_fail_soft_but_never_overwritten`（第一轮）；
② `test_every_console_error_code_has_a_readable_text` 的参数由 14 条**扩到 32 条**（本轮）。

### 处置汇总

| 严重度 | 条数 | 处置 |
|---|---|---|
| high | **0** | —（第一轮的 3 条 high 已闭合，本轮复核无回退） |
| medium | **7** | **patch 已修 2**（镜头三①②）；**defer 3**（镜头一 #6/#7/#8，沿用第一轮已登记）；**intent_gap/blocked 1**（非回环运行姿态）；**patch+defer 1**（镜头三③：补证 + 如实记录未覆盖面） |
| low | **6** | **patch 已修 1**（镜头一 #11）；**defer 4**（回滚文案 / `.env.lock` 落点 / 锁内 I/O / 末行换行约定）；**不补造用例 1**（镜头一 #4 不可达分支 + 纠正第一轮覆盖主张） |
| 已核无问题 | **11 条**（镜头一 3 + 镜头二 8） | —（记录在案，避免「没写就是没查」） |
| reject | 0 | — |

新增 deferred 条目 **1 条**（末行换行约定；`.env.lock` 落点与锁内 I/O 两条并入既有「控制台」族条目下的说明）。
`review_loop_iteration: 0` —— 本轮无「回实现阶段重新推导」的情形（全部为就地最小修复或如实登记）。

### 结论

- **Story 层（50-1…50-7）：全部放行。** 第一轮 3 条 high 已闭合且本轮复核无回退；本轮 2 条 medium 验证缺口
  已就地补上并带负向验证；`pytest` **3076 passed**、覆盖率 **91.83%**（门限 87%）、ruff / format / mypy 双平台
  全绿、真浏览器 18/18。补证的可量化收益：`context/session.py` 覆盖率 **85% → 90%**（损坏会话的运行入口路径）。
- **Epic 50 收口：放行。** 七条 story 的交付物齐备（含两份验收清单与三份文档同步），Epic 级无 high 级残留。
- **不阻塞收口但需人裁决/后续跟进的 3 项**（均已在台账）：
  1. **blocked**：非回环运行姿态（项目重命名 / 四个会话写操作 / 项目内运行入口无回环门）；另 `enable_cron=False`
     仍绑 cron 工具面 —— 两条都需要产品/安全口径拍板。
  2. **defer（medium）**：`deadline_reason` 归因保留、`tools_in_flight` 不衰减、唯一事件循环里的同步 I/O。
  3. **defer（low）**：`.env.lock` 落在用户项目根、回滚失败时的文案、写锁内 I/O 时长、无末行换行文件的追加约定。
- **给下一次评审的备忘**：本轮的「负对照」手法（同一变异 + 旧判据 ⇒ 应当全绿）能证明**判据修复**本身的价值，
  建议对「补证据」类发现一律配套使用。

---

<a id="review-epic-50-story-50-8"></a>

## Epic 50 · Story 50-8 收口后评审（第三轮）

> **原文件**：`reviews/review-epic-50-story-50-8.md` ｜ **轮次 / 类型**：第三轮 · Story 50-8 收口后评审（含续轮） ｜ **日期**：2026-09-26

**原 frontmatter（逐字保留）**

```yaml
epic: E50（网页控制台）
scope: Epic 50 收口后**增量轮**评审——Story 50-8（控制台体验优化 R1–R10）+ 对 50-1…50-7 面的回归式复核；含**续轮**（前端探针桩保真度 / 真实原生弹窗独立复现 / 新端点的入口宽度与默认姿态）
diff_range: e4d56cf..bb436b8（Story 50-8 的两条提交 cc717f8 / bb436b8；本轮修复另见「就地修复清单」）
review_loop_iteration: 0
reviewer: code_review 契约（三镜头 + 定级 + 分诊）
prior_rounds: reviews/review-epic-50-implementation.md（第一轮，50-1…50-4）· reviews/review-epic-50-closure.md（第二轮，50-1…50-7 收口放行）
verdict: 放行（Story 50-8 与 Epic 50 全量；4 处判据/口径已就地修复并带负向验证；新增 2 条 low 级 blocked 待人裁决，不阻塞）
created: '2026-09-26'
```


按 `code_review` 契约执行：**对抗式 / 边界追踪 / 验证缺口** 三镜头独立成段；定级前逐条打开源码读调用点与守卫
（不只看 diff hunk）；`medium` 及以上与判据类发现一律就地最小修复 + **负向验证**并重跑受影响测试。

### 为什么还有第三轮（评审范围）

- 第一轮（`review-epic-50-implementation.md`）是**增量轮**，只覆盖 50-1…50-4；
- 第二轮（`review-epic-50-closure.md`，2026-09-24）是**收口轮**，覆盖 50-1…**50-7**，结论「放行」；
- **Story 50-8 在收口之后才落地**（`cc717f8` 2026-09-24、`bb436b8` 2026-09-25），它自我定位为「Epic 50 的增量
  需求落点」（R1–R10 十轮追加），**从未被任何一轮评审覆盖过**。本轮即以 50-8 的**新增面**为主靶
  （`cli_dialogs.py` 新模块 + 新端点 + 网页侧事件桥收敛 + 8 处前端改动），并对 50-1…50-7 的面做回归式复核。

### 评审范围

- **Epic 产物**：`_bmad-output/epics/epic-50-网页控制台周期/`（脊柱 + 8 份 story + 4 份验收/评审产物）。
- **diff 范围**：`git diff e4d56cf..bb436b8` —— 26 文件 / **+2784 −96**（src 约 +396、tests 约 +1258、产物与文档约 +1130）。
- **新增可执行面**：`src/heagent/cli_dialogs.py`（257 行，新）、`POST /api/dialogs/pick-directory`、
  2 个新错误码、`cli_http._web_tool_output`、`web/{index.html,app.js,styles.css}` 的 8 处改动。
- **执行方式**：三镜头由我逐处读真实源码 + 亲跑命令；对抗式与边界镜头另用一次性探针直接打真实模块
  （`.heagent/tmp/review50_8_probe_test.py` / `review50_8_badge_probe.py` / `review50_8_mutate.py`），不靠读 diff 猜。

#### 我实际执行过的命令与结果（全部亲跑）

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

### 镜头一 · 对抗式（找「缺什么」）

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

### 镜头二 · 边界追踪（真实调用链）

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

### 镜头三 · 验证缺口（对照 AC 与测试报告）

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

### 就地修复清单（最小修复 + 负向验证）

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

### 处置汇总

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

### 续轮（同一评审的第二批探测：桩保真度 / 真实弹窗 / 入口宽度）

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

### 结论

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

---

<a id="review-epic-50-round4"></a>

## Epic 50 · 第四轮收口评审（HEAD 独立复核 + 新面深挖）

> **原文件**：`reviews/review-epic-50-round4.md` ｜ **轮次 / 类型**：第四轮 · HEAD 独立复核 + 新面深挖 ｜ **日期**：2026-09-26

**原 frontmatter（逐字保留）**

```yaml
epic: E50（网页控制台）
scope: Epic 50 收口后**第四轮**——对 HEAD 的独立全量复核（8 条 story）+ 新面深挖（配置面板归属 / 会话 id 校验 / 会话存储并发与回收 / 凭证掩码域）
diff_range: bd47a87..2f55e77（Epic 50 全量：90 文件 / +21166 −492；本轮修复另见「就地修复清单」）
review_loop_iteration: 0
reviewer: code_review 契约（三镜头 + 定级 + 分诊）
prior_rounds: reviews/review-epic-50-implementation.md（第一轮 · 50-1…50-4）· reviews/review-epic-50-closure.md（第二轮收口 · 50-1…50-7）· reviews/review-epic-50-story-50-8.md（第三轮 · 50-8 + 续轮）
verdict: 放行（Epic 50 全量 8 条 story；1 条 medium + 1 条 low 就地修复并带负向验证；新增 3 条 deferred + 2 条 blocked 待人裁决，均不阻塞）
created: '2026-09-26'
```


按 `code_review` 契约执行：**对抗式 / 边界追踪 / 验证缺口** 三镜头各自独立成段；定级前逐条打开源码读调用点与守卫；
`medium` 及以上与判据类发现一律就地最小修复 + **负向验证**并重跑受影响测试。既有三份报告与本轮**均按「待核验主张」**处理：
凡本报告写下的数字与行为，都是我**亲跑命令或亲读源码**得到的。

### 为什么还有第四轮（评审范围）

- 第一轮 `review-epic-50-implementation.md`（增量轮）只覆盖 50-1…50-4，结论「收口不放行」；
- 第二轮 `review-epic-50-closure.md`（收口轮）覆盖 50-1…50-7，结论「放行」；
- 第三轮 `review-epic-50-story-50-8.md` 覆盖 50-8（`cc717f8` / `bb436b8`）与其续轮，结论「放行」，并就地修了 3 处**判据空转**；
- 其后的 `2f55e77`（第三轮修复的提交）**只被第三轮报告自述覆盖**；本轮对 HEAD 做一次**独立**复核，并把前几轮**都没探过**的
  面（设置面板的**归属**语义、会话 id 的字符集边界、会话存储的**并发与回收**、凭证**掩码域**）作为主靶。

### 评审范围

- **Epic 产物**：`_bmad-output/epics/epic-50-网页控制台周期/`（脊柱 + 8 份 story + 6 份验收/评审产物）。
- **代码面（本轮精读）**：`config_write.py`（580 行全读）、`envfile.py`（368 行全读）、`cli_dialogs.py`（257 行全读）、
  `context/session.py`（路径/版本/列表/删除）、`config_catalog.py`（掩码/notes/unknown/构建入口）、
  `projects.py`（register 写路径）、`network/http_console_protocol.py`（id 正则与协议常量）、
  `web/app.js`（项目层 / 会话层 / 设置面板 / 引导段）、`tests/js/app_probe.js`（桩保真度与用例结构）。
- **改动文件**：`src/heagent/web/app.js`、`tests/js/app_probe.js`、`tests/test_http_web_ui.py`、
  `src/heagent/context/session.py`、`src/heagent/network/http_console_protocol.py`、`tests/test_session.py`、
  `tests/network/test_http_console_sessions.py`、`docs/frame.md`、台账（见「就地修复清单」）。

#### 我实际执行过的命令与结果（全部亲跑）

| 命令 | 结果 |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` | **3144 passed / 11 skipped / 18 deselected，140.02s** —— 与第三轮自报数字**逐字一致** |
| `.venv\Scripts\python.exe -m pytest -q --cov=heagent --cov-report=term` | `TOTAL 13041 869 3546 393 **92%**`；3144 passed（167.45s） |
| `.venv\Scripts\python.exe -m ruff check src tests` | `All checks passed!` |
| `.venv\Scripts\python.exe -m ruff format --check src tests` | `280 files already formatted` |
| `.venv\Scripts\python.exe -m mypy src` / `mypy src --platform linux` | 均 `Success: no issues found in 147 source files` |
| `.venv\Scripts\python.exe .heagent\tmp\rev50_probe.py` | 5 组边界探针（id 尾随换行 / 带换行的文件名落盘 / Windows 保留设备名 / 锁文件回收 / UNC 同步 I/O） |
| `node tests/js/app_probe.js src/heagent/web/app.js ... U`（修复前后各一次） | 修复前 `writeCalls=1, writtenKeys=["MAX_ITERATIONS"]`；修复后 `writeCalls=0` |
| `.venv\Scripts\python.exe -m pytest tests/test_http_web_ui.py -q` | 修复前 **137 passed** → 修复后 **138 passed**（+1 新判据） |
| `.venv\Scripts\python.exe -m pytest tests/test_session.py tests/network/test_http_console_sessions.py -q` | 修复后 **82 passed**；**负向**（两处正则退回 `$`）**1 failed** |
| `.venv\Scripts\python.exe -m pytest -q`（**修复后终态复跑**） | **3146 passed / 11 skipped / 18 deselected，140.86s**（+2 = 本轮新增的 1 个前端判据 + 1 个存储侧参数） |
| `ruff check` / `ruff format --check` / `mypy src` / `mypy src --platform linux`（**修复后终态复跑**） | 全部全绿（`All checks passed!` / `280 files already formatted` / `147 source files` ×2） |

> 执行方式：三镜头由我逐处读真实源码 + 亲跑命令；对抗式与边界镜头另用一次性探针直接打真实模块
> （`.heagent/tmp/rev50_probe.py` / `rev50_probe2.py`）与真实前端脚本（node + 既有 DOM 替身），不靠读 diff 猜。
> 我另用了隔离子代理做**广度扫描**（定位候选），但表中每条发现的**定级与处置都由我逐条打开被引用的源码复核**；
> 子代理提出而复核不成立者，一律降级为「已核无问题 / reject」并写明理由（见镜头一末）。

---

### 镜头一 · 对抗式（找「缺什么」）

| # | 位置 | 问题 | 证据（亲读 / 亲跑） | 严重度 | 处置 |
|---|---|---|---|---|---|
| 1 | `web/app.js::saveConfig`（`state.activeProjectId` 取项目、`state.config` 取内容） | **面板不校验归属 ⇒ 切换项目后会把 A 的未保存改动写进 B 的 `.env`**。切到 B 时若配置读取失败（或在途），面板留着 A 的行与 A 的未保存改动（`state.config` / `configInputs` 未失效），而写路径取 `activeProjectId`；两侧都没有 `.env` 时指纹都是 `null`（= 「文件不存在」），服务端的指纹闸门**拦不住** `None == None` | 探针用例 U（真前端脚本 + node 桩，**修复前** HEAD 版 app.js）：`activeProject="项目 B"`、`writeCalls=1`、`writtenKeys=["MAX_ITERATIONS"]` —— 确认请求发向 `PUT /api/projects/pB/config` | **medium** | **patch 已修**（+ 新增判据 + 负向验证，见修复清单 ①） |
| 2 | 同上（`loadConfig` 开头的 `el.settingsProject.textContent = projectName(projectId)`） | 面板头在读**开始**时就写成目标项目名 ⇒ 读失败时出现「头部写着 B、行与徽标还是 A」的撒谎状态 | 探针 U 修复前 `headerAfterSwitch="项目 B"`，而 `rowValue="25"`（A 的值） | low | **patch 已修**（头部只跟随已载入的配置，见修复清单 ①） |
| 3 | `context/session.py:40` `_SESSION_ID_RE` + `network/http_console_protocol.py:52` `SESSION_ID_PATTERN` | 两处同源校验都用 `$` 收尾（`re.match`）⇒ `"abc\n"` **被双放行**（Python `$` 匹配「末尾换行之前」），与协议 docstring 声称的「两点各自 fail-closed」相反 | 探针 1)：`session_re.match("abc\n")=True`、`protocol.is_valid("abc\n")=True`；探针 2) 带 `\n` 的文件名在 Windows 直接 `OSError(22, 'Invalid argument')`（→ 路由 500） | low | **patch 已修**（`$` → `\Z`，两处；判据补进既有「同义性」用例，见修复清单 ②） |
| 4 | `context/session.py::save` + `agent/run_lifecycle.py`（落盘不传 `expected_version`） | **同一会话文件的两个写者整份覆盖对方历史**：锁只覆盖「单次读改写」，不覆盖 `load → … → save`；CLI 与内嵌网页入口共享同一 cwd 工作区（默认项目根 = `os.getcwd()`），网页 `POST …/runs` 不带 `session_id` 时 `_resolve_session(None)` 取**最近**会话（往往是 CLI 正在写的那个）⇒ 后写者 `_session_payload` 替换整份消息、`version` 仍单调递增（无从发现） | 读码 `save(expected_version: int \| None = None)`（仅非 None 时比对）+ `run_lifecycle` 不传版本；`tests/network/test_http_console_sessions.py` 的替身**刻意**按 last-write-wins 建模 | **medium** | **defer**（台账新增：修法跨 `agent/`+`context/` 的写者语义，超出评审最小修复范围；冻结边界已写明「不得改成让运行落盘失败」） |
| 5 | `context/session.py::_validate_session_id`（字符集天然放行 `NUL` / `CON` / …） | **Windows 保留设备名 ⇒ 整段对话静默丢弃**：`NUL`（含 `NUL.json`）被解析为空设备，`exists()` 恒 True、读取得空串 ⇒ `load()` 返回「空历史」；`save()` 写向空设备 ⇒ 对话不落盘、`list_metadata` 也永远看不到它 | 探针 3)：`os.path.exists('NUL.json')=True`、`'CON.json'=True`、`path_for('NUL')` 通过校验 | low | **defer**（台账新增；既有缺陷类，`cc7fd5d` 引入，非本 Epic 引起 ⇒ 按纪律只登记） |
| 6 | `context/session.py::prune`（`suffix=".json"`）+ `delete`（只删 `.json`） | **`<id>.json.lock` 没有回收方**：每次 `save` / `create` / `rename` 留一个 0 字节锁文件，`endswith(".json")` 对 `X.json.lock` 为 False ⇒ 随会话数单调增长（`persist` 注释声称「由各自的 prune 随记录一并回收」对 sessions 不成立） | 探针 5)：400 天前的 `deadbeef.json` + `.json.lock`，`prune(retention_days=30)` 返回 1，残留 `['deadbeef.json.lock']` | low | **defer**（台账新增；删锁文件会引入「B 等旧 inode」竞态，须先定寿命策略） |
| 7 | `web/app.js::renderDiagnostics` + `config_catalog.build_config_report` | 诊断折叠标题把**信息性 note** 计入「需要注意」并把块标成 `failed`：`for (const note of config.notes \|\| []) warnings.push(...)`，而 notes 含 `project_env_missing`（新项目**常态**）；BOM 一事**双计**（前端 `env_file.has_bom` 告警 + `project_env_bom_stripped` note） | 读码；判据把现状钉住：`tests/test_http_web_ui.py::test_settings_panel_is_compact_without_losing_reasons` 断言「2 条需要注意」，S 用例 fixture 正是「重复键 + project_env_missing」 | low | **intent_gap → blocked**（台账新增；要裁「哪些 note 属需要注意」） |
| 8 | `config_catalog.is_secret_key`（`_SECRET_SUFFIXES`）+ `EXCLUSION_GROUPS` 的 `patterns=("*_BASE_URL",)` | **掩码域是名字后缀制**：写进 `*_BASE_URL` 的凭证（`https://user:token@relay/v1`）被**原样**放进 `ConfigItem.value` 并渲染进页面；`GET /api/projects/{id}/config` **无**回环门 ⇒ 能连到服务的客户端都可读 | 读码 `_build_item`（`value=None if secret else values.get(...)`）；脊柱 §288 把「凭证」定义为 `*_API_KEY(S)` ⇒ **与规格一致**（设计边界，非实现偏离）；对照 `LoggingObserver` 的脱敏**包含 URL userinfo** | low | **intent_gap → blocked**（台账新增；是否扩大掩码域待人裁决）+ **patch 文档**（`docs/frame.md` 该行补注掩码域口径，消除「以为面板不回显凭证」的误读） |
| 9 | `web/app.js:1442`（`未知键（${keys.length} 条，不生效）`）vs `config_catalog` 的 `MAX_UNKNOWN_KEYS=64` + `unknown_keys_truncated` | 未知键**被截断时**标题把 64 当**总数**（真正的提示落在另一个折叠块里），与已登记的会话计数条目（A18）同族但落在 50-8 的**新面** `#settings-unknown-summary` | 读码两侧；`tests/test_http_web_ui.py` 只断言 1 条时的文案 | low | **defer**（并入 A18 同族口径裁决；本轮不重复登记新条目） |
| 10 | `web/app.js::pickProjectDirectory` 与 `registerProject` / `selectProject` | `#project-register` 的 `disabled` 由**三处独立读写**、无共享在途计数 ⇒ 先结束的一方会解锁仍在途的另一方（可重复提交登记 / 切项目期间按钮"点了没反应"） | 读码三处赋值 | low | **reject**（复核后不构成缺陷：`ProjectRegistry.register` 按**规范化路径**去重——同路径直接返回既有条目、不产生第二条；且修法是共享 busy 计数的**局部重构**，评审契约明令不借评审做重构） |
| 11 | `web/app.js::pickProjectDirectory` 的 `const payload = await response.json()` | 2xx 但 body 非 JSON（响应被截断）时异常逃出 `void pickProjectDirectory()` ⇒ 未处理拒绝 + 状态行**永久停在**「已在服务端打开目录选择窗口…」 | 读码；服务端该路由恒回 `JSONResponse`（需响应截断才可达），同写法在既有 4 处一致 | low | **reject**（不可达性 + 既有同型风格；记录理由避免「没查就是没查」） |
| 12 | `web/styles.css` `.config-head{display:flex;flex-wrap:wrap}` + `.config-value{overflow-wrap:anywhere}` vs AC14「值不再独占一行」 | flex 换行判据用**未收缩前的 max-content** 宽度 ⇒ 超长值（`ROUTING_POOLS` 这类 JSON）会整体挪到自己那一行（在行内再折行）；AC14 的字面表述对该类键不成立 | 读码两侧 CSS（未做真实浏览器几何复测，**如实标注**） | low | **reject**（AC14 的**意图**——值不再是独立段落——成立；超长值独占一行是 flex 换行语义的必然，且相对旧 `<p>` 布局无回归） |
| 13 | `cli_dialogs.py::parse_marked_path`（`Path(candidate).is_dir()`） | 相对路径会相对**服务进程 cwd** 解析 ⇒ 病态后端可回一个"恰好存在的相对目录" | 读码：两个冻结脚本都回绝对路径（tkinter `askdirectory` / PS `SelectedPath`）⇒ 不可达 | low | **reject**（不可达，且返回值仍过登记校验） |
| 14 | `DirectoryPickResponse.path` 的 `max_length` vs `cli_http.pick_directory` | 超长路径让**响应模型构造**抛 `ValidationError` ⇒ 端点的 catch-all 兜成 500 `server_error`，而非稳定码 `invalid_project_path` | 读码 | low | **reject**（量级罕见 + 500 是 fail-safe 方向；同一路径在 `POST /api/projects` 也会被拒） |

> 镜头一合计 **14 条具名发现**（另 3 条「已核无问题」见下），满足契约「至少 10 条」。
>
> **已核无问题**：① `sessionMore` 在「当前会话落在最近 10 条之外」时隐藏是**有意**（代码注释写明「按钮点了也不会收起，留着只会误导」，逻辑上确不可收起）——非缺陷；
> ② 非回环来源对「项目重命名 / 四个会话写 / 项目内运行入口」无回环门 —— 沿用第二轮 `blocked` 条目，本轮不重复登记；
> ③ `web/app.js` 全文件无 `innerHTML` / `insertAdjacentHTML` / `eval` / `new Function`，服务端字符串一律走 `textContent` / `createTextNode`（既有 `TestPlainTextRendering` + `TestCspCompatibility` 在位）。

### 镜头二 · 边界追踪（真实调用链）

| # | 边界输入 → 行为 | 证据 | 严重度 | 处置 |
|---|---|---|---|---|
| ① | 会话 id `"abc\n"`：两道校验**都放行**；落到文件系统时 Windows `OSError(22)`（→ 500） | 探针 1) / 2) | low | 见镜一 #3（**已修**） |
| ② | 会话 id `"../escape"` / `"a/b"` / `"a"*129`：两处都拒（`"a"*129` 在协议侧由 `{1,128}` 拒、存储侧由长度检查拒） | 探针 1) | — | **已核无问题** |
| ③ | `NUL` / `CON`：校验通过；`os.path.exists('NUL.json')` 为 **True**（空设备） | 探针 3) | low | 见镜一 #5（defer） |
| ④ | 400 天前的会话 + 锁文件：`prune(30)` 删记录**不删锁** | 探针 5) | low | 见镜一 #6（defer） |
| ⑤ | `Path('\\\\192.0.2.1\\share').resolve()`（不可达 UNC）：**实测 22.1s**，且这条调用在 `projects.normalize_project_path` 里、由 async 入口**内联**执行（无 `to_thread`）⇒ 单请求冻结整个事件循环（含 SSE 心跳） | 探针 4)（22.1s 为本机亲测；与子代理独立测得一致） | medium | **defer（既有条目补证）**：台账「控制台阻塞 I/O」条已登记，本轮补上**可复现的 22.1s 量级**证据 |
| ⑥ | 面板跨项目（切项目时配置读 500）：A 的未保存改动被写向 B | 探针用例 U | medium | 见镜一 #1（**已修**） |
| ⑦ | 未知键 > 64：标题把被截断的 64 当总数 | 读码 | low | 见镜一 #9（defer） |
| ⑧ | 恰 10 个会话 / 0 个会话 / 无选中（`activeIndex=-1`）：与既有判据一致，无静默错 | 读码 + 第三轮金标 | — | **已核无问题** |
| ⑨ | 写通道并发第二个写：唯一胜者、败者 `config_conflict`（跨进程文件锁）；写入期间候选构造/备份扫描都在锁内（第五轮… 见第二轮 deferred） | 读码 `config_write._apply_locked` + `persist.atomic_update_bytes(verify=…)` | — | **已核无问题**（锁内时长隐患沿用第二轮台账条目） |
| ⑩ | `.env` 非 UTF-8（GBK）：写通道 `current.decode("utf-8")` 失败 ⇒ `config_write_failed` 且**不重写**；读面整层被丢但未知键仍按行级扫描报出 | 读码 `_apply_locked` + `config_catalog._unknown_keys` 的 `encoding_ok` 门 | — | **已核无问题**（fail-closed 方向正确） |

### 镜头三 · 验证缺口（对照 AC 与测试报告）

| # | AC / 声称 | 实际证据 | 严重度 | 处置 |
|---|---|---|---|---|
| ① | 「保存配置只影响当前项目的 `.env`」（写通道 AC） | 此前**零判据**：既有用例只覆盖同项目内「指纹冲突 / 写成功 / 刷新失败」三态，没有任何用例构造「面板归属 ≠ 当前项目」的组合（探针 U 是本轮新增的第一条） | **medium** | **patch 已补判据**（见修复清单 ①；负向验证：无守卫时 `writeCalls=1` ⇒ 用例必红） |
| ② | 协议 docstring「非法 id 由两点**各自** fail-closed（不触碰文件系统）」 | `"abc\n"` 在两点上**都**放行（探针 1)）⇒ 声称不成立；两处都缺判据（既有候选表 10 项里没有换行类） | low | **patch 已修 + 补判据**（见修复清单 ②；负向验证 1 failed） |
| ③ | 第三轮自报数字：`3144 passed / 91.87% / ruff·format·mypy 双平台 / 23 条变异全红` | 本轮亲跑：`3144 passed`（140.02s）、`TOTAL 92%`、ruff 全绿、`280 files formatted`、mypy 双平台 `147 files` 全绿 —— **逐条一致** | — | **已核无问题**（变异体脚本 `mutate_50_8.py` 未重跑：23/23 的复跑成本高且第三轮已留日志 `mutate_50_8_run*.log`；如实标注**未复跑**） |
| ④ | 前几轮 3 条 high 的修复是否仍在位 | 全量套件含其判据且全绿：`test_session.py::test_list_metadata_treats_invalid_message_entry_as_unreadable`、`test_projects.py::test_corrupt_registry_is_read_fail_soft_but_never_overwritten` 均在；`cli_http._project_settings`（`cli_http.py:379`，`for_workspace` 在 `:306` 使用）在位 | — | **已核无问题**（无回退） |
| ⑤ | 浏览器级 UI 验收（`console_acceptance.mjs`，23 行） | 本轮**未重跑**（需真浏览器；第三轮亲跑 23/23 并留证据）。缺口本身已登记（浏览器验收不进 CI） | — | **defer（既有条目）**：如实标注本轮未复跑 |
| ⑥ | 覆盖率门槛 87% | 亲跑 `TOTAL 92%`（13041 语句 / 869 未覆盖） | — | **已核无问题** |

---

### 与前几轮的关系（回归复核口径）

| 前几轮条目 | 本轮复核 | 结论 |
|---|---|---|
| 第一轮 3 条 high（会话列表 500 / 注册表被清空 / 运行端读错 `.env`） | 判据在位且全量绿；`_project_settings` 仍在 `for_workspace` 使用 | **未回退** |
| 第二轮 medium（运行时归因 / 在途工具计龄 / SSE 限额 / 阻塞 I/O / 工具配对证据 / 50-2 数字） | 台账条目仍在活动区；本轮**新增**证据（不可达 UNC `resolve()` 22.1s）与其中一条 | **仍成立（已登记）** |
| 第二轮/第三轮 blocked（非回环运行姿态 / cron 工具面 / A17 / A18 / A19） | 未见代码变更使其消解；本轮不重复登记 | **仍成立（blocked）** |
| 第三轮就地修复的 3 处判据空转（闸标钩子值 / 会话文件落盘 / 「其它工具」收敛） | 判据在位（`test_http_web_ui.py::test_settings_panel_is_compact_without_losing_reasons` 断言钩子值 `只读（桩）`；`test_http_agent_api.py` 14 例）且全量绿 | **未回退** |

### 就地修复清单（最小修复 + 负向验证）

| # | 文件 | 修复 | 受影响测试（重跑） | 负向验证 |
|---|---|---|---|---|
| ① | `src/heagent/web/app.js`（+2 处）、`tests/js/app_probe.js`（+路由与用例 U）、`tests/test_http_web_ui.py`（+1 用例） | ① `saveConfig` 补「面板归属 = 当前项目」守卫（不符即拒绝并说明原因）；② `loadConfig` 不再在读取**开始**时改面板头（头只跟随已载入的配置） | `pytest tests/test_http_web_ui.py` → **138 passed**（原 137） | 同一条用例 U 跑 **HEAD 版** `app.js`：`writeCalls=1` / `writtenKeys=["MAX_ITERATIONS"]` / `headerAfterSwitch="项目 B"`（**证明无修复即变红**，且证明缺口真实可达） |
| ② | `src/heagent/context/session.py`、`src/heagent/network/http_console_protocol.py`、`tests/test_session.py`、`tests/network/test_http_console_sessions.py` | 两处 id 正则 `$` → `\Z`；候选表补 `"abc\n"`（同义性用例 + 存储侧参数化用例各一处） | `pytest tests/test_session.py tests/network/test_http_console_sessions.py` → **82 passed** | 两处正则退回 `$` ⇒ **1 failed**（存储侧 `"abc\n"` 参数）；同义性用例新增的候选专门拦「只修一半」的漂移 |
| ③ | `docs/frame.md`（配置来源行） | 补注掩码域 = `*_API_KEY` / `*_API_KEYS` 后缀（`*_BASE_URL` 等值原样回传），消除「以为面板不回显凭证」的误读 | 纯文档（全量套件绿） | — |
| ④ | `_bmad-output/implementation-artifacts/deferred-work-archive.md` | 活动区 19 → **24** 条 + 2026-09-26 流水账单行 + 5 条新正文 | — | — |

**删除检查**：`bd47a87..2f55e77` 未删除任何既有守卫或契约；本轮未删除任何测试，只**新增/加强**判据
（新增 1 个前端用例 + 1 个探针用例 + 2 处候选；无一条既有断言被放宽）。

### 处置汇总

| 严重度 | 条数 | 处置 |
|---|---|---|
| high | **0** | —（前几轮的 3 条 high 本轮复核未回退） |
| medium | **3** | **patch 已修 1**（面板归属 ⇒ 跨项目写入）；**defer 2**（同会话双写者整份覆盖；UNC 同步 I/O 既有条目补证） |
| low | **10** | **patch 已修 1**（id 正则双放行）；**intent_gap / blocked 2**（诊断口径 / 掩码域）；**defer 2**（保留设备名 / 锁文件无回收）；**reject 5**（登记按钮 disabled 竞争 / 非 JSON 2xx / AC14 长值几何 / 相对路径 `is_dir` / 超长路径 500） |
| 已核无问题 | **13 条**（镜一 3 + 镜二 7 + 镜三 3） | 记录在案，避免「没写就是没查」 |
| reject | 5 | 逐条给出「为什么不构成问题」的理由，不静默丢弃 |

新增台账条目 **5 条**（19 → 24；含 1 条 medium 静默数据丢失、2 条 blocked）。`review_loop_iteration: 0` —— 本轮无「回实现阶段重新推导」的情形
（全部为就地最小修复或如实登记）。

### 结论

- **Story 层（50-1…50-8）：放行。** 前几轮的三条 high 与三处判据空转修复**均未回退**；本轮亲跑 `pytest` **3144 passed**、
  覆盖率 **92%**、ruff / format / mypy 双平台全绿，与第三轮自报数字逐条一致。
- **Epic 50 收口：放行。** 本轮的价值集中在**一条此前无任何判据的跨项目写入路径**（面板归属）与**两处同源校验的字符集边界**：
  前者已在真前端脚本上复现（HEAD 版会把 A 的改动写向 B）并就地修复 + 固化判据 + 负向验证；后者两处一并收口。
- **不阻塞收口、需人裁决 / 后续跟进的 5 项**（均已进台账）：
  1. **defer（medium）**：同一会话文件两个写者**整份覆盖**对方历史（网页运行落盘 last-write-wins）；
  2. **blocked（low）**：诊断「N 条需要注意」把信息性 note 计入告警且 BOM 双计 —— 需定分级口径；
  3. **blocked（low）**：`*_BASE_URL` 等非后缀载体的值原样回显 —— 需定掩码域（文档口径已补正）；
  4. **defer（low）**：会话 id 放行 Windows 保留设备名（`--resume NUL` 静默丢历史）；`.heagent/sessions/*.json.lock` 无回收方；
  5. **defer（medium，既有条目补证）**：控制台路径上的同步 I/O —— 本轮补上不可达 UNC `resolve()` **22.1s** 的可复现量级。
- **给下一次评审的备忘**：本轮最有效的一招是**「同一用例跑两个版本」**——把新判据先用 `git show HEAD:<file>` 落一份旧版，
  在旧版上跑同一条用例，直接拿到「无修复即变红」的证据（比回退-重跑更省事、也不会碰工作区）。另：子代理适合**定位**、
  不适合**定性**——本轮 3 条「候选」经复核后降级为 reject，2 条升格为 accepted，全部由亲读源码定夺。

---

<a id="acceptance-50-6-console-ui"></a>

## Story 50-6 验收：网页控制台 UI（真实浏览器）

> **原文件**：`reviews/acceptance-50-6-console-ui.md` ｜ **轮次 / 类型**：验收 · Story 50-6（真实浏览器 CDP） ｜ **日期**：2026-09-24（补记 09-24）
>
> （该文档原件无 YAML frontmatter。）


- 日期：2026-09-24
- 驱动：`tests/js/console_acceptance.mjs`（自起**真实** `heagent http-server` + headless Chrome，CDP 驱动真实点击）
- 环境：Chrome **153.0.8010.48**；`heagent-http` 0.6.2；Windows；工作区 = 临时目录（脚本自动创建/删除，`--keep` 保留）
- 结论：**17 / 17 PASS**（`ACCEPTANCE {"rows":17,"failed":0}`）—— 首次交付（2026-09-24）
- **收口后补记（2026-09-24）**：新增 **A1b**（首页无阻塞遮罩）后为 **18 / 18 PASS**（`ACCEPTANCE {"rows":18,"failed":0}`）。
  补入原因：原 17 行**没有一行**能发现「打开首页即弹出关不掉的确认遮罩」（`hidden` 属性为真却照样渲染，且吞掉
  整页真实鼠标点击）—— 判据问题逐条分析见文末「收口后新增的判据」。

### 怎么复跑

```bash
node tests/js/console_acceptance.mjs            # 起服务 + 起浏览器 → 打印清单表 + ACCEPTANCE 汇总
node tests/js/console_acceptance.mjs --keep     # 保留临时工作区（含 console.png 截图）便于人工比对
```

前提：本机有 Chrome 或 Edge（自动探测；也可 `--chrome <路径>` / `CHROME_PATH`）、已装 `heagent[http]`
（starlette/uvicorn）、`python` 指向装有本仓库的环境（可 `--python <路径>`）。退出码 1 = 有行失败。

脚本**不做**的事（如实声明）：不跑真实 LLM 运行——本机当前无可用 provider（Ollama 未运行），因此
「流式回答」在真浏览器里的观感不在本清单里；该链的前端侧由 node 探针（`tests/js/app_probe.js` 的
A/B/C/D/E/N 用例，注入 SSE 事件断言渲染结果）与 Epic 49 的服务端用例覆盖。

### 清单与实测结果

| # | 步骤（页面） | 期望 | 实测 | 结论 |
|---|---|---|---|---|
| A1 | 首页加载 | 两栏骨架、设置入口、安全声明三条事实同时可见 | 两栏 + 设置入口 + 声明常驻可见 | PASS |
| A1b | 首页加载后立刻查遮罩（计算样式 + 真实命中测试） | 确认遮罩 `display:none`、0 个盒子，真实鼠标点击落到页面元素 | display=none、0 个盒子、视口中心最上层=DIV、真实点击落点=DIV、发送按钮在首屏之下（未纳入判据） | PASS |
| A2 | 观察浏览器网络请求 | 全部请求都同源（CSP + 页面无外链） | 7 个请求全部同源 | PASS |
| A3 | 观察 console / CSP 违规 | 没有 error 级 console 消息或 CSP 拦截 | 0 条 error（favicon 404 按无害过滤） | PASS |
| A4 | 项目列表 | 侧栏列出服务工作区项目且标记为可用 | `default=heagent-console-AtEPbP`（服务工作区徽标），共 1 个 | PASS |
| A5 | 填写目录 → 登记项目 | 侧栏出现该项目，且服务端注册表也有 | 侧栏与 `/api/projects` 都有「验收项目 B」（id=p817fb93b，共 2 个） | PASS |
| A6 | 删除该目录 → 刷新 | 标为 `available=false` 并显示「目录已失效」 | available=false + 「目录已失效」徽标 | PASS |
| A7 | 切到项目 B → 新建会话 → 切回 | 两侧会话列表互不可见（不串味） | B 的会话 1 个、服务工作区 0 个，无交集 | PASS |
| A8 | 刷新页面 | 回到上次的项目，会话仍在（落盘） | 刷新前后都回到「验收项目 B」且会话为 `cd6b9068…` | PASS |
| A9 | 重命名会话（确认框） | 标题更新且磁盘会话文件同步 | `cd6b9068….json` 的 `title` = 验收重命名 | PASS |
| A10 | 删除会话（先取消、再确认） | 取消不删文件；确认后文件消失 | 取消保留、确认后文件消失（2 → 1） | PASS |
| A11 | 打开设置面板 | 按后端分组渲染 + 来源徽标 + 只读项给原因 + 未知键单列 | 20 组 / 113 条（= 后端 113 字段）/ default+global_env+project_env / 67 个只读项全部给了原因 / 未知键 TOTALLY_UNKNOWN | PASS |
| A12 | 项目 `.env` 内预设假密钥后浏览面板 | 明文密钥不出现在页面文本、DOM 与凭证行 | 页面/DOM/行内都没有标记；凭证行只有「已配置 ********」+ 只读原因 | PASS |
| A13 | 改 `MAX_ITERATIONS` → 保存 → 确认 | 磁盘 `.env` 出现新值、显示「下一次运行生效」、来源徽标刷新、写前有备份 | 25 → 321（磁盘 + 面板），来源 project_env，备份 1 个，状态行「已保存：下一次运行生效」 | PASS |
| A14 | 提交非法值（`abc`） | 可理解文案；文件逐字节不变 | 「值不合法：本次没有改动任何文件。 服务端说明：MAX_ITERATIONS: must be a number」，文件未变（115 字节） | PASS |
| A15 | 窗口收窄到 420px + 收起侧栏 | 侧栏可收起（计算样式 `display:none`），安全声明仍可见 | sidebar display:none，声明仍可见 | PASS |
| A16 | 截图留档 | 整页截图写入临时工作区 | `…\heagent-console-AtEPbP\console.png`（49 KB） | PASS |
| B1 | 以 `HTTP_CONSOLE_WRITE_ENABLED=false` 另起一份服务 | 面板说明闸门关闭、全部可写项不可编辑、无任何开启入口 | 闸门说明可见、0 个可编辑控件、可写项原因一致、开关自身只读（无输入框） | PASS |

> A16 的截图路径随临时目录在脚本退出时删除（`--keep` 才保留）；本报告只保留可复跑的**实测结论**。

> **2026-09-24 后续调整（Story 50-8 R4）**：AC5 的「说明闸门关闭」由**整句解释收窄为一行短状态**
> （面板级 `未开启配置写入：可写项在本页只读` + 逐项 `只读：未开启配置写入`，完整长文案改挂 `title`）。
> 本报告 B1 行与上表 AC5 的口径据此更新为「**短**状态仍可见、长句不再出现」；R4 的验收证据见
> [`acceptance-50-8-refinement.md`](#acceptance-50-8-refinement)（A11c / B1 两行复跑于 2026-09-24，22/22 PASS）。
>
> **2026-09-25 再收窄（Story 50-8 R9）**：**逐项**那句也撤了——闸门关闭时只在设置面板头部、**项目名徽标之后**
> 挂一个紧凑徽标 `只读`（`title` = 短状态 + 长解释），**可写项不再逐项说明**（实测面板内 `.config-reason`
> 由 113 → 67 条，剩下的都是**键自身**的只读原因）；所有可写项仍为不可编辑、开关自身仍无输入框。
> AC5 的「逐项说明」由此收窄为「**面板级说一次 + 逐项不可编辑**」；复跑见
> [`acceptance-50-8-refinement.md`](#acceptance-50-8-refinement) 的「第四轮复跑（R9）」（23/23 PASS）。

### 覆盖到哪些验收标准

| AC | 对应行 |
|---|---|
| AC1 两栏 + 设置入口 + 常驻声明 | A1、A11 |
| AC2 切换项目只改本页状态、会话随项目走 | A5、A6、A7、A8 |
| AC3 SSE 行为无回归（流式 / 工具活动 / 停止 / 重连） | 见上文「脚本不做的事」——由 node 探针 A/B/C/D/E 与 49 的服务端用例覆盖，**本清单未含真浏览器 LLM 运行** |
| AC4 有效值 + 来源徽标 + 可写性 + 只读原因 + 凭证掩码 | A11、A12 |
| AC5 闸门关闭 ⇒ 全只读 + 原因 + 无开启入口 | B1 |
| AC6 保存成功 ⇒ 结果 + 「下一次运行生效」+ 刷新来源徽标 | A13 |
| AC7 危险操作二次确认 + 文案说明影响范围 | A9（重命名确认框）、A10（删除会话）、A13（写入确认框） |
| AC8 失败给可理解文案、不渲染不可信 HTML、不加载第三方脚本 | A2、A3、A14 |
| AC9 窄屏降级可用 | A15 |

### 已知缺口（同时登记在活动台账）

1. **浏览器验收不进 CI**：CI 只装 `.[dev]`（无 `heagent[http]`），也没有浏览器 ⇒ 本脚本只能按需手动跑。
   CI 里跑得动的是 node 探针（`tests/test_http_web_ui.py::TestWebUiBehaviour` 等，DOM 替身，不需要浏览器）。
2. **无真实 LLM 的浏览器运行验收**：本机无可用 provider，AC3 的「真浏览器里看着流式回答出现」未做；
   建议在有 provider 的环境用同一脚本补一行（提交提示词 → 断言对话区出现文本且终态为已完成）。
3. 窄屏断言的粒度：A15 只验证「侧栏可收起 + 声明可见」，未逐项验证每个控件的可点性（截图人工比对补充）。
4. **`click()` 用 DOM API，绕过命中测试**：清单里除 A1b 外都用 `node.click()`，因此「全屏元素遮挡点击」这类缺陷
   只有 A1b 能发现（2026-09-24 那条遮罩缺陷 17/17 照旧全绿正是此因）。保留 DOM 点击是**有意**的（真鼠标点击对
   布局变化更脆），代价是遮挡类问题只靠 A1b 一行覆盖。

### 收口后新增的判据（2026-09-24）

**A1b：首页无阻塞遮罩（计算样式 + 真实鼠标命中）** —— 触发背景：用户实测发现打开首页即弹出「请确认」且关不掉。
根因是 `styles.css` 的 `.overlay { display: flex }`（作者级声明）压过 UA 样式表的 `[hidden] { display: none }`，
`#confirm-overlay` 带着 `hidden` 属性照常渲染（`position: fixed` + `inset: 0` + `z-index: 20`）并吞掉整页真实鼠标
点击；`settleConfirm` 又在隐藏遮罩**之前** `if (!pending) return;`，加载时没有 pending ⇒ 关不掉。详见 Story 50-6
「收口后修复」与台账 Z-D15。

判据（三者同时成立才 PASS）：① `getComputedStyle(overlay).display === "none"`；② `overlay.getClientRects().length === 0`；
③ `elementFromPoint`（视口中心，及在视口内时的发送按钮处）与 CDP `Input.dispatchMouseEvent` 派发的**真实点击**落点
都不是 `confirm-overlay`（真实点击用捕捉层记录落点并 `preventDefault`，避免误提交一次运行）。

负向验证：把 `styles.css` 退回无守卫版本重跑整份清单 → **只有 A1b 变红**（exit 1），其余 17 行照旧 PASS。

---

<a id="acceptance-50-7-epic-acceptance"></a>

## Story 50-7 验收：Epic 50 周期验收（brief §9 逐条）

> **原文件**：`reviews/acceptance-50-7-epic-acceptance.md` ｜ **轮次 / 类型**：验收 · Story 50-7（brief §9 逐条） ｜ **日期**：2026-09-24
>
> （该文档原件无 YAML frontmatter。）


- 日期：2026-09-24
- 基线提交：`4193eac`（Story 50-7 开工时 HEAD）
- 环境：Windows / Python 3.13.5 / Chrome 153.0.8010.48；`pytest` 默认参数（跳过 integration / benchmark）
- 结论：**§9 的 9 条全部有可复现命令与实测输出**；全量质量门与真实浏览器验收同时通过

> 口径：每条给出**命令 + 实测输出**；跨条重复引用的命令只在其首次出现处展开。所有数字均为当场实测，
> 没有估算值；命令行可在仓库根直接复现。

### 逐条（brief §9）

| # | 验收点（brief 原文要点） | 命令 | 实测输出 | 结论 |
|---|---|---|---|---|
| **1** | 两项目交替操作，会话 / 项目级记忆 / 运行状态归属正确；A 的请求不能误读或修改 B 的会话 | `pytest tests/network/test_http_console_e2e.py -q` | `9 passed`（含 `…cannot_touch_another_projects_sessions`：跨项目读取/重命名/删除均 404 `unknown_session`、B 的会话文件字节不变；`…loop_cannot_read_another_projects_files`：**真实工具路径** `file_read` 读 B 的绝对路径返回 `tool_error=True` 且 B 的文件内容一个字未进事件流）<br>`pytest tests/network/test_http_console_sessions.py tests/network/test_http_console_projects.py -q` → `41 passed` | ✅ |
| **2** | 已保存会话在刷新浏览器 / 重启服务后仍可列出、打开、继续；消息顺序与工具调用/结果配对完整 | `pytest tests/test_http_web_ui.py tests/test_config.py -q` → `206 passed`（含探针用例 A「同名工具两次调用按序配对」）<br>`node tests/js/console_acceptance.mjs` → **`ACCEPTANCE {"rows":18,"failed":0}`**（A8 刷新后仍在项目 B 且会话 id 不变；A9/A10 重命名与删除作用到磁盘会话文件） | 真浏览器 18 行清单：A8 刷新持久化、A9 重命名落盘、A10 删除磁盘文件 2→1 | ✅ |
| **3** | 切换项目不改变既有运行绑定；停止 / 重连 / 会话删除定位准确，冲突有明确结果 | `pytest tests/test_cli_http.py tests/test_http_agent_api.py tests/test_http_security.py tests/network/test_http_server.py -q` → `128 passed`（含 `test_delete_cancels_a_real_run`、`test_disconnect_does_not_cancel_the_run`、每项目独立 loop）<br>探针用例 F：切走时只断本页 SSE、**不取消**在途运行并留常驻提示 | 真浏览器 A7（B 的会话 1 个 / 服务工作区 0 个，无交集） | ✅ |
| **4** | 四级配置来源与新运行解析一致；移除项目覆盖后正确显示回退值与来源 | `pytest tests/test_config_catalog.py tests/test_config_write.py tests/network/test_http_console_config.py -q` → `216 passed`（`TestSourceSolve` 逐层：默认 / 全局 / 项目覆盖 / 系统环境变量优先 / 移除行后回退；`test_values_match_a_directly_constructed_settings` 把面板与直接构造的 `Settings` 对齐） | 真浏览器 A11：20 组 / 113 条 = 后端 113 字段，来源 `default + global_env + project_env` 三种徽标同时出现 | ✅ |
| **5** | 开关关闭 / 非允许来源 / 未知键 / 非法值 / 凭证键 / 外部修改冲突均**显式失败**，原配置保持完整 | 同上 `216 passed`（`TestGate` / `TestWhitelist`（23 个只读类键逐条）/ `TestValueValidation`（26 条非法值）/ `TestConflict`（指纹冲突与并发唯一胜者））<br>`pytest tests/network/test_http_console_e2e.py -q` → `9 passed`（含 T2：非回环来源在**登记 / 移除**上收 403 + **注册表逐字节不变**；`test_closed_gate_keeps_the_config_surface_read_only_but_runs_still_work`：闸门关闭时 PUT ⇒ 403 且 `.env` 字节不变） | 真浏览器 A14（非法值文案 + 文件 115 字节未变）、B1（闸门关闭：0 个可编辑控件） | ✅ |
| **6** | 保存成功后当前运行保持旧快照、下一次运行用新值；API 与 UI 如实表达生效时机 | `pytest tests/test_cli_http.py -k next_run -q` → 见上行 `128 passed` 中的 `test_write_channel_applies_on_the_next_run_only`（旧 loop 快照仍是 5、下一次解析出 42；响应 `applied=next_run`）<br>探针用例 H/N：结果区显示「下一次运行生效」且写后条目**就地**刷新 | 真浏览器 A13：`25 → 321`（磁盘 + 面板），来源转为 `project_env`，状态行「已保存：下一次运行生效」，磁盘备份 1 个 | ✅ |
| **7** | 配置响应 / 错误 / 日志 / 审计不出现密钥明文（覆盖短密钥、多密钥与备份访问的负向验证） | `pytest tests/network/test_http_console_e2e.py -q` → `9 passed` 中的 `test_no_credential_leaks_across_five_faces`：短密钥 `sk-SHRT1234` + 多密钥 `sk-POOLAAAA,sk-POOLBBBB` 在**配置响应 / 三类错误信封 / SSE 帧 / 全部日志记录 / 审计 JSONL** 五面逐一排除性断言；审计里只留 sha256 与长度<br>同文件 `test_backups_and_the_audit_log_have_no_download_endpoint`：4 个候选下载路径全部 404 | 真浏览器 A12：页面文本 / `documentElement.outerHTML` / 凭证行三处都没有标记，凭证行只有「已配置 \*\*\*\*\*\*\*\*」 | ✅ |
| **8** | 移除项目登记保留目录与数据；删除会话需要确认，不能静默覆盖正在进行的写入 | `pytest tests/network/test_http_console_sessions.py tests/network/test_http_console_projects.py -q` → `41 passed`（含 `session_busy` 拒删在途会话、`confirm_required`、`project_not_removable`）<br>探针用例 J/K：删除会话与移除登记都走二次确认，文案写明「删文件 / 保留目录数据」 | 真浏览器 A10（先取消后确认：取消保留、确认后文件消失）、A5/A6（登记与目录失效标记） | ✅ |
| **9** | Epic 49 的流式 / 工具活动 / 停止 / 重连 / 来源校验无回归；入口限制在 UI 与文档中可见 | `pytest tests/test_cli_http.py tests/test_http_agent_api.py tests/test_http_security.py tests/network/test_http_server.py -q` → `128 passed`（49 的 SSE / 取消 / 重连 / 同源防线用例原样全绿）<br>`pytest tests/network/test_http_console_e2e.py -k same_three_facts -q` → `1 passed`（非回环告警与 UI 常驻声明**同口径**：无认证 / 无 TLS / 非安全边界；`exposure_warning` 含「loopback client is not trusted either」）<br>文档：`docs/frame.md` 4.18 + 配置表 2 行 + 五 的新增缺口 | 真浏览器 18/18（含 A2 无第三方请求、A3 无 CSP 违规、A15 窄屏降级） | ✅ |

### 全量质量门（T11 实测）

```bash
$ python -m pytest -q --cov=heagent --cov-fail-under=87 --cov-report=term
TOTAL                                          12887    865   3506    390    92%
Required test coverage of 87% reached. Total coverage: 91.82%
3057 passed, 11 skipped, 18 deselected, 8 warnings in 189.36s (0:03:09)

$ ruff check src tests            → All checks passed!
$ ruff format --check src tests   → 277 files already formatted
$ mypy src                        → Success: no issues found in 146 source files
$ mypy src --platform linux       → Success: no issues found in 146 source files
$ node tests/js/console_acceptance.mjs
ACCEPTANCE {"rows":18,"failed":0,"workspace":"C:\\Users\\skype\\AppData\\Local\\Temp\\heagent-console-acZEgv","chrome":"Chrome/153.0.8010.48"}
```

覆盖率口径说明（R1 / 脊柱 D7 的实现期校正）：脊柱 §10 与 D7 预判控制台逻辑会拆到独立模块
`cli_console.py` 并「默认不 omit」，但该模块**从未落地** —— 控制台装配全在 `cli_http.py`，
而它**不在** `pyproject.toml` 的 omit 列表里（`omit` 只有 `*/gui/*` 与五个 CLI 交互层文件）⇒ 它计入
上面的总量并由测试覆盖。未新增任何 omit。

### 负向验证（DoD 四条 + 2 条凭证面）

`.heagent/tmp/mutate_50_7.py`，6 条变异全部**精确变红**后复原（每条回退后 sha256 与变异前一致）：

| 变异 | 目标 | 实测 |
|---|---|---|
| ① 网络层 `from heagent import projects` | `tests/test_architecture_contracts.py` | `1 failed`（`test_no_reverse_dependency_on_agent`） |
| ② 往写白名单塞 `KIMI_API_KEY` | 契约 + catalog | `3 failed`（含 `test_write_whitelist_is_a_subset_of_settings_and_holds_no_credentials`） |
| ③ 从 `.env.example` 删一个字段名 | `tests/test_config.py` | `1 failed`（`test_every_settings_field_is_documented_in_env_example`） |
| ④ 把非回环来源判定短路 | e2e + console 测试 | `5 failed`（含本 story 的 T2 用例） |
| ⑤ 面板回传凭证**原值** | e2e + catalog | `5 failed`（含 T3 五面用例） |
| ⑥ 审计写**原值**而非哈希 | e2e + write | `2 failed`（含 T3 审计断言） |

### 已知缺口（如实登记，见 `docs/frame.md` 五 与活动台账）

①网页入口非安全边界（无认证 / 无 TLS）；②全局 `~/.heagent/.env` 永久只读；③配置改动只对下一次 run
生效（无热生效）；④UI 无自动化回归（真浏览器清单只能手动跑）；⑤备份与审计不被工具读取、也无下载端点，
但仍在宿主文件系统上且**未加密**；⑥`cli_console.py` 从未落地（D7 作废，口径随模块走）；
⑦「只读」不是安全边界；⑧**「回环来源」不等于安全**——用户自己浏览器里打开的任意网页 peer 同为
`127.0.0.1`，真正的同源防线是 49-5 的 `Origin`/`Host` 校验；⑨跨项目并发无全局软上限
（在途 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`，默认最多 32；`HTTP_MAX_CONNECTIONS` 不随项目数放大）。
另：**非回环运行姿态未裁决**（项目重命名 / 四个会话写操作 / 项目内运行入口当前无回环门），
台账中标 `blocked` 待人裁决，本 story 未擅自改。

---

<a id="acceptance-50-8-refinement"></a>

## Story 50-8 验收：控制台体验优化（真实浏览器 + 单测 + 负向验证）

> **原文件**：`reviews/acceptance-50-8-refinement.md` ｜ **轮次 / 类型**：验收 · Story 50-8（真实浏览器 + 负向验证） ｜ **日期**：2026-09-24（第四轮复跑 09-25）
>
> （该文档原件无 YAML frontmatter。）


- 日期：2026-09-24
- 驱动：`tests/js/console_acceptance.mjs`（自起**真实** `heagent http-server`——B 段两份额外服务，含 `--dialog-backend none`——+ headless Chrome，CDP 驱动真实点击）
- 环境：Chrome **153.0.8010.48**；`heagent-http` 0.6.2；Windows；工作区 = 临时目录（脚本自动创建，`--keep` 保留）
- 结论：**23 / 23 PASS**（`ACCEPTANCE {"rows":23,"failed":0}`）
  - 首轮追加 A5b / A11b / A11c / B2（18 → 22 行）；
  - **第二轮（用户裁决）追加 A11d**，并把 A11b 的阈值由 20 改为 **10**（22 → 23 行）。
  - **第三轮（用户裁决 R7/R8）重写 A11d 的判据**：由「限宽居中」改为「对话区**占满该列** + 控件在**会话列表之上** +
    三列里**对话列最宽**」（行数仍 23）。新判据第一版当场变红（`{"chat":0,…}`）：`#chat-log` 为空时命中
    `.chat-log:empty{display:none}` ⇒ 它的盒子恒为 0，改量 `.chat` 这一**列容器**才拿到 812px。
  - A11d 另外留下**两张人眼可复核的截图**（`--keep` 时随工作区保留）：`console-a11d-2col-chat-fullwidth.png`
    （两栏：正文铺满该列 + 「显示全部」在列表之上）与 `console-a11d-3col-settings-open.png`（三列：对话列最宽）。
- 复跑：`node tests/js/console_acceptance.mjs --python E:/AI/HeAgent/.venv/Scripts/python.exe`
  （前提：本机有 Chrome/Edge、已装 `heagent[http]`；退出码 1 = 有行失败）

### 清单与实测结果

| # | 步骤（页面） | 期望 | 实测 | 结论 |
|---|---|---|---|---|
| A1 | 首页骨架 + 常驻安全声明 | 两栏骨架、设置入口、安全声明三条事实同时可见 | 两栏 + 设置入口 + 声明常驻可见 | PASS |
| A1b | 首页无阻塞遮罩（计算样式 + 真实命中） | 遮罩 `display:none`、真实鼠标点击落到页面元素 | display=none、0 个盒子、视口中心最上层=LI、真实点击落点=LI | PASS |
| A2 | 无第三方请求 | 全部请求同源 | 7 个请求全部同源 | PASS |
| A3 | 无 console 错误 / CSP 违规 | 0 条 error | 0 条 error（favicon 404 按无害过滤） | PASS |
| A4 | 项目列表渲染 | 服务工作区在列且可用 | default=heagent-console-*（服务工作区），共 1 个 | PASS |
| A5 | 登记项目（真实 POST） | 侧栏与服务端注册表都有该项目 | 两侧都有「验收项目 B」（id=p88d5c44e，共 2 个） | PASS |
| **A5b** | **「选择文件夹…」入口（R2）** | 表单内有服务端原生选择按钮，且与手工输入共存 | 「选择文件夹…」与「登记项目」同表单、`type=button`、带「在服务端机器上打开」说明、手工输入仍可编辑 | **PASS** |
| A6 | 目录失效可见标记 | `available=false` + 「目录已失效」 | available=false + 「目录已失效」徽标 | PASS |
| A7 | 切换项目刷新会话（隔离） | 两侧会话互不可见 | B 的会话 1 个、服务工作区 0 个，无交集 | PASS |
| A8 | 会话持久化 | 刷新后仍在（落盘） | 刷新前后都回到「验收项目 B」且会话为 `15c77c13…` | PASS |
| A9 | 重命名会话 | 标题与磁盘文件同步 | `<sid>.json` 的 `title` = 验收重命名 | PASS |
| A10 | 删除会话（先取消后确认） | 取消不删、确认后文件消失 | 取消保留、确认后文件消失（2 → 1） | PASS |
| A11 | 设置面板（分组 / 来源 / 只读原因） | 分组 + 来源徽标 + 只读原因 + 未知键单列 | 20 组 / 113 条（= 后端 113 字段）/ default+global_env+project_env / 67 个只读项全部给了原因 / 未知键 TOTALLY_UNKNOWN | PASS |
| **A11b** | **会话列表只显示最近 10 条（R1）** | 10+ 会话时只渲染 10 条、显示总数、展开后全部可见 | 用**真实 API** 造到 21 个会话：默认渲染 10 条（「共 21 个会话 · 只显示最近 10 条」），点「显示全部（21）」后 21 条全部可见 | **PASS** |
| **A11c** | **设置面板瘦身（R4）** | 无整句长解释；诊断/未知键默认收起且标题带条数；只读原因是短标签 | 诊断「项目 .env 诊断」与未知键「未知键（1 条，不生效）」默认收起；67 条只读原因均为「只读：…」短标签；面板文本里无「网页无法自行开启」「需在启动配置」 | **PASS** |
| **A11d** | **布局：一列侧栏 + 对话区占满所在列（R6/R7/R8）** | 项目与会话同栏堆叠；对话正文与输入条**铺满该列**（不再限宽居中）；设置面板打开时对话列仍最宽；会话控件在列表之上 | **1600px 视口**下实测：`显示全部` 底边 **687 ≤ 740** 会话列表顶边；设置面板打开时对话 **812px > 设置 508px**；侧栏 `flex/column` 且两个面板同栏堆叠；对话正文 **1288px**（= 该列 1320 − 内边距 16/16）、输入条 **1288px** | **PASS** |
| A12 | 凭证零明文 | 密钥标记不出现在页面/DOM/行内 | 页面/DOM/行内都没有标记；凭证行只有「已配置 ********」 | PASS |
| A13 | 保存配置（确认 → 写入 → 生效时机） | 磁盘出现新值 + 「下一次运行生效」+ 徽标刷新 + 有备份 | 25 → 321（磁盘 + 面板），来源 project_env，备份 1 个 | PASS |
| A14 | 非法值被拒且文件不变 | 可理解文案 + 文件逐字节不变 | 「值不合法：本次没有改动任何文件。服务端说明：MAX_ITERATIONS: must be a number」，文件未变（115 字节） | PASS |
| A15 | 窄屏降级 + 侧栏可收起 | 420px 下侧栏收起、声明仍可见 | sidebar display=none，声明仍可见 | PASS |
| A16 | 截图留档 | 整页截图 | `<workspace>/console.png`（46 KB） | PASS |
| B1 | 闸门关闭：全只读 + 原因 + 无开启入口 | 面板说明闸门关闭、全部可写项不可编辑 | 闸门说明可见（一行短状态）、0 个可编辑控件、可写项原因一致、开关自身只读；**且面板文本无长句** | PASS |
| **B2** | **选择文件夹：不可用路径（R2）** | `--dialog-backend none` 的服务上点击按钮 ⇒ 给原因、不回填、不登记 | 「本机没有可用的图形目录选择器（或服务启动时禁用了它）：请手工填写目录的绝对路径。 服务端说明：directory dialog is disabled (--dialog-backend none)」，输入框未被改动 | **PASS** |

> A16 截图随临时目录删除（`--keep` 才保留）；本报告只留可复跑的**实测结论**。

### 覆盖到哪些 AC（本 story）

| AC | 覆盖方式 |
|---|---|
| AC1 会话列表只显示最近 10 条（可展开、当前会话永远可见） | A11b（真浏览器）+ 探针 P/Q（`tests/js/app_probe.js`，含「当前会话落在窗口外 ⇒ 自动展开且按钮隐藏」）+ `test_http_web_ui.py::TestConsoleRefinement` 两例 |
| AC2 原生目录选择填回路径、取消无副作用 | A5b（入口形态）+ B2（不可用路径端到端）+ 探针 R（成功回填且**不发** `POST /api/projects`、取消文案）+ `tests/network/test_http_console_dialogs.py`（真 console 装配：成功 / 取消 / 503 / 409 / 回环门 / 无副作用） |
| AC3 三种边界（无后端 / 在途 / 非回环） | `TestEndpoint` 6 例 + `TestRealAssembly` 4 例（含「非回环⇒不 spawn」「并发⇒409」）；真机探针见下 |
| AC4 设置面板瘦身但不丢信息 | A11c + B1（真浏览器）+ 探针 S + `test_settings_panel_is_compact_without_losing_reasons` / `test_diagnostics_and_unknown_keys_are_collapsed_by_default` |
| AC5 侧栏一列（项目与会话同栏） | A11d（真浏览器计算样式）+ `test_sidebar_keeps_projects_and_sessions_in_one_column`（含「`display: contents` 不得回来」的护栏）+ A1/A15（收起与窄屏） |
| AC6 无回归 | 全量 3139 passed；A2/A3/A7…A15 全绿 |
| AC7 新错误码有文案 | `test_every_console_error_code_has_a_readable_text`（由 `HttpErrorCode` 枚举派生，**32 → 34 条**）+ `tests/network/test_http_protocol.py` 的码集断言 |
| AC8 文档与台账 | `docs/frame.md` 4.18（+3 行 / 错误码 32→34 / 安全声明段）/ 五（+3 行）/ 七（+1 段）；活动台账 +2 条；`sprint-status.yaml` |
| AC9 网页侧读取结果收敛 | R5 两半的真实装配用例 + 安全用例（内容不进帧 / 模型仍拿到 / 日志也没有）+ 探针 T（格式不变） |
| ~~AC10 ChatGPT 式限宽居中阅读列~~（2026-09-24 第三轮**用户裁决撤销**） | 由 AC11 取代——原 A11d 的「768px 居中」判据同时作废 |
| AC11 对话区**占满该列**（R7） | A11d（**1600px 视口**实测正文 1288px = 该列 1320 − 内边距 16/16、输入条 1288px；设置面板打开时对话 812px > 设置 508px）+ `test_chat_content_fills_the_column` + `test_settings_open_keeps_the_chat_column_the_widest` |
| AC12 会话控件在**列表之上**（R8） | A11d（几何实测 `显示全部` 底边 687 ≤ 列表顶边 740）+ `test_session_scale_controls_sit_at_the_top_of_the_sessions_panel` |

### 真实弹窗：唯一不能自动化的那一步

`file_read` 之外，本 story 唯一新增的宿主面是**真实原生窗口**——「选中并确认」需要人眼与人手，浏览器清单
只能覆盖「按钮存在 / 不可用路径 / 取消或超时」。已做的**真机**验证（一次性探针，会短暂闪窗 ≈2s）：

```
$ .venv\Scripts\python.exe .heagent/tmp/probe_50_8_dialog_real.py
resolve_backend('auto') = tkinter
in_flight(during)=False result=None elapsed=2.0s in_flight(after)=False
stderr: directory dialog timed out after 2s; treated as cancelled
```

即：**后端解析 → 真实拉起 tkinter 子进程（窗口真的出现）→ 2s 超时 → kill + 归还名额 + WARNING** 全链路成立；
`result=None` 是「超时按取消」的既定语义。（`in_flight(during)` 的观测点在调用之前——探针自身顺序问题，
在途语义由 `test_busy_while_another_pick_is_in_flight` 与 `test_cancellation_kills_the_child_and_releases` 覆盖。）

### 负向验证（`.heagent/tmp/mutate_50_8.py`，17 条变异 **17/17 精确变红**）

| # | 变异 | 结果 |
|---|---|---|
| M1 | 去掉选择器端点的回环门 | 2 failed（非回环被拒 + 不 spawn） |
| M2 | 去掉单在途守卫 | 2 failed（并发 ⇒ busy） |
| M3 | 不解析标记行、直接回传 stdout | 2 failed（脏值/无标记用例） |
| M4 | 超时不终止子进程 | 3 failed（kill 断言） |
| M5 | 会话列表不再截断 | 1 failed（探针 P） |
| M6 | 当前会话在窗口外时不自动展开 | 1 failed（探针 Q） |
| M7 | 整句长解释塞回设置面板 | 1 failed（探针 S：`gateText` 必须等于短状态） |
| M8 | 读取结果无内容时不再回显作用对象 | 1 failed（探针 T） |
| M9 | 网页不再对 `file_read` 收敛 | 3 failed（R5 + 日志面） |
| M10 | 连失败消息也收敛 | 1 failed（`Error:` 前缀判据） |
| M11 | 新错误码缺状态码映射 | 2 failed（503 退化成 400） |
| **M12** | **侧栏回退成多栏（`display:contents`）** | **1 failed（一列口径护栏）** |
| **M13** | **对话区把限宽阅读列加回来（撤销 R7）** | **1 failed（`test_chat_content_fills_the_column`）** |
| **M14** | **会话截断阈值回到 20** | **2 failed（探针 P 的「10 条」与自动展开边界）** |
| **M15** | **会话规模/展开控件挪回列表下方（撤销 R8）** | **1 failed（`test_session_scale_controls_sit_at_the_top_of_the_sessions_panel`）** |
| **M16** | **三列份额翻回「设置面板比对话列宽」** | **1 failed（`test_settings_open_keeps_the_chat_column_the_widest`）** |
| **M17** | **输入条也加上限宽（与正文不同宽）** | **1 failed（`.composer > *` 不得有 `max-width`）** |

每条变异写完即用**原始 bytes** 还原并复核 sha256（脚本内置断言）。

### 质量门（实测）

```bash
$ .venv\Scripts\python.exe -m pytest -q --cov=heagent --cov-fail-under=87 --cov-report=term --no-header -p no:randomly
TOTAL                                          13041    868   3546    391    92%
Required test coverage of 87% reached. Total coverage: 91.88%
3139 passed, 11 skipped, 18 deselected, 8 warnings in 169.73s (0:02:49)

$ .venv\Scripts\python.exe -m pytest tests/test_cli_dialogs.py tests/network/test_http_console_dialogs.py -q --cov=heagent.cli_dialogs
src\heagent\cli_dialogs.py     113      6     34      2    93%   108-110, 123, 127, 165
43 passed in 0.68s

$ .venv\Scripts\python.exe -m ruff check src tests          → All checks passed!
$ .venv\Scripts\python.exe -m ruff format --check src tests  → 280 files already formatted
$ .venv\Scripts\python.exe -m mypy src                       → Success: no issues found in 147 source files
$ .venv\Scripts\python.exe -m mypy src --platform linux      → Success: no issues found in 147 source files
$ .venv\Scripts\python.exe -m heagent http-server --help | findstr dialog-backend
  --dialog-backend [auto|tkinter|powershell|none]

$ node tests/js/console_acceptance.mjs --python E:/AI/HeAgent/.venv/Scripts/python.exe
ACCEPTANCE {"rows":23,"failed":0,"workspace":"…\\heagent-console-T5HOUf","chrome":"Chrome/153.0.8010.48"}

$ .venv\Scripts\python.exe .heagent/tmp/mutate_50_8.py
合计 17 条变异，未变红 0 条：[]
```

> 上一轮（第二轮）的对应数字为 `3137 passed / 91.88%`、真浏览器 23/23、变异 14/14；本轮把 U/I 判据改向
> （R7 撤销限宽、R8 控件置顶）后复跑，数字如上。

### 第四轮复跑（2026-09-25，Story 50-8 R9）

用户看过第三轮结果后又给了两条：①「"只看最近10条"，排版修改，共195个会话显示在它下面」②「"只读：未开启配置
写入"不用显示，显示在项目的后面，不独立占一行」。改动只落在**版面**上（无新端点、无新错误码），清单**加严后复跑**：

| 行 | 第三轮 | 第四轮（R9） |
|---|---|---|
| **A11b** 会话列表截断 | 只断言文案与条数 | **加真实几何判据**：展开按钮必须**单行**（内容盒高 ÷ 行高 ≤ 1.5）、右边界不得越出会话面板、规模提示必须在按钮**下面**。实测「按钮 36px/单行、提示在其下 6px」 |
| **B1** 闸门关闭 | 断言「面板含一句 `只读：未开启配置写入`」+ 逐项原因一致 | 断言**徽标在项目名之后且同一行**（`getBoundingClientRect` 比较）、可见文案 = `只读`、`title` 含 `未开启配置写入` + `HTTP_CONSOLE_WRITE_ENABLED`、**可写项 `.config-reason` 计数 = 0**、保存禁用、0 个可编辑控件、开关自身无输入框 |

```bash
$ node tests/js/console_acceptance.mjs --port 8922 --python E:/AI/HeAgent/.venv/Scripts/python.exe
ACCEPTANCE {"rows":23,"failed":0,"workspace":"…\\heagent-console-f61eX3","chrome":"Chrome/153.0.8010.48"}
# A11b：共 21 个会话：默认渲染 10 条（「共 21 个会话 · 只显示最近 10 条」），展开后 21 条全部可见；按钮 36px/单行、提示在其下 6px
# B1  ：项目名后「只读」徽标（title 含完整原因）、0 个可编辑控件、46 个可写项无逐项重复、开关自身只读（无输入框）
# A11 ：20 组 / 113 条 / 67 个只读项全部给了原因（113 → 67：可写项不再逐项铺同一句）

$ node tests/js/console_acceptance.mjs --port 8919      # 负向：先把会话控件 revert 回并排（M18）
ACCEPTANCE {"rows":23,"failed":1,…}
# A11b 精确变红：「规模提示必须在展开按钮**下面**（R9）：{…,"stacked":false,"gap":-28}」

$ .venv\Scripts\python.exe .heagent/tmp/mutate_50_8.py
合计 22 条变异，未变红 0 条：[]      # 原 17 条 + R9 的 M18–M22（22/22 全红）
```

> 另一条**只有真浏览器能看见**的缺陷也在这轮被抓到：并排布局下 `.status`（`white-space: nowrap`，不可收缩）
> 会把展开按钮挤成 **87×83px / 三行**、右边界 **308px 越过 280px 侧栏**——单测/字符串断言对此完全无感，
> 所以 A11b 的判据从此包含**几何**。195 个会话的真机几何数据见 story 第四轮记录。

#### R10（同批第二条）：值跟在键名后面（A11 加几何判据）

同一批反馈的第二条是「配置项的值不要另起一行」（`DEEPSEEK_MODEL` 的值跟在键名后面）。改动只在
`app.js::renderConfigItem`（`.config-value` 由 `<p>` 降为 `.config-head` 内的 `<span>`，类名保留），
清单里给 **A11** 加了一条**几何**判据——键与值的 rect 必须纵向重叠且值在键右侧：

```bash
$ node tests/js/console_acceptance.mjs --port 8923 --python E:/AI/HeAgent/.venv/Scripts/python.exe
ACCEPTANCE {"rows":23,"failed":0,"workspace":"…\\heagent-console-JIb9dS","chrome":"Chrome/153.0.8010.48"}
# A11：20 组 / 113 条（= 后端 113 字段）/ default+global_env+project_env / 67 个只读项全部给了原因 /
#      未知键 TOTALLY_UNKNOWN / 值内联（键 y=1829、值 y=1830）

$ .venv\Scripts\python.exe -m pytest tests/test_http_web_ui.py -q     → 137 passed
$ .venv\Scripts\python.exe .heagent/tmp/mutate_50_8.py
合计 23 条变异，未变红 0 条：[]      # +M23「值退回另起一行的 <p>」精确变红
```

### 已知缺口（同时登记在 `docs/frame.md` 五 与活动台账）

1. **网页请求可拉起宿主 GUI 进程**（本 story 有意引入的新暴露面）：回环门 + 单在途 + 冻结 argv + 超时都
   只是 defense-in-depth；回环 peer ≠ 可信，能连上端口的本机进程都能让服务机弹窗。
2. **不可用环境**：无图形后端 / 服务在远程机器 / `--dialog-backend none` ⇒ 一律 `dialog_unavailable` + 保留手工输入；
   不做服务端目录浏览 API（那会把宿主目录结构开放给回环客户端）。
3. **真实弹窗的那一步无法自动化**（见上）；`tkinter` 冻结脚本在 CI 里永不执行，只钉「能编译」。
4. **`Error:` 前缀判据是展示层启发式**：内置工具用返回值表达可预期失败，若将来改结构化错误，该判据应退化为只看 `is_error`。
5. 既有缺口未变：浏览器验收不进 CI、无真实 LLM 运行的浏览器验收（Z-D15 同处）、非回环运行姿态（blocked）。

---

*以上 3 份为验收记录（Story 50-6 / 50-7 / 50-8）。*

> **合并校验（脚本产出时实测）**：8 份文档的正文（frontmatter 之后全部内容）经上述两处机械处理后，以**逐字子串**形式各命中一次于本文件；字符数守恒（各章正文长度之和 + 生成的骨架 = 本文件长度）。
> 校验脚本：`.heagent/tmp/rev_merge.py`（生成）· `.heagent/tmp/rev_verify.py`（回读复核）。
