# Code Review: 近 10 个提交（`HEAD~10..HEAD`，`e36a42f..ace72a2`）

**Reviewed**: 2026-07-20
**Scope**: `git diff HEAD~10..HEAD`（10 commits，~41 files，+3800/-377）。方法论 = 以**最终态**为准（三路并行 python-reviewer subagent + 主线逐条复核 HIGH），避免累计 diff 中「加了又删」的幽灵代码误报。
**Mode**: Multi-commit local review（非 PR、非单次未提交 diff）
**Decision**: **REQUEST CHANGES** — 7 个 HIGH（含安全/正确性/静默失败），不可直接合并

## 涉及的主要提交

| commit | 主题 |
|---|---|
| `5a4a29e` | feat: Sandbox 硬化周期（S1-S4） |
| `ee6cda8` | feat(providers): SwitchableProvider 多 vendor 运行时切换 |
| `661ca91` / `f7957b8` / `bcc45e4` / `e36a42f` / `ed01b94` | 各轮代码审查 P0-P2 修复 |
| `ace72a2` | docs: sandbox-hardening 规划归档 |

> 注：`M src/heagent/cli.py`（`--sandbox` 默认 `passthrough`→`None`）为**未提交**改动，已单独审查（见 `local-sandbox-cli-default-2026-07-20.md`，APPROVE），不计入本次。

---

## Findings

### CRITICAL — None

无硬编码密钥、注入、SSRF 等。Provider 层密钥全部来自 `Settings`，无裸 `except: pass`。

### HIGH（7 — 全部已主线复核确认）

**[HIGH-1 / 安全·正确性] `src/heagent/tools/sandbox.py:63` — `os.killpg(os.getpgid(proc.pid), SIGKILL)` PID 复用竞态**
`start_new_session=True`（81/104）保证子进程即会话组长，`proc.pid` 本就是 pgid；`os.getpgid` 多余且危险：子进程已退出 + PID 被回收时，`getpgid(recycled_pid)` 返回**别的**进程的 pgid，`killpg` 会 SIGKILL 无关进程组。这是 S3-1「进程组 kill」招牌功能的正确性缺陷。
**Fix**: `with suppress(ProcessLookupError): os.killpg(proc.pid, signal.SIGKILL)`（组已无存活成员时自然抛 `ProcessLookupError` 被抑制）。

**[HIGH-2 / 测试意图] `tests/test_sandbox.py` 多处 `_FakeProc` 缺 `pid` 属性 → Linux killpg 路径假绿**
所有 `_FakeProc` 仅定义 `returncode`/`kill`/`communicate`/`wait`，无 `pid`。Linux 下 `os.getpgid(proc.pid)` 抛 `AttributeError`（非 `OSError`、非 `ProcessLookupError`），逃出 `_kill_and_reap`，被调用方 `except Exception` 吞掉（`sandbox.py:88/111`）→ 测试**静默通过但从未真正执行 killpg/reap**。（注：subagent 原称「crash」，实际是更糟的「静默假绿」。）违反「测试验证意图而非行为」+ 显性失败。CI（Linux）会放过这条本应覆盖目标平台的断言。
**Fix**: 给每个 `_FakeProc.__init__` 加 `self.pid = <int>`；并加一条 `monkeypatch sys.platform=="linux"` + stub `os.getpgid`/`os.killpg` 的用例真正验证 Linux 分支。

**[HIGH-3 / 静默失败·CI] `src/heagent/cli.py:551-552` + `:87,:95-96` — 启动 provider 选择在单次/CI 模式也强弹，关闭 stdin 时 `SystemExit(0)` 吞失败**
`if isinstance(provider, SwitchableProvider): _prompt_startup_provider(...)` 无条件触发（注释「始终弹出」），单次执行 `python -m heagent "task"` 与 CI 同样弹。非 TTY / `< /dev/null` 时 `click.prompt` 抛 `Abort`，`except (ValueError, click.Abort): raise SystemExit(0)` → 任务从未执行却以 **exit 0** 返回。违反显性失败，直接破坏 CI/自动化。
**Fix**: `if not sys.stdin.isatty(): return`（用 `ACTIVE_PROVIDER` 默认直跑）；或加 `--provider NAME` / `--no-prompt` 旁路。

**[HIGH-4 / 正确性·容错链断裂] `src/heagent/providers/key_rotation.py:121` — 流式「All keys exhausted」丢弃 `last_error`/`status_code`，阻断跨 provider 故障转移**
当所有 key 都因可轮换错误（429/403）耗尽，循环只在 `:119` `logger.warning` 记录，从未捕获 `last_error`，最终 `raise ProviderError("All keys exhausted for stream")`（无 `from`、无 status_code）。下游 `ProviderChain.classify_exception` 看到 `status_code=None` → 判为 NON_TRANSIENT → **不触发跨 provider 回退**——恰是全网限流时最该 failover 的场景。与 `send()`（`:89-90` `raise last_error or ProviderError(...)`）不对称。
**Fix**: 在 stream 循环跟踪 `last_error`，`raise last_error`（镜像 `chain.py:159-161`）。

**[HIGH-5 / 架构硬约束·类型] `src/heagent/providers/switchable.py:85-96` — `info()` 返回原始 `dict[str, object]`，违反「跨模块数据用 Pydantic 模型，禁止原始 dict」**
CLAUDE.md 把该约束标为「硬约束（违反即架构错误）」。`info()` 的 value 是裸 dict `{"model",...}`，CLI `cli.py:83` `meta['model']` 索引 `object` → mypy 报错。
**Fix**: 在 `types.py` 或 `providers/base.py` 定义 Pydantic `ProviderSummary(model, streaming, tools, active)`，返回 `dict[str, ProviderSummary]`，CLI 改属性访问。

**[HIGH-6 / 并发·契约不实] `src/heagent/providers/switchable.py:57,112-113` — `send()` 全程持 `_lock` 串行化并发请求，但 `switch()`（71-83）不走锁，声称的「防并发 switch+send 竞态」并未达成**
锁横跨整个 `await provider.send()` 网络调用，串行化所有并发请求（sub-agent 并行会全部排队）；而 `switch()` 是同步赋值、不取锁。`self._current`（dict 查找 + str 引用）在 GIL 下本就原子，锁对正确性无必要、对并发有实害。
**Fix**: 删除 `_lock`，`send()` 直接 `provider = self._current; return await provider.send(...)`。（`stream()` 已是「先捕获再释放」模式，:126-130 同理可简化。）

**[HIGH-7 / 死状态·误导] `src/heagent/cron/scheduler.py:40,52` + docstring:33-34 — C-3 重构遗留死 `provider` 参数/字段，文档却称「cron 依赖 provider」**
`self._provider = provider`（:52）**只写不读**（全文件仅此一处），`provider: BaseProvider` 仍是必填位置参数，docstring 反称「cron 仅依赖 provider / engine … 保持 DAG 方向一致」——与实现矛盾。所有调用方（`cli.py:263`、`test_cron.py` ×4、`test_engine_p0.py:300`）被迫传无意义 `_StubProvider()`。
**Fix**: 删除 `provider` 参数 + `self._provider` + `BaseProvider` import（:18）+ 改 docstring；更新 6 处调用方。（注：本条为 7 个 HIGH 中最软，borderline MEDIUM——非运行时 bug，属死代码/契约漂移。）

### MEDIUM（10 — 摘要，详见各 subagent 报告）

- `engine/container.py:60-65` 默认装配 `FirejailBackend` 不传 `profiles=`，且无 `Settings.sandbox_*_profiles` 配置入口 → profile 名经 contextvar 流到 `_build_argv` 但 `_profiles=={}` 取空元组，**profile 机制默认装配下完全惰性**（仅手工构造 `FirejailBackend` 才生效）。
- `tools/sandbox.py` `FirejailBackend` docstring 称 `RoleSpec.sandbox_profile`「产生实际隔离差异」，但 `RoleSpec.sandbox_profile`（`roles.py:37`）从未被读（sub.py 忽略它）——死字段 + 文档假声明。
- `config.py:120` `sandbox_backend: str` 接受任意字符串，`SANDBOX_BACKEND=Firejail`/`firejial`/尾空格 静默降级 Passthrough，违「显性失败」。应改 `Literal["passthrough","firejail"]` 或加 validator（CLI `--sandbox` 走 `click.Choice` 已正确，仅 env/setting 路径未护栏）。
- `tools/sandbox.py` 本轮删除了 `_kill_and_reap`/`_validate_timeout`/`_run_subprocess_*`/RuntimeSlot helpers 的中文契约注释——尤其 `_kill_and_reap` 记录了「kill/wait 解耦」「wait 硬上界」「不吞重入 CancelledError」等**承重不变量**，现仅留 `except BaseException:` 无说明，后续易改坏。建议至少恢复 `_kill_and_reap` 契约注释。
- `providers/chain.py:90-120,131-163` + `key_rotation.py:72-90,99-121` `async with self._lock` 横跨 `await provider.send()` / `yield chunk`——asyncio 反模式（消费者在同实例上再 await 易死锁）；锁仅用于保 `_current_index` 粘性一致。建议：锁内快照 `start`，释放后迭代，仅在提交索引变更时重取锁。
- `cli.py:95-96` `except (ValueError, click.Abort)` 不含 `KeyboardInterrupt`，Ctrl-C 在选择提示处出丑 traceback。
- `cli.py:376-393` `_handle_slash` 对未知 `/foo` 返回 `False` → 当作普通用户消息发给 LLM（意外行为）。
- `cli.py:99-157` + `providers/__init__.py` `_build_provider` 不再用 `ProviderChain` 包多 vendor（自动 failover → 手动 `SwitchableProvider`），但 `ProviderChain` 仍导出，CLI 不可达——需文档化「手动取代自动」或让 `SwitchableProvider` 内组合 `ProviderChain`。
- 测试缺口：`test_provider_switchable.py`/`test_chain.py` 缺 (a) `isinstance BaseProvider` 协议匹配、(b) 并发 `send`+`switch`、(c) `switch` 到当前活跃 no-op、(d) 启动提示 EOF/Abort/KeyboardInterrupt、(e) `KeyRotatingProvider.stream` 保 `last_error`（本条能抓到 HIGH-4）。
- `tests/test_compressor.py` 缺 P1-1（content×tool_calls 去重）回归测试；`tests/test_safety.py` 缺 fork-bomb fixture。

### LOW（≈10）— 摘要
`compressor.py:170` magic number `30`；`compressor.py:184-187` 兜底分支仍用旧格式丢 tool_calls；`scheduler.py:159` 引入私有 `_iso_now`；`safety.py` fork-bomb 正则 `[^}]*[;&|][^}]*` 会误伤良性 `func(){ echo hi; }`（建议要求 `: | : &` 自引用模式）；`cli.py:12,40` `Any` 重复 import；`chain.py:65-77` `_advance` 私有但被测试引用；`switchable.py:126-130` stream 取锁多余。`openai.py:174-175` `async with await ... as stream` 是正向改进（无问题）。

---

## Validation Results

| Check | Result |
|---|---|
| Ruff lint (`ruff check src tests`) | **Pass** |
| Tests (`pytest -q`) | **Pass** — 751 passed, 4 deselected, 2 warnings, 31.5s |
| mypy | 未跑（subagent 报 `switchable.info()` + `cli.py:83` 3 处 `object` 不可索引——HIGH-5） |

> 2 个 pytest warning 为既存 Windows asyncio `ProactorBasePipeTransport.__del__` transport 清理噪声（`test_sub_agent.py`，非本次范围），非真实失败。
> ⚠ 测试全绿但**不可作为合并依据**：HIGH-2 证明 Linux killpg 路径是假绿，HIGH-4 的 failover 断裂无测试覆盖。

## Files Reviewed（源码 16 + 测试 4）
- **Modified**: `cli.py` `config.py` `context/compressor.py` `cron/scheduler.py` `engine/{container,executor,policy,observability,store}.py` `memory/skills.py` `providers/{__init__,chain,key_rotation,openai}.py` `tools/{safety,sandbox}.py`
- **Added**: `providers/switchable.py`、`tests/test_provider_switchable.py`、`tests/test_sandbox.py`（及大量 `_bmad-output/sandbox-hardening/` 规划文档、`docs/`，本次仅作轻量过审）

## 建议修复顺序（按风险/独立性）
1. **HIGH-1**（killpg 竞态）+ **HIGH-2**（补 `_FakeProc.pid` + Linux 分支真测试）—— 一起改 `sandbox.py` / `test_sandbox.py`
2. **HIGH-4**（stream `last_error`）—— 小改 `key_rotation.py`，附带补一条断言 `exc.status_code==429` 的回归测试
3. **HIGH-3**（启动提示 TTY 守卫 / `--provider` 旁路）—— `cli.py`
4. **HIGH-5**（`info()` Pydantic 化）+ **HIGH-6**（删 `SwitchableProvider._lock`）—— `switchable.py` + `cli.py`
5. **HIGH-7**（删 scheduler 死 `provider`）+ MEDIUM 逐条
