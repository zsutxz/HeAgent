# skillresearch 研究过程与历史记录

本文件承接 `news/skillresearch.md` 外置的过程内容（2026-11-02 用户指令：报告保持结论简洁，过程放到其他文件）。结论只在报告（核心价值→检查点→案例索引），本文件只记录过程；逐案细节在本目录各案例卡。

## 候选筛选（十三轮）

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
| 十 | 11-02 | VoltAgent/awesome-agent-skills（首个目录/发现层对象：README 2002 行全读 + 73 节确定性清点 + 三区间深读 + 3 样本 frontmatter curl 抽验） | 36,726★/4,043 forks；当期最高星未研究对象 |
| 十一 | 11-02 | ECC 再复核·行为准则专项（用户点名，非热度选例）：AGENTS+CLAUDE 总纲 / rules common 10 件+README / hooks 24 件+memory-persistence 链 / 语言档抽样（python/typescript） | 292,862★；本地快照 ef648e01 不变 |
| 十二 | 11-03 | DietrichGebert/ponytail（候选池重筛；首个带受控基准评测设施的 skill 对象：全 6 SKILL.md + AGENTS.md + rules 副本 + CONTRIBUTING + check-rule-copies.js + behavior.yaml/behavior.test.js + 3 份基准结果文件直读） | 182,845★/132 contributors；topic:claude-skills+topic:agent-skills 重筛后最高星**纯 skill 对象** |
| 十三 | 11-03 | Leonxlnx/taste-skill（首个领域技能对象：SKILL.md 542 行 + research/critique/tells/copy 4 核心 references + app-screens 头节 + evals.json + CI + install.sh + draw.mjs 头注亲读） | 108,755★/7,321 forks/21 contributors；池内最高星未研纯 skill 对象（第十轮曾抽验 frontmatter，本轮清账） |

第六/七/八轮候选中 VoltAgent/awesome-agent-skills（36,408★）登记未读留后续，第十轮 11-02 完成补读。第七/八/九/十/十一轮为并行子 agent 读取协议（子 agent 只读取转述附 file:line 证据、主 agent 抽查核对）；第九轮 11 子 agent、16 处抽查全吻合；第十轮 5 子代理（其中官方区第一段因 API 限流中断后由下一会话从 transcript 回收完整报告续跑，本地 README 缓存零重跑复用），主线程抽查 6 处全吻合（含裁定一处跨报告位置矛盾：VoltAgent 自家节为官方区第 2 位而非第 1）；第十一轮 4 子代理（总纲/rules-common/hooks/语言档），主线程抽查 2 处逐字吻合（rules/README.md:104-107、rules/common/agents.md:51-59）。案例卡随后按用户指令改为统一现状卡（旧轮次标注与 skill-comply 样本移出，5 件样本）。候选池已清空，下一轮需重新筛 GitHub 选例。

**第十二轮选例与读取记录（2026-11-03，候选池重筛）**：以 topic:claude-skills（14,009 库）+ topic:agent-skills（40,466 库）双检索取 star 前 15 重排候选池。已研究名单外最高星为 morluto/rea（422,647★），核其树为主语言 TypeScript、7,565 文件的逆向工程**产品**，`.agents/skills/` 下 28 个 SKILL.md 为内部开发辅助（rea-changelog-update 等）——非「skill 对象」本体，记候选留后续（若研可作「产品仓库内部开发 skill」专题）。次高 DietrichGebert/ponytail（182,845★）为主语言即 skill 的纯 skill 对象（6 SKILL.md + 多 harness 镜像），选定。其余登记未读：Leonxlnx/taste-skill（108,661★，第十轮曾抽验 frontmatter）、pbakaus/impeccable（100,396★）、blader/humanizer（63,992★）、ayghri/i-have-adhd（59,824★）、coreyhaines31/marketingskills（58,088★）、K-Dense-AI/scientific-agent-skills（55,827★）、ComposioHQ/awesome-claude-skills（78,597★，目录型、与 VoltAgent 同层恐重复）。**读取方式**：克隆至临时目录（commit 96608e0）后主 agent 依「成组小文件直读」条款亲读全部引用材料（核心正文共 ~760 行 + 基准/测试/文档 ~1,700 行），无子代理转述环节、无抽查步骤（引用行号即亲读行号）。**传播采样降级**：stargazers `star+json` 端点匿名请求返回 "Requires authentication"（GitHub 收紧匿名访问），本机无 gh CLI——star 增速曲线未采样，为 SKILL.md 第 5 步确立以来首个数据源不可达降级案例；已采：created_at（2026-06-12）/contributors 132（Link 头末页号）/近期 30 commit 频次（10-13→10-29，约 1.9 commit/日，13 天内 v5.3.0→v5.3.3 四发版）/issues 负面证据（#126 基线反超 ~7×、#121 SDK 下 tool call 与成本上升、#764 误触政策拦截、#597 SubagentStart 全文注入、#863 OpenCode 2 断裂）/HN Algolia（story 49592706：33 pts 20 评论；JetBrains 独立测试文）/WebSearch 接收面（Reddit 作者重建帖、Stackademic「只沿一个轴改善」、towardsdeeplearning 质疑 54% 宣称、第三方评分 85/100）。

**第十三轮选例与读取记录（2026-11-03 同日第二轮）**：同日复核第十二轮池——topic:claude-skills star 前 10 出现工具/平台型新面孔（thedotmack/claude-mem 110,768★ 记忆插件、paperclipai/paperclip 110,404★ Agent 管理应用、tt-a1i/archify 92,742★ 图表生成 skill、Egonex-AI/Understand-Anything 89,918★ 代码库分析工具、code-yeongyu/oh-my-openagent 70,635★ 图谱工程工具），按第十二轮 rea 同一标准（非纯 skill 对象本体）不作首选，登记留档；池内最高星未研纯 skill 对象仍为 Leonxlnx/taste-skill（108,755★），且第十轮 VolAgent 案例仅抽验过其 frontmatter（名实分离样本 taste-skill→design-taste-frontend），本轮清账。morluto/rea（422,647★）维持第十二轮裁定不动（产品仓库，非 skill 本体；若研作「产品仓库内部开发 skill」专题）。**读取方式**：克隆至临时目录（pin `12af471f`，2026-10-25）后主 agent 依「成组小文件直读」条款亲读约 2,300 行（README 234 + SKILL.md 542 + skill README 81 + research.md 356 + critique.md 182 + tells.md 115 + copy.md 177 + app-screens.md 头 60 + CHANGELOG 头 90 + evals.json + CI workflow + install.sh 头 40 + marketplace.json ×2 + draw.mjs 头注 45 + inspect/rules grep + library JSON 结构清点），无子代理转述、无抽查环节。**传播采样降级（同第十二轮）**：star 增速曲线未采样（stargazers 端点要求认证 + 本机无 gh CLI）。已采：created_at 2026-02-19 / contributors 21（Link 头末页号）/ 近 30 commit（10-18→10-24 密集 v2.1.x 社区修复潮，#148-#172，含 2.1.2 frontmatter 事故→CI 门禁、2.1.3 单技能收敛）/ issues 温和（最热 #181/#185 为 inspector 误报修复、#154 措辞肯定化重构，无重大争议帖）/ HN Algolia 仅 1 条 3pts/0c 帖（2026-05-28）+ 邻接 Mollick 帖 / WebSearch 接收面：r/ClaudeCode UX/UI 对比帖（「decent UI 但仍有一点 slop 元素」）、r/opencodeCLI（「多个设计技能会打架，只装一个」）、r/ClaudeDesign 安装量 Top7 榜、daily.dev 介绍帖、skillleaderboard 收录。〔传播〕观察：社交讨论面小而安装量大（README 自带 star-history 徽章、5 个赞助商、TasteCode 桌面应用衍生物、加密货币抢注免责声明）——分发主干是技能目录/leaderboard 与 `npx skills add` 通道而非 HN/Reddit 辩论，与 ponytail（HN 33pts 主帖 + 第三方评测文）呈相反传播形态；无因果验证。

**案例卡结构重做（2026-11-02，第十一轮同日用户指令「总结输出还是太复杂：要深入到项目的 agent/skill 做深度分析、使用长场景、读者迅速了解核心观点」）**：卡片模板把「解剖样本」改为「长场景」（端到端链路按阶段推进，每站固定节奏 触发→强制→若无此技能→兑现核心观点），SKILL.md/ps1 生成链同步；mattpocock 卡首个按新结构重写，材料升级 = 本机已装插件 v1.2.3 全量 38 个 SKILL.md（主流程 13 个通读，第七轮「仅深读 1 个样本」的主流程部分就此清账，其余 25 个仍仅 description 级）；报告新增 §19（流程图一级资产/编排极薄/触发权分配/双轴不重排）。

**研究方法扩展：传播与接收面采样（2026-11-02，用户指令「采样更多数据、扩展研究方法，才更能理解本质」）**：起因是「mattpocock 为何能拿大量 star」一问暴露的方法盲区——文本证据答不了传播机制。SKILL.md 新增第 5 步：采用面（GitHub API 的 created/pushed/contributors/commit 频次 + stargazers `star+json` 分页抽样近似 star 曲线，400 页上限如实记录）+ 接收面（HN Algolia/Reddit/博客正反讨论 + issues 负面证据）+ 结论三级标注（[文本]/〔传播〕/〔推断〕）；传播数据只回答「为何流行」，不得佐证写作有效性。同时入 skill 的执行教训：材料获取优先本机已装插件缓存（全量 SKILL.md 直读）；成组小文件主 agent 直读 + grep 精确行号优于派子代理；复核轮先定专项主题。报告可信度边界行同步。存量 9 个案例的 star 增速与社区讨论为**未采样**状态，后续复核轮按主题补采。

## 历史案例要点（一、二轮正文压缩；细节已并入报告核心价值）

- **skill-creator**（Anthropic）：草拟→真实测试提示→with/without 基线→定性定量评估→改写→扩测；输出质量与触发评测分开，可定位失效在正文还是入口。小样本适合发现问题、不证明可靠性。
- **frontend-design**（Anthropic）：brief 驱动方向 + tokens/线框短计划 + 构建前反事实审查（"是否套任意 brief 都成立"）——低成本反默认门。
- **pdf**（Anthropic）：短入口 + 按任务分层长资源；表单先检测字段再分流，脚本错误回字段修正成恢复回路。314 行接近阈值、示例常驻成本不低。
- **superpowers `writing-skills`**：Iron Law（无失败测试不写 skill）；description 只写触发条件、第三人称、动名词命名；跨 skill 用 REQUIRED BACKGROUND 语义标记不强制加载；文末强制走完部署清单禁批量裸产。前提=可重复低成本独立上下文测试通道。
- **superpowers `systematic-debugging`**：四阶段逐级设门 + 红旗清单 + 合理化表 + 修复失败 ≥3 次强制停；"95% 无根因=调查不完整"是修辞断言。触发面极宽，大库中可能过度触发。
- **platform.claude.com 官方文档**：plan-validate-execute（批量/破坏性操作先产结构化计划、脚本验证后执行）、脚本"解决而非转交"、常量给依据、frontmatter 硬校验（name≤64、description≤1024 字符）。
- **冲突记录（保留）**：platform.claude.com 说 description 含 what+when，superpowers 实测要求只写 when——二者不同层（发现层选对 vs 遵从层真读正文）。综合口径已收录报告核心价值第 2 条。
- **mcp-builder / webapp-testing / doc-coauthoring**（第一轮）：分析已并入核心价值各条。

## 局限

- 所有轮次均未运行被研究 skill、无对照评测；机制结论基于文本证据与来源自述，非独立实测。热度均为单日快照。
- 第三轮起有对象级未读清单（各案例卡「未读与局限」节）；第九轮（ECC 复核）上游 main 超前本地快照，rules/agents/全量库其余 ~286 件、六语种镜像等未读，build-pi-core.js 安全闸为代码抽查非运行验证。
- 第八轮 "70+ agents" 与 WikiSkill 负迁移结论为来源自述；第五轮校验脚本「STYLE WARNING 标签但 exit(1)」为静态阅读发现；superpowers 措辞对照实验只有来源自述、无原始数据。
- platform.claude.com 页面代码示例在渲染中缺失，按文字论述取证。
- 样本集中于 Anthropic 生态 + 一个社区框架 + 四个高星库，未覆盖 Codex/Gemini 平台约定；不构成权威排名。
- 第十轮为静态阅读 README 单文件 + 3 样本 frontmatter 抽验；officialskills.sh 各页面与被收录仓库未系统访问（3 样本外）；「无捏造」结论限于 3 样本；徽章 1497+ vs 实测 1231 的差异成因未定；CONTRIBUTING 口径以第十轮前一会话主线程亲读为据。
- 第十一轮（ECC 行为准则专项）rules 层为抽样非全读：21 语言档只深读 python/typescript，rules 全层 ~100 文件仅覆盖 common 10 件 + README；5 个 Stop hook 实现、install.sh（疑似遗留接口）未核；语言档 frontmatter `paths` glob 的消费端（安装器是否真的按 glob 过滤安装）未验证，两层规则体系的「按项目命中」是基于文档自述。
- 第十二轮（ponytail）：star 增速曲线未采样（stargazers 端点要求认证 + 本机无 gh CLI，见上文降级记录）；JetBrains 博客全文抓取被域名校验拦截、结论取自搜索摘要；HN 帖 20 条评论仅采样可见前段，rvz「star 操纵」指控无证据无回应、仅录其存在；benchmarks/agentic/*.py 实现、5 份结果文件（llama3.2-local/robustness-audit/correctness-gate-fix/agentic-safety/2026-06-18-agentic）、hooks band/runtime/map/activate 实现、INSTALL.md、i18n、examples 正文、24 件测试中 22 件未读；585-session 头条基准为作者自报未独立复现（第三方独立基准亦未复跑）；`claude -p` headless + 无 shell 设定与真实交互会话有差距（作者已自注）。
- 第十三轮（taste-skill）：star 增速未采样（同第十二轮降级）；draw.mjs（584 行）/inspect.mjs（308）/rules.mjs（243）/cdp.mjs（248）仅读头注与关键 grep，检查项清单引自 CHANGELOG 2.1.0 与 research.md §9、规则 ID 未逐条核对实现；motion.md（980）/imagery.md（791）/layout.md（292）/scenes.md（174）/type.md/colour.md 六个 references 未通读（经 SKILL.md Files 表与 CHANGELOG 间接覆盖）；library JSON 仅结构清点未读内容；examples/*.webp 未查看；skill 级 README 末位补读（含文档漂移发现，已入卡）；接收面各帖仅搜索摘要级未抓全文；五轮盲测与 21-模型评审为作者自报未复现、评审用模型清单未披露；HN 无评论可采样。

## 参考资料

- [Agent Skills specification](https://github.com/agentskills/agentskills/blob/main/docs/specification.mdx)、[best-practices](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/best-practices.mdx)、[evaluating-skills](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/evaluating-skills.mdx)、[optimizing-descriptions](https://github.com/agentskills/agentskills/blob/main/docs/skill-creation/optimizing-descriptions.mdx)、[using-scripts](https://github.com/agentskills/agentskills/blob/main/docs/using-scripts.mdx)（agentskills/agentskills，2026-10-24；26,546★）
- [Skill authoring best practices（platform.claude.com）](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)（2026-10-26 全文）
- [anthropics/skills](https://github.com/anthropics/skills)（2026-10-24；183,391★）
- [obra/superpowers](https://github.com/obra/superpowers)（2026-10-26；304,853★）及 [writing-skills](https://github.com/obra/superpowers/blob/main/skills/writing-skills/SKILL.md)、[systematic-debugging](https://github.com/obra/superpowers/blob/main/skills/systematic-debugging/SKILL.md) 全文
- [affaan-m/ECC](https://github.com/affaan-m/ECC)（2026-10-26 初研 v2.2.1 / 2026-10-30 复核目录副本 ef648e01 / 2026-11-02 行为准则专项再复核；292,862★）→ [ecc.md](ecc.md)
- [mgechev/skills-best-practices](https://github.com/mgechev/skills-best-practices)（2026-10-27 全库取回；2,278★）→ [mgechev-skills-best-practices.md](mgechev-skills-best-practices.md)；配套 [mgechev/skillgrade](https://github.com/mgechev/skillgrade) 与 [SkillsBench (arXiv 2602.12670)](https://arxiv.org/abs/2602.12670) 登记未读
- [google/skills](https://github.com/google/skills)（2026-10-28；21,619★）→ [google-skills.md](google-skills.md)
- [mattpocock/skills](https://github.com/mattpocock/skills)（2026-10-28；304,944★）→ [mattpocock-skills.md](mattpocock-skills.md)
- [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)（2026-10-28；111,194★）→ [addyosmani-agent-skills.md](addyosmani-agent-skills.md)
- [VoltAgent/awesome-agent-skills](https://github.com/VoltAgent/awesome-agent-skills)（2026-11-02；36,726★/4,043 forks）→ [voltagent-awesome-agent-skills.md](voltagent-awesome-agent-skills.md)
- [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail)（2026-11-03；182,845★/132 contributors）→ [ponytail.md](ponytail.md)；本地克隆 commit 96608e0（2026-10-29，与当日 upstream pushed_at 一致）；独立接收面：[HN story 49592706](https://news.ycombinator.com/item?id=49592706)（2026-09-07，33 pts/20 c）、[JetBrains 独立测试](https://blog.jetbrains.com/ai/2026/07/ponytail-skill-claude-tested/)（2026-07-29，全文抓取被拦、取自搜索摘要）、[r/ClaudeAI 作者重建帖](https://www.reddit.com/r/ClaudeAI/comments/1x0hhg6/)、[Stackademic 质疑文](https://blog.stackademic.com/does-the-ponytail-skill-actually-improve-claude-code-or-just-cut-its-line-count-9e2f31a3b32a)
- [Leonxlnx/taste-skill](https://github.com/Leonxlnx/taste-skill)（2026-11-03；108,755★/7,321 forks/21 contributors）→ [taste-skill.md](taste-skill.md)；本地克隆 pin 12af471f（2026-10-25）；独立接收面：[r/ClaudeCode UX/UI 对比帖](https://www.reddit.com/r/ClaudeCode/comments/1syachi/best_skill_for_uxui_impeccable_vs_uxui_pro_max_vs)、[r/opencodeCLI 技能困惑帖](https://www.reddit.com/r/opencodeCLI/comments/1wqp3bb/im_confused_with_all_the_available_skills)、[r/ClaudeDesign Top7 帖](https://www.reddit.com/r/ClaudeDesign/comments/1vpi5mf/top_7_claude_skills_for_design_and_ui_by_install)、[daily.dev 介绍帖](https://daily.dev/posts/j2hnegj3l)、[skillleaderboard 页](https://www.skillleaderboard.com/skill/Leonxlnx-taste-skill)、[HN story 48306196](https://news.ycombinator.com/item?id=48306196)（2026-05-28，3 pts/0 c）
