# API 参考

全部由 docstring 自动生成（`mkdocstrings` + `show_submodules`）：每个核心包一节，展开该包的
公开子模块，渲染公开类 / 函数 / 方法的签名与说明。

覆盖口径与 `framework.md` 的架构模块一致；入口层与静态投递面不在内——它们的可读性由 CLI 输出与
测试覆盖（边界见 `tests/test_api_docstrings.py`）。

判据：`tests/test_api_docs_pages.py` 钉住「每个核心包都有渲染指令 + nav 已登记 + 单页」；站点构建由
`mkdocs build --strict` 与 `scripts/build_docs.py` 负责。

/// note
本页由 `mkdocstrings` 从 docstring 自动生成，展开各包的公开子模块；私有模块（`_` 前缀）与
私有成员不渲染。想改说明文字请改源码 docstring（书写口径见 `docs/testing.md`）。
///

| 包 | 内容 |
| --- | --- |
| `heagent.agent` | 顶层编排：AgentLoop 与各运行期策略（run / stream / resume / context / 子 Agent） |
| `heagent.config` | 配置面：Settings、四层来源求解、受闸门写流水线、keyring 读取与轮换提醒 |
| `heagent.context` | 上下文管理：token 估算、压缩、窗口重置、会话持久化、旁路调用记账 |
| `heagent.cron` | 定时任务域：作业存储、调度与执行 |
| `heagent.engine` | 运行时治理：PolicyEngine、ToolExecutor、台账 / 快照 / 观测 / 工作流 |
| `heagent.events` | 对外机器可读事件契约（JSONL / rollout） |
| `heagent.memory` | 记忆系统：事实库、画像、人格、字节归档与语义压缩 |
| `heagent.network` | 入口传输层：HTTP / SSE / WebSocket（不依赖运行栈） |
| `heagent.providers` | LLM Provider 与智能路由、回退、密钥轮换、元数据缓存 |
| `heagent.pub` | 公共层：异常与错误码、类型、持久化、审计、输入验证、路径与日志卫生 |
| `heagent.skills` | 技能库域包：解析、匹配索引、存储与声明式技能包 |
| `heagent.tools` | 工具系统：注册表、SafetyGuard、路径校验、沙箱后端、内置工具与 MCP 桥接 |

::: heagent.agent
    options:
      show_submodules: true

::: heagent.config
    options:
      show_submodules: true

::: heagent.context
    options:
      show_submodules: true

::: heagent.cron
    options:
      show_submodules: true

::: heagent.engine
    options:
      show_submodules: true

::: heagent.events
    options:
      show_submodules: true

::: heagent.memory
    options:
      show_submodules: true

::: heagent.network
    options:
      show_submodules: true

::: heagent.providers
    options:
      show_submodules: true

::: heagent.pub
    options:
      show_submodules: true

::: heagent.skills
    options:
      show_submodules: true

::: heagent.tools
    options:
      show_submodules: true
