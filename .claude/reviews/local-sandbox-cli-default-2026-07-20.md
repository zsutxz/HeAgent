# Local Review: `--sandbox` CLI 默认值修复 — 2026-07-20

**Reviewed**: 2026-07-20
**Scope**: 未提交改动（`git diff HEAD`）
**Mode**: Local Review
**Decision**: APPROVE

## Summary

单行改动：`--sandbox` click option 的 `default` 从硬编码 `"passthrough"` 改为 `None`。修复一个安全相关 footgun——此前 CLI 入口（最常用路径）的硬编码默认值会**静默覆盖** `SANDBOX_BACKEND` 配置，导致用户显式设置 `SANDBOX_BACKEND=firejail`（更安全的硬化选项）时经 CLI 启动仍得到 `passthrough`（零隔离）。改后未传 flag 即 honor 配置，与 `config.py:119` 注释「CLI --sandbox flag 可覆盖」的原始意图一致。

## Diff

```diff
 @click.option("--sandbox", type=click.Choice(["passthrough", "firejail"]),
-              default="passthrough", help="Sandbox backend for shell execution")
+              default=None, help="Sandbox backend for shell execution (default: from SANDBOX_BACKEND setting)")
```

文件：`src/heagent/cli.py:509-510`

## 正确性追踪（resolution chain）

改动前（broken）：`python -m heagent`（无 `--sandbox`）→ `sandbox="passthrough"`（click 默认）→ `_run_single(sandbox_backend="passthrough")` → `EngineContainer.default(sandbox_backend="passthrough")` → `container.py:58` `backend="passthrough"`（因非 None）→ **`SANDBOX_BACKEND=firejail` 被忽略**。

改动后（fixed）：`sandbox=None` → `_run_single(sandbox_backend=None)` → `EngineContainer.default(sandbox_backend=None)` → `container.py:58` `backend=settings.sandbox_backend` ✓。

- 显式 `--sandbox firejail` / `--sandbox passthrough` 覆盖语义保留（`sandbox_backend` 非 None 仍优先）。
- `cli.py:538` `sandbox_resolved = sandbox or settings.sandbox_backend` 原本就为 `None` 写好回退，证明原代码意图即允许 `None`，click 默认与之矛盾——本修复对齐意图。

## Findings

### CRITICAL — None
### HIGH — None

### MEDIUM — None

### LOW
- **建议补回归测试**（completeness）：当前无 CLI/integration 级测试断言「省略 `--sandbox` + `SANDBOX_BACKEND=firejail` → `FirejailBackend`」。container 层的 None 回退已被 `test_engine_p0.py` 覆盖，但本行为变更（安全相关 footgun 修复）值得一条端到端回归测试防回退。可选。

## Validation Results

| Check | Result |
|---|---|
| Ruff lint (`ruff check src/heagent/cli.py`) | Pass |
| CLI import + `--help` (exit 0, `--sandbox [passthrough\|firejail]` 渲染) | Pass |
| 行为验证：`SANDBOX_BACKEND=firejail` + `sandbox_backend=None` → `FirejailBackend` | Pass |
| 行为验证：显式 `passthrough` 仍覆盖设置 → `command_runner is None` | Pass |
| 测试依赖排查：无测试依赖旧 `default="passthrough"` | Pass |

## Files Reviewed

- `src/heagent/cli.py` — Modified（1 行，+1/-1）
