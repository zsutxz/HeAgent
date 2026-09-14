---
title: '运行时持久化与死代码治理'
type: 'refactor'
created: '2026-09-02'
status: 'done'
baseline_commit: '920d4be9f1d129906c083599e51b5ea2498a8d9d'
review_loop_iteration: 0
context:
  - 'AGENTS.md'
  - 'docs/frame.md'
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** Agent 的异步运行路径仍会直接执行文件读取和会话写入；部分读改写操作没有覆盖整个临界区的跨进程锁。另有两个只被测试消费的工作流状态机，以及 GUI 可选依赖导入会吞掉内部导入错误。

**Approach:** 保留现有存储的同步公共 API，以兼容直接消费者；在异步编排边界转入线程。为需要读改写的存储提供完整持锁更新，并移除没有产品调用方的重复状态机。GUI 只将真正缺少 Textual 识别为可选依赖缺失。

## Boundaries & Constraints

**Always:** 复用 `engine.persist` 原子写入语义；不改变 Markdown/JSON 文件格式、工具返回文本或现有 Provider 行为；保留显性错误。

**Ask First:** 删除任何存在产品调用方或对外导出的 API；变更默认文件路径或持久化格式。

**Never:** 把安全声明或 Policy/SafetyGuard 当成安全边界；通过吞掉异常或放宽测试来使校验通过；修改用户现有的未提交 Provider/FactStore 精简。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 并发事实写入 | 两个 worker 同时写同一 MEMORY.md | 两条不同事实均保留，重复事实只保留一条 | 锁超时显性抛出 OSError |
| 并发会话保存 | 两个 worker 保存同一 session | 每次写入为完整 JSON，版本在锁内递增 | I/O 错误由既有调用链显性处理 |
| GUI 缺少可选依赖 | Textual 未安装 | 输出安装指引并退出 1 | 仅模块缺失可转换为指引 |
| GUI 内部导入失败 | Textual 已安装但 GUI 自身模块报错 | 原始 ImportError 可见 | 不伪装为依赖未安装 |

</frozen-after-approval>

## Code Map

- `src/heagent/engine/persist.py` -- 原子写和跨进程锁的唯一实现；新增完整读改写原语而不复制平台锁逻辑。
- `src/heagent/memory/facts.py` -- 事实去重的读改写调用方；使用持锁更新。
- `src/heagent/context/session.py` -- 会话版本递增的读改写调用方；使用持锁更新。
- `src/heagent/memory/profile.py` -- 分节更新的读改写调用方；使用持锁更新。
- `src/heagent/agent/system_prompt.py`、`src/heagent/agent/loop.py` -- 保持同步构建函数，主循环经线程调用。
- `src/heagent/gui/cli.py`、`src/heagent/cli.py` -- 区分可选 GUI 依赖缺失和内部导入错误。
- `src/heagent/memory/skill_packages.py`、`src/heagent/engine/agile.py` -- 经全仓搜索确认仅测试使用的重复状态机，待移除。
- `tests/test_file_locking.py`、`tests/test_session.py`、`tests/test_memory.py` -- 锁、会话与事实回归覆盖。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/engine/persist.py` -- 提供复用现有平台锁的原子读改写入口。
- [x] `src/heagent/memory/facts.py`, `context/session.py`, `memory/profile.py` -- 将读改写持锁并保持文件格式。
- [x] `src/heagent/agent/system_prompt.py`, `agent/loop.py` -- 在异步 Agent 路径把同步系统提示词构建移入线程。
- [x] `src/heagent/gui/cli.py`, `src/heagent/cli.py` -- 只处理缺少可选 GUI 模块的 ImportError。
- [x] `src/heagent/memory/skill_packages.py`, `src/heagent/engine/agile.py` 及仅对应测试 -- 删除无产品消费者的重复状态机。
- [x] `tests/` -- 完成持锁、持久化和工作流恢复回归；GUI 缺少 Textual 的分支由导入守卫覆盖。

**Acceptance Criteria:**
- Given 并发事实或会话写入, when 操作同一文件, then 每个完成写入都保持完整格式且锁覆盖读取到替换。
- Given Agent 构建系统提示词或保存会话, when 文件 I/O 缓慢, then 主事件循环不直接执行该同步 I/O。
- Given GUI 运行时缺少 Textual, when 执行 `heagent gui`, then 显示依赖指引；Given 内部导入失败, then 原始异常未被吞掉。
- Given 全仓产品引用搜索, when 清理重复状态机, then 没有生产模块依赖被删除的符号。

## Design Notes

同步 Store API 继续服务 GUI 和测试；异步调用方自行使用 `asyncio.to_thread`。这样避免无关 API 破坏，同时确保 Agent 主循环不阻塞。锁文件继续保留，避免删除锁文件导致 inode 竞争。

## Verification

**Commands:**
- `ruff check src tests` -- expected: 无 lint 错误。
- `pytest tests/test_file_locking.py tests/test_session.py tests/test_memory.py -q` -- expected: 持锁读改写与格式回归通过。
- `pytest tests/test_cli.py tests/test_gui*.py -q` -- expected: GUI 导入路径回归通过。
- `pytest -q`（工作区 TMP/TEMP） -- expected: 所有可创建夹具的测试通过；现有 ACL 错误单独报告。

## Suggested Review Order

**异步边界与持久化**

- Agent 主循环将同步存储移出事件循环
  [`loop.py:654`](../../../../src/heagent/agent/loop.py#L654)

- 统一读改写锁，避免并发覆盖
  [`persist.py:164`](../../../../src/heagent/engine/persist.py#L164)

- 会话版本在锁内递增
  [`session.py:40`](../../../../src/heagent/context/session.py#L40)

**架构精简与错误边界**

- 删除无生产消费者的重复状态机
  [`skill_packages.py:619`](../../../../src/heagent/memory/skill_packages.py#L619)

- GUI 仅转换缺失 Textual 错误
  [`gui.py:18`](../../../../src/heagent/gui/cli.py#L18)

**回归验证**

- 工作流恢复测试保留核心契约
  [`test_goal_epic_story_smoke.py:109`](../../../../tests/test_goal_epic_story_smoke.py#L109)
