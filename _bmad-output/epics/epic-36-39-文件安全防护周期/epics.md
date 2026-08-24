---
stepsCompleted: ["step-01-requirements-extraction", "step-02-design-epics", "step-03-create-stories", "step-04-final-validation"]
inputDocuments:
  - _bmad-output/epics/epic-36-39-文件安全防护周期/brief.md
  - _bmad-output/epics/epic-36-39-文件安全防护周期/prd.md
  - _bmad-output/epics/epic-36-39-文件安全防护周期/architecture.md
cycle: file-safety-hardening
project: HeAgent
---

# HeAgent 文件安全与凭证防护 — Epic Breakdown

> 本文档把文件安全与凭证防护周期（凭证 deny / env scrub / 内部状态读 deny / 文档同步）的
> PRD FR/NFR 与架构承重决策（AD）分解为可实现的 story。FR 编号与 PRD `FR-F*` 对齐；
> AD 编号与 `architecture.md` 对齐。

## Overview

本轮借鉴 hermes `agent/file_safety.py` 的纵深防御设计，在 HeAgent 既有防护层（workspace
围栏 / shell 子进程 spawn）上并列新增：凭证文件写/读 deny、凭证环境变量 scrubbing、
`.heagent/` 内部状态读 deny，并同步安全声明文档。

## Requirements Inventory

### Functional Requirements

> verbatim 自 `prd.md` §4。

- **FR-F1: 凭证文件写 deny** — `path_safety.py` 新增 `build_write_denied_paths` /
  `build_write_denied_prefixes` / `check_write_denied`；file_write handler + policy 预检拦截。
- **FR-F2: 凭证文件读 deny** — `build_read_denied_basenames` / `check_read_denied`；file_read
  handler + policy 预检拦截 secret-bearing 文件名。
- **FR-F3: 凭证环境变量 scrubbing** — `sandbox.py` 新增 `scrub_sensitive_env` 纯函数；
  `_run_subprocess_shell` / `_run_subprocess_exec` 传 `env=scrub_sensitive_env()`。
- **FR-F4: `.heagent/` 内部状态读 deny** — `build_internal_state_dirs`；`check_read_denied`
  扩展；file_read / file_search handler + policy 预检拦截。
- **FR-F5: 安全声明 + 文档同步** — CLAUDE.md / AGENTS.md / frame.md / iteration.md 更新。

### Non-Functional Requirements

> 自 `prd.md` §5。

- **NFR-F1: 零回归** — 非凭证文件读写、shell 非敏感场景行为不变；全部 1052 测试保持绿。
- **NFR-F2: 安全声明诚实** — deny / scrub 均非真正边界。
- **NFR-F3: 确定性单测** — deny 规则 / scrub 为纯函数、不触达 LLM。
- **NFR-F4: 模块边界** — 改动限 `path_safety.py` / `sandbox.py` / `policy.py` / `file.py` /
  `search.py` + 文档。
- **NFR-F5: 测试覆盖** — 每 FR 至少 1 个独立单测 + 1 个集成测试。

### Additional Requirements (Architecture Decisions)

> 自 `architecture.md` 承重决策 AD-F1~AD-F4。

- **AR-1 (AD-F1):** deny 规则与 workspace 围栏并列，不合并进 `resolve_under_root`。
- **AR-2 (AD-F2):** deny 规则表内置为纯函数，不暴露 `.env` 配置。
- **AR-3 (AD-F3):** env scrubbing 是「剥离敏感 key」而非「白名单透传」。
- **AR-4 (AD-F4):** `.heagent/` 内部状态 deny 只覆盖「读」。
- **AR-5 (Stack):** 不新增运行时依赖；Python 3.11+。

### FR Coverage Map

> 5 个 FR 全覆盖。

- **FR-F1** (凭证写 deny) → Epic 36
- **FR-F2** (凭证读 deny) → Epic 36
- **FR-F3** (env scrubbing) → Epic 37
- **FR-F4** (内部状态读 deny) → Epic 38
- **FR-F5** (安全声明同步) → Epic 39

## Epic List

### Epic 36: 凭证文件精确 deny（读 + 写）

新增凭证文件/目录的写 deny 与 secret-bearing 文件名的读 deny，接进 file handler 与 policy
预检。完成后 `file_read(".env")` / `file_write("~/.ssh/id_rsa")` 被拦截。

**FRs covered:** FR-F1, FR-F2
**实现落点:** AD-F1（deny 与围栏并列）+ AD-F2（内置纯函数）。改 `path_safety.py`（规则表 +
check 函数）+ `engine/policy.py`（`_validate_paths` 挂接）+ `tools/builtins/file.py`
（handler 守卫）。
**独立性:** ✅ 无前置依赖。Epic 36 可独立交付核心价值。

### Epic 37: 凭证环境变量 scrubbing

shell 子进程 spawn 前剥离敏感环境变量，防止 `shell("env")` 泄出 API key。

**FRs covered:** FR-F3
**实现落点:** AD-F3（剥离敏感 key）。改 `tools/sandbox.py`（`scrub_sensitive_env` +
两个 spawn helper 传 env）。
**独立性:** ✅ 无前置依赖，可与 Epic 36 并行。

### Epic 38: `.heagent/` 内部状态读 deny

阻止读 `.heagent/` 内部状态（sessions/ledger/memory/skills），防注入载体 / 记忆污染。

**FRs covered:** FR-F4
**实现落点:** AD-F1 + AD-F4（内部状态只读 deny）。改 `path_safety.py`（`build_internal_state_dirs`
+ `check_read_denied` 扩展）+ `engine/policy.py` + `tools/builtins/file.py` / `search.py`。
**独立性:** ⚠️ 依赖 Epic 36 引入的 `check_read_denied` 骨架，建议在 36 后做。

### Epic 39: 安全声明 + 文档同步

同步 CLAUDE.md / AGENTS.md / frame.md / iteration.md，诚实声明 deny/scrub 非真正边界。

**FRs covered:** FR-F5, NFR-F2
**实现落点:** 文档 diff。改 4 个文档。
**独立性:** ⚠️ 依赖 36/37/38 完成，最后做。

---

## Epic 36: 凭证文件精确 deny（读 + 写）

### Story 36-1: path_safety 凭证写 deny 规则表 + check 函数

As a HeAgent 开发者,
I want `path_safety.py` 新增凭证写 deny 规则表与 `check_write_denied`,
So that file_write 能拦截对凭证文件的写入。

**Acceptance Criteria:**

**AC-1（FR-F1 写 deny 精确匹配）**
**Given** `build_write_denied_paths()` 纯函数
**When** 调用
**Then** 返回 `realpath` 集合，含 `~/.ssh/authorized_keys`、`~/.ssh/id_rsa`、`~/.env`、
`.netrc`、`.npmrc`、`.git-credentials`、`/etc/sudoers`、`/etc/passwd`、`/etc/shadow` 等

**AC-2（FR-F1 写 deny 目录前缀）**
**Given** `build_write_denied_prefixes()` 纯函数
**When** 调用
**Then** 返回前缀列表，含 `~/.ssh/`、`~/.aws/`、`~/.gnupg/`、`~/.kube/`、`/etc/sudoers.d/` 等

**AC-3（FR-F1 check_write_denied）**
**Given** `check_write_denied(path)` 纯函数
**When** path 命中精确匹配或目录前缀
**Then** 返回非 None 的 deny 原因；未命中返回 None

### Story 36-2: path_safety 凭证读 deny + file handler 守卫

As a HeAgent 开发者,
I want `path_safety.py` 新增读 deny 与 `check_read_denied`，并接入 file handler,
So that `file_read(".env")` 被拦截、API key 不进入上下文。

**Acceptance Criteria:**

**AC-1（FR-F2 读 deny basename）**
**Given** `build_read_denied_basenames()` 纯函数
**When** 调用
**Then** 返回集合，含 `.env`、`.env.local`、`.env.production`、`.envrc` 等

**AC-2（FR-F2 check_read_denied）**
**Given** `check_read_denied(path)` 纯函数
**When** path 的 basename 命中读 deny 集合
**Then** 返回 deny 原因；未命中返回 None

**AC-3（FR-F2 file handler 守卫）**
**Given** `file_read` handler 在 `resolve_workspace_path` 之后调用 `check_read_denied`
**When** 读 `.env`
**Then** 返回错误提示（不抛异常、不读文件内容）

**AC-4（FR-F1 file_write handler 守卫）**
**Given** `file_write` handler 在 `resolve_workspace_path` 之后调用 `check_write_denied`
**When** 写 `~/.ssh/id_rsa`
**Then** 返回错误提示（不写文件）

### Story 36-3: PolicyEngine._validate_paths 挂接凭证 deny 预检

As a HeAgent 开发者,
I want `_validate_paths` 在围栏预检后挂接凭证 deny 预检,
So that deny 在 policy 层也被预检拦截（与 handler 守卫形成两层纵深防御）。

**Acceptance Criteria:**

**AC-1（FR-F1/F2 policy 预检）**
**Given** `_validate_paths` 对 file_read / file_write 增加 deny 预检
**When** 目标路径命中凭证 deny
**Then** 返回非空 deny reason → 调用方判 BLOCKED

**AC-2（围栏与 deny 独立）**
**Given** 围栏预检与 deny 预检是独立两步
**When** 路径在 workspace 内但命中 deny
**Then** 仍 BLOCKED（deny 不依赖围栏越界）

---
### Story 36-4: SafetyGuard 凭证路径破坏性命令拦截

把凭证写 deny 从 `file_write` 工具层延伸到 shell 命令层：`SafetyGuard` 新增
`_CREDENTIAL_DESTRUCTIVE_PATTERNS`，拦截 `rm` / `mv` / `rmdir` / `unlink` / 重定向 `>` 作用于
凭证路径（`~/.ssh/*` / `.env` / `.aws/*` 等）。补齐 `file_write` deny 覆盖不到的移动/删除面。

---


## Epic 37: 凭证环境变量 scrubbing

### Story 37-1: scrub_sensitive_env 纯函数 + shell spawn 接入

As a HeAgent 操作者,
I want shell 子进程 spawn 前剥离敏感环境变量,
So that `shell("env")` 输出不含 API key。

**Acceptance Criteria:**

**AC-1（FR-F3 scrub 纯函数）**
**Given** `scrub_sensitive_env(env=None)` 纯函数
**When** 传入含 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `GH_TOKEN` / `DB_PASSWORD` 的 dict
**Then** 返回 dict 中这些敏感键被剥离；`PATH` / `HOME` / `LANG` 等非敏感键保留

**AC-2（FR-F3 大小写不敏感）**
**Given** 键名 `deepseek_api_key`（小写）或 `DEEPSEEK_API_KEY`（大写）
**When** scrub
**Then** 都被剥离

**AC-3（FR-F3 spawn 接入）**
**Given** `_run_subprocess_shell` / `_run_subprocess_exec`
**When** 创建子进程
**Then** 传 `env=scrub_sensitive_env()`（子进程环境不含敏感变量）

**AC-4（FR-F3 默认 os.environ）**
**Given** `scrub_sensitive_env()` 无参数
**When** 调用
**Then** 从 `os.environ` 取源并剥离敏感键

---

## Epic 38: `.heagent/` 内部状态读 deny

### Story 38-1: 内部状态读 deny + file/search handler 接入

As a HeAgent 操作者,
I want `file_read` / `file_search` 拦截 `.heagent/` 内部状态读取,
So that 内部状态文件不进入 LLM 上下文。

**Acceptance Criteria:**

**AC-1（FR-F4 内部状态目录）**
**Given** `build_internal_state_dirs()` 纯函数
**When** 调用
**Then** 返回集合，含 `~/.heagent/sessions`、`~/.heagent/ledger`、`~/.heagent/memory`、
`~/.heagent/skills` 等

**AC-2（FR-F4 check_read_denied 扩展）**
**Given** `check_read_denied(path)`
**When** path 命中内部状态目录（精确或子路径）
**Then** 返回 deny 原因；未命中返回 None

**AC-3（FR-F4 handler 接入）**
**Given** `file_read` / `file_search` handler 在围栏后调用 `check_read_denied`
**When** 读 `.heagent/sessions/xxx.json`
**Then** 返回错误提示（不读内容）

---

## Epic 39: 安全声明 + 文档同步

### Story 39-1: 安全声明 + 文档同步

As a HeAgent 维护者,
I want CLAUDE.md / AGENTS.md / frame.md / iteration.md 同步更新,
So that 本轮防护不会让人误以为 deny/scrub 变成了安全边界。

**Acceptance Criteria:**

**AC-1（CLAUDE.md / AGENTS.md）**
**Given** 安全声明章节
**When** 审查
**Then** 新增「文件安全与凭证防护（2026-08-24）」段：覆盖凭证 deny / env scrub / 内部状态读
deny；明确声明均为 defense-in-depth、非真正边界

**AC-2（docs/frame.md）**
**Given** path_safety 章节 + 第五章已知缺口
**When** 审查
**Then** 新增凭证 deny 描述；已知缺口移除已修复条目

**AC-3（docs/iteration.md）**
**Given** 时间线 + 周期记录
**When** 审查
**Then** 新增 file-safety-hardening 周期记录

---

## FR → Story 覆盖核对

| FR | Story | 说明 |
| --- | --- | --- |
| FR-F1 | 36-1, 36-2, 36-3, 36-4 | 凭证写 deny（规则表 + handler + policy 预检 + shell 破坏性命令拦截） |
| FR-F2 | 36-2, 36-3 | 凭证读 deny（规则表 + handler + policy 预检） |
| FR-F3 | 37-1 | env scrubbing（纯函数 + spawn 接入） |
| FR-F4 | 38-1 | 内部状态读 deny |
| FR-F5 | 39-1 | 安全声明 + 文档同步 |

5/5 FR 全覆盖。
