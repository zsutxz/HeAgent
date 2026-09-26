---
id: 50-7
title: 安全收口、端到端验收与文档同步
status: review
baseline_commit: 4193eac095adf4507a83d37b191a579cbb93c5e2
parent_epic: E50
priority: P0
phase: E（整体验收）
depends_on: [50-1, 50-2, 50-3, 50-4, 50-5, 50-6]
blocks: []
created: '2026-09-23'
---

# Story 50-7：安全收口、端到端验收与文档同步

## 用户故事

作为 HeAgent 维护者，我希望本 Epic 的安全立场、生效语义与验收证据完整可查、且逐条有实测支撑，
以便它可被信任地使用与维护——而不是留下一堆「以为安全」的错觉。

## 侦察实证（2026-09-23）

| 事实 | 证据 | 含义 |
|---|---|---|
| 非回环告警已有单点 | `network/exposure.py` 的 `exposure_warning(host)` / `is_loopback_host(host)` 是「绑定地址是否只对本机可见」的**唯一判定点**（Epic 48 交付） | 本 story 只要求「绑定告警 + 写通道来源判定」两处都复用它，不新增第二套判定 |
| 写通道来源判定可直接复用同一函数 | 实测 11 种 peer 形式全对（含 `::ffff:127.0.0.1`、`[::ffff:127.0.0.1]`；空串 fail-safe 为 `False`） | 零新增分支；结论入测试防回归 |
| `docs/frame.md` 的插入点明确 | `### 4.17 HTTP 网页入口` 在 `:1004`；`## 五、已知缺口` 在 `:1034` | 新增 `### 4.18 网页控制台` 须落在 1004 与 1034 之间 |
| `.env.example` 的同步义务由既有测试强制 | `tests/test_config.py:574-587` 断言「字段 ⊆ `.env.example` 的键」（实测当前 110/110，0 缺失）；文件 345 行 / 全 LF / 无 BOM；HTTP 键块在 `:336-340`，**均为注释形式** | 新增 2 键必须跟随注释风格，否则观感与文档一致性走样 |
| 架构契约测试是硬约束的可执行载体 | `tests/test_architecture_contracts.py`（含 `FORBIDDEN_RUNTIME_IMPORTS` 等） | 本周期新增的依赖方向约束必须钉在这里，否则只存在于文档 |
| 覆盖率门槛 | `pyproject.toml`：87%，且 omit `gui/` 与 CLI 交互层（`cli.py` / `cli_goal.py` / `cli_display.py` / `terminal.py` / `__main__.py`） | **`cli_console.py` 默认不 omit**（脊柱 §10），靠测试覆盖；若最终决定 omit 必须在此记录理由 |

## 范围

- 安全立场收口：绑定告警、写通道来源门、凭证零回传的系统性检查。
- 端到端验收：覆盖 brief §9 的 9 条验收标准，逐条给出**命令 + 实测结果**。
- 依赖方向与安全契约加入 `tests/test_architecture_contracts.py`。
- 文档同步：`docs/frame.md`（4.18 + 配置表 2 行）、`.env.example`（2 键）、`consolidated-overview.md`（Epic 50 条目）、
  `sprint-status.yaml`（7 条 story 状态流转）、`ARCHITECTURE-SPINE.md`（§14 校正表的最终确认）。
- 已知缺口如实登记（不得留「以为安全」）。

## 边界与约束

**Always**

- 每条验收标准都要有**实测证据**（命令 + 输出摘要 + 日期）；禁止先写结论后补命令（「不伪造未运行命令」）。
- 凭证零回传是**逐面**检查：API 响应、错误信封、SSE 帧、日志、审计文件五处都要扫。
- 文档声明与代码行为一致；不一致时**改文档或改代码**，不允许两者并存。
- 全量质量门必须真跑（含双平台 mypy）。

**Never**

- 不把安全机制描述成安全边界（`SafetyGuard` / `PolicyEngine` / 沙箱 / 写通道 / 同源防线一律 defense-in-depth，
  须 OS 级沙箱兜底）。
- 不在验收里用「人工看了一下没问题」替代可复现命令。
- 不新增省略覆盖率口径（如临时 omit `cli_console.py`）来「过门槛」。
- 不把未完成的项写成已完成；未完成项一律进已知缺口表。

## 任务（细分）

- [x] **T1** 绑定告警收口：非回环绑定时沿用 `exposure_warning()` 的 stderr + 日志双通道；UI 常驻声明与之同文案要点。
- [x] **T2** 写通道来源门回归：非回环来源访问写通道 / 项目登记 / 项目移除 → `loopback_required`，且
      **无副作用**（文件、备份、审计、注册表三者都不变）。
- [x] **T3** 凭证零回传系统性检查（逐面）：
      ①`GET .../config` 响应体；②所有错误信封（含 6 类写失败）；③SSE 帧；④日志（caplog）；
      ⑤审计 JSONL。覆盖**短密钥**、**多密钥**、以及「备份内容不经任何网页端点可下载」的负向断言。
- [x] **T4** 跨项目不串味端到端：两项目 A/B 交替「提交 → 切换 → 运行 → 删除」，断言会话、项目级记忆、
      运行快照归属正确；**用 A 的请求无法读取或修改 B 的会话与配置**（含越权路径：A 的 project id + B 的 session id）。
- [x] **T5** 无回归端到端：Epic 49 的流式 / 工具活动 / 停止 / 重连 / 来源校验 / 会话快照逐项目；
      `HTTP_CONSOLE_WRITE_ENABLED` 默认关闭时新增面**只读**。
- [x] **T6** 契约测试：`tests/test_architecture_contracts.py` 增加——`network/` 不得 import `projects` / `config`（非延迟）
      / `engine` / `agent` / `tools`；`workspace.py` 只依赖 stdlib（+ pydantic）；`config_catalog.py` 不依赖 engine/agent；
      写白名单 ⊆ `Settings.model_fields`（用 env 大写口径映射）。
- [x] **T7** `docs/frame.md`：新增 `### 4.18 网页控制台`（落 1004–1034 之间），覆盖工作区模型、项目注册表、
      会话持久化、配置来源求解、写通道 10 步流水线、生效语义、安全立场；配置表新增 `HTTP_CONSOLE_WRITE_ENABLED`
      与 `HTTP_CONSOLE_PROJECTS_FILE` 两行；错误码表补 **18 个新成员**（含 **D1** 的 `session_unreadable`）；
      配置可写面按 **D2/D3** 的划分（46 白名单 / 64 排除）表述；调用链补控制台路由与写通道。
- [x] **T8** `.env.example`：按注释风格补 2 键（默认 `false` / 默认落点说明），跑 `tests/test_config.py` 断言。
- [x] **T9** `consolidated-overview.md` 增 Epic 50 条目；`sprint-status.yaml` 把 7 条 story 推进到最终状态；
      `ARCHITECTURE-SPINE.md` §14 校正表确认最终结论（若实现中发现新校正，一并回写并注明理由）。
- [x] **T10** 已知缺口登记：写入 `docs/frame.md` 五 与/或 `deferred-work-archive.md`——至少包含
      ①网页入口非安全边界（无认证 / 无 TLS）；②全局 `~/.heagent/.env` 永久只读；
      ③配置改动只对下一次 run 生效（无热生效）；④UI 无自动化回归（手工清单）；
      ⑤备份/审计不被工具读取（deny 集合）但仍在宿主文件系统上；⑥`cli_console.py` 的覆盖率口径；
      ⑦**D2/D3** 的划分里若含「只读」的项，须列明「只读不是安全边界」。
      ⑧**「回环来源」不等于安全**（评审 F9）：用户自己浏览器里打开的任意网页，其 peer 也是 `127.0.0.1` ⇒
      回环门对「本机浏览器发起的跨站写入」**不构成防护**，真正的防线是 49-5 的 Origin 校验；
      文档必须写清这条边界，避免「回环 = 可信」的错觉。
      ⑨**跨项目并发（D9 已裁定）**：文档须写明「在途上限 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`
      （默认最多 32）」。**多项目并行是有意能力**，并如实登记已知缺口：无全局并发软上限、
      `HTTP_MAX_CONNECTIONS` 不随项目数放大（多项目并行时连接层可能先成为瓶颈）。
- [x] **T11** 全量质量门实跑并记录数字：`pytest`（含覆盖率）、`ruff check`、`ruff format --check`、
      `mypy src`、`mypy src --platform linux`。
- [x] **T12** brief §9 的 9 条验收标准逐条落「命令 + 实测结果」表（本 story 的产物主体）。

## 验收标准

- **AC1** Given 服务绑定非回环地址，When 控制台启动，Then 沿用 `network.exposure` 的无认证/无 TLS/非安全边界告警，
  且 UI 与文档同样声明。
- **AC2** Given 写通道被非回环来源访问，When 提交配置写入或项目登记，Then 被拒绝
  （`loopback_required`）且不产生副作用。
- **AC3** Given 客户端遍历所有 API（含错误路径、SSE、配置查询与写入响应），When 执行凭证零回传检查，
  Then 响应、错误信封、日志与审计中均不出现任何密钥明文（覆盖短密钥、多密钥、备份访问）。
- **AC4** Given 两个项目 A/B 交替操作，When 提交、切换、运行、删除，Then 会话、项目级记忆与运行状态归属正确，
  用 A 的请求无法读取或修改 B 的会话与配置（跨项目不串味验收）。
- **AC5** Given Epic 49 的既有能力（流式、工具活动、停止、重连、来源校验、会话快照），When 运行回归，
  Then 无行为回归；`HTTP_CONSOLE_WRITE_ENABLED` 默认关闭时新增面只读。
- **AC6** Given 文档与配置示例，When 检查 `docs/frame.md`、`.env.example`、README 索引，
  Then 4.18 小节与 `HTTP_CONSOLE_*` 键已同步，`.env.example` 覆盖全部 `Settings` 字段的既有断言通过。
- **AC7** Given 一次全量质量门，When 运行 `pytest` / `ruff check` / `ruff format --check` / `mypy`（双平台），
  Then 全部通过且覆盖率 ≥ 87%。
- **AC8** Given 实现过程中发现的新校正（含本周期已记录的 **D1–D4**），When 收口，Then
  `ARCHITECTURE-SPINE.md` 与 `epics.md` 的相应位置已回写并写明理由；未闭合项进已知缺口。

## Definition of Done

**交付物**：`docs/frame.md`（4.18 + 配置表 + 已知缺口）、`.env.example`、`tests/test_architecture_contracts.py`、
`tests/network/…` 与端到端测试、`_bmad-output/consolidated-overview.md`、`_bmad-output/sprint-status.yaml`、
`ARCHITECTURE-SPINE.md`（校正回写）、本 story 产物的 §9 逐条验收表。

**验证命令**：

```bash
pytest -q --cov=heagent --cov-fail-under=87
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
findstr /c:"HTTP_CONSOLE_WRITE_ENABLED" .env.example
```

**负向验证**（契约断言的红/绿对照）：①在 `network/` 里 import `projects` → 依赖面契约测试变红；
②往写白名单里塞一个凭证键 → 「白名单 ⊆ 字段集 **且** 不含凭证」断言变红；
③从 `.env.example` 删掉任一 `Settings` 字段名 → `tests/test_config.py` 的覆盖断言变红；
④把非回环来源判定短路 → 50-7 的 AC2 测试变红。逐项确认后复原，全绿。

**质量门**：以上全部通过；覆盖率数字与测试计数取**实测值**写入 story 产物。

## 代码地图

| 路径 | 角色 | 改动 |
|---|---|---|
| `docs/frame.md` | 架构权威 | 新增 4.18；配置表 2 行；已知缺口补条目 |
| `.env.example` | 配置示例 | 2 键（注释风格，默认关） |
| `tests/test_architecture_contracts.py` | 契约断言 | network/workspace/config_catalog 依赖面 + 白名单 ⊆ 字段集 |
| `tests/network/*`、`tests/test_http_console_e2e.py`（新增） | 端到端 | 跨项目不串味 / 凭证零回传 / 无回归 |
| `_bmad-output/consolidated-overview.md` | 总览 | Epic 50 条目 |
| `_bmad-output/sprint-status.yaml` | 状态权威 | 7 条 story 流转 + epic 收口 |

## 风险与未决

- **R1**：`cli_console.py` 的覆盖率——脊柱 §10 定「默认不 omit」。若实测发现难以覆盖（例如大量入口装配代码），
  只能在**有测试**的前提下调整口径，并把理由与实测数字写进产物；不得为了过门槛而 omit。
- **R2**：端到端「跨项目不串味」若只靠 HTTP 层测试，可能漏掉 `tools` 层围栏（handler 守卫 vs policy 预检）的串味；
  必须至少有一条**经过真实工具调用**的路径（如 A 项目的 `file_read` 无法读到 B 项目文件）。
- **R3**：Epic 49 的已知缺口（SSE 订阅上限与 Uvicorn `limit_concurrency` 复用、`sanitize_message` 两段 POSIX 路径漏网、
  TCP 入口错误文案等）**不在本周期修复范围**；本 story 只要求不引入**新的**同类缺口，并在文档中不重复声称它们已解决。

## Requirement Traceability

FR-7；NFR-4, NFR-9, NFR-10, NFR-12；脊柱 §9、§10、§13；brief §9（9 条）、§6.1、§10。

## Dev Agent Record

### Implementation Plan

1. **先侦察再动手**：逐条复核 story「侦察实证」表的事实（行号 / 键 / 口径 / 文件是否存在），
   实测出 3 处与计划期的差异（见 Completion Notes 的偏离 1–3），全部写进脊柱 §14「实现期校正」。
2. **端到端验收测试**（T1–T5）：新增 `tests/network/test_http_console_e2e.py`，一律走**真装配**
   （真 `HttpProjectConsole` + 真注册表 + 真 `SessionStore` + 真写通道 + 真 listener），只在 LLM 侧用
   stub provider —— 理由：本 story 要证的是「跨项目归属」「凭证不外泄」这类**整体性质**，替身会把
   要证的东西证掉。
3. **契约测试**（T6）：`config_catalog` / `envfile` / `config_write` / `projects` 四个顶层模块的依赖面，
   以及「白名单 ⊆ `Settings` 字段（大写口径）且不含凭证」。
4. **文档同步**（T7–T10）：`docs/frame.md` 4.18 + 配置表 2 行 + 错误码计数校正 + 调用链控制台段与
   写通道 10 步 + 五 的 9 条新缺口；`consolidated-overview.md` 补 Epic 49/50 两行；`sprint-status.yaml`
   推进 50-7；脊柱 §14/§15 回写实现期校正（C11–C13 + D8 落定）。
5. **验收表 + 负向验证**（T11/T12）：`reviews.md#acceptance-50-7-epic-acceptance`（§9 九条逐条
   命令 + 实测输出）；`.heagent/tmp/mutate_50_7.py`（DoD 四条 + 2 条凭证面）逐条确认变红后复原。

### Completion Notes

**与 story 文本的偏离（4 处，均有理由）**

1. **端到端测试落在 `tests/network/test_http_console_e2e.py`**（story 代码地图写 `tests/test_http_console_e2e.py`）：
   另外两个控制台测试（`test_http_console_{projects,sessions,config}.py`）都在 `tests/network/`，同目录
   才有同一套夹具风格（`pytest.importorskip("starlette")` + ASGI client 助手 + 真 console 装配）。放别处
   会为了「照抄路径」而把同类测试拆成两半。
2. **错误码计数与可写面划分按实测校正**（story 的 T7 沿用计划期数字）：`HttpErrorCode` 实为 **32** 码
   （计划期写「27 + 18 个新成员」；实测 = 49 的 14 + Epic 50 的 18，Story 50-5 的写通道再 +5 ⇒ 32）；
   可写面实为 **113 = 46 白名单 + 67 排除**（计划期写 111/65）。两处均按「文档与代码不一致时改文档」
   就地更正，并登记进脊柱 §14（C12/C13）。
3. **`cli_console.py` 从未落地**（R1 的前提不成立）：脊柱 §10 与 D7 预判控制台逻辑会拆到该模块并
   「默认不 omit」，但实现期它**没有存在过** —— 控制台装配全在 `cli_http.py`，而它本就不在
   `pyproject.toml` 的 omit 列表里。故 **D7 作废**（§15 已标注），口径记录在 `docs/frame.md` 五。
4. **T2 的范围严格照 story 文本**（写通道 / 项目登记 / 项目移除三处）。实测发现同一路径上的
   **项目重命名**与四个**会话**写操作、项目内运行入口**当前没有**回环门 —— 那是台账里已登记的
   「非回环运行姿态（intent_gap，**blocked 待人裁决**）」条目，本 story 不擅自扩大裁定范围，
   也**不把现状钉成断言**（否则等于把这个缺口冻结）；已写入 `docs/frame.md` 五 与验收报告。

**关键设计点（供评审复核）**

- **T3 的口径是「凭证值五面一律不得出现」，不是「任何值都不许出现」**：非凭证键的**有效值**在配置面板
  与写入响应里本该出现（那是面板的用途），但**不得**进 SSE 帧 / 日志 / 审计。首轮我把两者混成一条
  断言，被实测打回（写入响应回显了刚写入的 `DEFAULT_MODEL` 值）—— 已改成两段式断言并在用例里写明理由。
- **T4 特意包含一条真实工具路径**（R2）：只断言 HTTP 层「取不到 B 的会话」不够，工具层（workspace 围栏）
  才是拦住「让 A 的 agent 去读 B 的盘」的那道门。用例让 stub provider 发 `file_read`，断言 SSE 里
  `tool_error=True` 且 B 的文件内容一个字都没进事件流。
- **非回环来源的 ASGI 伪造**：`httpx.ASGITransport(client=None)` 会把 peer 变成空串 ⇒ `is_loopback_host("")`
  判非回环（fail-safe），所以「回环那一档」必须**显式**给回环 peer，不能靠 httpx 默认值。这一坑写在
  测试助手 docstring 里。

### 验证（实测命令 + 输出）

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

$ python -m pytest tests/network/test_http_console_e2e.py -q          → 9 passed
$ python -m pytest tests/network/test_http_console_sessions.py tests/network/test_http_console_projects.py -q  → 41 passed
$ python -m pytest tests/test_config_catalog.py tests/test_config_write.py tests/network/test_http_console_config.py -q  → 216 passed
$ python -m pytest tests/test_http_web_ui.py tests/test_config.py -q  → 206 passed
$ python -m pytest tests/test_cli_http.py tests/test_http_agent_api.py tests/test_http_security.py tests/network/test_http_server.py -q  → 128 passed

$ python .heagent/tmp/mutate_50_7.py          # 负向验证（DoD 四条 + 2 条凭证面）
[OK] ① 网络层 import projects（依赖面契约）      -> 1 failed
[OK] ② 白名单塞凭证键                            -> 3 failed
[OK] ③ 从 .env.example 删字段名                  -> 1 failed
[OK] ④ 非回环判定短路                            -> 5 failed
[OK] ⑤ 面板回传凭证原值                          -> 5 failed
[OK] ⑥ 审计写原值而非哈希                        -> 2 failed
合计 6 条变异，异常 0 条   # 每条回退后 sha256 与变异前一致
```

`docs/frame.md` 的结构复核（内容检索）：`### 4.18` 落于 `:1039`（4.17 之后、`## 五、已知缺口` 之前）；
五 的表格新增 9 行且与既有行**连续**（插入时曾误删 `## 六、目录结构` 标题与空行，当场修复并复核）。

### File List

**新增**

| 路径 | 行数 | 说明 |
|---|---|---|
| `tests/network/test_http_console_e2e.py` | 470 | 端到端验收（T1–T5：声明口径一致 / 非回环零副作用 / 凭证五面 / 跨项目不串味含真实工具路径 / 闸门只读与运行链路 / 每项目状态根） |
| `_bmad-output/epics/epic-50-网页控制台周期/reviews.md#acceptance-50-7-epic-acceptance` | 68 | §9 九条逐条「命令 + 实测输出」表 + 质量门 + 负向验证 + 已知缺口 |

**修改**

| 路径 | 说明 |
|---|---|
| `docs/frame.md` | +4.18 小节（16 行表格 + 安全立场）；4.10 配置表 +2 行；4.17 错误码计数 27→32；七 调用链 +控制台流程与写通道 10 步；五 已知缺口 +9 行 |
| `docs/README.md` | 文档索引补 4.18 两处（阅读顺序一行 + 快速定位一行） |
| `tests/test_architecture_contracts.py` | +`test_config_layer_stays_out_of_the_runtime_stack`、+`test_write_whitelist_is_a_subset_of_settings_and_holds_no_credentials` |
| `_bmad-output/consolidated-overview.md` | Epic 48 行状态更新 + Epic 49 / 50 两行 |
| `_bmad-output/sprint-status.yaml` | `50-7-security-acceptance-docs: ready-for-dev → review` |
| `_bmad-output/epics/epic-50-网页控制台周期/ARCHITECTURE-SPINE.md` | §14 +实现期校正（C11–C13、D8 与 D5/D6/D1–D4/D9 的落定确认）；§15 的 D7 标注作废 |
| 本 story | frontmatter `status/baseline_commit` + 12 个任务勾选 + 本记录 |

### Change Log

| 日期 | 变更 |
|---|---|
| 2026-09-24 | 实现 Story 50-7：端到端验收测试 9 例 + 契约测试 2 例；`docs/frame.md` 4.18 与配置表/调用链/已知缺口同步；错误码计数与可写面划分按实测校正（27→32、111/65→113/67）；`cli_console.py` 从未落定 ⇒ D7 作废；§9 九条逐条落验收表；全量 3057 passed / 覆盖率 91.82%；真浏览器 18/18；6 条变异负向验证全红。 |
