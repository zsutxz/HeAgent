---
stepsCompleted: ["step-01-requirements-extraction", "step-02-design-epics", "step-03-create-stories"]
inputDocuments:
  - _bmad-output/robustness-hardening/brief.md
  - _bmad-output/robustness-hardening/prd.md
  - _bmad-output/robustness-hardening/ARCHITECTURE-SPINE.md
cycle: robustness-hardening
project: HeAgent
created: 2026-07-21
---

# HeAgent 健壮性与质量硬化 — Epic Breakdown

## Overview

本周期两个 Epic（A / C），互相正交，可并行开发。编号延续主线：Epic 18-19。

## FR Coverage Map

| FR | Epic | 说明 |
|----|------|------|
| FR-A1 | Epic A | 跨进程文件锁 |
| FR-A2 | Epic A | Cron 范围表达式 |
| FR-A3 | Epic A | Windows 沙箱后端 |
| FR-A4 | Epic A | 安全声明更新 |
| FR-A5 | Epic A | Sandbox 死代码清理 |
| FR-C1 | Epic C | 测试覆盖率 80%→90% |
| FR-C2 | Epic C | CI 多平台矩阵 |
| FR-C3 | Epic C | 静态分析硬化 |
| FR-C4 | Epic C | 性能基准回归 |
| FR-C5 | Epic C | 代码复杂度治理 |
| FR-C6 | Epic C | 文档与版本号同步 |

---

## Epic A: 健壮性硬化

把既有系统三个已知缺口补齐——跨进程文件锁、Cron 范围表达式、Windows 沙箱。
不改架构、不加新依赖。全 `stdlib` 实现。

### Story A.1: 跨进程文件锁（`persist.py` + `EngineContainer`）

As a HeAgent 开发者,
I want `atomic_write_text` 支持可选的跨进程文件锁,
So that 多进程/多 loop 并发写 `.heagent/` 不损坏 checkpoint 数据。

**Acceptance Criteria:**

**Given** `persist.py::atomic_write_text` 新增 kwargs `lock` 和 `lock_timeout`
**When** `lock=False`（默认）调用
**Then** 行为与 V1 完全一致（零回归）

**Given** `lock=True` 且 platform 支持文件锁
**When** 两个进程同时对相同 path 调用 `atomic_write_text(path, content, lock=True)`
**Then** 串行执行：第一个完成后第二个才开始写，最终文件反射最后一次写入的完整内容（无交错/半写）

**Given** `lock=True` 且锁被另一个进程持有超过 `lock_timeout` 秒
**When** 调用 `atomic_write_text`
**Then** 抛 `OSError`（超时），不无限阻塞

**Given** `EngineContainer` 新增 `enable_file_locks: bool = False`
**When** `enable_file_locks=True`
**Then** `RunStore.save()` 和 `ExecutionLedger.complete()` 自动传 `lock=True`

**Given** 平台自适应锁实现
**When** `sys.platform == "linux"` or `"darwin"`
**Then** 使用 `fcntl.flock`（POSIX）
**And** `sys.platform == "win32"` → 使用 `msvcrt.locking`（Windows）

**Given** 并发写入测试
**When** 两个 asyncio task 并发写同一个 run_id
**Then** 最终文件内容完整（非交错），且无 `FileNotFoundError`/`PermissionError` 泄漏

### Story A.2: Cron 范围表达式

As a HeAgent 用户,
I want Cron 支持 `1-5` 范围和 `*/15` 步进语法,
So that 能表达 "工作日 9-17 点每 30 分钟" 等日常调度模式。

**Acceptance Criteria:**

**Given** `CronParser._parse_field` 统一解析入口
**When** 传入 `"1-5"` 和分钟范围 `(0, 59)`
**Then** 返回 `[1, 2, 3, 4, 5]`
**And** `_match_field(3, "1-5")` → True；`_match_field(6, "1-5")` → False

**Given** `"*/15"` 步进语法
**When** `_parse_field("*/15", 0, 59)`
**Then** 返回 `[0, 15, 30, 45]`

**Given** `"1-30/10"` 范围+步进组合
**When** `_parse_field("1-30/10", 1, 31)`
**Then** 返回 `[1, 11, 21]`

**Given** Cron 表达式 `"*/15 9-17 * * 1-5"`
**When** 解析并匹配 `datetime(2026, 7, 22, 10, 0)`（周三，在 1-5）
**Then** `matches()` → True（分钟 0 在 0,15,30,45；小时 10 在 9-17；星期 3 在 1-5）

**Given** 非法表达式
**When** `_parse_field("a-b", 0, 59)` 或 `_parse_field("1-100", 0, 59)`
**Then** 抛 `ValueError`

**Given** 既有简单表达式
**When** `"*"` / `"1,2,3"` / `"*/2"`（步进在 V1 已支持）
**Then** 行为零回归

**Given** croniter 对齐测试
**When** 对相同表达式跑 HeAgent 和 croniter 的匹配结果
**Then** 断言一致（参数化覆盖 20+ 种表达式）

### Story A.3: Windows 沙箱后端（WinJobBackend）

As a Windows 上的 HeAgent 用户,
I want 一个非透传的沙箱后端,
So that shell 命令执行有基本的进程级隔离（而非裸跑在宿主进程环境）。

**Acceptance Criteria:**

**Given** `tools/sandbox.py::WinJobBackend` 实现 `CommandRunner` protocol
**When** `sys.platform == "win32"`
**Then** `WinJobBackend.available()` → True
**And** `sys.platform != "win32"` → False

**Given** `WinJobBackend.run("echo hello")` 在 Windows 上
**When** 调用
**Then** 返回 `"hello\n"`（或含 exit_code），子进程正常退出

**Given** 父进程异常退出
**When** Job Object 配置了 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`
**Then** 子进程被 OS 自动终止（不残留孤儿进程）

**Given** `WinJobBackend` 不可用（非 Windows 或 API 调用失败）
**When** CLI 或 EngineContainer 检测到 `not WinJobBackend.available()`
**Then** 输出 WARNING + fallback 到 `Passthrough`（优雅降级，不崩溃）

**Given** CLI `--sandbox winjob` 和 `.env` `SANDBOX_BACKEND=winjob`
**When** Windows 上启动
**Then** `EngineContainer` 注入 `WinJobBackend()` 作为 `command_runner`

**Given** `WinJobBackend.run` 的 timeout/cancel 行为
**When** 取消 task 或 timeout 触发
**Then** 子进程被 kill（`TerminateProcess`），`wait` 回收，Job Object handle 在 finally 关闭

**Given** `WinJobBackend` 与 `FirejailBackend` 对称性
**When** 审查两个类的公开接口
**Then** 签名一致（`available()` / `run(command, *, timeout, workspace_root)`），
  可互相替换（`CommandRunner` protocol 满足）

### Story A.4: 安全声明更新 + sandbox 死代码清理

As a HeAgent 操作者,
I want CLAUDE.md / docs/frame.md 的安全声明反映硬化后的现状,
So that Windows 沙箱、文件锁等新能力被正确披露，且 sandbox 无死代码残留。

**Acceptance Criteria:**

**Given** CLAUDE.md 安全声明章节
**When** 审查 engine sandbox 后端说明
**Then** 覆盖 `WinJobBackend`（Windows Job Objects，进程级隔离，非完美边界）
**And** 文件锁声明（defense-in-depth，防数据损坏不防恶意进程）

**Given** `docs/frame.md` 已知缺口（第五章）
**When** 更新
**Then** 文件锁 → 标记「已交付（可选锁，EngineContainer 开关，默认关闭）」
**And** Windows sandbox → 标记「已交付 WinJobBackend（Windows 进程级隔离，非完美边界）」
**And** Cron 范围表达式 → 移除缺口清单

**Given** `tools/sandbox.py`
**When** 审查 `_PROFILE_MAP`、`SandboxProfileSlot`、`build_argv`
**Then** 确认无未使用分支 / 无 dead code（FR-A5）

**Given** `docs/iteration.md`
**When** 更新时间线
**Then** 新增本周期条目（2026-07-21，健壮性与质量硬化）

---

## Epic C: 质量工程化

拉高工程质量基线——覆盖率 90%、CI 三平台、静态分析加严、性能基准。

### Story C.1: 测试覆盖率 80%→90%

As a HeAgent 开发者,
I want 项目测试覆盖率 ≥90% 且 CI 硬拦,
So that 回归风险低、重构有信心。

**Acceptance Criteria:**

**Given** `pyproject.toml` 的 `--cov-fail-under=80`
**When** 改为 `90`
**Then** CI 在覆盖率 <90% 时失败

**Given** 覆盖率缺口模块
**When** 审查覆盖率报告（`pytest --cov=heagent --cov-report=term-missing`）
**Then** 每个模块至少 80%，整体 ≥90%

**Given** 新增测试目标
**When** 补齐以下未覆盖路径
**Then** 每个路径至少 1 个测试：
- `engine/persist.py`：锁超时 `OSError`、锁获取后写入失败不泄漏锁
- `engine/executor.py`：`execute()` 传入未知 verdict 模式
- `engine/observability.py`：事件 buffer 满时 emit 行为、subscriber 异常隔离
- `memory/skills.py`：`record_usage` 在 `asyncio.to_thread` 中的并发安全性
- `cli.py`：交互模式 `KeyboardInterrupt` 恢复、`EOFError` 退出
- `agent/tool_execution.py`：handler 内抛 `CancelledError` 正确传播

**Given** 既存测试
**When** 运行全量 pytest
**Then** 全绿（零回归）

### Story C.2: CI 多平台矩阵

As a HeAgent 开发者,
I want CI 在 Linux + Windows + macOS + Python 3.11/3.12/3.13 上跑,
So that 跨平台兼容性被持续验证。

**Acceptance Criteria:**

**Given** `.github/workflows/ci.yml`
**When** 扩展 matrix
**Then** `os: [ubuntu-latest, windows-latest, macos-latest]` × `python: ["3.11", "3.12", "3.13"]`

**Given** sandbox 测试的平台可用性
**When** 在非 Linux 平台运行 FirejailBackend 测试
**Then** 自动 skip（`pytest.skip` 或 marker 标记）
**And** Windows 平台 WinJobBackend 测试正常执行
**And** macOS 平台仅 Passthrough 测试执行

**Given** 全矩阵 CI
**When** push 触发
**Then** 所有 9 个 job 通过（或明确 skip 的合理跳过）

**Given** `fail-fast: false`
**When** 单个平台失败
**Then** 其他平台仍继续执行、报告完整结果

**Given** 覆盖率报告
**When** 多平台合并
**Then** 上传 artifact → `coverage combine` → 统一报告

### Story C.3: 静态分析硬化

As a HeAgent 开发者,
I want Ruff 启用更多规则 + Bandit 安全扫描 + pip-audit,
So that 潜在 bug、安全漏洞、依赖风险被提前发现。

**Acceptance Criteria:**

**Given** `ruff.toml` 或 `pyproject.toml [tool.ruff]`
**When** 启用新规则集
**Then** `select` 扩展为：`["E", "F", "I", "N", "W", "UP", "B", "C90", "S", "SIM", "TCH"]`
**And** `mccabe.max-complexity = 15`

**Given** 既有代码
**When** 运行 `ruff check`
**Then** 零告警（或超标函数有 `# noqa: C901` + 合理注释）

**Given** `bandit -r src/`
**When** CI 加 step
**Then** 零 MEDIUM+ 告警（`-ll` 过滤 LOW）
**And** 排除 `B101`（assert 在测试中合理）

**Given** `pip-audit`
**When** CI 加 step
**Then** 不报 CRITICAL；LOW 告警记录但不 fail

**Given** `.pre-commit-config.yaml`
**When** 同步新规则 → `pre-commit run --all-files`
**Then** 全量通过

### Story C.4: 性能基准 + 复杂度治理

As a HeAgent 开发者,
I want 有性能基准测试和复杂度治理,
So that 重构不引入性能回归，关键路径可读性可控。

**Acceptance Criteria:**

**Given** `tests/test_benchmarks.py`
**When** 包含 benchmark 测试
**Then** `test_token_estimation_accuracy`（误差 ≤20% vs tiktoken 真值）
**And** `test_compression_efficiency`（压缩率 ≥50%）
**And** `test_tool_registration_perf`（100 tools < 10ms）

**Given** 复杂度超标函数
**When** 审查 `ruff check --select=C90`
**Then** 每个超标函数：要么拆到合理边界，要么加注释解释复杂度来源
**And** `agent/loop.py` 评估拆分但**不强求**（C901 注释可接受）

**Given** benchmark 在 CI
**When** 跑 `pytest --benchmark-skip`（默认）
**Then** 跳过 benchmark（不增加 commit CI 时间）
**And** 手动 `pytest -m benchmark` 可跑完整基准

### Story C.5: 文档与版本号同步

As a HeAgent 维护者,
I want 所有文档与代码同步更新,
So that 版本号、迭代时间线、已知缺口、安全声明全部反映最新状态。

**Acceptance Criteria:**

**Given** `pyproject.toml`
**When** bump version
**Then** 从当前版本号加 minor bump（如 `0.8.0`）

**Given** `docs/frame.md`
**When** 更新
**Then** 已知缺口（第五章）反映 Epic A 交付后的状态
**And** 技术规范（第八章）更新 CI matrix

**Given** `docs/iteration.md`
**When** 更新时间线（二）
**Then** 新条目：2026-07-21 → 健壮性与质量硬化周期（Epic 18-19）

**Given** `CLAUDE.md`
**When** 更新
**Then** 已知缺口列表反映硬化后的状态
**And** 安全声明覆盖 `WinJobBackend` + 文件锁

**Given** `sprint-status.yaml`
**When** 新建维护
**Then** `_bmad-output/robustness-hardening/sprint-status.yaml` 跟踪 Epic 18/19 的 story 状态

---

## FR → Story 覆盖核对

| FR | Story | 说明 |
|----|-------|------|
| FR-A1 | A.1 | 跨进程文件锁 |
| FR-A2 | A.2 | Cron 范围表达式 |
| FR-A3 | A.3 | Windows 沙箱后端 |
| FR-A4 | A.4 | 安全声明更新 |
| FR-A5 | A.4 | Sandbox 死代码清理 |
| FR-C1 | C.1 | 测试覆盖率 80%→90% |
| FR-C2 | C.2 | CI 多平台矩阵 |
| FR-C3 | C.3 | 静态分析硬化 |
| FR-C4 | C.4 | 性能基准回归 |
| FR-C5 | C.4 | 代码复杂度治理 |
| FR-C6 | C.5 | 文档与版本号同步 |

12/12 FR 全覆盖。
