# Retrospective — Epic 13（MCP Client 周期 · 安全边界与开源可用）

> **事后补做**（2026-06-29），基于 `epics-mcp-client.md` Epic 3 AC + `CLAUDE.md` 安全声明 + `frame.md` 已知缺口提炼，非 epic 刚完成时的实时复盘。
> 用 `bmad-retrospective` skill 实质流程生成；**适配 CLI/库项目**——省略 sprint velocity / production incidents / deployment / stakeholder acceptance（本项目无时间盒、无生产部署、无外部 stakeholder），相关字段不适用，按「不编造」原则不杜撰数字。

## Epic 概览

| 项 | 内容 |
|----|------|
| 主线编号 | Epic 13（= `epics-mcp-client.md` 内部 Epic 3） |
| 标题 | 安全边界与开源可用（收尾） |
| FR | FR-10（安全声明覆盖 MCP）、FR-11（同等约束 + 返回内容不可信） |
| Stories | 13-1 `safety-statement-mcp`（done）、13-2 `opensource-config-docs`（done） |
| 性质 | 纯文档/配置收尾，代码改动极小，零回归风险 |

## 成果（What went well）

1. **安全立场同构落地**：把 MCP 不可信边界纳入既有「SafetyGuard / engine sandbox 均非真边界」声明，显式不制造「接 MCP 更安全」假象（`CLAUDE.md` 文首声明 +「MCP 特定风险 FR-10/11」节）。
2. **deferred 决策显式编号**：V1 `SafetyGuard` 不扩展到 MCP 标记为架构决策 **DP-4**，跨 `CLAUDE.md` / `architecture.md` / `frame.md` 引用，不散落。
3. **开源采用门槛降低**：`.mcp.json.example` + README 接入说明 + `CLAUDE.md` 模块速查 / DAG 就位，照示例即可接入自有 server。
4. **零契约改动**：纯文档/配置 epic，NFR-2（零回归）自然满足，无代码风险。

## 挑战（Challenges）

1. **诚实 vs 实用的张力**：声明「须 OS 级沙箱兜底」，但框架本身不提供 OS 沙箱（`execute_in_sandbox` 默认透传）——把隔离责任明确交给部署层，框架不假装提供。
2. **MCP 输出无围栏进上下文**：server 返回内容（含远端响应）直接并入 LLM 对话，prompt injection 无隔离——V1 框架内无法解决，只能声明为同等不可信。
3. **deferred 边界管理**：运行时断连只降级 `ToolError`（FR-3 部分），未做 auto-unregister；须清晰记录防遗忘。

## 教训（Key lessons）

1. **新不可信组件套用既有安全立场**：接入 MCP 时复用「非真边界 + OS 沙箱兜底」同构表述，不为新组件制造例外或「更安全」错觉。
2. **deferred 决策要编号 + 跨文档引用**：DP-4 这类「暂不做」的决定若只存于一处，极易在后续迭代被误认为「已做」或被遗忘。
3. **收尾 epic 的价值在可被采用**：代码量小不代表价值低——`.mcp.json.example` + README 是开源用户接入的第一道门。
4. **一致性优于特殊性**：MCP 工具返回内容视为不可信，与内置工具返回同等处理，优于为 MCP 单造一套。

## 技术债 / 遗留（Deferred）

| 项 | 来源 | 状态 |
|----|------|------|
| `SafetyGuard` 扩展到 MCP（敏感工具确认 / 返回内容复核） | DP-4 / `frame.md` 五 | deferred，未做 |
| 运行时断连 auto-unregister | FR-3 | 部分（仅降级 `ToolError`） |
| MCP Resources / Prompts 原语、写操作 | `frame.md` 五 | deferred，V1 仅 Tools |

## 行动项（Action items）

| # | 行动 | Owner | 触发 / 时机 |
|---|------|-------|-------------|
| A1 | 评估为运行时断连补 auto-unregister（开 spec） | tan | 用户报告 stale 工具调用困惑时 |
| A2 | DP-4（`SafetyGuard` → MCP）纳入下一集成周期候选 | tan | 已记入 `docs/iteration.md` 第四章路线图 |
| A3 | MCP 返回内容隔离（prompt injection 围栏）作研究项跟踪 | tan | 框架内 V1 不可解，依赖 OS 沙箱 + 上游 |

## 下一步

见 [`docs/iteration.md`](../../docs/iteration.md) 第四章「路线图与下一步」——MCP deferred 项（DP-4 安全覆盖、FR-3 断连 unregister、Resources/Prompts）均为下一集成周期候选。

## 不适用字段（CLI/库项目）

sprint velocity / 实际-vs-计划 story points / production incidents / deployment status / stakeholder acceptance —— 本项目无 sprint 时间盒、无生产部署、无外部利益相关者，按「不编造」原则省略。
