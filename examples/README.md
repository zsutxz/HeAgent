# 示例库

五个可运行的最小示例，覆盖本仓的三个扩展点（工具 / Provider / 技能包）加两个常用组合（故障转移 /
事件订阅）。

**全部默认离线**：不需要网络，也不需要 API key。四个 `main.py` 各自内嵌一个 stub Provider，先让读者
看到框架怎么转；要接真实模型只需换一处构造。`skill-package/` 不含代码入口，它是一份能被 `SkillStore`
解析的技能包 + 校验命令。

前提：仓库已 `pip install -e .`（否则 `import heagent` 失败）。

| 目录 | 解决什么问题 | 关键符号 |
| --- | --- | --- |
| [`custom-tool/`](custom-tool/) | 写一个 Agent 可调用的工具 | `@tool`、`ToolRegistry` |
| [`custom-provider/`](custom-provider/) | 接一个自己的 LLM 后端 | `BaseProvider`（Protocol）、`ProviderResponse` |
| [`provider-chain/`](provider-chain/) | 多后端自动故障转移 | `ProviderChain`、错误分类 |
| [`events-stream/`](events-stream/) | 拿一轮 run 的结构化轨迹 | `EngineContainer.events`、`EngineEvent` |
| [`skill-package/`](skill-package/) | 写一个能被加载的技能包 | `SKILL.md` frontmatter、`SkillStore` |

## 运行约定

```bash
# 在仓库根执行（workspace_root = 进程 cwd）
python examples/custom-tool/main.py
python examples/custom-provider/main.py
python examples/provider-chain/main.py
python examples/events-stream/main.py

# 技能包示例：用 SkillStore 校验能被解析
python -c "from heagent.skills.skill_store import SkillStore; print(SkillStore('examples/skill-package').list_skills())"
```

每个目录的 README 都带「期望输出」段——输出对不上就是环境有问题（最常见的是 `.env` 里的
`SANDBOX_BACKEND` 指向本机不可用的后端，启动时会多一行 fallback 提示）。

## 这里**没有**覆盖什么

- HTTP / WS 入口的定制（那是 `network/` 的事，见 [`README.md`](../README.md) 的入口章节）。
- `/goal` 声明式工作流的作者视角（见 [`docs/framework.md` §4.13](../docs/framework.md#413-goal-驱动工作流-goal)）。
- MCP server 的接入（改 `.mcp.json` 即可，见 [`docs/faq.md`](../docs/faq.md)）。
- 中间件 / 重试策略的组合（`Agent(middlewares=[my_middleware])`，本仓无现成示例）。

## 稳定性说明

示例里有两类导入：

- **公开符号**（`heagent` 包的 `__all__`）：`Agent`、`tool`、`OpenAIProvider`、`ProviderChain`、
  `EngineContainer`、`Settings`。这些跨版本保持。
- **包内路径**（示例需要看类型时才用）：`heagent.providers.base`（`BaseProvider` / `ProviderMetadata`）、
  `heagent.pub.types`（`ProviderResponse` / `TokenUsage` / `ToolCall`）、
  `heagent.engine.observability`（`EngineEvent`）、`heagent.pub.exceptions`（`ProviderError`）、
  `heagent.skills.skill_store`（`SkillStore`）。**这些是非稳定 API**：属于本仓内部结构，
  重构时可能移动或改名，升级前请对照 `CHANGELOG.md` 与 `docs/framework.md`。

## 与本仓纪律的关系

示例不进 `pytest` / `ruff` / `mypy` 的既有范围（`src tests scripts`），但仍须遵守架构约束：
新增 Provider 不得从 `heagent.agent` 导入，新增工具的文件路径必须经 `heagent.tools.path_safety` 校验。
