# Story 53-4 · 审批降级接入 PolicyEngine（期二 D53-2）

状态：**done + walkthrough 已验收**（2026-11-03 判据 12 绿 + 变异体 5/5 精确变红；用户验收：探针 docker 模式 PASS + 孤儿容器零残留亲验，审批交互抽样未跑、裁定接受机器层证据）

## 实测结果（2026-11-03 亲跑，容器沙箱 + `.heagent/tmp/py311-venv-linux`）

| 命令 | 实测 |
|------|------|
| `python scripts/quality_gate.py`（`PATH` 前置 venv bin，六门一次跑完） | **all gates passed**：回归/覆盖率 **4233 passed, 50 skipped, 25 deselected**（200.62s）、覆盖率 **93%**（≥87%）、ruff lint / format（376 files）、`mypy src`（177 files）、`bandit -r src/ -ll`（High 0 / Medium 0）全绿 |
| `pytest tests/test_sandbox_approval_relax.py -q` | **12 passed**（0.89s） |
| `pytest tests/test_approval.py tests/test_engine_p0.py tests/test_sandbox.py tests/test_sandbox_docker.py tests/test_sandbox_mode.py tests/test_coverage_sandbox.py -q` | **305 passed, 6 skipped**（101.88s，零回归） |
| `pytest tests/test_architecture_contracts.py tests/test_sandbox_approval_relax.py tests/test_approval.py -q` | **57 passed**（9.59s） |
| `ruff check src tests scripts` | All checks passed |
| `ruff format --check src tests scripts` | 376 files already formatted |
| `mypy src` | Success: no issues found in 177 source files |
| `bandit -r src/ -ll` | No issues identified（High 0 / Medium 0 / Low 8 低于阈值） |
| `python scripts/mutation/mutate_approval_relax.py` | 基线 12 passed；**存活变异体 0/5**（M1 不放松 3 failed / M2 不看可用性 1 / M3 不排除 MCP 1 / M4 不要求进沙箱 1 / M5 不看档位 4） |

判据逐条落地：1/1b/2/3/4/5/6/7/8/9 全部在 `tests/test_sandbox_approval_relax.py` 内有对应用例
（含 WARNING 留痕断言与「运行期换弱后端即刻不再放松」的惰性读断言）。

## 范围

把 `SandboxTier.can_relax_approval`（FR-2 预留、此前**从未接入**裁决）接到
`PolicyEngine.evaluate_tool_call` 的审批步：容器档生效时，**真正在容器里执行**的工具调用
可免审批；弱后端一律维持原审批要求（NFR-2 冻结边界不变）。

明确**不含**：MCP stdio 进容器（D53-1 → 53-5）、降级语义的交互提示改动、审批持久化改动。

## 冻结决策（D-53-4-1 … D-53-4-5）

- **D-53-4-1 只对「真正进沙箱的路径」降级**：判定 = 工具在 `policy.sandbox_tools` 内
  **且**不是 MCP 工具（`_is_mcp_tool` 为假）。理由：`file_write` / `file_edit` / `git_*`
  在宿主执行，与容器无关；MCP stdio 尚未进容器（D53-1 未落地），此时放松等于**假隔离**。
- **D-53-4-2 可用性必须为真**：`DockerRunner.tier` 是**类属性**（恒 `CONTAINER`），而降级路径
  会 fallback 到 `PassthroughRunner`（`docker.py:487-489`）⇒ 只判 `tier` 会把「宿主裸跑」当成
  「容器隔离」。故须同时要求 `runner.available is True`（`CommandRunner` Protocol 已有该属性）。
- **D-53-4-3 未知即不降级（fail-safe）**：无 provider、provider 抛异常、runner 缺 `tier`
  或 `available` ⇒ 维持审批。与 `ToolExecutor._runner_tier()` 的 fail-safe 口径一致（未声明
  `tier` 的库消费者自定义 runner 不当强隔离）。
- **D-53-4-4 降级不绕过沙箱授权**：审批放松后仍走第 6 步 `context_grants_sandbox`，verdict
  mode 仍是 `SANDBOX_REQUIRED`（未授权时照旧要求 grant）。审批与沙箱授权是两个旋钮。
- **D-53-4-5 显性留痕**：`PolicyVerdict.approval_relaxed: bool`（默认 `False`，零回归）+
  每次放松打一条 WARNING（含工具名与触发原因）。不静默。

## 交付物

- `src/heagent/engine/policy.py`：`PolicyEngine.__init__` 增 `sandbox_runner_provider`
  （`Callable[[], CommandRunner | None] | None`，默认 `None`）；新增
  `_container_relaxes_approval()`；第 5 步审批分支接放松；`PolicyVerdict` 增
  `approval_relaxed` 字段；模块 docstring 第 5 条补放松判定。
- `src/heagent/engine/container.py`：`__post_init__` 在 runner 注入之后把
  `policy.sandbox_runner_provider` 接到 `executor.sandbox_runner`（惰性读，避免构造顺序耦合）。
- `tests/test_sandbox_approval_relax.py`：新增，覆盖判据 1–9。
- 文档三处：`docs/frame.md:462`（FR-2 段）、`docs/frame.md:1447`（分级表行）、
  `docs/sandbox.md:108`——把「仍未接入 PolicyEngine 裁决」改为已接入并写明生效条件。
- `../deferred-work.md`：D53-2 状态 → done（含 evidence）；`../epics.md` Story 表加 53-4 行。

## 验收判据

| # | 判据 | 期望 |
|---|------|------|
| 1 | container 档（available=True）+ `shell` ∈ sandbox_tools + approval_tools + 沙箱已授权 | 不返回 `APPROVAL_REQUIRED`；`verdict.approval_relaxed is True`；mode `SANDBOX_REQUIRED` |
| 2 | 弱档 passthrough / job / firejail 同场景 | 仍 `APPROVAL_REQUIRED`（NFR-2） |
| 3 | tier=CONTAINER 但 `available=False`（降级 Passthrough） | 仍 `APPROVAL_REQUIRED` |
| 4 | 未注入 provider（既有直接构造） | 与现状逐字节一致（`APPROVAL_REQUIRED`，`approval_relaxed is False`） |
| 5 | provider 抛异常 | 仍 `APPROVAL_REQUIRED`（fail-closed） |
| 6 | `file_write` ∈ approval_tools + container 档 | 仍 `APPROVAL_REQUIRED`（宿主工具不降级） |
| 7 | MCP 工具（`sandbox_mcp_tools=True`）+ container 档 | 仍 `APPROVAL_REQUIRED`（等 D53-1） |
| 8 | 审批已授权（`approved_tools` 含该工具） | 行为不变、`approval_relaxed is False` |
| 9 | `EngineContainer` 装配后 provider 已接线（container runner ⇒ 放松；passthrough ⇒ 不放松） | 断言二者差异 |

## 不做 / 边界

- 不改变 `approval_tools` 默认值（默认空串 ⇒ 默认配置下本 story 无行为变化，仅当用户显式
  配了审批工具且容器档生效时才放松）。
- 不新增 Settings 开关：放松的**触发条件本身就是**「用户开了审批工具 + 容器后端可用」，
  再加一层开关等于把 NFR-2 的锁换成配置面可关的软锁。
- 边界地位不变：容器档是 OS 级强隔离兜底，**不是绝对边界**（宿主内核 / daemon 逃逸仍在）。

## 实测结果

（执行后回填）
