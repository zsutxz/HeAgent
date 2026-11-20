---
title: 'Story 62.7 消除魔法数字'
type: refactor
ticket: 7
created: '2026-11-17'
status: done
baseline_revision: 'f32acc7'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'docs/frame.md'
  - '_bmad-output/Goal-2-v6/tickets/epic-62-代码架构重构/epic-62-代码架构重构.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 票面要求「代码裸数字（0/1/-1 除外）全部收敛为具名常量」，verify 写「配置值全部定义于
常量模块并有注释说明」。勘测（baseline f32acc7，AST 全仓扫描）判定**字面口径不成立**：

- 裸数字（非 0/1/-1）共 **506 处 / 113 文件**，按上下文归类后其中
  **89 处是具名常量的定义右值**、**55 处是 Settings `Field(default=…)` 配置默认**、
  **26 处是协议映射表值**（HTTP 状态码）、**67 处是索引/切片**（`run_id[:8]`）——
  这些要么已是答案，要么抽常量为纯噪音。
- 真实候选 ≈ **324 处**；其中「有语义的阈值」只有 **41 处**（比较运算里的魔法值）。
- 现状已有 **79 个模块级大写常量**；若字面执行「全部收敛」，会再产 300+ 常量，
  可读性净损失且极易被下一轮改动打回。

**Ruling（2026-11-17 用户「按你建议」= 门禁化）：** 不做一次性大清扫，改为**持续约束**：
在 `ruff.toml` 的 `select` 里启用 `PLR2004`（magic-value-comparison，只盯比较运算），
本期把全部命中清零。口径三分：

1. **语义阈值 → 模块级具名常量**（cron 五字段、HTTP 状态码分档、端口上限、预览宽度、
   重叠比例、provider 遍历上限、毫秒进位等）——常量就近定义在被使用模块，不新建统一常量模块
   （跨层共享会破坏 `network` 不依赖配置面/运行栈的既有契约）。
2. **结构性字面量 → 就地 `# noqa: PLR2004`**（成对引号的最小长度 2、`/mcp prompt` 的
   命令参数个数等）。同一「成对引号」模式在 config/goal/network 多模块重复，但依赖方向
   禁止它们共享常量 ⇒ 逐处 noqa，不制造跨层依赖。
3. **调用点协议字面量 → 保持字面量 + `# noqa`**（`http_server/app.py` 的 405/404）。
   实测这类不能抽常量：契约基线 `transport_errors.json` 按 `status_code=<字面量>` 采集
   `status_source=call_site_literal`，抽常量会让静态扫描失去来源（首轮实测即红）。
4. **tests/ 与 scripts/ 豁免 `PLR2004`**：断言与验收里的期望值字面量是正文
   （与既有 `S105` 假 token 豁免同理）。

</frozen-after-approval>

## Tasks & Acceptance

**Execution:**

- [x] `ruff.toml` — `select` 加 `PLR2004`；`tests/**` 与 `scripts/**` 的 per-file-ignores 各加一条
- [x] 语义阈值提常量（14 个模块）：`cli/display.py`（`_THOUSAND`/`_MILLION`）、
      `cli/skill_merge.py`（`_SKIP_CHOICE`/`_DESCRIPTION_PREVIEW_CHARS`）、`cli/goal/commands.py`、
      `cron/expr.py`、`tools/builtins/cron.py`、`memory/dream.py`（各 `_CRON_FIELD_COUNT`）、
      `cron/expr.py`（`_SUNDAY_ALIAS`）、`goal/application.py`（`_EXECUTION_PROTOCOL_ARITY`）、
      `goal/document.py`（`_LEGACY_GOAL_ID_LENGTH`）、`goal/workflow_loader.py`（`_MIN_CELLS_WITH_EPIC_REF`）、
      `gui/screens/cron.py` / `gui/screens/skills.py`（预览宽度）、`memory/compact.py`
      （`_DUPLICATE_OVERLAP_RATIO`）、`providers/router.py`（`_MAX_PROVIDER_WALK`）、
      `pub/event_lines.py`（`_MS_PER_SECOND`）、`network/origin.py`（`_MAX_PORT_NUMBER`/`_HTTP_DEFAULT_PORT`）、
      `network/ws_server.py`（`_MAX_EVENT_ID_DIGITS`）、`network/http_server/middleware.py`
      （`_ERROR_STATUS_MIN`）、`providers/openai.py`（`_HTTP_BAD_REQUEST`）、`providers/retry.py`
      （`_HTTP_TOO_MANY_REQUESTS`/`_HTTP_NOT_FOUND`/`_HTTP_SERVER_ERROR_MIN`/`_HTTP_SERVER_ERROR_MAX`）、
      `tools/builtins/web_search_engine.py`（`_HTTP_REDIRECT_MIN/MAX`/`_HTTP_CLIENT_ERROR_MIN`）
- [x] 结构性字面量就地 `# noqa: PLR2004`（7 处）：`config/catalog/envscan.py`、`config/envfile.py`×2、
      `goal/git_port.py`、`goal/workflow_loader.py`、`network/exposure.py`、`network/http_server/app.py`×2（405/404）
- [x] `cli/interactive.py`（`_MCP_PROMPT_ARITY`）、`tools/sandbox/session.py`（`_MARKER_MIN_FIELDS`）

**Verification:**

- [x] `ruff check --select PLR2004 src` → 0 命中
- [x] `ruff check src tests scripts` / `ruff format --check` / `mypy src` 全绿（209 文件）
- [x] 全量 pytest（不带 --cov）：4387 passed / 5 failed（5 红全为 `test_setup_ws_external.py`，
      `verify_baseline.py` 判 environmental）
- [x] 契约基线 `scripts/contract_snapshot.py --check` 四份一致（含 `transport_errors.json` 的
      `call_site_literal` 来源未被常量破坏）

**Implementation Notes（执行期账）:**

- 首轮实测的两处反例（已写进 Intent 的口径 3）：① 把 `http_server/app.py` 的 `status_code=405` 抽成常量后
  `contract_snapshot.py --check` 立刻红——`transport_errors.json` 的 `status_source` 从
  `call_site_literal` 退化为 `None`（该码被登记为「调用点字面量」）⇒ 协议状态码在调用点保持字面量；
  ② `network/origin.py` 把常量命名为 `_MAX_TCP_PORT` 时触发
  `test_live_files_hold_no_reference_to_the_removed_tcp_entry`（大小写不敏感匹配 `TCP_`）⇒ 改为
  `_MAX_PORT_NUMBER`
- noqa 只有 7 处，提常量 22 处（跨 20 个模块）：判据是「该数字是否有业务语义」；`len(x) >= 2`
  这类结构判断在多模块重复出现，宁可逐处 noqa 也不跨层共享常量（`network` 不得依赖 `config`/运行栈）
- `memory/compact.py` 的重叠比例从内联表达式提为局部变量 + 阈值常量（可读性顺带改善，
  行为逐字等价）
- 门禁价值：`PLR2004` 此后随 CI 的 `ruff check` 常驻，新增魔法值比较在 PR 阶段即被拦下
