---
name: ecc
source: https://github.com/affaan-m/ECC（plugin.json repository 字段；研究对象为本地目录副本 E:/AI/ecc-trimmed，post-2.2.3 main 快照 ef648e01）
accessed: 2026-10-26 / 2026-10-30
heat: GitHub API 2026-10-30 快照 292,862 stars / 43,341 forks / 最近 push 2026-10-30（上游 main 已超前本地副本）；README 自述 trending 徽章、官网 ecc.tools、npm 包 ecc-universal——热度仅用于筛选，不证明质量
first_study: 2026-10-26
last_review: 2026-10-30
---

# ECC（旧名 "Everything Claude Code" 已退役，commit c05b2d66 仅保留 ECC）

## 核心观点与价值

本卡最重要的一节，综合报告主要从这里引用：

1. **skill 体系的治理闭环有四环**：新建前查重（skill-scout）→ 选装（agent-sort）→ 盘点（skill-stocktake）→ 遵从测量（skill-comply，低于阈值升级 hook）。skill 不只被写出来，还被持续治理；对维护数百件规模的 skill 库是必要设施。
2. **「精选 + 按需安装」是裁剪机制集，不是默认保证**。同一仓库有两种包装形态：插件 cache 档（v2.2.1）`skills/` 仅 7 件，目录 marketplace 档（v2.2.3）`skills/` 全量 293 件，两者 plugin.json 都只注册 `./skills/`（实测 + 本会话可见数百个 ecc: skill 印证）。真正的裁剪机制是三层可选项：安装 profile（minimal/core/full + `--skills` 按需 + hook runtime 须显式决定，README.md:445-465）、pi/core 精选档（白名单确定性生成，见第 3 条）、agent-sort（项目证据驱动的 DAILY/LIBRARY 分档）。**不选裁剪档就全量进上下文**——「避免全量」依赖用户选择，机制不强制（推论）。
3. **构建期安全闸：skill 内容安全从审稿人责任变成构建器责任**。pi/core 精选档（123/293 skills + 24/94 commands）由 `manifests/pi-core.json` 显式白名单经 `scripts/build-pi-core.js` 确定性生成，构建在内容安全违规时硬失败：非白名单 URL host、pipe-to-shell（`curl|sh`）、密钥/token 正则（Slack token 等）、绝对家目录路径（`/Users`、`/home`、`C:\Users` 三 OS）、symlink、frontmatter 缺失或 name≠目录名、重名 skill（脚本 L87,132-137,293-332，主 agent 已核对实现；清单口径见 CHANGELOG 2.2.2）；每个排除对象记入 CURATION.md 台账（"Everything excluded is listed here with its reason"，CURATION.md:4），CI 另做离线加载冒烟（CHANGELOG 2.2.2，未独立复跑）。前提：适用于「从主库派生发布档」的库型生态。
4. **官方写作指南把写法落成硬指标**（docs/SKILL-DEVELOPMENT-GUIDE.md，920 行）：长度 "200-500 lines typical, 800 lines maximum"（L439）；骨架必备 When to Activate（"**critical** for auto-activation. Be specific"，L307-309）与 Anti-Patterns 节；示例统一 PASS/FAIL 命名；**示例代码按可编译资产验收**（`npx tsc --noEmit` / `python -m py_compile` / `go build`，L608-626）——示例不是插画，是测试资产。前提：代码类 skill，且 CI 有对应工具链。同指南对「何时该写 skill」给 PASS/FAIL 对照表（粒度如 `pytest-fixtures` 而非 `python-testing`，L123-130）。
5. **能力面五问序：写之前先路由载体**（docs/capability-surface-selection.md:17-28，固定顺序）：①确定性必触发→rule；②按需 playbook→skill；③多客户端结构化交互→MCP；④一次性本地动作→本地脚本（需要时再包 skill）；⑤窄远程调用→直连 API；拿不准"从小面起步"（L135-140）。配套落位政策按「来源×是否发布」定层：Curated→repo 随发布；Learned/Imported/Evolved→用户目录不入库、须 `.provenance.json`（docs/SKILL-PLACEMENT-POLICY.md L7-12,31,41）。这是任一 skill 作者可直接套用的载体决策表（推论：其价值在「问的顺序」——先排除 rule/MCP，把 skill 留给真正按需的知识层）。
6. **指令工业化与代码工业化的分界在同一仓库内清晰可见**。skill-create 生成器（command）把写盘安全（临时兄弟文件验证+原子替换）、命名归一、description 校验全部写成 prompt 措辞由 LLM 自觉执行，确定性 JS 只管终端渲染（scripts/skill-create-output.js 全文核实，245 行零文件操作）；对比 pi/core 把同一类校验下沉为构建失败条件。教训：**能进构建管线的规则别留在 prompt 里**——prompt 约束只对当次会话的 LLM 生效，构建闸对每次发布生效（推论）。
7. **库内质量不均的实证：行数 gate 拦不住结构性问题**。python-patterns（751 行，原生 7 件中最大）零上下文经济性设计：无外置、无分层、无按需加载，Good/Bad 双份代码，内容重复（bare except 两处 L155-162≈L738-749；生成器读文件近重复；新旧类型注解近乎复制——主 agent 已核对重复属实），速查表后置（L686-699）不起导航作用。与官方指南自己的 800 行上限擦线、与 README 口号 "Optimize the context window. Persist everything else."（README.md:138）相悖。教训：大规模库的机械 gate（行数）通过≠质量；知识型 skill 同样需要披露设计。
8. **判定诚实声明**：skill-stocktake 的健康判定显式写明 "Evaluation is **holistic AI judgment** — not a numeric rubric"（SKILL.md:126），并列四维引导（Actionability/Scope fit/Uniqueness/Currency，L127-130）。伪精确量表不如诚实的整体判断+证据义务（reason 必须自包含、附好坏对照例 L132-145）。
9. **一源多端做 harness 化重组**：.codex/ 等目录是带 config 的重组而非裸复制；docs/ 下 6 语种镜像含 518 个 SKILL.md（实测计数）。
10. **规则→hook 升级通道**：反复不被遵守的文档规则升级为机器强制，阈值可数（skill-comply 合规率 <0.6）。

## 整体定位

自称 "the agent harness operating system"（README.md:2）：面向工程团队的 Claude Code 插件生态与跨 harness 适配层，v2.2.3 marketplace 自述含 293 skills、68 agents、94 command shims，另有 rules/hooks/MCP 约定/运维工作流（marketplace.json:16-17）。作者 Affaan Mustafa，MIT；Claude Code 最佳、Codex 原生同步路径、其余 harness（Cursor/Zed/Gemini/OpenCode/Qwen 等 10+）为能力受限 adapter（README.md:140）。口号 "Optimize the context window. Persist everything else."（README.md:138）。

## 体系结构与组织机制

- **五层分工**（实测，E:/AI/ecc-trimmed）：`skills/` 293 件 how-to 知识（canonical workflow surface，"New workflow development should land in `skills/` first"，README.md:1098）；`agents/` 68 个委派专家；`commands/` 94 个 slash 入口（迁移期 shim，退役名入 `legacy-command-shims/` opt-in，README.md:1096-1100,511）；`rules/` 122 个常驻规则（"Always loaded, so install them selectively"，README.md:1217）；`hooks/` 6 文件（事件触发脚本，"Run outside the model context"，README.md:1218）。README 自身计数不自洽（851 行写 67 agents、1699 行写 281 skills——旧版数字未同步）。
- **两种包装形态**（实测）：插件 cache 档 v2.2.1 `skills/` 仅 7 件精选；目录 marketplace 档 post-2.2.3 全量 293 件；两者 plugin.json 均注册 `./skills/` + `./commands/`。安装方式多路（`npx ecc-universal` / 插件 marketplace / 手动拷贝须为 `~/.claude/skills/` 直接子目录，README.md:500-501），"Do not stack install methods"（README.md:277）。
- **裁剪机制三层**：①安装 profile——minimal/core/full，凡物化 hook runtime 必须显式决定否则安装器停止写入（README.md:445-465）；②pi/core 精选档——123/293 skills + 24/94 commands，include 九类/exclude 六类硬规则（CURATION.md:8-16），白名单确定性构建（核心观点第 3 条），council 改名 ecc-council 避目录冲突（CURATION.md:270）；③agent-sort——DAILY/LIBRARY 证据分档（解剖样本节）。
- **质控文档四件套**（docs/，全读）：SKILL-DEVELOPMENT-GUIDE.md（920 行写作指南）、SKILL-PLACEMENT-POLICY.md（104 行落位）、skill-adaptation-policy.md（73 行改编规则：fork 只保留想法与工作流语义，实质扩缩须改名，四条件全真才留原名）、capability-surface-selection.md（140 行五问序）。CONTRIBUTING.md（541 行）贡献门槛：name 必须匹配目录名、description 单行/折叠标量（禁 `|` 字面块——"breaks flat-table renderers"，L172）、必备骨架六节、<500 行（800 max）、负向清单（"do not ship a skill whose main value is telling users to install an unvetted package"，L158）+ 新 skill 接线清单（catalog/manifests/registry/docs 表多处同步）。
- **一源多端**：docs/ 下 es/ja-JP/ko-KR/tr/zh-CN/zh-TW 六语种镜像含 518 个 SKILL.md；.agents/.kiro/.cursor 为 harness 镜像（实测 39/43/11 件）。全库 SKILL.md 618 个（排除 node_modules 实测），marketplace 自述 293 为去重口径。
- **方法论指南两件**（仓库根）：the-shortform-guide.md（431 行，设置/基础设施层，自述 10 个月日用量经验）与 the-longform-guide.md（354 行，进阶方法论：token 经济、记忆持久化、pass@k vs pass^k、并行化纪律），显式互引定序（longform:7 "Read that first"；shortform:427 反向指回）。

## 解剖样本

### skill-scout（skills/skill-scout/SKILL.md，141 行）

定位：新建 skill 前的查重守门员——先搜本地/marketplace/GitHub/web，防重复造轮子。frontmatter description（逐字）："Search existing local, marketplace, GitHub, and web skill sources before creating a new skill. Use when the user wants to create, build, fork, or find a skill for a workflow."

- **任务契约**：六步（L28-106）：①捕获意图（任务/触发/领域/3-5 关键词）→②搜本地（find+grep 文件名与 frontmatter）→③搜远程（gh search + web 查询≤3）→④审查外部匹配（读 frontmatter、查可疑 shell/网络/凭证操作、维护状态、fork 后 diff）→⑤五级排序（结果上限 10，L93）→⑥三选项决策表（用现有/fork/新建）。触发词清单 L18-23；用户明示跳过则直接创建（L25-26）。
- **机制拆解**：停止条件明文（L105-106）："Only create a new skill after the user chooses that path or after the search finds no close match."——创建决定权留给用户，skill 只能建议；可数硬约束（结果≤10、web 查询≤3）；反模式五条（L131-135：禁跳过搜索、禁未读即装、禁未排序弱匹配长列表、禁轻信 web-only、禁原地改 marketplace 原件）。正文标注来源为社区 PR 抢救（L8-14，salvaged from stale community PR #1232）。
- **设计本质**（推论）：把「不要重复造轮子」从美德口号变成带可数停止条件的流程；与 skill-adaptation-policy（fork 规则）、SKILL-PLACEMENT-POLICY（落位）构成新建链路的完整守门序列。盲点：`gh` CLI 缺失无降级路径（文件未写）。

### agent-sort（skills/agent-sort/SKILL.md，216 行）

定位：按仓库证据把 ECC 能力装配裁到 DAILY/LIBRARY 两档的选装元技能。description（逐字）："Build an evidence-backed ECC install plan for a specific repo by sorting skills, commands, rules, hooks, and extras into DAILY vs LIBRARY buckets using parallel repo-aware review passes. Use when ECC should be trimmed to what a project actually needs instead of loading the full bundle."

- **任务契约**：输出五件（L30-38）：DAILY 清单/LIBRARY 清单/install plan/verification report/可选 skill-library router。六步（L94-181）：读仓库定栈→建证据表（每组件记路径/类型/拟归档/证据/理由，样例格式 L121-124）→分档→生成安装计划→可选建 router→验证简报。可选并行阶段：按六个 pass 分给子代理（L75-92），无子代理则顺序执行。
- **机制拆解**：升 DAILY 三条件/降 LIBRARY 三条件（L127-139，逐字核实："the repo clearly uses the matching stack" 等）；**LIBRARY ≠ 删除**："keep accessible without loading by default"（L26）——裁剪的是加载不是存在；证据源七类（扩展名/lockfile/框架配置/CI/build 脚本/imports/仓库文档，L53-61）；报告五段固定格式（L199-216）。安装动作本身不执行（移交 configure-ecc，L185-195）。
- **设计本质**（推论）：装配裁剪=上下文预算分配决策；判定规则可数、证据强制入表使结论可审计。盲点：DAILY 无数量上限（装 80 件也照准）；"ECC 安装根"路径未写明。

### skill-stocktake（skills/skill-stocktake/SKILL.md，195 行 + scripts/ 3 件）

定位：skill 生命周期盘点——审计全部已装 skill 的质量并给出处置建议。description（逐字）："Use when auditing Claude skills and commands for quality. Supports Quick Scan (changed skills only) and Full Stocktake modes with sequential subagent batch evaluation."

- **任务契约**：审计 `~/.claude/skills` 与 `{cwd}/.claude/skills` 全部 SKILL.md，产物=汇总表+results.json 缓存。两模式：Quick Scan（缓存存在时仅重评 mtime 变更者，L43-57）；Full 四阶段（L58-162）：P1 盘点跑 scan.sh→P2 派子代理按 checklist 评每 skill 出 verdict JSON（每批约 20 个、逐批落盘、支持断点续评）→P3 汇总表→P4 整合：Retire/Merge/Improve/Update 逐项呈报证据、**用户确认后才动文件**（L152-162）。
- **机制拆解**：健康判定显式声明整体 AI 判断（L126，逐字核实）+四维引导+checklist 四项（重叠/与 MEMORY-CLAUDE.md 重叠/WebSearch 核验新鲜度/使用频次——频次取自 observations.jsonl 的 Read 记录）；verdict 五档（Keep/Improve/Update/Retire/Merge into [X]，L118-124）；reason 必须自包含含证据、附好坏对照例（L132-145）；results.json schema 规定 evaluated_at 须真实 UTC（禁日期近似，L164-189）。确定性全部下沉 3 个 bash 脚本：scan.sh（211 行，NUL 分隔枚举防空格路径、路径防御校验）、quick-diff.sh（时间戳非法 fail-fast）、save-results.sh（stdin 验 JSON+mktemp 原子替换）。
- **设计本质**（推论）：主客观分工——判定交子代理（带证据义务），确定性交脚本（防静默失败）；「每批落盘」使长盘点可中断恢复；处置动作必须过用户确认，skill 不自行删改。盲点：依赖 jq/node/date、observations.jsonl 的产生机制未说明。

### python-patterns（skills/python-patterns/SKILL.md，751 行，反样本）

定位：Python 惯用法知识库——原生 7 件精选中最大，纯知识型 skill 的形态极限。description（逐字）："Pythonic idioms, PEP 8 standards, type hints, and best practices for building robust, efficient, and maintainable Python applications. Use when writing or reviewing Python code and idiomatic structure, typing, or PEP 8 is in question."

- **任务契约**：无流程——14 章 33 个 `###` 模式小节，每节=模式名+0-1 句散文+Good/Bad 成对代码块（样例 L286-294，逐字核实）。无目录、无跳读指令、无分层设计——期望全文常驻。
- **机制拆解**（上下文经济性审查）：省 token 设计近乎为零——无 references/ 外置、无按需加载；唯一压缩物是结尾速查表（L686-699，**后置不起导航作用**）。烧 token 设计：Good/Bad 双份代码；内容重复（bare except L155-162≈L738-749、生成器读文件近重复 L299-308≈L588-597、新旧类型注解近乎复制 L79-91≈L97-105——主 agent 逐处核对属实）；Anti-Patterns 章与正文 Good/Bad 大面积重叠。751 行擦线过自家 800 上限。
- **设计本质**（推论，作为反样本的价值）：「全文常驻」假设下的知识平铺堆。它证明：机械 gate（行数上限）拦不住结构性问题（重复、无导航、双份代码）；同一仓库内官方指南的硬指标与实际库存存在执行落差。对知识型 skill 作者的对照教训：先分频次（常驻主干 vs 按需细节）、速查表前置做导航、同主题只留一处权威条目。**注意**：本节判定为「形态极限的反面教材」是研究者评价；该 skill 触发面清晰、Good/Bad 形式与官方指南骨架一致，作为「查某个具体惯用法」的参考仍可用——缺陷在组织不在内容。

### skill-create（commands/skill-create.md + scripts/skill-create-output.js，command 形态）

定位：从 git 历史提炼仓库约定自动生成 SKILL.md 的工业化生产入口（command 非 skill；正文自带先用 skill-scout 查重的前置，L1-5）。

- **任务契约**：参数 `--commits`（默认 200）/`--output`/`--instincts`；四步（L29-160）：采 git 数据→侦测 5 类模式→按内联模板生成 SKILL.md（L95-118）→可选 instincts。落位 `<output-dir>/<skill-name>/SKILL.md`，默认 `.claude/skills/`。
- **机制拆解**：生成模板强制 description "Use when" 开头（L120-129）；替换目标前有验证链——写唯一命名临时兄弟文件→frontmatter 须可解析 YAML→name 须匹配目标目录→description 须 "Use when" 开头（L124-137 附近，逐字核实）→才可替换。**但整条验证链是 prompt 措辞，靠 LLM 自觉执行**；确定性 JS（245 行）只管终端渲染（ANSI/框线/demo 假数据），零文件操作、零校验（全文核实）。
- **设计本质**（推论）：「指令工业化」样本——把生成规范（骨架、frontmatter 形状、触发措辞）固化进模板，但不保证执行；与 pi/core 构建闸（同仓库）对照出分界：进得了构建管线的校验才是机器保证，进不了的只是措辞。价值：description trigger-first 被做成生成时的强制段，等于把「描述只管触发」的结论制度化为出厂默认。

## 未读与局限

- 上游 main 在本地快照 ef648e01 之后仍有 push（API pushed_at 2026-10-30），本地副本非上游最新；cache 2.2.1 与目录档 post-2.2.3 的版本差使个别计数按副本分记。
- rules/ 122 件、agents/ 68 件、全量库其余 ~286 件 skill、docs/ 六语种镜像正文、hooks 6 文件实现、contexts/workflows/scaffolds/manifests 其余文件、ecc2/、integrations/、13 harness 目录内容均未读。
- build-pi-core.js 已抽查安全闸实现（L80-344 关键行），未运行；CI 离线冒烟（CHANGELOG 2.2.2 自述）未独立复跑。
- 按研究规范未实际安装/运行任何 ECC 组件；全部机制结论基于文本证据，非实测。
- longform/shortform 指南的 mgrep ~50% 省 token、"25k stars" 等作者自述数字未核实；两文配图未读。
- README 内部计数不自洽（67/68 agents、281/293 skills），宣传口径与实测计数并存，引用时以实测为准。
- skill-comply 样本（首轮解剖）已按用户指令移出本卡，其机制要点与证据保留在综合报告第一部分第 9 条。
