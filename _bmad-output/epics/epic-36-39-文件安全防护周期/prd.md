---
title: "HeAgent 文件安全与凭证防护 — 借鉴 hermes file_safety 的纵深防御"
status: draft
cycle: file-safety-hardening
preceded_by:
  - _bmad-output/epics/epic-S1-S4-沙箱硬化周期/（Epic S1-S4）
  - _bmad-output/epics/epic-29-35-交互扩展周期/（Epic 29-35）
created: 2026-08-24
updated: 2026-08-24
---

# PRD: HeAgent 文件安全与凭证防护

> **本文档的 FR 编号（FR-F1~F5）独立于主线 baseline（FR-1~24）、MCP（FR-*）、Sandbox（FR-S*）、
> 交互扩展（FR-A~G）。** 下游 epics/stories 以本 PRD 的 `FR-F*` 为准。

## 0. Document Purpose

本 PRD 面向**架构（`bmad-architecture`）与 epics/stories（`bmad-create-epics-and-stories`）**
两个下游工作流。它建立在以下既有产物之上、不重复其内容：

- **`brief.md`**（本周期）：产品愿景、缺口、方案、边界、关键决策——本 PRD 是其结构化展开。
- **`src/heagent/tools/path_safety.py`**（已交付）：`resolve_under_root` 单一工作区围栏算法，
  policy 预检与 handler 守卫共用——本 PRD 的凭证 deny 是**并列的独立层**，不合并进围栏。
- **`src/heagent/tools/sandbox.py`**（已交付）：`_run_subprocess_shell` / `_run_subprocess_exec`
  是 shell 子进程的 spawn 点——本 PRD 的 env scrubbing 落在这些 spawn 点。
- **`src/heagent/engine/policy.py`**（已交付）：`_validate_paths` 是 policy 预检入口——本 PRD
  的凭证 deny 预检挂接在它之后。
- **`src/heagent/tools/builtins/file.py`**（已交付）：`file_read` / `file_write` handler——
  本 PRD 的 handler 守卫挂接在 `resolve_workspace_path` 之后。

## 1. Vision

HeAgent 的文件层防护只有「工作区围栏」一个维度，缺两类直接对应真实威胁的纵深防御：**凭证
文件的精确 deny（读 + 写）** 与 **凭证环境变量的子进程 scrubbing**。本轮借鉴 hermes-agent
`agent/file_safety.py` 的设计（按 HeAgent 栈改造），把这两类防护补上，让「LLM 自主读写文件 /
执行 shell」时无法轻易泄露 API key 或篡改内部状态。

安全立场延续：凭证 deny 与 env scrub 均**非真正安全边界**（shell 工具仍可 `cat .env` 绕过，
deny 只拦「合作模式下尊重工具拒绝」的模型），须 OS 级沙箱兜底。本轮不制造「加了 deny 就安全」
的假象。

## 2. Target User

### 2.1 Jobs To Be Done

- **功能**：我在 workspace 里放了 `.env`（含 `DEEPSEEK_API_KEY`），agent 调 `file_read(".env")`
  时应该被拦截并提示「这是凭证文件」，而不是把 key 原样送进 LLM 上下文。
- **功能**：agent 调 `shell("env")` 或 `shell("curl ...")` 时，子进程环境里**不应该有**我的
  API key——`*_API_KEY` / `*_TOKEN` 等敏感变量在 spawn 前就被剥离。
- **功能**：agent 不能读 `.heagent/` 内部状态（session/ledger/memory），防止内部状态污染
  上下文或成为注入载体。
- **情境**：我是 HeAgent 的运维者——我信任自己的本地命令，但**不信任 LLM 自主生成的文件读写
  与 shell 命令**。凭证 deny 给我一层「凭证不入 LLM 上下文、不进子进程环境」的纵深防御——
  不是完美堡垒，但比裸跑强得多。
- **情感**：我不想为了安全关掉 shell / file 工具（它们太有用）。我要的是「工具还在，但凭证
  被圈住」。

### 2.2 Non-Users (本轮)

- 把 HeAgent 跑在整体 OS 沙箱/容器里、用 OS 级隔离替代进程内启发式的运维者——deny 对他们是
  冗余层（但仍有价值作为 defense-in-depth）。
- 需要在 shell 子进程里主动使用 API key（如 agent 调一个需要 key 的脚本）的用户——本轮剥离
  敏感 key，这类场景需后续提供白名单透传（deferred）。

### 2.3 User Journeys

- **UJ-F1. tan 的 agent 误读 workspace 里的 `.env`。**
  agent 调 `file_read(".env")` → policy 预检 `_validate_paths` 命中读 deny → `BLOCKED`，
  reason 提示「凭证文件，请读 .env.example」。handler 守卫同样拦截（若预检被绕过）。
  Realizes FR-F2。

- **UJ-F2. tan 的 agent 跑 `shell("env")`。**
  agent 调 `shell("env")` → `_run_subprocess_shell` 传 `env=scrub_sensitive_env(os.environ)`
  → 子进程环境里没有 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` 等敏感变量 → 输出不含凭证。
  Realizes FR-F3。

- **UJ-F3. tan 的 agent 尝试写 `~/.ssh/authorized_keys`。**
  agent 调 `file_write("~/.ssh/authorized_keys", ...)` → 写 deny 命中 → 拦截并提示「受保护
  的凭证/系统文件」。Realizes FR-F1。

## 3. Glossary

- **workspace 围栏** — `resolve_under_root(path, root)`：路径解析后必须在 `root` 内，否则
  `WorkspacePathError`。管「位置」。
- **凭证 deny** — 本轮新增：凭证文件/目录的精确 deny（写 deny 精确匹配 + 目录前缀；读 deny
  secret-bearing 文件名）。管「敏感度」，与围栏并列。
- **scrub_sensitive_env** — 本轮新增：剥离环境变量 dict 中匹配敏感模式（`*_API_KEY` / `*_TOKEN`
  / `*_SECRET` / `*_PASSWORD` 等）的键，透传其余。纯函数。
- **内部状态** — `.heagent/` 目录下的 session 持久化、ledger 账本、memory 记忆、skills 元数据。
  读 deny 防注入载体 / 污染上下文。
- **defense-in-depth** — 分层防御：凭证 deny / env scrub 是「合作模式下减少 casual 泄露」的
  启发式层，非真正安全边界，须 OS 级沙箱兜底。

## 4. Requirements

### FR-F1：凭证文件写 deny

**As a** HeAgent 操作者,
**I want** `file_write` 等写工具拦截对凭证/敏感文件的写入,
**So that** LLM 不能覆盖 `.env` / `~/.ssh/*` / `~/.aws/*` 等敏感文件。

**Consequences:**

- `path_safety.py` 新增纯函数 `build_write_denied_paths() -> set[str]`（`realpath` 精确匹配：
  `.env`、`.netrc`、`.npmrc`、`.pypirc`、`.git-credentials`、`~/.ssh/authorized_keys`、
  `~/.ssh/id_rsa`、`~/.ssh/id_ed25519`、`/etc/sudoers`、`/etc/passwd`、`/etc/shadow` 等）
- `path_safety.py` 新增纯函数 `build_write_denied_prefixes() -> list[str]`（目录前缀：
  `~/.ssh/`、`~/.aws/`、`~/.gnupg/`、`~/.kube/`、`/etc/sudoers.d/`、`~/.docker/`、
  `~/.azure/`、`~/.config/gh/`、`~/.config/gcloud/` 等）
- `path_safety.py` 新增 `check_write_denied(path) -> str | None`（返回 deny 原因或 None）
- `file_write` handler 在 `resolve_workspace_path` 之后调用 `check_write_denied`，命中则返回错误
- `PolicyEngine._validate_paths` 对 file_write 增加写 deny 预检

**独立可测：** 纯函数单测断言 deny 集合 / 前缀；handler 集成测试断言拦截。

### FR-F2：凭证文件读 deny

**As a** HeAgent 操作者,
**I want** `file_read` 拦截对 secret-bearing 文件（`.env` 等）的读取,
**So that** API key 不会原样进入 LLM 上下文。

**Consequences:**

- `path_safety.py` 新增纯函数 `build_read_denied_basenames() -> set[str]`（`.env`、`.env.local`、
  `.env.development`、`.env.production`、`.env.test`、`.env.staging`、`.envrc` 等）
- `path_safety.py` 新增 `check_read_denied(path) -> str | None`（按 basename 精确匹配；后续可扩展
  凭证 store 绝对路径如 `~/.heagent/auth.json`）
- `file_read` handler 在 `resolve_workspace_path` 之后调用 `check_read_denied`，命中则返回错误
  （提示「请读 .env.example」）
- `PolicyEngine._validate_paths` 对 file_read 增加读 deny 预检

**独立可测：** 纯函数单测断言 basename 集合；handler 集成测试断言拦截。

### FR-F3：凭证环境变量 scrubbing

**As a** HeAgent 操作者,
**I want** shell 子进程 spawn 前剥离敏感环境变量,
**So that** `shell("env")` / `shell("curl ...")` 不能泄出 API key。

**Consequences:**

- `sandbox.py` 新增纯函数 `scrub_sensitive_env(env: Mapping[str, str] | None = None) -> dict[str, str]`
  —— 默认从 `os.environ` 取，剥离键匹配敏感模式（`*_API_KEY`、`*_API_KEYS`、`*_TOKEN`、
  `*_SECRET`、`*_PASSWORD`、`*_CREDENTIALS`、`*_PRIVATE_KEY` 等，大小写不敏感）的变量，透传其余
- `_run_subprocess_shell` / `_run_subprocess_exec` 传 `env=scrub_sensitive_env()`（两者都改）
- `PassthroughRunner` / `FirejailBackend` / `WinJobBackend` 无需改——它们都经这两个 helper spawn

**独立可测：** 纯函数单测断言敏感键被剥离、非敏感键透传；集成测试 mock `create_subprocess_shell`
验证传入的 env 不含 API key。

### FR-F4：`.heagent/` 内部状态读 deny

**As a** HeAgent 操作者,
**I want** `file_read` / `search` 拦截对 `.heagent/` 内部状态的读取,
**So that** 内部状态文件不进入 LLM 上下文（防注入载体 / 记忆污染）。

**Consequences:**

- `path_safety.py` 新增纯函数 `build_internal_state_dirs() -> set[str]`（`.heagent/sessions`、
  `.heagent/ledger`、`.heagent/memory`、`.heagent/skills` 等运行时状态子目录）
- `check_read_denied(path)` 扩展：路径命中内部状态目录 → 返回 deny 原因
- `file_read` / `file_search` handler 在围栏后调用 `check_read_denied`
- `PolicyEngine._validate_paths` 对 file_read / file_search 增加内部状态读 deny 预检

**独立可测：** 纯函数单测断言目录集合；handler 集成测试断言拦截。

### FR-F5：安全声明 + 文档同步

**As a** HeAgent 维护者,
**I want** CLAUDE.md / AGENTS.md / docs/frame.md / docs/iteration.md 同步更新,
**So that** 本轮防护不会让人误以为凭证 deny 变成了安全边界。

**Consequences:**

- `CLAUDE.md` / `AGENTS.md` 安全声明新增「文件安全与凭证防护（2026-08-24）」段：覆盖凭证 deny
  / env scrub / 内部状态读 deny；明确声明均为 defense-in-depth、非真正边界（shell 可 `cat .env`
  绕过）
- `docs/frame.md` 4.x 新增 path_safety 凭证 deny 描述 + 第五章已知缺口更新
- `docs/iteration.md` 时间线 + 周期记录

## 5. Non-Functional Requirements

| NFR | 描述 | 验证方式 |
|-----|------|----------|
| **NFR-F1** | **零回归**：非凭证文件读写、shell 非敏感场景行为不变，全部 1052 测试保持绿 | `pytest` 全量通过，`ruff` / `mypy` clean |
| **NFR-F2** | **安全声明诚实**：deny / scrub 均非真正边界 | diff 审查新文档文本 |
| **NFR-F3** | **确定性单测**：deny 规则 / scrub 为纯函数、不触达 LLM | 单元测试直接断言函数输出 |
| **NFR-F4** | **模块边界**：改动限 `path_safety.py` / `sandbox.py` / `policy.py` / `file.py` + 文档；不反依赖 agent/providers/memory | import 审查 + DAG 验证 |
| **NFR-F5** | **测试覆盖**：每个 FR 至少 1 个独立单测 + 1 个集成/端到端测试 | coverage review |

## 6. Success Metrics

| SM | 指标 | 目标 |
|----|------|------|
| **SM-1** | 零回归 | 全部 1052 已有测试保持绿 |
| **SM-2** | 凭证不入上下文 | `file_read(".env")` 被拦截，API key 不返回 |
| **SM-3** | 凭证不入子进程 | `shell("env")` 输出不含 `*_API_KEY` |
| **SM-4** | 内部状态不入上下文 | `file_read(".heagent/...")` 被拦截 |
| **SM-5** | 安全声明更新 | CLAUDE.md / AGENTS.md / frame.md / iteration.md 同步 |

### SM counter-metric（防过度自信）

- **SM-C1**：不因凭证 deny 的存在而放行本该被围栏 BLOCKED 的越界访问——deny 与围栏独立，不互相覆盖。
- **SM-C2**：非敏感环境变量（`PATH` / `HOME` / `LANG`）不被误剥——shell 工具可用性不退化。

## 7. Assumptions & Open Questions

### Assumptions

- **[A1]** 凭证 deny 规则表内置为纯函数，本轮不提供 `.env` 级配置入口（D-1）。
- **[A2]** env scrubbing 按敏感模式剥离（`*_API_KEY` / `*_TOKEN` 等），非白名单透传（D-3）。
- **[A3]** `.heagent/` 内部状态 deny 只覆盖「读」，不覆盖「写」（D-4）。
- **[A4]** `Path.home()` 用于解析 `~` 前缀（`~/.ssh` 等），测试用 `monkeypatch` 固定 home。

### Open Questions

- **[Q1]** `scrub_sensitive_env` 的敏感模式集合是否需覆盖更多（如 `*_CLIENT_SECRET` / `*_PASSPHRASE`）？
  当前取 7 类，后续可扩展。
- **[Q2]** 读 deny 是否需要覆盖 `~/.heagent/auth.json` 等凭证 store 的绝对路径（hermes 有此）？
  本轮先做 basename 匹配 + 内部状态目录，凭证 store 绝对路径 deferred。

## 8. Implementation Notes

### 改动文件清单

| 文件 | 改动类型 | 关联 FR |
|------|----------|---------|
| `src/heagent/tools/path_safety.py` | **核心改动**：凭证写/读 deny 规则表 + check 函数 + 内部状态读 deny | FR-F1, F2, F4 |
| `src/heagent/tools/sandbox.py` | **核心改动**：`scrub_sensitive_env` + spawn 点传 env | FR-F3 |
| `src/heagent/engine/policy.py` | 小改：`_validate_paths` 增加凭证 deny 预检 | FR-F1, F2, F4 |
| `src/heagent/tools/builtins/file.py` | 小改：handler 增加 deny 守卫 | FR-F1, F2, F4 |
| `src/heagent/tools/builtins/search.py` | 小改：search handler 增加内部状态读 deny | FR-F4 |
| `tests/test_path_safety.py`（或 test_coverage_*） | **新增**：deny 规则单测 + 集成测试 | FR-F1~F4 |
| `tests/test_sandbox.py` | 扩展：scrub_sensitive_env 单测 + spawn env 集成测试 | FR-F3 |
| `tests/test_engine_p0.py` | 扩展：policy 预检 deny 测试 | FR-F1, F2, F4 |
| `CLAUDE.md` / `AGENTS.md` | 安全声明更新 | FR-F5 |
| `docs/frame.md` / `docs/iteration.md` | 文档同步 | FR-F5 |

### 现有测试不变量（必须保持绿）

- `tests/test_sandbox.py` 全部现有测试
- `tests/test_shell.py` 全部 shell 工具测试
- `tests/test_engine_p0.py` 全部 executor/policy 测试
- `tests/test_config.py` 全部配置测试
- `tests/test_git_tools.py` / `tests/test_file_search.py` 全部 file/git/search 工具测试
