---
epic: epic-75-project-channel-runtime
code: E75
date: 2026-11-23
verdict: accepted-with-open-items
criteria: declared
headless: false
---

# E75 · WS 远程项目通道：项目链运行时与投影注入 — Retrospective

## Epic 摘要

- **Epic**：`epic-75-project-channel-runtime`（Requirements R1–R7），2026-11-23 构建 → 同日六条 entry 全部 `built` → 三审 + 回顾收口。
- **Tickets**（构建顺序 = 票树表序）：

| ref | 标题 | 状态 | 提交 |
|---|---|---|---|
| 75.1 | E75-S01 · 注册表健康探针与项目错误码 | built | `0de2a1c3` |
| 75.2 | E75-S02 · `network` 侧项目通道端口与 `project_id` 提交分支 | built | `a38c58a7`（基线批 `745b251a`） |
| 75.3 | E75-S03 · `cli/ws_project_adapter.py` 帧转译单源 | built | `c232181b` |
| 75.4 | E75-S04 · 控制台编排：六项落点与会话续接/新建 | built | `63cd3528` |
| 75.5 | E75-S05 · 装配注入：`build_ws_servers` 透传与两处注入 | built | `e9d6bfd4` |
| 75.6 | E75-S06 · 契约基线与文档收口 | built | `84d55eb5` |

- **交付形态**：新建 `cli/ws_project_adapter.py`（77 → 96 行）；`pub/projects.py` +110（`health()` / `_read_raw()` / 告警去重 / 登记上限收紧）；`network/{ws_protocol,ws_commands,ws_host,ws_server}.py` 扩命令面与注入缝；新增/扩写测试 6 个文件约 900 行；契约基线五份与 `docs/{framework,errors}.md` 同批收口。
- **证据面**：六份 plan 各带 `## Verification` + 宿主实测数字；三份三审报告 + 本回顾齐备；每轮落改后重跑门禁。

## 三审记录

| 轮次 | 结论 | 发现计数 | 落改去向 |
|---|---|---|---|
| **R1** 规格与实现对账（`bmad-code-review` 镜头） | 有条件的通过 | Critical 0 / **High 1** / Medium 4 / Low 7 | **High-1 当轮落改**：R5 的「提交径 fail-loud 回 `project_registry_unreadable`」**无生产来源**（注册表坏 ⇒ `find()` fail-soft ⇒ `unknown_project`，正是架构文档的被拒替代 (c)）⇒ 适配器加 `_guard_registry` + 真注册表两例；M-2/M-3 半步落改（探针进线程池、真注册表顺序与 31 条上限判据）；M-4（WS 端到端六项落点）、L-1/L-2 等 6 条进 `brief.md` 延期项 |
| **R2** 不变量与守卫反脆弱（宿主自扫 + 三条注入反证） | 有条件的通过 | Critical 0 / High 0 / Medium 3 / Low 4 | **Medium-1 当轮落改**：告警去重集只增不减 ⇒ 注册表修好后再坏**完全静默**（fail-loud 在第二次故障失效）⇒ 按故障期复位 + 新用例；M-2/M-3 与 3 条 Low 进延期项；三条守卫反证（命令集封闭 / `network` 无 `is_dir` / 新健康守卫）全部「红 → 复原 → 绿」 |
| **R3** 三镜头对抗式（`code_review`：对抗式 15 / 边界 12 / 验证缺口 11） | 放行 | Critical 0 / **High 2** / Medium 10 / Low 15 | **两条 High 均为「规格文本 vs 实现/架构」矛盾**，按规格缺陷记录落改（不改冻结段、不改 E74 端点集）：H-1 = epic Boundaries「不改帧定义与错误码」与 AD 授权的新增帧/命令/码相反；H-2 = 架构 AD-8「只读 listener 上 `projects` 允许」与 §4.1 + E74 端点集矛盾（只读 listener 上零可达，属结构扩张 ⇒ 标记**需用户裁决**）；Medium/Low 落改 6 处（`default` 豁免健康守卫、告警「删文件也复位」、帧界三处按 AD §4.2、登记上限 32 → 31 消除 33 条溢出断连、非 UTF-8 与 schema 两分支补判据、`ws_commands` docstring） |

- **落改后的门禁实测**：`pytest tests/network tests/test_architecture_contracts.py tests/test_ws_project_adapter.py tests/test_project_registry_health.py tests/test_http_console_project_run.py tests/test_cli_http_lifecycle.py tests/test_projects.py tests/test_contract_baselines.py tests/test_docs_links.py -q` = **829 passed, 1 warning**；`ruff check` / `ruff format --check`（504 files）/ `mypy src`（240 files）/ `bandit -r src/ -ll` 全绿；`mkdocs build --strict` 0 warning；`contract_snapshot.py --check` 五份 `[OK]`。
- **R3 的两条 high 为什么不是「改实现」**：两条都不是代码缺陷，而是**文本自相矛盾**（epic Boundaries vs 架构 AD；架构 AD-8 vs §4.1/E74 端点集）。改实现的代价分别是「拒绝架构已授权的帧面扩张」与「破 E74 冻结的 4 端点封闭集」——都比改口径贵，且都会引入新回归面。故按 `code_review` 的 `bad_spec` 处置：写规格缺陷记录（触发发现 / 应改条目 / 避免的坏态 / KEEP），不改冻结段。

## 关键判断与 Decision

- **`project_registry_unreadable` 的落点选在入口层适配器，不在注册表**：注册表的读路径刻意保持 fail-soft（不可读 ⇒ 空表，脊柱 §4：不阻断 HTTP 服务），改它会把网页控制台的既有语义一起改掉（NG12）。适配器是「最后一次能分清『服务端坏了』与『项目不存在』」的位置，且它对同一条 listener 的两个端点只注入一次。
- **`default` 必须豁免健康守卫**：`find("default")` 由句柄的启动工作区直接合成、根本不读注册表。让「登记表被改坏」升级成「整个服务不可用」，是比原缺口更坏的取舍——而同一条帧里 `default` 仍是 `available=true`，客户端会看到自相矛盾的状态。
- **登记上限从「32 条登记」收紧到「31 条登记 + default」**：`register()` 早就按 `MAX_PROJECTS - 1` 拒绝，`_parse` 却允许 32 条存量 ⇒ 手改文件时 `list()` 回 33 条，撞 `ProjectListResponse(max_length=32)`，`projects` 命令 500 + 断连而 `health()` 说 `ok`。两侧口径对齐到**同一个总数**才是可判定的上限。
- **帧面自带上下界，不靠上游「恰好有界」**：架构 AD §4.2 写了 `name` 1–64 / `projects` ≤ 32 / `registry_state` 默认 `ok`，实现当初只写了裸类型。帧模型是客户端契约，界写在帧上才能在越界时给出 `ValidationError` 而不是把脏数据发给对端。
- **告警去重的正确语义是「按故障期」而不是「按句柄终身」**：一次不可读 = 一条 WARNING 必须同时满足「不刷屏」与「第二次故障要有声音」。R2 只修了「改好文件」那条恢复路径，R3 指出「删文件」（`app.js` 明示的运维动作）同样算恢复。
- **写集溢出两处一律追认、不重切**：75.1 的四条扩写（含 `pipeline.py` 的状态表、`web/app.js` 的文案）与 75.5 的 `network/ws_host.py` +10 行都是「不写就无法交付」的必需项；票面把它们错记在别的文件上（75.5 甚至把端点构造误记在 `build_ws_servers` 名下）。追认记录进 plan 的宿主复核节与 epic Notes，不回头重切冻结票面。

## 遗留（转下游 entry / 用户裁决，详见 `docs/Goal-4/brief.md`「延期项」）

- **需用户裁决（1 条）**：只读 listener 是否应当能看项目清单（架构 AD-8 的意图）。当前不可达；支持它要新增只读端点形态或给单 run 端点开白名单，属结构扩张，超出 E75 / E76 Boundaries。
- **E76（收口/文档/并发面）**：`projects` 帧的「单次读单源」（R1 M-1 / R2 M-1 / R3 镜头一#3 同根）；WS 端到端六项落点用例（R1 M-4 → 建议 76.5）；`submit_failed` 日志补 `run_id` 与端口 docstring 的「ack 丢失不在原子性保证内」（R3 #5）；`project_busy` vs `run_conflict` 的文档口径（R3 B6）；`ProjectRegistryHealth.detail` 的去向（R3 L-1）；`HTTP_ENABLED=false` 时的 console 惰性化（R3 L-2）；`project_service` 类型收窄（R2 L-1）；适配器「不碰盘」守卫改 AST 白名单（R3 V8）。
- **本 epic 已闭合的下游义务**：E74 遗留的「`project_service` 生产注入点 + wiring 判据」（75.5 交付）、「适配器不得把路径写进错误消息」（75.3 的端口义务 + 适配器只搬 `code`）、「契约基线过期红」（75.1 与批级派生重生成，`--check` 五份全 `[OK]`）。

## 结论

**accepted-with-open-items**：E75 的 7 条 Requirements 全部交付（R2 的「`cli` / `pub.projects` 恒 0 命中 `is_dir`」字面为假，已按架构 I2 口径记 Notes；R6 的 `cancel_run` 子句按 `bad_spec` 不实现，已记 Notes）；六条 `Done when` 均有可跑判据（「列表空表」一条按 R5 修正为「`default` 一条 + `unreadable`」，已记 Notes）。三份三审报告 + 本回顾齐备，无遗留 Critical / High。开放项已绑定到 E76 或用户裁决，不阻塞 E76 开工。
