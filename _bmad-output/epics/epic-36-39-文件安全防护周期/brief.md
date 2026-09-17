---
title: "HeAgent 文件安全与凭证防护 — 借鉴 hermes file_safety 的纵深防御"
status: draft
cycle: file-safety-hardening
preceded_by:
  - _bmad-output/epics/epic-S1-S4-沙箱硬化周期/（Epic S1-S4，Sandbox 后端硬化）
  - _bmad-output/epics/epic-29-35-交互扩展周期/（Epic 29-35，审批/会话/斜杠/Hooks/Plan Mode）
created: 2026-08-24
updated: 2026-08-24
---

# Product Brief: HeAgent 文件安全与凭证防护

> **本轮聚焦一个明确的问题：** HeAgent 有工作区路径围栏（`resolve_under_root`）和 shell
> 命令黑名单（`SafetyGuard`），但缺少 hermes-agent 已经落地、且直接对应真实威胁的两类防护——
> **凭证文件的精确 deny（读 + 写）** 与 **凭证环境变量的子进程 scrubbing**。本轮借鉴
> hermes `agent/file_safety.py` 与 `SECURITY.md` 的纵深防御设计，把这两类防护补上。

## 当前状态（一句话）

HeAgent 的文件层防护只有一个维度——**工作区围栏**：

```
file_read / file_write / search / git
    └─ resolve_under_root(path, workspace_root)  →  越界即 WorkspacePathError
    └─ PolicyEngine._validate_paths 预检 + handler 守卫（两层共用同一算法）
```

这个围栏解决的是「LLM 读写 workspace 之外的文件」，但**不解决**以下三类真实威胁：

1. **凭证泄露**：用户在 workspace 内放了 `.env`（含 `DEEPSEEK_API_KEY`），`file_read(".env")`
   会原样返回 API key 进 LLM 上下文；`file_write(".env")` 会覆盖它。
2. **子进程凭证继承**：`shell("env")` 经 `create_subprocess_shell` 未传 `env`，子进程继承完整
   父进程环境（含所有 `*_API_KEY` / `*_TOKEN`），可被 `env` 或 `curl` 直接读走。
3. **内部状态篡改/注入**：`.heagent/` 下的 session 持久化、ledger、memory 文件可被
   `file_read` 读入上下文（污染记忆），可被 `file_write` 篡改（伪造会话历史）。

## 借鉴来源

本轮直接借鉴 hermes-agent `agent/file_safety.py`（已核实源码）与 `SECURITY.md` 的设计，
按 HeAgent 栈（Pydantic / asyncio / 异步模块化单库）改造落地，**不照搬代码**：

| hermes 机制 | HeAgent 落地 |
|-------------|-------------|
| `build_write_denied_paths` / `build_write_denied_prefixes`（凭证写 deny） | `path_safety.py` 新增凭证 deny 规则表 |
| `get_read_block_error`（凭证 store + `.env` 读 deny） | `path_safety.py` 新增读 deny 规则表 |
| 凭证作用域（spawn 子进程前剥离 API key） | `sandbox.py` 子进程 spawn 前 `scrub_sensitive_env` |
| `skills/.hub/index-cache` 读 deny（防 prompt-injection 载体） | `.heagent/` 内部状态读 deny |

## 问题

### 问题 1：workspace 内的 `.env` 可被读写，API key 直接泄露

`resolve_under_root` 只管「路径是否在 workspace 内」，不管「这个文件是不是凭证」。用户项目
里的 `.env` 常规含 API key / DB 密码，`file_read(".env")` 原样返回、`file_write` 可覆盖。
hermes 把这类文件列入写 deny 和读 deny（`.env`、`.netrc`、`.npmrc`、`.git-credentials`、
`~/.ssh/*`、`~/.aws/*` 等），HeAgent 目前没有。

### 问题 2：shell 子进程继承全部环境变量

`_run_subprocess_shell` / `_run_subprocess_exec` 调用 `create_subprocess_*` 时不传 `env`，
子进程默认继承父进程完整环境。`shell("env")` 或 `shell("curl -d @<(env) ...")` 可把
`DEEPSEEK_API_KEY` 等凭证泄出。hermes 在 spawn 低信任子进程前过滤环境变量（默认剥离 key，
白名单透传），HeAgent 目前没有。

### 问题 3：`.heagent/` 内部状态可被读写

`.heagent/` 是 HeAgent 自己的运行时状态目录（session 持久化、ledger 幂等账本、memory 记忆、
skills 元数据）。这些文件若被 `file_read` 读入上下文，可能成为 prompt-injection 载体或污染
记忆；若被 `file_write` 篡改，可伪造会话历史 / 破坏 resume。hermes 把 `state.db`、`sessions/`
、`mcp-tokens/` 等内部状态列入 deny，HeAgent 目前没有。

## 方案

**不引入新架构、不改 agent 循环、不改 PolicyEngine 核心裁决逻辑。全部改动落在既有防护层：**

### P0（核心价值：凭证 deny + env scrub）

**1. 凭证文件精确 deny（读 + 写）**

在 `tools/path_safety.py` 新增两个纯函数规则表，与既有 `resolve_under_root` 并列：

- **写 deny**：`~/.ssh/*`、`~/.aws/*`、`.env`、`.netrc`、`.npmrc`、`.pypirc`、
  `.git-credentials`、`/etc/sudoers` 等（`realpath` 精确匹配 / 目录前缀匹配）
- **读 deny**：`.env`、`.env.local`、`.env.production` 等 secret-bearing 文件名、
  `auth.json`、`~/.ssh/id_*` 私钥等

两层接入：`PolicyEngine._validate_paths` 预检（读 + 写）+ file handler 守卫。

**2. 凭证环境变量 scrubbing**

在 `tools/sandbox.py` 新增 `scrub_sensitive_env()` 纯函数，剥离敏感环境变量（匹配
`*_API_KEY` / `*_API_KEYS` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD` 等模式）；
`_run_subprocess_shell` / `_run_subprocess_exec` 传 `env=scrub_sensitive_env(os.environ)`。

### P1（纵深加固）

**3. `.heagent/` 内部状态读 deny**

在 `path_safety.py` 读 deny 规则表新增 `.heagent/` 内部状态目录（sessions / ledger / memory /
skills 元数据），阻止 `file_read` / `search` 读入这些状态文件进上下文。

### P2（收尾）

**4. 安全声明同步**

`CLAUDE.md` / `AGENTS.md` / `docs/frame.md` / `docs/iteration.md` 更新，诚实声明：凭证
deny 与 env scrub 均为 defense-in-depth，**非真正安全边界**（shell 工具仍可 `cat .env` 绕过）。

---

## 边界

### In Scope（本轮做）

| ID | 内容 | 优先级 |
|----|------|--------|
| F1 | 凭证文件写 deny（精确匹配 + 目录前缀） | P0 |
| F2 | 凭证文件读 deny（secret-bearing 文件名） | P0 |
| F3 | 凭证环境变量 scrubbing（shell 子进程） | P0 |
| F4 | `.heagent/` 内部状态读 deny | P1 |
| F5 | 安全声明 + 文档同步 | P2 |

### Out of Scope（本轮不做）

- ❌ **file 工具走 shell 契约**（hermes 的 terminal-backend 设计）——HeAgent 的 file 工具是
  宿主进程内 async I/O，改走 shell 会损失 offset/limit/encoding 能力且属过度设计；HeAgent
  的立场是「整体 OS 级沙箱兜底」，file 工具在整体沙箱内已被覆盖。
- ❌ **路径级审批分级**（hermes 的 `~/.ssh/config` 审批门控）——HeAgent 的 workspace 围栏已把
  文件操作限制在 workspace 内，路径级审批在 workspace 模型下价值有限，留待未来评估。
- ❌ **MCP server 子进程的 env scrubbing**——本轮只覆盖 shell 工具的 spawn；MCP stdio server
  的 env 处理涉及 MCP 生命周期，deferred。
- ❌ **`HERMES_WRITE_SAFE_ROOT` 等价物**——HeAgent 已有 workspace 围栏（更严格），不需要
  hermes 的 safe-root 白名单机制。
- ❌ **输出脱敏（output redaction）**——hermes 的 `redact.py`，与文件层无关，本轮不做。

### Deferred（未来考虑）

> 2026-09-15 逐条复核完毕：未闭合项统一登记在 [`implementation-artifacts/deferred-work-archive.md`](../../implementation-artifacts/deferred-work-archive.md)（活动台账）；两条经核实「已覆盖、不成立」的已在下方就地标注。

- ✅ MCP stdio server 子进程的 env scrubbing — **已覆盖，不成立（2026-09-15 核实）**：MCP SDK 默认只继承环境**白名单**（`mcp/client/stdio/__init__.py:28,127`；Windows 下仅 APPDATA/HOMEDRIVE/HOMEPATH/LOCALAPPDATA/PATH/PATHEXT/PROCESSOR_ARCHITECTURE/SYSTEMDRIVE/SYSTEMROOT/TEMP/USERNAME/USERPROFILE），不含任何 `*_API_KEY` / `*_TOKEN`；只有 `.mcp.json` 显式声明的 `env` 才会追加 → 不列入待办。
- ✅ cron job 脚本子进程的 env scrubbing — **已覆盖，不成立（2026-09-15 核实）**：`src/heagent/cron/` 无 `Popen` / `create_subprocess_*`（job 在进程内跑 agent run），唯一子进程路径是 run 内的 shell 工具，已被 `tools/sandbox.py` 的 `scrub_sensitive_env` 覆盖 → 不列入待办。
- ⬜ 凭证 deny 规则的用户可配置入口（当前内置规则表，hermes 也是代码内硬编码 + env 变量） — **已登记活动台账（2026-09-15）**：无项目级可配置入口（内置表见 `tools/path_safety.py:89`），可照 `.heagent/injection_signatures.json` 的形状补一个。
- ⬜ 路径级审批分级（若未来引入非 workspace 的受控写场景） — **条件性，已登记活动台账（2026-09-15）**：前置（非 workspace 受控写场景）尚未引入，当前审批粒度为工具级。

---

## 关键决策

### D-1：凭证 deny 规则表内置在 `path_safety.py`，不暴露 `.env` 配置

**选择：** 规则表硬编码为纯函数（`build_write_denied_paths()` / `build_read_denied_basenames()`），
与 hermes 的 `file_safety.py` 一致。

**理由：** 凭证 deny 是安全配置，规则的选择直接影响凭证保护强度。放 `.env` 里易被用户随意
放宽、无 schema 校验。内置规则表保证「默认安全」，用户若需放宽可改代码。

**替代方案（否决）：** `.env` 里逐条配 deny 路径（如 `DENIED_WRITE_PATHS=...`）——脆弱、易配错、
可被用户无意放宽。

### D-2：deny 规则与 workspace 围栏是并列的两层，不合并进 `resolve_under_root`

**选择：** 新增独立函数 `check_credential_access(path, verb)`，在 `resolve_under_root` **之后**
调用（先围栏后 deny）。

**理由：** 两层语义不同——围栏管「位置」（是否在 workspace 内），deny 管「敏感度」（是否是
凭证/内部状态）。合并会让 `resolve_under_root` 承担两个职责、错误信息混在一起。分列可独立
单测、独立演进。

**替代方案（否决）：** 在 `resolve_under_root` 内加 deny 分支——破坏现有调用方（git 工具也调
`resolve_under_root`，不应被凭证 deny 影响）。

### D-3：env scrubbing 是「剥离敏感 key」而非「白名单透传」

**选择：** `scrub_sensitive_env` 按模式匹配剥离敏感 key（`*_API_KEY` / `*_TOKEN` / `*_SECRET`
/ `*_PASSWORD` 等），透传其余环境变量。

**理由：** hermes 是「默认剥离 + 显式白名单透传」，更严格但会破坏大量合法场景（shell 工具常
需要 `PATH` / `HOME` / `LANG` 等）。HeAgent 的 shell 工具定位是「用户可信的本地命令执行」，
按敏感模式剥离在「防护凭证」与「不破坏 shell 工具可用性」之间取得平衡。

**替代方案（否决）：** 完全白名单（hermes 风格）——过度严格，破坏 shell 工具实用价值。

### D-4：`.heagent/` 内部状态 deny 只覆盖「读」，不覆盖「写」

**选择：** 内部状态文件（sessions / ledger / memory）读 deny；写不额外 deny（workspace 围栏已
把写限制在 workspace 内，`.heagent/` 通常不在 workspace 内，已天然被围栏拦截）。

**理由：** 读 deny 的威胁是「注入载体进上下文」——即使 `.heagent/` 在 workspace 内，读入内部
状态也会污染上下文。写方面的威胁（伪造会话）已被 workspace 围栏覆盖（`.heagent/` 默认在
用户 home 下，不在 workspace 内）。

**替代方案（否决）：** 读写都 deny——写 deny 冗余（围栏已拦），增加无谓复杂度。

---

## FR / NFR 摘要

### 功能需求

| FR | 描述 |
|----|------|
| FR-F1 | `path_safety.py` 新增凭证文件写 deny（精确匹配 + 目录前缀），file_write 拦截 |
| FR-F2 | `path_safety.py` 新增凭证文件读 deny（secret-bearing 文件名），file_read 拦截 |
| FR-F3 | `sandbox.py` 新增 `scrub_sensitive_env()`，shell 子进程 spawn 前剥离敏感环境变量 |
| FR-F4 | `.heagent/` 内部状态读 deny（sessions/ledger/memory/skills 元数据） |
| FR-F5 | 安全声明 + 文档同步（CLAUDE.md / AGENTS.md / frame.md / iteration.md） |

### 非功能需求

| NFR | 描述 |
|-----|------|
| NFR-F1 | 零回归：DIRECT 路径 + 非凭证文件读写行为不变，全部 1052 测试保持绿 |
| NFR-F2 | 安全声明诚实：凭证 deny / env scrub 均非真正边界（shell 可绕过） |
| NFR-F3 | 确定性单测：deny 规则 / env scrub 为纯函数、不触达 LLM |
| NFR-F4 | 模块边界：改动限 `path_safety.py` / `sandbox.py` / `policy.py` / `file.py` + 文档 |
| NFR-F5 | 测试覆盖：每 FR 至少 1 个独立单测 + 1 个集成测试 |
