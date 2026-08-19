# HeAgent 交互与可扩展层周期 — Product Brief

> 周期编号：interaction（主线延续，Epic 29 起）
> 日期：2026-08-19
> 状态：frozen（规划冻结）

## 一、背景与动机

HeAgent 已完成 24 个主线 Epic + MCP/Sandbox/健壮性/质量/GUI 全部周期，**引擎底座**（Provider
容错、工具系统、四类记忆、PolicyEngine/ToolExecutor/ledger/store、MCP 三原语、cron、dream、
Textual GUI）已就绪。对照 Claude Code 与 hermes-agent 的功能审查（2026-08-19）发现，短板集中在
**面向使用者的交互与可扩展层**——审批闭环、会话恢复、斜杠命令、hooks、plan mode 等。这些能力
几乎都能复用已交付的基础设施，无需触碰 `AgentLoop` 核心循环。

## 二、目标

把 HeAgent 从「架构实验场」推进为「可日常使用的 agent 工具」，补齐 Claude Code 已验证的核心
交互能力，同时保持项目「学习价值优先、模块边界优先」的定位不变。

## 三、范围（按优先级）

| 优先级 | 功能 | 复用点 | 对照来源 |
|--------|------|--------|----------|
| P0 | ① 运行时审批闭环 | `APPROVAL_REQUIRED` + `approved_tools` 已就绪 | CC |
| P0 | ② 会话恢复入口（`--continue`/`--resume`） | `SessionStore`/`resume` 已就绪 | CC |
| P1 | ③ 斜杠命令注册表 + 用户自定义命令 | `SKILL.md` frontmatter 解析器可复用 | CC |
| P1 | ④ Hooks 系统（用户可配置事件钩子） | `EventBus` 事件已很细 | CC |
| P1 | ⑤ Plan Mode / 只读模式 | `PolicyEngine.allowed_tools` | CC |
| P2 | ⑥ 配置文件驱动自定义角色 | `RoleSpec` 字段已足够 | CC |
| P2 | ⑦ 成本估算 | `TokenUsage` 已统计 | CC |
| P2 | ⑧ CLI readline 历史/补全/Ctrl+C 中断 | — | CC |
| P2 | ⑨ `/init` 生成项目上下文文件 | `init` 命令已存在（仅建 `.env`） | CC |
| P2 | ⑩ 内置 Web 搜索 | `web_fetch` 已存在 | CC/HA |
| 收尾 | 技术债：`web_fetch` 接 `guard_content`；`cron/expr` 畸形输入诊断 | 已有 suggested fix | — |

## 四、非目标（本轮不做）

- 多模态（vision/图像/语音）——与 `design.md` 明确非目标冲突。
- Web API / 多租户服务端。
- 交互式审批的「跨 run 永久授权」（`approve_always` 持久化到磁盘）——P0 仅做 per-run 授权。
- Hooks 的完整事件过滤 / 参数模板引擎——P1 起步先做最小可用。

## 五、决策日志

| # | 决策 | 理由 |
|---|------|------|
| D1 | 审批闭环以「可注入 `ApprovalHandler`」落地，默认 None（auto-deny 等价现状），零核心回归 | 库消费者（CLI/GUI）各自注入交互实现，`AgentLoop` 零改动 |
| D2 | 审批授权写入 `RunContext.metadata["approved_tools"]`（per-run 粒度） | 复用 `PolicyEngine._approval_granted` 既有逻辑，不新增持久化 |
| D3 | 会话恢复先做 `--continue`（最近会话）+ `--resume <session_id>`，不改 `AgentLoop` 签名 | `SessionStore.recent_session_ids`/`load` 已就绪，仅 CLI 装配层改动 |
| D4 | 新周期编号延续主线 Epic 29 起 | 沿用 `iteration.md` 1.5「Epic 编号延续主线」规则 |

## 六、成功标准

- 配置 `approval_tools` 后，CLI 交互模式在工具执行前询问用户，同意后授权、拒绝后阻断。
- `heagent --continue` 恢复最近一次会话上下文继续对话。
- 未配置审批/未传 `--continue` 时行为与现状完全一致（零回归）。
