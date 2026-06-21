---
title: 'SubAgent 上下文注入 — 继承父级人格/记忆/技能/上下文'
type: 'bugfix'
created: '2026-06-17'
status: 'done'
baseline_commit: '2739274a5a3db1584bfbab51ca5fdbec500fd554'
context: ['{project-root}/docs/_bmad-output/implementation-artifacts/epic-5-context.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** SubAgent（`agent/sub.py:60`）用裸 AgentLoop 构造，只转发 provider/registry/guard/max_iterations，丢失父级的 soul/skills/facts/profile/compressor/context_dir。子 Agent 看不到人格、记忆、技能、项目上下文文件，也不压缩自身上下文——委派任务与主 Agent 人格/知识割裂，违背 epic-5 "子 Agent 继承父级工具集" 的一致性意图。

**Approach:** 给 SubAgent 和 configure_subagent_tools 增加 soul/skills/facts/profile/compressor/context_dir 六个可选参数，run() 创建子 AgentLoop 时转发它们；工具层 task_delegate/task_parallel 构造 SubAgent 时一并传入；cli.py 调用处补传。保持对话历史隔离（不继承 session）。

## Boundaries & Constraints

**Always:** 子 AgentLoop 的 messages 必须空起步（隔离对话历史——SubAgent 核心设计）；继承 soul/skills/facts/profile/compressor/context_dir；这些组件用于系统提示词注入（只读语义）；匹配 AgentLoop 既有显式注入风格，不引入 parent_loop 引用耦合；保持向后兼容（组件全 None 时行为同现状）。

**Ask First:** 是否继承 profile（用户画像）—— 默认包含，与 facts 同属 identity 层；是否继承 cron_store —— 默认不继承（子 Agent 临时性，cron 不在诉求内）。

**Never:** 不继承 session（会污染父级 `.heagent/sessions/` 持久化）；不继承 middlewares；不解决并行子 Agent 共享 store 写并发竞态（既有问题，超出范围，只读注入保证安全）；不改变 SubAgent 既有的 (provider, registry, guard) 公共构造语义。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| 委派任务时子 Agent 继承人格/记忆 | 父 loop 配置 soul+facts+skills | 子 loop 系统提示词含 SOUL/facts/skills 内容 | N/A |
| 并行子 Agent 历史隔离 | run_parallel 2 个任务 | 每个子 loop messages 独立、互不影响 | N/A |
| 向后兼容（裸构造） | 所有上下文组件为 None | 子 loop 行为与现状一致 | N/A |

</frozen-after-approval>

## Code Map

- `src/heagent/agent/sub.py` -- SubAgent：增加上下文参数并在 run() 转发到子 AgentLoop
- `src/heagent/tools/builtins/subagent.py` -- configure_subagent_tools 增加上下文参数存为模块级；task_delegate/task_parallel 传入 SubAgent
- `src/heagent/cli.py` -- `_run_single`(:181) 与 `_run_chat`(:234) 调用 configure_subagent_tools 处补传父级组件
- `tests/test_sub_agent.py` -- 验证子 loop 继承上下文且 messages 隔离
- `tests/test_subagent_tools.py` -- 验证工具层注入路径

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/agent/sub.py` -- SubAgent.__init__ 增加 skills/facts/profile/compressor/context_dir/soul 可选参数并存储；run() 创建子 AgentLoop 时转发 -- 让子 Agent 继承父级上下文
- [x] `src/heagent/tools/builtins/subagent.py` -- configure_subagent_tools 增加同名可选参数存为模块级变量；task_delegate/task_parallel 构造 SubAgent 时传入 -- 打通工具层注入
- [x] `src/heagent/cli.py` -- 两处 configure_subagent_tools(...) 调用补传 skills/facts/profile/compressor/context_dir/soul -- 真实运行时生效
- [x] `tests/test_sub_agent.py` -- 新增测试：子 loop 继承 soul/facts 等组件，且 messages 为空（隔离）；裸构造向后兼容 -- TDD 捕获意图

**Acceptance Criteria:**
- Given 父 AgentLoop 配置了 soul+facts+skills，when SubAgent.run() 执行，then 子 AgentLoop 系统提示词含 SOUL 与 facts 内容，且子 loop messages 不含父级历史。
- Given 未配置任何上下文组件，when 构造 SubAgent 并 run()，then 行为与现状一致（现有测试不破坏）。

## Design Notes

context 组件的注入本质是"只读"——它们参与子 loop 的 `_build_system()` 系统提示词组装，不写入。写并发风险（并行子 Agent 调用 fact_add 等写工具）是既有问题，本次不解决，仅通过只读注入保证安全。不继承 session 以避免污染父级会话持久化。cli.py 两处调用点组件已是局部变量，直接透传即可。

## Verification

**Commands:**
- `pytest tests/test_sub_agent.py tests/test_subagent_tools.py -v` -- expected: 全绿
- `pytest` -- expected: 全量通过，无回归
- `ruff check src tests` -- expected: 无错误
- `mypy src` -- expected: 无新错误

## Suggested Review Order

**上下文注入核心（设计意图入口）**

- 设计意图起点：SubAgent 新增 6 个上下文参数并存储
  [`sub.py:54`](../../src/heagent/agent/sub.py#L54)
- 关键转发：run() 把组件传入全新子 AgentLoop（messages 空起步）
  [`sub.py:88`](../../src/heagent/agent/sub.py#L88)

**工具层注入**

- configure_subagent_tools 接收并暂存 6 个组件
  [`subagent.py:40`](../../src/heagent/tools/builtins/subagent.py#L40)
- task_delegate 构造 SubAgent 时传入
  [`subagent.py:92`](../../src/heagent/tools/builtins/subagent.py#L92)
- task_parallel 每个子 Agent 同样传入
  [`subagent.py:125`](../../src/heagent/tools/builtins/subagent.py#L125)

**CLI 接线**

- _run_single 调用处补传父级组件
  [`cli.py:181`](../../src/heagent/cli.py#L181)
- _run_chat 调用处补传父级组件
  [`cli.py:242`](../../src/heagent/cli.py#L242)

**测试（外围）**

- 继承 + 隔离 + 向后兼容三类断言
  [`test_sub_agent.py:60`](../../tests/test_sub_agent.py#L60)
- 工具层注入路径验证
  [`test_subagent_tools.py:122`](../../tests/test_subagent_tools.py#L122)
