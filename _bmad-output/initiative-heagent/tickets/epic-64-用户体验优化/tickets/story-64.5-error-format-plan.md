---
title: 'Story 64.5 优化错误信息格式'
type: feature
ticket: 5
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
  - 'src/heagent/cli/console.py'
  - 'src/heagent/cli/http.py'
  - 'src/heagent/cli/wiring.py'
  - 'docs/errors.md'
---

## Intent

**Problem:** 票面要求用户可见错误统一为「描述 + 可用选项 + 文档链接」，且都要含可操作建议。现状：
CLI 有 **149 处** `err=True` 输出，其中真失败分支的文案形态各异——`[mcp config error] …`、
`invalid --resume session id: …`、`Error: WS server configuration is invalid: …`（来自
`click.ClickException`），多数只说「哪里错了」不说「可以怎么做」，也没有文档指向。

**Approach:** 只改**真失败分支**（不含状态行/进度公告/WARNING），把它们的出口收敛到一个新模块
`cli/errors.py`，输出三件事：原消息（保留原文，测试与用户习惯都能对上）+ `Try:` 选项列表 +
`Docs: docs/errors.md#<anchor>`。文案保持原文本作为首行，因此既有断言（`No API key configured` /
`mcp config error` / `invalid --resume session id`）继续命中。

**Verify 拆解：**
- 「格式统一易读」→ 所有接入点都由同一个函数生成，形状固定三行块。
- 「所有用户可见错误包含可操作建议」→ 每个接入点的 `Try:` 至少一条可执行动作（键名/命令/开关）。

## Boundaries & Constraints

**Always:**
- 原消息文本**逐字保留**在首行（`composition.py` 的 docstring 明确「消息文本即终端字节」）。
- 接入点仅限失败分支；`▶启动` / `✔完成` / WARNING / `[http] stopped` 等状态输出不动。
- 文档锚点必须存在于 `docs/errors.md`（同批校验，不留死锚）。
- 新增模块放 `src/heagent/cli/errors.py`，只依赖 `click`（入口层，不被下层导入）。

**Never:**
- 不改 `providers/composition.py` 的错误文案与异常类型（那是 providers 层契约）。
- 不给状态行/日志加 `Try:`/`Docs:`（会把正常输出污染成错误）。
- 不引入新依赖。

## Code Map

- `src/heagent/cli/errors.py` — 新建：`with_hints(message, options, anchor)` 纯函数 +
  `exit_with_hints(...)`（抛 `click.ClickException`）+ `report_with_hints(...)`（`click.echo` 到 stderr）。
- `src/heagent/cli/wiring.py:60-70` — `ProviderConfigError` → 按消息前缀给选项与锚点。
- `src/heagent/cli/console.py:205`（`invalid --resume session id`）、`:238`（`[mcp config error]`）、
  `:452`（`[replay] no events`）三处失败分支改为走 `errors`。
- `src/heagent/cli/http.py:377-384`（`embedded_http_error_message` 的四类异常）与 `:652/:687/:690/:694`
  的 `click.ClickException` 改为带选项与锚点。
- `tests/test_cli_error_format.py` — 新建：形状断言 + 每个接入点的 `Try:`/`Docs:` 存在性。
- `docs/errors.md` — 补「`Try:` / `Docs:` 行怎么读」一句说明（讲清 CLI 错误块的结构）。

## Tasks & Acceptance

**Execution:**
- [ ] `src/heagent/cli/errors.py` — 新建统一出口 — 唯一格式化点
- [ ] `src/heagent/cli/wiring.py` — provider 配置错误带选项 — 最高频的启动失败
- [ ] `src/heagent/cli/console.py` — 三处失败分支接入 — resume/mcp/replay
- [ ] `src/heagent/cli/http.py` — 四类启动异常接入 — 端口/依赖/token
- [ ] `tests/test_cli_error_format.py` — 新建 — 钉死形状与锚点存在性
- [ ] `docs/errors.md` — 补读法说明 — 让链接有落点

**Acceptance Criteria:**
- Given `heagent run --resume "bad/id"`，when 输出错误，then 依次含原消息、至少一条 `- ` 开头的
  可执行选项、一行 `Docs: docs/errors.md#…`。
- Given 未配置任何凭据时启动，when 读 stderr，then `No API key configured` 仍出现（既有断言不破），
  且其后有 `Try:` 与 `Docs:`。
- Given `WS_HOST=0.0.0.0` 且未配 token 启动 `http-server`，when 读 stderr，then 首行含原文
  `WS server configuration is invalid`，并给出「配 `WS_AUTH_TOKEN`」与「改回回环」两条选项。
- Given 全部接入点，when 逐个取锚点，then 每个 `#anchor` 都能在 `docs/errors.md` 里找到对应标题。
- Given `pytest tests/test_cli.py tests/test_cli_provider_build.py tests/test_mcp_cli.py -q`，
  then 全绿（沿用原断言）。

## Implementation Notes

## Implementation Notes

- 新增 `src/heagent/cli/errors.py`：`with_hints`（纯函数）/ `exit_with_hints`（ClickException）/
  `report_with_hints`（stderr，不退出）+ 常量 `ERRORS_DOC` / `ANCHOR_CLI_ERRORS`。
  `with_hints` 对空 `options` 抛 `ValueError`——宁可构造期炸，也不给用户畸形的 `Try:` 空列表。
- 接入点 8 处：`wiring.py` 的 provider 配置错误（按稳定子串给两组选项 + 中性兜底）、
  `console.py` 的 `--resume` / `[mcp config error]` / `[replay] no events`、
  `http.py` 的 `HTTP server failed to start` / `WS server configuration is invalid` /
  `WS server failed to start` / `missing 'aiohttp'`。四组选项抽成 `http.py` 模块级常量，
  避免默认 CLI 与 `http-server` 子命令两处文案漂移。
- 原消息逐字保留 ⇒ 既有断言全部继续命中（`pytest tests/test_cli.py … tests/test_cli_http.py`
  共 225 例通过）。状态行 / WARNING / `[http] stopped` 未改。
- 契约同步：`tests/test_architecture_contracts.py` 的 cli 布局白名单加 `errors`（字母序）；
  `docs/frame.md` 的子模块表与目录树各补一行。
- `docs/errors.md` 补「CLI 错误块怎么读」：说明 `Error: ` 前缀的两种来源、占位符要替换、
  `Docs:` 是仓库相对路径。

## Review Triage Log

- 2026-11-18 quick lens（1 个 reviewer，16 findings）：patch 8 / false 4 / maybe-false 4。
- patch：死锚测试恒真（原正则找 `anchor="…"` 字面量，而全部调用用常量 ⇒ 改为「实参只能是
  `ANCHOR_CLI_ERRORS`」）；`with_hints` 不校验空 options（补 `ValueError` + 用例）；
  provider 用例的期望值出现在消息本身、断言会被兜底分支满足（新增「不得落到兜底文案」的用例）；
  `http.py` 两组选项逐字重复（抽成 `_HTTP_STARTUP_OPTIONS` 等常量）；`docs/errors.md` 的「三行结构」
  与实际行数不符（改为「固定结构」并说明 `Error: ` 两种来源）；「每条都能直接照做」与 `<n>` 占位冲突
  （补「占位符需替换」）；兜底建议对非凭据类错误方向错（改为中性措辞，且不引用尚未实现的
  `heagent doctor`）；`console.py` / `http.py` 接入点无测试（补 `--resume` 与 `replay` 两条端到端用例）。
- false：`wiring.py` 删 `import click` 可能 NameError —— `ruff check`（F821）与 `mypy` 全绿即证；
  `CliRunner` 混合 stderr 的版本依赖 —— 测试改为 `result.output + result.stderr` 合并断言，实测 click
  8.5 通过；slug 规则自证 —— 文档标题与常量同仓同 PR 维护，人工可核，且 mkdocs strict 通过。
- maybe-false：`ERRORS_DOC` 是仓库相对路径（wheel 安装后不可解析）——已在文档写明该口径；
  `anchor=""` 合法（当前无调用点使用）；多行消息「首行」措辞（docstring 已改为「原样放在块首」）。

## Plan Change Log

## Review Triage Log

## Verification

**Commands:**
- `pytest tests/test_cli_error_format.py tests/test_cli.py tests/test_cli_provider_build.py tests/test_mcp_cli.py -q` -- expected: pass
- `pytest tests/test_architecture_contracts.py -q` -- expected: pass（新增 cli 模块不得引入反向依赖）
- `ruff check src tests scripts && mypy src` -- expected: pass
- `mkdocs build --strict` -- expected: pass（errors.md 改动）
