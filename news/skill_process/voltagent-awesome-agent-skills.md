---
name: voltagent-awesome-agent-skills
source: https://github.com/VoltAgent/awesome-agent-skills
accessed: 2026-11-02
heat: 36,726 stars / 4,043 forks（2026-11-02 GitHub API 快照；PR 编号已过 #1308）
first_study: 2026-11-02
last_review: 2026-11-02
---

# VoltAgent/awesome-agent-skills

**最后更新：** 2026-11-02

## 核心观点与价值

本卡最重要的一节，综合报告主要从这里引用：

1. **目录一句话是特征摘要，触发规格只在 frontmatter**。3 样本 curl 实证（无一捏造、全部实质缩水）：压缩第一损失永远是触发条件（口语触发短语、动词覆盖面、"Use when..." 句式），第二是机制与证据（247 站点样本、eval loop、real-browser inspector），第三是结构（多技能分工与互斥路由——skill-optimizer 条目下 skill-generalizer 整条零呈现）。与本研究「描述只管触发」结论成对偶：目录层（给人浏览）压掉的恰是路由层（给 agent）最需要的——**面向人的目录文本不可作为触发判断依据**。
2. **名实分离**：2/3 样本目录条目名 ≠ frontmatter name（taste-skill→design-taste-frontend；skill-optimizer→仓库中不存在该名技能）。目录条目以仓库名行世，以 name 为锚的安装/触发/引用存在真实对齐裂缝，跨层引用先对齐真名。
3. **双轨收录机制**：officialskills.sh 统一页（593 条，URL 恒为 `/<owner>/skills/<name>`）vs GitHub 深链（632 条），另有商业目录（catalog.redhat.com 4）、裸 SKILL.md 直链（paulo.com.br 1）、产品官网（notion.so 1）。经验规律（数据归纳，文件未写成规则）：企业大厂与高流量个人走统一页，自维护仓库的中小团队走深链；高频重组的官方目录给入口不复制快照——NVIDIA 节明文 "links to the maintained source instead of duplicating a snapshot"（L1466），全节仅 1 条目录入口。
4. **位置即广告，且无披露机制**：三家头部赞助商（SerpApi/Crawlbase/TestMu AI）占 anthropics 与运营方之后的 3-5 位，节首带 UTM 赞助参数链接；全文无星标数、无任何排序标准说明——策展排序是利益空间而文件没有披露标签。
5. **运营方自荐位**：VoltAgent 自家 4 条技能排官方区第 2 位（L143-152，`<details open>` 的 Official Claude Skills 之后、所有外部团队之前），与外部团队节同构、无任何标记区分自家与外部——利益相关位置是结构事实，是否存在偏袒文件未言明。
6. **元技能密度 0.65%**：1231 条中通用元技能仅 8 条；anthropics/microsoft/apollographql 三家各自造 skill-creator（前两家描述逐字近似），领域限定版（sentry-sdk-skill-creator、apollographql/skill-creator）是衍生模式——「教写 skill」被视为每个生态自带的基础设施而非共享公共品。
7. **分类学漂移**：CONTRIBUTING 声称的 7 类与 README 实际 7 子类仅 5 个重合（README 多 Vector Databases/Specialized Domains、少 AI and Data/Other）；Specialized Domains（62 条）事实充当 Other；n8n 类 7/8 条来自同一仓库（整仓打包成类）+ 1 条无关条目——分类随投稿批量漂移、文档与实际失同步。
8. **口头门槛与执行落差**：「Hand-picked, not AI-slop generated」（L13）+「不收刚创建 3 小时的 skill」+「描述 ≤10 词」规则 vs 实测约 40% 条目超 10 词（抽样 30 条计 12 条违规）、Notion 节 4 条技能整组重复收录（L1400-1410，全库唯一条目级重复）、OpenAI/Figma 跨节重复（L875-882 vs L895-901）、humanizer-ru/playwright-skill 各有同名对——策展真实活跃（2026-10 单月 100+ 提交）但规则执行不一致。
9. **描述风格三种生态口径**：官方团队区祈使动词开头 5-15 词、普遍含触发场景词（TestMu AI 49 条几乎全部 `Generate X tests in <lang>` 模板句）；Microsoft 区 SDK 镜像口径（133 条短名词短语跨语言逐字复用，子分组轴 = 语言/技术栈）；社区区数量钩子（`125 skills`、`753 rules`）+ 跨 agent 兼容声明 + 许可证标签 + 基准自夸（`measured -49% tokens`）直接进描述。
10. **README 自带元指导**：Skill Quality Standards 节（L1966-1978，Quality Criteria 表 4 行：第三人称 description、metadata ~100 token/正文 <500 行、no absolute paths、scoped tools）+ Other AI Coding Assistants 安装路径表——人工策展目录把质量标准写进文件本身（与 google/skills 机器生成目录的防手改标记互为对照物）。

## 整体定位

本研究**第一个分发/发现层对象**：前九轮研究技能本身（写法/治理/验证），本卡研究技能的目录层——跨生态人工策展 awesome-list，定位语 "Hand-picked, not AI-slop generated."。README 单文件承载 1231 条目（徽章自述 1497+，实测 1231，成因未定）、73 个 `<details>` 折叠节，格式合规率 99.6%（1228/1231 带 author/ 前缀）——千条规模单文件目录仍维持格式一致性的实证。与 google/skills 对照：google 是单一生态联邦聚合（机器生成目录 index.json），VoltAgent 是跨生态人工策展（手写目录），质量机制不同物——评测门禁/生成目录 vs 人工策展 + 口头规则。

## 体系结构与组织机制

**1. 全库结构（确定性清点）。** 官方团队区 66 节 869 条（L120-1525）+ 社区区 7 节 362 条（L1529-1936）= 1231 精确闭合（三区间深读加总 294+575+362 交叉吻合）。官方区排序：anthropics 第 1（唯一 `<details open>`）、VoltAgent 第 2、赞助商 3-5 位；Microsoft 133 条为最大单体节（6 语言子分组、全部 microsoft/ 前缀、描述跨语言逐字复用、全部链统一页——企业批量收录的 SDK 目录语言）。目录表锚点疑似失效 3 处、节标题畸形 2 处（Sentry 尾句号、Addy Osmani 标题内嵌 " - "）、Venice.ai/Expo/Zero 目录与正文错位。

**2. 格式契约与变体。** 标准格式 `- **[author/skill-name](url)** - 短描述` 合规 99.6%；变体仅三类：三级名称 20 条（google/cloud/*）、粗体分组子标题（Dean Peters/Pawel Huryn/Notion）、"More from X (not skills, but they pair with them)" 配套工具附加组（SerpApi/Crawlbase）——附加组条目非技能但仍按标准格式书写。无多行描述、无空描述、无分隔符变异（社区区 L1556 一处 `**:` 冒号变异除外）。

**3. 社区区分类学。** 7 子类非字母序、呈插入序/批量块形态（同仓连排：dreammis 18 条连排、NeoLabHQ 6 条连排）。边界模糊实证：obra/superpowers 劈两半（Productivity 6 + Dev&Testing 9）、NeoLabHQ 一仓横跨三子类（仓库名就叫 context-engineering-kit）、去 AI 味技能散落 3 个子类、"委托其他 agent CLI" 散落 3 个子类；同名对 humanizer-ru×2、playwright-skill×2 各自描述口径漂移。

**4. 质量治理。** 口头规则三件套（hand-picked 定位语、3 小时门槛、≤10 词）+ README 内置 Quality Criteria 表 + 不复述规则的正文——规则散在 CONTRIBUTING 与 README 两处且互不复述，实测执行落差约 40% 超词。策展节奏核实（2026-10 单月 100+ 提交、PR 过 #1308、维护者主动把错放条目并回正确子类）证明人工策展在真实运转，而非一次性 AI 批量生成。

**5. 元技能生态位。** 通用元技能 8 条 = anthropics 2（skill-creator/template）+ microsoft 1 + 社区 5；skill-optimizer 条目实为三技能合集（skill-miner/personalizer/generalizer，互斥路由 "Do not use to tune an existing skill; use skill-personalizer"）；README 描述写成泛化能力文档化的 obra/writing-skills 与实际内容明显不对口——目录层对元技能同样压缩失真。

## 解剖样本：描述保真度抽验（3 样本 curl 实证）

**选样**：2 元技能 + 1 非元技能对照，逐条对比 README 一句话 vs 仓库 frontmatter description 原文。

- **hedralab/eskill**（L1686）：README 五要素清单与正文 12 支柱对得上，无捏造；但技能正文与触发短语**全是越南语而 README 未标语言**，frontmatter 靠逐字口语短语触发（"tạo skill"/"viết SKILL.md"/"skill Cursor"），README 特征清单不含任何触发语义；改善旧 skill、商业出售、Cursor 安装路径三场景丢失。
- **hqhq1025/skill-optimizer**（L1745）：仓库中**不存在名为 skill-optimizer 的技能**，实为三技能合集；README 只呈现诊断/优化半边，skill-generalizer（私有路径/凭证脱敏后发布——安全相关功能链）整条零呈现；三技能互斥路由丢失，「发现→调优→公开化」生命周期管线压成一句诊断描述。
- **Leonxlnx/taste-skill**（L1727，frontmatter name 为 design-taste-frontend）：触发动词 6→1（build/design/redesign/restyle/polish/review 只剩 slop 一个触发点）；app screens（dashboard/admin/设置页）半壁江山丢失；247 精选站点样本、real-browser inspector、look-and-fix 循环三个最有辨识度的机制声明全部不在 README。

**结论（3 样本，比例推断有限）**：「不编造但大量缩水」是该目录压缩的准确定性；损失序 = 触发 > 机制证据 > 结构。保真度对目录自身用途（给人浏览选型）够用，对安装后用途（agent 触发判断）不够——凡复用目录描述做触发判断必须回读 frontmatter 原文。

## 未读与局限

- 全程静态阅读 README 单文件（2002 行全读：73 节确定性清点 + 三区间深读分工全覆盖）+ 3 样本 frontmatter curl 抽验；未运行任何技能、无 with/without 基线。
- CONTRIBUTING.md 为上一会话主线程亲读（7 类口径与 ≤10 词规则为一手证据）；README 的 Sponsors 表（L43-49）与 AI Design+Build 广告位（L53-82）仅核了存在性与位置，Security Notice/License/Contributing 原文未逐句过目。
- officialskills.sh 各页面内容未访问（仅核实域名为 VoltAgent 自营聚合站）；被收录的 1231 个仓库中仅 3 个抽验过 frontmatter，比例外推有限，「无捏造」结论限于 3 样本。
- 徽章 1497+ vs 实测 1231 的差异成因未定（「徽章计入合集仓库子技能数」仅为可能解释，未验证）；mblode/agent-skills 泄漏行（L1963，表格内 2 列破损行）是否算第 1232 条取决于维护者口径。
- 清点层条目数为确定性脚本计数，TestMu AI 49 条等大节未做第二次独立人工复核；热度为单日快照，目录处于活跃迭代期数据会漂移。
- 干扰说明：本轮研究因 API 限流中断过一次（上一会话 5 并行触发 429），由下一会话从 transcript 回收断点续跑完成——方法学上「断点回收」使 5 份报告的产出会话不同，但读取对象为同一本地缓存文件，内容不受影响。
