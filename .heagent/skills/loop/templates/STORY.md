# Story 产物指引（BMAD v7）

> 本文件是**产物指引**，不是要手抄的模板。本契约里一条 story 只有两件东西，路径都由脚本给出，
> 一律不要自造：
>
> 1. **entry**：`Docs/<goal-id>/tickets/<e编号>-<slug>/tickets/tickets.toml` 的 `[[entry]]` 表。Step 06
>    写入，字段与取值见 `.heagent/skills/bmad-agent-po/assets/tickets-template.toml`
>    （上游安装源同路径在 `.claude/skills/`）。
> 2. **plan**：`tickets.py find <ref>` 返回的 `plan` 绝对路径，由 `.heagent/skills/bmad-build`
>    按同包 `plan-template.md` 写出。frontmatter 的 `ticket` 必须等于 entry 的 `id`，`status`
>    是 story 状态的**唯一真源**。
>
> 不要再产出旧口径的 `story.md` / `implementation.md` / `test-report.md` / `verify-report.md`
> 四件套；需要附加证据时落 `Docs/<goal-id>/step-07-implement-story/<ref>/notes.md`。
> 只有评审、细化或发布需要 leaf 文件时才用 `tickets.py pull <ref>` 生成，不手写。

## entry 必填字段

- `type`：`story` | `spike` | `bug`
- `id`：epic 内从 1 起连续，永不复用
- `title`
- `description`：完成时是什么状态
- `verify`：一条可跑或可观察的检查
- `covers`：所属 epic 的 `R<n>`
- `after`：仅前置（`<epic id>.<entry id>` 或 `<e编号>-<slug>`），顺序靠表序
- `hitl`：是否需要人操作
- `risk`：`low` | `medium` | `high`
- 可选：`plan_checkpoint` / `done_checkpoint` / `refine` / `estimate` / `references` / `notes`
- 待裁决问题：`unknown`（一句话用户问题）——构建前必须清零

## plan 必须回答

- **Intent**：问题与做法（`<frozen-after-approval>` 段，批准后只有人能改）
- **Boundaries & Constraints**：`Always` / `Never` 两层
- **Code Map**：相关文件、符号/行锚点、可复用点、只读约束
- **Tasks & Acceptance**：可执行任务清单 + 可判定的验收标准
- **Verification**：确切命令，宿主亲自跑并把结果写进 `progress.md`
- **Implementation Notes / Review Triage Log / Plan Change Log**：随实现追加

## 状态推进

只用 `tickets.py mark <ref> <status>`（`draft` → `ready-for-dev` → `in-progress` → `in-review` →
`built` → `done`，另有 `blocked` / `dropped`）。build 只到 `built`；`done` 只在用户 `approve`
之后写。
