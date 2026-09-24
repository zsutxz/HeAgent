---
scope: Epic 50 网页控制台周期 · 规划产物（brief / epics / ARCHITECTURE-SPINE / 7 份 story）
review_type: adversarial-planning-review
review_loop_iteration: 1
date: 2026-09-24
reviewer_stance: 对抗式（不采信产物自述，结论只来自亲自读过的文件与亲自跑过的命令）
---

# Epic 50 规划评审报告（三镜头）

## 评审范围

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

## 镜头一：对抗式（12 条）

### F1 — 写流水线缺「系统环境变量覆盖 ⇒ 不可写」检查　**high**　`bad_spec` → 已就地修复

- **位置**：`ARCHITECTURE-SPINE.md` §8 流水线第 3 步（原） / `50-5` AC4 邻域
- **证据**：探针实测——候选文件含 `MAX_ITERATIONS=abc` 且系统 env 提供 `MAX_ITERATIONS=5` 时，
  `Settings(_env_file=候选)` **不抛异常**（env 优先级更高，候选值根本没被解析）。
  而 §8 原第 3 步只查「在白名单内」，**没有任何一步**检查「该键是否被系统 env 提供」；
  50-4 只在**读**侧标 `writable=false`。⇒ 写通道会接受一个「面板显示只读」的键，
  写进去的是**当下无效、日后生效**的坏值（用户哪天 unset 该 env，进程起不来）。
- **处置**：§8 第 3 步改为「必须在显式白名单内**且不得被系统环境变量提供**（与 50-4 的 `writable=false`
  同一求解器、同一常量，不得只在 UI 层拦）」；新增 `50-5` **AC12** 与 T9 测试项。

### F2 — 传 `session` 会顺带在 HTTP 进程内构造 `CronScheduler`　**medium**　`patch` → 已就地修复

- **位置**：`cli.py:229`（`if session is not None and config.cron_enabled and cron_store:`）→ `cli.py:246`（构造 <code>CronScheduler</code>）
- **证据**：今日 HTTP 侧「无后台调度」**是因为 `session=None` 才偶然成立**（`cli_http.py:207-214`）；
  50-3 T6 要求把 `SessionStore` 传进 `_build_loop` ⇒ 每次 `new_loop()` 都会构造一个 `CronScheduler`
  （`new_loop` 丢弃返回值，`__init__` 无副作用，但**没有任何守卫或测试**保证它不被启动）。
  与 49-5 已确立的「不装 stdin 审批、不连 MCP」立场同源，却缺少对应条款。
- **处置**：50-3 T6 增硬要求 + 测试断言；Never 列表新增「不在 HTTP 进程内构造/启动后台执行」。

### F3 — `WorkspacePaths.projects_file` 作用域错配（项目级类型承载服务级路径）　**medium**　`patch` → 已就地修复

- **位置**：`ARCHITECTURE-SPINE.md` §3.1（`projects_file = console_dir/"projects.json"`）vs §4（「落点 = `<服务启动工作区>/.heagent/console/projects.json`」）；`50-1` T1 把 `projects_file` 列入 `WorkspacePaths`
- **证据**：`WorkspacePaths` 是**项目级**的；对已登记项目 `P`，`WorkspacePaths(P.root).projects_file`
  ⇒ `P/.heagent/console/projects.json`，即**每个项目一个注册表**。任何按「项目 → WorkspacePaths → 注册表」
  的写法都会读到空注册表或写出分叉数据。
- **处置**：§3.1 新增「作用域警告」：注册表路径**只能**由控制台从启动工作区 + 覆盖解析一次，
  禁止从任意项目的 `WorkspacePaths` 取，须配测试。

### F4 — 跨项目并发被「顺带」放开，与 brief §5 冲突　**medium**　`intent_gap` → **blocked，交人裁决**

- **位置**：§6（每项目一个 `HttpRunService`，持有「在途名额」）vs `brief` §5（「扩大跨项目并发运行能力」不在本周期）
- **证据**：`max_inflight_runs` 是 **service 级**（`network/http_server.py:150`、`:386` 用 `self.config`），
  每项目一个 service ⇒ 总并发 = 项目数 × 1；即「A 在跑时 B 也能起跑」。brief 明写「沿用既有运行限额，
  多项目切换不等于并行运行」。
**已裁决（2026-09-24，选 **b**）→ 关闭**：采纳「并发随项目数线性增长」。
处置：`intent_gap` → **已转 D9 并落地**（脊柱 §6 新增「并发口径」、§12 改写、§15 决策登记表新增 D9 行；
`brief` §5 该行作废并标注；`epics.md` Additional Requirements 增并发语义条目；50-2 T4 / 50-3 T9 / 50-7 T10⑨ 同步）。
已知缺口如实登记：无全局并发软上限、`HTTP_MAX_CONNECTIONS` 不随项目数放大。

### F5 — 失败/取消的 run 也写会话文件，与 49-3「失败不投影」形成双口径　**medium**　`patch` → 已就地修复

- **位置**：`agent/run_lifecycle.py:324-350`（`persist_and_cache` 在 finally 里 `if loop.session and session_id: save(...)`）
- **证据**：进程内投影只在 `COMPLETED` 时写历史（49-3 AD-3「失败不投影」），而文件侧**成功/失败/取消都落盘**
  ⇒ 同一段对话在 `/api/session` 与会话文件里给出**两个答案**，UI 若各取一半就会自相矛盾。
- **处置**：50-3 新增 **T9b** + **AC10**（必须显式定义失败/取消是否算对话的一部分，且同一页面只用一种口径）。

### F6 — BOM 的 `.env` 让首个键静默失效（读 + 写两侧）　**medium**　`patch` → 已就地修复

- **位置**：50-4 读路径 / 50-5 `envfile.parse_index`
- **证据**：探针实测——带 BOM 的 `.env` 经 `DotEnvSettingsSource` 返回键 `'\ufeffmax_iterations'`，
  `Settings` 因而回落到默认值（文件写 123 → 实际 50），**无任何告警**；写侧若按行取键名，
  首键会定位不到 ⇒ 追加一条重复行（死行）。这与 2026-09-23 刚修过的 frontmatter / MEMORY.md **BOM 缺陷族同源**。
- **处置**：50-4 增 **T9b** + **AC12**；50-5 T1 增 BOM 剥离要求 + **AC11**（首行须替换而非追加，BOM 保留）。

### F7 — 全局 `run_id → project` 索引无上限与回收　**low**　`patch`（记入 story）

- **位置**：§5.1 / 50-3 T9；NFR-11 要求「有界」
- **处置**：记入 50-3 **R4**，要求定义淘汰口径（与既有 run 保留期同源）并配测试。

### F8 — 运行落盘是否传 `expected_version` 未定义　**low-medium**　`patch`（记入 story）

- **位置**：50-3 T1（`save(..., expected_version=None)` 默认 = 现状）
- **证据**：若仅 PATCH/DELETE 传期望版本、**运行落盘不传**，则同一会话的两个并发 run 交替写仍可能
  互相覆盖内容（文件不损坏，但**丢消息**）。
- **处置**：记入 50-3 **R5**，要求明确并覆盖「两写者交替」测试。

### F9 — 「回环来源」不防用户自己浏览器里的跨站写入　**low**　`patch`（记入文档义务）

- **位置**：§9 / 50-5 T4（用 `is_loopback_host(request.client.host)`）
- **证据**：用户浏览器访问的任意网页，其到 `127.0.0.1:8766` 的 peer 也是 `127.0.0.1` ⇒ 回环门**不构成防护**；
  真正的防线是 49-5 的 Origin/Host 校验。
- **处置**：记入 50-7 T10 ⑧（已知缺口声明），避免「回环 = 可信」错觉。

### F10 — 注册表无长度上限（NFR-11）　**low**　`patch` → 已就地修复

- **位置**：50-2 T4（原只写条目数上限）
- **处置**：T4 增显示名（≤64）与路径（≤4096）显式校验。

### F11 — 项目移除无服务端确认（与会话删除不对称）　**low**　`patch` → 已就地修复

- **位置**：§5.2 `DELETE /api/projects/{id}` / 50-2 AC6 vs 50-3 会话删除要求 `?confirm=true`
- **处置**：§5.2 与 50-2 AC6 统一为「缺 `?confirm=true` → `confirm_required`」（危险操作的确认放服务端，不只靠 UI）。

### F12 — 18 个新错误码无「全部可达」断言　**low**　`reject`

- 判断：各码由对应 story 的 AC 分别覆盖；「可达性总表」属噪声，非可执行主张。

## 镜头二：边界追踪（7 条）

| # | 边界 | 结论 | 严重度 | 处置 |
|---|---|---|---|---|
| E1 | `.env` 为**空文件** | 来源层返回 0 键 → 全字段落 `default` ✓（AC7 覆盖「不存在/不可读」） | — | reject |
| E2 | `.env` 是**目录** | `is_file()` 探测可挡住（50-4 T3）✓ | low | defer（DoD 未单列，实现时顺手断言） |
| E3 | `.env` **只读**（ACL/permission） | 写入会失败 → 50-5 AC8「回读失败自动恢复」覆盖；但**权限位继承**未验证 | low | 已记录于 50-5 R2 |
| E4 | 重复键 / 行内注释 / 无末行换行 / CRLF | §7 坑 5/6 + 50-5 T10 四变体保真断言 ✓ | — | reject |
| E5 | 会话 JSON 缺 `messages` | `data.get("messages", [])` ✓（`context/session.py:137`） | — | reject |
| E6 | 会话文件损坏 | D1 已裁定 `session_unreadable` + AC9 ✓ | — | reject |
| E7 | **超长输入**（项目路径 / 显示名 / session id） | session id 有既有守卫 ✓；项目路径与显示名原**无上限** | low | patch（= F10） |

## 镜头三：验证缺口（6 条）

| # | 缺口 | 严重度 | 处置 |
|---|---|---|---|
| V1 | **50-4 AC11（返回守卫约束）无对应任务**，且 `ConfigItem` 字段表没有承载字段 ⇒ AC 不可实现 | medium | patch → T1 增 `guards` 字段（已就地修复） |
| V2 | 50-2 AC6 的 `project_busy` 需 50-3 的索引（**story 前向依赖**，BMAD step-03 明令禁止） | low | reject（已记录于 50-2 R2，端到端断言归 50-3/50-7） |
| V3 | 「BOM 读路径」无测试 | medium | patch（= F6） |
| V4 | 「系统 env 覆盖的键被写」无测试 | medium | patch（= F1） |
| V5 | 手工浏览器验收无 CI 覆盖 | low | reject（50-6 R2 / 50-7 T10④ 已如实登记） |
| V6 | `.env` 权限位继承未验证 | low | defer（50-5 R2 已登记为待核实） |

## 处置汇总

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

## 结论

**放行（阻塞项已关闭）**：唯一阻塞 F4（跨项目并发语义）已于 2026-09-24 裁决为 **(b) 并发随项目数线性增长**，
并已转为 **D9** 落地（脊柱 §6/§12/§15、brief §5、epics.md、50-2 T4、50-3 T9、50-7 T10⑨）。
其余发现已在本次评审内就地修复或登记到对应 story 的「风险与未决」。

可进入 50-1 实现。`review_loop_iteration = 1`（未超回环上限 5）。
