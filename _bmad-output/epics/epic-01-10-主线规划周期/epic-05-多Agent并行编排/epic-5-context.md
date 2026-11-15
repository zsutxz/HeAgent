# Epic 5 Context: 多 Agent 并行编排

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

让 Agent 能将复杂任务拆分成可并行的子任务，委派给隔离的子 Agent 实例执行，再回收结果汇总。这让单会话 Agent 可以在不污染父 Agent 状态的前提下处理可分解的工作（如并行检索、多方案探索），是 HeAgent 从单线程执行走向任务编排的关键能力。

## Stories

- Story 5.1: 子 Agent 生成与执行（FR-16）
- Story 5.2: 并行子 Agent 编排（FR-17）

## Requirements & Constraints

- 每个子 Agent 拥有独立的对话上下文（messages）和独立的迭代预算；子 Agent 的执行不得修改父 Agent 的状态。
- 子 Agent 默认继承父 Agent 的全部工具集（registry）；工具继承受同一套安全护栏（SafetyGuard）约束。
- 子 Agent 执行完毕后将结果回传给父 Agent；父 Agent 收到的是结果汇总，不是流。
- 多个子 Agent 通过 `asyncio.gather()` 并行运行，全部完成后返回结果列表。
- 单个子 Agent 失败不得阻塞其他子 Agent；失败的子 Agent 返回错误结果（而非抛异常），父 Agent 最终拿到完整的成功/失败混合汇总。
- 子 Agent 预算可与父 Agent 独立分配（可配置）；默认子 Agent 迭代上限低于主循环。

## Technical Decisions

**隔离模型 — 同进程 asyncio 任务，不做进程隔离。** 子 Agent 通过 `asyncio.create_task()` 创建、`asyncio.gather()` 收集，共享事件循环与进程内存。Rationale：HeAgent 是单 Agent 单会话场景，子 Agent 是短期任务委派，进程隔离的开销不划算。仅在协程/对象层面隔离上下文与状态。

**上下文隔离的边界（关键决策）。** 子 Agent 为每次 `run()` 创建全新的 `AgentLoop`，确保对话上下文（messages、iteration counter）是空白起点、不携带父 Agent 历史消息。父 Agent 只通过任务字符串（task prompt）向子 Agent 传递意图，不透传父级的消息列表。

**共享 vs 独立注入的依赖：**
- 共享（继承自父/进程级单例）：`BaseProvider`、`ToolRegistry`、`SafetyGuard`。这些是无状态服务或进程级单例，共享是安全的。
- 不继承（每次新建/留空）：父 Agent 的 `messages`、迭代计数、会话 ID、累积的 tool 结果。
- 待定/当前未注入（实现时需明确取舍）：SOUL 人格、自动匹配的 skills、facts 记忆、profile 画像、上下文文件（CONTEXT.md/AGENTS.md/CLAUDE.md）、ContextCompressor。当前 `SubAgent` 仅构造裸 `AgentLoop`，这些自学习模块**没有**下传——这是当前实现与完整 Epic 意图之间的已知缺口。需要决定：子 Agent 是否应继承人格与项目上下文（让其回复风格、项目背景一致），还是保持纯工具执行者身份（最小上下文、最省 token）。

**结果契约 — `SubAgentResult` dataclass。** 字段：`task`（原始任务描述）、`output`（成功时为最终答案，失败时为错误信息）、`success`（bool）、`iterations`（实际迭代次数）。异常在 `SubAgent.run()` 内部捕获并转换为 `success=False` 的结果，绝不向外抛——这是“单失败不阻塞”的保障。

**实现位置 — `agent/sub.py`。** `SubAgent` 类 + 模块级 `run_parallel(agents, tasks)` 函数。`agents[i]` 执行 `tasks[i]`，两者长度必须一致（`zip(..., strict=True)`）。

## Cross-Story Dependencies

- Story 5.1 → 5.2：并行编排依赖子 Agent 生成已就绪。
- 依赖 Epic 2（AgentLoop、ToolRegistry、SafetyGuard）与 Epic 1（BaseProvider）作为构造前提。
- 与 Epic 6（AgentLoop 全模块集成）耦合：父 AgentLoop 集成 SOUL/skills/facts/profile/context 后，需明确这些模块是否、如何下传给子 Agent（见上方“待定”项）。
