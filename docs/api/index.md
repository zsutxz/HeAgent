# API 参考

本区按**包**组织，全部由 docstring 自动生成（`mkdocstrings` + `show_submodules`）：每个包页展开该包的
公开子模块，渲染公开类 / 函数 / 方法的签名与说明。

覆盖口径与 `docs/framework.md` 的架构模块一致（12 个核心包）；入口层（`cli/`、`gui/`）不在内——
它们的可读性由 CLI 输出与测试覆盖（模块边界见 `tests/test_api_docstrings.py`）。

判据：`tests/test_api_docs_pages.py` 钉住「每个核心包都有生成页 + nav 已登记」；站点构建由
`mkdocs build --strict` 与 `scripts/build_docs.py` 负责。

| 包 | 页面 | 内容 |
| --- | --- | --- |
| `heagent.agent` | [agent](agent.md) | 顶层编排：AgentLoop 与各运行期策略（run / stream / resume / context / 子 Agent） |
| `heagent.config` | [config](config.md) | 配置面：Settings、四层来源求解、受闸门写流水线、keyring 读取与轮换提醒 |
| `heagent.context` | [context](context.md) | 上下文管理：token 估算、压缩、窗口重置、会话持久化、旁路调用记账 |
| `heagent.cron` | [cron](cron.md) | 定时任务域：作业存储、调度与执行 |
| `heagent.engine` | [engine](engine.md) | 运行时治理：PolicyEngine、ToolExecutor、台账 / 快照 / 观测 / 工作流 |
| `heagent.events` | [events](events.md) | 对外机器可读事件契约（JSONL / rollout） |
| `heagent.memory` | [memory](memory.md) | 记忆系统：事实库、画像、人格、字节归档与语义压缩 |
| `heagent.network` | [network](network.md) | 入口传输层：HTTP / SSE / WebSocket（不依赖运行栈） |
| `heagent.providers` | [providers](providers.md) | LLM Provider 与智能路由、回退、密钥轮换、元数据缓存 |
| `heagent.pub` | [pub](pub.md) | 公共层：异常与错误码、类型、持久化、审计、输入验证、路径与日志卫生 |
| `heagent.skills` | [skills](skills.md) | 技能库域包：解析、匹配索引、存储与声明式技能包 |
| `heagent.tools` | [tools](tools.md) | 工具系统：注册表、SafetyGuard、路径校验、沙箱后端、内置工具与 MCP 桥接 |
