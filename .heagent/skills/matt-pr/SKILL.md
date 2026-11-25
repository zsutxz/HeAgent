---
name: matt-pr
description: "写 PR 正文的模板与判据：Summary 用最小可视化（伪代码/调用树/组件树/文件树/Mermaid/diff 择一）、Evidence 给前后对比、Merge Danger 判 one-way/two-way door 与 blast radius。 | Template for a PR body: the smallest visual that makes the change clear, before/after evidence that it works, and a one-way or two-way door call with blast radius."
triggers: [写 PR 正文, 开 PR 描述, PR 模板, pull request body, write the PR, 开个 PR]
negative_triggers: [提交到本地分支, 写提交信息, 评审改动, 写规格]
---

# matt-pr

## Pattern
做什么：按固定模板塑造 PR 正文，只用三段——`## Summary`（一张最小可视化）、`## Evidence`（前后证据）、`## Merge Danger`（门型 + 影响面）。
何时用：要写 PR 正文时（模型触发，写完代码准备开 PR 时主动用）；只提交到本地分支不用它，评审既有改动走 matt-code-review。
原则：跳过所有前言、散文尽量短，使用 `GLOSSARY.md` 里的领域语言。
来源：本技能改编自 Humanlayer 的 show-me 技能（见 references/CREDITS.md）。

## Steps
1. 按模板起草三段式正文：Summary 放一张最小可视化，Evidence 放 Before/After，Merge Danger 放 Door 与 Blast Radius。
2. Summary 选「让要点最清楚的最小视图」：逻辑或算法用伪代码，运行时控制流用调用树，UI 结构用组件树，文件职责或大范围重构用浅文件树，组件交互与数据流用 Mermaid，改动形状已存在时用 diff 并让 diff 的形态匹配主题。
3. 视觉只保留回答当前问题或当前讨论点所需的最少调用、文件、props、状态与边界；一个 PR 通常用一两种即可，不要堆砌到淹没读者。
4. Evidence 给可执行、可复现的前后对比：截图最优（视觉改动且环境允许时），执行证据次优（测试结果、控制台输出），并用伪代码点明「现在失败、改后通过」的那条测试。
5. Merge Danger 先判门型：two-way 门可以走回去、风险低；one-way 门（破坏性动作、难以逆转的决策）要显式点出。
6. 再写 Blast Radius，用一个词概括影响范围，必要时补潜在连带影响，例如布局位移、下游消费者破坏、移动端适配。
7. 把每张视觉紧贴它支撑的那段短文字，不要远离上下文。
