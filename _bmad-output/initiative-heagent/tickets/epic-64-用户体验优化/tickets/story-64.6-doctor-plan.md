---
title: 'Story 64.6 实现配置诊断工具'
type: feature
ticket: 6
created: '2026-11-18'
status: built
baseline_revision: '69fbd2a'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_recommended: false
context:
  - 'src/heagent/config/catalog/report.py'
  - 'src/heagent/config/catalog/envscan.py'
  - 'src/heagent/config/__init__.py'
  - 'src/heagent/cli/console.py'
  - 'src/heagent/cli/errors.py'
---

## Intent

**Problem:** 票面要求 `heagent doctor`：检测 ≥10 类常见配置问题，每条给描述与修复建议，运行 <5 秒。
现状没有任何配置自检入口：用户遇到「起不来 / 跑不通」只能翻日志或逐键比对 `.env`。仓库已有
两件可复用的基础设施——`config/catalog` 的 `build_config_report`（值 + 来源 + `.env` 行级诊断：
重复键 / 空值键 / 未知键 / BOM，实测 14 ms）与 `SkillStore.conflicts()`——但都没有面向命令行的出口。

**Approach:** 新增 `heagent doctor` 子命令，聚合两类检查：
① **复用** `build_config_report` 的文件级诊断与 `routing_report`；
② **新增**运行期可判定的不一致（凭据缺失、`ACTIVE_PROVIDER` 指向不存在条目、池声明无凭据、
WS 对外模式缺 token / `WS_EXTERNAL_HOST` 取回环 / TLS 半配、端口被占、
`APPROVAL_TOOLS` 含未注册工具、`SAFETY_BLOCKED_TOOLS` 非法 JSON、`OLLAMA_ENABLED` 缺模型、
`MAX_OUTPUT_TOKENS ≥ MAX_CONTEXT_TOKENS`、技能双根同名冲突）。

**Verify 拆解：**
- 「≥10 类」→ 实装 **11 组检查**，产出 **25 个稳定诊断码**（每组可报多种码）；
- 「含描述与修复建议」→ 每条 finding 带 `code` / `severity` / `message` / `fix`；
- 「运行 <5 秒」→ 只做文件读取与本地 socket 探测（不联网、不调 `docker info` 之外的外部进程），
  测试里用耗时断言钉住。

## Boundaries & Constraints

**Always:**
- 只读：doctor 不写任何文件、不改配置、不启停服务。
- 每项检查独立 try/except：单项抛错记成 `doctor.check_crashed`（`info` 级），不让整体崩。
- 严重度三档：`error`（必然跑不起来）/ `warning`（可能跑不通或行为不符预期）/ `info`（提示）。
  有 `error` 时退出码 1，否则 0——便于脚本消费。
- 复用既有求解器：`.env` 诊断走 `build_config_report`，不自己再写一套解析。
- 修复建议给具体键名或命令，形态与 `cli/errors.py` 的 `Try:` 一致（同一套文案纪律）。

**Never:**
- 不探测上游 Provider（不做真实 API 调用）——那会把 <5 秒与可用性绑在一起。
- 不判断「配置对不对」的语义正确性（如某个 key 是否有效）；只判结构性与一致性。
- 不引入新依赖；不修改 `config/catalog` 的公开行为。

## Code Map

- `src/heagent/cli/doctor.py` — 新建：`Finding`(Pydantic) / `run_checks()` / `doctor_cmd`（click）。
- `src/heagent/cli/console.py` — `main.add_command(doctor_cmd)`（与 init/gui/http-server 同处尾部注册）。
- `tests/test_architecture_contracts.py` — cli 布局白名单加 `doctor`（字母序）。
- `docs/frame.md` — 子模块表 + 目录树各补一行。
- `docs/faq.md` — 「使用」栏补一条 `heagent doctor` 的问答（此前 FAQ 明确不写未实现的命令）。
- `tests/test_cli_doctor.py` — 新建：13 项检查各有正/负例 + 耗时 + 退出码 + `--json`。
- 复用事实源：`config/catalog/report.py::build_config_report`（env 诊断 + routing）、
  `config/catalog/envscan.py`（`blank_keys` / `duplicate_keys` / `unknown_keys`）、
  `providers/composition.py::ROUTING_POOL_ENTRIES` 语义（条目名清单在 `config/__init__.py`）、
  `skills/skill_store.py::SkillStore.conflicts`、`network/exposure.py::is_loopback_host`、
  `tools/registry.py::ToolRegistry`（`APPROVAL_TOOLS` 合法性）。

## Tasks & Acceptance

**Execution:**
- [ ] `src/heagent/cli/doctor.py` — 13 项检查 + click 命令 + `--json` — 主体
- [ ] `src/heagent/cli/console.py` — 注册子命令 — 可达性
- [ ] `tests/test_architecture_contracts.py` + `docs/frame.md` — 布局契约同步 — 硬约束
- [ ] `tests/test_cli_doctor.py` — 正/负例、退出码、耗时 — 判据
- [ ] `docs/faq.md` — 补 doctor 问答 — 可发现性

**Acceptance Criteria:**
- Given 一个空配置目录，when `heagent doctor`，then 输出含 `doctor.no_credentials`（error）与
  「配哪个键」的修复建议，退出码 1。
- Given 配好一个凭据的最小 `.env`，when `heagent doctor`，then 无 `error` 级 finding，退出码 0。
- Given `.env` 里有重复键与空值键，when `heagent doctor`，then 分别报 `doctor.env_duplicate_keys`、
  `doctor.env_blank_value`（warning）。
- Given `WS_HOST=0.0.0.0` 且无 `WS_AUTH_TOKEN`，when `heagent doctor`，then 报
  `doctor.ws_external_without_token`（error，因为服务必然拒绝启动）。
- Given `--json`，when 解析输出，then 是合法 JSON 数组，每项含 `code` / `severity` / `message` / `fix`。
- Given 任一次运行，when 计时，then 耗时 < 5 秒。

## Implementation Notes

## Implementation Notes

- `src/heagent/cli/doctor.py`：11 组检查 → 25 个诊断码；`Finding` 用 Pydantic（`code`/`severity`/
  `message`/`fix` 四段），人读输出走 stderr、`--json` 走 stdout，有 `error` 时退出码 1。
- 复用既有求解器：`.env` 诊断走 `config.catalog.build_config_report`（重复键 / 空值键 / 未知键 / BOM /
  缺失），回环判定改用 `network.exposure.is_loopback_host`（不另写一份），技能冲突走 `SkillStore.conflicts()`。
- 实现期修掉的**误报与漂移**：WS 检查按 `WS_ENABLED` 门控；主 listener 与外部 listener 的「缺 token」
  拆成两个码；补 `WS_LOCAL_AUTH_ENABLED` 缺 token；`ACTIVE_PROVIDER` 指向无凭据条目判 error；
  端口占用降为 info（很可能是自己刚起的实例）；docker daemon 探测不到降为 info 且覆盖 `DOCKER_HOST`；
  检查崩溃由静默 info 改为 warning + `logger.warning(exc_info=True)`。
- 事实核对：`providers/openai.py` 的 Chat Completions 条目已删 ⇒ 只配 `OPENAI_API_KEY` 确实不产生
  provider，doctor 判「无凭据」是对的；`fix` 文案里已点明这一点，避免读者以为漏检。
- 契约同步：`console.py` 尾部注册 `doctor_cmd`（与 init/gui/http-server 同形态）；
  `tests/test_architecture_contracts.py` 白名单与 `docs/frame.md` 表格/目录树各补 `doctor`。
- 文档：`docs/faq.md` 使用栏新增 doctor 问答（此前 64.1 明确不写未实现命令，本票落地后补上）。

## Review Triage Log

- 2026-11-18 quick lens（1 个 reviewer，28 findings）：patch 18 / false 6 / maybe-false 4。
- patch：检查项「13」与实现不符（改为 11 组 / 25 码，三处文档同步）；`get_settings()` 在 try 之外
  （移入，Settings 校验失败也给可读结论）；`WS_ENABLED=false` 仍报 WS error（加门控）；主/外部 listener
  共用同一 code（拆成两个）；`WS_LOCAL_AUTH_ENABLED` 缺 token 未检（补）；`ACTIVE_PROVIDER` 指向无凭据
  条目静默（补 error）；`port_in_use` 把「自己正跑着」当问题并劝停进程（降 info + 改措辞）；
  `_is_loopback` 重复实现且把 `localhost` 判回环（改用 `is_loopback_host`）；docker 探测不到就给
  warning 且文案说 "silently"（降 info、改文案、补 `DOCKER_HOST`）；检查崩溃无日志（补 warning +
  exc_info）；`fix` 缺具体键名（routing pool / approval tools / skill conflict 补）；
  `SAFETY_BLOCKED_TOOLS` 拦 shell 的措辞像劝人削弱安全（改中性）；
  测试 `_report` 的 `content or content == ""` 恒真（改 `None` 语义）；`_BASE` 仍受进程环境变量影响
  （改 `_CLEAN` 显式置空全部凭据字段）；`test_clean_config_exits_zero` 打了噪声 monkeypatch 且只断
  退出码（改为断言「无 error 级 finding」）；`--json` 用例断言每项四段 + 退出码；技能冲突 message 中英混排（改英文）。
- false：`OPENAI_API_KEY` 未覆盖 ⇒ 必然误报 —— Chat Completions 条目已从 `composition.py` 删除，
  只配该键确实不产生 provider，doctor 判「无凭据」正确（reviewer 不知该历史）；
  「`SAFETY_BLOCKED_TOOLS` 非法 JSON 未检查」——类型是 `list[str]`，非法值在 `Settings` 构造期就报错，
  由 `doctor.settings_unreadable` 覆盖；「测试绕过 `main` 组」—— 已补 `--json`/退出码用例，组级注册由
  `test_architecture_contracts.py` 的布局白名单 + `heagent doctor` 实跑验证。
- maybe-false：容器内探测结论与宿主不一致（工具本就跑在哪个命名空间就报哪个的事实，已在 message 里
  写明探测点）；`build_config_report` 入参用 `Path.cwd()/".env"`（多项目场景需先 cd，已在注释写明）；
  新建文件 `100755`（9p 不支持 chmod，提交时 `git add --chmod=-x`）。

## Plan Change Log

## Review Triage Log

## Verification

**Commands:**
- `pytest tests/test_cli_doctor.py -q` -- expected: pass
- `pytest tests/test_architecture_contracts.py -q` -- expected: pass
- `python -m heagent doctor` -- expected: 有输出、退出码与 finding 一致
- `ruff check src tests scripts && ruff format --check src tests scripts && mypy src` -- expected: pass
