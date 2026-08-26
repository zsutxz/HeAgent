---
title: 'Story 40.2: 沙箱后端强度分级（FR-2）'
type: 'feature'
created: '2026-08-26'
status: 'done'
epic: 40
story: '40-2'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-40-context.md'
---

## Intent

**Problem:** 沙箱后端（Passthrough / WinJob / Firejail）的隔离强度差异（无隔离 / 进程级 / 文件系统级）对策略层与执行层不可见——执行路径无法感知「当前跑在什么强度的后端里」，未来接入更强后端（bubblewrap/nsjail/AppContainer）时也无从判定是否可放宽审批。

**Approach:** 引入强度分级枚举 `SandboxTier`（`passthrough < job < firejail < container`，container 档预留、无实现后端）；三个后端声明自身档位；`CommandRunner` Protocol 增加 `tier` 属性使执行路径可查询；审批降级（`can_relax_approval`）仅对 `container` 档开放，弱后端一律维持原审批要求。

## Boundaries & Constraints

**Always:**
- 强度序固定 `passthrough(0) < job(1) < firejail(2) < container(3)`；`container` 仅存在于枚举、无实现后端（预留）。
- 弱于 container 的后端（passthrough/job/firejail）`can_relax_approval` 恒为 False——不得因后端强度跳过审批（NFR-2，测试锁定）。
- 档位以强类型 `SandboxTier`（StrEnum）传递，无裸 str；查询后端档位一律经 `CommandRunner.tier` 或 executor 的 `_runner_tier()`。
- 不改变工具执行链 `PolicyEngine.evaluate() → ToolExecutor → SafetyGuard.check() → handler` 形态；不改变既有审批/沙箱裁决结果（弱后端下逐字节一致）。
- `AgentLoop` 零改动。

**Ask First:**
- 若实现中发现需要在 `PolicyEngine.evaluate_tool_call` 加 tier 参数才能达成「裁决可感知」——停下询问（本 story 判定为仅需执行层感知 + 枚举级审批降级判定点，不接 policy 裁决）。

**Never:**
- 不实现任何 `container` 档后端（bubblewrap/nsjail/AppContainer）——仅预留枚举。
- 不把审批降级真正接入 `PolicyEngine` 裁决（那是 container 后端落地时的独立工作）。
- 不改 `scrub_sensitive_env`（Story 40.3 范畴）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 后端实例化 | `PassthroughRunner()` / `WinJobBackend()` / `FirejailBackend()` | `tier` 分别为 `passthrough` / `job` / `firejail` | N/A |
| 强度序 | 四档枚举 | `rank` 严格递增 0→3 | N/A |
| 审批降级判定 | `tier in {passthrough, job, firejail}` | `can_relax_approval` 为 False | N/A |
| 审批降级判定（预留） | `tier == container` | `can_relax_approval` 为 True（无实现后端） | N/A |
| 执行路径查询（无后端） | `sandbox_runner is None` | `_runner_tier()` → `PASSTHROUGH` | N/A |
| 执行路径查询（有后端） | `sandbox_runner` 已注入 | `_runner_tier()` → 对应后端 tier | N/A |
| 可观测 | SANDBOX_REQUIRED emit 事件 | `details["sandbox_tier"]` 含当前档位字符串 | N/A |

## Code Map

- `src/heagent/tools/sandbox.py` — `CommandRunner` Protocol L33-38（加 `tier` 属性）；`PassthroughRunner` L159 / `FirejailBackend` L166 / `WinJobBackend` L262（各加 `tier` class attribute）；新增 `SandboxTier` 枚举（置于 Protocol 前）。
- `src/heagent/engine/executor.py` — `_execute_in_sandbox` 的 started/completed/failed emit（加 `sandbox_tier`）；新增 `_runner_tier()` helper（`sandbox_runner.tier` or `PASSTHROUGH`）。
- `docs/frame.md` 4.12 / 五 — 分级语义 + container 预留 + 审批降级非启用。
- `tests/test_sandbox.py` / `tests/test_engine_p0.py` — 枚举 + 后端声明 + 查询 + emit 断言。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/tools/sandbox.py` — 新增 `SandboxTier(StrEnum)`（四档 + `rank` + `can_relax_approval`）；`CommandRunner` Protocol 加 `tier: SandboxTier`；三后端各加 `tier` class attribute
- [x] `src/heagent/engine/executor.py` — 新增 `_runner_tier()`；`_execute_in_sandbox` 三个 emit 事件 details 加 `sandbox_tier`
- [x] `tests/test_sandbox.py` — SandboxTier 枚举（四档/rank 序/can_relax_approval）+ 三后端 tier 声明断言
- [x] `tests/test_engine_p0.py` — `_runner_tier()` 无后端→passthrough / 有后端→对应档；emit 事件含 sandbox_tier
- [x] `docs/frame.md` — 4.12 分级语义 + 五 已知缺口（container 预留、审批降级非启用）

**Acceptance Criteria:**
- Given 分级模型，When 后端实例化，Then 各后端正确声明档位：Passthrough→`passthrough`、WinJob→`job`、Firejail→`firejail`；`container` 档存在于枚举、无实现后端（预留）
- When `SANDBOX_REQUIRED` 执行路径查询当前后端强度，Then 执行路径可获取档位（强类型 `SandboxTier`，无裸值）
- Given 弱于 `container` 的任意后端，When 触发审批语义裁决，Then 审批要求与现状一致（测试锁定：弱后端不得触发审批降级）
- And 分级语义与升级路径写入 `docs/frame.md` 4.12

## Verification

**Commands:**
- `pytest tests/test_sandbox.py tests/test_winjob_backend.py tests/test_engine_p0.py -q` — 结果（2026-08-26，Windows）：**144 passed, 1 skipped**（既有断言零改动 + 新增 SandboxTier/emit 用例全过）
- `ruff check src` — 结果：**All checks passed**（`test_plan_mode.py:76` E501 为基线既有，非本变更引入）
- `mypy src` — 结果：**Success, no issues found in 92 source files**

## Spec Change Log

- 2026-08-26 迭代1（实现中 review 发现，2 patch）：
  - **`_RANK` 类属性被 StrEnum 误判为成员（Python 3.13）**：`class SandboxTier(StrEnum)` 内 `_RANK: dict[str, int] = {...}` 带类型注解的类属性在 Python 3.13 的 Enum 类创建中被 `_new_member_` 处理，抛 `TypeError: {...} is not a string`。修复：rank 映射移到模块级 `_TIER_RANK`，`rank` property 引用模块级常量——枚举成员与内部映射彻底分离。
  - **`_runner_tier()` 对无 tier 的自定义 runner 兜底**：既有测试的 `_RecordingRunner` 未声明 `tier`（旧 `CommandRunner` 契约无此属性），`self.sandbox_runner.tier` 抛 AttributeError。修复：`getattr(self.sandbox_runner, "tier", SandboxTier.PASSTHROUGH)`——未知强度按最弱档 fail-safe，不误判为强隔离。
