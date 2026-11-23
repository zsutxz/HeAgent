---
name: loop
description: 目标驱动开发（声明式 8 步工作流）：/loop 命令与多阶段大目标的触发与执行
triggers: [/loop, loop 工作流]
negative_triggers: [/goal, code review, 代码评审, 技能评审, 重构, refactor]
---

# /loop 工作流（目标驱动开发）

## 定位

- **适用**：多阶段目标（从需求到交付）。只改一处、只答一问、只做一次探查不要启动工作流。
- **契约**：本文件 = 参数分派与执行总则；同包 `workflow.md` = 流程唯一真源（8 步顺序、票树接口、各步
  验收核对、产物位置）。任何动作前先读它，本文件不复述流程细节。
- **状态**：`Docs/current` 指针 + goal 目录（`Docs/<goal-id>/`，或同一文档根下按代分目录的
  `Docs/<root>/goal-<n>/`；内含 `brief.md` / `progress.md` / `tickets/` / `step-NN-*/`）。
- **无 CLI 强制**：`status` / `review` / `approve` / `reset` 等语义由 Agent 按契约执行，不由脚本保证。
- **规划正本**：BMAD v7 票树——epic 与 entry 住 `Docs/<goal-id>/tickets/`，一律经
  `.heagent/skills/bmad-agent-po/scripts/tickets.py` **带显式目录**读写；不产 `epics.md` /
  `sprint-status.yaml`（v7 无 sprint）。goal 目录同时留 `brief.md`、`progress.md` 与各步报告。

## 参数分派

`$ARGUMENTS` 由命令注入；无参数 = 打印用法与当前状态。

| 参数 | 动作 |
|---|---|
| `<目标描述>` / `new <描述>` | 跑 `scripts/new-goal.py <goal-id>` 建骨架，执行 Step 01 |
| `next` | 推进下一步；Step 07 取 `tickets.py next` 的 `ready_to_start`，按「epic 内并行批」组批（缺省只取首行） |
| `run` | 连续推进到审批门、失败或完成 |
| `status` | 读 `progress.md` + `tickets.py status/next` 报告进度 |
| `review [step]` | 只读审查状态与产物一致性，不推进、不改文件 |
| `pause` / `resume <回复>` | 置 paused / 记回答进决策日志并写入 `brief.md` 用户补充段，恢复等待项；Step 02 交互轮的回答也走这里（原话进 `step-02-brainstorm-options/report.md`，不写 `brief.md` 冻结段） |
| `approve` / `reject <原因>` / `amend <补充>` | 处理审批门；Step 08 的 `approve` 还会逐条 `mark done` |
| `decisions` | 回显决策日志 |
| `auto [cron]` / `auto off` | 注册 / 注销自动推进 job（永不写 `done`） |
| `reset` | 清除 current 指针（goal 目录保留） |

## 执行总则

1. **先读后写**：每次调用先读 `Docs/current`、`progress.md` 与 `tickets.py status/next`，再动手、再落盘；
   绝不凭记忆续跑。
2. **每步全新子会话**：用 `task_delegate` 执行步骤，正文 = 该步契约全文 + 输入产物路径。子会话视为只读
   环境（不假设有 `file_write` / `file_edit` / 建目录能力），必须把完整产物正文或实现/验证报告写在回复里。
   同一 epic 内成批并行时改用 `task_parallel` 一次开多个子会话，一条 entry 一个（见总则 12）。
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
11. **完成即提交，提交即交接，交接即换会话**：一批 entry 全部置 `built`（串行时即单条）后；epic 则在全部 entry
    完成、三审（`R1`/`R2`/`R3`）与回顾都已落盘后，先过 `workflow.md`
    「完成即自动提交」的判据——通过就**自动 `git commit`**（中文 Conventional Commit、只暂存本批显式文件、
    禁 `-A`/`.`、不 push），未通过则不提交并把缺口写进交接块；提交后再按「上下文交接与续跑」覆盖写
    `progress.md` 的 `## 交接块（下一轮入口）`，再**默认注册一次性 cron job**
    （`recurring: false`、`* * * * *`）让新会话接手——agent 调不了客户端的 `/clear`，cron 是等价手段；
    注册前先 `cron_list` 去重，写完 job 即收官本轮（**cron 只换执行入口，不清空当前会话**——要清零
    得用户 `/clear` 或另开会话，回复里必须写明这一点）。下一条是 `hitl` / checkpoint、Step 08 放行前、
    显性失败或需用户裁决时**不注册**，按人工续跑收官并清掉遗留 job。epic 收口不是停止点，
    下一条按 `next` 取（可能已是下一个 epic）；中断后一律靠交接块 + `/loop next` 续跑。
12. **同 epic 内可成批并行**：Step 07 默认逐条串行；同 epic 内声明了 `parallel_group` 与 `write_set`、
    且过「七条件」的相邻 entry 可成批并行——用 `task_parallel` 同时开子会话，但**门禁、`mark`、提交、
    交接仍由宿主串行收口**（本仓源码树、容器 workspace 与设备腿只有一份）。写集相交、缺声明、带
    checkpoint / `hitl`、跨 epic 一律 fail-closed 退回串行；批内越集写撤销本 epic 的并行授权。
    细则见 `workflow.md` 的「epic 内并行批」。
13. **Epic 收口三审（缺一不可）**：该 epic 全部 entry 完成后按 `workflow.md` 的「epic 收口三审」跑三遍不同视角的
    审查——`R1` 规格与实现对账（`bmad-code-review`）、`R2` 不变量与守卫反脆弱（宿主自扫 + 注入反证）、
    `R3` 三镜头对抗式评审（技能 `code_review`：对抗 / 边界 / 验证缺口）。**串行推进、每轮修完再开下一轮**，
    三份报告（`<E编号>-<slug>-review-r1.md` / `-review-r2.md` / `-review-r3.md`）+ 回顾的 `## 三审记录`
    齐了才允许提交与收口；`R3` 不得用 `R1`/`R2` 顶替（`bmad-code-review` 是 `R1` 的镜头），也不得改写它的
    结论。`skill_load code_review` 不可用时**报 gap**（记 `brief.md`「延期项」+ 交接块「未关闭的门」，
    `/loop auto` 下登记完继续收口），`R3` 报告照写「未执行（gap 已登记）」，不得伪造审查结论。
    三审期间不提交、不写 `done`。**开跑前先换一次上下文**：先提交这批 entry、写交接块，再把三审交给新会话
    （一次性 cron，或用户 `/clear` + `/loop next`）；三审链在新会话里连跑到底、中途不再换会话。
    **触发与顺序**：该 epic 全部 entry 达 `built`/`in-review`/`done`（只认
    `tickets.py status`，不看本批是否含最后一条）即**自动开跑、不呈报、不等确认**；链固定为三审 → 回顾 →
    自动提交 → 交接 → `tickets.py next` 取**下一个 epic** 的第一条 entry（或 `none（转 Step 08）`），
    epic 边界不是停止点。
