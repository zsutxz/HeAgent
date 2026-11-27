# /loop 契约 · 只读文档审查

> 本文件是 `workflow.md` 拆出的章节，与它同属流程真源；章节归属见 `workflow.md` 的「文件地图」。

## 只读文档审查

`review [step]` 是独立于 8 步的只读动作，不是工作流步骤：无参数审查当前 goal 全部状态与产物，
可限定 `step-01`…`step-08`、某个 epic / `ref` 或具体 entry。审查范围至少包括：

- `current` 指针、`progress.md` 状态与产物存在性、`- Initiative:` 行指向的票树是否一致；
- 各步骤必需章节、审批门、输入/输出引用是否完整；
- `tickets.py status` / `next` 的 `problems` / `unpinned_after` / `undeclared_after` / `order_conflict` /
  `drift` 是否为空，plan `status` 与 `progress.md` 的记载是否一致；
- epic 的 `refined`、`covers` 指向的 `R<n>`、entry 的 `after` 是否都由更早的工作交付；
- 是否越过审批门、越过分批纪律（写集相交仍成批、越集写未撤销授权）、改动冻结段、留悬空引用或跨产物矛盾，是否把 `unknown` / `blocked` 当作可构建；
- 报告中的测试、性能、硬件与验证结论是否有证据，是否把计划命令写成已执行结果。

纪律：只读（必要的检查命令由宿主执行），不委派实现型子会话，不改任何文件、状态、审批记录或勾选，
不推进步骤；每条发现给位置、证据、严重度（Critical/High/Medium/Low）与建议处置；`review` 是 goal
文档/状态审查，不等于代码评审——代码评审走「epic 收口三审」：`R1` = `bmad-code-review`（规格与契约轴）、
`R2` = 不变量与守卫反脆弱（含注入反证）、`R3` = 技能 `code_review` 的三镜头（对抗 / 边界 / 验证缺口）。
