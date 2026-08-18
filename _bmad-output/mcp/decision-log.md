# Decision Log — HeAgent MCP Client 集成（三阶段整合）

> **2026-08-18 整合**：本文整合原 `mcp-client/brief-decision-log.md` + `mcp-client/prd-decision-log.md`（阶段一 V1：D1-D7 + DP-1~6 + Editorial）、`mcp-v2-upgrade/prd-decision-log` 相关决策（阶段二：FR 编号空间 + 订正）、`mcp-client-v2/brief.md` 的 P1-P5 + `prd.md` OQ 定稿（阶段三）。每条记录「决定了什么 + 为什么」，供下游追溯与「为何否决另一条路」留证。

---

# 阶段一 · MCP V1 集成

## Brief 阶段决策（D1-D7，2026-06-20）

### D1 · 走路 A「通用 MCP client」，否决路 B「GitHub 专用」
- **决定**：做通用 MCP client 适配层，GitHub 作为首个接入/验收场景。
- **否决**：路 B（只为 GitHub 做接入，甚至不走 MCP、直接调 GitHub API 包成 @tool）。
- **理由**：用户主动选了「MCP 工具协议」方向，且 HeAgent 定位是「框架」——协议层的复用性（以后接数据库/浏览器/Slack 只改配置）才是选 MCP 的价值。路 B 更短平快，但放弃复用。

### D2 · 只接 Tools 原语，不接 Resources / Prompts
- **决定**：V1 只消费 MCP 的 **Tools** 原语。
- **理由**：与 Pydantic AI / CrewAI / OpenAI Agents SDK / LangChain 等主流框架一致；Resources（应用控制）与 Tools（模型控制）边界模糊，多数框架为简化只接 Tools。后由阶段三补齐。

### D3 · V1 只读优先，写操作进 roadmap
- **决定**：第一版以 GitHub 只读（看 issue/搜代码/读 repo）为验收。
- **理由**：风险最低 + 对开源用户好上手；先把「连接 → 发现 → 调用」链路打通。
- **张力记录**：用户原话是「让 agent **操作** GitHub」，而「操作」通常含写。决议诚实处理：V1 scope 写明只读，写操作明确列进 Vision 作为「紧接的下一步」。若后续 review 认为只读验证价值不足，可升级为含写。

### D4 · 服务对象「自用为主 + 开源友好」
- **决定**：受众定位为主创自用提效，同时对开源用户友好可用。
- **影响**：brief 须兼顾「个人效率场景」与「开源用户的配置/文档体验」。

### D5 · 依赖 pin `mcp>=1.27,<2`，握手封装内部
- **决定**：依赖官方 Python SDK（`mcp` 包），pin 上界 `<2`；`initialize` 握手等协议细节封装在 `MCPClientManager` 内部，不泄漏给 `AgentLoop`。
- **理由**：SDK v2（~2026-07 stable）+ 协议 2026-07-28 RC（stateless、删 initialize）双重 breaking；封住握手细节 = 迁移改动局部化（→ 阶段二兑现为隔离层）。

### D6 · 声明式 mcpServers 配置，对齐 Claude Code / Cursor
- **决定**：配置形态为声明式 `mcpServers`（command/args/env for stdio，url/headers for Streamable HTTP）。
- **理由**：业界事实标准，用户认知成本低，生态示例多。

### D7 · 安全定位：MCP server 归入既有不可信边界
- **决定**：外部 MCP server 视同「运行不可信代码 + 返回不可信输出」，纳入既有安全声明，受与内置工具同等（且同样有限）的约束。
- **理由**：与 `SafetyGuard` 局限同构；不制造「接了 MCP 更安全」的假象。

## 待校准（[ASSUMPTION] 清单 → 由 PRD finalize 定稿）

- 配置落点 `.heagent/mcp.json`（vs 别的路径/格式）→ DP-1 定稿为项目根 `.mcp.json`
- 鉴权 GitHub PAT 放环境变量（vs GitHub App/配置文件）→ DP-2 定稿
- 差异化「工具使用沉淀成技能」列为 Vision（vs 并入 V1）→ DP-6 定稿

## Editorial Polish（Finalize，2026-06-20）

对 `brief.md` 跑两道 doc_standard 审校（structure + prose，并行 subagent），采纳：概述去 epic/FR 计数；问题收敛为 1 句锚点；方案由实现细节收敛为 4 项产品级能力点（brief 不越权做架构决策）；差异化第 1 点由「承诺」压缩为「探索方向」；新增「非受众（V1）」边界；成功标准补轻量量化门槛；依赖 pin/协议迁移与时间窗口合并为独立「技术约束/兼容性窗口」小节；术语统一。未采纳：少量低优先风格项。

## PRD 阶段决策（DP-1~DP-6，2026-06-20）

> 继承 D1-D7；FR 编号策略 FR-1~11 全局稳定编号按 feature 分组；能力导向（实现细节放 addendum/architecture）；UJ downscale 为单个示例会话。

### DP-1 · 配置落点 = 项目根 `.mcp.json`（1/6 已定）
- **决定**：MCP server 配置文件为项目根 `.mcp.json`。
- **否决**：`.heagent/mcp.json`（`.heagent/` 现装运行时产物 skills/memory/sessions/cron，配置性质不同，混放别扭）。
- **理由**：对齐 Claude Code/Cursor 业界标准文件名与位置（D6），用户心智复用、开源友好度最高。

### DP-2 · 鉴权 = GitHub PAT 走环境变量（2/6）
- **决定**：GitHub 鉴权用 PAT，经 `${GITHUB_TOKEN}` 插值注入 `.mcp.json`，不落配置明文。
- **否决**：GitHub App（V1 过重）/ 配置内明文（安全）。
- **理由**：与现有 `.env` + pydantic-settings 凭据惯例一致；最小可行。

### DP-3 · GitHub 验收清单 = 列 open issue + 代码搜索（3/6）
- **决定**：V1 验收跑通两类只读 E2E：列 open issue、代码搜索；其余只读为加分项。
- **理由**：两类覆盖「结构化列表」与「全文检索」两种典型调用形态，足以证明链路通；不追求全集。

### DP-4 · SafetyGuard 对 MCP = 声明为主（4/6）
- **决定**：V1 不扩展 `SafetyGuard` 到 MCP 工具调用；以安全声明 +「返回内容视为不可信」边界为主，检查机制扩展交 architecture 探索。
- **理由**：`SafetyGuard` 现主要管 shell 命令；MCP 工具非 shell，V1 先定边界。
- **后续（跨文档 deferred 锚点）**：DP-4 第一半（执行前工具名拦截）2026-07-08 交付；第二半（返回内容启发式围栏）2026-07-10 交付；用户可配置注入签名入口仍 pending。

### DP-5 · 验收 server = 官方远程 Streamable HTTP（5/6）
- **决定**：GitHub 验收用官方远程 server（`github/github-mcp-server` Streamable HTTP），不依赖本地 Docker。
- **否决**：社区 stdio 版（需本地装、维护弱）。
- **理由**：只读 + 官方维护，配置最简；双 transport 仍都支持（FR-1）。

### DP-6 · 记忆整合 = Vision 非 V1（6/6）
- **决定**：MCP 工具使用沉淀成技能的整合列为 Vision，不进 V1。
- **理由**：继承 brief 差异化定位；V1 聚焦基础接入闭环。

## PRD Finalize（2026-06-20）

Reviewer gate 跑 validation rubric walker（`reviews/_v1/prd-review-rubric.md`，verdict「需修复后通过」）+ 综合 editorial。采纳：§8 标题修正（[ASSUMPTION] 残留矛盾）、FR-9 schema 锚点 + V1 边界化、FR-3 区分连接失败 vs 运行时断连、FR-2 工具发现时序约束（eager/lazy 交架构定）、FR-7 无配置行为、NFR-2 覆盖率基线、NFR-4 可测阈值、NFR-3 成功标准句。未采纳（低优先）：R3 用词口语化、§6 与 FR-7 冗余等。结果 `prd.md status: final`，无 phase-blocker。

---

# 阶段二 · MCP v1→v2 升级准备

## 方向 override（2026-07-12，原 memlog 记录）

- **原始方向**：`mcp-primitives` 周期（Resources/Prompts 原语扩展，承接 V1 Out deferred 项）。
- **证伪**：2026-07-12 一手 research（协议 RC 2026-07-28 按期 locked；SDK v2 stable 目标 2026-07-27 即将重塑 client API；同代框架 Pydantic AI/CrewAI 仍 tools-only；Prompts 无真实需求）→ 原方向 ROI 低于 v1→v2 升级准备，**挑战原方向假设**。
- **tan 决策**：转向「MCP v1→v2 升级准备」周期；周期目录 `mcp-primitives` → `mcp-v2-upgrade`；原 Resources/Prompts/写操作三 deferred 项暂挂，待 v2 stable 落地后重评（→ 后由阶段三实际落地）。

## 关键决策（2026-07-12）

## 关键决策（2026-07-12）

- **FR 编号独立空间**：本周期 FR-1~5，与 V1 FR 独立；引用 V1 周期 FR/NFR/DP 时写全限定（如 V1 FR-3、V1 NFR-3、V1 DP-4）。
- **【订正 2026-07-12】** 原 research digest 误断「v1 最新 stable = 1.27.2 / 无 1.28.x」，rubric review F1 据此误 CONFIRMED。实际 1.28.0 早在 2026-06-20 已被本仓库安装（V1 Story 1.1 commit `5b6453f`），1.28.1 为当前最新。故 V1 prd §6「v1.28.0 stable」**非笔误、正确**；FR-1/Story 14-1 已据此重定为「bump floor 到 1.28.1」（非降级到 1.27.2）。
- **隔离层抽象形态**（PRD [ASSUMPTION] → 架构定稿）：**Adapter 函数式收敛模块（`session_api.py`）**，非 Protocol——v1→v2 是替换不是并存，多态无价值（AD-1）。
- **FR-3 等价机制选型**（A/B/C → 架构定稿）：**C 过渡占位（v1 保留 send_ping）+ v2 切 A 被动（call_tool 失败即注销）**；B（`server/discover` 周期探测）否决但留作重评备选（AD-3）。
- **Open question（留 v2 切换任务）**：`ClientSession` vs `Client(mode='auto')`——POC 实测答案 = **保持 `ClientSession`，不迁**（SDK v2 保留 legacy `initialize`，`mode` 是 `Client` 参数，HeAgent 用 `ClientSession` 不命中）。
- **评审**：`reviews/_upgrade/review-adversarial.md`（对抗评审）+ `review-rubric-facts.md`（事实核查 rubric）。

---

# 阶段三 · MCP Client V2

## Brief 关键决策（P1-P5，2026-07-17 checkpoint）

- **P1 · Resources 消费模型**：定稿 = **on-demand 内置工具**（`read_resource`/`list_resources`），不自动全量注入。备选 = 自动注入全部 resources 进 system prompt（context 膨胀风险，不推荐）。
- **P2 · Prompts 消费模型**：定稿 = **CLI slash 表面**（`/mcp-prompt`）。备选 = 暴露为工具让 LLM 自调（语义怪异，不推荐）。
- **P3 · Prompts 是否纳入本周期**：✅ **已确认**：纳入，列为最弱腿、**Epic C 最后交付**。
- **P4 · 缺 annotations 的默认策略**：定稿 = **fail-safe**（视为非只读 → 需确认）。备选 = 放行（危险，不推荐）。
- **P5 · 周期结构**：✅ **已确认**：**单周期、三 epic、分阶段交付**（Epic A 写操作治理最先 / Epic B Resources / Epic C Prompts），共用一份 architecture。

## PRD Open Questions 定稿（OQ-1~6）

- **OQ-1（fail-safe 保守度 → V3 增强）**：已定稿「缺 annotations → 需确认」。若日后实测太吵，V3 增强：已知只读工具名白名单 / per-server 关闭 fail-safe。本周期不做。
- **OQ-2（annotations 接入点）**：架构定稿 = **`evaluate_tool_call` 增 `schema` kwarg**（调用方 `execute_tool_call` 从 registry 取 schema 传入，两调用点都传）。否决：污染 ToolCall / 注入 registry / 塞 RunContext.metadata（AD-1）。
- **OQ-3（策略优先级）**：✅ **已定稿**——显式策略（`approval_tools`/`approval_mcp_tools`）优先于 annotation；反向不成立（FR-A4）。
- **OQ-4（CLI slash 机制）**：架构定稿 = **最小 slash 分发器**（无既有机制可复用）；推荐接入 (i) `_mcp_lifecycle` 返回 manager，`_run_chat` 经 `as` 取实例（AD-7）。
- **OQ-5（订阅 defer）**：架构定稿 = **defer** `subscribe_resource`（与 on-demand 及 2026-07-28 stateless RC 双冲突）。
- **OQ-6（resource templates）**：架构定稿 = **defer** `list_resource_templates`（边际价值低，具名 resources 已覆盖主用例）。

## 其他架构决策（AD-4/AD-5 相关定稿）

- **Resources 归属**：走「manager 注册的聚合桥接工具」路径（`mcp__` 命名空间，`mcp` 聚合 token），**不是** V1 内置工具形态——确保 `_is_mcp_tool` 识别 → 继承全量 V1 MCP 门控（AD-5）。
- **`read_resource` 签名收紧**：`read_resource(server: str, uri: str)`，`server` 必填（消解跨 server 同 URI 歧义）——收紧 PRD FR-B2 原 `read_resource(uri=...)`（AD-5）。
- **注入围栏提升**：`_guard_injection` 提升为 `mapping.py` 公共函数 `guard_content(text)`，Tools/Resources/Prompts 三者共用单一实现（AD-6）。
- **评审**：`reviews/_v2/prd-review-rubric.md`（PRD 评审）+ `reviews/_v2/review-adversary.md` + `reviews/_v2/review-reality-check.md` + `reviews/_v2/review-rubric.md`。

---

# 决策编号索引（速查）

| 编号 | 阶段 | 决策 |
|------|------|------|
| D1-D7 | V1 | brief 阶段（通用 client / Tools-only / 只读优先 / 受众 / pin+封装 / 声明式配置 / 不可信边界） |
| DP-1~6 | V1 | PRD 阶段（`.mcp.json` / `${GITHUB_TOKEN}` / 两类验收 / SafetyGuard 声明为主 / 官方远程 server / 记忆 Vision） |
| **DP-4** | V1 | 跨文档 deferred 锚点：SafetyGuard 扩展 MCP（后两半交付 + 用户签名入口 pending） |
| FR 编号空间 + 订正 | 升级 | 独立 FR-1~5 + 全限定引用；1.28.0 非笔误订正 |
| AD-1~6 | 升级 | 隔离层 5 调用点收敛 / diff 为空 / C→A 断连 / 纯 v1 / 零回归 / DAG 异步 |
| P1-P5 | V2 | Resources on-demand / Prompts slash / 纳入确认 / fail-safe / 三 epic 结构 |
| OQ-1~6 | V2 | fail-safe 保守度 / schema kwarg / 显式策略优先 / slash 分发器 / 订阅 defer / templates defer |
| AD-1~8 | V2 | schema kwarg / 固定优先级 fail-safe 仅 MCP / 确定性 / _sessions / mcp__ 聚合桥接 / guard_content / slash 分发器 / 诚实立场 |
