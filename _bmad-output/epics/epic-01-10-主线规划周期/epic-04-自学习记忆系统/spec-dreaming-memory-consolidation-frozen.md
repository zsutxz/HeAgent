---
title: 'Dreaming 模式（离线记忆巩固）'
type: 'feature'
created: '2026-08-11'
baseline_commit: '169b8bb'
status: 'done'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/epics/epic-01-10-主线规划周期/epic-04-自学习记忆系统/spec-dreaming-memory-consolidation.md'
  - '{project-root}/docs/frame.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** HeAgent 自学习闭环仅在线、被动（对话中临时调 memory 工具落盘），缺空闲时自主整理/巩固——facts 不去重、skills 过期不清理、经验不提炼。当前无 dreaming 模式。

**Approach:** 新增 `DreamScheduler`（双触发：cron 时刻 + idle 超时，共用同一 tick 循环），到点起一个角色化 `SubAgent(role="dreamer")`，对近期 session 历史 + `skill_curate` 过期清单做巩固（去重/提炼/查证），经 memory 工具回写四库，下个会话 `_build_system()` 自然注入。

## Boundaries & Constraints

**Always:**
- dreamer 是角色化 `SubAgent`，工具面由 `RoleSpec.allowed_tools` 白名单 + `blocked_tools` 黑名单**双层**限定（呼应工作区路径围栏的双层纵深防御惯例）。
- dreamer **不持 `file_read`**：近期 session 历史由 `DreamScheduler` 预加载、截断、拼进初始 prompt（最小权限）。
- `DreamScheduler` tick **模仿而非塞进 `CronScheduler`**——dream 不进 `JobStore`、不是用户 prompt；两者可并存于交互模式后台。
- `dream_enabled` **默认 `False`**（opt-in）；`dream_max_iterations` 用独立预算（默认 20），不复用全局 `max_iterations`。
- `DreamScheduler.stop()` 必在 `stop_timeout` 内返回（对齐 sandbox/MCP/cron 三处同构关停硬上界）。
- 安全声明**如实落代码注释**：`PolicyEngine`/`RoleSpec`/web 围栏均非真正安全边界（与 CLAUDE.md 文首立场一致）。

**Ask First:**
- 若发现现有 `RoleSpec` 不支持所需白名单语义 → HALT 问用户（不静默改 RoleSpec 契约）。
- 若 idle 计时需要改 REPL 同步 `input()` → HALT（spec 明确 defer 异步 input 重构）。

**Never:**
- 不集成 OS 级沙箱（用户选定不等；立场：未来 OS 沙箱就绪后 dreamer 须迁移进沙箱）。
- 不加 dream 产出的用户 review 闸（dream 直接经 memory 工具回写）。
- dreamer 不持 `shell`/`file_write`/`file_read`/`task_delegate`/`task_parallel`/`git_*`/`cron_*`。
- 不做 dream 递归（dream 内不再 delegate）。
- 不做 dream 历史 dashboard（仅 `EventBus` 事件 + 日志）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| cron 触发 | `dream_enabled=True`, cron 时刻命中, 无活跃 dream | 起 dreamer SubAgent, 发 `dream_start` | `_dreaming` 中则跳过 |
| idle 触发 | 距上次 run 结束 ≥ `dream_idle_minutes`, tick 检查 | 起 dreamer SubAgent | `dream_idle_minutes=0` 禁用 idle 触发 |
| 工具白名单 | LLM 请求 `shell`/`file_write` | `PolicyViolation` 拦截 | dreamer 拿不到这些工具 |
| web 注入 | `web_fetch` 返回命中注入签名 | **当前无端到端围栏**（返回直接进上下文）；`guard_content` 函数级可用但未接入 `web_fetch` | 降级：诚实声明无围栏，端到端接入 deferred（见 deferred-work） |
| 关停 | `DreamScheduler.stop()` | `stop_timeout` 内返回 | dream 进行中则取消 SubAgent |

</frozen-after-approval>

## Code Map

- `src/heagent/memory/dream.py` — **新增** `DreamScheduler`（双触发 tick + idle 计时 + dreamer SubAgent 装配 + EventBus 事件 + stop 硬上界）
- `src/heagent/engine/roles.py` — **新增** `dreamer` 内置 `RoleSpec`（allowed/blocked 双层 + 巩固 system 提示词）
- `src/heagent/config.py` — **新增** `dream_enabled`/`dream_cron`/`dream_idle_minutes`/`dream_max_iterations`/`dream_session_lookback`
- `src/heagent/cli.py` — 交互模式 `_run_chat` 装配 `DreamScheduler` 后台 task + `finally` stop
- `src/heagent/engine/observability.py` — `dream_start`/`dream_end` 事件类型（若现有 `EngineEvent` 不覆盖则扩展）
- `src/heagent/context/session.py` — `DreamScheduler` 读近期 session（预注入 prompt，需确认读取接口）
- `tests/test_dream.py` — **新增** AC1–AC9 测试

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/config.py` -- 加 5 个 `dream_*` 配置项（`dream_enabled` 默认 `False`）-- opt-in 门控
- [x] `src/heagent/engine/roles.py` -- 加 `dreamer` RoleSpec（allowed 白名单 `fact_add`/`profile_update`/`skill_create`/`skill_update`/`skill_list`/`skill_curate`/`skill_archive`/`web_fetch` + blocked 黑名单 `shell`/`file_write`/`file_search`/`content_search`/`cron_*`/`task_delegate`/`task_parallel`/`git_*` + 巩固 system 提示词）-- 最小权限角色
- [x] `src/heagent/memory/dream.py` -- `DreamScheduler`（双触发 tick + `last_active_ts` idle 计时 + dreamer `SubAgent` 装配 + 近期 session 预注入 prompt + `dream_start`/`dream_end` 事件 + `_dreaming` 互斥 + `stop()` 硬上界）-- 核心
- [x] `src/heagent/engine/observability.py` -- 加 `dream_start`/`dream_end` 事件（若需）-- 观测（**无需改动**：EventBus.publish 接受任意 event_type 字符串，dream_start/dream_end 直接复用现有 EngineEvent 模型）
- [x] `src/heagent/cli.py` -- `_run_chat` 启动 `DreamScheduler` 后台 task + `finally` `stop()` -- 装配
- [x] `tests/test_dream.py` -- AC1–AC9 测试（含 `StubProvider`、`dream_enabled=False` 零回归）-- 验收

**Acceptance Criteria:**
- AC1: Given `dream_enabled=True` 且 cron 时刻命中, when `DreamScheduler` tick, then 发 `dream_start` 事件并起 dreamer SubAgent。
- AC2: Given 距上次 run ≥ `dream_idle_minutes`, when tick, then 触发 dream；`dream_idle_minutes=0` 时 idle 触发禁用。
- AC3: Given dream 进行中, when 再次命中触发条件, then 不起第二个 dream（`_dreaming` 互斥）。
- AC4: Given dreamer 角色, when LLM 请求 `shell`/`file_write`/`task_delegate`, then `PolicyViolation` 拦截。
- AC5: Given dream 经 `fact_add`/`skill_create` 落盘, when 下个会话 `_build_system()`, then `<memory>`/`<skills>` 含 dream 新增条目。
- AC6（降级，2026-08-11 human renegotiate）: Given `guard_content` 对 web 内容调用, when 命中注入签名, then 标记 warning 透传（函数级复用，`is_error=False`，零回归）。**端到端**（dreamer→`web_fetch`→返回经 `guard_content`）**当前未实现**——`web_fetch` 返回路径未接 `guard_content`（仅 MCP 工具经 `bridge_result`），dreamer 联网返回内容无围栏；端到端接入 deferred（见 deferred-work）。
- AC7: Given `dream_enabled=False`（默认）, when 运行, then 无 tick、无事件、现有行为零回归。
- AC8: Given `DreamScheduler.stop()`, when dream 进行中, then `stop_timeout` 内返回。
- AC9: Given `pytest`/`ruff`/`mypy`, when 运行, then 全绿 / 零新增 / clean。

## Spec Change Log

### 2026-08-11 · AC6 端到端降级（step-03 内 human renegotiate）

- **Trigger**: step-03 实现后发现 `web_fetch` 返回路径未接 `guard_content`（仅 MCP 工具经 `bridge_result` 走围栏），原 AC6「dreamer 调 `web_fetch` → `guard_content` 标记透传」端到端不成立；spec 立场段把「web 返回启发式标记」列为缓解之一，与实现矛盾。
- **Amended**: AC6 降级为「`guard_content` 函数级复用（零回归）」；端到端接入 deferred-work；I/O Matrix「web 注入」行 + Design Notes + 代码注释（`dream.py` / `roles.py`）如实声明「`web_fetch` 当前无注入围栏」。frozen 块 I/O Matrix 改动经 human 批准（用户选「诚实降级 AC6」）。
- **Avoids**: 代码/spec 声称一个不存在的 `web_fetch` 围栏，误导为「dreamer 联网已有注入围栏」（违背 CLAUDE.md 教训 4「安全边界必须诚实声明」）。
- **KEEP**: `web_fetch` 的 DAG/角色白名单/双触发/EventBus idle/stop 硬上界实现均不变；仅声明层诚实化。

## Design Notes

- **双触发共用 tick**：idle 触发不改 REPL 同步 `input()`，仅检查"距上次 run 结束时长"（覆盖 run 之间间隙，不覆盖 input 等待期间）；异步 input 重构 out-of-scope。
- **dreamer 不持 `file_read`**：`DreamScheduler` 预加载最近 `dream_session_lookback` 个 session 消息截断注入 prompt，dreamer LLM 自行消化提炼。
- **安全张力**：dreaming = 无人监督 + 联网 + 改持久记忆（被污染网页可跨会话污染后续对话）。完整风险/缓解/硬立场见同目录 `spec-dreaming-memory-consolidation.md` 立场段（frontmatter context 引用）；代码注释须如实声明 `PolicyEngine`/role 围栏非真边界，**且 `web_fetch` 当前无注入围栏**（端到端 deferred），不制造"已安全"假象。

## Verification

**Commands:**
- `pytest tests/test_dream.py -v` -- expected: AC1–AC9 全绿
- `pytest` -- expected: 零回归（全量绿）
- `ruff check src tests` -- expected: 零新增
- `mypy src` -- expected: clean

## Suggested Review Order

**核心调度器（设计意图 · 双触发 · 互斥 · 关停）**

- 入口：双触发设计 + DAG 合规 + 诚实安全立场（模块 docstring）
  [`dream.py:81`](../../../src/heagent/memory/dream.py#L81)

- 双触发评估：cron 优先、idle 阈值、`_dreaming` 互斥早返
  [`dream.py:216`](../../../src/heagent/memory/dream.py#L216)

- dream 执行：互斥置位入 try、dream_start/end 事件、finally 重置 idle（审查 #2/#3）
  [`dream.py:242`](../../../src/heagent/memory/dream.py#L242)

- 关停硬上界：cancel + bounded wait + 超时记 ERROR（对齐 CronScheduler）
  [`dream.py:187`](../../../src/heagent/memory/dream.py#L187)

**fail-fast 配置校验**

- 构造期校验 cron：5 字段 + 字段合法，避免每 tick 刷屏 / 6 字段静默（审查 #4/#5）
  [`dream.py:355`](../../../src/heagent/memory/dream.py#L355)

**session 预注入（最小权限 · 时间序）**

- 按 session.timestamp 降序取真正最近 N 个（审查 #1——list_sessions 字母序不反映时间）
  [`dream.py:312`](../../../src/heagent/memory/dream.py#L312)

- SessionStore 新方法：按落盘 timestamp 排序，支撑 dream 取近期 session
  [`session.py:90`](../../../src/heagent/context/session.py#L90)

**角色与工具围栏**

- dreamer RoleSpec：allowed/blocked 双层 + 独立迭代预算
  [`roles.py:162`](../../../src/heagent/engine/roles.py#L162)

- 巩固 system prompt：去重/提炼/查证/归档 + web 批判性对待声明
  [`roles.py:115`](../../../src/heagent/engine/roles.py#L115)

**装配与配置**

- 5 个 dream_* 配置项（dream_enabled 默认 False = opt-in）
  [`config.py:111`](../../../src/heagent/config.py#L111)

- 组合根注入 dream_runner 闭包（memory/ 不导入 agent/，DAG 合规）
  [`cli.py:389`](../../../src/heagent/cli.py#L389)

- 交互模式装配 DreamScheduler 后台 task + finally stop
  [`cli.py:473`](../../../src/heagent/cli.py#L473)

**测试**

- AC1–AC9 + 审查 patch 回归（fail-fast cron / 端到端 start-tick-stop / 失败 idle 重置）
  [`test_dream.py:1`](../../../tests/test_dream.py#L1)
