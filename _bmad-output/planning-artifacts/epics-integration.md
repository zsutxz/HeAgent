---
stepsCompleted: [1, 2, 3, 4]
status: complete
completedAt: '2026-06-03'
startedAt: '2026-06-03'
validation: passed
inputDocuments:
  - docs/prd-HeAgent-2026-05-23/prd.md
  - docs/architecture-HeAgent-2026-05-23/architecture.md
  - docs/planning/epics.md
project_name: 'HeAgent'
user_name: 'tan'
date: '2026-06-03'
---

# HeAgent - Epic 6: AgentLoop 全模块集成

## Overview

将已实现但未接入 AgentLoop 的 5 个模块集成到核心循环中，使 Agent 具备完整的记忆、会话恢复、长对话压缩和自动重试能力。

## Requirements Inventory

### Functional Requirements (Integration)

- INT-1: 上下文压缩接入 AgentLoop (FR-13) — token 使用率超阈值时自动摘要旧消息
- INT-2: 会话持久化接入 AgentLoop (FR-15) — run() 开始加载历史、结束时保存会话
- INT-3: 事实记忆接入 AgentLoop (FR-11) — 系统提示词注入 + 注册 fact_add 工具
- INT-4: 用户画像接入 AgentLoop (FR-12) — 系统提示词注入 + 注册 profile_update 工具
- INT-5: 重试中间件接入 (FR-19) — 作为 MiddlewareFn 包装 provider.send()

### NonFunctional Requirements

- NFR-1: AgentLoop 模块不超 1500 行
- NFR-6: 所有集成点可独立单元测试
- 现有测试不回归

### Additional Requirements

- Settings 已有 retry_max_attempts/retry_base_delay/retry_max_delay/compression_threshold
- 中间件管道 compose() 已可用
- AgentLoop 构造器需扩展参数
- cli.py 需初始化并注入新模块

### FR Coverage Map

| FR | Story | 说明 |
|----|-------|------|
| FR-19 | 6.1 | retry_with_backoff 作为中间件包装 provider.send() |
| FR-11 | 6.2 | FactStore 注入系统提示词 + fact_add 工具 |
| FR-12 | 6.2 | ProfileStore 注入系统提示词 + profile_update 工具 |
| FR-15 | 6.3 | SessionStore 在 run() 生命周期加载/保存 |
| FR-13 | 6.4 | ContextCompressor 在 token 超阈值时自动压缩 |
| — | 6.5 | CLI 初始化所有模块并注入 AgentLoop |

## Epic List

### Epic 6: AgentLoop 全模块集成

用户成果：Agent 具备完整的记忆、会话恢复、长对话压缩和自动重试能力——可处理真实复杂任务场景。
**FRs covered:** FR-11, FR-12, FR-13, FR-15, FR-19

---

## Epic 6: AgentLoop 全模块集成

用户成果：Agent 具备完整的记忆、会话恢复、长对话压缩和自动重试能力——可处理真实复杂任务场景。
**FRs covered:** FR-11, FR-12, FR-13, FR-15, FR-19

### Story 6.1: 重试中间件集成

As a 开发者,
I want retry_with_backoff 作为中间件包装 provider 调用,
So that 瞬态错误（网络超时、503）自动恢复，非瞬态错误快速失败。

**Acceptance Criteria:**

**Given** `providers/retry.py` 中有 `retry_with_backoff` 函数和 `MiddlewareFn` 类型
**When** 创建重试中间件函数并注入 AgentLoop 的 `middlewares` 列表
**Then** 中间件包装 `next_fn(req)` 调用，对 `TRANSIENT` 错误自动重试
**And** 使用 `Settings` 中的 `retry_max_attempts`、`retry_base_delay`、`retry_max_delay` 配置
**And** `RATE_LIMITED` 和 `AUTH_FAILED` 错误立即抛出，不重试
**And** 重试日志记录每次尝试的错误类型和延迟时间
**And** 无中间件时（`middlewares=[]`）行为不变，回归通过

### Story 6.2: 事实记忆与用户画像集成

As a 开发者,
I want FactStore 和 ProfileStore 自动注入系统提示词，并注册管理工具供 LLM 调用,
So that Agent 跨会话记住用户偏好和项目事实，回复可个性化适配。

**Acceptance Criteria:**

**Given** `memory/facts.py` 有 `FactStore`，`memory/profile.py` 有 `ProfileStore`
**When** AgentLoop 构造器接受可选的 `facts` 和 `profile` 参数
**Then** `_build_system()` 自动加载事实列表和用户画像文本，注入到系统提示词的 `<memory>` 和 `<profile>` 区块中
**And** 创建 `tools/builtins/memory.py`，包含 `fact_add` 和 `profile_update` 两个 `@tool` 注册工具
**And** `fact_add` 调用 `FactStore.add()`，`profile_update` 调用 `ProfileStore.update_section()`
**And** 工具文件使用与 `skills.py` 相同的模块级注入模式（`configure_*_tools` 函数）
**And** `tools/builtins/__init__.py` 注册新工具模块
**And** `FactStore`/`ProfileStore` 为 `None` 时不注入任何记忆内容，不注册工具

### Story 6.3: 会话持久化集成

As a 开发者,
I want AgentLoop 在运行开始时恢复历史会话，结束时保存完整对话,
So that 用户可以跨会话继续之前的对话。

**Acceptance Criteria:**

**Given** `context/session.py` 有 `SessionStore` 类
**When** AgentLoop 构造器接受可选的 `session` 参数和 `session_id` 参数
**Then** `run()` 开始时，若 `session` 和 `session_id` 均存在，调用 `session.load(session_id)` 恢复历史消息，拼接到 `state.messages` 前方
**And** `run()` 正常返回后，若 `session` 和 `session_id` 均存在，调用 `session.save(session_id, state.messages)` 保存会话
**And** `run()` 异常时（`BudgetExceeded` 等）也尝试保存已积累的消息
**And** `session` 为 `None` 或 `session_id` 为空时，行为不变（无持久化）
**And** 恢复的历史消息不重复追加（系统消息保持最新，旧系统消息替换）

### Story 6.4: 上下文压缩集成

As a 开发者,
I want AgentLoop 在每轮迭代后检查 token 用量并自动压缩,
So that 长对话不会因 token 超限而失败。

**Acceptance Criteria:**

**Given** `context/compressor.py` 有 `ContextCompressor` 类
**When** AgentLoop 构造器接受可选的 `compressor` 参数
**Then** 每轮 `provider.send()` 返回响应后，若 `compressor` 存在且 `response.usage` 有值，调用 `compressor.compress(state.messages, usage.total_tokens, max_tokens)`
**And** `max_tokens` 从 `provider.get_metadata().max_tokens` 获取，若无元数据则使用 `Settings` 中的默认值
**And** 压缩结果替换 `state.messages`，日志记录压缩前后的消息数量
**And** `compressor` 为 `None` 时，不执行压缩，行为不变
**And** 压缩阈值使用 `Settings.compression_threshold`（已存在于 `ContextCompressor` 构造器）

### Story 6.5: CLI 接线与端到端验证

As a 开发者,
I want CLI 入口初始化所有新模块并注入 AgentLoop,
So that 用户开箱即用所有集成功能。

**Acceptance Criteria:**

**Given** 所有 Story 6.1~6.4 已完成
**When** 更新 `cli.py`
**Then** `_run_single` 和 `_run_chat` 中创建 `FactStore`、`ProfileStore`、`SessionStore`、`ContextCompressor` 实例
**And** 重试中间件自动构造并传入 `AgentLoop` 的 `middlewares` 列表
**And** `ContextCompressor` 使用当前 `provider` 实例创建（需要 provider 做摘要）
**And** 交互模式 `_run_chat` 为每次对话生成唯一 `session_id`，支持跨轮对话恢复
**And** 单次模式 `_run_single` 不使用会话持久化（一次性执行）
**And** 现有测试全部通过（`pytest`），无回归
**And** `AgentLoop` 模块行数不超过 1500 行（NFR-1）
