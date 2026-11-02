# skillresearch 研究过程与历史记录

本文件承接 `news/skillresearch.md` 外置的过程内容（2026-11-02 用户指令：报告保持结论简洁，过程放到其他文件）。结论只在报告（核心价值→检查点→案例索引），本文件只记录过程；逐案细节在本目录各案例卡。

## 候选筛选（十一轮）

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

第六/七/八轮候选中 VoltAgent/awesome-agent-skills（36,408★）登记未读留后续，第十轮 11-02 完成补读。第七/八/九/十/十一轮为并行子 agent 读取协议（子 agent 只读取转述附 file:line 证据、主 agent 抽查核对）；第九轮 11 子 agent、16 处抽查全吻合；第十轮 5 子代理（其中官方区第一段因 API 限流中断后由下一会话从 transcript 回收完整报告续跑，本地 README 缓存零重跑复用），主线程抽查 6 处全吻合（含裁定一处跨报告位置矛盾：VoltAgent 自家节为官方区第 2 位而非第 1）；第十一轮 4 子代理（总纲/rules-common/hooks/语言档），主线程抽查 2 处逐字吻合（rules/README.md:104-107、rules/common/agents.md:51-59）。案例卡随后按用户指令改为统一现状卡（旧轮次标注与 skill-comply 样本移出，5 件样本）。候选池已清空，下一轮需重新筛 GitHub 选例。

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
