---
epic: epic-64-用户体验优化
date: 2026-11-18
verdict: accepted
criteria: declared
headless: false
---

# Epic 64 Retrospective

> 路径约定：正文里的 `tickets/story-64.*` 均相对 `_bmad-output/initiative-heagent/tickets/epic-64-用户体验优化/`；
> 其余路径相对仓库根。所有实测数字为本 retro 现场取证（2026-11-18，容器内
> `.heagent/tmp/py311-venv-linux/bin/python`），未跑全量 `pytest`。

## Epic summary

**Epic**：epic-64-用户体验优化（R7 / R9 / R10 / R11；10 个新 `src/` 模块 + 15 个改动模块 + 4 份文档面 + 5 个示例）

**票态**：14/14 `built` / `state=review`，**本次收口置 `done`**（`tickets.py mark` 由 orchestrator 执行），
无 `dropped`、无 `pending_tickets`。现场取证：

```text
tickets.py status .../epic-64-用户体验优化/tickets
→ {"counts": {"total": 14, "review": 14}, "next_id": 15}
```

**Plan 区间与证据**：

| Stories | 区间 | 提交 | 变更量 |
|---------|------|------|--------|
| 64.1–64.4 | 198b2aa..69fbd2a | `69fbd2a` | 22 文件 +2202 −2（含 4 份 plan） |
| 64.5 | 69fbd2a..724fdee | `724fdee` | 9 文件 +544 −15 |
| 64.6 | 724fdee..8026aa9 | `8026aa9` | 7 文件 +986 −0 |
| 64.7–64.14 | 8026aa9..90fc230 | `90fc230` | 51 文件 +8401 −102 |
| 收口（既有红） | 90fc230..369e849 | `369e849` | 1 文件 +12 −13 |
| 收口后修复 | 369e849..工作树（**未提交**） | — | 18 文件 +838 −170，另 1 个新文件 `tests/test_cli_single_progress.py`（313 行） |

机读合计（`198b2aa..369e849`，排除 `_bmad-output/`）：**62 文件 +9913 −98**；`src/` 30 文件 +4167 −105
（`git diff --numstat`）。

**证据清单**：

- Epic 文件 ✓（R7/R9/R10/R11 + Done when 四条均 `declared`，`epic-64-用户体验优化.md:41-46`）
- `tickets/tickets.toml` 14 entry（description / verify 齐备）✓
- 14 份 plan（`status: built`、`baseline_revision` 全在：64.1–64.4 = `198b2aa`，64.5–64.6 = `69fbd2a`，64.7–64.14 = `8026aa9`）✓
- 5 个提交区间，8+6 票全归因（subject 点名 story 范围）、零 merge ✓
- 契约快照两次重生成：`90fc230` 的 `exception_types.json`（+127）与 `transport_routes.json`（+2 路由常量），
  工作树再 +7 行（`CommonKeyGroup`）
- Session logs：未在树内正式引用（transcript 留存于会话侧，未入档）→ 过程教训按窄化记录
- **缺口**：① 收口后修复（18 文件）尚未提交，as-built 有一段落不进 git 史；② 3 个子 agent 撞轮次上限
  只有产物痕迹、无 plan 内记录（见 V1）

## Findings

### 聚合视角（确定性推导）

| # | 视角 | 发现 | 源引用 | 处置 |
|---|------|------|--------|------|
| F1 | 架构增量 | `src/` 新增 **10 个模块**、改动 15 个：`cli/{cron_cmd,doctor,errors,progress,suggestions,wizard}.py`、`config/validation.py`、`cron/status.py`、`engine/tasks.py`、`network/http_server/endpoints_tasks.py`——新增全落入口层与既有域包的叶子位置，零新包、零反向导入 | `git diff --name-status 198b2aa..369e849 -- src/`；`pytest tests/test_architecture_contracts.py -q` → 38 passed | accept |
| F2 | 共享落点串扰 | **架构白名单是本 epic 最大的串扰面**：一次集成要补 5 行（cli 4 个模块 + config 1 个），且四个并行 lane 各自撞同一条断言 | `tests/test_architecture_contracts.py:741-758`（cli 白名单）、`:811`（config 白名单）、`90fc230` 的该文件 diff（+4 / −1 / +1 行） | accept（治理动作见 AI-2） |
| F3 | 规格对齐① | 三处 verify 用**结构保证**替代性能调优：`/api/tasks` 的「响应 <100ms」= 只读内存 + 定长模型（实测 0.14–0.24 ms 中位）；工具进度的「不影响性能」= 未越阈值时零任务零输出；启动校验的「<100ms」= 门控先行 + 纯内存（实测 19/19 键、µs 级） | `tickets/story-64.11-…-plan.md`（Implementation Notes 实测段）、`tickets/story-64.8-…-plan.md`（Acceptance 1）、`tickets/story-64.7-…-plan.md`（Verification 计时） | accept（口径已写进 plan，非缺陷） |
| F4 | 规格对齐② | plan 与代码的**时序差**：plan 里标「未完成 / 交 orchestrator」6 处，5 处在 `90fc230` 闭合、1 处（单测回填）在工作树闭合；64.10 的两条「留待裁决」也已在集成期落成代码 | 未完成项：`tickets/story-64.10-…-plan.md:92`、`story-64.11-…-plan.md:103,105`、`story-64.14-…-plan.md:109-110`、`story-64.8-…-plan.md:142`；闭合证据：`src/heagent/cli/console.py:498-500`、`src/heagent/cli/http.py:371,682`、`src/heagent/cli/cron_cmd.py:96-143`、`tests/test_architecture_contracts.py:741-758,811` | accept + AI-4（回填 plan） |
| F5 | 契约快照扩张 | `exception_types.json` 本 epic 累计 **+134 行**：收集规则是「基底名以 `Error`/`Exception` 结尾 **或** 在 `__all__` 中」，故新模块导出的 `CommandSuggestion`/`ErrorScenario`/`TaskProgress`/`CommonKeyGroup` 等会被自动收进来——这是集合**扩张**而非漂移；`transport_routes.json` 新增 `_TASKS_PATH` / `_TASK_DETAIL_PATH` 两条路由常量 | `scripts/contract_snapshot.py:299-320`；`git show 90fc230 -- tests/fixtures/contract_baselines/*.json`；`git diff tests/fixtures/contract_baselines/exception_types.json`（`CommonKeyGroup`） | accept（口径见 D5） |
| F6 | 依赖与静态面 | `pyproject.toml` 区间内**零改动**；新模块 import 面 = stdlib + `pydantic` + `click`（`suggestions.py` 甚至只有 `re` + pydantic）；`bandit -r src/ -ll` exit 0 | `git diff --stat 198b2aa..369e849 -- pyproject.toml`（空）；各新文件 import 头；`python -m bandit -q -r src/ -ll` | accept |

### 聚合视角补充

| # | 视角 | 发现 | 源引用 | 处置 |
|---|------|------|--------|------|
| F7 | 文档面增量 | `docs/faq.md` 实测 **36 条**（三栏各 12：配置 / 使用 / 故障排查，票面要求 ≥20）；`docs/errors.md` 三张主表 + 关键词跳转表（传输层 35 码 / 框架 9 类 / CLI 12 条）；`docs/performance.md` 五节（分析方法 / 常见瓶颈 / 优化建议 / 参数与推荐值 / 测试方法）；`examples/` 5 个示例 + 索引 README | `docs/faq.md:9,217,389`（三个二级栏）；`docs/errors.md:42,129,145,205`；`docs/performance.md:9,74,90,107,158`；`ls examples/` | accept |
| F8 | 测试面增量 | 12 个新测试文件 + 4 个既有文件扩展（`tests/` 区间 17 文件 +3976 −17）；本 retro 定向跑 **13 文件 380 passed** | `git diff --name-status 198b2aa..369e849 -- tests/`；`pytest` 定向两批（见 Behavior verification） | accept |
| F9 | 覆盖面口径 | 三条「覆盖率」类 verify 的分母都是**代码里的常量**而非测试里的魔数：向导 45/45、启动校验 19/19、doctor 11 组 25 码——清单变化会直接打红，不会静默同义反复 | `src/heagent/cli/wizard.py:240`（`COMMON_KEYS`）+ `:53`（`MIN_COVERAGE`）；`src/heagent/config/validation.py:35`（`REQUIRED_SETTING_KEYS`）+ `:266-324`（6 项检查）；`src/heagent/cli/doctor.py`（25 个 `doctor.*` 码） | accept |

### 透镜发现（代码透镜 · 四镜头）

**收窄记录**：`bmad-review` 未装进 HeAgent 技能库（同步脚本声明不得调用），故按四向自审收窄——并行协作
代价（process）、接线是否真的通（verification-gap）、行为缺陷（adversarial）、文案与文档漂移（spec-drift）+
可执行性（actionability）。审查域 = `198b2aa..工作树` 全 diff。

- **V1 并行开发的代价（process）— 3 个 agent 撞 60 轮迭代上限，白名单是最大串扰面**
  - 执行形态：8 票分两波多 agent 并行（第一波 64.1–64.6，第二波 4 + 3 个 agent，其中 **64.8+64.9 同族
    合并给 1 个 agent**）——合并的依据写在 64.8 plan 里（两票共用 `cli/progress.py` 一个模块，常量互不重叠）。
  - 代价一：**3 个 agent 撞 60 轮迭代上限 ⇒ 代码已落盘、plan 未写，由 orchestrator 补写**。残留痕迹可核：
    `tickets/story-64.8-…-plan.md:126` 的 `## Verification` 首行仍写「（结果见交付报告「实测」节）」、`:142`
    把白名单插入位置推给「交付报告」、`story-64.9-…-plan.md:102` 与 `story-64.8-…-plan.md:100` 的 pytest 任务框
    至今未勾——plan 是事后补写而非逐轮推进的形态。**轮次上限本身无提交内证据**（会话侧记录，未入档）。
  - 代价二：**共享落点集中在 4 个文件**（`cli/console.py` 注册、`tests/test_architecture_contracts.py` 白名单、
    `docs/frame.md` 子模块表与目录树、契约快照），只能由 orchestrator 一次改对。白名单尤其如此：四份 plan
    各自记录同一断言 FAIL 并把插入位置外推（`story-64.10-…-plan.md` 的「待 orchestrator 集成」、
    `story-64.13-…-plan.md` 的接线表、`story-64.14-…-plan.md:109`、`story-64.8-…-plan.md:142`），而集成本质上
    是**一次 5 行改动**（`90fc230`：`cron_cmd` / `progress` / `suggestions` / `wizard` / `validation`）。
  - → **process lesson**（AI-2 / AI-3）：并行 lane 的共享落点在开工前登记为 orchestrator 独占，子 agent 的
    任务里给轮次预算与「先落 plan 再落代码」的顺序。
- **V2 接线型真缺陷（verification-gap）— `build_http_app(tasks=None)` 让 `/api/tasks` 在生产恒 404，且注册表无生产者**
  - 现象：64.11 的单元面全绿（`build_http_app(tasks=…)` 手工注入 + 端点 404/405/耗时断言），但**生产入口
    从未传 `tasks=`**，而 `build_http_app` 的契约是「`tasks is None` 就不注册路由」⇒ 真实服务上两条端点恒 404；
    同时唯一生产者是 CLI 侧 `_compact_session`，网页进程里没有生产者。
  - 归因点在 plan 里被如实记录（`tickets/story-64.11-…-plan.md` 的「已实测的两处缺口 A/B」），修法：
    `cli/http.py` 两处 `HttpServer(...)` 注入 `RegistryTaskSource(default_task_registry())`，并在
    `agent/context_runtime.py` 的真实压缩路径绑定 `compression_progress`。
  - 判据：`tests/test_cli_epic64_wiring.py:52-70`（内嵌服务实例上 `GET /api/tasks` 必须 200，拨回注入即红）、
    `:39-50`（`main` 能派发 `cron status`）、`:113`（真压缩留 `completed` 条目）。
  - → **accept**（已修）；教训 = 单元测试若自己构造依赖注入，必须另有一条「走真实入口装配」的接线判据。
- **V3 我引入的行为缺陷（adversarial）— `maybe_compress` 每轮开 scope，未压缩迭代留 `completed 100%` 噪声**
  - 缺陷：把进度注册表接到自动压缩时，`maybe_compress` 每轮迭代都进 `scope(...)`，而「未超阈值」路径
    直接返回**同一个列表对象**，`TaskScope.__exit__` 于是把它收成 `completed 100%`；终态只保留 32 条，
    真压缩结果几轮后就被挤出窗口——**接上进度反而把可查信息冲掉**。
  - 修法：新增 `TaskRegistry.discard()` / `TaskScope.discard()`，`compressed is state.messages` 时摘除条目
    （既不冒充完成、也不谎报失败）。
  - 判据：`src/heagent/agent/context_runtime.py:98-109`；`src/heagent/engine/tasks.py:191,294-303`；
    `tests/test_cli_epic64_wiring.py:102-111`（no-op 迭代后 `registry.snapshot() == []`）与
    `:113-123`（真压缩留 1 条 `completed`）。
  - → **accept**（已修，由评审在第二波抓出）；教训 = 给「每轮都会调用」的函数挂状态机，先问「没做事的那次
    会留下什么」。
- **V4 文案与文档三类漂移（spec-drift）**
  - ① **行内注释口径写反**：新生成模板与 `cli/init.py` 既有模板都把行内注释的剥除规则写反（读侧会剥掉
    「空白 + `#`」之后的内容）⇒ 两处同批改正：`src/heagent/cli/wizard.py:58`、`src/heagent/cli/init.py:26`；
    源 = `tickets/story-64.14-…-plan.md` 的 Review Triage Log 第 1 条。
  - ② **FAQ 退出码 2 ≠ 实际 1**：`heagent init --interactive` 非 tty 时走 `exit_with_hints` →
    `click.ClickException` ⇒ 退出码 **1**，文档曾写 2。现状 `docs/faq.md:45` 已改为 1；
    源 = 同一 plan 的 Triage Log 第 2 条。
  - ③ **启动校验清单与 `REQUIRED_CHECKS` 不一致**：FAQ 曾多列 `ACTIVE_PROVIDER` / 路由池、漏列 ollama /
    sandbox / binding / TLS。现状按常量重写为 6 项，逐条对齐
    `provider_credentials` / `ollama_model` / `ws_auth_token` / `ws_external_binding` / `ws_tls_pair` /
    `sandbox_docker`（`docs/faq.md:402-415` ↔ `src/heagent/config/validation.py:266-324`）。
  - → **accept**（三处已修）；共性 = 文档抄的是「设计意图」而非「代码常量」，修法统一为「从常量反查文档」。
- **V5 建议必须可直接执行（actionability）— `--no-ws` 曾作为 WS 缺 token 的逃逸建议，实测无效**
  - 原建议表给 `heagent run --no-ws` / `heagent http-server --no-ws`；实测**无效**：启动校验作用于
    `Settings` 的构造结果，**早于**本次进程的命令行覆盖 ⇒ 带 `--no-ws` 仍会 fail-loud 阻断。
  - 修法：场景表换成 `heagent init` + `heagent doctor` 两条真实可执行的命令，并在注释与文档里写死原因
    （`src/heagent/cli/suggestions.py:100-102`；`docs/errors.md:177`；`docs/faq.md:415`）。
  - 同批另一条：`config_invalid` 曾是**死场景**（真实报文 `configuration could not be loaded: ValidationError…`
    因关键词边界落到兜底）⇒ 补 `validationerror` / `could not be loaded` 关键词并用真实报文做样例。
  - 判据：`tests/test_cli_suggestions.py`（命令反射校验：`heagent <sub>` 必命中 `console.main.commands`、`/<name>`
    必命中斜杠注册表、`--flag` 必在该 click 命令参数表里）。
  - → **accept**（已修）；教训 = 建议类文案必须跑一遍真实复现路径，不能靠「看起来能绕过」。
- **V6 删实现必须同步删测试（process）— 既有红 `test_setup_ws_external` 的真实成因**
  - `954f9d4`（`/simplify` 清理批）把脚本私有函数 `upsert_env_value` 换成共享求解器
    `config.envfile.replace_or_append`，但 `tests/test_setup_ws_external.py` 里 5 条参数化用例仍指向旧函数
    ⇒ `AttributeError`。`369e849` 收口：删掉 5 条旧用例，改为「脚本与运行栈同一份 `replace_or_append`，
    且脚本内不再出现 `upsert_env_value`」的单源断言（形态见 `tests/test_setup_ws_external.py` 现行
    `test_env_rewrite_delegates_to_the_shared_solver`）。
  - 顺带一条对账：Epic 63 retro 把这批红记为「`test_setup_ws_external` CRLF 环境失败」（`epic-63-测试体系增强-retrospective.md`
    的 Behavior verification 段），而 `369e849` 的提交信息表明其中 5 例是删除实现未同步删除测试导致的
    `AttributeError`——**计数与文件都对得上，当时的「环境失败」归因不准确**。
  - → **accept**（已闭合）；教训 = 删/改名实现时先 `grep` 测试里的字符串路径（与既有「monkeypatch 缝是搬移
    红线」同源纪律），且把红一律归为「环境噪声」前必须先看 traceback 类型。

## Behavior verification

运行时行为已实际执行，非仅靠测试声明：

- **定向回归（本 retro 现场）**：`tests/test_cli_epic64_wiring.py` + `tests/test_cli_single_progress.py` +
  `tests/test_engine_tasks.py` + `tests/network/test_http_tasks.py` → **66 passed / 3.31s**；
  `test_cli_cron_status` + `test_config_validation` + `test_cli_suggestions` + `test_cli_init_wizard` +
  `test_slash_help` + `test_cli_progress` + `test_file_progress` + `test_cli_doctor` + `test_cli_error_format`
  → **314 passed / 7.58s**。合计 **380 passed**。
- **架构契约**：`pytest tests/test_architecture_contracts.py -q` → **38 passed / 8.24s**（依赖方向与布局白名单全绿）。
- **示例库实跑**（离线、无 API key、无网络）：`examples/{custom-tool,custom-provider,provider-chain,events-stream}/main.py`
  → 4/4 退出码 0（输出首行分别为「最终答案: 工具返回了 1 条结果。」/「isinstance(BaseProvider): True」/
  「回答: [healthy] 我接住了这次调用（第 1 次）。」/「答案: 2 + 3 = 5」）；`examples/skill-package` 经
  `SkillStore('examples/skill-package').list_skills()` → `['release-notes']`。**5/5 示例可运行**。
- **三条自查**：
  | 自查项 | 结论 | 证据 |
  |--------|------|------|
  | 不引入新依赖 | ✓ | `pyproject.toml` 区间零改动；新模块 import = stdlib + `pydantic` + `click` |
  | 依赖方向未破 | ✓ | `pytest tests/test_architecture_contracts.py -q` → 38 passed；`network/http_server/endpoints_tasks.py` 只认注入 Protocol，`config/validation.py` 内联等价的回环判定并有等价性交叉断言（`story-64.7-…-plan.md` 的「第二个偏差」） |
  | 安全机制未削弱 | ✓ | `python -m bandit -q -r src/ -ll` → exit 0、零 issue（仅 3 条既有 `# nosec` 提示：`goal/script_runtime.py:92` B102、`network/origin.py:32` B104 ×2）；向导刻意不收安全闸门键（`SAFETY_BLOCKED_TOOLS` / `APPROVAL_TOOLS`），`app.py` 的只 GET 端点、错误信封不回显异常文本 |
- **静态门禁**：`pytest -q` = **4809 passed / 51 skipped / 25 deselected**（2026-11-18 实测，265s）；`ruff check` + `ruff format --check`（455 文件）全绿；`mypy src`（219 源文件）无报错；`bandit -r src/ -ll` = Medium 0 / High 0
- **覆盖率**：**93.41%**（19360 stmts / 1053 miss；2026-11-18 实测，gate 87%）

**窄化记录**：本轮约束为「不跑全量 pytest」，故全量回归与覆盖率数字由 orchestrator 回填（`pytest -q` = **4809 passed / 51 skipped / 25 deselected**（2026-11-18 实测，265s）；`ruff check` + `ruff format --check`（455 文件）全绿；`mypy src`（219 源文件）无报错；`bandit -r src/ -ll` = Medium 0 / High 0 / **93.41%**（19360 stmts / 1053 miss；2026-11-18 实测，gate 87%））；
真 tty 下的 `heagent init --interactive` 交互走查与真进程 `heagent cron status` 冒烟未在 retro 现场执行
（其单元与接线判据已含在 380 passed 内）。

## Previous-retro follow-through

对照 `epic-63-测试体系增强-retrospective.md` 的 Open questions（3 条）：

| # | Epic 63 的开放问题 | 本轮结果 | 证据 |
|---|-------------------|----------|------|
| 1 | epic-62 无 retrospective 文件，建议在 epic 64 开工前补 | **未做（结转）**——`find _bmad-output/initiative-heagent/tickets -name '*retrospective*'` 实测仅 61 / 63 两份 | 现场 `find` 输出 |
| 2 | AI-5 直接改 epic 文件（默认 retro 不改 epic）是否需补 poc 记录留存例外授权 | **未做（无落盘痕迹）** | 无对应产物 |
| 3 | 下一步票：epic 64 等 planned 票无 `after` 阻塞 | **已执行**——14 票全部 built、本次收口置 done | `tickets.py status` + 本文 Epic summary |

另有一条**对账式 follow-through**：Epic 63 记的「5 红 = `test_setup_ws_external` CRLF 环境失败」被 `369e849`
推翻为「删实现未同步删测试」（见 V6），属前一轮 retro 的归因修正。

## Action items

**propose-only（本 retro 唯一可写文件，未落地任何修复）。**

| # | 类型 | 内容 | 落点 | 状态 |
|---|------|------|------|------|
| AI-1 | remediation | 提交收口后修复（18 文件 +838 −170 + 新文件 `tests/test_cli_single_progress.py` 313 行）——否则本 epic 的 as-built 有一段只存在于工作树 | `git status --porcelain` 现有 19 项 | **closed**（随 2026-11-18 收口提交落地） |
| AI-2 | process | 并行 lane 开工前把共享落点登记为 orchestrator 独占：`cli/console.py` 注册、`tests/test_architecture_contracts.py` 白名单、`docs/frame.md`、`docs/faq.md`、契约快照——并把「本次要补哪几行白名单」写进 plan 的待集成清单 | 源自 F2 / V1 | **proposed** |
| AI-3 | process | 子 agent 任务里给轮次预算 + 「先落 plan 再落代码」；撞上限后由 orchestrator 补写的 plan 需在 `Review Triage Log` 标注补写 | 源自 V1（`story-64.8-…-plan.md:126,142`、`story-64.9-…-plan.md:102`） | **proposed** |
| AI-4 | remediation | 把 64.8 / 64.9 的「见交付报告」占位与未勾任务框替换为实测数字 | 同上两文件 | **closed**（2026-11-18 回填：64.8 11 passed / 单次模式另 12 例；64.9 18 例 + 比值 1.18x） |
| AI-5 | spec reconciliation | Epic 64 Done when 四条各补 as-built 注记（FAQ 36 条 vs 票面 ≥20、向导 45 键 vs 票面 >80%、启动校验 6 检查 / 19 键、进度跨进程边界） | `epic-64-用户体验优化.md` Done when 节 | **closed**（2026-11-18 四条均已补 as-built 与边界说明） |
| AI-6 | process | 承接 Epic 63 的两条开放问题（epic-62 补 retro / 例外改 epic 的授权记录） | Previous-retro follow-through 表 | **proposed** |

## Decisions

本轮不新增 ADR 文件（本 retro 是唯一可写文件），决策记录于本节：

| # | 决策 | 理由与证据 | 可反转性 |
|---|------|-----------|----------|
| D1 | **向导分母扩容到 45 项 / 11 个配置面**（用户 2026-11-18 裁定，自 19 项扩容） | 19 项对「覆盖 >80% 常用配置项」的代表性偏弱。口径已钉明：45/45 = 1.0 是**相对本清单的恒等式**，不是相对 `Settings` 全字段的覆盖证据；代表性由「11 个面各至少 1 键」的结构断言兜住（`src/heagent/cli/wizard.py:240`、`:53`；实测 `coverage() = 1.0`；`tickets/story-64.14-…-plan.md` 的「已裁决」条） | 易（清单是常量） |
| D2 | **cron 状态查询退出码三档 0 / 1 / 2** | 0 = 无 failed；1 = 有 job 最近一次 failed；2 = `jobs.json` 整体不可解析**或存在但打不开**。`--json` 在 2 时给 `{"error", "jobs_file"}` 信封而非空数组，避免脚本把「读不出来」当「没有任务」（`src/heagent/cli/cron_cmd.py:42-44,96-143`）。同批把「存在但 `open` 失败」自判放在 `JobStore` 之前，因为 `list_jobs()` 会把 `OSError` 与空列表合并成 `[]` | 中（脚本消费方已依赖） |
| D3 | **`--no-ws` 保持 fail-loud，不改校验时序** | 启动校验作用于 `Settings`、早于命令行覆盖；为让 `--no-ws` 绕过而把校验挪到 argv 之后，会让「配了对外 listener 却缺 token」静默降级。故选择「保持阻断 + 换掉无效建议 + 文档写明」（`src/heagent/cli/suggestions.py:100-102`、`docs/errors.md:177`、`docs/faq.md:415`） | 中（改时序是语义变更） |
| D4 | **进度补单次模式** | 64.8 plan 的留待项是「单次执行不走 `_consume_stream`，没有 3s 耗时行」；收口时补 `_single_run_progress` + `EngineToolProgressAdapter`，与交互模式共用同一套 `ToolProgress`，`--json` 时**整体不装配**（连订阅都不建，stdout 纯 JSONL 是结构保证）（`src/heagent/cli/interactive.py:223-248`、`src/heagent/cli/progress.py:289`；判据 `tests/test_cli_single_progress.py` 313 行） | 易 |
| D5 | **契约快照口径维持**：不因计数上涨改收集规则 | 收集规则 = 「基底名以 `Error`/`Exception` 结尾 或 类在 `__all__` 中」（`scripts/contract_snapshot.py:299-320`）⇒ 新模块导出模型必然进快照；本 epic 的 +134 行与 +2 条路由常量属预期扩张。判据是**脚本重跑幂等**，不是「数字没变」（Epic 63 先例：拆包后 `exception_types` 144→132 亦为预期） | 易（口径已两次被验证） |

## Acceptance verdict

**accepted**（criteria: **declared**）——14/14 票 built、本次收口全部置 `done`，无 `dropped`、无 `pending_tickets`；
8 票的证据面（plan + 定向测试）齐备，收口后修复已在工作树完成并有接线判据。

**Done when 四条对账**（`epic-64-用户体验优化.md:41-46`）：

| # | 票面条款 | 判定 | as-built 证据 / 偏差 |
|---|----------|------|---------------------|
| ① | `docs/faq.md`、`docs/errors.md`、`docs/performance.md`、`examples/` 达标 | **declared → as-built 满足** | FAQ 36 条三栏各 12（票面 ≥20）；errors 传输层 35 码 + 框架 9 类 + CLI 12 条 + 关键词跳转表（票面 >80% 覆盖，三链路各 100%，口径写在页首）；performance 五节；examples 5 示例 5/5 实跑通过（票面 ≥5） |
| ② | 错误格式统一含建议 | **declared → as-built 满足** | 三段块（描述 + `Try:` + `Docs:`）+ 可选 `Try these commands:` 段；10 场景 / 25 条条目 / 15 条去重命令全部通过反射校验；接入 console 3 处、http 5 处、wiring 4 处真实出口（`src/heagent/cli/errors.py`、`src/heagent/cli/suggestions.py`；判据 `tests/test_cli_error_format.py`、`tests/test_cli_suggestions.py`） |
| ③ | 工具/文件/后台进度可见 | **declared → as-built 满足（含边界说明）** | 工具 >3s 原地耗时行（`TOOL_PROGRESS_MIN_SECONDS=3.0`、`PROGRESS_REFRESH_SECONDS=0.5`）；文件 >10MB 真分块读写（`FILE_PROGRESS_MIN_BYTES=10MB`、`FILE_PROGRESS_CHUNK_BYTES=1MB`）；`GET /api/tasks` 与 `/api/tasks/{task_id}` 由入口层注入（`cli/http.py:371,682`）；`heagent cron status/list`。**偏差**：后台进度注册表是**进程内**单例，跨进程不可见（`docs/frame.md` 的「任务进度 API」行已写明）——已在 Next 挂账为口径说明而非缺陷 |
| ④ | `/help`、命令建议、配置向导可用 | **declared → as-built 满足（含边界说明）** | `/help <command>` 四段详情 + 未知命令近似建议（`tests/test_slash_help.py`；3 参 `register` 向后兼容有 `tests/test_cli.py` 45 例兜底）；错误场景建议命令（同 ②）；`heagent init --interactive` 45 项 + 非 tty 显性拒绝 + 三重校验 + 原子写（`tests/test_cli_init_wizard.py`）。**偏差**：`/help` 只覆盖斜杠命令，顶层子命令帮助仍由 click 自带 `--help` 提供（票面措辞是「REPL 中提供上下文帮助」，不构成缺口） |

**Constraints**：覆盖率 **93.41%**（19360 stmts / 1053 miss；2026-11-18 实测，gate 87%）（epic constraint ≥87%）；架构契约 38 passed；`pyproject.toml` 零改动 ⇒
无新依赖；`bandit -ll` exit 0 ⇒ 安全机制未削弱；`network/` 依赖边界由 `endpoints_tasks.py` 的 Protocol 注入 +
`tests/network/test_http_tasks.py::TestLayerBoundary` 双向钉住。

**未闭合 findings**：F4 的 plan 回填（AI-4）、AI-1 的提交面属治理动作，不阻塞 verdict；V2 / V3 / V4 / V5 均已在
代码与判据层闭合，V6 由 `369e849` 闭合。

## Next

1. ~~**先提交 AI-1 的 19 项工作树改动**（含 `tests/test_cli_single_progress.py`）~~ → **已提交**（2026-11-18 收口提交）。
2. ~~**回填 plan 与 epic 文件的 as-built 注记**（AI-4 / AI-5）~~ → **已回填**（2026-11-18：64.8 / 64.9 的占位与任务框、Epic 64 Done when 四条）。
3. **仍挂账项**——2026-11-18 收口时逐条裁定：
   - 后台进度**跨进程不可见**（`engine/tasks.TaskRegistry` 进程内单例）→ **已登记 A56**（触发条件 = 出现「网页端要查
     另一个进程的压缩进度」的真实需求）；
   - `examples/` 不在 `ruff check` / `mypy` 的既有范围（`src tests scripts`）→ **已登记 A56**（触发条件 = 示例与 API
     首次漂移或用户报「示例跑不通」）；
   - `tests/test_file_progress.py` 的耗时断言阈值比票面宽 → **已收紧**到 `< 2x`（实测比值 max **1.18x**，留约 1.7 倍余量）；
   - `tests/network/test_http_tasks.py` 的绝对耗时断言 → **裁定保留**宽阈值并补注释（紧阈值只会在高负载 CI 上 flaky；
     实测中位 0.14–0.24ms，两个数量级余量）；
   - Epic 63 结转的两条开放问题 → **epic-62 retro 已补**（`tickets/epic-62-代码架构重构/epic-62-代码架构重构-retrospective.md`），
     「例外改 epic 的授权记录」仍未动。
4. **下一批票**：initiative 内 `epic-65`（工程自动化）等 planned 票无 `after` 阻塞可解析。

## Assumptions

交互式运行，无 headless 假设记录。
