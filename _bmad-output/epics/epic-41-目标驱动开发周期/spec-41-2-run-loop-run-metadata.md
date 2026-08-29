---
title: 'Story 41.2: /goal run 连续推进与 run 观测标记'
type: 'feature'
created: '2026-08-29'
status: 'done'
review_loop_iteration: 2
baseline_commit: '81264bb2791acc023cb8351ee25c5bc2943d458c'
context:
  - '{project-root}/_bmad-output/epics/epic-41-目标驱动开发周期/epic-41-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** goal 只能逐条 `/goal next` 手动推进，长目标无法一条命令跑完；且 goal 会话的 run 记录与普通 subagent run 无法区分，事后不能按 goal 审计。

**Approach:** cli.py 把 `_goal_next` 的单步核心抽成可复用步进函数并新增 `/goal run` 循环调用（每条 story 仍一个全新会话，边界语义同构；触顶/失败/白跑显性停止）；`sub.py` SubAgent 增 `metadata` 参数（默认 None），goal 会话传 `goal_id`/`goal_kind`，经 `engine.create_run_context` 落进 `.heagent/runs/<run_id>.json` 快照 metadata。

## Boundaries & Constraints

**Always:**
- 循环每步经同一单步步进函数（`/goal next` 与 `/goal run` 共用一份代码，边界语义逐字节一致）
- 每步全新 SubAgent 会话（沿用 `_goal_session`）；session 快照 metadata 含 `goal_id`/`goal_kind` 且 `kind=subagent` 保留（框架标记权威，用户 metadata 不得覆盖 `kind`）
- max rounds 为模块常量（默认 10）；触显性报错、GOAL.md 现状保留可续跑
- 单步失败（result.success=False / 会话被中断）与白跑（(done,total) 零变化）都停止循环并回显，不静默续推
- `sub.py` metadata 缺省 None 时行为与现状一致（既有 `tests/test_sub_agent.py` 全绿回归锁定）

**Ask First:** 实现中发现必须改 `_goal_session`/`_goal_next` 之外的既有函数签名、或必须动 `_build_slash_registry` 签名才能接线时。

**Never:** 不建 goal.py / Pydantic GoalState / runs.jsonl（NFR-1）；不做 cron auto（41.3，`/goal auto` 仍回用法表）；不做流式输出；不改非 goal 命令行为；不为 metadata 做类型化工具或校验表。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| run 至完成 | 活跃 goal，2 条 story | 逐 story 开会话推进，全部勾选后停止并回显总结 | N/A |
| run 已完成 | status=done 或全勾选 | 回显已完成、不开会话直接返回 | N/A |
| run 触顶 | 连续 `_GOAL_RUN_MAX_ROUNDS`（10）步未达 done | 显性报错（附常量值与「可再 `/goal run` 续跑」指引） | 回显后 return |
| 单步失败 | 某步 result.success=False | 停止循环、回显错误输出 | 不续推 |
| 单步白跑 | 会话成功但 (done,total) 无变化 | 停止循环、回显白跑告警 | 不续推 |
| 会话被中断 | Ctrl+C / CancelledError | 沿用 41.1 兜底回显后停止循环 | 不崩出交互层 |
| 无活跃 goal | current 指针缺失 | 回显「无活跃 goal」不开会话 | N/A |
| GOAL.md 缺失 | goal.txt 在 | 沿用 41.1 恢复路径重跑 planning，作为循环的一步继续 | 恢复失败则停 |
| metadata 透传 | goal 会话（planning/story） | `.heagent/runs/*.json` 快照 context.metadata 含 goal_id+goal_kind+kind=subagent | N/A |
| metadata 缺省 | SubAgent(...) 不传 metadata | 快照 metadata 仅含框架键（kind/role），行为同现状 | N/A |
| run 带尾文本 | `/goal run foo` | 沿用保留字守卫：回用法表 | N/A |

</frozen-after-approval>

## Code Map

- `src/heagent/cli.py:1127-1176` — `_goal_next`：单步核心（goal 解析→done 检查→prompt→会话→前后对比/白跑检测）；抽成 `_goal_advance(...) -> str` 返回结局 token，`_goal_next` 变薄壳
- `src/heagent/cli.py:1037-1054` — `_goal_session`：SubAgent 构造点，加 `metadata` 参数透传
- `src/heagent/cli.py:1086-1124` — `_goal_run_planning`/`_goal_new`：planning 会话同传 metadata（goal_id：新建时已知 / 恢复时 `goal_md.parent.name`）
- `src/heagent/cli.py:1216-1217` — `_goal_runner` 的 `run` 分支：改调新循环函数；`auto` 保持用法表
- `src/heagent/cli.py:979-990` — `_goal_usage` 文案更新（run 已实现，auto 仍 41.3）
- `src/heagent/agent/sub.py:61-95` — ctor：`metadata: dict[str, Any] | None = None`（window_reset 之后），存 `self._metadata`；需补 `Any` import
- `src/heagent/agent/sub.py:168-170` — `run()` metadata 合并点：`{**(self._metadata or {}), "kind": "subagent"}` 再叠 role（框架标记后写=权威，用户键不得覆盖 kind）
- `src/heagent/engine/container.py:158` — `create_run_context(metadata=...)`（既有，直接用）；`engine/context.py:49` RunContext.metadata；`engine/store.py:72` 落盘 `.heagent/runs/<run_id>.json`（快照含 context.metadata 全量）
- `tests/test_goal_command.py:107-137` — ScriptedGoalProvider（单会话状态机 `_wrote`）；run 测试需多会话版：按「本次调用无 assistant 消息=新会话」重置状态，逐会话勾一条 story
- `tests/test_goal_command.py:413-436` — run 记录观测先例：glob `.heagent/runs/*.json` 前后差集；metadata 断言同点位读 JSON `context.metadata`
- `tests/test_sub_agent.py` — metadata=None 回归锁定基线（全绿不改）

## Tasks & Acceptance

**Execution:**
- [ ] `src/heagent/agent/sub.py` -- SubAgent 增 metadata 参数（默认 None）+ run() 保留键过滤合并（kind/role 框架权威、策略授权键剔除）+ 防御性拷贝 + docstring -- FR-3 透传底座（含审查轮 1 修正 ①⑤）
- [ ] `src/heagent/cli.py` -- `_goal_advance` 结局 token（blocked/planning 守卫、净增判据、回归显性）+ `_goal_run` 循环（轮次回显、触顶报错引常量）+ `_goal_run_planning` 三态返回与合规谓词合一 + `_goal_session`/planning 传 metadata + runner/usage 更新（薄壳移除、文案修正、f-string 常量） -- FR-2/FR-3 机制（含审查轮 1 修正 ②③④⑤）
- [ ] `tests/test_goal_command.py` -- 按 I/O 矩阵补 run 循环用例（多会话 ScriptedProvider、触顶〔勾+增驱动〕与续跑、失败停、白跑停〔含纯增 total〕、中断停〔story 与恢复路径〕、blocked 前后停、回归停、写坏停、metadata 快照断言） -- 验证意图而非跑通流程
- [ ] `tests/test_sub_agent.py` -- 补 metadata 透传/缺省最小用例 + 保留键过滤锁定（策略授权键注入不得存活）+ role 框架权威 + 防御拷贝 -- FR-3 回归锁定

**Acceptance Criteria:**
- Given 活跃 goal（2 条 story），when `/goal run`，then 顺序开 2 个全新会话勾完所有 story 后停止并回显总结；会话边界与 `/goal next` 一致（共用同一函数）
- Given 连续 10 步未达 done，when `/goal run`，then 显性报错附常量值，GOAL.md 现状保留
- Given goal 会话结束，when 读 `.heagent/runs/<run_id>.json`，then context.metadata 含 goal_id、goal_kind（planning|story）、kind=subagent
- Given SubAgent 不传 metadata，when run()，then 快照 metadata 仅含框架键，既有测试全绿

## Spec Change Log

- 2026-08-29（step-04 审查轮 2）：① 保留键集不完整——轮 1 修正案只列 7 键，漏 `progress_summary`/`segment`（window_reset 框架态，`loop.py:579,798` resume 消费）与 `completed_steps`（`subagent` 工具 task_status 消费），用户 metadata 可伪装框架态 → amendment：集扩为 10 键并用测试 pin 精确内容。② 判定顺序缺陷——轮 1 Design Notes 五步序把 stall（零变化）排在 status-done 前，「翻 done 无净增」被误判 stalled 且报「无变化」假消息，与下一轮预检（done）矛盾 → amendment：序改为 blocked/planning 守卫→回归→status-done→全勾 done→stalled→advanced。③ 冻结矩阵「停止并回显总结」未操作化——循环 done 停止无终局总结行 → amendment：`_goal_run` 在 done 结局补收尾总结。④ patch 簇：白跑消息改「无 story 净完成」（in-progress 标记变化不再是假「无变化」）；`_GOAL_ADVANCED` 注释补「或恢复 planning 成功」；SubAgent docstring 注明 metadata 值须可 JSON 序列化；防御拷贝改 deepcopy（嵌套容器亦隔离）；`_goal_run` 循环级 KeyboardInterrupt/CancelledError 兜底（同步间隙 Ctrl+C 不崩交互层）；usage 提示 Ctrl+C 可中断；测试补 5 缺口（恢复 planning 失败停、planning 预检停、会话后翻 planning、翻 done 无净增〔锁定顺序〕、净完成 done 分支）+ 轮次断言引常量 + metadata spy 去重/删死断言 + 嵌套 deepcopy 用例。KNOWN-BAD 避免项：stall 判定先于 status-done；保留键集凭记忆列举不 pin 测试。KEEP（轮 2 新增）：`_goal_run_planning` 三态返回、`_goal_judge_after` 抽取、blocked/planning 双侧守卫、净增语义、MultiSessionGoalProvider 驱动族。defer 出册：`RoleSpec.metadata` 死字段（既有无消费者）；交互 REPL 无逐命令异常围栏（cli.py:763 既有，goal 外溢）。reject：goal_round/关联 id 观测（超出 FR-3 范围）；frame.md 同步（Story 41.4 专职收尾）；GOAL.md 并发编辑 mtime 守卫（不可能场景防御）。

- 2026-08-29（step-04 审查轮 1，三审查层发现聚类）：① SubAgent metadata 透传未过滤 PolicyEngine 授权键（approved_tools/sandboxed_tools/sandbox_profiles/sandbox_active/sandbox_workspace）——Design Notes 原合并式把用户键全量并入 RunContext.metadata，而 policy.py:187 等以这些键为 per-run 授权依据（container 仅 scrub sandbox_workspace）→ amendment：合并前剔除保留键集（kind/role 框架权威后写）。② blocked/planning 状态在 run 循环无停机分支（烧会话至触顶，与 41.3「blocked→注销」语义冲突）→ amendment：会话前后均显性停止。③ advanced 判据过宽：done/total 回归、删未勾 story 凑全勾均计 advanced/done → amendment：advanced ⇔ done 净增；回归显性 failed；仅增 total 无净完成计白跑。④ 恢复路径中断被吞（_goal_run_planning 把中断/失败/不合规压成同一返回值，中断后循环可续开新会话）→ amendment：三态返回 True/False/None，恢复分支 None→停止。⑤ 次要：合规谓词两份副本合一、max rounds 字面量三处改引常量、run 语境过期文案（next→next/run）、_goal_next 空壳移除、metadata 防御性拷贝+docstring、_goal_session 类型统一 dict[str, Any]、每步轮次回显。KNOWN-BAD 避免项：把「advanced=任何 (done,total) 变化」「用户 metadata 携带策略授权键」「planning 产物谓词写两份」带回复现。KEEP：结局 token 模块常量 + _goal_advance 单函数共用（next/run 边界同构）；框架 kind 后写权威方向；.heagent/runs/*.json 快照直读的 metadata 断言法；MultiSessionGoalProvider 无 assistant 消息=新会话判据；矩阵驱动的 TestGoalRun（含中断停循环用例）。

## Design Notes

结局 token（模块级字符串常量，不建 enum——NFR-1 简约）：`advanced`（story done 净增未达完成态，**或恢复 planning 成功**——循环唯一继续条件）/ `done`（已达完成态：全勾或 status 翻 done——含未翻 done 的读侧按完成）/ `stalled`（白跑：无 story 净完成——零变化或仅非 story 标记变化）/ `failed`（会话失败/中断/产物不合规/进度回归/状态 blocked·planning）/ `no-goal`。planning 恢复路径按一步计入轮次。

**sub.py 保留键过滤**：`run()` 合并前剔除用户 metadata 中的保留键 `_METADATA_RESERVED_KEYS = {"kind","role","approved_tools","sandboxed_tools","sandbox_profiles","sandbox_active","sandbox_workspace","progress_summary","segment","completed_steps"}`（前 7 键=PolicyEngine per-run 授权键 + container 管理键 + 框架标记；后 3 键=window_reset 框架态〔`loop.py` resume 消费〕与 subagent 工具 task_status 消费键——用户键不得经 SubAgent 注入或伪装框架态；kind/role 框架后写权威，role 仅在 role 非空时落键）。ctor 防御性拷贝 `copy.deepcopy(metadata) if metadata is not None else None`（嵌套容器亦隔离）；类 docstring 补 metadata 参数说明并注明**值须可 JSON 序列化**（run 快照落盘）。测试 pin 保留键集的精确内容（新增键必须显式改测试）。

**`_goal_judge_after` 会话后判定（story 路径，按序——status-done 必须先于 stalled，否则「翻 done 无净增」误判白跑）**：
1. `after.status in ("blocked", "planning")` → failed（显性回显「会话后 status 变为 …」）
2. `after.done < prog.done or after.total < prog.total` → failed（进度回归，显性回显前后值）
3. `after.status == "done"` → done（提前翻牌读侧按完成）
4. `after.total > 0 and after.done == after.total` → done（status 未翻 done 仍读侧按完成 + 提示）
5. `after.done == prog.done` → stalled（无 story 净完成——含零变化与仅非 story 标记变化〔in-progress 行等〕，消息用「无 story 净完成」不谎称「无变化」）
6. 其余（done 净增且未达完成态）→ advanced

**会话前守卫**：status=blocked → 显性停止（需人工处理，处理后可续跑）；status=planning → 显性停止（planning 未收口）。会话后 after.status ∈ {blocked, planning} → failed 显性回显。

**`_goal_run_planning` 三态返回** `bool | None`：True=产物合规 / False=会话失败或产物不合规（均已回显）/ None=中断（已回显）。恢复分支：None→failed（中断即停，不得续开新会话）、True→advanced、False→failed；产物合规谓词（`status=="executing" and total>=1`）抽模块级单一函数，`_goal_run_planning` 与恢复分支共用（消灭两份副本）。

```python
async def _goal_run(provider, engine, skill) -> None:
    try:
        for round_no in range(1, _GOAL_RUN_MAX_ROUNDS + 1):
            click.echo(f"[goal] run 第 {round_no}/{_GOAL_RUN_MAX_ROUNDS} 步", err=True)
            outcome = await _goal_advance(provider, engine, skill)
            if outcome == _GOAL_DONE:
                click.echo(f"[goal] run 完成：共 {round_no} 步。", err=True)  # 终局总结（矩阵「回显总结」）
                return
            if outcome != _GOAL_ADVANCED:
                return
    except (KeyboardInterrupt, asyncio.CancelledError):
        click.echo("[goal] 已中断：状态在盘（GOAL.md），/goal next 可续跑（连续推进用 /goal run）。", err=True)
        return
    click.echo(
        f"[goal] run 触顶：连续 {_GOAL_RUN_MAX_ROUNDS} 步推进仍未达 done。"
        "GOAL.md 现状保留，可再 /goal run 续跑。",
        err=True,
    )
```

- 循环级 KeyboardInterrupt/CancelledError 兜底：同步间隙（文件读写/回显）的 Ctrl+C 亦不崩出交互层（矩阵「不崩出交互层」承诺全覆盖）

- run 语境文案：中断回显「/goal next 可续跑（连续推进用 /goal run）」；planning 完成「用 /goal next 推进（或 /goal run 连续推进）」；`_goal_usage` 步数用 f-string 引常量并注明「Ctrl+C 可中断」；测试 import 常量并断言完整消息片段（轮次断言一律引 `_GOAL_RUN_MAX_ROUNDS`，不留字面量）
- `_goal_next` 薄壳移除：runner 的 next 分支直调 `_goal_advance`
- `_goal_session` metadata 类型统一 `dict[str, Any] | None`（与 SubAgent 一致）
- 多会话测试 provider 会话边界判据：send() 收到的 messages 无 assistant 角色消息 ⇒ 新会话开始（重置单会话状态）；触顶测试驱动改为「每步勾一条 + 新增一条未勾」（done 净增永不满勾）——纯增 story 在新语义下计白跑停止，不再驱动触顶
- run 专项测试另须覆盖：恢复 planning 会话失败（False）第 1 轮即停；planning 状态预检停；会话后翻 planning 停；会话后翻 done 无净增 → done（锁定判定序，防 stall 抢先）；净增至全勾 + 翻 done 的干净收尾（含「run 完成：共 N 步」总结行）；`_METADATA_RESERVED_KEYS` 精确内容 pin；deepcopy 嵌套隔离用例；test_sub_agent 的 metadata spy 与既有 AgentLoop spy 去重（共用 fixture，删死断言）

## Verification

**Commands:**
- `pytest tests/test_goal_command.py tests/test_sub_agent.py -v` -- expected: 全绿
- `pytest` -- expected: 全绿（零回归）
- `ruff check src tests` -- expected: 无告警
- `mypy src` -- expected: 零新增错误
