# BMad 学习笔记（learning_bmad）

> 这是一份**絮叨式学习日志**：记录学 BMad Method 的过程——看到了什么、想通了什么、还剩什么没看。
> 追加式维护：每学一块就往「学习日志」里添一条，后面的理解推翻前面的就划掉重写，不删历史。
>
> - 仓库安装版本：bmad-method **6.12.4**（2026-10-15 从 6.11.0 升级）
> - 官方文档：https://docs.bmad-method.org/
> - 相关翻译参考在 `docs/bmad/`（customize.toml 与 SKILL.md 的中文阅读版）

---

## 一、BMad 是什么（一句话版）

BMad Method 是一套**装进 Claude Code 技能目录里的软件工程方法论**：把「想法 → 需求 → 架构 → 拆故事 → 排冲刺 → 写码 → 评审 → 回顾」整条流水线拆成一格格的技能（skill），每格带自己的操作手册（SKILL.md）、参考材料、脚本和定制文件。人负责决策，AI 负责按手册推进并产出落盘的文档工件。

它不是库、不是服务，**本质是一堆 markdown + 少量 python 脚本**，靠 LLM 的指令跟随能力"运行"。

## 二、仓库里的安装形态：三块领地

| 领地 | 路径 | 谁写 | 作用 |
|------|------|------|------|
| 技能本体 | `.claude/skills/bmad-*/`（50 个目录） | 安装器 | 每个技能一个目录，SKILL.md 是入口 |
| 运行时配置 | `_bmad/` | 安装器 + 用户 | config.toml（安装器重生成，只读）、`_config/` 目录清单、`scripts/` 解析脚本、`custom/` 用户定制 |
| 产物落盘 | `_bmad-output/` | 技能运行时 | planning-artifacts / implementation-artifacts / sprint-status.yaml / epics / archive |

关键认知：**`_bmad/config.toml` 不可手改**（下次安装会被覆盖），要定制就写 `_bmad/custom/config.toml`（团队级，提交）或 `_bmad/custom/config.user.toml`（个人级，gitignore）。本仓库的核心配置：`communication_language = 中文`、输出语言中文、产物目录 `{project-root}/_bmad-output`。

## 三、技能全景：现役 vs 空壳（2026-10-19 盘点）

50 个目录里真正"活着"的**29 个**，剩下 **21 个是 deprecated 转发壳**（2026-10-20 实测修正，原记「约 26 / 19」，见文末日志）——description 一行写明 `Deprecated — forwards to bmad-xxx`，保留旧名字只为兼容旧习惯和旧文档。这是学到的第一个**模式**：**改名靠转发壳过渡，不硬删**。

现役技能按用途分组：

**主线工作流（plan → ship）**
`bmad-spec` → `bmad-prd` → `bmad-ux` → `bmad-architecture` → `bmad-create-epics-and-stories` → `bmad-sprint-planning` → `bmad-build` → `bmad-code-review` → `bmad-walkthrough` / `bmad-qa-generate-e2e-tests` → `bmad-retrospective`

**想法孵化与研究**
`bmad-brainstorming`（头脑风暴）、`bmad-product-brief`（产品简介）、`bmad-prfaq`（亚马逊逆向工作法）、`bmad-forge-idea`（多拷问压力测试想法）、`bmad-deep-recon`（调研，吞并了 market/domain/technical 三个旧研究技能）

**基础设施**
`bmad-help`（导航员）、`bmad-project-context`（维护 AGENTS.md，吞并了 document-project / generate-project-context）、`bmad-customize`（定制技能行为）、`bmad-advanced-elicitation`（深度追问）、`bmad-party-mode`（多角色圆桌）

**无人值守循环**
`bmad-build-auto`（单轮自动开发循环）

**Agent 人格（5 个）**
`bmad-agent-analyst` Mary 📊 / `bmad-agent-pm` John 📋 / `bmad-agent-architect` Winston 🏗️ / `bmad-agent-dev` Amelia 💻 / `bmad-agent-ux-designer` Sally 🎨——每个是可对话的角色，不只是流程步骤。

完整现役/deprecated 对照表见 `_bmad/bmm/module-help.csv` 与 `_bmad/_config/bmad-help.csv`。

## 四、主线工作流：阶段与闸门

从 `module-help.csv` 读出的官方路径（phases 是软建议，`required=true` 才是硬闸门）：

```
anytime（随时可用）：project-context · spec · correct-course
plan 阶段：
  brainstorming → product-brief 或 prfaq（二选一，软性）
  → PRD（★必需）→ UX（UI 重的项目强烈建议）
  → Architecture（★必需）→ Epics & Stories（★必需）→ Sprint Planning（★必需）
ship 阶段：
  Build（★必需，自带评审）→ Code Review（可选加一道）
  → Walkthrough / QA 自动化测试（可选）→ Retrospective（epic 收尾可选）
```

必经闸门只有 5 个：**PRD → Architecture → Epics&Stories → Sprint Planning → Build**。其余全是可选支线。`bmad-correct-course` 是中途变道的逃生口：冲刺中出大变更时评估影响面，可能建议回滚到任何一个前置阶段。

## 五、关键机制（学到的小机关）

1. **技能解剖**：标准结构是 `SKILL.md`（入口手册）+ `references/`（延伸阅读）+ `scripts/`（确定性脚本）+ `customize.toml`（定制覆盖）+ `assets/`（模板）。`bmad-build` 更进一步，把流程拆成 `step-01-clarify-and-route.md` … `step-05-present.md` 一步一步走，还备了 `step-oneshot.md` 快捷通道。
2. **customize.toml 生效时机**：技能**激活第 1 步**由 `resolve_customization.py` 解析，失败回退直读默认值。合并算法在 `config_utils.py` 的 `structural_merge`：带 `code`/`id` 键的表数组按身份合并（菜单项按 code 对上就改），其余数组追加、标量覆盖。
3. **配置解析链**：`config.toml → config.user.toml → custom/config.toml → custom/config.user.toml` 依次合并，后者赢。`resolve_config.py` 输出合并后的 JSON。
4. **bmad-help 怎么知道你走到哪了**：拿目录清单里的 `outputs` 模式去产物目录**找文件**。文件存在只算"开始过"，不算"完成了"——要打开看有没有 finalize 标记；判断不了就问人，不猜。这是个很克制的设计：**宁可承认不知道，不基于文件存在硬推进**。
5. **架构 spine 思想**（详见 `docs/bmad/bmad-architecture-SKILL.zh-CN.md`）：架构文档只固化**不变量**（invariants），结构性内容当**种子**冷启动；AD-n 稳定 ID 绝不重编号；memlog 追加式工作记忆；Reviewer Gate 用 lint 脚本 + 并行评审子代理把关。分 coaching（默认）与 fast 两条路径。
6. **Agent 人格即 prompt 工程**：每个 agent 的 description 写得像人物小传（"像侦探审悬案一样说话"），菜单按 code 合并、原则数组追加——人格和定制是同一套 merge 机制。

## 六、学习日志

### 2026-10-16 · customize.toml 与 SKILL.md 首次深潜
- 起因：问「customize.toml 什么时候调用？」→ 顺着翻译文件、grep 引用面、SKILL.md 激活流程、`config_utils.py` 合并算法一路挖到底。
- 产出：两份翻译（bmad-architecture / bmad-agent-architect 的 customize.zh-CN.toml）+ 一份 SKILL.md 全文翻译（`docs/bmad/bmad-architecture-SKILL.zh-CN.md`），确立三层翻译约定：功能性内容保留英文、正文中文、术语首现附英文。
- 顺带搞懂 Headless：无交互用户时整条运行改走 `references/headless.md`，跳问候跳工作模式询问，**其余闸门一个不跳**。

### 2026-10-19 · 全景盘点（本篇）
- 把 50 个技能目录的 description 全部拉出来过了一遍，分出现役 / deprecated 壳 / agent 人格三类。
- 读懂 `module-help.csv` 的列契约：module · skill · display-name · menu-code · description · action · args · phase · preceded-by · followed-by · required · output-location · outputs——后五列是 bmad-help 做进度探测的原料。
- 确认三块领地（skills / _bmad / _bmad-output）的读写权属：安装器写配置、技能写产物、人只该碰 `custom/` 和产物。
- 记下几个值得再挖的点（见下节）。

### 2026-10-19 · bmad-build 五步走深潜
- 读了 SKILL.md + workflow.md + 五个 step 文件 + oneshot + customize.toml + sync-sprint-status（共 837 行）。

**骨架**：SKILL.md（渲染启动器）→ workflow.md（模板+宪法）→ step-01 路由 → step-02 规划（CHECKPOINT 1）→ step-03 实现 → step-04 评审（4 路分流）→ step-05 收尾。旁路：oneshot 快捷道。

**认知更新**：
1. **SKILL.md 不是流程本体**——只跑 `render_skill.py` 把 `{workflow.*}` 定制占位符**预编译**进快照（落 `_bmad/render/bmad-build/`），`[[bmad-snapshot:]]` 渲染成绝对路径，失败即 HALT。修正了之前"定制在激活时运行时解析"的理解：build 这类技能的定制是**编译时**内联的。
2. **step-file 架构 = 给 LLM 戴镣铐**：绝不同时加载多个 step 文件、绝不跳步、绝不"优化"顺序、检查点必停——每条都在补上下文稀释/抄近路的弱点。状态持久化靠 spec frontmatter。
3. **裁量权集中**：评审子代理报的 severity 一律无视（"they lack the context to grade"），主会话逐条亲验 bad outcome 真会发生才裁决；每条 finding 一行 Triage Log 不许丢不许并。

**各步灵魂**：
- 01 路由：status 决定早退（draft→02 / ready→03 / in-review→04 / done→当资料）；歧义 HALT 不猜；story key 数字精确比较防 `1-1` 撞 `1-10`；epic 走缓存 `epic-<N>-context.md` + 前序 done spec 连续性。
- 02 规划：调研期禁问人；三事实（Intent gaps 人答 / Irreversibles / Footprint）；干净小改动走 oneshot；CHECKPOINT 1 三选一；批准前重读盘上 spec，外部改过认账；`<frozen-after-approval>` 批准后唯人可改。
- 03 实现：spec 是子代理唯一真源，dispatch 禁夹带；**亲验 diff 不信实现者自报**；矩阵测试存在但没跑=缺失，测试与矩阵冲突改代码不改期望。
- 04 评审：先全发射再读结果（防锚定）；分流 intent_gap（回滚回人，重走 2-4）/ bad_spec（KEEP 指令+Change Log 后重推导）/ patch（最小修，唯一活过 loopback）/ defer（进 deferred-work.md）；拿不准 patch/bad_spec 选 bad_spec；loopback 超 5 次 HALT。
- 05 收尾：done + 本地 commit 永不 push + 摘要 1-2 句禁叙事。
- oneshot 安全阀：实现中遇到不可逆/膨胀/缺口 → spec 降回 draft 升格回完整路线，单向不降级。

**模式提炼**：编译式定制（渲染内联而非运行时读）· spec 单一真源 + 冻结块宪法 · 亲验 diff 的信任边界 · 分流经济学（patch 最小化，重推导优先于补丁）· HALT 哲学贯穿（猜不如停）。

### 2026-10-19 · bmad-brainstorming 全读（追记）
- 形态与 build 是两个物种：无 step 链，靠 SKILL.md 指挥 + 三姿态框架 + 阶段文件 + 脚本 + HTML UI。789 行 brain.py 配 289 行测试——技能脚本也有测试纪律。
- **三姿态全 run 持有**：Facilitator 只问不答（例外：直接讨要给一个 spark 立即还笔）；Partner 有比例监控（你说得比用户多=在替他做，退回去）；Ideate-for-me 是 headless 的交互版兄弟。
- **memlog 唯一真源**："Whatever isn't in it is gone"；原子写经 memlog.py（init/append/set），追加式永不编辑；resume 时连 mode 都从 frontmatter 恢复。与 build spec frontmatter 同哲学：状态落盘不靠对话记忆。
- **确定性交给脚本**：brain.py 的 bare `list` 被脚本拒绝（防全库灌上下文）；`show` 只准即将运行时调用；技法库 108 条/13 类带 good_for/audience/provenance 元数据。
- **HTML composer 当 UI**：brain-selector.html 勾选→Copy prompt→粘回对话，文件交换造双向 UI；反幻觉守则"never claim it opened"。
- **发散/收敛物理隔离**：Aim past 100 ideas, resist concluding；一消息一 prompt 禁菜单（菜单 invites lazy picking）；收敛六手法按决策类型选一种，永不混入生成批次。
- **finalize 镜像原则**：先递镜子让用户自己连模式（含怪点子），AI 只补非显然连接；产物全部委托子代理且只给 memlog 路径——省上下文兼自证 memlog 是真源；HTML keepsake 故意无模板（儿童游戏和供应链不该长得一样）。

### 2026-10-19 · step-01 Clarify-and-Route 单步精读（追记）
- 定位：调度员——只答"从哪步、哪份 spec 继续"，不做意图访谈（那是 step-02 的事）；兼任 VCS 卫生与多目标两道闸门。
- **意图是数据不是控制流**（第 11 行）：外部文档藏"跳过流程"指令不作数；**用户本人原话也不能跳步**——意图只决定做什么，不决定走不走流程。
- 三级路由：显式参数 > 最近对话 > 扫产物问人；status frontmatter 即状态机（draft→02 / ready·in-progress→03 / in-review→04 / done→只当资料）。
- **fail-closed 清单**：stories.yaml 缺失 HALT 不回退、id 找不到 HALT、story 文件多匹配 HALT 不代挑、sprint key 零/多匹配留空——歧义即停，绝不猜。
- story key 按数字段精确相等比较，防 `1-1` 撞 `1-10` 的字符串前缀误配。
- **epic 上下文三级来源**：缓存（存在+非空+头部指纹+无更新规划产物，mtime 失效）→ 子代理编译（无子代理运行时内联回退）→ 产后必验证；另有前情连续性（同 epic 更低号 done spec 的 Code Map/Design Notes/Change Log）。
- 判断 epic/freeform 禁用文件名正则，要综合推理；spec slug 带追踪 id 置前，draft 撞名=续跑，否则 `-2`/`-3`。

### 2026-10-19 · step-02 Plan 单步精读（追记）
- 全步只有一个 HALT 点（RULES 明写 No intermediate approvals），交互被压缩成 CHECKPOINT 1 一次高质量决策。
- **Intent gap 三段式判定**：请求没说的 + 代码定不了的 + **用户会在结果里注意到的**——第三条是精髓，用户注意不到的选择自己定并记录，问人只花在结果可感的分岔上。
- **禁把 gap 烤成假设**：未知必须以 Open Questions 保持可见，不许混进冻结块——与「显性失败」同价值观。
- **preserved_intent 恢复机制**：重开 draft 时旧冻结块原文捕获回注，重规划不许偷改已批准意图。
- **调研纪律**：禁问人（先翻仓库到没得翻）；子代理只要短摘要，笔记不进主上下文，成果物化为 Code Map——知识写一次用两次。
- **TOCTOU 意识**：批准后从磁盘重读 spec，外部改动认账继续，文件丢失 HALT 且不许擅自重建。
- **问答循环可级联**：答案写进冻结块成决策，但可能暴露新 gap → 追加再问，清空才准到 CHECKPOINT。冻结块是逐题累积的用户决策记录。

### 2026-10-19 · 「转发壳」拆开看了（追记）
- 问题：deprecated 壳到底是什么？拆了 `bmad-quick-dev` 和 `bmad-create-prd` 两个真文件。
- 答案：壳里没有真逻辑，只有三步——报弃用通知、原样转发用户输入到新技能、立即停手（"execute no further steps in this shim"）。
- 最讲究处：壳连 `_bmad/custom/` 的旧名定制文件都管迁移——经明确同意才改名、新文件已存在不覆盖、失败即 HALT，绝不带旧定制静默跑。改名从硬切换变成每次调用推送一次的渐进迁移。
- 考究变体：`bmad-create-prd → bmad-prd` 转发时显式带 `Intent: create` 让新技能跳过意图识别，且预解析 4 个遗留定制字段传入——旧行为精保证，不靠新技能猜。
- 本质：API 弃用纪律的 prompt 版。对照自家 `/goal → /work` 改名留旧名，同一思路。
- 词源补记：**shim = 垫片**（机械里填平两块零件间隙的薄片）。软件引申为插在调用方与真实现之间的薄转发层——薄、透明、过渡性。同族：JS polyfill、Wine 的 Win32 API 垫层。`lifecycle: shim` 即声明"此目录是垫片不是真功能，未来拆"。

### 2026-10-19 · bmad-agent-architect 精读：agent 型人格技能样本（追记）
- 形态是第三个物种：build 是「渲染启动器 + step 链」，brainstorming 是「SKILL.md 指挥 + 脚本 + HTML UI」，architect 这种 agent 型**没有自己的流程**——全部内容就是一份 8 步激活协议 + 一张两行菜单。它不干活，职责是「成为 Winston，并把活派出去」。
- 8 步激活链：resolve_customization.py **运行时**三层合并（缺文件跳过 = **fail-soft**，与工作流技能歧义 HALT 的 fail-closed 相反——定制丢了只是少点风味，流程走错是真损失）→ prepend 步骤 → 人格叠加 → persistent_facts → resolve_config.py 拿名字/语言/产物目录 → icon 问候 → append 步骤 → 菜单派发。
- 合并契约写在 SKILL.md 里做手动兜底：脚本只是优化，prose 才是规格——脚本挂了 LLM 按同一规则手工合并继续走，不 HALT。
- **身份与行为分离**：customize.toml 里 name/title 标注 non-configurable（"要新名字就另造一个 agent"），可定制的只有 icon / 前后步骤 / 持久事实 / 风格 / 原则 / 菜单——「他是谁」锁死，「他怎么做事」随便改。
- persistent_facts：字面句或 `file:` 前缀路径/glob（org 规则、领域常量、用户偏好），激活时装载全程携带；注释明说它与 runtime memory sidecar 是两回事——静态声明式上下文 vs 运行时记忆。
- 菜单交互经济学：意图清晰直派跳菜单；含糊才**一句**澄清（"one short question, not a confirmation ritual"）；全不合则继续聊天——菜单是加速器不是笼子。CA→bmad-architecture、IR→bmad-sprint-planning，正好对应 plan 阶段两道★必需闸门：**Winston 是他地盘上硬闸门的人形接口**。
- **人格贯穿**：菜单派发调子技能时 persona 不脱（"this persona carries through"）——工作流技能无状态当工人，agent 技能有记忆当脸面。icon 前缀全程保留，多 agent 同场（party-mode）时靠它认人。
- 时序对照：build 定制**编译时**内联（render_skill.py），agent 定制**激活时**运行时解析（resolve_customization.py）——同名 merge 机制两套时序，是否同根待查 render_skill.py。

### 2026-10-19 · bmad-agent-dev 精读 + 五 agent 同构验证（追记）
- diff 实证：五个 agent 的 SKILL.md 是**同一个 76 行模板**，差异仅换名——frontmatter、Overview 人设段、step-8 例句（"hey Amelia, let's implement the next story"）、结尾代词 him/her。人格是数据不是代码，连激活协议都五个共享。
- customize.toml 同骨架不同载荷，**菜单规模 = 地盘大小**：Sally 1 项（CU→bmad-ux）/ Winston 2（CA/IR）/ John 4（PRD/CE/IR/CC）/ Amelia 5（BD/QA/CR/SP/ER）/ Mary 9。**bmad-sprint-planning 三家共用**（Winston IR / John IR / Amelia SP）——实现就绪是跨角色共同闸门，不是一个 agent 的私产。
- **Amelia 的人格里塞的是政策不是价值观**：6 条 principles 一半是硬禁令——禁 epic/story 引用进代码注释（`# Story: PROJ-42` 这类）、注释只说 why 不说 what、生成码必须 production-ready 无 AI 噪音。人格贯穿机制让这些规则跟着她进 bmad-build 等一切被派发的技能——**persona 即横切策略层（AOP 的 prompt 版）**。对照 Winston 的原则是抽象价值观（Rule of Three / boring tech）。
- 沟通风格与职能互为镜像：Amelia "Ultra-succinct. Speaks in file paths and AC IDs — every statement citable"（可引用、零废话）；Winston "trade-offs, not verdicts"。人格工程师先想清楚这个角色产出什么，再让说话方式长成产出的形状。
- **Mary 的菜单藏着 shim 思想的复用**：9 项里 6 项是无 `skill` 的 prompt 型，prompt 文本清一色 "Invoke `bmad-deep-recon` with X type pre-selected (forwarded activation: skip type inference)"——与转发壳显式带 `Intent: create` 跳意图识别同一招。**菜单项 = 微型垫片**：一个技能的 N 种入口姿态摊成 N 个菜单项，每个预先钉死一个自由度。

### 2026-10-19 · bmad-sprint-planning 精读：脚本承担确定性的重度样本（追记）
- 三 agent 菜单共用的 IR/SP 就是它，★必需闸门。形态分层最全：SKILL.md（63 行纯调度）→ 5 个 reference（每意图一册共 99 行）→ sprint_plan.py（701 行三子命令）→ template（格式契约）→ 524 行测试。customize.toml 换 [workflow] 命名空间：无 icon/人格/菜单，多一个 on_complete 完成钩子（标量=单指令/数组=序列）。
- **五意图路由**：readiness（只查闸门即停）/ sprint-planning（全流程兼刷新）/ status（跳闸门看进度）/ validate（查格式零写入）/ fix（重建坏文件）。激活按意图懒加载 reference——build step-01 同思想。
- **分工口号**："Discovery is your call; everything after it is the script's." 开场人设 "You are a senior developer about to commit to this plan"——先怀疑式读计划（缺口现在发现便宜、构建中发现贵）。与「确定性逻辑交给代码」同义但更精确：**判断力放门口（闸门）→ 机械活全交脚本 → 判断力只在 JSON report 的异常处（warnings/orphans/illegal）重新入场**。
- readiness gate 全部检查收敛为一句话："could a developer implement these epics without inventing decisions nothing records?"——双向追溯/独立可完成/决策有记录/冲突显性化；缺文档类型≠finding（无 UX 产物且无 UI story 没问题）。FAIL 时逐条点名修复技能，跨 cutting 的指给 bmad-correct-course。
- 脚本契约要点（源码实证）：merge 永不降级（`_merge_status` 返回 rank 高者）；legacy v6 值透明映射并上报（drafted→ready-for-dev / contexted→in-progress）；story 文件落盘即 floor 到 ready-for-dev；action_items/自定义键/用户注释全透传；原子写+产后自校验；**argparse 错误也输出 JSON**（JsonArgumentParser）——脚本输出即 LLM 读取的契约，连报错都结构化。
- **失败路径是全局规则**："If the Script Fails"——不停在错误上、不静默猜：人肉读文件给同样结果 + 声明确定性路径为何失败 + 引导 fix 流程恢复脚本可用状态。SKILL.md 与多个 reference 重复强调。比「显性失败」多一步：降级到人肉后承诺修复确定性路径，让人肉成为一次性而非常态。
- fix 流程：四路并行取证子代理（epics 权威 / story 文件 / git 代码证据 / 旧文件抢救 action_items）→ 合并提议表，冲突取低值（"a false done costs more than a false in-progress"——降级误报代价小）→ 用户逐条确认才写（headless 则 blocked）→ `--fresh --set` 干净重建，**--set 是全技能唯一允许降级的路径**。
- **模板双副本测试钉死**：sprint-status-template.yaml 的 STATUS DEFINITIONS 与脚本内嵌 HEADER_COMMENT 是两份拷贝，`test_header_comment_matches_template` 逐行比对防漂移——与自家 test_architecture_contracts.py 同思路：文档性内容用测试当围栏。
- headless JSON 契约（status/gate/findings/warnings/status_file，歧义→blocked 不猜）就是无人值守循环的接口；status 子命令的 **`recommendation`**（~~`next_recommended_action`~~，6.12.4 实测字段名，见文末日志）直接给 `{skill: bmad-build, story_key}`，固定优先级 in-progress(resume)→review→ready-for-dev→backlog→optional-retro→all_done。**sprint-planning 是状态文件的生产者/修复者，build 是消费者，推荐字段是联动接口**。

## 七、下一步待学

- [x] `bmad-build` 的五步文件逐个读——已深潜（见 2026-10-19 日志），最大发现：SKILL.md 是渲染启动器，定制走编译时内联
- [ ] `bmad-spec` 的 SPEC.md 模板与 `bmad-prd` 的 HTML 检查报告产出方式
- [ ] `_bmad/scripts/render_skill.py` 细读——已确认部署范围：`_bmad/render/` 只渲染了 bmad-build 与 bmad-build-auto 两族（编译时内联只服务无人值守族？待验证动机），其余技能走激活时运行时解析
- [x] `bmad-build-auto` 与 `bmad-sprint-planning` 的 sprint-status.yaml 联动——sprint-planning 侧已明（见 2026-10-19 追记：它是生产者/修复者，`recommendation` 是给编排层的接口）；build-auto 侧已补（见 2026-10-20 日志：它不读 sprint-status，靠调用方 folder+id 派发）
- [x] `bmad-build-auto` 消费侧：**不读** sprint-status.yaml——step-01 按调用方给的 `spec_folder` + `story_id` 做 folder+id 派发（2026-10-20 实测，见文末日志）
- [ ] 现有产物考古：`_bmad-output/` 里 epic 1-50 与 S1-S4 主题是怎么被这套流水线生产出来的（对照 `_bmad-output/consolidated-overview.md`）

## 八、整体架构与设计理念（2026-10-19 学习周期收束）

### 本质一句话

**方法论即代码**：BMad 把软件工程自身的工程纪律（配置分层、API 弃用、测试围栏、原子写、单一真源、CI 闸门、AOP）用来包裹 LLM 的概率性。隐喻：**LLM 是 CPU，markdown 是指令集，5 个共享脚本是内核，`_bmad-output/` 是内存，闸门是断言，人是唯一有权限改冻结块的特权指令。**

### 四层领土与读写权属

| 层 | 路径 | 写者 | 角色 |
|----|------|------|------|
| 指令集 | `.claude/skills/bmad-*`（50 目录） | 安装器 | 四种形态的技能 |
| 内核+配置 | `_bmad/`（5 脚本 + 4 清单 + custom/） | 安装器 + 人（仅 custom/） | 合并算法/渲染/配置链/记忆库 |
| 内存 | `_bmad-output/` | 技能运行时 | spec/sprint-status/epics/台账 |
| 特权层 | 人 | — | 只在确认点/冻结块/闸门出现 |

### 四种技能形态 + 统一激活骨架

工作流（step 链/意图路由）· 交互（姿态框架+UI）· agent 人格（纯激活协议+菜单）· shim（转发垫片）。骨架统一：解析定制 → prepend → 人格/事实 → config → 问候 → append → 路由派发，差异只在路由后的载荷。

### 双层解耦（正交设计）

agent（角色视角、人格、横切策略载体）⊥ skill（无状态工作单元）。菜单按角色视角切同一批技能而非技能归属角色——sprint-planning 三家共用是实证。人格贯穿机制让 agent 成为横切策略层（Amelia 的反 AI 噪音规则跟着她进一切被派发技能）。

### 统一内核：一套合并算法，两种时序

structural_merge（标量覆盖/数组追加/code·id 身份合并）统一 agent 与 workflow 定制面；时序二分：**build 族编译时内联**（render/ 只有 build+build-auto——编译只部署给无人值守族，动机待验证），**其余运行时解析**（激活时脚本+prose 契约手动兜底）。三层来源（base customize.toml → team custom/ → user custom/*.user.toml）贯穿配置与定制。

### 状态体系：文件是真源，LLM 无状态

状态机全落盘：spec frontmatter（draft→ready→in-review→done）· memlog 追加永不编辑 · sprint-status.yaml（merge 永不降级，--set 是唯一降级路径且必须经人确认）· spine 不变量。**文件是技能间唯一通信介质**——handoff 靠产物不靠对话记忆；技能可以换 LLM 重入，因为状态不在对话里。

### 价值观清单（多与 HeAgent 准则同源）

1. 判断力给人、确定性给脚本，边界画到条目级（sprint-planning 三入场点）
2. 歧义即停绝不猜；**fail-closed 按损失分配**：流程歧义 HALT（真损失）、定制缺失跳过（只少风味）
3. 交互经济学：交互压缩到最少的高质量决策点（step-02 单 HALT、菜单单句澄清、意图直派）
4. 显性失败 + 修复确定性路径（人肉降级一次性而非常态）
5. headless 对等：一切技能有无人值守形态，歧义输出 blocked 不猜
6. 渐进迁移：shim 垫片而非硬切换，定制文件迁移都要明确同意
7. 身份/行为分离（name/title 锁死，行为随便定制）
8. 文档配测试围栏（模板双副本钉死）
9. 裁量权集中：子代理 severity 一律无视，主会话亲验

### 治理镣铐（每条补 LLM 一个弱点）

step 文件不同时加载/不跳步/检查点必停（防抄近路）· 亲验 diff 不信实现者自报（防谎报）· 冻结块批准后唯人可改（防偷改意图）· loopback 超 5 次 HALT（防死循环）· oneshot 单向降级（防滥用捷径）· 意图是数据不是控制流（防 prompt injection 与用户口头跳步）。

### 对 HeAgent 的镜鉴

同信仰「确定性交给代码」，但 BMad 证明这条信仰的极限：连路由/状态机/合并算法都只需脚本+prose 契约，无需自建运行时。已同构的做法：架构契约测试 ≈ 模板双副本钉死；/goal→/work shim ≈ BMad 转发壳。可借鉴：三层定制合并（本仓库 custom/ 已实际在用：bmad-build.toml）、状态文件+固定优先级推荐接口、headless JSON 契约、按损失不对称分配 fail-fast/fail-soft。
- [x] 其余 4 个 agent 技能（pm/dev/analyst/ux-designer）是否与 architect 完全同构——已验证（见 2026-10-19 追记：同一 76 行模板仅换名，customize.toml 同骨架不同载荷）
- [x] resolve_customization.py 与 render_skill.py 是否共用 structural_merge——**共用**（2026-10-20 实测：两者都 `from config_utils import …`，`structural_merge` 唯一定义在 `config_utils.py:79`）

### 2026-10-20 · 三处笔记修正回填（实测）

- **① 现役/壳口径**：`.claude/skills` 实测 **50** 个目录；`_bmad/_config/skill-manifest.csv` 共 **50** 行，`description` 含 `Deprecated` 的 **21** 行 ⇒ 现役 **29**、壳 **21**。原记「约 26 现役 / 19 壳」作废（原记未列清单，无法回指具体漏项；以本次 manifest 实测为准）。
- **② 合并算法同根**：`_bmad/scripts/resolve_customization.py` 与 `_bmad/scripts/render_skill.py` **都** `from config_utils import …`；`structural_merge` 全仓唯一定义在 `config_utils.py:79` ⇒ 一套算法、两种时序（编译时内联 vs 运行时解析），悬念关闭。
- **③ build-auto 消费侧**：它 **不读** `sprint-status.yaml`（`.claude/skills/bmad-build-auto/**` 全文检索 `sprint-status|next_recommended_action` = **0 命中**）。入口是 step-01 的 **folder+id 派发**：调用方给 `spec_folder` + `story_id` → 读 `{spec_folder}/stories.yaml` 取该 id 的 `title`/`description`（多个文件匹配 `stories/{id}-*.md` → HALT `ambiguous story file match`；id 查不到 → HALT `story id not found in stories.yaml`；缺 `SPEC.md` → HALT `no epic spec found`）→ 再读 story 文件与 `SPEC.md` 的 `companions:`。
- **④ 字段名修正**：sprint-planning `status` 输出里的推荐字段是 **`recommendation`**（`sprint_plan.py:564-592`，形如 `{skill, story_key, reason}`），**不是** `next_recommended_action`；优先级实测 in-progress(resume) → review(`bmad-code-review`) → ready-for-dev → backlog → optional-retro → `null` + `all_done: true`。
- **联动口径修正**：两技能之间**没有直接耦合**——`recommendation.story_key` 服务的是**调用方/编排层**，由它按 folder+id 把 spec 喂给 build-auto。「build 直接消费 sprint-status」的说法不成立。
