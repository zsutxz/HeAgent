# AI Agent Skill 写作研究

**最后更新：** 2026-11-02 13:52（第十轮·VoltAgent；每次更新报告时刷新此行）
**研究日期：** 2026-10-24 起共十轮。逐案细节见 `skill_process/` 案例卡；候选筛选、逐轮记录、历史案例要点、局限与参考资料见 [skillresearch_process.md](skill_process/skillresearch_process.md)（2026-11-02 起本报告保持结论简洁，过程外置）。
**范围：** Agent Skills 开放格式规范、Anthropic 官方（agentskills 指南 + platform.claude.com 文档 + 官方样例库）、obra/superpowers、ECC、mgechev/skills-best-practices、google/skills、mattpocock/skills、addyosmani/agent-skills、VoltAgent/awesome-agent-skills 的逐案深读，以及 skill 的写作、触发与评测方法。
**摘要：** 好 skill 是能改变 Agent 执行结果的专业操作知识：从真实失败中抽取、按触发/契约/决策路径/失败处理组织、按失败类型选指导形式、触发与改善分开验证并核算成本。跨十轮收敛的硬结论：描述只管触发且不内嵌流程（三独立来源收敛）、发现层负例指名有效而执行层否定有害、停止条件写可数判据、可机械判定的规则下沉为脚本或构建闸（不留在 prompt）、评测从作者自觉升级为入库门禁、治理闭环四环（查重→选装→盘点→遵从）；目录层对偶结论——目录一句话是特征摘要、触发规格只在 frontmatter，目录名与技能真名常不一致，从目录复用描述必回读原文对齐真名。

## 核心价值

从各 skill 案例提取的可直接采用原则；跨案例重复已合并（注明来源案例）。

### 1. 写 Agent 缺少、且会改变结果的知识

从真实任务纠正、代码评审、事故记录和成功轨迹中找知识，逐条问"没有这条，Agent 最可能在哪里做错"；通用常识与无法关联失败模式的背景优先删。可正则/校验器强制的机械约束不要写成文档——自动化它（superpowers `writing-skills`）；一次性方案、通行做法、项目专属约定（归项目指令文件）不值得立 skill。**环境也是真相源**：`package.json`、config、`--help` 查得到的内容写进文档就成了 cache，只缓存 agent 查不到的（不成文约定、选择背后的理由、配置不自认的坑）（mattpocock `writing-for-agents`）。

**参考：** [agentskills 最佳实践](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/best-practices.mdx) "Start from real expertise"；[superpowers `writing-skills`](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md)。

### 2. 触发归 description：不内嵌流程、负向指名、指针措辞

description 是 Agent 无需打开正文就能"执行"的最短文本：内嵌流程摘要等于给绕过正文的捷径——superpowers 有实测失败案例（描述含"评审穿插"→Agent 只评审一次），mattpocock 指针学说与 addyosmani 明文规则（"Do not summarize the workflow"，docs/skill-anatomy.md:42）三独立来源收敛：**what 只写到"够选择"的粒度，步骤/阶段数/决策结构只留正文**。负向触发写**邻接指名**：google/skills 73% 的 description 含 "Don't use…（use X）"，负例既抑制误触发又把正确路由候选塞进同一句。指针措辞决定触发可靠性：引导词前置、每分支一个触发词、删正文已携带的身份信息。生成与构建两档强制（ECC）：skill-create 模板强制 "Use when" 开头并在替换前校验（commands/skill-create.md:118-130，但靠 LLM 自觉执行）；pi/core 构建闸把同类校验下沉为构建失败条件（build-pi-core.js:132-137）——能进构建管线的校验才是机器保证。

**参考：** [description 优化指南](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/optimizing-descriptions.mdx)（正负提示、near-miss、调优/验证集分离）。platform.claude.com 的 what+when 口径与 superpowers「只写 when」不同层（发现层选对 vs 遵从层真读正文）：综合口径 = what 到够选择粒度、流程结构只留正文；实测发现描述被当执行捷径时先砍描述流程内容。

### 3. 决策路径：默认值、阶段门、可数停止条件与完成判据

写清默认路径、分支条件、失败处理与停止条件；顺序脆弱的任务精确规定先后。**停止条件写可数判据**：superpowers `systematic-debugging`"尝试修复 <3 次回根因、≥3 次必须停下质疑架构"；google/skills 升级写成双条件命中即停+固定三动作（明说局限、汇总证据、转人工）+禁编造诊断。**完成判据 clarity × demand 双杠杆**（mattpocock）：清晰度防 premature completion，要求量措辞（"every modified model accounted for"）让挖掘活潜藏于措辞；先磨判据（便宜），观察到赶工才隐藏后续步骤，且只在真上下文边界有效。

**参考：** agentskills 最佳实践 "Match specificity to fragility"、"Provide defaults, not menus"；[systematic-debugging](https://github.com/obra/superpowers/blob/main/skills/systematic-debugging/SKILL.md)。

### 4. 按失败类型选指导形式；执行层正向措辞

| 基线失败 | 合适形式 | 不合适形式 |
|---|---|---|
| 压力下明知故犯（纪律失败） | 禁令 + 合理化表 + 红旗清单 | 软性建议 |
| 产出形状不对 | 正向配方：直接说产出是什么、分几部分 | 禁令清单 |
| 漏掉必备元素 | 结构槽位：模板 REQUIRED 字段 | 散文提醒 |
| 行为应取决于条件 | 绑定可观察谓词的条件 | 无条件规则+豁免条款 |

superpowers 措辞对照测试：对产出形状错误，禁令组无效内容显著多于配方组、甚至差于无指导；豁免条款不产生作用域，真有例外改写成条件谓词。**分层规则：发现层（description 路由）负例指名有效，执行层（正文措辞）否定有害**——否定是 elephant 效应（_don't think of an elephant_），禁令半读成做的指令；正向表述目标行为，禁令只留给无法正向表述的硬护栏且必须配正向目标（mattpocock "Negation" 节，与「纪律失败才用禁令」兼容）。使用前先对自己的场景微测试（结论来自 superpowers 自述实验，勿默认外推）。

**参考：** [superpowers `writing-skills` "Match the Form to the Failure" 与 "Micro-Test Wording"](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md)。

### 5. 解释机制与适用边界；model-neutral

简短理由帮 Agent 把规则迁移到未列出的情况；纪律型可用"违反字面即违反精神"堵整类狡辩。**model-neutral**（addyosmani）：不点名模型/版本/私有工具就无法成立的步骤进 issue 不进 skill（docs/skill-anatomy.md:159-163）；其引述的 WikiSkill（arXiv:2608.27454，未独立核实）称针对单模型失败写的 skill 可令更强模型劣于无 skill——适配不当可能是负增量。

### 6. 渐进式披露与上下文经济

`SKILL.md` 留每次触发都需要的主干，大段资料外置并写清"何时打开哪个"：

- **引用一层深**；>100 行引用文件开头放目录；脚本经解释器调用（`bash scripts/tool.sh`）并写明"执行还是参考"；MCP 工具全限定名；路径正斜杠。
- **脚本优于内联代码**（addyosmani docs/skill-anatomy.md:135）：执行脚本不耗 context（只有输出耗），内联代码每次加载都付费；状态消息走 stderr、机器可读走 stdout；参考资料 >100 行才外置、50 行内 inline。
- **预算跟加载时机走**：官方 `SKILL.md` <500 行；superpowers 对会话常驻技能另设 <200 词——不是单一数字。
- **作者侧确定性闸门**（mgechev）：可机械判定的规则（命名/长度/人称/层级）打包成校验脚本，流程第一步执行并"按 stderr 自纠重跑"；错误消息=字段+规则+修法方向。
- **Agent 面与人类面分离**：skill 目录禁 README/CHANGELOG 等人类文档；输出形状用 `assets/` 模板复制，不用散文。
- **库级路由**（google/skills）：常驻规则层只装命名前缀路由表，全量发现交运行时生成目录（带 "Do not edit by hand" 防手改标记）；fetch 优先于 install。
- **两种负载记账**（mattpocock）：context load（常驻材料的窗口成本）与 cognitive load（人类记住"有哪些文档、何时取用"）分开算；"The human is the index"；user-invoked 省 context 花认知，多到记不住用 router skill 集中还债。
- **库级构建期安全闸**（ECC）：发布档由显式白名单确定性生成，构建在违规时硬失败——非白名单 URL、pipe-to-shell、密钥、绝对家目录路径（三 OS）、symlink、坏 frontmatter、重名（build-pi-core.js:87,132-137,293-332，已核对实现）；每个排除对象进 CURATION.md 台账。配套硬指标：长度 200-500 行/800 max（SKILL-DEVELOPMENT-GUIDE.md:439）、示例代码按可编译资产验收（`tsc --noEmit`/`py_compile`/`go build`，:608-626）。**反样本**：同库 python-patterns（751 行）擦线过闸却零经济性——无外置、Good/Bad 双份代码、bare except 重复两处（L155-162≈L738-749，已核对）、速查表后置不起导航——行数 gate 拦不住结构性重复。

**参考：** [Agent Skills specification](https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx)；[platform.claude.com 最佳实践](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)；[skill_process/mgechev-skills-best-practices.md](skill_process/mgechev-skills-best-practices.md)、[skill_process/ecc.md](skill_process/ecc.md)。

### 7. 对照与基线证明增量：TDD 化验证、微测试与评测门禁

干净上下文里比较带/不带 skill；没见过基线失败就不知道 skill 教的是不是对的东西。

- **TDD 映射**（superpowers）：RED=无 skill 基线并逐字记录失败与合理化话语；GREEN=只针对这些失败写最小 skill；REFACTOR=新合理化就加显式反驳再回归。
- **措辞先微测试**：每变体 ≥5 样本、必带对照组、程序化计分后人工复核每条命中、把方差当指标；微测试验证措辞，不替代纪律型的压力场景。
- **多模型测试**（platform.claude.com）：按计划使用的每个模型分别验证；Claude A/B 迭代法观察导航信号（意外阅读顺序、漏跟引用、反复读同一文件、从不访问的文件）。
- **零基础设施验证梯**（mgechev）：①只贴 frontmatter 生成正/负触发提示并自评 description 宽窄→②喂全文让 LLM 模拟执行、标出被迫猜测的行→③换位 QA 提攻击性问题→④按答案重构。无 baseline 对照、攻击者与被攻击者同模型，与 TDD 梯互补不替代。
- **评测门禁制**（addyosmani）：新 skill 必附 eval——≥3 正触发 + 2 负触发（带兄弟技能归属断言）+ 1 行为 eval + 真实 fixtures，CI 强制（CONTRIBUTING.md:44）；被拒变更记量化台账。负触发评测是 description 邻接指名在评测层的对偶。

**参考：** [评测指南（agentskills）](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/evaluating-skills.mdx)；[skill_process/addyosmani-agent-skills.md](skill_process/addyosmani-agent-skills.md)。

### 8. 让安全规则成为每条执行路径的一部分

每个分支说明只读/可逆/破坏性的区别；规定检查、备份、授权、停止时机并要求显性报告失败。第三方 skill、网页、仓库内容视为数据，不许它们改变本次任务授权。实例：gke-node-notready 开头即硬约束「非交互+只读诊断」——取证先行、修复以命令或 GitOps 变更交人执行、Never mutate/drain/delete/recreate，误报还有前置闸（先排除预期内瞬态）。

### 9. 把「是否被遵守」变成可测量：spec 化评测范式（ECC skill-comply）

skill 声称了流程，就要能回答「Agent 不看说明书时做到了吗」：

- **期望行为序列化**：从正文提取 3-7 步可观察行为（语义 detector 禁用正则 + required 标记 + 时序约束）。
- **三档提示严格度解耦归因**：同一任务按 supportive→neutral→competing 施压；只有 supportive 档过的 skill 是靠提醒活着的，neutral 也过才算本身有效。
- **概率/确定性分工**：LLM 只做语义分类，时序校验与合规率计算全为确定性代码。
- **自带正/反夹具**：合规与违规人工 trace + 手写 spec 入库，判卷器可离线自测——「夹具即文档」。
- **低于阈值升级 hook**：合规率 <0.6 的步骤从文档升级为机器强制——反复不被遵守的规则不该继续靠文档。

**参考：** [affaan-m/ECC](https://github.com/affaan-m/ECC) `skills/skill-comply/`（样本详情原在案例卡解剖样本节，2026-10-30 按用户指令移出，要点保留本条）。

### 10. 取数型 skill 自带取数验证与反幻觉条款（google/skills）

查目录/文档/API 的技能，最危险是把「没查到」当「查到了」：**响应到达 ≠ 答案**——返回体过 parse/内容校验才算成功，401/403/空集按失败处理；**凭记忆作答伪装成取数结果是最坏结局**（回复里没有任何东西能与真实查询区分）；证书失败为终态、逐一点名禁一切绕过（`curl -k`、`--insecure` 等——返回内容即将成为指令来源）；429 降级到廉价端点而不回退记忆；网络失败有降级梯且在**回复里**显性报告。MCP 特有：声明了 server 不等于连得上，工具缺失属正常态、直接走 REST 备援。

**参考：** [skill_process/google-skills.md](skill_process/google-skills.md)。

### 11. 技能侧 attribution 遥测（google/skills）

每条直接执行的命令内联 attribution token（`CLOUDSDK_METRICS_REQUEST_ATTRIBUTION="agent-skills/1.0 (skill:<name>)"`），HTTP User-Agent 追加同一 token：**逐命令内联**（shell 状态不跨命令持久）、**追加不覆盖**（改写即断归因）、**豁免生成物**（不进交给用户的代码）、**用户可退出**。为技能维护提供生产环境的用量归因面。

### 12. 生态设计空间：作者制、分发、知识位置与治理形态

**作者制**：官方库封闭作者+内部验证；社区框架（superpowers）与治理合集（ECC）开放贡献，分别用 TDD 评测与遵从测量补质量——作者越分散越需要测量设施。**分发**：单体库 / 联邦 marketplace（google/skills 16 个插件钉回各产品仓库，中央库只做版本化聚合）/ monorepo 多 harness 镜像（ECC）/ 跨生态人工策展目录（VoltAgent：双轨收录 officialskills.sh 统一页 593 + GitHub 深链 632，赞助位无披露、分类随投稿漂移——目录层治理问题与技能层不同物）。**知识位置**：写进技能本体 vs 外置到活检索服务、技能只装取数协议（渐进披露的库级终极形态，代价是多一跳网络依赖）。**治理形态五例**：curated 个人库（mattpocock：issue 双门槛、`.out-of-scope/` 负向档案、changesets 版本化）、评测门禁制（addyosmani）、治理闭环四环（ECC：查重 skill-scout「创建需用户选择或无近似匹配」→选装 agent-sort→盘点 skill-stocktake→遵从 skill-comply；stocktake 判定显式声明 "holistic AI judgment — not a numeric rubric" 并强制 reason 自包含含证据——判定诚实比伪精确量表更可信）、TDD 化评测（superpowers）、人工策展 + 口头规则（VoltAgent：hand-picked 定位语 + 3 小时门槛 + ≤10 词规则，README 内置 Quality Criteria 表，实测执行落差约 40% 超词）。

**参考：** 各案例卡。

### 13. 词汇工程与修剪（mattpocock `writing-for-agents`）

**leading word**：复用模型预训练已有的紧凑概念（_red_、_tight_、_tracer bullets_）以 token 身份反复出现、锚定整片行为；自造词招募不到先验。重构信号：三处拼写的三元组折叠成一个 token。**no-op 猎杀**：模型默认就服从的指令白付负载；判据「相对默认是否改变行为」是 model-relative，分歧靠跑文档解决；失败时整句删除而非削词（第三来源收敛：addyosmani "If removing it wouldn't change agent behavior, remove it"，docs/skill-anatomy.md:156）。**sediment**：文档的默认命运是层层沉积（增加显得安全、删除显得危险），对抗靠修剪纪律。参考型 skill 也能靠 demand 型措辞携带穷尽性标准；与 superpowers 纪律型构成谱系两端：**纪律靠表，判断靠词**。

### 14. 能力面五问序：写之前先路由载体（ECC）

一个能力该做成什么载体？固定顺序五问（capability-surface-selection.md:17-28，已核对原文）：①确定性必触发、无模型判断→rule；②按需 playbook→skill；③多客户端结构化交互→MCP；④一次性本地动作→本地脚本（需要时再包 skill）；⑤窄远程调用→直连 API；拿不准"从小面起步"（L135-140）。价值在问的顺序：先排除 rule/MCP，把 skill 留给真正按需的知识层。配套落位按「来源×是否发布」：Curated→repo 随发布；Learned/Imported/Evolved→用户目录不入库、须 `.provenance.json`（SKILL-PLACEMENT-POLICY.md L7-12,31,41）。

**参考：** [skill_process/ecc.md](skill_process/ecc.md)。

### 15. 目录一句话是特征摘要：触发规格只在 frontmatter；目录名≠技能真名（VoltAgent）

awesome-list 目录（1231 条）README 一句话与 frontmatter 的保真度实证（3 样本 curl 对比，无一捏造、全部实质缩水）：压缩第一损失永远是**触发条件**（口语触发短语、动词覆盖面、"Use when..." 句式），第二是机制与证据（247 站点样本、eval loop、real-browser inspector），第三是结构（多技能分工与互斥路由——skill-optimizer 条目下 skill-generalizer 整条零呈现）。**与 §2 成对偶**：目录层（给人浏览）压掉的恰是路由层（给 agent）最需要的——面向人的目录文本不可作为触发判断依据，凡复用目录描述必回读 frontmatter 原文。**名实分离**：2/3 样本目录条目名≠frontmatter name（taste-skill→design-taste-frontend；skill-optimizer→仓库中不存在该名技能）——目录条目以仓库名行世，以 name 为锚的安装/触发/引用存在对齐裂缝，跨层引用先对齐真名。

**参考：** [skill_process/voltagent-awesome-agent-skills.md](skill_process/voltagent-awesome-agent-skills.md)。

### 16. 元技能是各生态自带的基础设施，密度极低（VoltAgent）

跨生态目录 1231 条中通用元技能仅 8 条（0.65%）；anthropics/microsoft/apollographql 三家各自造 skill-creator（前两家描述逐字近似），领域限定版（sentry-sdk-skill-creator、apollographql/skill-creator）是衍生模式——「教写 skill」被视为每个生态自带的基础设施而非共享公共品，新生态起步时 skill-creator 是标配。目录层同样自带元指导：README 内置 Quality Standards 节（第三人称 description、~100 token/<500 行、no absolute paths、scoped tools）——把质量标准写进目录文件本身。

**参考：** [skill_process/voltagent-awesome-agent-skills.md](skill_process/voltagent-awesome-agent-skills.md)。

## 检查点

- [ ] description 能让 Agent 识别真实用户意图，用正例、near-miss、负例验证触发边界；**描述不内嵌流程摘要**；负向边界指名替代技能；单行/折叠标量（禁字面块）。
- [ ] 从目录/marketplace 文案引用描述时回读 frontmatter 原文——目录一句话是特征摘要，触发规格与多技能路由只在 frontmatter；跨层引用以 name 为锚时先对齐技能真名（目录条目名≠frontmatter name 常见）。
- [ ] 输入、产出、成功标准和授权边界明确。
- [ ] 流程包含默认路径、关键分支、失败恢复、检查点和**可数的**退出/升级条件。
- [ ] 写指导前对基线失败分类，形式与失败类型匹配；执行层默认正向措辞（禁令只留给硬护栏且配正向目标）。
- [ ] 有条件读取的资料写清加载时机；引用一层深；>100 行引用带目录；脚本写明"执行还是参考"、经解释器调用、含依赖与失败行为；MCP 全限定名。
- [ ] 常驻技能与按需技能分别套用对应 token 预算。
- [ ] 干净上下文做同提示基线比较；纪律型另做压力场景；措辞改动先过微测试（含对照组）；覆盖计划使用的各模型。
- [ ] 流程型 skill 能序列化成 3-7 步可观察行为，按 supportive/neutral/competing 三档验证 prompt 独立性；关键正反样本以夹具形式随 skill 附带。
- [ ] 可机械判定的规则配校验脚本或可数清单（第一步执行、按 stderr 自纠）；发布档过构建期安全闸（URL/下载/密钥/家目录/symlink/frontmatter/重名 fail）且排除对象进台账。
- [ ] skill 目录只含 agent 资产；输出形状用 assets 模板复制。
- [ ] 交付前跑「模拟执行」：干净 LLM 按正文逐步模拟并标出被迫猜测的行；边缘场景先问后修。
- [ ] 调优集与最终验证集分开；结论标记为观测、推论或未验证假设。
- [ ] 取数型技能：返回体过 parse/内容校验才算成功；失败有降级梯且在**回复**中显性报告；严禁把记忆伪装成取数结果；证书失败终态禁绕过。
- [ ] 细粒度库：命名前缀约定当路由表；生成目录带防手改标记。
- [ ] 内置遥测：逐命令内联、append 不覆盖、豁免生成代码、用户可退出。
- [ ] 成本按两种负载记账；改 user-invoked 时确认人类索引跟得上；指针措辞前置引导词。
- [ ] 逐句猎杀 no-op（默认即服从=删整句）；复述环境内容的行改成指针或删除；leading word 用预训练概念锚定行为。
- [ ] 入库/发布附评测资产（≥3 正触发 + ≥2 负触发带归属断言 + ≥1 行为 eval + 真实 fixtures）；示例代码可编译；长度硬指标之外自查结构性重复与导航有效性。
- [ ] 写作前过能力面五问序（rule/skill/MCP/脚本/API，从小面起步）；新建前先搜后建，创建决定权留给用户；fork 改编只留想法与语义、实质扩缩改名；非 Curated 来源不入库、带 .provenance.json。
- [ ] 步骤 model-neutral；执行体用脚本不写内联代码。
- [ ] 想写「教写 skill」类元技能前，先查目标生态是否已有官方/领域版 skill-creator（该类技能是各生态自带基础设施，先复用再考虑新造）。

## 案例索引

| 案例 | 对象 | 一句话定位 | 案例卡 |
|---|---|---|---|
| 一 | Anthropic skill-creator 等 | 官方样例：评测闭环、反默认设计、分层资源 | （正文并入核心价值） |
| 二 | superpowers writing-skills / systematic-debugging | 社区框架：TDD 化文档工程、阶段门纪律 | （正文并入核心价值） |
| 三 | ECC | 治理合集：治理闭环四环、构建期安全闸、五问序 | [ecc.md](skill_process/ecc.md) |
| 四 | mgechev/skills-best-practices | 个人 meta-skill：确定性闸门、零基建验证梯 | [mgechev-skills-best-practices.md](skill_process/mgechev-skills-best-practices.md) |
| 五 | google/skills | 平台官方库：联邦分发、取数协议、attribution 遥测 | [google-skills.md](skill_process/google-skills.md) |
| 六 | mattpocock/skills | curated 个人库：两种负载、词汇工程、修剪纪律 | [mattpocock-skills.md](skill_process/mattpocock-skills.md) |
| 七 | addyosmani/agent-skills | 评测门禁制：CI 强制 eval、反合理化节序 | [addyosmani-agent-skills.md](skill_process/addyosmani-agent-skills.md) |
| 八 | VoltAgent/awesome-agent-skills | 跨生态策展目录：双轨收录、目录压缩失真、名实分离 | [voltagent-awesome-agent-skills.md](skill_process/voltagent-awesome-agent-skills.md) |

---

**可信度边界**：所有轮次均未运行被研究 skill、无对照评测；机制结论基于文本证据与来源自述，非独立实测。逐轮局限、候选筛选、历史案例要点与完整参考资料见 [skillresearch_process.md](skill_process/skillresearch_process.md)。
