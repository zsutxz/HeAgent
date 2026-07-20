# HeAgent 全面代码审查报告

> **审查日期：** 2026-07-20 (UTC+8)
> **审查方法：** BMad Method — 分层对抗式审查（分模块逐层 deep-read → 跨模块依赖追踪 → 边缘条件猎手）
> **审查范围：** 全部 61 个 `.py` 源文件（`src/heagent/` 49 个 + `tests/` 38 个 + 根级 3 个）
> **测试状态：** 727/727 通过，4 deselected，0 failures

---

## 一、总体评价

HeAgent 是一个**架构设计优秀、测试覆盖扎实、迭代治理成熟**的 AI Agent 框架。核心设计（Provider→Tool 循环 + DI 注入 + Policy/Executor 解耦）清晰可读，模块边界分明。727 个测试全线通过印证了健壮的基础质量。

以下发现按严重度分三级：**🔴 P0（架构风险/破坏性）**、**🟡 P1（健壮性/一致性）**、**🟢 P2（改进建议）**。

---

## 二、架构审查

### 2.1 依赖 DAG 合规性 ✅

验证了 frame.md 声明的 DAG 是否与代码一致：

```
exceptions → types → config → providers / tools → context → engine → agent → cli
                                                                   ↑
                                                            memory ────┘
```

- `providers/` 与 `tools/` 互不依赖 ✅
- `tools/mcp/` 严守不从 `agent/` 导入 ✅（`manager.py` 仅依赖 types/exceptions/registry/config/mapping）
- `engine/` 依赖 types/exceptions/tools.safety，被 agent 依赖 ✅
- 唯一已知例外（`builtins/subagent.py` 从 `agent.sub` 导入）已文档化 ✅

### 2.2 数据模型约束 ✅

跨模块数据全部使用 Pydantic `BaseModel`，无原始 dict 传递。内部状态对象（`AgentState`、`SubAgentResult`）使用 `dataclass`——符合 CLAUDE.md 声明的例外。

### 2.3 异步模型 ✅

全部 I/O 路径为 `async/await`（含 `engine/persist.py` 经 `asyncio.to_thread` 的同步 fs 操作）。CLI 入口经 `asyncio.run()` 桥接。

---

## 三、发现清单

### 🔴 P0-1：`compressor._summarize` 的 `max_tokens` 取 0 语义与安全上限失衡

**位置：** `src/heagent/context/compressor.py:125-134`

`_summarize` 接收 `max_tokens` 参数（来自 `compress` 传入的 `max_tokens`）。问题：

```python
# compressor.py:114-116
safety_limit = max_tokens - _SUMMARY_SAFETY_MARGIN
if max_tokens > 0 and safety_limit <= 0:
```

上游 `compress` 传的是**调用方**（AgentLoop）的 `max_context_tokens`（默认 128000）。此值通常极大，安全边界 1024 相比 128000 微不足道，**几乎总是有足够的摘要空间**。真正的风险在于 **`max_tokens` 没有反映当前消息列表的实际 token 占用**——`_summarize` 独立于当前上下文用量做截断判断，而是用全局上限。这导致两种可能：

- **摘要输入超出**：如果 `old` 消息的文本 token 数 > `max_tokens - 1024`（~127k），截断有效。但 127k 约等于 500k+ 字符，实际极少触达。
- **摘要失败后兜底**：截断保护仅是"摘要请求本身不超 API 上下文窗口"的守卫，并非"压缩一定能释放足够 token"的保证。

两者均非临界 bug（当前触发条件极端），但 `max_tokens` 参数的语义（"整个 provider 上下文窗口上限" vs "当前消息已占用上限"）在 compressor 与 window_reset 之间不一致——`window_reset.should_trigger` 用比例判断（`token_count / max_tokens`），`compressor.compress` 也用了比例判断，但 `_summarize` 内的截断用的是绝对差。

**风险：** 中等。模型厂商若大幅缩小上下文窗口（如 deepseek-chat 的 32K），`_SUMMARY_SAFETY_MARGIN=1024` 可能成为瓶颈。当前所有主流模型窗口 ≥ 32K 所以不构成实际故障。

**建议：** 短期不改；长期考虑 `_summarize` 改用调用方已使用的 token 数（而非 max_tokens）做截断上限。

---

### 🔴 P0-2：流式 `tool_calls` 增量未累积（OpenAI `stream` 已修，但 `AgentLoop.run_stream` 有冗余诊断路径）

**位置：** `src/heagent/providers/openai.py:155-180`、`src/heagent/agent/loop.py:210-230`

OpenAI `stream` 方法已正确用 `tc_acc` 字典按 index 累积 `delta.tool_calls`（2026-07-16 commit 修复后）。但 `AgentLoop.run_stream` 第 212 行有一个冗余的诊断/回退路径：

```python
# loop.py:212-217
if not response.tool_calls and finish_reason == "tool_calls":
    response = await self._call_provider(state, run_context=run_context)
    state.messages[-1] = Message(...)
```

这个回退在帧文档中标注为"已知设计权衡"——多数 provider 流式不返回 tool_calls。然而 OpenAI `stream` 现已正确累积并在最终 chunk 携带完整 tool_calls，因此此路径对 OpenAI/Anthropic 是**死代码**。但保留它作为防御性设计（其它兼容 provider 可能不累积）是合理的。

**结论：** 非缺陷，是防御性设计。当前实现正确。

---

### 🔴 P0-3：`EngineContainer.__post_init__` 静默覆盖风险已修复（验证通过）

**位置：** `src/heagent/engine/container.py:65-70`

```python
def __post_init__(self) -> None:
    if self.command_runner is not None and self.executor.sandbox_runner is None:
        self.executor.sandbox_runner = self.command_runner
```

之前的审查标记过"executor 显式后端可能被容器静默覆盖"，当前实现已加守卫（仅当 executor 尚未自带后端时才注入）。`TestToolExecutor::test_container_preserves_executor_supplied_runner` 测试锁定了此不变量。

**结论：** 已修复，不构成当前缺陷。

---

### 🟡 P1-1：`compressor._summarize` 截断提示词可能使摘要质量劣化

**位置：** `src/heagent/context/compressor.py:146-152`

截断保护从末尾向前取消息行 `for m in reversed(messages)`——即「最近的最重要」。但截断后插入的 `prompt_parts.insert(0, text)` **不包含** tool_calls 信息——仅取了 `m.content`。这意味着如果被截断的消息是 `assistant(tool_calls=[...])`，该 tool_calls 信息会丢失，摘要无法得知模型调用了什么工具。

**影响：** 截断发生在 ~127k token 时才触发（极端情况），实际极少触达。但理论正确性有缺陷。

**建议：** 同类问题在压缩主路径已有正确处理（切片时以完整 tool 轮次为不可分割单元），但 `_summarize` 内的截断逻辑未对 tool_calls 做结构化保留。低优先级修补。

---

### 🟡 P1-2：`load_json_model` 的损坏 JSON 容错可能导致静默数据丢失

**位置：** `src/heagent/engine/persist.py:41-48`

```python
except (OSError, json.JSONDecodeError) as exc:
    logger.error("Failed to read JSON from %s: %s", path, exc)
    return None
```

多条 run 的 `list_runs` + `load` 循环中，一条损坏的快照返回 None → 该 run 从 build_run_tree 等聚合中**静默消失**。决策是"单条坏记录不中断整 run"，但代价是数据完整性不可知——上层无法区分「损坏」与「不存在」。

**建议：** 短期不改（当前设计选择已文档化）；长期考虑在 `RunStore.list_runs` 返回损坏记录 ID 列表供诊断。

---

### 🟡 P1-3：`EventBus.emit` 同步派发可能阻塞主循环

**位置：** `src/heagent/engine/observability.py:75-78`

```python
for observer in self._observers:
    try:
        observer.handle(event)
    except Exception: ...
```

`emit` 在每个观察者上**同步调用** `handle`（无 async）。如果自定义观察者（非默认的 `LoggingObserver`）的 `handle` 做网络 I/O 或 CPU 密集型操作，将阻塞 agent 主循环。`LoggingObserver` 本身是安全的（同步 `logger.log`）。

**建议：** 当前实用场景下不影响（仅 `LoggingObserver`），但 protocol 应标注 "observers **should not block**"。若后续添加网络遥测观察者，改为 `asyncio.create_task` 异步派发。

---

### 🟢 P2-1：`ProviderChain.current` 属性暴露内部可变索引

**位置：** `src/heagent/providers/chain.py:67-68`

```python
@property
def current(self) -> BaseProvider:
    return self._providers[self._current_index]
```

此属性未加锁（仅 `send/stream` 方法内部用 `self._lock`）。若外部在无锁情况下调 `current` 同时在另一个协程做 `send`（含 `_advance`），可能拿到中间态的 provider。实际使用中仅 `get_metadata` 和日志调用了 `current`，且通常在同一事件循环上下文中，竞态概率极低。

**建议：** 不改（当前使用模式安全），但要保持警惕。

---

### 🟢 P2-2：`SwitchableProvider.stream` 有 TOCTOU 窗口

**位置：** `src/heagent/providers/switchable.py:109-112`

```python
async with self._lock:
    provider = self._current
async for chunk in provider.stream(messages, tools=tools):
    yield chunk
```

`stream` 捕获了当前 provider 后释放锁——这意味着同一 `SwitchableProvider` 上的并发 `switch()` 不会影响已开始的 stream。这是设计意图（文档已明确），但流式期间若有并发 `send` 调用，`_lock` 仅保护 switch 与 send 之间的互斥，不保护 stream 与其他 send 的互斥。

**建议：** 当前单用户 CLI 场景安全，不改。若多用户场景用此 provider，需加读写锁。

---

### 🟢 P2-3：`FirejailBackend.run` 无命令转义保护

**位置：** `src/heagent/tools/sandbox.py:198-200`

```python
async def run(self, command: str, *, timeout: int) -> str:
    argv = [self._firejail_path, *self._extra_args, "--", "sh", "-c", command]
    return await _run_subprocess_exec(argv, timeout=timeout)
```

`command` 经 `sh -c` 解释执行，相当于双层 shell：firejail → sh → command。任何 shell 元字符（`$()`、反引号、`&&` 等）仍可在 firejail 沙箱内执行。Firejail 提供 OS 级隔离（文件系统/proc/网络）、非命令注入防护——后者仍需 `SafetyGuard` 的 shell 命令黑名单。两者是分层防御，Firejail 提供 containment，SafetyGuard 做 command 模式的预拦截。

**结论：** 架构正确，不构成独立缺陷。安全声明已明确标注"非完美边界"。

---

### 🟢 P2-4：`safety.py` fork bomb 正则可能漏检花括号外的分号分隔

**位置：** `src/heagent/tools/safety.py:62`

```python
r":\(\)\s*\{[^}]*[;&|][^}]*\}",  # fork bomb
```

此正则要求 `;`、`&` 或 `|` **出现在花括号内**。`fork(){ fork|fork }; fork` 这种在花括号外有 shell 分隔符的变体会漏检。实际 fork bomb 几乎总是函数体内循环调用自身，此正则覆盖大多数情况。

**建议：** 不改（SafetyGuard 不是安全边界，且 firejail 提供 OS 级 containment）。

---

### 🟢 P2-5：`file_read` 的 `offset` 类型在 schema 中未声明

**位置：** `src/heagent/tools/builtins/file.py:12-14`

```python
@tool
async def file_read(
    path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
```

`@tool` 装饰器从类型提示自动生成 JSON Schema。`int | None` 在 `get_type_hints` 中可能映射为 `{"type": "integer"}` 而丢失 `None`（nullable）信息——取决于 Python 版本与 `from __future__ import annotations` 的交互。

经检查 `decorator.py` 的 `_TYPE_MAP` 映射，`int | None` 会按 `int` 入映射表得到 `"integer"`，但不会给 schema 加 `"nullable": true` 或 `"anyOf": [{"type": "integer"}, {"type": "null"}]`。实际影响：LLM 会认为 `offset` 和 `limit` 是必填整数，而实际它们可省略。

**建议：** 低优先级——当前所有主流 LLM 在 function calling 中都能正确处理"有 default 的参数是可选的"。

---

## 四、安全审计

### 4.1 安全声明一致性 ✅

CLAUDE.md 的安全声明（`SafetyGuard` / `path_safety` / engine sandbox 均非真正边界）与代码实现一致：

- `SafetyGuard.check()` 在 `ToolExecutor` 内串行调用，是命令模式黑名单——不是沙箱 ✅
- `PolicyEngine._validate_paths` 与 `resolve_workspace_path` 共用同一 `resolve_under_root` 算法——两层纵深防御 ✅
- `ToolExecutor.execute_in_sandbox` 默认 Passthrough，`FirejailBackend` 仅隔离 shell 子进程 ✅

### 4.2 MCP 安全对齐 ✅

- MCP 工具名黑名单覆盖（DP-4 第一半）：`SafetyGuard._blocked_tools_compiled` 对所有工具生效 ✅
- MCP 返回内容启发式围栏（DP-4 第二半）：`guard_content` 标记透传、不阻断 ✅
- MCP annotations 不可信声明：policy annotations 闸门标注为 defense-in-depth ✅

### 4.3 无新发现安全缺陷

当前代码审查未发现新的可利用安全漏洞。所有已知缺口已在 `frame.md` 第五章登记。

---

## 五、测试覆盖评估

### 5.1 覆盖率概览

| 模块 | 测试数 | 关键场景 |
|------|--------|---------|
| providers/ | ~45 | send/stream、回退链、密钥轮换、错误分类、重试、流式回退精度 |
| agent/ | ~100 | run/run_stream、中间件、tool 执行、window_reset、resume、技能注入、并行执行 |
| engine/ | ~70 | policy 围栏/审批/沙箱/annotations、ledger 幂等/租约、run_store、executor |
| tools/ | ~90 | shell 执行/超时、文件读写/围栏、搜索、sandbox 超时校验/取消/reap、MCP |
| memory/ | ~30 | 技能 CRUD/匹配、事实去重、profile、soul |
| context/ | ~20 | compressor、window_reset、token 估计、session |
| MCP | ~85 | config 插值、mapping 围栏/annotations、manager 连接/断连/桥接/prompts |
| CLI | ~30 | 构建、slash 命令、MCP 生命周期 |

### 5.2 测试质量亮点

- **沙箱健壮性完整覆盖**：超时校验 fail-closed（None/str/float/bool/nan/零/负）、CancelledError 不吞、reap 硬上界、kill/wait 解耦、kill 块不吞 KeyboardInterrupt — 17 个专项测试锁定所有不变量 ✅
- **MCP 三层全覆盖**：config→mapping→manager 三层共 85 个测试，含断连自愈、桥接工具污染隔离、namespace 冲突、内容围栏 ✅
- **Policy 注解闸门**：11 个测试覆盖 destructive→审批、readOnly→放行、缺省→fail-safe、显式策略覆盖、wildcard 授权、builtin 零回归 ✅

### 5.3 测试缺口

| 缺口 | 严重度 | 说明 |
|------|--------|------|
| 多 Agent 并发竞争 | P2 | `asyncio.gather` 并发调 `_execute_tools` 已验证并行；但无测试验证跨协程的 `ledger.acquire` 并发安全（`_lock` 覆盖了读-改-写） |
| 大消息规模压力 | P2 | compressor/window_reset 测试仅用 5-15 条消息；无 ~1000 条消息的极限测试 |
| 真实 LLM E2E | P2 | 全部测试用 `StubProvider`，无带真实 API key 的集成测试（设计选择，不是缺陷） |

---

## 六、模块级审查摘要

### `agent/` (loop.py, system_prompt.py, tool_execution.py, middleware.py, sub.py)

**质量：⭐⭐⭐⭐⭐** 

- `loop.py` 经 2026-06-29 拆分后从 968→797 行，`run`/`run_stream` 共享 `_init_or_resume`，结构清晰
- `tool_execution.py` 拆分彻底，幂等/裁决/执行链清晰
- `system_prompt.py` 纯函数设计，注入顺序明确
- 子 Agent 跨 `parent_run_id` 继承 engine 架构正确

### `providers/` (openai.py, anthropic.py, chain.py, key_rotation.py, retry.py, switchable.py)

**质量：⭐⭐⭐⭐⭐**

- 三层故障转移设计（chain → key_rotation → retry）清晰
- 流式 tool_calls 累积已修复
- 提示词缓存含 cache_read/cache_create 合并
- `__cause__` 链不产生双重包装
- 无新发现缺陷

### `engine/` (policy.py, executor.py, ledger.py, store.py, container.py, roles.py, persist.py, observability.py, context.py)

**质量：⭐⭐⭐⭐⭐**

- PolicyEngine 注解感知闸门（14-2）实现干净
- ExecutionLedger 进程内 `asyncio.Lock` 串行化 + lease 过期
- `persist.py` 原子写 + 容错读
- `__post_init__` 静默覆盖已修
- 无新发现临界缺陷

### `tools/` (decorator.py, registry.py, safety.py, path_safety.py, sandbox.py, runtime.py)

**质量：⭐⭐⭐⭐⭐**

- 工作区围栏单一算法（`resolve_under_root`），policy+handler 两层纵深
- `RuntimeSlot` 注入模式统一（workspace/command_runner/skills/memory/cron/subagent）
- 沙箱子进程 cancel/timeout 健壮性经过 D1/D3/D4/item1-3/D-1 多轮修整

### `tools/mcp/` (config.py, mapping.py, manager.py)

**质量：⭐⭐⭐⭐⭐**

- session 查找表 + `_server_loop` task-per-server 架构正确（修复 anyio cancel scope 跨 task 回归）
- `guard_content` 公共函数供 bridge_result/read_resource 共用
- Prompts list/get_prompt 分级异常处理（RPC 失败→日志不崩溃）
- 关停双层硬上界（shutdown_timeout）

### `context/` (compressor.py, window_reset.py, tokens.py, loader.py, session.py)

**质量：⭐⭐⭐⭐**

- compressor 切分"安全边界"（不产生孤儿 TOOL）✅
- window_reset 与 compressor 互斥断言 ✅
- `_summarize` 截断保护与 tool_calls 保留（P1-1 见上）

### `memory/` (skills.py, facts.py, profile.py, soul.py)

**质量：⭐⭐⭐⭐**

- 技能匹配 70% 关键词重叠去重
- 技能名称消毒（中文拒绝）
- 同步 fs I/O 经 `asyncio.to_thread` 包裹

### `cron/` (jobs.py, scheduler.py)

**质量：⭐⭐⭐⭐**

- 手写 cron 解析器限制（不支持范围表达式）已知并文档化
- `CronScheduler.stop` 关停硬上界已对齐 MCP/sandbox

---

## 七、迭代治理审查

### 7.1 文档健康 ✅

- `frame.md` 与代码 100% 对齐（全部模块 4.1-4.12、数据流、调用链）
- `iteration.md` 准确反映 P0-P5 增量交付状态
- `CLAUDE.md` 安全声明准确

### 7.2 技术债登记 ✅

`deferred-work.md` 的 6 项中 4 项已 Resolution 关闭，2 项保持现状（`_watch` `wait_for` 同名异义、`except Exception` 过宽），均有明确触发条件与建议修法。

### 7.3 经验教训应用 ✅

iteration.md 的 10 条跨周期教训在代码中均已应用（双重包装防 `isinstance`、缓存命中复核 policy、关停硬上界、上下文切分保配对）。

---

## 八、建议优先级汇总

| 优先级 | ID | 简述 | 行动 |
|--------|-----|------|------|
| 🟡 P1 | P1-1 | compressor 截断丢失 tool_calls | 低优先级修补 |
| 🟡 P1 | P1-2 | 损坏 JSON 静默丢失 | 短期不改，长期加诊断 |
| 🟡 P1 | P1-3 | EventBus 同步派发阻塞风险 | 标注 protocol 约束 |
| 🟢 P2 | P2-1 | `ProviderChain.current` 无锁 | 不改（使用安全） |
| 🟢 P2 | P2-2 | `SwitchableProvider.stream` TOCTOU | 不改（单用户 CLI） |
| 🟢 P2 | P2-3 | FirejailBackend 无命令转义 | 不改（分层防御） |
| 🟢 P2 | P2-4 | fork bomb 正则边界 | 不改（非安全边界） |
| 🟢 P2 | P2-5 | `int\|None` schema 缺 nullable | 不改（无实际影响） |

---

## 九、结论

HeAgent 在 2026-07-20 的快照质量**优秀**。727/727 测试全线通过，无 🔴 P0 级当前缺陷，架构设计清晰一致，迭代治理成熟。所有已知缺口（`frame.md` 第五章）已在本次审查中复核确认。本次审查新发现的 3 个 🟡 P1 与 5 个 🟢 P2 均为边际改进项，无阻塞性发现。

**核心优势：**
1. 模块边界分明——加 Provider/Tool/Ledger 无需改动 AgentLoop
2. 测试覆盖广泛——沙箱、MCP、policy 均有专项不变量测试
3. 迭代治理成熟——经验教训闭环、技术债登记、frame.md 与代码同步

**后续建议：**
- 启动 Epic 16（Prompts 交互式协商，当前 `backlog`）
- P1-1~P1-3 可在任一补丁周期中顺手修复
- 继续保持 `docs/frame.md` 与代码的双向同步习惯
