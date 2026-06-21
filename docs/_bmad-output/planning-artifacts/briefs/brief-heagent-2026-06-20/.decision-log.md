# Decision Log — HeAgent MCP Client 集成

> Brief 的决策审计记录。每条记录「决定了什么 + 为什么」，供后续 PRD / architecture 追溯，也为「为何否决另一条路」留证。

## 2026-06-20 · Discovery 阶段决策

### D1 · 走路 A「通用 MCP client」，否决路 B「GitHub 专用」
- **决定**：做通用 MCP client 适配层，GitHub 作为首个接入 / 验收场景。
- **否决**：路 B（只为 GitHub 做接入，甚至不走 MCP、直接调 GitHub API 包成 @tool）。
- **理由**：用户主动选了「MCP 工具协议」方向，且 HeAgent 定位是「框架」——协议层的复用性（以后接数据库 / 浏览器 / Slack 只改配置）才是选 MCP 的价值所在。路 B 更短平快，但放弃了复用，与方向相悖。

### D2 · 只接 Tools 原语，不接 Resources / Prompts
- **决定**：V1 只消费 MCP 的 **Tools** 原语。
- **理由**：与 Pydantic AI / CrewAI / OpenAI Agents SDK / LangChain 等主流框架一致；Resources（应用控制、被动注入）与 Tools（模型控制、主动调用）边界模糊，多数框架为简化只接 Tools。Resources / Prompts 留作后续可选。

### D3 · V1 只读优先，写操作进 roadmap
- **决定**：第一版以 GitHub 只读（看 issue / 搜代码 / 读 repo）为验收。
- **理由**：风险最低 + 对开源用户好上手；先把「MCP server 连接 → 发现 → 调用」链路打通。
- **张力记录**：用户原话是「让 agent **操作** GitHub」，而「操作」通常含写。决议诚实处理：V1 scope 写明只读，写操作明确列进 Vision 作为「紧接的下一步」（非遥远 roadmap）。若后续 review 认为只读验证价值不足，可升级为含写。

### D4 · 服务对象「自用为主 + 开源友好」
- **决定**：受众定位为主创自用提效，同时对开源用户友好可用。
- **影响**：brief 须兼顾「个人效率场景」与「开源用户的配置 / 文档体验」；成功标准含两者。

### D5 · 依赖 pin `mcp>=1.27,<2`，握手封装内部
- **决定**：依赖官方 Python SDK（`mcp` 包），pin 上界 `<2`；`initialize` 握手等协议细节封装在 `MCPClientManager` 内部，不泄漏给 `AgentLoop`。
- **理由**：SDK v2（~2026-07 stable）+ 协议 2026-07-28 RC（stateless、删 initialize）是双重 breaking；封住握手细节 = 迁移时改动局部化。

### D6 · 声明式 mcpServers 配置，对齐 Claude Code / Cursor
- **决定**：配置形态为声明式 `mcpServers`（command / args / env for stdio，url / headers for Streamable HTTP）。
- **理由**：业界事实标准，用户认知成本低，生态示例多。

### D7 · 安全定位：MCP server 归入既有不可信边界
- **决定**：外部 MCP server 视同「运行不可信代码 + 返回不可信输出」，纳入 CLAUDE.md 文首安全声明，受与内置工具同等（且同样有限）的约束。
- **理由**：与现有 `SafetyGuard` 局限同构；不制造「接了 MCP 更安全」的假象。

---

## 待校准（[ASSUMPTION] 清单）

> 以下为 fast path 起草时的推断，标在 brief 内 `[ASSUMPTION: ...]`，待用户 review 校准：

- **配置落点**：`.heagent/mcp.json`（vs 别的路径 / 格式）
- **鉴权**：GitHub Personal Access Token 放环境变量（vs GitHub App / 配置文件）
- **差异化「工具使用沉淀成技能」**：列为 Vision 探索方向，非 V1 承诺（vs 直接并入 V1）

---

## 2026-06-20 · Editorial Polish（Finalize）

对 `brief.md` 跑了两道 doc_standard 审校（structure + prose，并行 subagent），采纳并 apply 的关键改动：

- **概述**：移除 epic/FR 计数（下游不挣其位），价值句精简。
- **问题**：GitHub 触发点由 4 处重复收敛为 1 句锚点；「造轮子」→「成熟实现」。
- **方案**：由实现细节（`AsyncExitStack` / `ClientSession` / `inputSchema`）收敛为 4 项产品级能力点——brief 不越权做架构决策，实现细节留给 architecture / addendum。
- **差异化**：第 1 点（记忆整合）由「承诺」压缩为「探索方向」；删「老实说」；明确「诚实的安全定位本身就是差异化」。
- **受众**：新增「非受众（V1）」边界。
- **成功标准**：每条补轻量量化门槛（`pytest` 全绿、≥1 个 GitHub 只读 E2E）。
- **范围**：依赖 pin / 协议迁移从 V1 In 移出，与时间窗口合并为独立「技术约束 / 兼容性窗口」小节。
- **术语统一**：「外部工具（MCP server 暴露的工具）」「Streamable HTTP」「namespace」「MCP client 适配器」。

未采纳：少量低优先风格项（重复用词、节奏），不阻塞。
