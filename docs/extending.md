# 扩展指南：新增 Provider / Tool / Skill 包

> 状态：当前实现指南（2026-09-22，Phase 5 C3）。代码事实以 `src/` 为准；硬约束见
> [`frame.md`](frame.md) 三（模块依赖 DAG）与项目根 [`CLAUDE.md`](../CLAUDE.md)。
> **通用前置**：新增 provider/tool **禁止**从 `heagent.agent` 导入（全仓无例外）；
> 跨模块数据一律 Pydantic 模型（`types.py`）；业务执行只读构造期配置快照（Phase 1 原则，
> 不在业务方法里调 `get_settings()`）。

## 一、新增 LLM Provider

1. **实现契约**：继承/实现 `providers/base.BaseProvider` —— `send(messages, *, tools) -> ProviderResponse`
   （async）、`stream(...) -> AsyncIterator[StreamEvent]`、`get_metadata() -> ProviderMetadata`。
   参考最小实现：`tests/test_agent_loop.py::StubProvider`（结构兼容即可，Protocol 风格）。
2. **接入方式**（三选一）：
   - OpenAI 兼容端点：复用 `providers/openai_compat.py`，仅加配置（`config.py` 的 provider 段 + `.env`）；
   - 新协议：在 `providers/` 下新建 `snake_case.py`，实现上述契约，别忘流式 `usage`/`tool_calls`
     的最终 chunk 补全（先例：Anthropic 流式实现，见 `providers/anthropic*`）；
   - 智能路由/容错：跨 provider 回退挂 `providers/chain.py`，多密钥轮换挂 `providers/key_rotation.py`。
3. **中间件**（可选）：包裹 provider 调用（重试/限流/日志）实现 `agent/middleware.MiddlewareFn`，
   经 `AgentLoop(middlewares=[...])` 注入。
4. **测试**：provider 单测放 `tests/providers/`；agent loop 交互一律用 `StubProvider`
   （tests 既有先例），**不打真实 API**；`reset_settings()` fixture 重置 Settings 单例。
5. **文档**：若引入新配置项，同步 `.env.example` 与 `docs/frame.md` 4.10（配置管理）。

## 二、新增内置 Tool

1. **实现**：在 `tools/builtins/` 新建 `snake_case.py`，用 `@tool(read_only=...)` 装饰 async 函数
   （先例：`tools/builtins/git.py`）；在 `tools/builtins/__init__.py` 触发注册（import 即注册）。
2. **治理面**（`engine/policy.py` 自动裁决）：
   - 只读工具：`read_only=True` → `readOnlyHint=True`，策略层可放行；
   - 副作用工具：考虑是否需要沙箱档位（`SANDBOX_TOOL_PROFILES` 配置）或审批；写操作治理
     依赖 `ToolAnnotations`（MCP 路径）——内置工具按 read_only 声明走。
3. **路径安全**：涉及文件读写必须经 `tools/path_safety.resolve_under_root` / `workspace_root()`
   围栏；文本读取走 `open_text_under_root`（单一安全入口，`os.open` 有 AST 白名单契约）。
4. **子进程**（若 spawn）：复用 `tools/sandbox/process.py` 内核——`reap_subprocess`（有界回收）、
   `cap_channel`（512KB/通道截断）、`scrub_sensitive_env`（env 剥离）；不要手写 `communicate()` 无界等待。
5. **target 摘要**：工具的「作用对象」日志/事件摘要由 `tools/call_summary.summarize_tool_call`
   自动生成；新工具名若需要专门摘要，在该单点补分支（不要在展示层各写一份）。
6. **测试**：`tests/test_<tool>.py`；patch 注意——测试若 monkeypatch 模块内部函数，
   patch 目标与调用方必须同模块（Python 模块全局查找语义）；实例级 patch 要求 call 点走 `self.`。
7. **文档**：`docs/frame.md` 4.4（tool 系统）模块表追加一行。

## 三、新增 Skill 包（声明式，BMad 风格）

1. **目录结构**：`.heagent/skills/<package-id>/`：
   - `SKILL.md`（必需）：frontmatter 声明 `canonical_id` 等；正文是方法论（分层铁律：方法论只在
     SKILL.md，代码零文案副本）；
   - `workflow.md`（工作流包才有）：`## Step NN: name` 区块，`NN` 从 1 连续；`role:` 指向
     `.heagent/skills/<role>/SKILL.md`（指向不存在的包会在执行时硬失败，不降级）；
   - `templates/`、`references/`、`assets/`、`scripts/`：经 `SkillPackage.read_template` 等类型化
     读取（内部走 `path_safety.open_text_under_root` 安全入口）。
2. **声明契约**：`input:` 只能引用 CLI 注入键（`user intent` / `user responses` / `existing project
   context`）或前序步骤 `output:` 名字，否则该步骤 BLOCKED；`validation: section: <标题>` 由
   `WorkflowRunner` 机械校验输出章节；`required_resources` 声明必需模板（缺失即加载失败）。
3. **导入外部包**：`memory/skill_importer.py`（manifest.csv + manifest.lock；哈希与物化原子换入）。
4. **测试**：包解析 `tests/test_skill_packages.py`；工作流装载 `tests/test_workflow_resources.py`；
   读取安全 `tests/test_skill_packages_toctou.py`。**读取技能文件禁止裸 `read_text`/`open`**
   （AST 契约钉死，见 `tests/test_architecture_contracts.py::test_skill_modules_do_not_read_files_directly`）。
5. **文档**：包行为变更改包声明，不改 Python；运行时进度/恢复语义见 `docs/frame.md` 4.13。

## 四、架构契约自检（改完必看）

跑 `pytest tests/test_architecture_contracts.py -q`——反向依赖、frontmatter 单点、`os.open` 白名单、
skill 裸读禁令、sandbox/mcp click-free 等契约全部在此；新增边界时**必须同步维护**该文件，
把只写在文档里的硬约束钉成可执行断言。
