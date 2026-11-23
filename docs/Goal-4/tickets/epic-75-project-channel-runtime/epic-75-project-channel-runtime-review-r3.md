---
type: review
code: E75-R3
epic: epic-75-project-channel-runtime
review_loop_iteration: 1
lens: 三镜头对抗式（技能 code_review：对抗式 / 边界追踪 / 验证缺口）
reviewed_at: 2026-11-23
head: da29790d
---

# E75 收口三审 · R3 三镜头对抗式评审

## 评审范围

- diff 范围：已提交 `604b4fb4..HEAD`（32 文件 / +2411 −74）**加**评审当时的工作树（R1/R2 落改 8 文件）。
- 覆盖 story：75.1–75.6 全部（六份 plan 均 `status: built`）。
- 评者实跑：`pytest` 受影响面 125 passed / `tests/network` 706 passed / `pytest tests/test_projects.py tests/test_contract_baselines.py tests/test_docs_links.py` 24 passed /
  `contract_snapshot.py --check` 五份 `[OK]` / `--cov` 两处（`pub.projects` 90%、`cli.ws_project_adapter` 100%）/ 12 个一次性探针（`.heagent/tmp/r3/`）。
- **不采信** plan、R1、R2 的结论，只把它们用于「哪些缺口已被登记」的核对。

## 镜头一 · 对抗式（15 条）

| # | 严重度 | 位置 | 问题 | 处置 |
|---|---|---|---|---|
| 1 | **high** | `epic…md:45`（Boundaries）vs 交付的帧/命令/码面扩张 | Boundaries 写「不改帧定义与错误码」，交付新增帧类型 + 命令 + 码 + 两模型 + 端口方法（架构 AD 授权）⇒ 契约文本两侧相反，且 epic Notes 无裁定 | **落改**：epic Notes 记 `H-1` 规格缺陷 + KEEP 指令（以 spine 为准，Requirements/Boundaries 冻结不改） |
| 2 | **high** | 架构 `AD-8`（「只读 listener 上 `projects` 允许」）vs `§4.1`（「单 run / CLI 旁路 / 通知流一律 `invalid_request`」）+ 只读 listener 不注册集合级端点 | spine 自相矛盾 ⇒ 只读 listener 上 `projects` 零可达路径，实现落到的正是 AD-8 的**被拒替代 (a)**；该缺口未进延期项 | **落改**：epic Notes 记 `H-2` 裁定（按 §4.1 + E74 端点集落地，不改实现）+ `brief.md` 延期项标记「需用户裁决」（新增只读端点形态属结构扩张） |
| 3 | medium | `ws_project_adapter.py:80/95` | 守卫放两处 ⇒ 一次提交读注册表 4 次；且守卫读与 console `find` 读之间窗口仍开（那时损坏仍译成 `unknown_project`） | 延期（R2 M-1 同根；窗口收窄不闭合） |
| 4 | medium | `ws_project_adapter.py:66-76` | 注册表坏时 `project_id="default"` 也被拒，而 `find("default")` 根本不读注册表 ⇒ WS 面独有可用性回归 | **落改**：`_guard_registry(project_id)` 对 `default` 豁免 + 两方法参数化用例 |
| 5 | medium | `ws_commands.py:234` + `ws_server.py:184` | 提交成功但 ack 丢失 ⇒ run 孤儿、客户端拿不到 `run_id`、日志不记 `run_id`、重试得 `run_conflict` | 延期（探针证实；端口 docstring 的「无原子性保证」需补这一条） |
| 6 | medium | `pub/projects.py` 告警复位点 | R2 的复位只覆盖「修好文件」，**删文件**（`app.js` 明示的运维动作）不复位 `_CONTENT_CORRUPT` ⇒ 再坏静默 | **落改**：文件不存在时连内容成因一并复位 + `test_deleting_the_corrupt_file_also_rearms_the_warning` |
| 7 | medium | `ws_protocol.py` 两个帧模型 | AD §4.2 的三处界未实现：`name` 无 1–64、`projects` 无 `max_length=32`、`registry_state` 无默认 `ok` | **落改**：三处按 AD 补齐 + `test_projects_frame_carries_the_architecture_bounds` |
| 8 | medium | `pub/projects.py:_parse`（`> MAX_PROJECTS`）↔ `ProjectListResponse(max_length=32)` | 手改成 32 条登记 ⇒ `list()` 回 33 条 ⇒ `projects` 命令 `server_error` + **close 1011**，而 `health()` 同时说 `ok` | **落改**：登记上限改 `>= MAX_PROJECTS`（= 可登记 31 条，与 `register()` 同源）+ 三例（31 / 32 / 33） |
| 9 | medium | `ws_project_adapter.py` 探针注入面 | 探针抛异常 ⇒ 断连；返回非两值 ⇒ 列表径 `ValidationError` 断连、提交径当 `unreadable` 拒（同处误配两种结局） | 延期（注入面误配属装配错，两端都「响亮」；收窄留 E76） |
| 10 | medium | `ws_project_adapter.list_projects` | `projects` 与 `registry_state` 非同源快照（两次独立读） | 延期（R1 M-1 同根） |
| 11 | low | `pub/projects.py:detail` | `detail` 生产侧零消费者却进了 `__all__` 与契约基线 | 延期（接进日志或收回导出面，择一） |
| 12 | low | `cli/http.py:_project_channel` + 无节流 | 每帧 2 次读盘 + ≤32 次 `is_dir`，走进程级共享线程池；`lan` 档无认证可达 | 延期（E76 并发面） |
| 13 | low | `ws_commands.py:195-199` | `projects` 分支只兜 `HttpRunConflictError`，其它异常断连（纯读命令断连代价与 `run` 不对等） | 延期（与 `run` 同档是刻意） |
| 14 | low | `cli/http.py:474` | `HTTP_ENABLED=false` 时 console 仍被构造 ⇒ 为一个不存在的端口打「配置写通道已开启」告警 | 延期（探针证实；惰性化留 E76） |
| 15 | low | `ws_commands.py:79` | docstring 仍写「三条命令」，同函数已加第四个拒绝分支 | **落改**（文案） |

## 镜头二 · 边界追踪（12 条，摘要）

| # | 边界 | 结论 |
|---|---|---|
| B1 | `project_id` = `""` / 17 字符 / `null` | `malformed` / `malformed` / 走旧路径；有测试 |
| B2 | 注册表不存在 | 帧 = `[default]` + `ok`；不崩 |
| B3 | **恰 32 条登记** | 修前：`server_error` + close 1011（且 `health=ok`）⇒ **已落改**（判整表不可读，fail-soft 回 `default`）；三例已补 |
| B4 | 33 条登记 | 判不可读、整表回 `default`（既有 fail-soft 语义，README/文档已写） |
| B5 | 目录 / 非 UTF-8 / 坏 JSON / BOM | 均 `unreadable`；**非 UTF-8 与 schema 不符两分支原先零覆盖 ⇒ 已补两例** |
| B6 | 两客户端并发提交同一项目 | 回 `run_conflict`（会话级），而 `docs/errors.md` 把同场景写成 `project_busy` ⇒ 延期（文档口径） |
| B7 | 提交成功但 ack 丢失 | 孤儿 run + 客户端拿不到 `run_id` ⇒ 延期（见镜头一#5） |
| B8 | 端口抛非契约异常 | 提交分支有判据；`projects` 分支无 ⇒ 延期 |
| B9 | 超时 / 取消 | 端口无 `timeout` 兜底 = 实现方义务（docstring 有 grep 判据，行为无判据）⇒ 延期 |
| B10 | 只读 listener 发 `projects` | 端点不存在，客户端见框架级拒绝 ⇒ **H-2**（见镜头一#2） |
| B11 | `registry_state` 注入非法值 | 两结局不一致 ⇒ 延期（见镜头一#9） |
| B12 | 时间戳时区混合排序 | `sort(key=last_opened_at)` 是字符串序 ⇒ 手改文件才触发 ⇒ 延期 |

## 镜头三 · 验证缺口（11 条，摘要）

| # | 严重度 | 缺口 | 处置 |
|---|---|---|---|
| V1 | medium | R7 的 7 码里 4 个在**提交链**无生产来源（`project_busy` 只由删项目端点产生等），桩用例证明的是转译层 | **部分落改**：`test_ws_project_submit.py` 头部写明「本节证明转译层、生产来源由 adapter 真注册表用例钉住」；码表重写留 E76 |
| V2 | low | `_read_failure_detail` 的 `UnicodeError` 与 `_corrupt_detail` 的 `ValidationError` 分支零覆盖 | **落改**：两例（非 UTF-8 字节 / 条目缺字段） |
| V3 | medium | R1「32 上限可判定」只验在安全侧（31 条） | **落改**：31 / 32 / 33 三点各一例 |
| V4 | medium | 帧类型封闭集在**同一提交里**从 5→6 放宽，放宽理由只在 story plan 里 | **落改**（并入 H-1 的 Notes 裁定 + KEEP） |
| V5 | medium | R3 六项落点 / R6 单源 / R7 装配缺**端到端**（真 listener）判据 | 延期（R1 M-2 → E76-S05） |
| V6 | low | `_http_listener_for(console=None)` 的回退分支零调用 | 延期 |
| V7 | low | 接线用例断言私有属性 `adapter._console` | 登记（可接受形态） |
| V8 | low | 「适配器不碰盘」守卫是字符串白名单 + 属性集，`open` / `read_text` / 别名不在禁列 | 延期（改 AST 白名单） |
| V9 | low | 端口「超时是实现方义务」只有 docstring 判据 | 登记（刻意） |
| V10 | low | `_project_channel` 闭包仍零直调 | 延期（R2 M-2 顺延） |
| V11 | low | 新分支（`default` 豁免、ack 丢失、`readonly` 下的 `projects`）零用例 | **部分落改**（`default` 豁免已补两例）；其余随延期项 |

## 处置汇总

- 严重度：**high 2** / medium 10 / low 15。
- **当轮落改 8 处**：H-1（epic Notes 裁定）、H-2（epic Notes 裁定 + 延期项标记待用户裁决）、
  `default` 豁免 + 2 例、告警「删文件也复位」+ 1 例、帧界三处 + 1 例、登记上限 32→31 + 3 例、
  非 UTF-8 / schema 两例、`ws_commands` docstring、桩用例口径声明、`framework.md` 两处口径。
- **延期 12 条**（落 `brief.md`「延期项」，逐条带来源轮次与建议处置），其中 1 条标记**需用户裁决**
  （只读 listener 是否要有项目清单）。
- 无未处置的 Critical / High：两条 high 均已按「规格缺陷记录 + KEEP」落盘，且**不改冻结段、不改 E74 端点集**。

## 结论

**放行**（两条 high 已按规格缺陷记录处置并在 epic Notes 与延期项留证；落改后门禁全绿：
`829 passed` / ruff / format / mypy / bandit / `mkdocs --strict` 0 warning / 契约基线五份 `[OK]`）。
