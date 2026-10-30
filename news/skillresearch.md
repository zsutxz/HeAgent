# AI Agent Skill 写作研究

**研究日期：** 2026-10-24 起共九轮（第四/三轮 2026-10-26、第五轮 10-27、第六/七/八轮 10-28、第九轮·ECC 复核 10-30）。自第四轮起逐案细节外置到 `skill_example/<对象名>.md` 案例卡，本报告只留综合方法与案例索引；案例卡以「核心观点与价值」开篇，报告固定三部分（核心价值→检查点→研究过程与重要参考点）。
**范围：** Agent Skills 开放格式规范、Anthropic 官方（agentskills 指南 + platform.claude.com 文档 + 官方样例库）、obra/superpowers、ECC、mgechev/skills-best-practices、google/skills、mattpocock/skills、addyosmani/agent-skills 的逐案深读，以及 skill 的写作、触发与评测方法。
**摘要：** 好 skill 是能改变 Agent 执行结果的专业操作知识：从真实失败中抽取、按触发/契约/决策路径/失败处理组织、按失败类型选指导形式、触发与改善分开验证并核算成本。跨九轮收敛的硬结论：描述只管触发且不内嵌流程（三独立来源收敛）、发现层负例指名有效而执行层否定有害、停止条件写可数判据、可机械判定的规则下沉为脚本或构建闸（不留在 prompt）、评测从作者自觉升级为入库门禁、治理闭环四环（查重→选装→盘点→遵从）。

## 核心价值

从各 skill 案例提取的可直接采用原则；跨案例重复已合并（注明来源案例）。

### 1. 写 Agent 缺少、且会改变结果的知识

从真实任务纠正、代码评审、事故记录和成功轨迹中找知识，逐条问"没有这条，Agent 最可能在哪里做错"；通用常识与无法关联失败模式的背景优先删。可正则/校验器强制的机械约束不要写成文档——自动化它（superpowers `writing-skills`）；一次性方案、通行做法、项目专属约定（归项目指令文件）不值得立 skill。**环境也是真相源**：`package.json`、config、`--help` 查得到的内容写进文档就成了 cache，只缓存 agent 查不到的（不成文约定、选择背后的理由、配置不自认的坑）（mattpocock `writing-for-agents`）。

**参考：** [agentskills 最佳实践](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/best-practices.mdx) "Start from real expertise"；[superpowers `writing-skills`](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md)。

### 2. 触发归 description：不内嵌流程、负向指名、指针措辞

description 是 Agent 无需打开正文就能"执行"的最短文本：内嵌流程摘要等于给绕过正文的捷径——superpowers 有实测失败案例（描述含"评审穿插"→Agent 只评审一次），mattpocock 指针学说与 addyosmani 明文规则（"Do not summarize the workflow"，docs/skill-anatomy.md:42）三独立来源收敛：**what 只写到"够选择"的粒度，步骤/阶段数/决策结构只留正文**。负向触发写**邻接指名**：google/skills 73% 的 description 含 "Don't use…（use X）"，负例既抑制误触发又把正确路由候选塞进同一句。指针措辞决定触发可靠性：引导词前置、每分支一个触发词、删正文已携带的身份信息。生成与构建两档强制（ECC）：skill-create 模板强制 "Use when" 开头并在替换前校验（commands/skill-create.md:118-130，但靠 LLM 自觉执行）；pi/core 构建闸把同类校验下沉为构建失败条件（build-pi-core.js:132-137）——能进构建管线的校验才是机器保证。

**参考：** [description 优化指南](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/optimizing-descriptions.mdx)（正负提示、near-miss、调优/验证集分离）；冲突记录见第三部分。

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

**参考：** [Agent Skills specification](https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx)；[platform.claude.com 最佳实践](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)；[skill_example/mgechev-skills-best-practices.md](skill_example/mgechev-skills-best-practices.md)、[skill_example/ecc.md](skill_example/ecc.md)。

### 7. 对照与基线证明增量：TDD 化验证、微测试与评测门禁

干净上下文里比较带/不带 skill；没见过基线失败就不知道 skill 教的是不是对的东西。

- **TDD 映射**（superpowers）：RED=无 skill 基线并逐字记录失败与合理化话语；GREEN=只针对这些失败写最小 skill；REFACTOR=新合理化就加显式反驳再回归。
- **措辞先微测试**：每变体 ≥5 样本、必带对照组、程序化计分后人工复核每条命中、把方差当指标；微测试验证措辞，不替代纪律型的压力场景。
- **多模型测试**（platform.claude.com）：按计划使用的每个模型分别验证；Claude A/B 迭代法观察导航信号（意外阅读顺序、漏跟引用、反复读同一文件、从不访问的文件）。
- **零基础设施验证梯**（mgechev）：①只贴 frontmatter 生成正/负触发提示并自评 description 宽窄→②喂全文让 LLM 模拟执行、标出被迫猜测的行→③换位 QA 提攻击性问题→④按答案重构。无 baseline 对照、攻击者与被攻击者同模型，与 TDD 梯互补不替代。
- **评测门禁制**（addyosmani）：新 skill 必附 eval——≥3 正触发 + 2 负触发（带兄弟技能归属断言）+ 1 行为 eval + 真实 fixtures，CI 强制（CONTRIBUTING.md:44）；被拒变更记量化台账。负触发评测是 description 邻接指名在评测层的对偶。

**参考：** [评测指南（agentskills）](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/evaluating-skills.mdx)；[skill_example/addyosmani-agent-skills.md](skill_example/addyosmani-agent-skills.md)。

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

**参考：** [skill_example/google-skills.md](skill_example/google-skills.md)。

### 11. 技能侧 attribution 遥测（google/skills）

每条直接执行的命令内联 attribution token（`CLOUDSDK_METRICS_REQUEST_ATTRIBUTION="agent-skills/1.0 (skill:<name>)"`），HTTP User-Agent 追加同一 token：**逐命令内联**（shell 状态不跨命令持久）、**追加不覆盖**（改写即断归因）、**豁免生成物**（不进交给用户的代码）、**用户可退出**。为技能维护提供生产环境的用量归因面。

### 12. 生态设计空间：作者制、分发、知识位置与治理形态

**作者制**：官方库封闭作者+内部验证；社区框架（superpowers）与治理合集（ECC）开放贡献，分别用 TDD 评测与遵从测量补质量——作者越分散越需要测量设施。**分发**：单体库 / 联邦 marketplace（google/skills 16 个插件钉回各产品仓库，中央库只做版本化聚合）/ monorepo 多 harness 镜像（ECC）。**知识位置**：写进技能本体 vs 外置到活检索服务、技能只装取数协议（渐进披露的库级终极形态，代价是多一跳网络依赖）。**治理形态四例**：curated 个人库（mattpocock：issue 双门槛、`.out-of-scope/` 负向档案、changesets 版本化）、评测门禁制（addyosmani）、治理闭环四环（ECC：查重 skill-scout「创建需用户选择或无近似匹配」→选装 agent-sort→盘点 skill-stocktake→遵从 skill-comply；stocktake 判定显式声明 "holistic AI judgment — not a numeric rubric" 并强制 reason 自包含含证据——判定诚实比伪精确量表更可信）、TDD 化评测（superpowers）。

**参考：** 各案例卡。

### 13. 词汇工程与修剪（mattpocock `writing-for-agents`）

**leading word**：复用模型预训练已有的紧凑概念（_red_、_tight_、_tracer bullets_）以 token 身份反复出现、锚定整片行为；自造词招募不到先验。重构信号：三处拼写的三元组折叠成一个 token。**no-op 猎杀**：模型默认就服从的指令白付负载；判据「相对默认是否改变行为」是 model-relative，分歧靠跑文档解决；失败时整句删除而非削词（第三来源收敛：addyosmani "If removing it wouldn't change agent behavior, remove it"，docs/skill-anatomy.md:156）。**sediment**：文档的默认命运是层层沉积（增加显得安全、删除显得危险），对抗靠修剪纪律。参考型 skill 也能靠 demand 型措辞携带穷尽性标准；与 superpowers 纪律型构成谱系两端：**纪律靠表，判断靠词**。

### 14. 能力面五问序：写之前先路由载体（ECC）

一个能力该做成什么载体？固定顺序五问（capability-surface-selection.md:17-28，已核对原文）：①确定性必触发、无模型判断→rule；②按需 playbook→skill；③多客户端结构化交互→MCP；④一次性本地动作→本地脚本（需要时再包 skill）；⑤窄远程调用→直连 API；拿不准"从小面起步"（L135-140）。价值在问的顺序：先排除 rule/MCP，把 skill 留给真正按需的知识层。配套落位按「来源×是否发布」：Curated→repo 随发布；Learned/Imported/Evolved→用户目录不入库、须 `.provenance.json`（SKILL-PLACEMENT-POLICY.md L7-12,31,41）。

**参考：** [skill_example/ecc.md](skill_example/ecc.md)。

## 检查点

- [ ] description 能让 Agent 识别真实用户意图，用正例、near-miss、负例验证触发边界；**描述不内嵌流程摘要**；负向边界指名替代技能；单行/折叠标量（禁字面块）。
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

## 研究过程与重要参考点

### 候选筛选（九轮）

热度仅决定选谁、不证明质量；均为当日 GitHub API 快照。

| 轮次 | 日期 | 对象 | 热度与依据 |
|---|---|---|---|
| 一~二 | 10-24 | agentskills 规范/指南；anthropics/skills（skill-creator、frontend-design、pdf 等） | 183,391★；官方样例库起步 |
| 三 | 10-26 | obra/superpowers（writing-skills、systematic-debugging）+ platform.claude.com 文档 | 304,853★；刻意换生态 |
| 四 | 10-26 | ECC（用户指定生态；本地 v2.2.1，样本 skill-comply） | 全库 618 SKILL.md（含镜像） |
| 五 | 10-27 | mgechev/skills-best-practices（全库 5 文件 100% 覆盖） | 2,278★；与研究主题直接同构 |
| 六 | 10-28 | google/skills（第二平台官方库，样本 gke-node-notready） | 21,619★；联邦分发 |
| 七 | 10-28 | mattpocock/skills（样本 writing-for-agents） | 304,944★；当期最高星未研究对象 |
| 八 | 10-28 | addyosmani/agent-skills（样本 context-engineering；并行协议首跑） | 111,194★ |
| 九 | 10-30 | ECC 复核（用户点名，非热度选例）：本地目录副本 E:/AI/ecc-trimmed（post-2.2.3 快照 ef648e01） | 292,862★/43,341 forks/push 同日超前本地 |

第六/七/八轮候选中 VoltAgent/awesome-agent-skills（36,408★）登记未读留后续。第七/八/九轮为并行子 agent 读取协议（子 agent 只读取转述附 file:line 证据、主 agent 抽查核对）；第九轮 11 子 agent、16 处抽查全吻合；案例卡随后按用户指令改为统一现状卡（旧轮次标注与 skill-comply 样本移出，5 件样本）。

### 案例索引

| 案例 | 对象 | 一句话定位 | 案例卡 |
|---|---|---|---|
| 一 | Anthropic skill-creator 等 | 官方样例：评测闭环、反默认设计、分层资源 | （正文并入核心价值，见下「历史案例要点」） |
| 二 | superpowers writing-skills / systematic-debugging | 社区框架：TDD 化文档工程、阶段门纪律 | 同上 |
| 三 | ECC | 治理合集：治理闭环四环、构建期安全闸、五问序 | [ecc.md](skill_example/ecc.md) |
| 四 | mgechev/skills-best-practices | 个人 meta-skill：确定性闸门、零基建验证梯 | [mgechev-skills-best-practices.md](skill_example/mgechev-skills-best-practices.md) |
| 五 | google/skills | 平台官方库：联邦分发、取数协议、attribution 遥测 | [google-skills.md](skill_example/google-skills.md) |
| 六 | mattpocock/skills | curated 个人库：两种负载、词汇工程、修剪纪律 | [mattpocock-skills.md](skill_example/mattpocock-skills.md) |
| 七 | addyosmani/agent-skills | 评测门禁制：CI 强制 eval、反合理化节序 | [addyosmani-agent-skills.md](skill_example/addyosmani-agent-skills.md) |

### 历史案例要点（一、二轮正文压缩；细节已并入核心价值）

- **skill-creator**（Anthropic）：草拟→真实测试提示→with/without 基线→定性定量评估→改写→扩测；输出质量与触发评测分开，可定位失效在正文还是入口。小样本适合发现问题、不证明可靠性。
- **frontend-design**（Anthropic）：brief 驱动方向 + tokens/线框短计划 + 构建前反事实审查（"是否套任意 brief 都成立"）——低成本反默认门。
- **pdf**（Anthropic）：短入口 + 按任务分层长资源；表单先检测字段再分流，脚本错误回字段修正成恢复回路。314 行接近阈值、示例常驻成本不低。
- **superpowers `writing-skills`**：Iron Law（无失败测试不写 skill）；description 只写触发条件、第三人称、动名词命名；跨 skill 用 REQUIRED BACKGROUND 语义标记不强制加载；文末强制走完部署清单禁批量裸产。前提=可重复低成本独立上下文测试通道。
- **superpowers `systematic-debugging`**：四阶段逐级设门 + 红旗清单 + 合理化表 + 修复失败 ≥3 次强制停；"95% 无根因=调查不完整"是修辞断言。触发面极宽，大库中可能过度触发。
- **platform.claude.com 官方文档**：plan-validate-execute（批量/破坏性操作先产结构化计划、脚本验证后执行）、脚本"解决而非转交"、常量给依据、frontmatter 硬校验（name≤64、description≤1024 字符）。
- **冲突记录（保留）**：platform.claude.com 说 description 含 what+when，superpowers 实测要求只写 when——二者不同层（发现层选对 vs 遵从层真读正文）。综合口径：what 到够选择粒度、流程结构只留正文；实测发现描述被当执行捷径时先砍描述流程内容。
- **mcp-builder / webapp-testing / doc-coauthoring**（第一轮）：分析已并入核心价值各条。

### 局限

- 所有轮次均未运行被研究 skill、无对照评测；机制结论基于文本证据与来源自述，非独立实测。热度均为单日快照。
- 第三轮起有对象级未读清单（各案例卡「未读与局限」节）；第九轮（ECC 复核）上游 main 超前本地快照，rules/agents/全量库其余 ~286 件、六语种镜像等未读，build-pi-core.js 安全闸为代码抽查非运行验证。
- 第八轮 "70+ agents" 与 WikiSkill 负迁移结论为来源自述；第五轮校验脚本「STYLE WARNING 标签但 exit(1)」为静态阅读发现；superpowers 措辞对照实验只有来源自述、无原始数据。
- platform.claude.com 页面代码示例在渲染中缺失，按文字论述取证。
- 样本集中于 Anthropic 生态 + 一个社区框架 + 四个高星库，未覆盖 Codex/Gemini 平台约定；不构成权威排名。

### 参考资料

- [Agent Skills specification](https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx)、[best-practices](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/best-practices.mdx)、[evaluating-skills](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/evaluating-skills.mdx)、[optimizing-descriptions](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/optimizing-descriptions.mdx)、[using-scripts](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/using-scripts.mdx)（agentskills/agentskills，2026-10-24；26,546★）
- [Skill authoring best practices（platform.claude.com）](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)（2026-10-26 全文）
- [anthropics/skills](https://github.com/anthropics/skills)（2026-10-24；183,391★）
- [obra/superpowers](https://github.com/obra/superpowers)（2026-10-26；304,853★）及 [writing-skills](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md)、[systematic-debugging](https://github.com/obra/superpowers/blob/main/skills/systematic-debugging/SKILL.md) 全文
- [affaan-m/ECC](https://github.com/affaan-m/ECC)（2026-10-26 初研 v2.2.1 / 2026-10-30 复核目录副本 ef648e01；292,862★）→ [skill_example/ecc.md](skill_example/ecc.md)
- [mgechev/skills-best-practices](https://github.com/mgechev/skills-best-practices)（2026-10-27 全库取回；2,278★）→ [skill_example/mgechev-skills-best-practices.md](skill_example/mgechev-skills-best-practices.md)；配套 [mgechev/skillgrade](https://github.com/mgechev/skillgrade) 与 [SkillsBench (arXiv 2602.12670)](https://arxiv.org/abs/2602.12670) 登记未读
- [google/skills](https://github.com/google/skills)（2026-10-28；21,619★）→ [skill_example/google-skills.md](skill_example/google-skills.md)
- [mattpocock/skills](https://github.com/mattpocock/skills)（2026-10-28；304,944★）→ [skill_example/mattpocock-skills.md](skill_example/mattpocock-skills.md)
- [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)（2026-10-28；111,194★）→ [skill_example/addyosmani-agent-skills.md](skill_example/addyosmani-agent-skills.md)
- [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)（36,408★；仅热度参考，未读）
