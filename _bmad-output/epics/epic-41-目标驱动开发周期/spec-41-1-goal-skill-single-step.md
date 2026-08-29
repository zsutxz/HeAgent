---
title: 'Story 41.1: /goal 启动 skill 与单步工作流'
type: 'feature'
created: '2026-08-29'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'e192934'
context:
  - '{project-root}/_bmad-output/epics/epic-41-目标驱动开发周期/epic-41-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 交互 CLI 没有 BMAD 式目标驱动开发入口——长目标无法「一条命令启动、逐 story 独立会话推进、进度落盘可续跑」。

**Approach:** 在 cli.py 增加 `/goal` 命令族（new/next/status/reset）：skill 正文路径直读注入、每步开一个全新 SubAgent 会话、代码只扫 GOAL.md 机器标记判边界；方法论全部由 `.heagent/skills/goal/SKILL.md` 契约驱动（已就位，采纳为基线）。

## Boundaries & Constraints

**Always:**
- skill 正文从 `.heagent/skills/goal/SKILL.md` 路径直读（不走 SkillStore 相似度匹配）
- 每步一个全新 SubAgent 会话（`run()` 每次新建 AgentLoop+RunContext），`window_reset=WindowResetConfig(threshold=get_settings().window_reset_threshold)`，engine 经 `loop.engine`
- 机器只扫三个标记：首非空行 `status: <planning|executing|done|blocked>`、`- [ ]`/`- [x]` checkbox、`> in-progress: S<n>`
- goal 目录 `.heagent/goals/<uuid4().hex[:8]>/`（`goal.txt` 存原始描述 + GOAL.md）+ `.heagent/goals/current` 指针，全部经 `atomic_write_text`；路径锚定 `Path.cwd()`
- 机制代码全部落 cli.py（模块级私有函数 + 薄注册闭包，仿 `_dream_runner`），增量约 130 行内；中文注释

**Ask First:** 实现中发现必须改 `sub.py` 签名或 `_build_slash_registry` 签名才能接线时。

**Never:** 不建 goal.py / Pydantic GoalState / runs.jsonl；不做 run 循环（41.2）、metadata 透传（41.2）、cron auto（41.3）；reset 不删任何文件（只清指针）；不做流式输出（defer）；不改动非 goal 既有命令行为。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| skill 缺失 | 任意 /goal 子命令 | 显性报错附创建指引（路径+frontmatter 最小示例） | 回显后 return |
| new 缺描述 | `/goal new` 无参 | 打印子命令用法表 | 不 input() 追问 |
| planning 成功 | `/goal <描述>` | 建 goal 目录（goal.txt+current 原子写）→ planning 会话 → 扫描通过回显进度 | GOAL.md 不合规=显性失败回显，目录保留可重试 |
| 会话未落盘 | 会话返回但 GOAL.md 缺失/无合法 status 行 | 显性报错（run 白跑但可检测） | 目录保留 |
| next 成功 | 活跃 goal | 会话 prompt=skill 正文+GOAL.md 全文+单 story 指令；`.heagent/runs/` 独立 run 记录 | result.success=False→回显错误输出 |
| next 无活跃 goal / status=done | 指针缺失或全部勾选 | 显性报错（指引 `/goal new`）或回显已完成，不开会话 | |
| status | 裸 `/goal` 或 `/goal status` | 打印 done/total+status+GOAL.md 全文 | 无活跃 goal→报错 |
| reset | `/goal reset` | 删 current 指针文件、目录保留、回显目录路径 | |
| Ctrl+C / 保留字子命令 | 会话 await 期间 / `run`·`auto`（41.2/41.3 未实现） | 回显「状态在盘，`/goal next` 可续跑」/ 打印用法表 | 捕获不抛出，不带 traceback 崩出 |
| 非保留首 token | 任意不命中 {new,next,run,auto,status,reset} 的首 token（含中文单 token 目标、拼错的子命令） | 一律视为目标描述，开 planning 会话 | 显性回显 + `/goal reset` 可恢复 |

</frozen-after-approval>

## Code Map

完整锚点见 context 引用的 epic-41-context.md（已核实零漂移）。决策关键项：

- `src/heagent/cli.py:865-909` — `_build_slash_registry(provider, mcp_manager, session, session_id, loop, system)`；register 为位置参数 `(name, description, handler)`（:895-899 先例）；`/goal` 注册在 :899 `help` 后、:901 自定义命令循环前；handler 闭包捕获 provider/loop（engine=loop.engine，`agent/loop.py:185` 恒非 None）
- `src/heagent/cli.py:630-648` — `_dream_runner`：SubAgent 惰性导入先例（函数内 import），`run()` 消费 result.success/output/run_id
- `src/heagent/cli.py:749-765` — dispatch 调用点无 try/except、Ctrl+C 不被该层捕获 → /goal handler 须自带 `KeyboardInterrupt`/`asyncio.CancelledError` 兜底
- `src/heagent/cli.py:912-920` — `_handle_slash` args=空白折叠 join（引号/多空格不保留）
- `src/heagent/agent/sub.py:61-81,156-216` — SubAgent ctor（provider 位置参数+keyword-only，含 window_reset/engine/context_dir）；run() 异常包装 success=False 不抛出
- `src/heagent/engine/persist.py:112-118` — `atomic_write_text(path, text)` 自动 mkdir
- `src/heagent/slash.py:31,44-46` — SlashHandler = `async (args: str) -> None`
- `src/heagent/tools/builtins/file.py:85-86` — `file_write(path, content)`：skill 落盘 GOAL.md 所用工具（测试脚本化它）
- `.heagent/skills/goal/SKILL.md` — 已就位 75 行基线；status 行须为文件首非空行
- `tests/test_agent_loop.py:26-67` — StubProvider/`_tc`/`_tool_resp` 脚本化先例；`tests/test_slash.py:7-8` 直接 import cli 私有函数

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/cli.py` -- 新增 /goal 机制（skill 直读 + goal 目录/指针管理 + planning/story 会话构造 + GOAL.md 边界扫描 + 子命令 new/next/status/reset + 显性错误 + Ctrl+C 兜底）并注册进 `_build_slash_registry` -- FR-1 机制底座
- [x] `tests/test_goal_command.py` -- 新建测试文件，按 I/O 矩阵全覆盖（StubProvider 脚本化 file_write 写 GOAL.md、`monkeypatch.chdir(tmp_path)`、`reset_settings`） -- 验证意图而非跑通流程

**Acceptance Criteria:**
- Given SKILL.md 存在，when `/goal <描述>`，then 创建 `.heagent/goals/<uuid4().hex[:8]>/`（goal.txt+current 原子写）且 planning 会话以确定性注入的 skill 正文运行（全新 AgentLoop/RunContext + `WindowResetConfig(threshold=settings.window_reset_threshold)`）
- And 会话后 GOAL.md 存在、status=executing、≥1 条 story；不合规显性失败回显、目录保留可重试
- Given 活跃 goal，when `/goal next`，then prompt 含 skill 正文+GOAL.md 全文+单 story 任务指令；每条 story 独立 run 记录
- Given 裸 `/goal` 或 `/goal status`，when 执行，then 打印进度计数（done/total+status）与 GOAL.md 全文
- Given `/goal reset`，when 执行，then current 指针清空、goal 目录保留

## Spec Change Log

- 2026-08-29（step-03 实现期，用户批准的冻结块重议）：I/O 矩阵「拼错子命令→用法表」与 Design Notes「非保留首 token=目标描述」互斥——`_handle_slash` args 为空白折叠 join，中文目标描述整体是单 token，「未知 token 打用法」会打断所有中文目标（实现首版实测 5 测试失败）。裁决：采 Design Notes 规则，矩阵该行拆为「保留字子命令」与「非保留首 token」两行。KNOWN-BAD 避免项：任何把「未知单 token」判为拼错子命令的启发式。KEEP：`test_unknown_first_token_treated_as_description` 锁定该契约。

## Design Notes

prompt 骨架（确定性注入，整段拼接非模板渲染）：

```
<SKILL.md 全文>

# 任务：执行 planning 规程
目标：<用户描述>
GOAL.md 路径：<cwd>/.heagent/goals/<goal_id>/GOAL.md
```

story prompt 同头部，任务段换为「执行 story 规程（仅一条）」+ GOAL.md 当前全文。

- 边界扫描为无状态模块级函数 `_scan_goal_md(text) -> (status, total, done)`，status 非法时返回 None 由调用方显性报错
- 子命令解析：首 token ∈ {new,next,run,auto,status,reset} 即子命令，否则整段 args 视为目标描述；多次 `/goal new` 共存（旧目录保留，current 指针切到最新）
- 测试直接调用模块级 `_goal_runner(provider, engine, args)`（engine 传 None），另配一个经真实 SlashRegistry dispatch 的子命令解析用例

## Verification

**Commands:**
- `pytest tests/test_goal_command.py -v` -- expected: 全绿
- `pytest` -- expected: 全绿（零回归）
- `ruff check src tests` -- expected: 无告警
- `mypy src` -- expected: 零新增错误

## Suggested Review Order

**入口与子命令解析契约**

- /goal 总入口：保留字集合分发 + 非保留首 token 一律视为目标描述（中文单 token 目标不被打断，经用户批准的冲突裁决）
  [`cli.py:1179`](../../src/heagent/cli.py#L1179)

- 注册点：薄闭包经 loop.engine 取 engine，不动 `_build_slash_registry` 签名
  [`cli.py:906`](../../src/heagent/cli.py#L906)

**会话机制（skill 注入 + 全新会话）**

- 每步全新 SubAgent 会话 + WindowResetConfig 阈值武装 + Ctrl+C/CancelledError 兜底（后者回显后 re-raise）
  [`cli.py:1037`](../../src/heagent/cli.py#L1037)

- skill 正文路径直读（不走 SkillStore 相似度匹配），缺失/解码失败返回 None 由入口报创建指引
  [`cli.py:993`](../../src/heagent/cli.py#L993)

**GOAL.md 边界扫描（机器只扫不写）**

- GoalProgress NamedTuple + 三标记扫描（status 首非空行 / checkbox 归一化 / in-progress 行）
  [`cli.py:943`](../../src/heagent/cli.py#L943)

- 读+扫描+显性失败收口；`_goal_active_md` 的指针 8-hex 校验（防手改穿越，仿 sandbox_session_dir 先例）
  [`cli.py:1017`](../../src/heagent/cli.py#L1017)
  [`cli.py:1001`](../../src/heagent/cli.py#L1001)

**planning 与 story 推进**

- 新建 goal（uuid 防碰撞 + 原子写 + planning 会话 + 产物合规校验）
  [`cli.py:1111`](../../src/heagent/cli.py#L1111)

- goal.txt 恢复路径：GOAL.md 缺失时用原始描述重跑 planning（复用同一 prompt 构造）
  [`cli.py:1086`](../../src/heagent/cli.py#L1086)

- story 推进：会话前后 (done,total) 对比做白跑检测 + 全勾未翻 done 读侧提示
  [`cli.py:1127`](../../src/heagent/cli.py#L1127)

**外围与测试**

- status/reset/usage（reset 只删指针文件 missing_ok=True，不碰其他文件）
  [`cli.py:1057`](../../src/heagent/cli.py#L1057)
  [`cli.py:1071`](../../src/heagent/cli.py#L1071)

- 45 个测试：ScriptedGoalProvider 按真实 file_write 工具链落盘（契约遵循模拟器，非 mock 管道）
  [`test_goal_command.py:107`](../../tests/test_goal_command.py#L107)

- 关键锁定用例：GBK 解码失败显性化 / 非保留 token=描述契约
  [`test_goal_command.py:308`](../../tests/test_goal_command.py#L308)
  [`test_goal_command.py:576`](../../tests/test_goal_command.py#L576)
