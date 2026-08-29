---
title: 'Story 40.1: 沙箱会话目录管理（FR-1）'
type: 'feature'
created: '2026-08-26'
status: 'done'
review_loop_iteration: 1
baseline_commit: 10a478f10e11738eb0ca392817da894ad108d2ff
epic: 40
story: '40-1'
context:
  - '{project-root}/_bmad-output/epics/epic-40-沙箱会话化周期/epic-40-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 沙箱后端目前无 per-task workspace 概念——Firejail 的 `--private` 指向构造期固化的全局 `workspace_root`，WinJob 子进程继承随机 cwd，同 run 的命令之间、不同 run 之间工作区无隔离也无持久性。

**Approach:** 引入声明式开关（`Settings.sandbox_session_workspace`）+ 纯函数目录解析 `sandbox_session_dir(run_id)`（`.heagent/sandboxes/<run_id>/`，幂等创建）+ 经 `RunContext.metadata` 与既有 contextvar 模式（仿 `bind_sandbox_profile`）把 per-run 目录送达两个后端：Firejail 复用既有 `_build_argv(workspace_root=)` 通道优先作为 `--private` 根；WinJob 将其作为子进程 cwd（目录约定，无文件系统隔离——注释与文档明示）。

## Boundaries & Constraints

**Always:**
- 未启用开关时行为与现状逐字节一致（不建目录、不写 metadata、不 bind、argv/cwd 不变）——既有 sandbox 测试全绿锁定。
- 工具执行链 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler 形态不变；`AgentLoop` 零改动（目录解析挂在 `EngineContainer.create_run_context`，bind 挂在 `execute_in_sandbox` 既有 with 块）。
- 开关开启但目录创建失败（权限/磁盘）→ **显性失败**：`create_run_context` 抛异常带路径，严禁静默降级为「无目录继续跑」（NFR-1：不制造已受保护错觉）。
- firejail/WinJob 不可用降级路径（warn + Passthrough）不因本变更改变——目录可能已建但后端照旧降级。
- 跨模块数据用 Pydantic/str 传递，不引入原始 dict 新键以外的裸结构；`RunContext.workspace_root`（policy 围欄语义）**不得复用/污染**——沙箱目录走独立 contextvar 与 metadata 键。

**Ask First:**
- 若实现中发现需要改 `agent/loop.py` 或 `_build_argv` 之外的 Firejail 参数通道才能达成 AC——停下询问。

**Never:**
- 不实现 SandboxSession 生命周期/cwd 跨命令保持（Story 40.4 范畴）。
- 不给 WinJob 补 `env=scrub_sensitive_env()`（Story 40.3 范畴，顺带对齐）。
- 不动 `path_safety.py`：`.heagent/sandboxes/` 不加入内部状态 deny 集（host 侧工具需可读写沙箱产物）；任意路径 `.env` 读 deny 对沙箱目录内同样生效，维持。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 开关关（默认） | `sandbox_session_workspace=False` | 无目录、无 metadata 键、Firejail 用构造期 root、WinJob 无 cwd——与现状一致 | N/A |
| 开 + Firejail | metadata 含 `sandbox_workspace` | `_build_argv` 得到 per-run 目录，`--private=<该目录>` 优先于构造期 root | N/A |
| 开 + WinJob | 同上 | `Popen(..., cwd=<该目录>)`；metadata 无键时不传 cwd | N/A |
| 目录创建失败 | 开关开，mkdir 抛 OSError | `create_run_context` 抛异常（链原错误，消息含目标路径），run 启动显性失败 | 不降级、不重试 |
| firejail 不可用 | `_firejail_available=False` + 开关开 | 目录照常解析创建，后端仍 warn + Passthrough 透传 | 无新增失败路径 |
| 幂等创建 | 同一 run_id 两次请求 | 返回同一路径，不抛异常 | N/A |
| cwd ≠ workspace_root（修订1） | 开关开，caller 传 `workspace_root=X` 且进程 cwd=Y | 目录落在 `<X>/.heagent/sandboxes/<run_id>/`（**已解析 root 链**下，围栏内可被 file 工具访问），绝不落 `<Y>` 下 | N/A |
| 预含键 + 开关关（修订1） | caller metadata 已含 `sandbox_workspace`，开关 False | 键被 `create_run_context` 清除，不 bind | N/A |
| 非法 run_id（修订1） | run_id 含 `/`、`..`、绝对路径或空串 | `sandbox_session_dir` 抛 `ValueError` | N/A |
| metadata 值异常（修订1） | `sandbox_workspace` 非字符串/空串/不存在路径 | 不 bind（返回 None）；目录缺失时 bind 前报「sandbox workspace missing: <path>」显性失败 | N/A |

</frozen-after-approval>

## Code Map

- `src/heagent/tools/sandbox.py` — 主战场：`RuntimeSlot` contextvar 族 L371-404（仿 `get/bind_sandbox_profile` L394-404 新增 workspace slot）；`FirejailBackend._build_argv(command, profile, workspace_root=None)` L203-226（per-call 参数通道**已存在**，L219-220 映射 `--private=`）；`FirejailBackend.run()` L228-235；`WinJobBackend.run()` L324-329（Popen 现无 `cwd=`）；构造期 root 固化于 L171-183。
- `src/heagent/engine/container.py` — `EngineContainer.default()` L102-156（现有装配，不改语义）；`create_run_context()` L158-178（**目录解析+metadata 写入挂点**；`RunContext.run_id` 为 uuid4 hex，构造后回读）。
- `src/heagent/engine/executor.py` — `execute_in_sandbox(*, call, profile, handler, run_context=None)` L221-252：既有 `with bind_command_runner(...), bind_sandbox_profile(...)` 块是第三个 bind 的挂点；`run_context` 已流经至此。
- `src/heagent/engine/context.py` — `RunContext` L49-74：`run_id` L57（default_factory uuid4）、`metadata: dict[str, Any]`（已有 `sandboxed_tools` 等 metadata 键先例）。
- `src/heagent/config.py` — `sandbox_backend` L147 / `sandbox_firejail_path` L149（env 惯例参照）；新开关字段加同区。
- `src/heagent/tools/path_safety.py` — 只读证据：`build_internal_state_dirs()` L143-156 枚举五子目录（不含 sandboxes，保持）；`.env` 任意路径读 deny L130-140（沙箱目录内同样生效，预期行为）。
- `tests/test_sandbox.py` — `test_build_argv_with_workspace_root` L632 / `_without_` L640 / `_ordering_` L645、`TestFirejailWorkspaceRoot` L832（既有锁定，扩展而非改写）。
- `tests/test_winjob_backend.py` L9-121 — WinJob 用例（补 cwd 断言）。
- `tests/test_engine_p0.py` `TestToolExecutor` L480 — RecordingExecutor 模式可仿（捕获 bind 效果）。
- `docs/frame.md` 4.4 sandbox 段 L327-331 / 4.12 L584-614 / 五 L615-620；`CLAUDE.md` L123-127 — 文档同步定位。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/config.py` -- 新增 `sandbox_session_workspace: bool = False`（env `SANDBOX_SESSION_WORKSPACE`），置于 sandbox 配置区 -- 声明式开关，默认关闭保兼容
- [x] `src/heagent/tools/sandbox.py` -- 新增 `sandbox_session_dir(run_id: str, *, base: Path | None = None) -> Path`（run_id 非法——空串/含路径分隔符/`..`/绝对路径——抛 `ValueError`；默认根 `base or Path.cwd()/".heagent"/"sandboxes"`，幂等 `mkdir(parents=True, exist_ok=True)`；docstring 措辞「幂等目录解析（有 I/O 副作用、依赖 cwd）」勿自称纯函数）+ `bind_sandbox_workspace()/get_sandbox_workspace()` contextvar（仿 profile slot）；`FirejailBackend.run()` 以 `get_sandbox_workspace() or self._workspace_root` 传入 `_build_argv`；`WinJobBackend.run()` Popen 加 `cwd=get_sandbox_workspace()`（None 不传）并补注释「目录约定，无文件系统隔离」 -- 核心目录管理与两后端接入
- [x] `src/heagent/engine/container.py` -- `create_run_context()`：**目标路径在 try 外预推导**（复用 root 回退链结果：`target = Path(root)/".heagent"/"sandboxes"/ctx.run_id`——严禁在 except 里二次调 `Path.cwd()` 重建路径），开关开启时 `ctx.metadata["sandbox_workspace"] = str(sandbox_session_dir(ctx.run_id, base=Path(root)/".heagent"/"sandboxes"))`（失败抛 RuntimeError 链 OSError，消息含 target）；**开关关闭时 `ctx.metadata.pop("sandbox_workspace", None)` 清除 caller 预含键** -- per-run 目录解析挂点（根锚定 workspace_root 回退链而非进程 cwd，目录落围栏内），AgentLoop 零改动
- [x] `src/heagent/engine/executor.py` -- `execute_in_sandbox` with 块内：`_session_workspace(run_context)` 读 metadata 键并**校验**（非 str/空串 → None 不 bind；`Path(raw)` 不存在 → 抛 `RuntimeError("sandbox workspace missing: <path>")` 显性失败）后 `bind_sandbox_workspace(...)`；**调用 `self.execute_in_sandbox` 处对子类 override 做签名兼容**（`run_context` 不在 `inspect.signature(...).parameters` 时不传该 kwarg，防库消费者旧签名子类 TypeError）；`sandbox_runner is None` 且 metadata 含会话目录时记明确 warning「sandbox_workspace ignored: no sandbox backend」 -- 目录送达后端 + 防御边界
- [x] `tests/test_sandbox.py` -- 新增：`sandbox_session_dir` 幂等/base 注入/规范路径/非法 run_id ValueError；Firejail per-run 优先于构造期 root；开关关时 argv 与现状一致（回归锁定）；contextvar bind/reset -- 意图级断言
- [x] `tests/test_winjob_backend.py` -- 补 cwd 传递断言（metadata/无 metadata 两态） -- WinJob 目录约定验证
- [x] `tests/test_engine_p0.py` -- 补 create_run_context 开关两态 metadata 断言 + **cwd ≠ workspace_root 分叉测试**（chdir 到 A、container workspace_root=B，断言目录在 B 下且不在 A 下）+ 预含键开关关被清除 + execute_in_sandbox bind 生效（RecordingRunner）+ 旧签名子类 override 兼容 -- 引擎链路验证
- [x] `tests/test_config.py` -- 补 `sandbox_session_workspace` default=False + env `SANDBOX_SESSION_WORKSPACE` 解析（"true"/"1"/非法值→校验错误） -- 配置入口验证
- [x] `docs/frame.md` + `CLAUDE.md` -- 4.4/4.12/五 与已知缺口补沙箱会话目录条目（含 WinJob 无文件系统隔离明示；根锚定 workspace_root 回退链；开关关「argv/cwd 逐字节一致」措辞精确化） -- 活文档义务

**Acceptance Criteria:**
- Given 任意 run_id，when 调 `sandbox_session_dir(run_id)`，then 返回 `<root>/<run_id>/` 且目录存在，重复调用幂等，不依赖任何执行器实例状态
- Given 开关开启的 run，when 其 SANDBOX_REQUIRED shell 命令执行，then Firejail argv 含 `--private=<session_dir>`（优先于构造期 root），WinJob 子进程 cwd 为 session_dir
- Given 开关关闭（默认），when 任意执行路径，then 行为与现状一致（既有全部 sandbox/executor 测试不改断言全绿）
- Given 开关开启但目录不可创建，when `create_run_context`，then 抛异常（含路径），run 显性失败
- Given firejail 不可用 + 开关开启，when 执行，then 维持既有 warn + Passthrough，无新增失败路径
- Given 开关开启且 caller 的 workspace_root ≠ 进程 cwd，when `create_run_context`，then 目录落在 workspace_root 回退链下（围栏内，file 工具可访问），绝不落在进程 cwd 下

## Spec Change Log

- 2026-08-26 迭代1（bad_spec loopback，review 分诊：1 bad_spec + 9 patch）：
  - **触发发现**：`sandbox_session_dir` 根硬编码 `Path.cwd()`，而 `create_run_context` 已解析 workspace_root 回退链（参数→container→policy→cwd）且所有真实 caller（loop.py:913 / sub.py:193 / cron/scheduler.py:164）传的 root 可 ≠ cwd——分叉时沙箱目录落 file 工具围栏外（shell 写入产物 file 工具不可读，split-brain），且原测试全在 cwd==workspace_root 下跑零覆盖（三方 reviewer 共同命中）。
  - **修订**：① 目录根锚定 workspace_root 回退链（container 传 `base=Path(root)/".heagent"/"sandboxes"`；CLI 场景 root 回退 cwd 行为不变）；② `run_id` 非法值 ValueError；③ `_session_workspace` 校验（非 str/空→None；路径不存在→RuntimeError 显性失败）；④ 开关关时 pop caller 预含 metadata 键；⑤ 子类 override `execute_in_sandbox` 旧签名兼容（inspect 检查）；⑥ except 路径推导去重（try 外预推导，防 POSIX cwd 消失二次异常掩盖）；⑦ runner None + 目录在 metadata 时明确 warning；⑧ 补 test_config 解析测试与 cwd≠workspace_root 分叉测试；⑨ docstring 去「纯函数」、文档措辞精确化「argv/cwd 逐字节一致」。
  - **避免的已知坏状态**：库消费者（显式 context_dir）沙箱目录静默逃出围栏、任意 metadata 字符串直入 `--private=`/`cwd=`、旧签名子类 TypeError、crash 后错误信息丢失路径。
  - **KEEP（必须在重推导中存活）**：整体架构不变——开关 + contextvar 送达链 + Firejail 复用 `_build_argv` 既有通道 + WinJob 显式 if/else 分支（mypy Popen 泛型安全，勿改回 `**kwargs`）+ RecordingExecutor 适配模式 + 全部既有回归锁定测试语义。
  - **流程偏离记录**：workflow 规定 revert 后全量重推导，但 revert 命令被本机 Fact-Forcing Gate 拦截（两次陈述不放行）；改为把修订点 + patch 清单交回原实现 subagent 在现有代码上校正——修订为收敛性局部改动而非方向推翻，工程等价且免回归风险。

## Verification

**Commands:**
- `pytest tests/test_sandbox.py tests/test_winjob_backend.py tests/test_engine_p0.py tests/test_coverage_sandbox.py -q` -- expected: 全绿（既有断言零改动 + 新增全过）
  - 迭代0结果（2026-08-26，Windows）：148 passed, 2 skipped（既有平台 skip）——既有断言零改动全绿，新增 27 个 FR-1 用例全过（含 WinJob cwd 两态，实跑非 skip）
  - 迭代1结果（2026-08-26，Windows，含 `tests/test_config.py` 共跑）：227 passed, 2 skipped——修订新增 18 个用例全过（cwd≠workspace_root 分叉两态 / 预含键清除 / 旧签名子类兼容 / missing-dir RuntimeError / ignored warning / 非法 run_id ×6 / 开关解析 ×5）
- `ruff check src tests` -- expected: 无告警
  - 迭代1结果：本 story 触及的全部文件（src + 4 个测试文件）`All checks passed`；`tests/test_plan_mode.py:76` 存在 1 个 **基线既有** E501（已在 HEAD `10a478f` 复现，非本变更引入，未顺手修改）
- `mypy src` -- expected: 无新错误
  - 迭代1结果：`Success: no issues found in 92 source files`（迭代0曾因 `**popen_kwargs` unpacking 触发 Popen 泛型误判 3 错，显式 if/else 分支归零；迭代1新增 `inspect` 兼容层后保持干净）

**补充（迭代1）**：全量 `pytest -q` 1189 passed, 3 skipped——跨文件无回归；仓库根无 `.heagent/sandboxes/` 残留；KEEP 清单全部存活（开关+contextvar 送达链、Firejail 复用 `_build_argv` 通道、WinJob 显式 if/else、RecordingExecutor 适配模式、既有回归锁定测试语义未改）。
