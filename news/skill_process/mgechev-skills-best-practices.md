---
name: mgechev-skills-best-practices
source: https://github.com/mgechev/skills-best-practices
accessed: 2026-10-27
heat: 2,278 stars / 169 forks（2026-10-27 GitHub API 快照）；2026-02-24 创建，2026-07-27 最后 push（访问时已 3 个月无提交）
first_study: 2026-10-27
last_review: 2026-10-27
---

# mgechev/skills-best-practices

## 核心观点与价值

本卡最重要的一节，综合报告主要从这里引用：

1. **元数据确定性闸门**：能机械判定的规则打包成随 skill 附带的校验脚本，流程第一步命令执行、按 stderr 自纠重跑（为何成立：机械错误靠作者记忆必然漏；前提：规则确实可代码化）。
2. **四阶段验证梯 + 即用提示模板**：任何作者当场可用的廉价验证层——尤值一提的两个动作：模拟执行标出「被迫猜测的确切行」、边缘测试先问后修。
3. **stderr 即 agent 接口**：脚本错误消息按「字段+规则+修法方向」写，使失败成为自纠输入而非终点。
4. **skill 目录禁人类文档 + 模板即契约**：人类面与 Agent 面分离；输出形状用 assets 模板命令复制。
5. **router skill 组合模式**：无注册表生态下的轻量组合件。

## 整体定位

一个「把 skill 编写方法本身做成 skill」的 meta-skill 仓库：README 是给人看的方法指南，`skill/` 目录是一个可直接安装、指导 Agent 创建其他 skill 的技能。作者自述定位是「浓缩的最佳实践集」，明确不做全面文档并指向 platform.claude.com 官方指南（README.md:3-5），配套的 skill 评测工具放在另一个仓库 mgechev/skillgrade（README.md:7）。目标读者是 skill 作者；解决的问题是「skill 写出来没人保证能被正确触发、正确执行、不浪费上下文」。

## 体系结构与组织机制

**体量（git tree 2026-10-27 实测）：全库仅 5 个文件**——README.md（10,544 B）、`skill/SKILL.md`（4,313 B）、`skill/assets/SKILL.template.md`（974 B）、`skill/references/checklist.md`（2,441 B）、`skill/scripts/validate-metadata.py`（2,013 B）。本轮全部读取，100% 覆盖。

**双面结构（本对象最鲜明的组织决策）。** 人类面（README，讲道理、给对照示例）与 Agent 面（`skill/`，纯 agent 资产）物理分离。`skill/` 目录本身严格示范了它教的规范：标准三目录 `scripts/ references/ assets/` 全部一层平铺、无任何人类文档。「skill 目录内禁人类文档」（README.md:48-50 禁 README/CHANGELOG/INSTALLATION_GUIDE；SKILL.md Step 2.3；checklist §2 第 3 条）是贯穿三处的硬教条——理由是「Skills are for agents, not humans」（README.md:48），人类文档是浪费上下文的噪声；仓库级 README 放在 `skill/` 之外，与教条自洽。

**三层质控，按确定性分工**（研究者概括，依据见解剖样本）：
1. **确定性脚本**：`validate-metadata.py` 机械校验命名正则、长度、人称词——能代码判定的不进散文；
2. **LLM 协作验证梯**：README Validation Guide 四阶段（Discovery / Logic / Edge Case / Architecture Refinement），各配一段可直接粘贴的提示——判断性问题（description 是否过宽、正文哪里逼模型猜）交给 LLM；
3. **终审清单**：`references/checklist.md` 5 组 19 项，全部可数/可验证，部署前逐项 Pass（checklist.md:3「Every item must be marked as "Pass"」）。

**分发与组合。** 无插件系统，标准 agentskills 目录直装；技能组合用 router skill 模式——顶层 router 按条件分节指向子技能路径（README.md:74-98 的 build_project 示例：Client/Server 各节「To build the client…see [path to skill]」）。

## 解剖样本：skill-creator（`skill/`）

**一句话定位**：技能创建六步流程技能——从命名到终审，内置确定性校验脚本、模板资产与 19 项清单。这是对象内唯一的 skill。

**触发边界（文件事实）**。description 正触发「creating new skill directories, drafting procedural instructions, optimizing metadata」+ 负触发「Don't use for general documentation, non-agentic library code, or README files」（SKILL.md:2-3）——负触发与正触发并写，且该 description 自身就是 README.md:32-34 所教写法的活示例。

**任务契约**。输入=技能意图；产出=合规技能目录；完成判据=校验脚本通过 + checklist 全 Pass（SKILL.md Step 6.3）。

**机制拆解（逐条证据）**：
1. **元数据先过确定性闸门再动工**：Step 1.3 命令执行 `python3 scripts/validate-metadata.py --name ... --description ...`，Step 1.4「若脚本报错，按 stderr 输出自纠并重跑直至成功」（SKILL.md:13-15）。校验前移到流程第一步，机械错误在写正文之前就被拦下。
2. **脚本错误消息按 agent 界面设计**：每条错误=字段名+违反的规则+修法方向（如 NAME ERROR 给出字符数与合法字符集，STYLE WARNING 给出人称词清单并示范第三人称改写）（validate-metadata.py:10-19,33-36）；stdout=成功通道、stderr=失败通道是 checklist 明文要求（checklist.md:27「descriptive stdout for success and stderr for failure to allow agent self-correction」），README.md:72 把目的说破——「让 agent 无需用户介入即可自纠」。
3. **人称检查是词表启发式且硬失败**：禁用词表 {i, me, my, we, our, you, your}，整词匹配（validate-metadata.py:29-31）；但标着「STYLE WARNING」的错误实际进 errors 列表并 `sys.exit(1)`（validate-metadata.py:38-40）——标签语义（警告）与行为（硬失败）不一致【文件事实；研究者注：这使第三人称成为强制约束而非建议】。
4. **判断性内容模板化**：「输出有固定结构就放 `assets/` 模板并命令复制结构，而不是用段落描述」（SKILL.md:30；README.md:59「Agents pattern-match exceptionally well」）。本 skill 自身用 `assets/SKILL.template.md` 起稿（SKILL.md:26）——模板含决策树步、JiT 读取、错误处理的占位槽。
5. **模拟执行找「幻觉缺口」**：Step 6.1 要求审查 SKILL.md 中的「hallucination gaps（agent 被迫猜测之处）」（SKILL.md:48）；README Logic Validation 阶段把它操作化——喂全文+目录树，让 LLM 以已触发该技能的 agent 身份逐步模拟执行、输出内心独白，并「标出因指令含糊而被迫猜测/编造的确切行」（Execution Blockers，README.md:143-148）。
6. **边缘测试问答分离**：Edge Case 阶段让 LLM 换位「ruthless QA tester」提 3-5 个攻击性问题，并明确「先不要修，只提问并等我回答」（README.md:156-163）——发现与修复分离，防止模型把问题自我消化掉。
7. **错误处理写成分支恢复动作**：metadata 失败→按错误类型改写字段；超过 500 行→「抽出最大的过程块搬去 references/」（SKILL.md:52-54）。
8. **术语纪律到领域原生粒度**：不只「术语一致」，还要「用领域内最具体的那一个词」——Angular 语境用 "template" 而非 "html"/"markup"/"view"（README.md:64-65）。

**设计本质（研究者推论，下同）**：把「写 skill」变成 skill 的核心增量，是把可判定规则从作者自觉移交脚本与清单——skill 规模上的「确定性逻辑交给代码」；其验证方法论定位是**零基础设施层**：四阶段全部单会话粘贴即用，不需要 superpowers 式子 Agent 测试通道、≥5 样本与对照纪律。成立前提：LLM 能足够诚实地模拟执行与自我攻击（问答分离正是对这个前提的补丁）；代价：无 baseline 对照、无多样本方差、攻击者与被攻击者是同一个模型——自我审视不构成独立红队。

**边界**：校验脚本只管 metadata，SKILL.md 正文的 500 行上限靠 checklist 人肉核查（脚本无此检查）；人称词表仅覆盖英文，非英文 description 静默通过；该技能与 Anthropic 官方 `skill-creator` 同名不同物，多来源同装会撞名【研究者观察】；与官方规范交叉核对：name ≤64、description ≤1024、<500 行、引用一层平铺均与 agentskills 规范/platform.claude.com 文档（第二、三轮已读）一致，属收敛结论。

## 未读与局限

- 未运行 `validate-metadata.py`（研究规范禁止执行外部脚本）；其行为结论来自逐行阅读。
- 配套评测仓库 mgechev/skillgrade（README.md:7）与 SkillsBench 基准（README.md:104，arXiv 2602.12670）仅登记未读。
- README 所指 "agentskills.io spec" 未重新核对版本；issue/讨论区未查。
- 所有机制有效性判断基于文本证据与作者自述，未做独立实测；热度数字仅作筛选依据。
