---
name: mattpocock-skills
source: https://github.com/mattpocock/skills
accessed: 2026-10-28 / 2026-11-02
heat: 304,944 stars / 25,661 forks（2026-10-28 API 快照，当期最高星 skill 仓库）
first_study: 2026-10-28
last_review: 2026-11-02
---

# mattpocock/skills

**最后更新：** 2026-11-02（长场景结构重做 + 关键引文中英并置；材料 = 本机插件 v1.2.3 全量 38 个 SKILL.md，主流程 13 个已通读）

Matt Pocock（Total TypeScript 作者）的个人日用库，自述 "Skills For Real Engineers——not vibe coding"。**一句话核心：技能库首先是一条流程，技能是流程上的站。**

## 核心观点（30 秒版）

1. **库自带路由图**：ask-matt 开篇 "You don't remember every skill, so ask"（译「你记不住每个技能，所以开口问」，ask-matt:9），把 38 个技能组织成一条主流程（idea→ship）+ 三条 on-ramp（bug/巨量工作/积累的 issue）+ 两层词汇（domain-modeling/codebase-design）——路由本身是一级资产，不是读者自己拼的。
2. **编排层极薄**：grill-with-docs 正文只有 7 行 = "Call the Skill tool twice, for grilling and domain-modeling"（译「调用两次 Skill 工具：grilling 与 domain-modeling」，grill-with-docs:7）；implement 15 行 = "Use /tdd where possible, at pre-agreed seams … use /code-review … Commit"（译「尽可能用 /tdd，在预先约定的缝上……用 /code-review……提交」，implement:9-13）。复杂度在链上，不在任何单点。
3. **一切测试挂在 seam（缝）上**：spec 阶段先画缝并确认（"ideal number is one"，译「理想是一条」，to-spec:15）；tdd 拒绝在未确认缝上写测试（"No test is written at an unconfirmed seam"，译「未确认的缝上不写测试」，tdd:22）；bug 修复先造红色回路再谈假设（diagnosing-bugs Phase 1）。缝是贯穿三技能的同一词汇，由 codebase-design 供给。
4. **触发权按风险分配**：规划/写操作类全部 user-invoked（setup/to-spec/to-tickets/implement/grill 系/wait-what 等 14 个带 `disable-model-invocation: true`——人扣扳机）；tdd/diagnosing-bugs/code-review/wizard 等 model-invoked——可自动、风险低的才放手给模型。触发权是显式设计决策，不是默认。
5. **技能的主业是对抗默认行为**：to-spec 第一段 "Do NOT interview the user"（译「不要面审用户」，to-spec:7）；diagnosing-bugs "stop: jumping straight to a hypothesis is the exact failure this skill prevents"（译「停：径直跳到假设，正是本技能要防止的失败」，:66）；code-review "Don't pick a single winner across axes"（译「不要在各轴之间挑唯一赢家」，:78）——每条都在命名并阻止一种模型天然倾向。
6. **上下文按阶段记账**：规划三站一个不间断窗口（"Keep steps 1–3 in one unbroken context window"，译「把 1–3 步保持在一个不间断的上下文窗口里」，ask-matt:30），每张票 /clear 后新窗口 implement（票自包含所以上下文可弃）；接近 smart zone（~150k）就在阶段边界 /compact（ask-matt:32）。
7. **写作技术层**（writing-for-agents 样本，报告 §1/2/3/4/13 已收录）：两种负载（context/cognitive）、指针措辞决定触发、完成判据 clarity×demand、leading word 锚定、no-op 猎杀与 sediment 修剪。
8. **治理闭环**：issue 双门槛（观察到失败+符合哲学）、`.out-of-scope/` 负向档案、changesets 版本化每次行为修订——「skill 越少越短，维持正确越便宜」。

## 长场景：一句话需求，从对齐到 PR

> 场景：你在自己的 SaaS 仓库里对 agent 说——「帮我把订单做成可以导出 CSV，运营一直要」。一句话需求，背后藏着权限、字段、编码、定时还是手动等十几个没说的决策。看这个库怎么接。

### 第 0 站 · 地基（每仓库一次）：setup-matt-pocock-skills

先探仓库（remote/AGENTS.md/CONTEXT.md/monorepo 信号），再三节问答：issue tracker 在哪（GitHub/GitLab/本地 `.scratch/`/其他自由描述）、triage 标签用不用默认五个、领域文档单上下文还是多上下文。产出 `docs/agents/*.md` + 在 CLAUDE.md（存在哪个改哪个，"Never create AGENTS.md when CLAUDE.md already exists"，译「CLAUDE.md 已存在时绝不另建 AGENTS.md」，setup:80）写 `## Agent skills` 块。**若无此步**：后面每个技能都要重新问一遍 tracker 在哪——配置被抽成一次性的仓库资产。

### 第 1 站 · 对齐：grill-with-docs = 两个技能的组合

7 行正文调用 grilling + domain-modeling。grilling 把需求画成**设计树**，按**轮次**追问：每轮把「前沿」（前提已定的全部问题）一次问完、编号、附推荐答案（grilling:8）；**事实 agent 自己查**（派 sub-agent，"don't ask the user for anything you could look up yourself"，译「凡自己能查到的就别问用户」，:26），**决策归用户**；完成判据 = 前沿清空、"nothing left silently assumed"，译「不留任何默默的假设」，且用户确认共识前不动手（:28）。domain-modeling 同步把新词落进 CONTEXT.md、难逆决策落成 ADR。**若无此技能**：agent 拿着一句话需求直接开写，十几个未决策全靠它猜——对齐失败（三大失败模式之首）。

### 第 2 站 · 固化：to-spec 把对话变 spec

第一段就划界："Do NOT interview the user; just synthesize"（译「不要面审用户，只做综合」，to-spec:7）。写之前先画测试缝并跟用户确认——"Existing seams should be preferred… Use the highest seam possible… the ideal number is one"（译「优先既有缝……尽量用最高的缝……理想是一条」，:15）。模板七节，两条硬约束：user stories 要 "A LONG, numbered list"（译「一份长长的、编号的用户故事清单」）、"extremely extensive"（极其详尽）；实现决策**禁止文件路径和代码片段**——"They may end up being outdated very quickly"（译「它们很快就会过时」，:55——spec 是决策记录不是代码）。发布打 `ready-for-agent` 标签。**若无此技能**：决策散在对话里，下个会话就蒸发。

### 第 3 站 · 拆票：to-tickets 的 tracer-bullet 纵切片

每票三规则：**纵切**穿所有层（"schema, API, UI, tests: vertical, NOT a horizontal slice"，译「纵切穿过每一层（schema/API/UI/测试），不是水平切一层」，to-tickets:31）、**单票可 demo**、**单窗口装得下**（"sized to fit in a single fresh context window"，译「大小以装进一个全新上下文窗口为准」，:33——为第 4 站的 /clear 铺路）。每票声明 blocking edges；宽 refactor 是唯一例外，走 expand–contract 序列保 CI 恒绿。拆完三问用户（粒度/依赖边/合并拆分），迭代到批准再发布，然后 "Work the **frontier**"（译「在『前沿』上工作」，:65）——只做阻塞已清的票。**若无此技能**：水平切片（先写完所有 schema 再写 API）让每张票都无法独立验证。

### 第 4 站 · 实现：implement 驱动 tdd

你手动敲 `/implement <票号>`（user-invoked）。15 行正文是纯编排：用 /tdd、勤跑类型检查、最后 /code-review、commit。tdd 接管循环，三条纪律：**只在预约定缝上写测试**（"Before writing any test, write down the seams under test and confirm them with the user"，译「写任何测试前，先写下要测的缝并与用户确认」，tdd:22——缝从第 2 站传过来）；**红在绿前**、一次一片；**重构不进循环**——"It belongs to the review stage (see the code-review skill)"（译「重构属于评审阶段（见 code-review 技能）」，:38，职责外移）。三反模式有名字：implementation-coupled（重构就碎）、tautological（自证通过）、horizontal slicing（bulk 测试验证想象的行为）。接口形状本身有疑问时调 codebase-design 拿词汇——"a reference to consult, not a session to run"（译「是供查阅的参考，不是要跑的会话」）。**若无此技能**：测试追着实现写，mock 到私有方法，重构一次碎一片。

### 侧线 · 中途撞上间歇性 bug：diagnosing-bugs 六阶段

实现中报错间歇出现，description 命中 "reports something broken/throwing/failing/slow"——模型自动触发（model-invoked）。**Redact 先行**：一切展示的命令/输出/工件先脱敏，循环对 env var 构建让凭证留在环境里（:14，v1.2.3 新增 #779）。Phase 1 唯一目标：造**紧的红色回路**——"**This is the skill.** Everything else is mechanical"（译「这就是技能本体，其余全是机械活」，:20），十种造法按序尝试，完成后必须过五判据（red-capable/deterministic/fast/agent-runnable/已跑过一次），"No red-capable command, no Phase 2"（译「没有能变红的命令，就不进第二阶段」，:66）。Phase 2 复现+最小化（每个残留元素 load-bearing）；Phase 3 先出 **3–5 个可证伪假设排序**再测任何一个（"Single-hypothesis generation anchors on the first plausible idea"，译「单假设生成会锚死在第一个看似可信的想法上」，:90），列表给用户看但不阻塞；Phase 4 一次改一个变量、debug 日志打 `[DEBUG-a4f2]` 前缀（清理=一次 grep，:110）；Phase 5 回归测试**写在修复前**，且只在正确的缝上——"If no correct seam exists, that itself is the finding"（译「不存在正确的缝，这本身就是发现」，:120，架构问题升级而非硬测）；Phase 6 清单收尾，正确假设写进 commit——"so the next debugger learns"（译「让下一个调试的人学到」，:138）。**若无此技能**：读完代码直接给理论，改两行，bug 两周后回来。

### 第 5 站 · 评审：code-review 双轴不重排

"Review the changes since a fixed point"——先钉死基点并验证 ref 有效、diff 非空（坏 ref 在这里失败，不进子代理）。两轴**并行子代理**："so they don't pollute each other's context"（译「以免互相污染上下文」，code-review:11）：Standards 轴对照仓库文档规范 + 固定 Fowler 气味基线（12 条随技能自带，两条约束：**仓库规范覆盖基线**（:40）、**永远是 judgement call**、工具已管的跳过（:41））；Spec 轴对照原始 issue/spec 找缺失/越界/假实现。聚合纪律："Don't pick a single winner across axes: that's the reranking the separation exists to prevent"（译「不要在各轴之间挑唯一赢家：这种重排正是分轴要防止的」，:78）——分轴就是为了防止一轴掩盖另一轴。**若无此技能**：一份混排评审清单，规范问题和需求偏差互相淹没。

### 第 6 站 · 交付：pr 三段式

`## Summary`（用最小视图：伪代码/调用树/组件树/mermaid/diff 按需选）+ `## Evidence`（before/after，截图 S-tier、执行结果 A-tier，pr:160）+ `## Merge Danger`（one-way/two-way door + blast radius 一词——"A PR that is cheap to roll back is lower risk"，译「回滚便宜的 PR 风险更低」，:166）。全文用 CONTEXT.md 领域语言。frontmatter `metadata.credits` 注明模板借自 Humanlayer show-me（pr:6）——**借用注明出处被机制化**。**若无此技能**：PR 正文复述 diff，评审人自己找证据。

### 横切机制（任何一站可用）

- **wait-what**（7 行）："`Stop. That last message did not land: re-pitch it.`"（译「停。刚才那条消息没落地：换个讲法重讲」，wait-what:3）——没听懂就打断，要求用简明英语+CONTEXT.md 词汇重讲。
- **handoff**：交接文档写 **OS 临时目录不进工作区**（handoff:8）、必含 "suggested skills"（建议技能）段（:10）、不复制已有工件只引路径、脱敏。
- **阶段边界五选项**：Continue / /clear / /handoff / Subagent / /compact（默认垫底）——决策做在边界上，phase 中途不做。

## 主流程之外的地图（ask-matt 一览）

- **On-ramp 三条**：bug 堆积→/triage（只 triage 外来的，自产票已 agent-ready）；难 bug→/diagnosing-bugs；雾太大一次装不下→/wayfinder（产**决策**不产交付物，雾散后汇入 /to-spec——"it hands off, it doesn't build"（译「它交棒，不施工」）。
- **词汇层垫底**：domain-modeling（领域词/ADR）与 codebase-design（deep module/seam 词汇）是两个 model-invoked 参考，被上面的技能按需拉取——**共享词汇是技能间协议**。
- **Standalone**：prototype（抛弃式回答一个设计问题，结果作为 primary source 存 prototype/ 分支）、research（后台代理读材料落引用文件）、to-questionnaire（把问题写给**别人**填）、resolving-merge-conflicts（按意图逐 hunk 解，永不 --abort）、wizard（只为只有人能做的步骤生成 bash 向导——"If the agent could just do it itself, it should"（译「agent 自己能做的就该自己做」）、teach、writing-for-agents。

## 体系结构与治理（压缩）

- **成熟度分层**：engineering(18)/productivity(6)/misc(4, 冻结)/in-progress(8, 隔离)/deprecated；v1.2.3 多 harness 单源分发（Claude Code 插件/Codex/Copilot/Gemini CLI/npx skills），每 skill 一个 `agents/openai.yaml` 适配文件。
- **issue 双门槛**（SCOPE.md）：①观察到的失败（真实 session 证据，假想改进不过 bar）②符合哲学；`.out-of-scope/` 8 个文件把**拒绝本身**档案化；changesets 给每次行为修订绑定 issue 号——skill 有 semver 化变更日志。
- **人/Agent 面同名映射**：docs/engineering/*.md 与 skills/ 同名一一对应；仓库吃自己狗粮（GLOSSARY.md/AGENTS.md/ADR）。
- **v1.2.3 变更样例**（CHANGELOG）：diagnosing-bugs 加 Redact 段；code-review 系去掉 Claude Code 专属工具名（跨 harness 可跟随）；wizard 删时间估算——变更全是行为级的，走 changesets。

## 未读与局限

- 本轮通读 13 个 SKILL.md（主流程 8 + 横切 3 + ask-matt + setup）；其余 25 个（triage/wayfinder/domain-modeling/codebase-design/prototype/research/wizard/grill-me/teach/to-questionnaire/resolving-merge-conflicts/improve-codebase-architecture 及 in-progress·misc 全部）仅有 description 与 ask-matt 转述，未逐文件打开。
- 引用行号以本机插件 v1.2.3 为准，上游可能已推进；writing-for-agents 深读基于第七轮取回文本（SKILL.md + SKILL-MECHANICS.md），本轮未复读。
- 未运行任何 skill，未验证触发表现；多 harness 通道未实测安装。
