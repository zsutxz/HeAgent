---
name: HeAgent 文件安全与凭证防护 — 借鉴 hermes file_safety 的纵深防御
type: architecture-spine
purpose: build-substrate
altitude: feature
paradigm: brownfield 扩展 — 在既有 `resolve_under_root` 围栏与 `_run_subprocess_*` spawn 点上，新增凭证 deny / env scrub / 内部状态读 deny，不引入新架构、不改 agent 循环
scope: file-safety-hardening 周期（Epic 36 凭证 deny / 37 env scrub / 38 内部状态读 deny / 39 文档同步）
status: final
created: 2026-08-24
updated: 2026-08-24
binds: [FR-F1, FR-F2, FR-F3, FR-F4, FR-F5, NFR-F1, NFR-F2, NFR-F3, NFR-F4, NFR-F5, SM-1, SM-2, SM-3, SM-4, SM-5, SM-C1, SM-C2]
sources:
  - _bmad-output/epics/epic-36-39-文件安全防护周期/brief.md
  - _bmad-output/epics/epic-36-39-文件安全防护周期/prd.md
  - src/heagent/tools/path_safety.py
  - src/heagent/tools/sandbox.py
  - src/heagent/engine/policy.py
  - src/heagent/tools/builtins/file.py
  - src/heagent/tools/builtins/search.py
companions: []
---

# Architecture Spine — HeAgent 文件安全与凭证防护

> 本 spine 只承重「本轮引入的、未来 builder 无法从合规代码读出的不变量」。既有 HeAgent
> 架构（DAG / 执行链 / engine 治理层）权威见 `docs/frame.md`；`resolve_under_root` /
> `_run_subprocess_*` 既有决策见源码——本 spine **继承而非重述**两者。

## Design Paradigm

**brownfield 扩展（在既有防护层上并列新增，非重写）**。本轮不引入新架构、不改 agent 循环、
不改 PolicyEngine 核心裁决顺序。全部增量落在四个既有扩展点：

1. **`path_safety.py`** — 新增凭证写/读 deny 规则表 + `check_*_denied` 函数 + 内部状态读 deny，
   与既有 `resolve_under_root` 围栏**并列**（先围栏后 deny）。
2. **`engine/policy.py` `_validate_paths`** — 在围栏预检之后，挂接凭证 deny 预检（读 + 写）。
3. **`tools/sandbox.py` `_run_subprocess_*`** — 新增 `scrub_sensitive_env`，spawn 时传
   `env=scrub_sensitive_env()`。
4. **`tools/builtins/file.py` / `search.py` handler** — 在 `resolve_workspace_path` 之后，
   调用 `check_*_denied` 守卫。

承重约束：**安全声明诚实**——凭证 deny / env scrub 均**非真正安全边界**（shell 工具仍可
`cat .env` 绕过），仅拦截「合作模式下尊重工具拒绝」的模型。不制造「加了 deny 就安全」的假象。

## Inherited Invariants

| Inherited | From parent | Binds here |
| --- | --- | --- |
| `resolve_under_root(path, root)` 是单一围栏算法，policy 预检与 handler 守卫共用 | `path_safety.py` 已有 | **不改此函数**——deny 是并列的独立层，在围栏之后调用 |
| 工具执行链固定为 `PolicyEngine → ToolExecutor → SafetyGuard → handler` | baseline `frame.md` + CLAUDE.md | 本轮不改执行链顺序；deny 预检发生在 `_validate_paths` 内、handler 守卫发生在 handler 内 |
| `_run_subprocess_shell` / `_run_subprocess_exec` 是 shell 子进程唯一 spawn 点 | `sandbox.py` 已有 | 在 spawn 点统一传 `env=scrub_sensitive_env()`，后端（Passthrough/Firejail/WinJob）零改动 |
| 凭证 deny / env scrub 非真正安全边界 | CLAUDE.md 安全声明 | 本轮延续此立场，文档同步 |

## Invariants & Rules

```
┌─────────────────────────────────────────────────────────────────┐
│                      本轮改动范围（四个扩展点）                      │
│                                                                   │
│  PolicyEngine._validate_paths ──▶ resolve_under_root（围栏）      │
│        │                          └─ 越界 → BLOCKED              │
│        └──────────────▶ check_read_denied / check_write_denied   │
│                              └─ 命中 → BLOCKED（凭证/内部状态）    │
│                                                                   │
│  file_read / file_write / search handler                          │
│        └─ resolve_workspace_path（围栏）                          │
│        └─ check_read_denied / check_write_denied（deny 守卫）     │
│                                                                   │
│  _run_subprocess_shell / _run_subprocess_exec                     │
│        └─ env=scrub_sensitive_env(os.environ)  ← 新增            │
│              └─ 剥离 *_API_KEY / *_TOKEN / *_SECRET ...          │
└─────────────────────────────────────────────────────────────────┘
```

### AD-F1 — deny 规则与 workspace 围栏并列，不合并进 `resolve_under_root`（D-2 定稿）

- **Binds:** FR-F1, FR-F2, FR-F4, NFR-F4, SM-C1
- **Prevents:** 在 `resolve_under_root` 内加 deny 分支会破坏既有调用方（`git.py` 也调
  `resolve_under_root`，不应被凭证 deny 影响）；也防止围栏与 deny 两个语义（位置 / 敏感度）
  混在一起、错误信息不可区分。
- **Rule:** `path_safety.py` 新增独立纯函数：
  - `build_write_denied_paths() -> set[str]`（`realpath` 精确匹配）
  - `build_write_denied_prefixes() -> list[str]`（目录前缀）
  - `check_write_denied(path) -> str | None`（写 deny 检查）
  - `build_read_denied_basenames() -> set[str]`（secret-bearing 文件名）
  - `build_internal_state_dirs() -> set[str]`（`.heagent/` 内部状态目录）
  - `check_read_denied(path) -> str | None`（读 deny 检查，含 basename + 内部状态目录）
  调用顺序固定为「先围栏后 deny」：handler 先 `resolve_workspace_path`（围栏），后 `check_*_denied`
  （deny）；policy 先 `resolve_under_root` 围栏预检，后 deny 预检。

### AD-F2 — deny 规则表内置为纯函数，不暴露 `.env` 配置（D-1 定稿）

- **Binds:** FR-F1, FR-F2, FR-F4, NFR-F3
- **Prevents:** deny 规则暴露 `.env` 会被用户无意放宽、无 schema 校验。
- **Rule:** 规则表硬编码为纯函数（无 I/O、无 contextvar、无外部状态），`Path.home()` 用于解析
  `~` 前缀。测试用 `monkeypatch` 固定 `Path.home()`，直接断言函数输出。

### AD-F3 — env scrubbing 是「剥离敏感 key」而非「白名单透传」（D-3 定稿）

- **Binds:** FR-F3, SM-C2
- **Prevents:** 完全白名单（hermes 风格）会破坏 shell 工具可用性（`PATH` / `HOME` / `LANG` 等
  合法变量被误剥）。
- **Rule:** `scrub_sensitive_env(env=None) -> dict[str, str]` 纯函数，默认从 `os.environ` 取；
  剥离键匹配敏感模式（大小写不敏感）的变量，透传其余。敏感模式集：
  `*_API_KEY` / `*_API_KEYS` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD` / `*_CREDENTIALS` /
  `*_PRIVATE_KEY`。`_run_subprocess_shell` / `_run_subprocess_exec` 传
  `env=scrub_sensitive_env()`。

### AD-F4 — `.heagent/` 内部状态 deny 只覆盖「读」，不覆盖「写」（D-4 定稿）

- **Binds:** FR-F4, SM-C1
- **Prevents:** 写 deny 冗余（workspace 围栏已把写限制在 workspace 内，`.heagent/` 默认在
  home 下、不在 workspace 内，已天然被围栏拦截）。
- **Rule:** `build_internal_state_dirs()` 只被 `check_read_denied` 消费（读 deny）；写 deny 不
  额外覆盖内部状态目录。

## 凭证 deny 规则表（伪代码）

```python
# path_safety.py 新增（纯函数）
def build_write_denied_paths() -> set[str]:
    home = Path.home()
    return {
        str(p.resolve())
        for p in [
            home / ".ssh" / "authorized_keys",
            home / ".ssh" / "id_rsa",
            home / ".ssh" / "id_ed25519",
            home / ".env",
            home / ".netrc",
            home / ".npmrc",
            home / ".pypirc",
            home / ".git-credentials",
            Path("/etc/sudoers"),
            Path("/etc/passwd"),
            Path("/etc/shadow"),
        ]
    }

def build_write_denied_prefixes() -> list[str]:
    home = Path.home()
    return [
        str((home / ".ssh").resolve()) + os.sep,
        str((home / ".aws").resolve()) + os.sep,
        str((home / ".gnupg").resolve()) + os.sep,
        str((home / ".kube").resolve()) + os.sep,
        "/etc/sudoers.d" + os.sep,
        str((home / ".docker").resolve()) + os.sep,
        str((home / ".azure").resolve()) + os.sep,
        str((home / ".config" / "gh").resolve()) + os.sep,
        str((home / ".config" / "gcloud").resolve()) + os.sep,
    ]

def build_read_denied_basenames() -> set[str]:
    return {".env", ".env.local", ".env.development", ".env.production",
            ".env.test", ".env.staging", ".envrc"}

def build_internal_state_dirs() -> set[str]:
    home = Path.home()
    return {
        str((home / ".heagent" / "sessions").resolve()),
        str((home / ".heagent" / "ledger").resolve()),
        str((home / ".heagent" / "memory").resolve()),
        str((home / ".heagent" / "skills").resolve()),
    }

def check_write_denied(path: str) -> str | None:
    resolved = Path(path).expanduser().resolve()
    if str(resolved) in build_write_denied_paths():
        return f"Write denied: '{path}' is a protected credential/system file."
    for prefix in build_write_denied_prefixes():
        if str(resolved).startswith(prefix):
            return f"Write denied: '{path}' is inside a protected directory."
    return None

def check_read_denied(path: str) -> str | None:
    resolved = Path(path).expanduser().resolve()
    if resolved.name.lower() in build_read_denied_basenames():
        return f"Read denied: '{path}' is a secret-bearing environment file. Read .env.example instead."
    for d in build_internal_state_dirs():
        if str(resolved).startswith(d + os.sep) or str(resolved) == d:
            return f"Read denied: '{path}' is internal HeAgent state and cannot be read directly."
    return None
```

以上函数均为**纯函数**——无 I/O、无 contextvar、无 LLM。可独立单测。

## env scrub 算法（伪代码）

```python
# sandbox.py 新增（纯函数）
_SENSITIVE_ENV_SUFFIXES = (
    "_API_KEY", "_API_KEYS", "_TOKEN", "_SECRET", "_PASSWORD",
    "_CREDENTIALS", "_PRIVATE_KEY",
)

def scrub_sensitive_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    source = dict(os.environ if env is None else env)
    return {
        k: v for k, v in source.items()
        if not any(k.upper().endswith(suffix) for suffix in _SENSITIVE_ENV_SUFFIXES)
    }
```

## 测试策略

| 测试类型 | 测试内容 | 不变量 |
|----------|----------|--------|
| **纯函数单测** | `build_write_denied_paths` / `build_write_denied_prefixes` / `build_read_denied_basenames` / `build_internal_state_dirs` 输出 | 无 I/O、无 subprocess |
| **check 函数单测** | `check_write_denied` / `check_read_denied` 命中 / 未命中 | 精确匹配 + 前缀匹配 + basename 匹配 |
| **scrub 纯函数单测** | `scrub_sensitive_env` 剥离敏感键、透传非敏感键 | 大小写不敏感；非敏感键（PATH/HOME/LANG）保留 |
| **spawn 集成测试** | mock `create_subprocess_shell` / `create_subprocess_exec` → 断言传入 env 不含 API key | 两个 helper 都改 |
| **handler 集成测试** | `file_read(".env")` / `file_write("~/.ssh/id_rsa")` / `file_read(".heagent/sessions/...")` 拦截 | 命中返回错误，不抛异常 |
| **policy 预检测试** | `_validate_paths` 命中 deny → BLOCKED | deny 预检与围栏预检独立 |
| **零回归测试** | 全部 1052 个现有测试 | 不新增 failure |

## FR→AD 覆盖核对

| FR | 实现 AD | 测试锚点 |
|----|---------|----------|
| FR-F1 | AD-F1, AD-F2 | `test_check_write_denied_*` |
| FR-F2 | AD-F1, AD-F2 | `test_check_read_denied_*` |
| FR-F3 | AD-F3 | `test_scrub_sensitive_env_*` |
| FR-F4 | AD-F1, AD-F4 | `test_check_read_denied_internal_state` |
| FR-F5 | NFR-F2 | 文档 diff 审查 |

5/5 FR 全覆盖。

## 安全声明（本轮更新）

本轮防护不改变 HeAgent 的安全边界底线。以下声明需同步进 `CLAUDE.md` / `AGENTS.md` /
`docs/frame.md`：

> **文件安全与凭证防护（2026-08-24）：** `path_safety.py` 新增凭证文件写/读 deny（`.env` /
> `~/.ssh/*` / `~/.aws/*` 等）与 `.heagent/` 内部状态读 deny；`sandbox.py` 新增
> `scrub_sensitive_env`，shell 子进程 spawn 前剥离 `*_API_KEY` / `*_TOKEN` 等敏感环境变量。
> 上述均为 defense-in-depth 启发式层，**非真正安全边界**——shell 工具仍可 `cat .env` 绕过，
> 须 OS 级沙箱兜底。

## 与既有架构的交互边界

| 边界 | 约束 |
|------|------|
| `resolve_under_root` | **不改**——deny 是并列独立层，在围栏之后调用 |
| `git.py` | **不受影响**——git 工具只走围栏，不接 deny（D-2 保证） |
| `PolicyEngine` | 裁决顺序**不改**——deny 预检挂接在 `_validate_paths` 内部、围栏之后 |
| `AgentLoop` | **不改**——本轮改动只在 path_safety / sandbox / policy 预检 / file-search handler |
| `CommandRunner` 后端 | **零改动**——env scrub 在 `_run_subprocess_*` 层统一注入，Passthrough/Firejail/WinJob 无感 |
| `SafetyGuard` | **不改**——凭证 deny 与 shell 黑名单是不同维度（文件层 vs 命令层） |
