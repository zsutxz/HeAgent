---
title: 'Story 64.12 实现详细帮助命令'
type: feature
ticket: 12
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
  - 'src/heagent/cli/slash.py'
  - 'src/heagent/cli/interactive.py'
---

## Intent

**Problem:** 票面要求 `REPL /help <command>` 详细帮助可用，验收口径是「所有斜杠命令含语法、参数说明、
示例且格式统一」。实测现状（`src/heagent/cli/interactive.py:637-640`）只有列表版：

```text
Available slash commands:
  /compact  摘要并压缩当前会话上下文
  ...
```

`/help <command>` 的参数被彻底忽略——`_help(args)` 不看 `args`，敲 `/help goal` 与 `/help` 输出逐字相同。
注册表（`cli/slash.py`）只存 `(description, handler)`，没有任何可承载「语法 / 参数 / 示例」的位置，
所以详细帮助无处可取。

**Approach:** 两层改动，都不动命令面（不新增/不改名任何斜杠命令）：

1. `cli/slash.py`：给注册表加**命令元数据**。新增 Pydantic 模型 `SlashCommandInfo`
   （`name` / `description` / `usage` / `arguments` / `examples` / `custom`）与
   `SlashRegistry.register_command(...)`（元数据全为关键字参数、均可省略）；既有
   `register(name, description, handler)` 保持原签名并委派给 `register_command`，因此
   `cli/skill_merge.py:36` 与 `tests/test_cli.py:143` 的 3 参调用零改动。另加 `info()` /
   `commands()` / `suggest()`（`difflib` 近似名，stdlib）。本模块仍是**零 heagent 运行栈依赖**
   （只 pydantic + `pub.frontmatter` + stdlib），渲染与 click 一律留在 `interactive.py`。

2. `cli/interactive.py`：`_help` 按有无参数分叉到同一套渲染函数
   （`_render_help_list` / `_render_command_help`），列表版按名排序且列宽对齐，详情版固定四段
   （`/名字  描述` → `语法:` → `参数:` → `示例:`）；未知命令给错误 + `difflib` 建议（≥1 条，
   兜底不空）+ 提示敲 `/help`。八个内置命令（`provider` / `model` / `mcp-prompt` / `deferred` /
   `clear` / `compact` / `help` / `goal`）注册时补齐元数据；自定义命令（`.heagent/commands/*.md`）
   走同一渲染，参数段显式打印「自定义命令，无参数说明」，不渲染空块。

## Boundaries & Constraints

**Always:**
- `cli/slash.py` 保持零 heagent 依赖（只 pydantic + `heagent.pub.frontmatter` + stdlib）；handler 仍由
  `interactive.py` 以闭包注入。
- 向后兼容：`register(name, description, handler)` 的 3 参位置调用语义不变（`skill_merge.py`、
  `tests/test_cli.py` 现有调用不得破坏）。
- 输出走 `click.echo(..., err=True)`（与现有 `/help` 同一流向）；纯文本、无 ANSI 硬编码。
- 全部输出中文标签（`语法:` / `参数:` / `示例:`）+ 既有 `[前缀]` 纪律（`[help]`）。
- 列表版与详情版**共用同一注册表数据源**：列表的描述与详情首行描述逐字一致。

**Never:**
- 不新增、不改名、不删除任何斜杠命令（命令面冻结）；不改 handler 行为。
- 不改 `run` / `stream` / REPL 主循环与暂停恢复逻辑（`_help` 只换实现体）。
- 不动 `cli/console.py`、`cli/skill_merge.py`、`cli/display.py`、文档与契约测试（跨 lane）。
- 不引入新依赖；不自造 ANSI 样式。

## Code Map

- `src/heagent/cli/slash.py` — 新增 `SlashCommandInfo`(Pydantic) / `_Registration`(内部 dataclass) /
  `register_command()` / `info()` / `commands()` / `suggest()`；`register()` 委派；`_commands` 改存
  `_Registration`（私有，无外部消费者，实测 `grep _commands` 仅本文件）。
- `src/heagent/cli/interactive.py` — `_build_slash_registry` 的 8 个 `registry.register(...)` 调用改为
  `register_command(...)` 并补元数据；`_help` 改为分叉渲染；新增模块级 `_render_help_list` /
  `_render_command_help` / `_render_unknown_command` / `_help_argument_lines`。
- `tests/test_slash_help.py` — 新建：详情四段、列表、未知命令建议、自定义降级、注册表向后兼容。
- `tests/test_slash.py` — 追加一节注册表元数据用例（`info` / `commands` / `suggest` / 3 参兼容）。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/cli/slash.py` — 元数据模型 + `register_command` + `info`/`commands`/`suggest`，`register` 委派 — 主体
- [x] `src/heagent/cli/interactive.py` — 8 个内置命令补元数据 + `_help` 分叉 + 3 个渲染函数 — 主体
- [x] `tests/test_slash_help.py` — 新建 5 组用例 — 判据
- [x] `tests/test_slash.py` — 追加注册表元数据用例 — 判据

**Acceptance Criteria:**
- Given REPL 内敲 `/help`，then 输出 `Available slash commands:` + 按名排序的 `/<name>  描述` 列表 +
  一行 `/help <command>` 提示。
- Given `/help goal`，then 输出四段：`/goal  <描述>`、`语法:`、`参数:`、`示例:`，且参数段含全部
  goal 子命令名、示例段含 `/goal status`。
- Given 对**每个**内置命令（provider/model/mcp-prompt/deferred/clear/compact/help/goal）敲
  `/help <name>`，then 四段齐全且非空。
- Given `/help providr`（拼错），then 输出 `[help] Unknown slash command: /providr` +
  `[help] Did you mean: /provider` + `[help] Run /help to list all commands.`。
- Given 一个自定义命令（无 frontmatter 以外的元数据），when `/help <name>`，
  then 参数段打印「自定义命令，无参数说明」，示例段给出 `/<name>`，不出现空段。
- Given 只调 `registry.register(name, desc, handler)`（3 参），then 命令仍可 `has` / `dispatch` /
  `describe`，且 `/help` 详情不崩（元数据缺省 → 通用兜底文案）。

## Implementation Notes

- **兼容形态**：`register` 保持位置参数签名并委派 `register_command`；元数据全为关键字参数
  （`usage` / `arguments` / `examples` / `custom`），既有调用点不必改。
- **内部存储**：`_commands: dict[str, _Registration]`，`_Registration` 是 `dataclass(frozen=True)`，
  持 `info: SlashCommandInfo` + `handler`；跨模块只暴露 Pydantic 的 `SlashCommandInfo`。
- **建议兜底**：`difflib.get_close_matches(..., cutoff=0.5)` 命中即用；无命中时按「长度差 → 字典序」
  取 1 条，保证 64.12 要求的「≥1 条」不落空（与 64.13 的全局错误建议不是同一处，不重叠）。
- **自定义命令降级**：注册自定义命令时传 `custom=True`；无 `arguments` 时参数段打印
  「自定义命令，无参数说明（正文见 `.heagent/commands/<name>.md`，`$ARGUMENTS` 替换为本次参数）。」。
  非 custom 且无元数据（如 `skill-merge` 仍走 3 参 `register`）打印「未提供参数说明。」的同类兜底。
- **语法兜底**：未声明 `usage` 时渲染 `/<name> [参数]`，因此任何已注册命令都不会出现空的语法段。
- **不改渲染位置的理由**：`slash.py` 的零 heagent 依赖约束把它限定为数据层，click 渲染留在
  `interactive.py`，列表版与详情版共用同一组函数。
- 实测输出（`/help` / `/help goal` / `/help providr` / `/help loop` 直跑）与预期的四段格式逐字一致；
  自定义命令 `loop` 走降级分支，参数段给出 `.heagent/commands/loop.md` 路径。

## Verification

**Commands（实测）：**
- `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_slash_help.py tests/test_slash.py -q`
  → **55 passed**（4.3s）
- `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_cli.py -q` → **45 passed**
  （该文件用 3 参 `register`，验证向后兼容）
- `.heagent/tmp/py311-venv-linux/bin/python -m ruff check <4 个文件>` → All checks passed
- `.heagent/tmp/py311-venv-linux/bin/python -m ruff format --check <4 个文件>` → 4 files already formatted
- `.heagent/tmp/py311-venv-linux/bin/python -m mypy src` → Success: no issues found in 216 source files
- 行尾/BOM 核查：4 个文件 `CRLF=0`、无 BOM、末行有换行。

## Review Triage Log

- 2026-11-18 quick lens（本批 2 条 patch）：
  - 无元数据的非自定义命令（当前唯一 = `/skill-merge`，仍走 3 参 `register`）渲染出
    `语法: /x [参数]` + `参数: 无参数。` 的自相矛盾 ⇒ 语法兜底去掉 `[参数]`、参数兜底改
    「未提供参数说明。」，测试口径同步。
  - 自定义命令没有 `description` 时首行渲染成 `/bare  `（尾随空格、无描述）⇒ 补「（无描述）」兜底。
- false：`register(name, description, handler)` 三参向后兼容有 3 条测试钉住；`suggest` 在无近似名时
  仍给 ≥1 条；8 个内置命令四段齐全由参数化用例覆盖。
