---
name: loop
description: 目标驱动开发（声明式 8 步工作流）：/loop 命令与多阶段大目标的触发与执行
triggers: [/loop, loop 工作流]
negative_triggers: [/goal, code review, 代码评审, 技能评审, 重构, refactor]
---

# /loop 工作流（目标驱动开发）

## 定位

- **适用**：多阶段目标（从需求到交付）。只改一处、只答一问、只做一次探查不要启动工作流。
- **契约**：本文件 = 参数分派与执行总则；同包 `workflow.md` + `references/*.md` = 流程唯一真源（8 步顺序、票树接口、各步
  验收核对、产物位置；章节落在哪个文件见 `workflow.md`「文件地图」）。任何动作前先读它，本文件不复述流程细节。
- **状态**：`docs/current` 指针 + goal 目录（`docs/<goal-id>/`，或同一文档根下按代分目录的
  `docs/<root>/goal-<n>/`；内含 `brief.md` / `progress.md` / `tickets/` / `step-NN-*/`）。
- **无 CLI 强制**：`status` / `review` / `approve` / `reset` 等语义由 Agent 按契约执行，不由脚本保证。
- **规划正本**：BMAD v7 票树——epic 与 entry 住 `docs/<goal-id>/tickets/`，一律经
  `.heagent/skills/bmad-agent-po/scripts/tickets.py` **带显式目录**读写；不产 `epics.md` /
  `sprint-status.yaml`（v7 无 sprint）。goal 目录同时留 `brief.md`、`progress.md` 与各步报告。

## 参数分派

`$ARGUMENTS` 由命令注入；无参数 = 打印用法与当前状态。

| 参数 | 动作 |
|---|---|
| `<目标描述>` / `new <描述>` | 跑 `scripts/new-goal.py <goal-id>` 建骨架，执行 Step 01 |
| `next` | 推进下一步；Step 07 取 `tickets.py next` 的 `ready_to_start`，按「epic 内并行批」组批（默认整批并行，不成批时单条串行） |
| `run` | 连续推进到审批门、失败或完成 |
| `status` | 读 `progress.md` + `tickets.py status/next` 报告进度 |
| `review [step]` | 只读审查状态与产物一致性，不推进、不改文件 |
| `pause` / `resume <回复>` | 置 paused / 记回答进决策日志并写入 `brief.md` 用户补充段，恢复等待项；Step 02 交互轮的回答也走这里（原话进 `step-02-brainstorm-options/report.md`，不写 `brief.md` 冻结段） |
| `approve` / `reject <原因>` / `amend <补充>` | 处理审批门；Step 08 的 `approve` 还会逐条 `mark done` |
| `decisions` | 回显决策日志 |
| `auto [cron]` / `auto off` | **仅用户显式发起**的自动推进 job（注册 / 注销，永不写 `done`）；交接路径永不自动注册 |
| `reset` | 清除 current 指针（goal 目录保留） |

## 执行总则

1. **先读后写**：每次调用先读 `docs/current`、`progress.md` 与 `tickets.py status/next`，再动手、再落盘；
   绝不凭记忆续跑。
2. **每步全新子会话**：用 `task_delegate` 执行步骤，正文 = 该步契约全文 + 输入产物路径。子会话默认不写盘：产物正文或报告写在回复里，由宿主落盘。唯一例外是 Step 07（含 Step 08 修复）的实现子会话，它按 entry 的 `write_set` 写源码、测试与 plan；`progress.md`、`mark` 与提交仍只由宿主执行。同一 epic 内成批并行时改用 `task_parallel`，一条 entry 一个子会话（见总则 12）。
3. **宿主验收与落盘**：子会话返回后按该步「验收核对」核对，`command:` 类核对亲自跑；产物由宿主写盘，
   核对结果写进 `progress.md`，未过按该步处置，不得静默放行。
4. **状态只经脚本**：story 状态只经 `tickets.py mark <goal 目录> <ref> <status>` 写，不手改 frontmatter；
   票树有 `problems` / `drift` / `unknown` 时先修树再推进。
5. **冻结与重切**：不手改 `brief.md` 的「原始需求」段、已批准的 epic Requirements / `Done when`、
   plan 的 `<frozen-after-approval>` 段；要改走 Step 04 / 06 重切并重新审批。
6. **默认值优先**：契约、该步产物或上一轮呈报已给推荐项的，按推荐项执行并在 `progress.md` 记
   「按默认值执行」；只有无人给过默认值的开放问题才停下问。
7. **只停真门**：只在审批门、Step 02 头脑风暴交互轮、`hitl` / `plan_checkpoint` / `done_checkpoint`、
   Step 08 放行、显性失败、全部完成时停；不因「顺便问一句」或已呈报未被反对的事项停。Step 02 交互轮不是审批门（详见 `workflow.md` 的 Step 02），回一句就继续。
8. **`done` 只由人写**：用户「继续 / 推进 / 按默认值 / `approve`」即视为对已呈报推荐项的放行，此时逐条
   `mark done` 并记答复原文；未表态就停在门前。
9. **只读审查**：`review` 不委派实现型子会话、不改任何文件与状态；每条发现给位置、证据、严重度、处置。
10. **显性失败**：状态文件缺失/损坏、脚本非零退出、同一子任务连续两次失败时如实报告并停，不伪造进度。
11. **完成即提交、交接、续跑**：一批 entry 全部 `built` 后，按 `workflow.md`「完成即自动提交」判据提交；未过判据不提交，缺口写进交接块。随后按「上下文交接与续跑」覆盖写 `progress.md` 交接块，并在本轮回复里给出**可直接复制的续跑指令**（同一会话发「继续」或 `/loop next`；要清零上下文就先 `/clear` 或另开会话再发）。**不注册 cron、不建任何自动 job**——续跑只靠「交接块 + 用户一句话」，流程不因没有定时器而停下。遇 `hitl` / checkpoint、Step 08 放行前、显性失败或需用户裁决时同样只交接、不自动推进。
12. **同 epic 内默认成批并行**：Step 07 默认成批并行——声明齐全且过「七条件」的相邻 entry 用
    `task_parallel` 同时开子会话（`parallel_group` / `write_set` 是 Step 06 的义务声明）；**门禁、`mark`、
    提交、交接仍由宿主串行收口**（本仓源码树、容器 workspace 与设备腿只有一份）。声明缺失、写集相交、
    带 checkpoint / `hitl`、跨 epic 一律 fail-closed 单条串行兜底；批内越集写撤销本 epic 的并行授权。
    细则见 `workflow.md` 的「epic 内并行批」。
13. **Epic 收口三审**：该 epic 全部 entry 达 `built` / `in-review` / `done` 后自动开跑，不呈报、不等确认；
    开跑前先交接（覆盖写交接块）并**建议**换新上下文：用户换就新会话 `/loop next`（三审随之在新会话里开跑），不换就在当前会话直接开跑——**不得为等换会话而停**（不注册 cron）。三镜头**并行审读**（`task_parallel` 开三个子会话，
    同一快照、只读，产出待核验清单），宿主合并落盘后**串行**做验证与反证——`R1` 规格对账、
    `R2` 不变量与守卫、`R3` `code_review` 三镜头。顺序、报告落点与缺口处置以 `workflow.md`
    「epic 收口三审」为准；三镜头齐备的报告与回顾的 `## 三审记录` 缺一即不提交。
