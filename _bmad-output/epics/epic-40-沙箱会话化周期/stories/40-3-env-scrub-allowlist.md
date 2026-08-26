---
title: 'Story 40.3: 声明式环境变量豁免（FR-3）'
type: 'feature'
created: '2026-08-26'
status: 'done'
epic: 40
story: '40-3'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-40-context.md'
---

## Intent

**Problem:** `scrub_sensitive_env`（Epic 37 交付）对 `*_API_KEY` / `*_TOKEN` 等敏感变量一律剥离，无豁免入口——受信任务需要的凭证（如 `GITHUB_TOKEN`）无法进入 shell 子进程，用户只能改代码。

**Approach:** 给 `scrub_sensitive_env` 加声明式 `allowlist` 参数（精确变量名，大小写不敏感）；新增 `Settings.sandbox_env_allowlist`（env `SANDBOX_ENV_ALLOWLIST`，逗号分隔）+ `sandbox_env_allowlist_set` property；`_run_subprocess_shell` / `_run_subprocess_exec` 从 Settings 读 allowlist 传入。

## Boundaries & Constraints

**Always:**
- allowlist 为空/未配置时行为与现状**逐字节一致**（默认全剥离，向后兼容）。
- 豁免仅作用于 `scrub_sensitive_env` 的 env 剥离——不影响 `path_safety` 凭证文件读写 deny 与 `SafetyGuard` 凭证路径拦截。
- `scrub_sensitive_env` 保持纯函数（allowlist 作显式参数传入，不内部读 Settings）；Settings 读取放在调用方。
- 工具执行链形态不变；`AgentLoop` 零改动。

**Ask First:**
- 若需给 `WinJobBackend` 补 env scrub（当前 WinJob 直接 Popen 不 scrub，属既有缺口、非本 story scope）——停下询问。

**Never:**
- 不把 allowlist 匹配改成前缀/后缀/通配（AC 只要求精确变量名）。
- 不修改 `_SENSITIVE_ENV_SUFFIXES` 剥离规则本身。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior |
|----------|--------------|---------------------------|
| allowlist 空 | `scrub_sensitive_env(env)` | 与现状逐字节一致（全剥离敏感） |
| allowlist 命中 | `scrub_sensitive_env({"GITHUB_TOKEN": "x", "OPENAI_API_KEY": "y"}, allowlist=["GITHUB_TOKEN"])` | `GITHUB_TOKEN` 保留，`OPENAI_API_KEY` 剥离 |
| 大小写不敏感 | allowlist 含 `github_token`，env 键 `GITHUB_TOKEN` | 命中保留 |
| 非敏感 + 命中 | allowlist 含 `PATH` | `PATH` 本就不剥，仍保留 |
| 配置解析 | `SANDBOX_ENV_ALLOWLIST=GITHUB_TOKEN,CUSTOM` | `sandbox_env_allowlist_set` = {GITHUB_TOKEN, CUSTOM} |

## Code Map

- `src/heagent/config.py` — 沙箱配置区加 `sandbox_env_allowlist: str` + `sandbox_env_allowlist_set` property（仿 `approval_tools` → `approval_tool_list`）。
- `src/heagent/tools/sandbox.py` — `scrub_sensitive_env` L111 加 `allowlist` 参数；`_run_subprocess_shell` L152 / `_run_subprocess_exec` L176 经 `_env_allowlist()` 读 Settings 传入；`TYPE_CHECKING` 加 `Iterable`。
- `tests/test_credential_guard.py` — `TestScrubSensitiveEnv` 补 allowlist 用例。
- `tests/test_config.py` — `sandbox_env_allowlist` 解析（default 空 / 逗号分隔 / property set）。
- `docs/frame.md` — 4.4 sandbox 段 FR-3 段落 + 五 已知缺口。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/config.py` — 加 `sandbox_env_allowlist: str = Field(default="")` + `sandbox_env_allowlist_set` property
- [x] `src/heagent/tools/sandbox.py` — `scrub_sensitive_env` 加 `allowlist` 参数；`_env_allowlist()` helper；`_run_subprocess_shell`/`_run_subprocess_exec` 传入 allowlist
- [x] `tests/test_credential_guard.py` — allowlist 命中/空/大小写 用例
- [x] `tests/test_config.py` — 解析用例
- [x] `docs/frame.md` — FR-3 文档同步

**Acceptance Criteria:**
- Given allowlist 含 `GITHUB_TOKEN`，When spawn shell 子进程，Then `GITHUB_TOKEN` 传入，其余命中剥离规则的变量仍被剥离
- Given allowlist 未配置/为空，When spawn，Then 行为与现状逐字节一致（默认全剥离，向后兼容）
- Given `Settings` 字段 + `.env` 覆盖入口，When 用户声明豁免，Then 无需改代码
- And 豁免仅作用于 env 剥离，不影响 `path_safety` 凭证文件读写 deny 与 `SafetyGuard` 凭证路径拦截

## Verification

**Commands:**
- `pytest tests/test_credential_guard.py tests/test_config.py -q` — 结果（2026-08-26，Windows）：**110 passed**
- `ruff check src tests` — 结果：仅 `test_plan_mode.py:76` E501（基线既有，非本变更引入）
- `mypy src` — 结果：**Success, no issues found in 92 source files**

## Spec Change Log

- 2026-08-26 迭代1（实现中 review，1 patch）：`assert result["GITHUB_TOKEN"] == "ghp_xxx"` 触发 bandit S105（硬编码密码）——改为 `== env["GITHUB_TOKEN"]` 与源值比较，避免在比较语句中写硬编码凭证字面量。
