# 架构沿革与参考来源

> 状态：历史索引；整理日期：2026-09-21。维护责任：架构变更提交者。当前行为以 [frame.md](frame.md) 和源码为准。

## 迁移记录

| 时间 | 变化 | 当前实现与证据 |
| --- | --- | --- |
| 2026-09 | persist、roles 从 engine 迁出 | `src/heagent/persist.py`、`src/heagent/roles.py`；共享底层能力 |
| 2026-09-17 | 集中 frontmatter 解析 | `src/heagent/frontmatter.py`、`tests/test_architecture_contracts.py` |
| 2026-09-20 | workflow 资源模型和装载职责分离 | `engine/workflow_resource.py`、`goal/workflow_loader.py`，路径均相对于 `src/heagent/` |

原始周期与验收证据见 [迭代历程](iteration.md) 和 [规划归档](../_bmad-output/README.md)。本表是历史摘要，不是新一轮待办。

## 参考实现

[hermes-agent](https://github.com/NousResearch/hermes-agent.git)（NousResearch）——同源自学习 agent 架构（skills/facts/profile/soul 记忆、MCP、cron、多 provider 容错），设计与约定可作参考。注意 hermes 为**同步单文件巨型架构**（`run_agent.py`/`cli.py` 各逾万行、多平台 gateway/TUI），HeAgent 为**异步模块化单库**——**不可直接照搬**，须按 HeAgent 栈（Pydantic / asyncio / pytest-asyncio）改造适配；仅硬约束级条目进 `CLAUDE.md`，细节以本文件为准。（2026-09-17 自 CLAUDE.md「参考实现」节原样迁入，常驻改按需查阅。）

### path_safety 对 hermes 的借鉴

`tools/path_safety.py` 的凭证 deny 与内部状态读 deny 借鉴自 hermes `file_safety.py`（2026-08-24），见 [当前工具架构](frame.md)。
