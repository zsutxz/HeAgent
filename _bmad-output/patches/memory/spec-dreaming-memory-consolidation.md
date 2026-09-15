# Spec：Dreaming 模式（离线记忆巩固）

## source
- 路线来源：用户经差距分析（对比 Claude Code / hermes-agent）选定 dreaming 为自学习闭环的**离线阶段**——HeAgent 现有自学习是在线、被动的（LLM 对话中临时调 `fact_add`/`skill_create`），缺"空闲时自主整理/巩固"。
- 参考概念：自学习 agent 的「做梦 / idle memory consolidation」范式（空闲期对记忆做去重、提炼、过期清理、事实查证）。
- 落地基础：HeAgent 现有 `CronScheduler`（tick 调度）、`SubAgent` + `RoleSpec`（角色化隔离）、`memory/` 四库（facts/skills/profile/soul）、`EventBus`（观测）。
- 用户决策（2026-08-11）：①触发=两者都要（cron + idle）；②范围=整理 + 提炼新技能 + web 查证；③安全=先用 PolicyEngine+role 限定，不等 OS 级沙箱。

## in scope（做）
1. **`memory/dream.py` 新增 `DreamScheduler`**：后台 asyncio tick 循环，复用 `CronScheduler` 的周期检查模式（每 `cron_tick_seconds` 秒一次），检查两个触发条件，任一命中且当前无活跃 dream 则起一次 dream：
   - **cron 触发**：命中 `dream_cron` 表达式（默认 `0 3 * * *` 凌晨低峰）。
   - **idle 触发**：距上次 `AgentLoop.run`/`run_stream` 结束超过 `dream_idle_minutes`（默认 30；0 = 禁用 idle 触发）。
   - **互斥**：`_dreaming: bool` 守卫，dream 进行中再命中条件则跳过（同一时刻最多一个 dream）。
2. **`engine/roles.py` 新增 `dreamer` 内置角色**：`RoleSpec` 含巩固 system 提示词 + `allowed_tools` 白名单 + `blocked_tools` 显式黑名单（defense-in-depth 双层）。
   - **allowed**：`fact_add`、`profile_update`、`skill_create`、`skill_update`、`skill_list`、`skill_curate`、`skill_archive`、`web_fetch`。
   - **blocked**：`shell`、`file_write`、`file_search`、`content_search`、`cron_add`、`cron_remove`、`task_delegate`、`task_parallel`、`git_*`。
   - dreamer **不持 `file_read`**：近期 session 历史由 `DreamScheduler` 在起 dreamer 前预加载、截断、拼进初始 prompt（最小权限，dreamer 不自己翻文件）。
3. **dream 执行**：`DreamScheduler` 构造一个角色化 `SubAgent(role="dreamer")`，初始 prompt = 巩固指令 + 最近 `dream_session_lookback` 个 session 的消息（截断到 token 预算）+ `skill_curate` 过期清单；SubAgent 经 memory 工具回写四库，下次会话 `_build_system()` 自然注入巩固后的记忆。
4. **idle 计时**：`AgentLoop` 在每次 `run`/`run_stream` 结束时更新 `DreamScheduler.last_active_ts`（或经 `EventBus` 订阅 done 事件）；`DreamScheduler` tick 时比对 `now - last_active_ts`。
5. **CLI 装配**：交互模式 `_run_chat` 启动 `DreamScheduler` 后台 task（与 `CronScheduler` 同模式），`finally` 里 `stop()` 关停（带硬上界，对齐 `spec-cron-stop-timeout` / `spec-mcp-shutdown-timeout` 的同构关停立场）。
6. **观测**：`EventBus` 发布 `dream_start`/`dream_end`（含触发源 cron/idle、迭代数、写入的 memory 条目计数）；`LoggingObserver` 落日志。
7. **配置**（`config.py`）：`dream_enabled: bool = False`（**默认关**——无人监督后台跑是 opt-in）、`dream_cron`、`dream_idle_minutes`、`dream_max_iterations: int = 20`、`dream_session_lookback: int = 5`。
8. **测试** `tests/test_dream.py`：cron 命中触发 / idle 超时触发 / `_dreaming` 互斥不重入 / dreamer role 工具白名单（shell/file_write 被屏蔽、web_fetch 放行）/ dream 端到端（起 dream → 经 memory 工具写入 → 下个会话 `_build_system` 能见新 fact/skill）/ web_fetch 返回命中注入签名走 `guard_content` 标记透传（复用现有围栏，零回归）/ `dream_enabled=False` 零触发零回归。

## out of scope（不做 / deferred）
- ❌ **OS 级沙箱集成**——用户选定不等；当前接受「PolicyEngine+role 非真边界」风险（见立场段，未来 OS 沙箱就绪后 dreamer 应迁移进沙箱）。
- ❌ **dream 产出的用户 review 闸**——dream 直接经 memory 工具回写，不在下次会话前要求确认（用户选「先跑」）。
- ❌ **idle 触发的异步 input 重构**——idle 仅在「run 与 run 之间的间隙」经 tick 周期检查判定，**不改 REPL 同步 `input()`**（异步 input 是独立大改，另开 spec）。
- ❌ **递归「深度睡眠」**——单次 dream = 单个 SubAgent，dream 内不再 `task_delegate` 子 dream（blocked_tools 已禁）。
- ❌ **dream 历史记录 / 可观测 dashboard**——仅 `EventBus` 事件 + 日志，不做查询 UI（与 Epic 28 可观测性正交，未来合并）。
- ❌ **记忆写入的并发锁**——复用现有 store 同步语义（单线程 asyncio 下串行安全，见 deferred-work 2026-06-18 条核实）；若未来 store async 化需重评，届时 `tests/test_sub_agent.py::test_parallel_shared_skillstore_no_lost_usage_update` 类回归会变红提醒。

## AC（验收）
- **AC1**（cron 触发）：`dream_enabled=True` 且 cron 时刻命中时，`DreamScheduler` 起一个 dreamer SubAgent；`dream_start` 事件发布。
- **AC2**（idle 触发）：距上次 run 结束 ≥ `dream_idle_minutes` 时，下一 tick 触发 dream；`dream_idle_minutes=0` 时 idle 触发禁用。
- **AC3**（互斥）：dream 进行中再次命中触发条件（cron 或 idle）不再起第二个 dream。
- **AC4**（角色白名单）：dreamer SubAgent 的 `PolicyEngine` 仅放行 allowed 工具；`shell`/`file_write`/`task_delegate` 等被屏蔽（即便 LLM 请求也走 `PolicyViolation`）。
- **AC5**（巩固回写）：dream 产生的 `fact_add`/`skill_create` 等落盘到 memory 四库；下一个会话 `_build_system()` 注入的 `<memory>`/`<skills>` 含 dream 新增条目。
- **AC6**（web 围栏复用）：dreamer 调 `web_fetch` 返回内容命中注入签名时，走 `guard_content` 标记透传（与内置工具/MCP 同语义，零回归）。
- **AC7**（零回归）：`dream_enabled=False`（默认）时，`DreamScheduler` 不启动、无 tick、无事件，现有所有行为不变。
- **AC8**（关停有上界）：`DreamScheduler.stop()` 必在 `stop_timeout` 内返回（dream 进行中则取消 SubAgent，对齐三处同构关停硬上界）。
- **AC9**：pytest 全绿 / ruff 零新增 / mypy clean。

## 约束（硬）
- dreamer 是**角色化 `SubAgent`**，经 `parent_run_id` 继承父 `engine`；工具面**仅由 `RoleSpec.allowed_tools` 白名单 + `blocked_tools` 黑名单双层**限定（呼应工作区路径围栏的双层纵深防御惯例）。
- 近期 session 历史以 **prompt 预注入**方式供给 dreamer，dreamer **不持 `file_read`**（最小权限）。
- `DreamScheduler` 的 tick 调度逻辑**模仿而非塞进 `CronScheduler`**——dream 不是 `CronJob`（不进 `JobStore`、不是用户 prompt、有专属巩固流程）；两者可并存于交互模式后台。
- `dream_enabled` **默认 `False`**：dreaming 是 opt-in 能力，不为现有用户默认开启无人监督后台循环。
- dreamer 的 `max_iterations` 用独立的 `dream_max_iterations`（默认 20），不复用全局 `max_iterations=50`（dream 是辅助循环，预算更紧）。

## 立场（不变，须诚实声明）
- **dreaming = 无人监督下主动跑 + 改持久记忆 + 含联网（`web_fetch`）**，比交互式更危险：被污染的网页内容可经 prompt injection 写入记忆库，**影响后续所有会话**（攻击面是持久的、跨会话的）。
- 用户选定「先用 PolicyEngine + role 限定，不等 OS 级沙箱」。这与 CLAUDE.md 文首声明（`SafetyGuard`/`PolicyEngine`/`FirejailBackend`/MCP 围栏**均非真正安全边界**）存在**有意识的张力**：当前 dreaming 的安全依赖 (a) `RoleSpec` 工具白名单、(b) `PolicyEngine` 审批门、(c) `web_fetch` 的 `guard_content` 启发式围栏——三者皆为 defense-in-depth 标记/拦截，**非真正隔离**。
- **缓解（defense-in-depth，非真正边界）**：dreamer 工具白名单最小化（无 shell/file_write）、~~web 返回启发式标记~~（**未实现/deferred**——`web_fetch` 返回路径当前未接 `guard_content`，仅 MCP 工具经 `bridge_result`；见 `_bmad-output/patches/_meta/deferred-work.md`；该台账 2026-09-15 退役并删除）、`dream_enabled` 默认关、`dream_max_iterations` 紧预算、`EventBus` 事件可审计。
- **硬立场**：OS 级沙箱就绪后，dreamer SubAgent 必须迁移进沙箱执行（尤其联网 + 写记忆的组合）。在此之前，dreaming 不可在不可信内容/不可信网络下启用。本 spec **不制造「dreaming 已安全」假象**——与项目教训 4「安全边界必须诚实声明」一致。
