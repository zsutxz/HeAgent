# 扩展页索引（`docs/frame/`）

> 状态：`docs/framework.md` 的机制细节分册。维护责任：对应模块的变更提交者。

`framework.md` 只留「架构是什么 + 边界在哪 + 违反即错的约束」；**逐模块的实现事实**（子模块清单、
字段 / 参数表、限额默认值、逐 kind 发射点、判据用例名、逐键配置默认值）按 `4.x` 编号迁到本目录，
编号与 `framework.md` 保持一致——正文里「见 4.16」这类引用指向本目录的对应页。

## 页与覆盖范围

| 页 | 覆盖小节 | 一句话 |
| --- | --- | --- |
| [cli.md](cli.md) | 4.1 | `cli/` 子模块表、启动编排、测试缝与覆盖率口径 |
| [agent.md](agent.md) | 4.2 | `AgentLoop` façade、状态与参数、注入顺序、中间件与子 Agent |
| [providers.md](providers.md) | 4.3 | 各 provider、容错四层（重试 / 轮换 / 回退链 / 切换与路由） |
| [tools.md](tools.md) | 4.4 · 4.11 · 4.14 | 工具系统与沙箱后端、MCP 集成、技能资源读取加固 |
| [context.md](context.md) | 4.5 | 上下文文件分层、Token 计量、压缩与窗口重置、会话持久化 |
| [memory.md](memory.md) | 4.6 | 事实 / 画像 / 人格 / 技能库四库与 dream 巩固 |
| [config.md](config.md) | 4.10 | 四层配置来源、运行快照、逐键默认值与说明 |
| [engine.md](engine.md) | 4.12 | DI 容器、策略链、store / ledger、日志卫生 |
| [goal.md](goal.md) | 4.13 · 4.13.1 | `/goal` 命令族、审批与决策记录、并行写集、受控 GoalScript |
| [events.md](events.md) | 4.15 | `RunEvent` 字段表、逐 kind 发射点、传输与分发语义 |
| [network.md](network.md) | 4.16 · 4.16.1 · 4.17 | HTTP / SSE、WebSocket 四端点与三档、网页控制台与写通道 |
| [call-chains.md](call-chains.md) | 七 | 单次 / 交互 / HTTP+WS / 控制台的完整调用链 |
| [layout.md](layout.md) | 六（原） | `src/heagent/` 目录树速查（阅读辅助，以 `src/` 为准） |

## 阅读顺序

1. 先读 [`framework.md`](../framework.md) 的 §二 数据流与 §三 模块 DAG，建立骨架。
2. 再按要改的模块读本目录对应页；页内「判据」行给出该机制的可执行断言。
3. 涉及暴露面与信任边界时，一律回到 [`framework.md` §4.18](../framework.md#418-安全口径canonical)。
