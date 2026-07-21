---
stepsCompleted: ["step-01-requirements-extraction", "step-02-design-epics"]
inputDocuments:
  - _bmad-output/robustness-hardening/brief.md
  - _bmad-output/robustness-hardening/prd.md
cycle: robustness-hardening
project: HeAgent
created: 2026-07-21
---

# HeAgent 健壮性与质量硬化 — Architecture

> 承重决策（AD）与模块级设计。无新 DAG 依赖——全部改动在叶子模块（`engine/persist.py`、`cron/jobs.py`、
> `tools/sandbox.py`）或 CI 配置（`.github/workflows/`）。

---

## 1. 架构承重决策 (AD)

### AD-1 · 文件锁 API 设计（FR-A1）

**决策：** `atomic_write_text(path, content, *, lock=False, lock_timeout=5.0)` ——
最小侵入，向后兼容。

**设计：**
```
persist.py

_acquire_lock(fd, timeout) -> None    # 平台自适应（POSIX fcntl / Windows msvcrt）
_release_lock(fd) -> None

atomic_write_text(path, content, *, lock=False, lock_timeout=5.0):
    if lock:
        fd = os.open(path + ".lock", os.O_CREAT | os.O_RDWR)
        _acquire_lock(fd, lock_timeout)
    try:
        # 原有逻辑：tmp write + os.replace
    finally:
        if lock:
            _release_lock(fd)
            os.close(fd)
```

**关键约束：**
- 锁文件与目标文件分离（`foo.json.lock`），不与数据文件混用
- 锁获取超时抛 `OSError`（不静默等待、不无界阻塞）
- 调用方（`RunStore.save` / `ExecutionLedger.complete`）传 `lock=self._enable_locks`
- `EngineContainer.__init__(enable_file_locks=False)` 默认关闭
- `EngineContainer.default()` 仍在 `__init__` 中隐式关着（单进程默认无需锁）
- `subprocess` 或 `task_parallel` 场景需用户显式 `EngineContainer(enable_file_locks=True)`

**为什么不用 `fcntl.flock` 直接锁数据文件：** 因为 `os.replace` 是 inode 级原子替换——
锁放在 `.lock` 文件避免 replace 后 fd 指向旧 inode、锁失效的竞态。

### AD-2 · Cron 解析器扩展方案（FR-A2）

**决策：** 在 `_match_field` 周围加 `_parse_field` → `_expand_field` pipeline，
不改现有 5 字段结构。

**设计：**
```
jobs.py::CronParser

_parse_field(raw: str, min_val: int, max_val: int) -> list[int]:
    # 统一入口，把 "*" / "*/15" / "1,2,3" / "1-5" / "1-30/10" 解析为展开列表

_expand_range(raw: str, min_val: int, max_val: int) -> list[int]:
    # "1-5" → [1,2,3,4,5]
    # "*/15" → [0,15,30,45]
    # "1-30/10" → [1,11,21]

_match_field(value: int, pattern: str) -> bool:
    # 改为：parsed = _parse_field(pattern, ...); return value in parsed
```

**实现要点：**
- 纯函数，输入 `str + int + int` → 输出 `list[int]`，零副作用
- 非法输入 → `ValueError`（格式 or 越界）
- 与 croniter 对齐（参数化测试：对每种表达式跑 croniter 等效 → 断言 HeAgent 解析一致）
- `_match_field` 内部改为 `if _is_simple(pattern) else` 的分支——简单 `*`/逗号不加展开开销

### AD-3 · Windows Job Objects 沙箱架构（FR-A3）

**决策：** `WinJobBackend` 作为独立 `CommandRunner` 实现，与 `FirejailBackend` 对称。
用 ctypes 调用 Windows Job Object API，不引入 `pywin32`。

**设计：**
```
sandbox.py

_WIN32_JOB_ACCESS = 0x1F001F  # JOB_OBJECT_ALL_ACCESS

_kernel32 = ctypes.windll.kernel32  # Windows-only

class WinJobBackend:
    """Windows Job Objects 沙箱后端。"""
    
    def __post_init__(self):
        # 惰性加载 kernel32 DLL
    
    def available() -> bool:
        # sys.platform == "win32"
    
    async def run(self, command: str, ...) -> str:
        # 1. CreateJobObject → hJob
        # 2. SetInformationJobObject(hJob, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        # 3. Popen with CREATE_SUSPENDED
        # 4. AssignProcessToJobObject(hJob, proc._handle)
        # 5. ResumeThread
        # 6. communicate (with timeout/cancel)
        # 7. finally: CloseHandle(hJob)
    
    def __repr__(self):
        return f"WinJobBackend(available={self.available()})"
```

**关键约束：**
- `available()` 在 `sys.platform != "win32"` 返回 False，不尝试导入 ctypes
- 不可用时 **warn + fallback Passthrough**（在 EngineContainer 或 CLI 层做降级）
- `killpg` 等价：Windows Job Object 自带 KILL_ON_JOB_CLOSE，进程退出自动清理
- 命令用 `subprocess.Popen(["cmd", "/c", command])`（Windows shell）
- workspace 隔离：`JOB_OBJECT_UILIMIT_HANDLES` 设 `:0` 禁止 USER 句柄（不接桌面）

**为什么不用 WSL2 / Docker：** 需用户额外安装，依赖太重。Job Objects 是 Windows 内核内置、
零配置。局限是仅进程级隔离（不像 Firejail 有 FS 隔离），但已远超 Passthrough。

### AD-4 · CI 矩阵架构（FR-C2）

**决策：** 全组合矩阵 3×3 = 9 jobs + 1 optional integration job。用 `include`/`exclude`
控制 sandbox 相关测试的平台可用性。

**设计：**
```yaml
# .github/workflows/ci.yml
strategy:
  matrix:
    os: [ubuntu-latest, windows-latest, macos-latest]
    python: ["3.11", "3.12", "3.13"]
  fail-fast: false

# Sandbox 测试仅在原生平台跑真后端：
#   ubuntu → FirejailBackend tests
#   windows → WinJobBackend tests
#   macos → 仅 Passthrough（无原生沙箱后端）

# 覆盖率报告合并（上传 artifact → download + coverage combine → 统一报告）
```

### AD-5 · 静态分析规则集策略（FR-C3）

**决策：** 渐进启用新规则，不一次性打开导致大面积重构。

| 规则集 | 目标 | 策略 |
|--------|------|------|
| `B` (bugbear) | bug 检测 | 全量启用，逐个 fix |
| `C90` (mccabe) | 圈复杂度 | max-complexity=15，超标函数加 `# noqa: C901` + 理由注释 |
| `S` (bandit) | 安全扫描 | 启用但排除 `S101`（assert 在测试中）、`S104`（bind all） |
| `SIM` (simplify) | 简化建议 | 全量启用，auto-fix |
| `TCH` (type-checking) | 导入检查 | 启用 `TCH004`（仅 type-checking 下导入），修复循环导入隐含 |

### AD-6 · 测试覆盖率策略（FR-C1）

**决策：** 先 `--cov-report=json` 出每个模块的覆盖率 gap，再按 gap 大小排序逐个补。
不盲目加测试——每个新增测试必须覆盖一个现有未覆盖分支。

**目标清单（按模块）：**
| 模块 | 当前覆盖（估） | 目标 | 关键未覆盖路径 |
|------|---------------|------|---------------|
| `engine/persist.py` | 90% | 95% | 锁超时、锁释放异常 |
| `engine/executor.py` | 85% | 92% | 并发 lease、custom runner 异常 |
| `engine/observability.py` | 70% | 85% | 事件 buffer 满、subscriber 异常 |
| `memory/skills.py` | 80% | 90% | 并发 record_usage、损坏 SKILL.md |
| `cli.py` | 60% | 80% | 异常路径、交互中断恢复 |
| `agent/tool_execution.py` | 85% | 92% | CancelledError 传播、handler 抛异常 |

---

## 2. 数据流（不变）

本周期无新数据流——所有改动是既有路径的**加固**，不引入新消息管道、不改变 LLM↔Tool 循环。
文件锁加在持久化层（`persist.py`）的 I/O 边界，Cron Parser 纯计算层，Windows Sandbox 是
`CommandRunner` 的另一实现。

---

## 3. DAG 影响

```
exceptions  types  config
    ↑          ↑       ↑
    └─ providers ─┴── tools ─┴── context ── engine ── agent
                            ↑              ↑
                        memory ───── cron ──┘
```

- `engine/persist.py`：加锁逻辑，无新 import（仅 stdlib）
- `cron/jobs.py`：parser 扩展，无新 import
- `tools/sandbox.py`：加 `WinJobBackend` 类，新 import `ctypes`（stdlib）— **不改 DAG 结构**
- CI：仅在 `.github/` 和 `pyproject.toml`

---

## 4. 关键接口契约

### 4.1 `atomic_write_text` 签名变更

```python
# Before (V1):
async def atomic_write_text(path: Path, content: str) -> None: ...

# After (V2):
async def atomic_write_text(
    path: Path,
    content: str,
    *,
    lock: bool = False,
    lock_timeout: float = 5.0,
) -> None: ...
```

**调用方改动（向后兼容，lock 默认 False）：**
- `RunStore.save()` → `atomic_write_text(path, content, lock=self._enable_locks)`
- `ExecutionLedger.complete()` → 同上
- 其他调用方（如 `JobStore`）→ 不传 lock（默认 False，零改动）

### 4.2 `EngineContainer` 新增参数

```python
@dataclass
class EngineContainer:
    workspace_root: Path
    policy: PolicyEngine | None = None
    executor: ToolExecutor | None = None
    store: RunStore | None = None
    ledger: ExecutionLedger | None = None
    event_bus: EventBus | None = None
    sandbox_profile: str | None = None
    command_runner: CommandRunner | None = None
    enable_file_locks: bool = False  # NEW
```

### 4.3 CronParser 内部 API

```python
class CronParser:
    def _parse_field(self, raw: str, min_val: int, max_val: int) -> list[int]:  # NEW
        ...

    def _expand_range(self, raw: str, min_val: int, max_val: int) -> list[int]:  # NEW
        ...

    def _match_field(self, value: int, pattern: str) -> bool:
        # modified: calls _parse_field internally for non-trivial patterns
        ...
```

### 4.4 WinJobBackend

```python
@dataclass
class WinJobBackend:
    """CommandRunner 的 Windows Job Objects 实现。"""
    
    @staticmethod
    def available() -> bool: ...
    
    async def run(
        self,
        command: str,
        *,
        timeout: int = 120,
        workspace_root: Path | None = None,
    ) -> str: ...
```

---

## 5. 安全立场（不变）

本周期所有 hardening 仍是 **defense-in-depth**：
- 文件锁防数据损坏，不防恶意进程
- WinJobBackend 是进程级隔离（非完整 FS/网络沙箱），非真正安全边界
- `SafetyGuard` / `PolicyEngine` 立场不变
- 须 OS 级沙箱兜底的声明不变

**唯一微调：** Windows 开发者从「只能 Passthrough」升级为「Job Objects 基础隔离」，
这是一个质的提升（从零到有），但不在安全边界声明上让步。

---

## 6. 下游

- Epics（`bmad-create-epics-and-stories`）：按 Epic A / Epic C 拆 story。
- quick-dev：按 AD 设计实现。
