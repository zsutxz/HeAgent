# DeepSeek Harness (dsh) vs HeAgent 架构对标研究

- 日期：2026-11-03（本日会话内完成）
- 对象：github.com/deepseek-ai/deepseek-harness（dsh），269k star，MIT，「Everything is a Plugin」，TypeScript/pnpm monorepo + Python SDK，开发者预览版
- 本地 clone：`.heagent/tmp/dsh-study-20261103/deepseek-harness/`（depth-1，ghfast.top 镜像，运行产物不入库）
- 方法：精读 docs/architecture.zh.md、cordis-primer.zh.md、subsystems/{compaction,approval}.zh.md、AGENTS.md、SAFETY.zh.md；外围九域（session/schedule/subagent/skills/sandbox/shell/subprocess/tool-execution-pipeline/boot+bundle/mcp）委派扫读；HeAgent 侧锚点取自 frame.md 骨架 + 定向 grep
- 性质：参考研究，非立项文档。借鉴条目若要落地须另走 BMAD 周期

## 一、dsh 架构速写

1. **Cordis 一切皆插件**：插件向共享上下文（`ctx.<key>`）贡献服务/类型化事件/可逆副作用；无特权内核，扩展=挂载旁路插件；注册是 effect，卸载即撤销。
2. **声明式分层装配**：运行中的 dsh 是启动时按序叠加的插件树——profile（具名组装）→ 有序 bundle → 用户 `cordis.patch.yml` → `--patch` overlay。web/headless/sdk/sdk-minimal/acp 五 profile 共享 `dsh-base` 第一层。`dsh --dump-config` 打印生效装配树，任何条目可被 patch 替换。
3. **三事件域 + 五分发模式**：会话事件（持久事实，append-only 日志）/ agent 事件（实时观察拦截）/ 能力事件（无导入循环地向 seam 附策略）。分发模式 emit/waterfall/parallel/serial/bail 是事件公开约定的一部分。
4. **seam 三角色**：Service Definition / Service Provider / Consumer 缺一不可；「换一个 provider 改变整个产品」——fs 与进程共享同一执行世界。
5. **会话日志即模型上下文事实源**：「模型可见 ⟺ 已记录」是结构不变式；`deriveMessages()` 从日志投影模型历史；surface 事件必须声明 `surfaceOp` 入面方式。

## 二、逐轴对标

### 轴 1 装配：声明式插件树 vs 代码闭包
- dsh：profile/bundle/patch 声明式分层；入口=同一装配基座上的 bundle 层差异；required 插件失败拆整个应用、可选失败只告警；`--dump-config` 可观察。
- HeAgent：`cli/composition.py` 代码闭包装配（`_build_provider` + `EngineContainer.default` + `_build_dream_scheduler` 同 interactive.py 闭包）；入口按 `HTTP_ENABLED`/`WS_ENABLED` 开关挂端点；配置目录已有 `config/catalog.py`（网页控制台 §4.18）。
- 结论：全插件化不照搬（体量不匹配）。**可借鉴**：装配树级「生效配置 dump」——HeAgent 有字段目录但无「这次启动实际装配了什么」的一览输出；以及 required/optional 失败分级语义（HeAgent http-server 双关 fail-fast 已是同方向）。

### 轴 2 事件系统：三域五模式 vs 单一总线
- dsh：域按「是否持久/surface 可见/可忽略」分型；分发模式是事件约定；持久 writer 由 agent 生命周期在发布时挂接——**结构上排除「交互 REPL 没挂 sink」这类接缝遗漏**。
- HeAgent：单一 EventBus（EngineEvent.details dict）；57-4 实锤：交互 REPL 不挂 JsonlSink → `EVENTS_ROLLOUT_ENABLED` 交互模式失效，观察必须直接订阅 EventBus。
- 结论：57-4 的缺口在 dsh 是被结构消灭的问题类别。**可借鉴**：frame.md §4.15 事件契约补「事件域分型表」（哪些事件必须持久、由谁挂 sink）+ 分发语义（观察/拦截/扇出）词汇化。低成本文档改造。

### 轴 3 会话日志：不变式与迁移纪律
- dsh：「模型可见⟺已记录」；`ignorable:true` 前向兼容契约——无标记的不认识事件**拒绝重建**（宁可过度拒绝也不悄悄恢复被掏空的会话）；格式 generation 迁移链（`session.vN.jsonl`，已提交 generation 绝不重命名/删除，每包只做 vN→vN+1）；崩溃遗留=可检测合成事件（`interrupted`）。
- HeAgent：SessionStore jsonl 落盘即历史；重载时**丢弃**不完整工具事务（context/session.py:85-105）。
- 结论：同方向不同严格度。**可借鉴**：①「拒绝 vs 丢弃」取舍显式化（HeAgent 丢弃有日志告警，但 dsh 的 ignorable 标记契约更精确）；②格式变更迁移链纪律——直接适用于 MEMORY.md/会话格式未来演进（Epic 59 刚改过格式）。

### 轴 4 工具流水线：瀑布阶段 vs 策略引擎
- dsh：固定顺序 pre-execute(钩子/权限/沙箱)→单调守卫(deny/abstain)→approval 一次性询问→execute→post-execute，三瀑布可转换调用而循环不动；PTC 子调用进同一流水线。
- HeAgent：`PolicyEngine.evaluate_tool_call` 确定性判定（policy.py，五级：白名单/审批/deny-read/deny-write/write-allow）+ ToolExecutor。
- 结论：实质同构，HeAgent 把策略集中在引擎、dsh 把策略摊成流水线阶段。**无需改动**；若未来策略维度增多（如按调用方 scope 差异化），流水线形态是演进参考。

### 轴 5 审批：闭集词表 + 决策入日志
- dsh：闭集 outcome（`allowed-once` 唯一授权；rejected/cancelled/unavailable 一律拒绝）；缺失/异常/违规应答者→`unavailable` fail-closed；`never` 策略在服务内强制（prepend 应答者绕不过）；`approval/asked`/`decided` 审计事件对（branded id 配对）**写入会话日志**，策略变更也是日志事件——回放可重建覆盖值。
- HeAgent：`ToolExecutionMode` 三态（APPROVAL_REQUIRED 在 V1 等同阻断，policy.py:69）+ goal.py workflow 审批门（WAITING_USER/USER_APPROVE 状态机，`approve()` 是唯一放行路径 workflow_runner.py:948）。
- 结论：fail-closed 哲学完全一致（HeAgent 显性失败准则的镜像）。**可借鉴**：审批决策持久化——HeAgent 的 run 授权是运行时态，崩溃/重启后无审计可查；dsh 的「asked/decided 事件对 + 策略变更是日志事件」是现成形态。中成本代码改造。

### 轴 6 压缩：独立收敛（本次对标最高价值验证）
- dsh（对话上下文压缩）：锁先行——`compaction/start` 落日志才动手，崩溃=可检测遗留锁而非假完成；`compactNow` 无有效范围返回 null **不写入**；失败闭集 `busy/cancelled/changed/summary/commit/persistence` 全部持久化到日志；压缩以 surface replace 遮蔽原事件，日志保持 append-only。
- HeAgent Epic 59（长期记忆压缩）：D3 留底先行（归档先落 archive/）；F5④ no-op 不进统计不写入（facts.py:92，本日冒烟实证）；rejected 列表记录被拒合并。
- 结论：**两条独立演化收敛到同一组不变式**（先落底再动手 / no-op 零写入 / 失败有痕）。互相印证为正确设计。差异在作用对象：dsh 改对话 surface，HeAgent 改记忆事实清单。
- **可借鉴（需验证）**：dsh 锁对解决「崩溃窗口」——HeAgent fact_compact 在「留底完成后、MEMORY.md 写回前」崩溃，会留下什么状态？留底在而新状态未写=可检测（留底可作重建源）还是静默不一致？值得一次定向审查（低成本的检查项，非必然缺陷）。

### 轴 7 执行世界：单一 seam vs 双执行面
- dsh：fs 与进程共享同一执行世界，换 provider（如指到远程沙箱）Bash/PTY/LSP 全家搬走；策略按**每次调用**解析（同一时刻两消费方可用不同边界）；「静默的无隔离透传永远不合法」是 seam 契约（无后端=SANDBOX_UNAVAILABLE 拒绝）；`denialSignatures` 是每后端方言而非跨后端并集。
- HeAgent：DockerRunner 进程级沙箱；`command_runner` 与 `executor.sandbox_runner` 双面并存、前者被后者静默忽略（container.py:151-157 警告——本日冒烟时也出现）。
- 结论：这是 HeAgent 现存接缝混乱的直接对症方案。**可借鉴**：统一执行面 seam——命令执行与文件工具共用一个「执行世界」注入口，策略解析独立；静默忽略改为装配期显性失败（要么报错要么接管，不并存）。中成本，可立项。

### 轴 8 调度：两域分离 vs 双触发一体
- dsh：schedule 是宿主级持久任务域（七种时间类型、at-least-once 显式重复投递、`expectedUpdatedAt` 乐观并发）；idle 唤醒不在 schedule 域——是 agent-loop pre-step 的收件箱唤醒。
- HeAgent：DreamScheduler 双触发（cron/idle）共享同一 tick 循环（dream.py）。
- 结论：HeAgent 一体化更简单，dsh 分离更正交；**现结构不必改**。**可借鉴**：投递语义显式化——HeAgent dream 触发的 at-least/misfire 行为未成文（错过的 cron 批次如何处理，llm-digest 记忆里「周日批次周一 08:00 接不住」即此类问题）。

### 轴 9 子代理：组合即白名单 vs 角色白名单
- dsh：subagent 层**不做**工具白名单——可见工具面由挂载的 preset/scope 组装决定（「组合即白名单」）；约束=身份/深度/邻接授权；结算通知与模型代写消息是不同 kind（「合并的 transcript 会把没说过的话记到子代理头上」）。
- HeAgent：SubAgent 角色级 `allowed_tools` 白名单（dreamer 等，pub/roles.py）。
- 结论：两种哲学，HeAgent 的角色声明更直白、dsh 的组合裁剪更正交。**无需改动**；若未来角色增多且白名单开始重复，scope 化是演进方向。

### 轴 10 技能：单元一致，目录形态不同
- dsh：SKILL.md 单元一致；多 provider 分层合并（宿主+per-scope，最近层赢重名）；技能目录是**会话历史内的持久消息**（压缩遮蔽后重建），非每轮重扫注入；`SkillInvocationPolicy {modelInvocable, userInvocable}` 与注册表解耦。
- HeAgent：SkillStore 读 SKILL.md，system prompt 组装时注入。
- **可借鉴**：`modelInvocable/userInvocable` 双开关进 SKILL.md frontmatter（HeAgent 已有类似显性声明准则，这是低成本补强）；目录消息持久化——与记忆压缩的交互是 dsh 已解决的设计题，HeAgent 若将来把技能目录也纳入 compact 范围可直接参考其重建语义。

### 轴 11 多入口：bundle 层 vs 独立开关
- dsh：五 profile 共享 `dsh-base` 装配基座，「产品功能放 profile 组合包，而不是新增应用 bin」。
- HeAgent：interactive/HTTP/WS 各自接线 + `HTTP_ENABLED`/`WS_ENABLED` 独立开关（de8311b）。
- 结论：HeAgent 开关模型已满足现规模；dsh 的「共享基座+入口差异层」在入口继续增多（如 ACP/桌面）时再考虑。**记录备查，不动**。

### 轴 12 Agent 指引纪律（AGENTS.md 对照）
收敛点（互证）：CLAUDE.md 一行薄壳指向 AGENTS.md（dsh 与 HeAgent 同款）；真源唯一；规则自包含+链接高层文档。
dsh 独有纪律值得精选纳入 HeAgent AGENTS.md：
- 「Misconfiguration fails loud at load when self-contained」——配置错误在装载期爆，HeAgent 已有 fail-fast 先例（http-server 双关），可升为通用条款
- 「No hardcoded tunables——部署可变配置必须是可校验 Config 字段；DEFAULT_* 常量不算可配置」——与 HeAgent「用户声明优于代码立场」同源，补上了「常量≠配置」的判定线
- 「Prefer symmetry for parallel values；不解释的对称破缺通常暗示漏提取」——代码评审细则
- 「An empty catch names the error and why」——显性失败的落地细则
- Agent Notes=持久决策理由（机械编辑豁免）、归档 notes 冻结不可编辑——对应 HeAgent 的 retro/台账实践，形态更轻

### 轴 13 安全口径
- dsh：SAFETY.zh.md 面向使用者——实验性声明、「不要把 harness 当不可信工作负载唯一安全控制」、最小权限/一次性环境/备份清单。
- HeAgent：frame.md §4.19 canonical（内部口径）。
- **可借鉴**：若 HeAgent 对外发布，从 §4.19 派生一份面向使用者的 SAFETY 文档（声明进 md 包，符合「用户声明优于代码立场」）。现阶段可不动。

## 三、可落地借鉴清单（按成本/收益排序）

| # | 条目 | 成本 | 承接方式 |
|---|---|---|---|
| 1 | 事件域分型表 + 分发语义词汇化（frame.md §4.15） | 低 | 文档改造 |
| 2 | AGENTS.md 纪律条款精选（fails loud at load / 常量≠配置 / 空 catch 具名 / 对称破缺） | 低 | 文档改造 |
| 3 | fact_compact 崩溃窗口定向审查（留底后写回前崩溃的状态可检测性） | 低 | 检查项，若有缺口小改 |
| 4 | dream 触发 misfire 语义成文（错过的 cron 批次行为） | 低 | 文档改造 |
| 5 | 审批决策持久化（asked/decided 事件对进会话日志） | 中 | BMAD 立项 |
| 6 | 统一执行世界 seam（消解 command_runner/sandbox_runner 双面） | 中 | BMAD 立项 |
| 7 | 格式迁移链纪律成文（MEMORY.md/会话格式演进规范） | 中 | 文档+流程 |
| 8 | SKILL.md 增加 modelInvocable/userInvocable 双开关 | 低 | 声明进 md 包 |
| 9 | 装配树「生效配置 dump」（CLI 一览本次实际装配） | 中 | BMAD 立项 |
| 10 | 「模型可见⟺已记录」结构不变式 | 高 | 长期方向，记录不立项 |

## 四、不建议照搬

- **Cordis 全插件框架**：dsh 是 24,922 commits 的 monorepo，插件化收益来自百包规模；HeAgent 单体 Python harness 引入等价框架是负资产。
- **surface/投影复杂度**：dsh 的 surfaceOp、纯消息投影、generation 链是「日志=唯一事实源」的代价；HeAgent 记忆+会话分离的简单模型在当前规模更划算，只借其纪律（ignorable 契约、迁移链）不借其结构。
- **TypeScript 严格性设施**（type-equiv 漂移检查、cordis-surface 生成目录）：依赖 TS 编译器能力，Python 侧等价物成本高于收益。

## 五、附：本次研究的独立收敛验证

Epic 59 的 D3（留底先行）/D4（写后比对）/F5④（no-op 不进统计）与 dsh compaction 的锁先行/no-op 返回 null 不写入/失败全留痕**独立收敛到同一组不变式**。两个团队在同域问题上的同解，是对 Epic 59 设计决策的外部背书；同时 dsh 的崩溃锁形态提示了 HeAgent 尚未成文的崩溃窗口问题（清单 #3）。

## 六、2026-11-27 复核：十项逐条裁定（挑选依据）

复核方法：对当前代码与文档逐条勘测。11-03 至今约 300 提交（Epic 60–64、Goal-4、两轮审查修复周期），
清单时效需重验；证据锚点逐条给出，均为本次实测。

| # | 条目 | 裁定 | 证据锚点 |
|---|---|---|---|
| 1 | 事件域分型表 + 分发语义 | ✅ 已交付 | `frame/events.md:49-53`「事件域分型与分发语义（2026-11-06，**dsh 对标采纳**）」：运行事实域/进程观察域两域 + 观察/拦截/扇出词汇 |
| 2 | AGENTS.md 四条款 | ✅ 已交付 | `AGENTS.md:78` 指针 + `framework.md` §8.4 canonical（四条款全文在案，含先例） |
| 3 | fact_compact 崩溃窗口审查 | ✅ 本轮闭合（窗口良性） | 详述见下 |
| 4 | dream misfire 语义成文 | ✅ 已交付 | `frame/memory.md:56`「触发投递语义（misfire 口径，2026-11-06 成文）」+ `framework.md:245` cron 同口径 |
| 5 | 审批决策持久化 | ◐ 部分交付，仍开放 | `engine/approval.py`：ApprovalHandler 注入缝已就位（协议化、主循环零改动）；授权 per-run（`RunContext.metadata["approved_tools"]`），docstring 明示**不新增持久化**——asked/decided 事件对进 rollout.jsonl 仍缺 |
| 6 | 统一执行世界 seam | ❌ 未做 | `engine/container.py:195` 仍 `command_runner is ignored` warning 并存——即批次9 结构课题 **B1**（已在 todo 池，「各自独立周期，不批不动」） |
| 7 | 格式迁移链纪律 | ❌ 未成文 | `frame/memory.md` 有格式契约（B4 双开关等）但无迁移链/generation 演进纪律；Epic 59 改格式时未留演进规范 |
| 8 | modelInvocable/userInvocable 双开关 | ✅ 已交付 | B4 双开关 2026-11-06（meta.yaml 契约，`skill_meta.py:81-82` + `skill_catalog.py:222` 过滤 + `skill_load` 显式拒绝）；he-goal 停自动注入即其应用 |
| 9 | 装配树「生效配置 dump」 | ❌ 未做 | `composition.py` / `interactive.py` 无 dump 面（audit_cmd 是审计不是装配） |
| 10 | 「模型可见⟺已记录」不变式 | ➖ 立场不变 | 高成本不立项，维持「记录备查、长期方向」 |

### #3 定向审查结论（本轮完成，原清单留下的检查项）

窗口位置：`compact.py` 留底先行（D3）——`_append_archive` 成功后、MEMORY.md 写回前崩溃。

结论：**良性窗口，非缺陷，无需改动**。推演：留底先行保证「归档 ⊇ 被移除条目」不变式；写回是
最后一步，且 compare-after-read 冲突即放弃整批（留底保留）——崩溃时 MEMORY.md 保持旧态，语义上
「压缩未发生」，重跑压缩只会让归档出现重复小节（小节带真实 UTC 时间戳，重复可辨），数据本体
无损、无静默不一致路径。与 dsh 的崩溃锁对照：dsh 用锁把窗口变成可检测事件，HeAgent 用「写回
最后 + 冲突放弃」把窗口后果压到无害——两种都是把窗口关死的合法形态，后者更简单。

### 复核后待挑清单（真正需要用户裁定收敛的）

- **#7 格式迁移链纪律成文**（低成本，文档+流程）：可搭下次文档周期顺带；
- **#5 审批决策持久化**（中成本，BMAD 立项候选）：注入缝已就位，只差 asked/decided 事件对进
  运行事实域（rollout.jsonl）；
- **#6 统一执行世界 seam**（中成本）：已在 B1 课题池，按池纪律「不批不动」；
- **#9 装配 dump**（中成本，BMAD 立项候选）：现无任何一处能看到「这次启动实际装配了什么」。

四项之外，其余六项（1/2/3/4/8/10）建议按「已交付 / 已闭合 / 立场不变」归档，不再占用待挑面。
用户逐项裁定后，本条 todo（`T-… dsh 借鉴清单`）即可经 todo 整理归档收口。
