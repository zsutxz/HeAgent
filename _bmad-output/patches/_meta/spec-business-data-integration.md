# Spec：业务运营数据整合（HeAgent 作统一数据访问层）

> 形态：**母规划 spec**——多阶段、跨周期。进入实现时按阶段衍生独立实现 spec（如 `spec-business-data-mvp`、`spec-approval-callback`），一会话一 spec，不对齐单会话完成（见 [[bmad-quickdev-budget-per-spec]]）。

## source
- 路线来源：用户 2026-08-11 经三问决策选定——① 数据范围＝**业务运营数据**（数据库/表单/Excel/报表 API）；② 目标＝**Agent 统一访问/操作**（跨系统读写、自动化、分析）；③ 载体＝**基于 HeAgent 构建**；④ 架构＝**混合，以 MCP 为主**；⑤ 推进＝**落成规划文档**。
- 参考概念：agent-as-data-plane（用 agent 作统一数据访问层，区别于传统 ETL 入仓）；数据虚拟化 + 按需访问。
- 落地基础（HeAgent 现成）：`@tool` 装饰器 + `ToolRegistry`（`tools/decorator.py:78`、`registry.py:19`）；MCP 客户端三原语 + annotations 闸门（Epic 14/15/16，`tools/mcp/manager.py`）；`PolicyEngine` 7 步治理（`engine/policy.py:135`）；`engine/ledger` 审计；`memory/` 四库（`skills`/`facts`）；`providers` 多层容错；`CronScheduler` 定时。
- 现状缺口（探查确认）：**无 SQL/DB 工具、无通用 HTTP/REST（仅 `web_fetch` GET 只读）、无 CSV/Excel 解析**；V1 `APPROVAL_REQUIRED` 当前等同阻断（`policy.py:52`，无 human-in-the-loop 审批 callback）。
- **治理反直觉点（关键）**：内置 `@tool` 的 `read_only`/`destructive` 在 `PolicyEngine` 阶段**不被消费**（`policy.py:248` 显式跳过内置工具 annotations 裁决）——内置写工具是否走审批仅靠显式列入 `approval_tools`；**MCP 工具的 annotations 闸门有效**（`destructive→审批 / readOnly→放行 / 缺省→fail-safe 审批`，`policy.py:257-270`）。这是选「MCP 为主」的核心治理依据。

## 架构决策（混合，MCP 为主）

| 维度 | A：内置 `@tool` | B：MCP server 封装（**主线**） |
|---|---|---|
| 实现 | 为 DB/REST/Excel 各写 builtin | 每业务系统封 MCP server，`.mcp.json` 接入 |
| 治理 | ⚠️ annotations 不生效，须显式配 `approval_tools`/`sandbox_tools` | ✅ annotations 闸门自动生效（destructive/readOnly） |
| 加系统 | 改 HeAgent 代码 + 重启进程 | 零 HeAgent 代码改动，加一条 `.mcp.json` |
| 隔离 | 工具与 agent 同进程 | server 独立进程，可单独沙箱/限权 |
| 延迟 | 同进程，低 | 多一层进程/网络 |
| 生态 | HeAgent 专属 | 对齐 Claude Code/Cursor，可复用现成 server |

**选定策略**：
- **外部系统**（SaaS API / 第三方库 / 内部报表服务）→ **一律封 MCP server**（治理与隔离最省心，加系统零代码改动）。
- **内部业务库只读探查**（需低延迟、高频）→ 补一个 builtin `db_query`（`read_only=True` + 强制 row limit/超时/列裁剪）。
- Excel/CSV 源 → 封 MCP server（解析在 server 侧），不在 HeAgent 进程内建解析。

## in scope（按阶段）

### 阶段 0 · 业务数据盘点（前置，非编码，阻塞后续）
- 产出：《数据源盘点表》＝ 系统名 / 类型(DB\|REST\|Excel) / 读 or 写 / 敏感等级(PII\|财务\|普通) / owner / 数据量级 / 访问方式(DSN\|API base\|文件路径) / 现有凭据位置。
- 据此最终敲定每个源的 A/B 路线与阶段 1 MVP 选哪 1–2 个源。
- 验证：各业务 owner 签字确认清单。

### 阶段 1 · 只读探查通道（MVP）——衍生 `spec-business-data-mvp`
- **`src/heagent/tools/builtins/db.py` 新增 `db_query`**：`@tool(name="db_query", read_only=True)`，参数化 SQL，强制 `limit`（默认 100，硬上界如 1000）、`timeout`、结果列裁剪；DSN 经 `${ENV}` 读（`DB_DSN_*`），不落代码；模块加到 `builtins/__init__.py:3` import 行即自动注册。
- **核心外部源封 MCP server**：`.mcp.json`（仓库根新增）声明，server 端标 `readOnlyHint=true` → PolicyEngine 免审批放行；未标则 fail-safe 审批（阶段 1 全只读，不应命中）。
- **schema 沉淀**：`.heagent/skills/{业务域}/` 每域一个 skill——`SKILL.md` 写查询套路、`references/` 放 ER 图/字段说明、`scripts/` 放参数化 SQL；零散常用片段进 `facts`（`.heagent/memory/MEMORY.md`）。下次会话 `_build_system()` 自动注入。
- **只读护栏**：row limit / 超时 / 列裁剪三道防拉全表；DSN 凭据 fail-fast（仿 `mcp/config.py:57-72` 的 `${ENV}` 缺失即报错）。
- 验证（AC 见下）：agent 能回答「上月 X 区销售额」类业务问题，数据正确性由业务 owner 人工核对。

### 阶段 2 · 写操作与审批流——前置衍生 `spec-approval-callback`
- ⚠️ **阻塞依赖**：V1 `APPROVAL_REQUIRED`＝阻断（`policy.py:52`），写操作落地前**必须先实现 human-in-the-loop 审批 callback**（外层授权后经 `RunContext.metadata.approved_tools` 注入，支持 `"*"` / `"__mcp__"` 通配，`policy.py:306-314`）。此为独立 spec，不在本规划内实现。
- 写操作源封 MCP server 标 `destructiveHint=true` → PolicyEngine 自动 `APPROVAL_REQUIRED` → 审批 callback → 授权放行。
- **审计**：`engine/ledger` 记录每次写工具调用（谁/何时/何参/裁决）；`EventBus` 发写操作事件。
- 验证：写操作未经审批不得执行；ledger 全可追溯；试错注入「未授权写」必被拦。

### 阶段 3 · 跨系统编排
- 复用 `ToolExecutor` 串联多工具（查库→计算→写回/出报表）；复杂分析用 `task_delegate`/`task_parallel`（`builtins/subagent.py`）拆子 agent；定时报表/对账用 `cron_add`（`builtins/cron.py`）。
- 验证：端到端跑通一个真实跨系统业务流程（如「拉销量→算环比→写回看板→cron 每日推送」）。

### 阶段 4 · 安全硬化收口
- **OS 级沙箱兜底**（CLAUDE.md 文首硬约束——`SafetyGuard`/`PolicyEngine`/`FirejailBackend`/MCP 围栏**均非真边界**）：业务数据 agent 须在容器/firejail 内运行，子进程与出站网络最小权限。
- **凭据**：DB 密码/API key 全走 `${ENV}` + vault，零硬编码（呼应全局安全准则）。
- **返回内容围栏**：业务数据入 LLM 上下文视为不可信，复用 `guard_content` 启发式标记（DP-4，标记透传非真隔离）。
- **脱敏与合规**：PII/财务字段在 server 侧或 `db_query` 结果层脱敏；访问审计满足合规要求。
- 验证：安全 review（经 `security-reviewer`）+ 审计日志完整性核对。

## out of scope（不做 / deferred）
- ❌ **OS 级沙箱本身的实现**——本 spec 声明其必要但不实现（立场段），复用项目既有 firejail/容器路径。
- ❌ **实时 CDC / 流式 ETL 管道**——本规划是「agent 按需访问」的数据平面，不是入仓 ETL。
- ❌ **自建 BI / 报表前端**——agent 产出结论即可，不做可视化 UI。
- ❌ **多租户 / 全员 RBAC**——先单租户，授权经 `RunContext.metadata`；全员 RBAC 另开 spec。
- ❌ **human-in-the-loop 审批 UI 实现**——列为阶段 2 前置依赖，独立 `spec-approval-callback`。
- ❌ **Excel/CSV 解析 builtin**——一律封 MCP server，不在 HeAgent 进程内建。

## AC（验收，按阶段）
- **AC0**（盘点）：《数据源盘点表》产出，每源标注 A/B 路线与敏感等级，业务 owner 确认。
- **AC1**（MVP 只读）：`db_query` 经 `@tool` 注册成功；对 MVP 源执行参数化查询返回 ≤ row limit 行、超时即中止；`.mcp.json` 声明的外部 server 经 `MCPClientManager` 连入，工具命名 `<server>__<tool>`；schema 进 `skills`/`facts` 后下次会话 `_build_system()` 可见。
- **AC2**（治理分流）：阶段 1 全只读——MCP 源（`readOnlyHint=true`）免审批放行，内置 `db_query` 不在 approval 列表即 DIRECT；无任何 `APPROVAL_REQUIRED` 命中。
- **AC3**（写操作，依赖审批 spec）：写源（`destructiveHint=true`）触发 `APPROVAL_REQUIRED`，未授权时阻断、授权后放行；`ledger` 留痕。
- **AC4**（编排）：端到端跨系统流程跑通，含 cron 定时与子 agent 拆分。
- **AC5**（安全收口）：安全 review 无 CRITICAL；审计日志完整；凭据零硬编码（grep `-r` 仓库无明文 DSN/key）。
- **AC6**：每阶段衍生 spec 各自的 pytest 全绿 / ruff 零新增 / mypy clean。

## 约束（硬）
- 所有数据访问工具（内置或 MCP）一律经固定链 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler，不绕过（CLAUDE.md 硬约束）。
- 内置写工具**必须显式列入 `approval_tools`**——不得依赖 annotations（对内置不生效）。
- 只读查询强制 row limit / 超时 / 列裁剪三道护栏，禁止全表扫描型调用。
- 凭据经 `${ENV}` 插值 + vault，缺失 fail-fast，**零硬编码**。
- 业务数据返回内容入上下文一律视为不可信（复用 `guard_content`，标记透传非真隔离）。
- 跨模块数据用 Pydantic 模型（`types.py`），禁止原始 dict（CLAUDE.md 硬约束）。

## 立场（不变，须诚实声明）
- **业务运营数据＝高敏感**（含 PII / 财务），用 agent 统一读写比文件/shell 风险面更高：一次被污染的返回内容或 prompt injection 可经 agent 触发跨系统误写、或泄露敏感数据入上下文。
- 与 CLAUDE.md 文首声明一致：`SafetyGuard` / `PolicyEngine` / `FirejailBackend` / MCP annotations 闸门 / `guard_content` **均非真正安全边界**。本 spec 的所有治理（annotations 闸门、approval 列表、ledger 审计、返回围栏）皆为 **defense-in-depth 标记/拦截/记录，非真正隔离**。
- **缓解（defense-in-depth，非真正边界）**：MCP server 进程隔离 + 最小权限、写操作必审批、ledger 可审计、只读护栏、凭据 vault、返回内容标记。
- **硬立场**：业务数据 agent **必须在 OS 级沙箱（容器/firejail）内运行**并对子进程/出站网络限权；PII/财务数据须脱敏 + 访问审计。本 spec **不制造「agent 操作业务数据已安全」假象**——与项目教训「安全边界必须诚实声明」一致。

## 开放问题 / 待补充业务前置（阻塞阶段 0）
1. **《数据源盘点表》**——系统名/类型/读写/敏感度/owner/量级/访问方式（阶段 0 核心 input）。
2. **部署形态**：HeAgent 跑在哪？能否直连内网数据库？OS 沙箱（容器/firejail）就绪度？
3. **第一期读/写范围**：MVP 是否严格只读（推荐）？
4. **凭据管理现状**：有无 vault / secret manager？DSN 如何下发？
5. **合规要求**：PII/财务数据的脱敏、留存、审计具体口径？

## 衍生 spec（后续会话）
- `spec-approval-callback`（阶段 2 前置，阻塞写操作）——human-in-the-loop 审批 callback。
- `spec-business-data-mvp`（阶段 1）——`db_query` builtin + 核心 MCP 源 + skills/facts 沉淀。
- 阶段 3/4 待阶段 1/2 落地后按需开。
