# goal 工作流契约（companion）

> 本 companion 承载 GOAL.md 状态文件契约与 planning/story 规程的全部承重细节。
> 实施时其正文落为 `.heagent/skills/goal/SKILL.md`（工作区已有草稿，采纳为基线）；
> 该 skill 文件是方法论的唯一载体，人可直接编辑定制。

## GOAL.md 状态文件契约

路径：`.heagent/goals/<goal_id>/GOAL.md`（每次任务消息里给出绝对路径）。人可直接读改；
机器只扫三个标记——**status 行、story checkbox、in-progress 行**。格式（严格遵守）：

```markdown
status: executing

# <目标一句话>

## Stories

- [ ] S1: <story 标题>
  - 验收: <可验证的验收标准 1>
  - 验收: <可验证的验收标准 2>
- [x] S2: <story 标题>
  - 验收: <标准>
  - notes: <完成备注：做了什么、怎么验证的>

> in-progress: S1
```

规则：

- `status:` 行必须是文件第一个非空行，取值 `planning | executing | done | blocked`。
- 每条 story 一个 checkbox：`- [ ]` 未完成 / `- [x]` 已完成；编号 S1、S2… 递增不重用。
- 正在进行的 story 用 `> in-progress: S<n>` 行标注；完成或放弃时移除该行。
- `验收` 必须可验证（测试命令、可检查的产物、明确的判定条件），不可写「做好」「优化」这类不可判定项。
- story 的关键决策、踩坑、验证方式写进该 story 的 `notes`。

## planning 规程（目标 → story 清单）

1. 理解目标：必要时先探索工作区（读文件、查结构），弄清目标边界与现有约束。
2. 拆解：把目标拆成**从前往后可独立交付**的 story，每条含可验证验收标准；
   规模指引——一条 story 一个可独立验证的增量，过大要继续拆，过碎要合并。
3. 落盘：用 file_write 一次性写出完整 GOAL.md（`status: executing`，全部 `- [ ]`，
   无 in-progress 行）。
4. 收口：简要输出拆分理由（为什么这样拆、顺序依据），**禁止开始实现任何 story**。

## story 规程（一次会话 = 一条 story）

1. 读 GOAL.md，选定**最早一条未勾选**的 story（若有 `> in-progress:` 行则优先续做该条）。
2. 更新状态：把该 story 标为 in-progress（加 `> in-progress: S<n>` 行）写回 GOAL.md。
3. 实现该 story：按验收标准动手（写代码/文件，可运行验证命令）。
4. 逐条核对验收：每条 `验收` 都要有明确的通过证据；无法通过且无法绕开时，
   在 notes 写明原因并把 `status:` 行改为 `blocked`。
5. 勾选写回：通过则该 story 勾为 `- [x]` 并补 notes，移除 in-progress 行；
   **全部 story 均已勾选**时把 `status:` 行改为 `done`。
6. 收口：给出最终答复——本条 story 做了什么、验收证据、GOAL.md 当前进度。
   到此为止，**不要开始下一条 story**。

## 禁止事项

- 禁止在一个会话里做多条 story（会话边界 = story 边界，这是机制层的清窗依据）。
- 禁止改动本条 story 之外的勾选状态、禁止回退 status（`done`/`[x]` 不可逆）。
- 禁止把进度只写在会话回复里而不落盘 GOAL.md——清窗后回复即失忆。
- 禁止在 `.heagent/goals/` 之外维护 goal 状态。

## 会话 prompt 组装约定（机制层供参考）

每次 goal 会话的 prompt = skill 正文（frontmatter 之后）+ 当前 GOAL.md 全文 + 本次任务指令
（planning：目标描述 + 规划指令 + 禁止实现；story：推进下一条 + 单 story 边界声明）+
状态文件绝对路径。SubAgent 的 system 为固定定位提示（目标执行引擎、严格遵循契约、每轮只做一步）。
