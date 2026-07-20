# 全代码库审查报告 — HeAgent

**审查日期**: 2026-07-20
**审查范围**: `src/heagent/` 全量（8,834 行 / 7 模块 / 65 源文件）+ `tests/`
**方法**: 6 个专项 agent 并行（security-reviewer ×2 负责 tools 核心 + mcp；python-reviewer ×4 负责 engine/agent/providers/支撑模块）+ ruff/mypy/pytest 基线
**立场校准**: SafetyGuard / path_safety / engine sandbox / MCP 全部为 CLAUDE.md 已声明的「非真正安全边界」——相关发现按 defense-in-depth 缺口处理，不拔高为安全漏洞。

---

## 0. 基线校验（事实）

| 检查 | 结果 | 说明 |
|---|---|---|
| ruff check | ❌ 17 errors | 全部为 `F811`：`tests/test_mcp_manager.py` 重复定义的测试函数（合并 commit 4d71136 残留：898/1311、908/1321、924/1337…） |
| mypy src | ❌ 1 error | `providers/openai.py:228` `arguments: object` 与 `dict[str, object]` 不兼容 |
| pytest | ❌ 2 failed / 715 passed | `test_stream_yields_chunks`（openai mock 漂移）、`test_summary_content_used`（compressor safety_margin=1024 > max_tokens=100 触发 fallback） |

## 模块健康度

| 模块 | 健康度 | 一句话 |
|---|---|---|
| tools 核心（builtins+safety+sandbox） | 中 | 路径围栏/SSRF/沙箱收尾设计扎实；builtins 层系统性同步 I/O + git 无 timeout |
| tools/mcp | 中 | 生命周期/断连 unregister/硬上界扎实；guard_content 三个入口有覆盖缺口 |
| engine | 中 | 硬约束全合规、工具链顺序正确；ledger.acquire TOCTOU + policy fail-safe 第四情形缺口 |
| agent | 中 | 依赖注入一致、best-effort 边界注释充分；SessionStore 同步 I/O + 参数列表三处漂移 |
| providers | 中 | 三层容错设计清晰、流式三件套正确；403 分类/并发锁/AsyncStream 资源管理三处 HIGH |
| 支撑（context/memory/cron/top） | 中 | ruff/mypy 绿；同步 I/O 进库 + SkillContent dataclass + cron 反向依赖三条硬约束违反 |

---

## 1. CRITICAL — 架构硬约束系统性违反

> 按 CLAUDE.md「硬约束（违反即架构错误）」判定。这三类是**全栈性**问题，单点修不完，需统一收敛。

### C-1. 库代码系统性同步 I/O（违反「库代码全异步无同步 I/O」）

**覆盖**（同一根因，跨 4 个 agent 独立发现）：
- `tools/builtins/`: file.py:33,38,82,83 · search.py:40,71,79 · memory.py:65,77 · skills.py:62-156 · cron.py:56-86
- `memory/`: facts.py · profile.py · skills.py · soul.py（store 全同步）
- `context/`: loader.py · session.py:38-53（SessionStore）
- `cron/jobs.py`（_load_all/_save_all 全同步）
- 调用方在 async 函数里裸调：`agent/system_prompt.py:52/71/82/107/124`、`agent/loop.py:474,506`、`cli.py:249`

**影响**: 大文件/慢盘/`rglob`/`shutil.rmtree` 阻塞事件循环，冻结整个 agent（同批工具、cron tick、MCP watch、取消传播全卡死）；并发 agent loop 下实际触发。

**建议**: 本仓已有正确范式——`engine/store.py:114-168` 与 `engine/ledger.py:155-173` 用 `asyncio.to_thread`。把所有 store 方法改 async 并 `await asyncio.to_thread(...)` 包裹底层 fs 调用，与 engine 子模块对齐收敛。

### C-2. `SkillContent` 用 `@dataclass`（违反「数据模型一律 Pydantic BaseModel」）

- `memory/skills.py:25`

**影响**: CLAUDE.md 明示例外仅 `AgentState`/`SubAgentResult`；dataclass 绕过 Pydantic 校验/序列化。
**建议**: 改 `class SkillContent(BaseModel)`，`field(default_factory=list)` → `Field(default_factory=list)`。

### C-3. cron 反向依赖 agent（违反 DAG 硬约束）

- `cron/scheduler.py:131` `from heagent.agent.loop import AgentLoop`（lazy import）

**影响**: DAG 上 cron 应被 agent 依赖，不该反向；掩盖架构方向错误，测试隔离困难。
**建议**: agent 层注入 `JobRunner` 协议（callable），cli.py 把 `AgentLoop.run` 传入 scheduler，cron 仅依赖协议类型。

---

## 2. HIGH — 真实正确性 / 并发 / 容错缺陷

### 并发与状态一致性

- **H-1. `engine/ledger.py:78-116` `acquire()` TOCTOU 竞态** — get→判定→_save 无文件锁，两个并发 acquire 同 key 可同时通过、后写覆盖前写，**租约互斥语义失效**（重复执行仍可能发生）。建议 `_save` 前 `fcntl.flock`/`msvcrt.locking` 或 `os.open(O_CREAT|O_EXCL)` 原子创建独占文件。

- **H-2. `providers/chain.py:51,89` + `key_rotation.py:42,81` 共享 `_current_index` 无 `asyncio.Lock`** — 并发 `send`/`stream` 在 await 点交错相互覆盖索引，回退与轮换状态漂移。建议两类各持一把 `asyncio.Lock`，全程临界区执行；或工厂侧每次 new + 文档化非并发安全。

- **H-3. `engine/store.py:163-173,117-119` `run_id` 未做 uuid 校验，`load`/`delete`/`_path` 暴露路径穿越** — `resume(run_id)`/`resume_stream` 是公开入口，`../../etc/passwd` 类可触发越界读/`.json` 删除。建议 `_path` 加 `re.fullmatch(r"[0-9a-f]{32}", run_id)` 或 `Path(run_id).name != run_id` 拒绝。

### 容错分类与流式

- **H-4. `providers/retry.py:39-44` `_classify` 未把 403 归为 AUTH_FAILED** — 与同文件 docstring「AUTH_FAILED (401/403)」矛盾；403 且无关键词时落 NON_TRANSIENT → ProviderChain 不回退（**FR-4 精度被破坏**）。而 `key_rotation._is_rotation_error:68` 硬编码 403 触发轮换——两套分类对同一状态码结论相反。建议 `_classify` 补 403，并让 `_is_rotation_error` 委托 `classify_exception` 成为唯一分类源。

- **H-5. `providers/openai.py:175-238` 流式未用 `async with`** — `create(stream=True)` 返回的 AsyncStream 异常路径不 `aclose()`，httpx Response 累积泄漏（长跑 + 断连场景）。建议 `async with await self._client...create(**kwargs) as stream:`。

- **H-6. `engine/policy.py:251-264` `_requires_approval` fail-safe 缺口（第四情形）** — annotations 存在但 destructive/readOnly 均为 False 时返回 False（免审批），违反 docstring「缺省→fail-safe」。**mcp agent 独立复核同一衔接点（mapping.py:58-63）确认**：server 什么都不声明反而比完全不提供 annotations 更宽松。建议 `if ann is None or not ann.readOnlyHint: return True`——只有显式 readOnlyHint=True 才免审批。

- **H-7. `tools/builtins/git.py:24-35` git 子进程无 timeout** — `proc.communicate()` 无上界，凭据提示/远端 unreachable/巨型 diff/submodule 会无限挂起（shell 工具已强制 timeout，git 遗漏）。建议 `await asyncio.wait_for(proc.communicate(), timeout=60)` + 复用 `sandbox._kill_and_reap`。

- **H-8. `cli.py:249` `_run_chat` 在 async 里裸调阻塞 `input()`** — 用户不输入时整个事件循环阻塞，同会话的 cron tick + MCP watch 一次都跑不动。建议 `await asyncio.to_thread(input, "> ")`。

- **H-9. `config.py:55` dotenv 优先级高于 env** — `settings_customise_sources` 把 dotenv 提到 env 前，**.env 胜出**（与 pydantic-settings 默认及多数预期相反）。安全相关：用 env 临时覆盖过期 `.env` 会静默失败。建议恢复默认 `init > env > dotenv`，或显著标注。

### 非原子写（崩溃即数据损坏）

- **H-10.** `cron/jobs.py:95` · `memory/profile.py:31` · `memory/skills.py:118` · `memory/facts.py:36` 写文件非原子——同仓 `SessionStore` 已用 `engine.persist.atomic_write_text`，这四处直接 `write_text`/`open('a')`。进程写盘中途被杀 → 截断 JSON，下次 load 抛 JSONDecodeError 或事实行错乱。建议统一走 `atomic_write_text`（facts 改「读全文+内存追加+原子写整文件」）。

### 工具层

- **H-11. `tools/builtins/file.py`/`search.py`/`memory.py`/`skills.py`/`cron.py` async 函数里同步 fs I/O** — 见 C-1（系统性，此处单列为 HIGH 级实例，因其直接卡事件循环）。

### Defense-in-depth 覆盖缺口（MCP，按 stance 非真边界但建议补齐）

- **H-12. `tools/mcp/manager.py:372` `_handle_list_resources` 返回 JSON 未经 `guard_content`** — 与同模块 `_handle_read_resource:392`（有 guard）不一致；server 自控制的 name/description 含注入签名不触发围栏。建议 `guard_content(json.dumps(...))`。

- **H-13. `tools/mcp/mapping.py:178-180` `bridge_result` isError 分支直接 `raise ToolError(text)` 未走 `guard_content`** — 恶意 server 把注入 payload 配 `isError=true` 即绕过标记。建议先 `guard_content(...)` 再 `raise ToolError(...)`，错误语义与围栏标记都保留。

---

## 3. MEDIUM

| # | 位置 | 问题 |
|---|---|---|
| M-1 | `tools/decorator.py:71-89` | `@tool` 对 `Optional[int]`/`int\|None`/`Literal` 一律 fallback `string`——`file_read(offset:int\|None)` schema 错标为 string，LLM 传 `"5"` → handler `offset-1` 抛 TypeError 被吞为 error 结果，功能静默退化。建议 `get_origin/get_args` 解析 Optional 或迁 `pydantic.TypeAdapter`。 |
| M-2 | `tools/builtins/search.py:66` | `content_search` 直接编译 LLM 传正则并对每行 search——病态正则 `(a+)+b` 指数级回溯卡死循环。建议限长 + 文本切片上限 + `wait_for(to_thread(...))`。 |
| M-3 | `tools/builtins/subagent.py:234-243` | `SubTaskOutcome.output` 不截断进 `model_dump_json()` 回喂 LLM——MB 级 output 撑爆父上下文，`task_parallel` 放大。建议 output 截断（与 web_fetch cap 同量级）。 |
| M-4 | `tools/builtins/subagent.py:218-232` | `task_delegate`/`task_parallel` 透传 registry 含自身，无递归深度限制——LLM 自我委派无限递归。建议 runtime 加 `depth` 字段，超阈值返回 error。 |
| M-5 | `tools/mcp/manager.py:206-213` | `_server_loop` except 仅 `_sessions.pop`，未 `_unregister_server(name)`——慢 server 超时后「ghost 工具」滞留 registry 直到 `__aexit__`。建议改调 `_unregister_server`（已幂等）。 |
| M-6 | `tools/mcp/mapping.py:58-63` | annotations tri-state 折叠与 policy fail-safe 衔接漏洞——见 H-6（同源）。 |
| M-7 | `engine/store.py:96-98` | `checkpoint` 的 `system` 参数被无条件覆盖，违反 docstring「None 时保留原值」——`resume` 续跑丢失人设/技能注入。建议 `if system is not None:`。 |
| M-8 | `engine/executor.py:62` | docstring 称 emit 绑 `EventBus.publish`，但 publish 无 `run_context` 关键字——直接绑会在首次 emit 抛 TypeError。建议改 docstring 指向 `loop._emit` 或定义 `EventEmit` Protocol。 |
| M-9 | `agent/system_prompt.py:1-4,79` | docstring 称「纯函数」，但 `build_system_prompt` 调 `skills.record_usage` 有副作用——与 loop.py:646 注释自相矛盾。建议改 docstring 讲清副作用。 |
| M-10 | `agent/sub.py:201-209` | `SubAgent.run` bare `except Exception` 兜底成失败结果，无 logger——子任务失败无堆栈无 warning。建议 `logger.warning(..., exc_info=True)`。 |
| M-11 | `agent/tool_execution.py:43-44` | `gather(*tasks)` 并发，单工具的 ledger I/O 异常会让 gather 取消杀掉整批——与「单工具异常不阻塞同批」docstring 不符。建议 `gather(..., return_exceptions=True)` 或 execute_tool_call 外包一层。 |
| M-12 | `agent/loop.py:106-125` + `sub.py:60-79` | `AgentLoop.__init__`(17参)/`SubAgent.__init__`(14参) 参数几乎全重复，`bind_subagent_tools` 再抄一份——三处漂移风险。建议抽 `AgentDeps` 模型收敛。 |
| M-13 | `providers/__init__.py:3-14` | `KeyRotatingProvider` 公开类未在 `__all__`/re-export 暴露——与 ProviderChain 暴露级别不对等。建议补 re-export。 |
| M-14 | `providers/openai.py:225-228` | `args: object = json.loads(...)` 传 `ToolCall(arguments=...)`（期望 dict）——mypy 已报错（见基线）。建议 `isinstance` 守卫或 `cast`。 |
| M-15 | `providers/anthropic.py:124`+`openai.py:95` | 模块级可变 `_ZERO_USAGE` 被多 chunk 共享引用——消费者若就地改会污染基线。建议 `TokenUsage` 加 `frozen=True`。 |
| M-16 | `context/session.py:38-53`+`cron/jobs.py:61-70`+`memory/skills.py:193-207` | 读-改-写无锁，version/usage_count/last_run 并发或重入丢更新。建议 `asyncio.Lock` 或原子文件锁。 |
| M-17 | `memory/facts.py:36-37` | `f.write(f"- {fact}\n")` 不转义换行——多行 fact 写入后只有首行能读回，静默数据损失。建议 `fact.replace("\n"," ")`。 |
| M-18 | `context/compressor.py:199-213` | `_estimate_tokens` 与 `tokens.py:_estimate_text_tokens` 重复且 CJK 覆盖更窄——两份算法会漂移。建议复用。 |
| M-19 | `context/session.py:43,66` | `except (json.JSONDecodeError, OSError): pass/return []` 静默吞错，违反「显性失败」。建议 `logger.warning(..., exc_info=True)`。 |
| M-20 | `memory/skills.py:228-239` | `archive()` 不查重名，二次归档覆盖旧归档丢历史。建议带时间戳后缀。 |
| M-21 | `cli.py:286` | 对不可信 MCP 返回数据用 `a['name']` 直接下标——恶意/破损 server 缺 name 字段 KeyError。建议 `a.get("name")`。 |
| M-22 | `cli.py:12,40` | `Any` 重复导入（line 40 死代码）。建议删。 |
| M-23 | `types.py:43,124` | `arguments/parameters: dict[str, object]` 塌缩成 object——类型安全收益为零。建议定义递归 `JsonValue`。 |
| M-24 | `cron/scheduler.py:165-187` | `_matches` 仅支持 `*`/`*/n`/纯数字，不支持范围 `1-5`/列表步进/`@daily`——标准 cron 表达式**静默不触发**无报错。建议入口校验 reject 或引 `croniter`。 |

---

## 4. LOW（择要，完整列表见各 agent 原始返回）

- `tools/safety.py:68` `_violation_log` 无界 list → `deque(maxlen=1000)`
- `tools/builtins/git.py:33` `decode()` 未传 `errors="replace"`（与 sandbox 不一致）
- `tools/sandbox.py:207` `FirejailBackend` 默认依赖 PATH 查找
- `tools/path_safety.py:14` `_workspace_override` 模块级全局跨协程污染
- `engine/store.py:151` `build_run_tree` 自引用无防御（无限递归）
- `engine/store.py:163` `delete` TOCTOU（`exists` 与 `unlink` 间）
- `engine/roles.py:141` 导入副作用写进程级 `_REGISTRY`，无 `reset_roles()` 测试辅助；`get_role` 抛 KeyError 非领域异常
- `engine/persist.py:35` 崩溃残留 `.tmp` 无清理
- `engine/context.py:35` `iso_now` naive local time，docstring 称 ISO-8601 不准
- `agent/loop.py:176` `max_iterations or settings...` truthy 判定（0 被当未指定）
- `agent/loop.py:305` `run_stream` 补救分支无 warning
- `agent/middleware.py:24,50` `MiddlewareFn`/`NextFn` 返回 `Any`，loop 需 cast
- `agent/sub.py:111` 子任务默认 20 iter magic number
- `providers/anthropic.py:36` TOOL 消息空 content 边界
- `providers/openai.py:178` 流式 `model=""` 初值，中断时为空串
- `memory/skills.py:243` `matching_skills` 忽略 description 字段
- `memory/facts.py:32` 去重阈值 0.7 魔法数（与 skill_match_threshold 风格不一）
- `context/tokens.py:25` 注释笔误 `<|assistant|/>`
- `types.py:88` `tool_calls=[]` 可变默认值（改 `Field(default_factory=list)`）
- `cli.py:169,218` engine 重复兜底建实例
- `__init__.py:5` 顶层 import 拉起全量子树，冷启动开销

---

## 5. 修复优先级建议

**P0（合并/发布前必修，CI 已红 + 硬约束）**
1. 清理 `tests/test_mcp_manager.py` 的 17 个 F811 重复测试定义（合并残留）→ ruff 归零
2. 修 `providers/openai.py:225-228` arguments 类型（M-14）→ mypy 归零
3. 修 2 个失败测试：`test_stream_yields_chunks`（补 mock `tool_calls=None`）、`test_summary_content_used`（核查 safety_margin=1024 vs max_tokens 阈值逻辑）

**P1（真实正确性/并发/数据损坏）**
4. H-4 retry 403 分类（FR-4 容错精度）
5. H-1 ledger.acquire TOCTOU + H-2 ProviderChain/KeyRotation 并发锁
6. H-5 openai AsyncStream `async with`（资源泄漏）
7. H-6 policy fail-safe 第四情形（annotations 不可信 defense-in-depth）
8. H-10 非原子写统一 atomic_write_text
9. H-7 git timeout + H-8 cli input() 阻塞

**P2（硬约束系统性收敛，跨多模块）**
10. C-1 同步 I/O → asyncio.to_thread（与 engine 子模块对齐，最大工作量）
11. C-2 SkillContent → Pydantic
12. C-3 cron → agent 反向依赖 → JobRunner 协议反转

**P3（defense-in-depth + 质量收尾）**
13. H-12/H-13 MCP guard_content 覆盖缺口
14. M-1 decorator Optional schema（潜在功能 bug）
15. M-3/M-4 subagent output 截断 + 递归深度
16. 其余 MEDIUM/LOW 按模块分批治理

---

## 6. 决策

**本次未提交变更（`sprint-status.yaml` 日期订正）**: ✅ APPROVE——与代码无关，独立干净。

**全代码库**: 整体设计扎实（路径围栏单算法、SSRF/重定向 defense-in-depth 完整、沙箱 reap 异常路径稳健、三层容错与流式三件套正确、工具执行链顺序严格、依赖注入一致），**无 CRITICAL 级安全漏洞**（所有「边界可绕过」均为 CLAUDE.md 已声明的设计立场）。但存在 **3 类硬约束系统性违反 + 13 项 HIGH（并发/容错/数据损坏/资源泄漏）+ 基线 CI 红**——建议按 P0→P1→P2 顺序分批治理，P0 可立即清零 CI。
