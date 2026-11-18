---
title: 'Story 64.13 错误时自动建议相关命令'
type: feature
ticket: 13
created: '2026-11-18'
status: built
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
  - 'src/heagent/cli/errors.py'
  - 'docs/errors.md'
---

## Intent

**Problem:** Story 64.5 已把用户可见 CLI 错误收敛成「原消息 + `Try:` 散文 + `Docs:` 链接」三段块，
但 `Try:` 里给的是**描述性动作**（"put WS_AUTH_TOKEN in ~/.heagent/setting.md"），用户还得自己
翻译成命令。票面 R11 要的是「错误发生时自动给出 **≥2 个相关命令建议**，建议与错误场景相关且可直接
执行」——这是一层**从错误文本到可粘贴命令**的映射，不是把 `Try:` 写得更长。

**Approach:** 新增声明式映射表 `cli/suggestions.py`：`场景 → (关键词元组, ≥2 条 CommandSuggestion)`。
`errors.py` 不变更既有三段块，只在**其后**追加一段 `Try these commands:` 列表；新增
`with_command_hints` / `exit_with_command_hints` / `report_with_command_hints` 三个入口，按错误文本
自动选场景（命中不了的走兜底 `heagent doctor` + `/help`）。既有 `with_hints` / `exit_with_hints` /
`report_with_hints` 签名与输出**逐字不变**，新能力只经新增的 `commands=` 关键字参数启用。

**实测偏差（票面前提 vs 仓库现状，以实测为准）：**

- 票面要求「把 console.py / http.py 里所有用户可见错误出口都接上建议」——这两个文件在本 lane 的
  **禁改清单**里（并行开发文件所有权）。本 lane 交付「映射表 + 渲染 API + 出口清单」，调用点替换
  由 orchestrator 接线（见 `## Implementation Notes` 的接线表）。
- 新增 `src/heagent/cli/suggestions.py` 会撞两条**钉死的布局契约**——`tests/test_architecture_contracts.py`
  的 `test_cli_package_layout_is_pinned` 的模块白名单、`docs/frame.md` 的 cli 子模块表与目录树。
  两者都在本 lane 禁改清单内，故按「报告给 orchestrator」处理，不自行修改。

**Verify 拆解：**
- 「≥2 个相关命令」→ 映射表每个场景在导入期校验条数 ≥2（表级不变量，失败即抛），兜底场景同样 ≥2。
- 「可直接执行」→ 每条命令用**代码反射**校验：`heagent <sub>` 必须命中 `console.main.commands`、
  `/<name>` 必须命中 `interactive._build_slash_registry()` 的注册表，`--flag` 必须是该 click 命令真有的
  参数；不硬编码清单，命令表变了测试自然跟着变。
- 「与错误场景相关」→ 每场景固定断言一条**场景专属锚点命令**（如端口场景必须出现
  `heagent http-server --port …`、沙箱场景必须出现 `--sandbox passthrough`）。

## Boundaries & Constraints

**Always:**
- `with_hints` / `exit_with_hints` / `report_with_hints` 的既有签名与输出逐字不变（`tests/test_cli_error_format.py`
  的 `TestShape` 与各接入点断言全部继续通过）；建议段只经新增关键字 `commands=` 触发。
- 错误首行文本不改（用户熟悉、既有断言依赖）；建议段**追加在 `Docs:` 之后**。
- 每条建议命令必须真实存在、可直接粘贴执行：不写占位符（不写 `<n>` / `<path>`）、不带未定义的参数。
- `suggestions.py` 只依赖 `pydantic` + stdlib（入口层模块，不导入运行栈）；`errors.py` 仍只依赖
  `click` + 同层 `suggestions`。
- 注释与文档中文；表级不变量在导入期显性失败（fails loud at load）。

**Never:**
- 不改 `console.py` / `http.py` / `doctor.py` / `wiring.py` 的调用点（不在本 lane）。
- 不改 `docs/errors.md` 既有标题（`三、CLI 与启动期错误` 等锚点被 `ANCHOR_CLI_ERRORS` 与测试钉住），
  只新增小节与表格。
- 不把建议段塞进状态行 / WARNING / 进度提示（那些不是错误）。
- 不引入新依赖、不联网、不调真实 API。

## Code Map

- `src/heagent/cli/suggestions.py` — **新建**。`CommandSuggestion`（`command` + `when`）、`ErrorScenario`
  （`key` / `label` / `keywords` / `suggestions`）、`SCENARIOS` 常量表（10 个场景 + 兜底）、
  `detect_scenario(message)`（按表序取首个关键词命中）、`suggest_commands(message, *, scenario=None)`
  （返回 ≥2 条，未知走兜底）、`MIN_SUGGESTIONS` / `FALLBACK_SCENARIO`。
  关键词按「边界感知」正则匹配（`port` 不命中 `support` / `reports`）。
- `src/heagent/cli/errors.py` — **扩展**：`with_hints(..., commands=None)` 追加 `Try these commands:` 段；
  新增 `with_command_hints` / `exit_with_command_hints` / `report_with_command_hints`（按消息自动选场景）；
  建议段 <2 条抛 `ValueError`（与 `options` 空列表同口径）。
- `src/heagent/cli/console.py`（禁改，接线目标）：`:206`（`invalid --resume session id`）、`:246`
  （`[mcp config error]`）、`:467`（`[replay] no events`）三处 `exit_with_hints` / `report_with_hints`。
- `src/heagent/cli/http.py`（禁改，接线目标）：`:400/:406/:412/:418`（`embedded_http_error_message`
  四类启动异常）、`:692/:731/:737/:743`（`http-server` 子命令的同一批异常）。
- `src/heagent/cli/wiring.py`（禁改，接线目标）：`:101/:103`（provider 配置错误）。
- `docs/errors.md` — **独占**：扩展「CLI 错误块怎么读」的示意块，并在「三、CLI 与启动期错误」下新增
  `### 建议命令` 小节（场景表 + 每类错误的建议示例）。
- `tests/test_cli_suggestions.py` — **新建**：场景覆盖、命令反射校验、兜底、相关性、渲染形态、文档一致性。
- `tests/test_cli_error_format.py` — **扩展**：向后兼容（`commands=None` 逐字等同旧输出）、新增入口的
  形态与 `<2` 条显性失败、既有出口不回归。

## Tasks & Acceptance

**Execution:**
- [x] `suggestions.py` — 场景表 + 匹配 + 兜底 — 建议的唯一数据源
- [x] `errors.py` — 追加建议段 + 三个新入口 — 向后兼容的渲染面
- [x] `docs/errors.md` — 「建议命令」小节 + 块读法 — 让 `Docs:` 链到的地方讲清建议段
- [x] `tests/test_cli_suggestions.py` — 新建 — 场景/反射/兜底/相关性
- [x] `tests/test_cli_error_format.py` — 扩展 — 旧格式不回归 + 新入口形态

**Acceptance Criteria:**
- Given 任一已声明场景的错误文本，when `suggest_commands(text)`，then 返回 ≥2 条命令，且每条都能
  在 CLI 子命令表 / 斜杠注册表里找到（反射校验），`--flag` 也在该命令的参数表里。
- Given 端口类错误（含 `bind` / `port`），then 建议含 `heagent http-server --port …`；
  Given 沙箱后端不可用，then 含 `--sandbox passthrough`；Given WS 缺 token，then 含 `--no-ws`。
- Given 完全无法识别的错误文本，when 取建议，then 恰好是兜底 `heagent doctor` + `/help`（≥2 条）。
- Given `with_hints("boom", options=("a","b"), anchor="x")`（不传 `commands`），then 输出与 64.5 逐字
  一致（5 行、无建议段）。
- Given `with_command_hints(...)`，then 首行仍是原消息、`Try:` / `Docs:` 顺序不变、建议段在 `Docs:` 之后。
- Given `docs/errors.md`，then `ANCHOR_CLI_ERRORS` 仍能按 slug 命中，新增 `### 建议命令` 存在，且每个
  场景的 `label` 都出现在文档里。

## Implementation Notes

**场景表（10 个，每场景 ≥2 条命令；顺序即匹配优先级，更具体的在前）：**

| key | label | 触发关键词（节选） | 建议命令 |
| --- | --- | --- | --- |
| `credentials` | 凭据缺失 | `api key` / `api_key` / `credential` / `401` | `heagent init --interactive`、`heagent doctor`、`/provider` |
| `ws_token` | WS 对外缺 token | `ws_auth_token` / `bearer token` / `auth-enforcing` | `heagent run --no-ws`、`heagent http-server --no-ws`、`heagent doctor` |
| `port` | 端口占用/绑定失败 | `port` / `bind` / `address already in use` | `heagent http-server --port 9102`、`heagent http-server --ws-port 9202`、`heagent doctor` |
| `sandbox` | 沙箱后端不可用 | `sandbox` / `firejail` / `docker` / `winjob` | `heagent run --sandbox passthrough "hi"`、`heagent doctor` |
| `mcp` | MCP 配置/连接失败 | `mcp` / `.mcp.json` | `heagent doctor`、`/mcp-prompt` |
| `skill` | 技能/工作流包不可用 | `skill` / `workflow role` / `workflow package` | `/goal doctor`、`heagent doctor`、`/help` |
| `cron` | 定时任务失败 | `cron` / `job store` / `schedule` | `/goal auto`、`heagent doctor` |
| `session` | 会话 id 非法/缺失 | `session` / `--resume` / `replay` | `/clear`、`heagent run "hi"` |
| `provider` | provider 未配置/切换失败 | `provider` / `routing pool` / `not supported by any configured account` | `/provider`、`/model auto`、`heagent doctor` |
| `config_invalid` | 配置键非法 | `invalid value` / `cannot parse` / `.env` / `config` | `heagent doctor`、`heagent init --interactive` |
| `unknown`（兜底） | 未识别场景 | — | `heagent doctor`、`/help` |

**设计取舍：**

- 关键词用**短语级**而非单词级：裸 `token` 会同时命中「WS token 缺失」与「token 预算」，因此表里写
  `ws_auth_token` / `bearer token` / `auth-enforcing`。宁可少命中走兜底，也不要给出方向错的三条命令。
- 匹配顺序 = 表序，首命中即返回；`credentials` 排第一是因为「No API key configured for provider X」
  同时含 `api key` 与 `provider`。
- 建议段用 `  Try these commands:` 抬头、条目 `    - <command>  # <何时用>`；`#` 在 bash / PowerShell
  里都是注释符，粘贴整行可直接执行。
- 表级不变量（每场景 ≥2 条、key 唯一非空、命令非空）在 `suggestions.py` 导入期校验，坏表当场抛错，
  不把「只有一条建议」的畸形块写给用户。

**需 orchestrator 接线的调用点（本 lane 禁改）：**

| 文件:行 | 现状 | 目标 |
| --- | --- | --- |
| `src/heagent/cli/console.py:206` | `exit_with_hints(...)`（`invalid --resume session id`） | `exit_with_command_hints(...)` |
| `src/heagent/cli/console.py:246` | `report_with_hints(...)`（`[mcp config error]`）+ `raise SystemExit(1)` | `report_with_command_hints(...)` |
| `src/heagent/cli/console.py:467` | `report_with_hints(...)`（`[replay] no events`） | `report_with_command_hints(...)` |
| `src/heagent/cli/http.py:400/406/412/418` | `with_hints(...)`（`embedded_http_error_message`） | `with_command_hints(...)`，并同批改 `console.py` 里打印该消息的调用方 |
| `src/heagent/cli/http.py:692/731/737/743` | `exit_with_hints(...)`（`http-server` 四类启动异常） | `exit_with_command_hints(...)` |
| `src/heagent/cli/wiring.py:101/103` | `report_with_hints(...)`（provider 配置错误） | `report_with_command_hints(...)` |
| `tests/test_architecture_contracts.py:741-758` | cli 布局白名单 | 加 `"suggestions",`（字母序在 `slash` 与 `terminal` 之间） |
| `docs/frame.md` | cli 子模块表 / 目录树 | 补 `suggestions.py` 一行 |

## Verification

**Commands:**
- `/workspace/.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_cli_suggestions.py tests/test_cli_error_format.py -q`
  → **78 passed**（新文件 `test_cli_suggestions.py` 52 例 + 既有 `test_cli_error_format.py` 26 例，其中新增 9 例）
- `python -m pytest tests/test_cli.py -q` → **45 passed**（`errors.py` 被 console/http 导入，回归面复核）
- `python -m pytest tests/test_cli_provider_build.py tests/test_mcp_cli.py tests/test_cli_http.py -q`
  → **112 passed**（provider 配置错误 / MCP / HTTP 启动错误三个既有接入点未回归）
- `ruff check` / `ruff format --check` 四个文件 → 全绿；`mypy src/heagent/cli/suggestions.py src/heagent/cli/errors.py`
  → `Success: no issues found`
- `python -m pytest tests/test_architecture_contracts.py -q` → **2 failed / 36 passed**，两条都是**布局白名单**：
  - `test_cli_package_layout_is_pinned`：实际多出 `cron_cmd` / `progress` / `suggestions` / `wizard`
    （前三个属其它 lane，`suggestions` 属本 lane）；
  - `test_shared_layer_layout_is_pinned`：`config/` 多出 `validation`（**非本 lane**，本 lane 未碰 config/）。
  两处都在本 lane 禁改清单内，接线清单已登记。

**实测口径：**
- 场景 **10** 个（+1 兜底），每场景 **2–3** 条命令，共 28 条条目 / **16** 条去重命令，全部通过反射校验：
  9 条 `heagent <sub>`（`run` / `init` / `doctor` / `http-server`）+ 7 条 `<slash>`（`provider` /
  `model` / `mcp-prompt` / `goal` / `clear` / `compact` / `help` 中实际用到的 7 条），`--port` /
  `--ws-port` / `--no-ws` / `--sandbox` / `--interactive` 逐个对到该 click 命令的参数表。
- `docs/errors.md`：新增 `### 建议命令`（slug `建议命令`）+ 场景表 11 行；`ANCHOR_CLI_ERRORS` 仍命中。
- 输出样例（端口/绑定类错误块尾三条命令）与文档示例逐字一致。

## Review Triage Log

- 2026-11-18 quick lens（本批 2 条 patch）：
  - `ws_token` 场景建议的 `heagent run --no-ws` / `heagent http-server --no-ws` **实测无效**：启动校验作用于
    `Settings`，早于本次进程的 `--no-ws` 覆盖生效 ⇒ 换成 `heagent init`（生成含 `WS_AUTH_TOKEN` 说明的
    用户级模板）+ `heagent doctor`，`docs/errors.md` 补一行「`--no-ws` 不能绕过这道校验」。
  - `config_invalid` 是死场景：真实报文 `Error: configuration could not be loaded: ValidationError: …`
    因关键词边界（`config` 后接 `u`）落到兜底 ⇒ 补 `validationerror` / `could not be loaded` 关键词，
    样例改用真实报文而不是手写串。
- false：`Try these commands:` 已接到 6 类真实出口（console / http / wiring），首行文本与退出码不变；
  `port` 不误命中 `support` / `export` / `reports`；既有「描述 + Try + Docs」三段块逐字不回归。
- 集成：`console.py` 3 处、`http.py` 10 处、`wiring.py` 4 处调用点已由 orchestrator 换成
  `*_with_command_hints`（这些文件不在本 story 的写权限内）。
