---
title: 'Story 64.7 实现启动配置验证'
type: feature
ticket: 7
created: '2026-11-18'
status: done
baseline_revision: '8026aa9'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_recommended: false
context:
  - 'src/heagent/config/__init__.py'
  - 'src/heagent/cli/wiring.py'
  - 'src/heagent/cli/doctor.py'
  - 'src/heagent/cli/errors.py'
---

## Intent

**Problem:** 票面要求「启动时必需配置验证生效」，verify = 「覆盖 >90% 必需配置项，错误信息清晰，
验证耗时 <100ms」。现状的启动期配置错误**分散在各自的装配点**：零凭据 / `OLLAMA_ENABLED` 缺模型由
`providers/composition.py` 抛 `ProviderConfigError`；WS 对外模式缺 token、`WS_EXTERNAL_HOST` 取回环、
TLS 半配由 `network/ws_host.py::WsServerConfig` 的 model_validator 抛 `ValueError`；`Settings` 自身的
pydantic 约束失败则在 `get_settings()` 处抛出原始的 `ValidationError`。三者文案形状、发现时机、退出码
各不相同，最后一个尤其对用户不可读（pydantic 的英文长报文）。

**Approach:** 新增 `config/validation.py`（config 层，零运行栈依赖）做实心判据，由 `cli/wiring.py`
的 `_build_provider` 薄壳作为**唯一挂载点**调用——三个入口（`heagent run` / 交互模式 / `heagent
http-server`）与 GUI 全部经该函数装配 provider，一处挂载即全入口覆盖，无需改 `console.py` / `http.py`
（它们属他人 lane，报告里给出可选集成行）。失败一律 `report_with_hints` + `SystemExit(1)`，不降级成
WARNING。

**与 64.6 `heagent doctor` 的分工（刻意不重叠）：**

| | doctor (64.6) | 本 story |
|---|---|---|
| 时机 | 人手动跑 | 每次启动自动跑 |
| 范围 | 11 组检查 / 25 诊断码（含 .env 行级诊断、技能双根冲突、APPROVAL_TOOLS、端口探测） | 只收「不满足就一定跑不起来」的项 |
| 严重度 | error / warning / info 三档 | 只有「失败」一档，一律阻断 |
| I/O | 本地 socket 探测、目录扫描 | 纯内存 + 至多一次用户级 setting.md 读取 |
| 预算 | <5 秒 | <100ms |

**判据收窄的具体口径（每条都写进代码常量 `REQUIRED_CHECKS`）：** 只有**结构性阻断**才进来——
凭据全缺、`OLLAMA_ENABLED` 缺模型、认证 listener 缺 `WS_AUTH_TOKEN`、`WS_EXTERNAL_HOST` 取回环、
两个 listener 都非回环、TLS 半配、`SANDBOX_BACKEND=docker` 却空镜像 / 非法 digest。
反向排除（**刻意不做**，避免把 doctor 的检查搬一遍）：端口占用（HTTP/WS 均有顺延窗，不属「一定
跑不起来」）、`ACTIVE_PROVIDER` 指向未配置条目（composition 自己回退到首个可用条目并告警）、
`SANDBOX_MODE` 非法值（回退 `workspace-write` 且告警）、token 上限倒置（doctor 判 WARNING）。

**票面偏差（以实测为准）：** 设计要点里提到「路由池声明与凭据的一致性也要门控」。实测该情形**不是
致命项**——`Settings._parse_routing_pools` 与 `providers/composition.py` 的既定契约是「非法 / 无凭据的
池告警后跳过，其余 provider 不受影响」，`doctor` 亦判 WARNING。启动验证若把它升级为阻断，会推翻既有
容错契约并让「只想临时停用某个池」的用户起不来。故 `routing_pools` **不纳入**启动验证的必需键集合，
一致性由 64.6 `heagent doctor`（`doctor.routing_pool_without_credentials`）承担。

**第二个偏差（分层约束）：** 「回环判定」的唯一实现点是 `network/exposure.py::is_loopback_host`，而
`config/` 不得导入 `network/`（依赖方向 + 架构契约）。故在 validation 内联一份等价的纯 stdlib 判定
（`ipaddress` + `localhost` + `[::1]` 脱括号，非字面量一律按暴露处理），并用测试对
`network.exposure.is_loopback_host` 做**等价性交叉断言**——两处漂移由测试点名。

## Boundaries & Constraints

**Always:**
- 判据只用 `Settings` 构造结果 + 纯内存读取；**禁止** socket 探测、子进程、网络、`docker info`。
- 每项检查独立 `try/except`：崩溃转成一条**阻断性** issue（点名检查名 + 异常类型 + 首行 + 逃生路径），
  绝不静默放行。
- 门控先行：`gate(settings)` 为假时不执行 `judge`，因此 WS 未启用时不会去读用户级 `setting.md`。
- 失败信息形态 = `cli/errors.py` 的「描述 + Try + Docs」；validation 只产出结构化
  `ConfigIssue(message, options)`，**锚点与渲染由入口层给**（config 层不得 import `cli`）。
- 跨模块数据用 Pydantic：`ConfigIssue` / `StartupValidationResult` / `RequiredCheck` 均为
  `BaseModel`（`frozen=True`）。
- 覆盖率分子分母都存在代码里：`REQUIRED_SETTING_KEYS`（分母，逐键附「为何必需」注释）与
  `REQUIRED_CHECKS[*].covers`（分子来源），测试只读常量，不硬编码比例。

**Never:**
- 不修改 `cli/errors.py` / `cli/doctor.py` / `console.py` / `http.py` / `config/__init__.py`。
- 不新增异常类：`scripts/contract_snapshot.py::collect_exceptions` 会把任何基底名以 `Error` /
  `Exception` 结尾的类收进 `exception_types.json` 基线，而该基线文件不在本 lane ⇒ 改用
  「返回值 + 入口层渲染」表达失败。
- 不改 `_build_provider` 的签名与既有呈现语义（`ProviderConfigError` → `SystemExit(1)` 的字节契约不动）。
- 不把检查失败降级为 WARNING 后继续跑。

## Code Map

- `src/heagent/config/validation.py` — 新建（config 层，本 story 实心）：
  - 常量：`REQUIRED_SETTING_KEYS`（分母，19 键）、`REQUIRED_CHECKS`（6 项，每项含 name / covers /
    gate / judge / options）。
  - 模型：`ConfigIssue` / `RequiredCheck` / `StartupValidationResult`。
  - 函数：`validate_startup(settings)`（唯一入口，返回结果模型，含 `duration_ms`）、
    `required_coverage()`（返回 `(numerator, denominator)`）、`required_coverage_ratio()`、
    `_is_loopback(host)`（内联等价判定）。
- `src/heagent/cli/wiring.py` — 挂载两处最小改动（入口层呈现）：
  - `_build_provider(settings, model)` 首行调用 `_ensure_startup_config(settings)`；
  - 新增 `ensure_startup_config(settings)`（渲染 + `SystemExit(1)`）与 `load_startup_settings()`
    （`get_settings()` 的可读失败包装，供入口层替掉裸 `get_settings()`——本 story 不替，报告给行）。
- `tests/test_config_validation.py` — 新建：每项检查正/负例、门控静默、覆盖率分子分母、耗时上界、
  错误文案含键名与建议、检查崩溃转阻断、与 composition / `network.exposure` 的跨层一致性。

**入口覆盖（挂载点为什么是 `_build_provider`）：**
- `heagent run`（`cli/console.py:226`）、交互模式（同函数分支）、`heagent http-server`
  （`cli/http.py:622`）、`heagent gui`（`gui/__init__.py:39`）——四处全部经
  `cli.wiring._build_provider`，一处挂载即全覆盖。
- 不覆盖 `heagent doctor`（刻意：诊断命令必须在配置坏掉时仍能跑）、`heagent init`、`heagent replay`
  （不装配 provider，无运行期配置）。
- 已知残余：`--no-ws` 是进程级覆盖，晚于 `Settings`，故「配置声明了对外 listener 但缺 token」时
  带 `--no-ws` 仍会阻断。方向是 fail-loud（不是静默放过），逃逸路径写在错误建议里（修 token 或
  去掉 `WS_EXTERNAL_HOST`），故不作特例分支。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/config/validation.py` — 6 项必需检查 + 覆盖率常量 + 结果模型 — 主体
- [x] `src/heagent/cli/wiring.py` — `_build_provider` 挂载 + 渲染 + `load_startup_settings` — 可达性
- [x] `tests/test_config_validation.py` — 正/负例、门控、覆盖率、耗时、崩溃、跨层一致性 — 判据
- [x] 报告给 orchestrator 的共享行：`console.py` / `http.py` 的 `settings = get_settings()` →
  `load_startup_settings()`（可选强化）、`docs/frame.md` 模块表行、`docs/faq.md` 条目。

**Acceptance（对应票面 verify）：**
- 「覆盖 >90% 必需配置项」→ 测试读 `required_coverage()`，断言 `numerator / denominator > 0.9`
  并逐键断言 ∈ `Settings.model_fields`；实测 19/19。
- 「错误信息清晰」→ 每条 issue 的消息含**具体键名**（`WS_AUTH_TOKEN` / `OLLAMA_MODEL` /
  `WS_EXTERNAL_HOST` / `WS_TLS_*` / `SANDBOX_DOCKER_IMAGE|DIGEST`）+ `Try:` 建议 + `Docs:` 锚点；
  测试逐项断言键名出现在首行、建议非空。
- 「验证耗时 <100ms」→ 测试用 `time.perf_counter` 取 200 次稳态运行的 p95 与最大值双断言。

## Implementation Notes

- **校验与呈现分离**：`validate_startup` 是纯函数，`cli/wiring.py` 负责 `with_hints` 渲染与退出码。
  这样 `config/` 不必反向依赖 `cli/`，也让测试能只断言结构化结论。
- **零凭据消息刻意与 composition 逐字相同**（含 `Error: No API key configured. ...`）：既有测试
  `tests/test_cli_provider_build.py::test_shell_maps_to_exit_code_one` 与
  `tests/test_cli_error_format.py` 断言的是该稳定子串；本 story 用
  `test_credentials_message_matches_composition_contract` 反向钉住这份「跨层同文案」，一旦 composition
  改文案，本 story 的测试先红。同法钉 `OLLAMA_ENABLED` 缺模型那条。
- **`REQUIRED_SETTING_KEYS` 是独立策展的**（不是 checks 的 covers 并集抄一遍）：每个键附「为何必需」
  注释，检查忘记登记某键、或某检查被删除，都会把覆盖率打下来——是可漂移的红灯，不是同义反复。
- **`ws_auth_token` 不在分母**：它不是 `Settings` 字段（凭证只认用户级 `setting.md`，见
  `Settings.user_ws_auth_token` 的注释），只出现在检查的建议文案里。
- **崩溃即阻断**：`gate`/`judge` 抛异常（含 `setting.md` 语法错导致的 `SettingsError`）转成一条
  issue，文案点名检查与异常首行，并给两条逃生路径（`heagent doctor` / 修配置文件）。
- **稳态计时**：`duration_ms` 用 `perf_counter` 包住检查循环；不含 `Settings` 构造（构造发生在
  调用方）。门控为假时不读文件 ⇒ 默认配置（无 WS 对外、非 docker）路径零文件 I/O。
- **已知残余风险**：`--no-ws` 覆盖见 Code Map；digest 检查只判格式（`sha256:<64 hex>`），不探测
  镜像是否存在（探测需要 `docker image inspect` 子进程，越界）。

## Verification

- `pytest tests/test_config_validation.py -q` → **59 passed**（本 lane 全绿）。
- 挂载点回归（只跑相关既有用例，未跑全量）：
  - `tests/test_cli_provider_build.py` → 48 passed
  - `tests/test_cli_http.py` + `tests/test_cli_events_rollout.py` + `tests/test_cli_web_overrides.py` → 70 passed
- `ruff check` + `ruff format --check` + `mypy`（三个本 lane 文件）→ 全绿。
- 覆盖率（分子/分母均来自代码常量）：`required_coverage()` = **19/19 = 100%**（阈值 >90%）。
- 耗时（500 次稳态，`perf_counter`）：
  - 默认配置（仅有凭据）：mean 3.6µs / p95 4.0µs / max 32µs
  - 门控全开（`WS_EXTERNAL_HOST` 非回环 + `SANDBOX_BACKEND=docker`，含一次 `setting.md` 读取）：
    mean 17.8µs / p95 24.6µs / max 740µs
  - 两者都远低于 100ms 上界；测试内对 200 次采样断言 `max` 与 `p95` 双过。
- 手动：`python -c "from heagent.config.validation import required_coverage; print(required_coverage())"`
  → `(19, 19)`。

**需 orchestrator 集成的共享文件（本 lane 禁改）：**
- `tests/test_architecture_contracts.py:807`：`assert config_modules == ["envfile", "user_settings", "write"]`
  → `["envfile", "user_settings", "validation", "write"]`（新增 `config/validation.py` 触发的布局钉）；
- `docs/frame.md:114` 配置面一行追加 `· validation = 启动期必需配置验证（依赖方向 DAG 的配置面不变）`；
- `docs/faq.md` 在「配置看起来没错但起不来，有自检工具吗？」之后补一条
  「启动时会自动校验必需配置吗？」（doctor 手动全量 vs 启动验证自动极简的分工）；
- 可选强化：`cli/console.py:221` 与 `cli/http.py:603` 的 `settings = get_settings()`
  → `settings = load_startup_settings()`（`Settings` 构造失败时的可读报文；不改也安全）。

## Review Triage Log

- 2026-11-18 quick lens（本批 4 条 patch）：
  - `ws_tls_pair` 的 `WS_EXTERNAL_TLS` 半配在**对外 listener 未启用**时也阻断启动——运行期根本不读这对键
    ⇒ judge 内按 `_external_ws_host` 门控，测试改成「未启用不阻断 / 启用才阻断」两段。
  - `load_startup_settings` 无生产调用点（死代码）⇒ 由 `http-server` 与主 CLI 入口调用；签名收 `loader`
    参数，让 `heagent.cli.console.get_settings` 这条 monkeypatch 缝继续生效。
  - `config_invalid` 是死场景：真实报文 `configuration could not be loaded: ValidationError…` 落到兜底
    ⇒ 补 `validationerror` / `could not be loaded` 关键词，样例改用真实报文。
  - FAQ 的启动校验清单与 `REQUIRED_CHECKS` 不一致（多列 ACTIVE_PROVIDER / 路由池，漏列 ollama / sandbox /
    binding / TLS）⇒ 按常量重写为 6 项。
- false：四条入口（run / 交互 / http-server / gui）都经 `wiring._build_provider` 这一 choke point；
  WS 关闭 / Ollama 关闭 / 非 docker 后端不误报；模块内无 socket / subprocess（AST 断言）；耗时断言双口径
  （max + p95）。
- 留待裁决：`--no-ws` / `--no-http` **不**绕过本校验（校验作用于 `Settings`，早于命令行覆盖）。
  已在 `docs/faq.md` 写明，并在 64.13 的建议表里去掉那条无效命令。
