# AI Agent Skill 写作研究

**最后更新：** 2026-11-03 06:45（第十二轮·ponytail；每次更新报告时刷新此行）
**研究日期：** 2026-10-24 起共十二轮。逐案细节见 `skill_process/` 案例卡；候选筛选、逐轮记录、历史案例要点、局限与参考资料见 [skillresearch_process.md](skill_process/skillresearch_process.md)（2026-11-02 起本报告保持结论简洁，过程外置）。
**范围：** Agent Skills 开放格式规范、Anthropic 官方（agentskills 指南 + platform.claude.com 文档 + 官方样例库）、obra/superpowers、ECC、mgechev/skills-best-practices、google/skills、mattpocock/skills、addyosmani/agent-skills、VoltAgent/awesome-agent-skills、DietrichGebert/ponytail 的逐案深读，以及 skill 的写作、触发与评测方法。
**摘要：** 好 skill 是能改变 Agent 执行结果的专业操作知识：从真实失败中抽取、按触发/契约/决策路径/失败处理组织、按失败类型选指导形式、触发与改善分开验证并核算成本。跨十二轮收敛的硬结论：描述只管触发且不内嵌流程（三独立来源收敛）、发现层负例指名有效而执行层否定有害、停止条件写可数判据、可机械判定的规则下沉为脚本或构建闸（不留在 prompt）、评测从作者自觉升级为入库门禁、治理闭环四环（查重→选装→盘点→遵从）；行为准则层——常驻规则与按需技能写法分道（what/how），模型可自我说服绕过的约束下沉为 hook 机器强制，并行委派必须配完成契约；目录层对偶结论——目录一句话是特征摘要、触发规格只在 frontmatter，目录名与技能真名常不一致，从目录复用描述必回读原文对齐真名；第十二轮（ponytail）补上实证地基——「操作化措辞优于态度化措辞」有受控实验证据、规则措辞变更可设三臂基准门禁、暂缓决定可债务化记账、自报收益指标需要反幻觉边界。

## 核心价值

从各 skill 案例提取的可直接采用原则；跨案例重复已合并（注明来源案例）。

### 1. 写 Agent 缺少、且会改变结果的知识

从真实任务纠正、代码评审、事故记录和成功轨迹中找知识，逐条问"没有这条，Agent 最可能在哪里做错"；通用常识与无法关联失败模式的背景优先删。可正则/校验器强制的机械约束不要写成文档——自动化它（superpowers `writing-skills`）；一次性方案、通行做法、项目专属约定（归项目指令文件）不值得立 skill。**环境也是真相源**：`package.json`、config、`--help` 查得到的内容写进文档就成了 cache，只缓存 agent 查不到的（不成文约定、选择背后的理由、配置不自认的坑）（mattpocock `writing-for-agents`）。

**参考：** [agentskills 最佳实践](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/best-practices.mdx) "Start from real expertise"；[superpowers `writing-skills`](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md)。

### 2. 触发归 description：不内嵌流程、负向指名、指针措辞

description 是 Agent 无需打开正文就能"执行"的最短文本：内嵌流程摘要等于给绕过正文的捷径——superpowers 有实测失败案例（描述含"评审穿插"→Agent 只评审一次），mattpocock 指针学说与 addyosmani 明文规则（"Do not summarize the workflow"，docs/skill-anatomy.md:42）三独立来源收敛：**what 只写到"够选择"的粒度，步骤/阶段数/决策结构只留正文**。负向触发写**邻接指名**：google/skills 73% 的 description 含 "Don't use…（use X）"，负例既抑制误触发又把正确路由候选塞进同一句。指针措辞决定触发可靠性：引导词前置、每分支一个触发词、删正文已携带的身份信息。生成与构建两档强制（ECC）：skill-create 模板强制 "Use when" 开头并在替换前校验（commands/skill-create.md:118-130，但靠 LLM 自觉执行）；pi/core 构建闸把同类校验下沉为构建失败条件（build-pi-core.js:132-137）——能进构建管线的校验才是机器保证。**触发词类别可扩展到情绪信号**（ponytail）：description 除领域动词外还收「用户抱怨」——"or complains about over-engineering or bloat"（skills/ponytail/SKILL.md:3-8），把「用户不满意现状」写成显式路由条件。

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

superpowers 措辞对照测试：对产出形状错误，禁令组无效内容显著多于配方组、甚至差于无指导；豁免条款不产生作用域，真有例外改写成条件谓词。**分层规则：发现层（description 路由）负例指名有效，执行层（正文措辞）否定有害**——否定是 elephant 效应（_don't think of an elephant_），禁令半读成做的指令；正向表述目标行为，禁令只留给无法正向表述的硬护栏且必须配正向目标（mattpocock "Negation" 节，与「纪律失败才用禁令」兼容）。使用前先对自己的场景微测试（结论来自 superpowers 自述实验，勿默认外推）。**ponytail 把这条从主张升级为受控实验**：修 bug 规则不写「要追溯根因」（态度）而写 `"grep every caller of the function you touch, then fix the root cause once in the shared code."`（skills/ponytail/SKILL.md:38）——对照实验里 pre-fix 版与纯 prose 版（"trace the flow end to end"）在 Opus 上均 0/3，只有操作版指令 6/6（ponytail 卡引 benchmarks/results/2026-06-22:50-52）；配套框架技巧：**把期望行为表述为目标价值系统内的最小阻力路径**（root-cause 修复 = "更懒/更小的 diff"），让 skill 自己的本能拉向正确行为而非逆本能下禁令。

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
- **skill 对自身同样记账**（ponytail）：极简 skill 本身必须极简——SKILL.md 115→95 行（"the minimalism skill should not be 2× caveman's length"）；输出侧配对规则 "if the explanation is longer than the code, delete the explanation"；注入器按 level 过滤 SKILL.md 时普通规则 bullet 必须 verbatim 保留、只有 mode 键名的表格行/工作示例可裁（hook 注释记录了「普通 bullet 被误当工作示例静默丢弃」的真实踩坑与引号值判定修复）；规则集的 skill 版/常驻版双形态经字节比对 + 不变量 canary 同步（见 §17）。

**参考：** [Agent Skills specification](https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx)；[platform.claude.com 最佳实践](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)；[skill_process/mgechev-skills-best-practices.md](skill_process/mgechev-skills-best-practices.md)、[skill_process/ecc.md](skill_process/ecc.md)。

### 7. 对照与基线证明增量：TDD 化验证、微测试与评测门禁

干净上下文里比较带/不带 skill；没见过基线失败就不知道 skill 教的是不是对的东西。

- **TDD 映射**（superpowers）：RED=无 skill 基线并逐字记录失败与合理化话语；GREEN=只针对这些失败写最小 skill；REFACTOR=新合理化就加显式反驳再回归。
- **措辞先微测试**：每变体 ≥5 样本、必带对照组、程序化计分后人工复核每条命中、把方差当指标；微测试验证措辞，不替代纪律型的压力场景。
- **多模型测试**（platform.claude.com）：按计划使用的每个模型分别验证；Claude A/B 迭代法观察导航信号（意外阅读顺序、漏跟引用、反复读同一文件、从不访问的文件）。
- **零基础设施验证梯**（mgechev）：①只贴 frontmatter 生成正/负触发提示并自评 description 宽窄→②喂全文让 LLM 模拟执行、标出被迫猜测的行→③换位 QA 提攻击性问题→④按答案重构。无 baseline 对照、攻击者与被攻击者同模型，与 TDD 梯互补不替代。
- **评测门禁制**（addyosmani）：新 skill 必附 eval——≥3 正触发 + 2 负触发（带兄弟技能归属断言）+ 1 行为 eval + 真实 fixtures，CI 强制（CONTRIBUTING.md:44）；被拒变更记量化台账。负触发评测是 description 邻接指名在评测层的对偶。
- **规则措辞变更门禁**（ponytail，强度最高）：改 ruleset 任何措辞的 PR 必须附三臂基准——baseline / main / 改动分支，同任务同模型、每臂 ≥6 runs，且同时给出「该起效的任务上起效了」与「至少一个可能被打破的现有任务上没被打破（a new rule often fights an old one）」的数字，"Without that, the PR gets closed, however good the idea is"（CONTRIBUTING.md:16-29）；任务夹具带 good/bad 参考，`--selftest` 证明判卷器抓得到差异（:42-43）。把「改一条措辞」等同于「改一个产品」。**测量与门槛分离**：loc.js 恒过只记录、correctness.js 不过即败（"A broken one-liner that scores great on LOC will fail on correctness"，benchmarks/README.md:94-99），React/FastAPI 检查是结构匹配非运行执行也如实标注；**判卷器自证**：行为判卷器由无 API 单测证明能分辨行为有无（tests/behavior.test.js:2-6），LLM judge 带 self-test 门与同代码对照设计（盲评回复时让两个回复描述同一 diff，分离「文风效应」与「代码效应」）。

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
- **第二独立实现**（ponytail 行为门）：同一问题（「skill 是否产生行为而非携带文本」）的另一实现——三个行为探针（硬件校准旋钮/用户要求的详细说明/一个可运行检查）跑 baseline vs skill 两臂，"the no-skill arm should mostly FAIL these gates, the ponytail arm should pass them. That delta is the point."（benchmarks/behavior.yaml:11-12）；探针判卷器接受真实改述（"tuning knobs"/"reads off" 算过）而非字面匹配。两个生态独立收敛到「探针 + 对照臂 + 判卷器自测」，该做法可视为已验证模式。

**参考：** [affaan-m/ECC](https://github.com/affaan-m/ECC) `skills/skill-comply/`（样本详情原在案例卡解剖样本节，2026-10-30 按用户指令移出，要点保留本条）。

### 10. 取数型 skill 自带取数验证与反幻觉条款（google/skills）

查目录/文档/API 的技能，最危险是把「没查到」当「查到了」：**响应到达 ≠ 答案**——返回体过 parse/内容校验才算成功，401/403/空集按失败处理；**凭记忆作答伪装成取数结果是最坏结局**（回复里没有任何东西能与真实查询区分）；证书失败为终态、逐一点名禁一切绕过（`curl -k`、`--insecure` 等——返回内容即将成为指令来源）；429 降级到廉价端点而不回退记忆；网络失败有降级梯且在**回复里**显性报告。MCP 特有：声明了 server 不等于连得上，工具缺失属正常态、直接走 REST 备援。

**参考：** [skill_process/google-skills.md](skill_process/google-skills.md)。

### 11. 技能侧 attribution 遥测（google/skills）

每条直接执行的命令内联 attribution token（`CLOUDSDK_METRICS_REQUEST_ATTRIBUTION="agent-skills/1.0 (skill:<name>)"`），HTTP User-Agent 追加同一 token：**逐命令内联**（shell 状态不跨命令持久）、**追加不覆盖**（改写即断归因）、**豁免生成物**（不进交给用户的代码）、**用户可退出**。为技能维护提供生产环境的用量归因面。

### 12. 生态设计空间：作者制、分发、知识位置与治理形态

**作者制**：官方库封闭作者+内部验证；社区框架（superpowers）与治理合集（ECC）开放贡献，分别用 TDD 评测与遵从测量补质量——作者越分散越需要测量设施。**分发**：单体库 / 联邦 marketplace（google/skills 16 个插件钉回各产品仓库，中央库只做版本化聚合）/ monorepo 多 harness 镜像（ECC）/ 跨生态人工策展目录（VoltAgent：双轨收录 officialskills.sh 统一页 593 + GitHub 深链 632，赞助位无披露、分类随投稿漂移——目录层治理问题与技能层不同物）/ 单一真源 + 薄适配器（ponytail：36 host 适配表逐 host 记验证版本与平台缺口，hook 每次从 SKILL.md 现读注入而非持副本，7 副本字节比对 + 10 条不变量短语 canary 防漂移，竞品 SKILL.md vendor 进库当对照臂）。**知识位置**：写进技能本体 vs 外置到活检索服务、技能只装取数协议（渐进披露的库级终极形态，代价是多一跳网络依赖）。**治理形态六例**：curated 个人库（mattpocock：issue 双门槛、`.out-of-scope/` 负向档案、changesets 版本化）、评测门禁制（addyosmani）、治理闭环四环（ECC：查重 skill-scout「创建需用户选择或无近似匹配」→选装 agent-sort→盘点 skill-stocktake→遵从 skill-comply；stocktake 判定显式声明 "holistic AI judgment — not a numeric rubric" 并强制 reason 自包含含证据——判定诚实比伪精确量表更可信）、TDD 化评测（superpowers）、人工策展 + 口头规则（VoltAgent：hand-picked 定位语 + 3 小时门槛 + ≤10 词规则，README 内置 Quality Criteria 表，实测执行落差约 40% 超词）、**基准门禁制个人库**（ponytail：skill 本体封闭作者、规则集开放但三臂基准强制——见 §7；独立第三方基准含负面结果照单全收并标注 "the numbers are theirs ... corroboration rather than official figures"）。

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

### 17. 常驻规则与按需技能写法分道；规则体系两层分离（ECC 行为准则专项）

四层分工一句话：**"Rules tell you _what_ to do; skills tell you _how_ to do it."**（rules/README.md:104-107，已核对原文）——规则常驻注入管「做什么/不许做什么」，skill 按需加载管「怎么做」，hook 在模型上下文外管机器强制，agent 管隔离上下文。落位按载体能力判，不是按内容重要性判。**写法分界**（rules/common/agents.md:51-59 等，已核对）：常驻规则**无 frontmatter**（不走路由，每次都在）、**无渐进披露**（常驻=全量付费，条目必须比 skill 更精）、条件分支写进正文（"当 X 时…"——不会被 description 路由）、重复内容**不抽取共享文件**（各注入路径独立整读，共享文件反增双份加载）。**两层规则体系**：common 10 文件无 frontmatter 恒装；21 语言档 ×5 文件带 frontmatter `paths` glob 按项目命中安装、`extends` 回链所属 common；优先级 specific overrides general；语言档用 "Language note" 标记局部覆盖 common 通则而非整段重写。**空壳档风险**：语言档只放覆盖标记无实质内容时，装了 glob 反而稀释 common——覆盖必须带实质。**第二来源佐证**（ponytail）：同一规则集的双形态发行——常驻版 `.agents/rules/ponytail.md` 30 行（无 frontmatter、无 levels、无会话语义），按需版 `skills/ponytail/SKILL.md`（frontmatter + 触发词 + 三档 level + 会话持久语义），两形态以字节比对 + 不变量短语 canary 强制同步；hook 缺 fallback 时注入的也是常驻版内容（ponytail 卡）。

**参考：** [skill_process/ecc.md](skill_process/ecc.md)。

### 18. 模型可自我说服绕过的约束下沉 hook；并行委派必须配完成契约（ECC）

**hook 选型判据**：反复不被遵守、且模型能自我说服绕过的纪律才值得机器强制（GateGuard 强制事实依据、config-protection 白名单保护配置文件）——hook 生效在模型上下文之外，模型不可协商。**强制点必须选事前**：PreToolUse 可 exit-2 硬拦，PostToolUse 只能观测不能拦。**fail-closed 有边界**：hook 输入被截断/解析失败按拦截处理（宁误拦不漏放），但操作员配置错误不拦（区分被保护对象与操作员自身）。**Delegation Completion Contract**（delegation-patterns）："Your final message IS the deliverable"——并行委派禁止 fire-and-forget，"the parallel rule without a completion contract produces zombie tasks"；子代理返回不是免检输入，主代理必须逐项验收（本报告第九/十/十一轮的抽查核对协议即此原则的应用）。

**参考：** [skill_process/ecc.md](skill_process/ecc.md)。

### 19. 技能库首先是流程：路由图一级资产、编排极薄、触发权显式分配（mattpocock v1.2.3 深读）

库自带路由（ask-matt："You don't remember every skill, so ask"）：主流程 idea→ship + 三条 on-ramp 汇入 + 词汇层垫底——**路由是技能库的一级资产**，不留给读者自己拼图。**编排技能极薄**：grill-with-docs 正文 7 行 = "Call the Skill tool twice"，implement 15 行 = "Use /tdd … use /code-review … Commit"——复杂度在链上，不在任何单点。**触发权按风险显式分配**：规划/写操作类一律 user-invoked（`disable-model-invocation: true`，人扣扳机），参考/纪律类才 model-invoked（tdd/diagnosing-bugs/code-review/wizard）。**评审双轴不重排**："Don't pick a single winner across axes"——分轴聚合就是为了防止一轴掩盖另一轴。小机制三件：借用模板用 frontmatter `metadata.credits` 注明出处（借用礼仪机制化）；diagnosing-bugs 的 Redact 段把脱敏写成正文第一步（写出来的纪律——与 ECC 的 hook 机器强制是同一目标的路线对照）；handoff 交接文档写 OS 临时目录、不污染工作区。

**参考：** [skill_process/mattpocock-skills.md](skill_process/mattpocock-skills.md)。

### 20. 规则措辞的生命周期治理：issue→证伪复现器→对照实验→回归检查→诚实判定（ponytail）

skill 的每条规则都是一个假设，ponytail 给出了一条完整的假设检验流水线：**issue 报告行为失败**（#245 "Dangerously lazy"：shortest-diff 本能让 agent 只补被告警的路径）→ **可证伪复现器**（trace-transfer：评分器专考报告*未点名*的兄弟调用方；bad 参考答案在 happy path 完全正确、只在争议点偷工——"This run is built to be able to *disprove* the fix, not flatter it"）→ **操作化措辞修复 + 价值内框架**（§4）→ **对照实验**（pre-fix 0/3、纯 prose 版 0/3、操作版 6/6——把「起效的是操作措辞而非 prose 情绪」钉死）→ **回归检查**（27 任务 pre/post：安全恒 1.0、省码保持、correctness 无系统变化）→ **诚实判定**（#245 fixed and validated；#217 rung 按请求发布但复现失败——"the behavioural value is unproven here"；Haiku 不改善且 baseline 同样全挂——判定为模型能力天花板而非回归）。配套两个诚实机制：**null 结果公开**（盲评裁判对无 skill 臂回复质量判无显著差异 p=0.09/0.22，如实写进结果文件；README 亲手给自家单发基准头条打 honesty note——"counts prose, not just code, and overstates the win"）；**反样本公开**（per-task 表保留 ponytail 行数多于 baseline 的格子，vibe-md2html PT5 139 行 vs PT 106 行）。对比 §7 的门禁：门禁管「进门时有效」，本条管「进门后持续被检验」。

**参考：** [skill_process/ponytail.md](skill_process/ponytail.md) 引 benchmarks/results/2026-06-22、2026-10-07-agentic。

### 21. 暂缓债务化与自报指标的反幻觉边界（ponytail）

**暂缓决定要有格式、账本和复审权**：已知限制写成固定格式注释 `"shortcut: <the limit>, <when to upgrade>"`（skills/ponytail/SKILL.md:42），三环互认——写作端打标、评审端把已声明 shortcut 认定为 "a decision, not a finding, unless the expected load already crosses it"（ponytail-review/SKILL.md:63-64，避免同一决定被反复翻案）、记账端 /ponytail-debt 收账并对「没写升级触发」的标记打 `no-trigger` 标——"those are the ones that silently rot"（ponytail-debt/SKILL.md:36-37）；结尾强制计数 `<N> markers, <M> with no trigger.`，标记词可由用户替换。**自报收益要设反幻觉边界**：记分牌技能明文 NEVER 打印单仓库节省数字——"the unbuilt version was never written, so there is no real baseline to subtract from in a live repo"（ponytail-gain/SKILL.md:44-48），要真数指向 /ponytail-debt 的实数账本而非现场编反事实；基准数字声明 "They are measured, not computed from the current repo"。这是 §10「取数型反幻觉」在**自我指标**上的对偶：没有真实基线的对比数就是幻觉，宁缺毋造。

**参考：** [skill_process/ponytail.md](skill_process/ponytail.md)。

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
- [ ] 常驻准则与按需技能分家：必须常驻的 what 进规则（无 frontmatter、无渐进披露、条件分支写正文、不抽共享文件），按需的 how 进 skill；语言/场景档只在有实质覆盖内容时才装（空壳档稀释 common）。
- [ ] 模型能自我说服绕过的纪律下沉 hook：强制点选事前（PreToolUse 可拦、PostToolUse 只能观测）；输入截断 fail-closed，操作员配置错误不拦。
- [ ] 并行委派配完成契约：子代理最终消息即交付物、主代理逐项验收，禁止 fire-and-forget。
- [ ] 设计多技能库先画流程图（路由是一级资产）；编排技能保持极薄（只指名相邻技能）；触发权显式分配（规划/写操作 user-invoked 人扣扳机，参考/纪律类才 model-invoked）。
- [ ] 步骤 model-neutral；执行体用脚本不写内联代码。
- [ ] 想写「教写 skill」类元技能前，先查目标生态是否已有官方/领域版 skill-creator（该类技能是各生态自带基础设施，先复用再考虑新造）。
- [ ] 规则措辞可执行化：每条规则写成操作（grep X、运行 Y、输出字段 Z）而非态度句；期望行为表述为目标价值系统内的最小阻力路径，不逆本能下禁令（ponytail #245 对照实验：操作版 6/6 vs prose 版 0/3）。
- [ ] 改规则 = 改产品：措辞变更附三臂基准（baseline/main/change、同任务同模型、每臂 ≥6 runs、收益任务 + 回归任务双证据）；任务夹具带 good/bad 参考且判卷器过 --selftest。
- [ ] 证伪设计：评分器考「报告未点名的失效路径」；bad 参考答案在 happy path 正确、只在争议点偷工；行为门探针验证「规则产生行为而非携带文本」（no-skill 臂应挂、skill 臂应过）。
- [ ] 判卷器先自证：评分脚本/LLM judge 有无 API 自测证明能分辨行为有无；测量指标与门槛指标分离并声明；结构匹配检查如实标注非运行验证；LLM 盲评配同代码对照与 self-test 门。
- [ ] 暂缓债务化：已知限制用固定格式注释（`shortcut: <限制>, <升级触发>`）；账本给无触发者打 no-trigger 标并以计数收尾；评审把已声明 shortcut 认定为决定而非发现（除非负载越限）。
- [ ] 自报收益设反幻觉边界：不给无真实基线的现场反事实数字（"the unbuilt version was never written"），要真数指向可数账本；null 结果与反样本（本方法更差的格子）如实公开。
- [ ] 多 harness/多副本分发以单一真源 + 薄适配器发行：注入器从源文件现读；副本字节比对 + 载荷规则不变量短语 canary（每条带出处）；生成式同步作为已知升级路径；平台能力缺口（如丢弃 SubagentStart、被动 hook 不能注入）逐 host 记录在适配表。

## 案例索引

| 案例 | 对象 | 一句话定位 | 案例卡 |
|---|---|---|---|
| 一 | Anthropic skill-creator 等 | 官方样例：评测闭环、反默认设计、分层资源 | （正文并入核心价值） |
| 二 | superpowers writing-skills / systematic-debugging | 社区框架：TDD 化文档工程、阶段门纪律 | （正文并入核心价值） |
| 三 | ECC | 治理合集：治理闭环四环、构建期安全闸、五问序、行为准则分层 | [ecc.md](skill_process/ecc.md) |
| 四 | mgechev/skills-best-practices | 个人 meta-skill：确定性闸门、零基建验证梯 | [mgechev-skills-best-practices.md](skill_process/mgechev-skills-best-practices.md) |
| 五 | google/skills | 平台官方库：联邦分发、取数协议、attribution 遥测 | [google-skills.md](skill_process/google-skills.md) |
| 六 | mattpocock/skills | curated 个人库：主流程接力路由、seam 纪律、双轴评审、词汇工程 | [mattpocock-skills.md](skill_process/mattpocock-skills.md) |
| 七 | addyosmani/agent-skills | 评测门禁制：CI 强制 eval、反合理化节序 | [addyosmani-agent-skills.md](skill_process/addyosmani-agent-skills.md) |
| 八 | VoltAgent/awesome-agent-skills | 跨生态策展目录：双轨收录、目录压缩失真、名实分离 | [voltagent-awesome-agent-skills.md](skill_process/voltagent-awesome-agent-skills.md) |
| 十二 | DietrichGebert/ponytail | 基准门禁制个人库：操作化措辞受控实验、三臂规则门禁、暂缓债务化、单一真源分发 | [ponytail.md](skill_process/ponytail.md) |

---

**可信度边界**：所有轮次均未运行被研究 skill、无对照评测；机制结论基于文本证据与来源自述，非独立实测（ponytail 案例的基准数字为作者自报，第三方独立基准未复跑）。2026-11-02 起方法扩展增加传播与接收面采样（star 增速/贡献者/社区讨论/负面证据），此前热度均为单日快照、传播结论缺数据支撑；第十二轮 ponytail 的 star 增速曲线因 stargazers 端点要求认证且本机无 gh CLI **未采样**（仅有总量快照）。逐轮局限、候选筛选、历史案例要点与完整参考资料见 [skillresearch_process.md](skill_process/skillresearch_process.md)。
