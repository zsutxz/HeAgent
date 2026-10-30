---
name: mattpocock-skills
source: https://github.com/mattpocock/skills
accessed: 2026-10-28
heat: 304,944 stars / 25,661 forks（2026-10-28 API 快照，当期最高星 skill 仓库；创建 2026-02-03，最近 push 2026-10-27）
first_study: 2026-10-28
last_review: 2026-10-28
---

# mattpocock/skills

## 核心观点与价值

本卡最重要的一节，综合报告主要从这里引用：

1. **两种负载是 agent 文档架构的总账本。** context load（常驻材料的窗口成本）与 cognitive load（人类记住「有哪些文档、何时取用」的成本）是每份文档、每个指针都要花费的两本预算；拆不拆、内联还是披露、model-invoked 还是 user-invoked，全是同一权衡在不同位置的再分配。关键立场：认知负载**不是**要最小化的成本——"The human is the index"，它是 human agency 的价格，该花在人类判断重要的地方（SKILL.md "The two loads" 节）。这把「常驻成本 vs 按需成本」（官方口径）扩展成带人类维度的完整记账模型。
2. **指针的措辞，而非其目标，决定触发可靠性。** skill 的 description 与 AGENTS.md 里指向文档的一行是同一对象（context pointer）；「必须有但措辞弱」是 variance bug——先磨措辞，磨不动才内联。指针写法三条：引导词前置（触发工作就在这发生）、每个分支一个触发词（同义词改名 = 一个分支写两遍）、删掉正文已携带的身份信息（SKILL.md "Context pointers" 节）。
3. **完成判据是双杠杆：clarity × demand。** 每步以「什么算做完」结束；清晰度防 premature completion（可见的后续步骤产生赶工拉力，判据清晰度是阻力），要求量驱动 legwork（潜藏在措辞里的挖掘活，如 "every modified model accounted for"）——纯 reference 文档也能靠 "every rule applied" 携带穷尽性标准。防守顺序固定：先磨判据（局部、便宜）；只有判据不可再磨**且观察到赶工**才拆分隐藏后续步骤，且隐藏只在真上下文边界（hand-off / subagent dispatch）有效——inline 调用后续步骤仍在上下文里，清不掉（SKILL.md "Steps and completion criteria" 节）。
4. **leading word：用预训练概念锚定行为。** 模型预训练里已有的紧凑概念（_red_、_tight_、_tracer bullets_、_fog of war_）以 token 身份反复出现时积累分布式定义，用最少 token 锚定整片行为；自造词招募不到先验，定义成本自己付。双重锚定：正文内锚执行（词出现即取同一行为），指针内锚调用（同一词活在 prompt/文档/代码库里，agent 把共享语言链接到材料）。重构机会的识别：三处拼写的三元组（"fast, deterministic, low-overhead" → _tight_）、用一句话指意（"a loop you believe in" → _red_，把模糊闸门变成二元可观察状态）（SKILL.md "Leading words" 节）。
5. **执行层默认正向措辞，否定是失败模式。** 靠禁令引导会把被禁行为拉进上下文、变得更可用（_Don't think of an elephant_）；否定是弱修饰词，强激活的概念会碾过它，禁令半读成做这件事的指令。正向表述目标行为（"write one-line comments"），被禁的根本不说出口；禁令只保留给无法正向表述的硬护栏，且必须配对正向目标。与 google/skills 的负向触发合并看：**发现层（description 路由）负例指名有效，执行层（正文措辞）否定有害**——两层分工不同。
6. **修剪纪律与三个命名失败模式。** no-op 猎杀：模型默认就服从的指令白付负载，判据「相对默认是否改变行为」是 model-relative 而非 reader-relative——分歧靠跑文档解决、不靠辩论；失败时整句删除而非削词。duplication 与 co-location 相区分（重复 = 一个含义在两处；分散 = 一个含义碎在多处），单一真相源原则下唯一允许的重复是 leading word（重复 token 不重复含义）。**环境也是真相源**：`package.json` scripts、config、`--help` 查得到的别写进文档——复述环境的文档是 cache，只缓存 agent 查不到的（不成文约定、选择背后的理由、配置不自认的坑）。长期失败模式 sediment（沉积）：增加显得安全、删除显得危险，层层沉积直到要钻透它们找活行（SKILL.md "Pruning" 节）。

## 整体定位

Matt Pocock（Total TypeScript / AI Hero 作者）的个人日用 skills 仓库，自述 "Skills For Real Engineers——not vibe coding"。与 GSD、BMAD、Spec-Kit 等「接管整个流程」的框架正面对立：小、易改、可组合、声称 any model 可用（README 开篇）。热度为当期 GitHub skills 类仓库最高档（304,944★）。封闭作者制：PR 仅 collaborator 可开（CONTRIBUTING.md），新 skill 提案与捐赠直接关闭（`.out-of-scope/new-skills.md`：每个 skill 是永久维护面，必须与其它 skill、docs 页、ask-matt 路由图、plugin manifest 保持同步——「skill 越少越短，维持正确越便宜」）。

## 体系结构与组织机制

- **按成熟度分层目录**：`skills/` 下 engineering（20）/ productivity（6）/ misc（4）/ in-progress（7）/ deprecated（README）；misc 冻结不维护（SCOPE.md：issue 一律关闭）；in-progress 单独隔离，不进默认安装面。全库 291 个 tree 条目、38 个 SKILL.md。
- **多 harness 单源分发**：README 写明五条安装通道（Claude Code plugin 官方市场自动更新、Codex plugin、GitHub Copilot、Gemini CLI、`npx skills` 覆盖 cursor/opencode/devin/windsurf/amp/pi）；每个 skill 内 `agents/openai.yaml` 承载 Codex 特定配置（如 `policy.allow_implicit_invocation: false` 实现 user-invoked）——与 ECC 的 monorepo 多 harness 镜像目录不同，此处是单源 + 每 skill 一个适配文件。
- **issue 质控 bar（SCOPE.md）**：issue 存活须同时满足①观察到的失败（真实 session 跑了什么、skill 做了什么、期望什么；假想改进不过 bar）②符合哲学（不碰 `.out-of-scope/` 档案、非配置选项、非单人 workflow 适配）。一字修复与重写同 bar；reaction 与 +1 不计。无法判定的 issue 一轮提问 + needs-info 标签，14 天不回自动关。
- **负向范围档案（`.out-of-scope/`）**：8 个文件各记录一个被拒概念及理由（new-skills、subagent-recursion、native-question-tool、harness-name-collisions、question-limits 等）——拒绝本身被文档化为可引用资产，提重复提案前先读档案。
- **修订版本化（`.changeset/`）**：skill 的每次行为修订走 changesets 管理，一条 patch note 绑定 issue 号（样本 `tdd-seam-tradeoffs.md`：`tdd` 给每个提议的 seam 加一行「抓什么/漏什么」注记，#607）——skill 有 semver 化变更日志，为「行为变化可追溯」提供了比 CI 自愈 issue 更细的机制。
- **人类面/Agent 面同名映射**：`docs/engineering/*.md`、`docs/productivity/*.md` 与 `skills/` 同名一一对应，人类文档带 aihero.dev 词典链接；仓库自身也吃自己的狗粮（根 GLOSSARY.md、AGENTS.md、`.agents/adr/` 两篇 ADR）。
- **理念叙事**：README 按三大失败模式组织（#1 对齐失败 → grilling 系列；#2 冗长 → 共享语言 GLOSSARY/ADR，引 DDD；#3 代码不工作 → 小步 + TDD），每个失败模式引经典软件工程文献（《Pragmatic Programmer》、Evans）站台。
- **setup skill 抽象环境差异**：`setup-matt-pocock-skills` 每 repo 跑一次，把 issue tracker（GitHub/GitLab/local/自述）、triage 标签、docs 位置写进配置——其余 skill 面向抽象的 tracker/docs 接口而非硬编码 GitHub。

## 解剖样本：writing-for-agents

一句话定位：写任何 agent 消费文档的通用参考——skill、AGENTS.md/CLAUDE.md、指针可达文档；"The packaging differs; the writing does not"（SKILL.md:6）。v1.1 前名 `writing-great-skills`，改名以承认适用域远大于 skill（docs 面）。

- **触发边界**：description 仅两句——做什么（"Writing documents for agents"）+ 触发（"Use when creating or editing skills, or modifying AGENTS.md or CLAUDE.md"），无流程摘要，符合其自身指针学说。
- **形态自指**：全 reference、零步骤——它自己就是「all reference 是合法形态」的实例，并靠 demand 型措辞（no-op 判据、每个含义单一真相源）对读者携带穷尽性标准。这补上了第三轮 superpowers 案例边界里「参考型 skill 的内容组织几乎未被覆盖」的空白。
- **skill 专属机制按条件披露**：frontmatter、invocation 选择、router skill 全部外置到 `SKILL-MECHANICS.md`，SKILL.md:8 一行指针限定「写 skill 时才读」——渐进披露的教科书执行：非 skill 文档场景不付这笔负载。SKILL-MECHANICS 的核心增量为：model-invoked（description 常驻 = context load 换 discoverability，且 model-invocation 包含用户可达，不会移除人的入口）vs user-invoked（`disable-model-invocation: true`，零 context load，人是索引）；两个 user-invoked skill 共需的 reference 两边都住不下（无 description 互相点不着）→ 推到 skill 系统外的普通文件；router skill：user-invoked 多到记不住时用一个 router 命名其余（只能 hint 不能 fire）；按 invocation 拆分：只有当独立 leading word 值得一条新常驻 description 时才拆。
- **写作技术全部概念化**：每个 lever = 命名概念 + 定义 + 判别测试 + 失败模式 + 药方（context pointer / two loads / information hierarchy / completion criterion / leading word / negation / sprawl / sediment / no-op），不用 MUST 清单、不用阶段门——与 superpowers 纪律型形态（红旗表 + 计数器）构成谱系另一端：**纪律靠表，判断靠词**。
- **设计本质（研究者解释）**：它把「写 agent 文档」从风格偏好重构为一套可检验的负载会计与词汇工程；几乎所有建议都可归结为两种负载的再分配或先验的招募，因此能跨 packaging（skill/AGENTS.md/spec/提示词）迁移。
- **成立前提与代价**：前提是读者能接受高概念密度——全篇自造/半自造术语（context pointer、two loads、legwork、leading word、sediment）本身就是其 leading word 学说的展示，对新手是一笔一次性认知负载；未提供验证协议（无对照/微测试指引），效果验证交给了它的姊妹工程实践而非本 skill。

## 未读与局限

- 38 个 SKILL.md 仅深读本样本 1 个（+ SKILL-MECHANICS.md 全文）；其余 37 个只有 `skills/engineering/README.md` 的一句话定位，未逐一打开。
- `.agents/` 附属文件（invocation.md、writing-docs.md、ADR 0001/0002）、`.changeset/` 其余 17 个、`docs/engineering/*` 19 篇、GLOSSARY.md 内容未读（GLOSSARY.md 已取回未读）。
- docs 面仅读 writing-for-agents 一篇的前半；README 后半（失败模式 #3 之后）未读。
- 未运行任何 skill，未验证 trigger 表现；多 harness 通道仅按 README 与 `agents/openai.yaml` 的树内存在性记录，未实测各端安装。
- 热度为单日 API 快照；「当期最高星」截至 2026-10-28。
