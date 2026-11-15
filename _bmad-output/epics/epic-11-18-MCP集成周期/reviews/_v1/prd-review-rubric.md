# PRD Quality Review — HeAgent MCP Client 集成

## Overall verdict

pass-with-fixes. 这是一份目标清晰、scope 诚实的 internal capability PRD，决策点干净、非目标明确、安全边界与既有框架约束（DAG / 异步 / 既有异常层级）衔接到位，brief → PRD → addendum 的分工也合理。主要风险集中在 done-ness 维度：多个 FR 仍是能力描述而非可验证条件（NFR-4「不显著拖慢」、FR-9「返回结构化结果」无 schema 锚点），加上个别 NFR 缺阈值（覆盖率「不低于当前基线」未给基线数值）。这些是局部补强，不动摇主体。

## Decision-readiness — strong

开放问题全部已定稿（§8 六条 `✅已定`），无 phase-blocker，决策点以**决策**形式陈述而非「考虑中」。关键 trade-off 显式命名：

- §7 R5 把官方远程 server vs 社区 stdio 的取舍摊开，并明确「验收采用官方远程」给了什么（只读 + 官方维护、无需本地 Docker）。
- §3 非目标把写操作 / Resources / Prompts / server 反向暴露 / OAuth / Registry 全部外推，不模糊。
- FR-11 把 SafetyGuard 扩展机制**主动降级为 architecture 探索项**，没有把未决安全问题粉饰成已解决——这是诚实的决策而非回避。

对照 brief 的「internal / solo」定位，决策颗粒度恰当。

### Findings
- **medium** §8 标题写「开放问题 / [ASSUMPTION]」，但全部条目已定稿。`[ASSUMPTION]` tag 与正文「全部已定稿」自相矛盾——rubric 关注的 Assumptions Index roundtrip 会因此产生噪音。*Fix:* 把标题改为「决策记录」或「Decisions」，移除 `[ASSUMPTION]` 残留 tag；或在 §8 顶部一句话说明这些是「已 triage 的假设，保留作为追溯」。

## Substance over theater — strong

无 persona theater（§2 受众一句话带过，不灌水）、无 innovation theater（MCP 接入是真实生态缺口，非营销话术）、无 vision theater。NFR 整体扎实——NFR-1（全异步）、NFR-3（版本 pin + 握手封装为 stateless 迁移预留）、NFR-6（错误隔离）、NFR-7（DAG 约束）都是产品特定约束，不是模板套话。Success Metrics（§5）配 counter-metric 是加分项。

## Strategic coherence — strong

有明确 thesis：从「自带工具」升级为「可连接生态无限工具」，首个验收锚 GitHub 只读。FR 分组（连接生命周期 / 发现桥接 / 配置 / GitHub 验收 / 安全）服务于同一弧线，无游离能力。Success Metrics 对齐 thesis（MCP 链路打通、协议可迁移），counter-metric（server 连接失败率、与 SDK v2 强耦合面）防 SM 失真。MVP scope kind = platform capability，scope 逻辑匹配。

### Findings
- **low** §5「开源可用」SM 的目标列是「声明式配置 + 文档示例可让他人接入」，但 FR（§3）里**没有任何 FR 要求产出文档示例**。文档作为 SM 的可观测手段却无对应 FR 支撑，SM ↔ FR traceability 断一环。*Fix:* 在 §3 加一条轻量 FR-12（或挂到 FR-7）「提供 `.mcp.json` 示例 + README 接入说明」，或在 §9 下游明示文档由 epic 承担。

## Done-ness clarity — adequate

这是最需要补强的一维。FR 多数能力导向清晰，但可验证后果参差。

### Findings
- **high** **NFR-4「启动性能」无阈值**（§4）。「不显著拖慢」「stdio 子进程开销可控」是 adjectives，违反 rubric 明文「bounds, not adjectives」。下游 story 无法据此写验收。*Fix:* 给定可测阈值，如「单 stdio server 冷启动连接 < X ms」「N server 并行发现总耗时 < Y ms（N=3）」，或退一步写「启动连接不阻塞 AgentLoop 首次响应（lazy 或后台并发）」。
- **high** **NFR-2「覆盖率不低于当前基线」未给基线数值**（§4）。zero-regression 的反指标「新增 bug 数」也无法机械验证。*Fix:* 在 PRD 或引用处给出当前 pytest 覆盖率基线（如「≥ 当前 main 分支覆盖率 X%」），让下游 story 能 gate。
- **medium** **FR-9「返回结构化结果」缺 schema 锚点**（§3.4）。「列出 open issue」与「代码搜索」的「结构化」未定义字段——是 MCP 原生 ToolResult 还是 HeAgent `ToolResult`？issue 列表最少含哪些字段（number/title/state/url）？这影响 §9 的 GitHub 验收 epic 能否直接写出 E2E 断言。*Fix:* 在 FR-9 或 addendum 给出最小结果形状（如 issue 至少含 `number/title/state/url`，search 命中至少含 `path/snippet`）。
- **medium** **FR-3「失败 server 的工具不注入」缺机制边界**（§3.1）。未说明：发现阶段失败 vs 运行时崩溃，工具是全量不注入还是已注入后摘除？连接中途断开，已注册工具的生命周期如何？*Fix:* 明确「连接建立阶段失败 → 该 server 工具不入注册表；运行时断连 → 标记不可用 / lazy 移除」二选一，交 architecture 兜底也行，但 PRD 层面要选向。
- **low** **FR-6 命名 namespace 规则未定形**（§3.2）。「工具名加 server 名前缀」是方向但无 separator / 冲突二次处理规则。LLM 看到的工具名形态会影响 tool-selection 准确率（R3 的缓解之一）。*Fix:* 给一个示例形态（如 `<server>__<tool>`）或显式声明交 architecture 定。

## Scope honesty — strong

非目标 §1 末、§3 开头两处出现且一致，`✅已定` 标记（虽然提问者说算刻意，但作为决策追溯是清晰的）。§7 风险 5 条覆盖安全 / 子进程 / 工具爆炸 / SDK breaking / server 形态，每条配缓解，无隐藏风险。`[ASSUMPTION]` 仅 §8 标题残留（见 decision-readiness finding）。Internal / solo 定位下开放项密度恰当。

## Downstream usability — adequate

§9 下游（架构 / epics）指引具体（点名 `MCPClientManager`、transport 抽象、`ToolSchema` 映射），FR 编号稳定且全局唯一（FR-1..11）。但 ID 连续性与名词一致性有小瑕疵。

### Findings
- **medium** **NFR/FR 编号断层**：FR 是 FR-1..FR-11，NFR 是 NFR-1..NFR-7，无重复无跳号——这部分 OK；但 §9 提到「按 FR 拆 epic（连接生命周期 / 发现桥接 / 配置 / GitHub 验收 / 安全）」共 5 个 epic 候选，**与 FR 分组（3.1-3.5 共 5 组）一一对应，逻辑干净**。真正的小瑕疵：**无 Glossary**（见 mechanical notes），跨 FR 的「server」「transport」「namespace」含义靠读者从上下文推断，架构消费时名词漂移风险存在。
- **low** **Success Metrics 无 ID**（§5）。表格六行无 SM-1..SM-6 编号，下游若要 SM ↔ FR / counter-metric 做 traceability 表需要自己编。*Fix:* 加 `SM-1..SM-6` 左列。

## Shape fit — strong

Internal / solo capability spec，shape 选型正确：无 UJ（单操作者、§2 用一个示例会话代替 UJ 是恰当的轻量化）、SM 偏运营性（链路打通、零回归、协议可迁移而非 DAU/MAU）、persona 不灌水。Brownfield 约束（§6 DAG、复用 `ToolRegistry`/`ToolSchema`/`ToolResult`/`SafetyGuard`、与既有异常层级衔接）引用准确，与 CLAUDE.md 模块依赖 DAG 一致。未过度形式化（没强塞 UJ / 多 persona），也没 under-formalized（安全 / 协议 / DAG 约束都给了）。这一维是本文最强项。

## Mechanical notes

- **Glossary 缺失**：全文无 Glossary 段。「MCP server」「transport」「stdio」「Streamable HTTP」「namespace」「ToolRegistry」「ToolSchema」等术语首次出现即用，未集中定义。对 internal PRD 可接受，但 addendum 若也省略，架构 / epic 消费时会重复定义。建议在 PRD 或 addendum 顶部加 5-8 条核心术语。
- **ID 连续性**：FR-1..11、NFR-1..7 连续无跳号无重复。SM 无编号（见 downstream finding）。Cross-ref（§9 引用 FR 分组、§3.4 引 FR-9、风险 R3 引 ContextCompressor）均能解析。
- **Assumptions Index roundtrip**：§8 标题含 `[ASSUMPTION]` tag 但正文全部 `✅已定`，且**无独立 Assumptions Index 表**做 roundtrip 校验。因提问者声明 `✅已定` 刻意，此项作为信息记录——建议标题去 tag 或显式说明「假设已全部 triage，不再维护 index」。
- **MCP SDK 版本号不一致**：§4 NFR-3 写 `mcp>=1.27,<2`，§6 约束写「官方 `mcp` Python SDK（v1.28.0 stable）」。基线版本应统一（建议以 §6 的 1.28.0 为 pin 下限，§4 写 `>=1.28,<2`）。
- **协议日期措辞**：§6「stable `2025-11-25`，`2026-07-28` RC stateless breaking」日期混入正文，与 §4 NFR-3「2026-07-28 stateless 协议迁移」一致，OK。
- **必要 section 覆盖**：背景 / 目标 / 受众 / FR / NFR / SM / 约束 / 风险 / 开放问题 / 下游 齐全，符合 internal capability PRD 形态。无可测性 / 验收 section——rubric 说「有时 FR 的 consequences 承载即可」，本文多数 FR 满足，唯 done-ness finding 列出的几条需补。

## 建议修复优先级

1. **high** — NFR-4 加阈值（done-ness）
2. **high** — NFR-2 给覆盖率基线数值（done-ness）
3. **medium** — FR-9 给最小结果 schema（done-ness）
4. **medium** — FR-3 明确运行时断连工具生命周期（done-ness）
5. **medium** — §8 标题去 `[ASSUMPTION]` 残留 / 补 Assumptions Index 说明（mechanical）
6. **medium** — 补 Glossary（downstream）
7. **low** — SM 加编号、MCP SDK 版本号统一、文档 FR 补齐 / 下游声明（downstream + mechanical）
