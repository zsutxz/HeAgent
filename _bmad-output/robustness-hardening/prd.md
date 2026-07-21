---
stepsCompleted: ["step-01-requirements-extraction"]
inputDocuments:
  - _bmad-output/robustness-hardening/brief.md
cycle: robustness-hardening
project: HeAgent
created: 2026-07-21
---

# HeAgent 健壮性与质量硬化 — PRD

## 1. 需求概览

本周期为已有系统的**硬化周期**——不开发新功能，全部 FR 作用于既有的健壮性缺口和质量基线。

| 维度 | 需求数 | 说明 |
|------|--------|------|
| 方向 A · 健壮性 | FR-A1 ~ FR-A5 | 文件锁 / Cron 扩展 / Windows 沙箱 |
| 方向 C · 质量 | FR-C1 ~ FR-C6 | 测试覆盖 / CI 矩阵 / 静态分析 / 性能基准 |

---

## 2. 方向 A：健壮性与安全

### FR-A1：原子写加可选的进程间文件锁

**优先级：P0**

`persist.py` 的 `atomic_write_text` 当前只保证单进程原子性（tmp + `os.replace`），
跨进程并发写同文件时最后写入赢、可能丢失数据。需新增可选的文件锁。

- `atomic_write_text(path, content, *, lock=False)` 新增 kwarg `lock`
- `lock=True` 时，写入前获取平台自适应文件锁（POSIX `fcntl.flock` / Windows `msvcrt.locking`）
- 锁在 `os.replace` 完成后释放
- 锁获取失败（超时/权限）→ 抛 `OSError`（调用方决定重试/放弃）
- 锁超时默认 5 秒，可配置 `lock_timeout` 参数
- `EngineContainer` 新增 `enable_file_locks: bool = False`（默认关闭，单进程场景避免无谓开销）
- 当 `enable_file_locks=True` 时，`RunStore` 和 `ExecutionLedger` 的写操作自动传 `lock=True`

**验收标准：**
- 两个进程同时写同一个 run 文件，锁保证串行、无数据丢失
- 单进程场景（`enable_file_locks=False`）行为零回归
- POSIX 和 Windows 均有对应的锁实现

### FR-A2：Cron 范围表达式

**优先级：P1**

扩展 `CronParser` 支持标准 cron 的范围（`1-5`）和步进快捷（`*/15`）语法。

- `CronParser` 新增 `_expand_range(field, min_val, max_val)` 方法
- `CronParser` 新增 `_parse_field(field, min_val, max_val)` 统一入口，处理 `*`/逗号/范围/步进
- 支持 `1-5` 范围语法（展开为 `[1,2,3,4,5]`）
- 支持 `*/15` 步进快捷（等价于 `0,15,30,45`）
- 支持 `1-30/10` 范围+步进组合（`1,11,21`）
- 非法表达式 → `ValueError`（保持现有 fail-fast 风格）
- 解析结果与 `croniter` 库一致（用参数化测试锁定）

**验收标准：**
- `"1-5"` → 分钟字段在 1,2,3,4,5 匹配
- `"*/15"` → 分钟字段在 0,15,30,45 匹配
- `"*/15 9-17 * * 1-5"` → 工作日 9-17 点每 15 分钟
- 非法表达式 `"a-b"` → `ValueError`

### FR-A3：Windows 沙箱后端

**优先级：P1**

提供 Windows 可用的非透传 `CommandRunner` 实现，让 Windows 开发者也能享受基本子进程隔离。

- 新增 `tools/sandbox.py::WinJobBackend`，实现 `CommandRunner` Protocol
- 使用 Windows Job Objects（`CreateJobObject`/`AssignProcessToJobObject`/`SetInformationJobObject`）
  - `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`：父进程退出时自动杀子孙
  - `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`（可选）：限制最大子进程数
- 子进程管理：`subprocess.Popen` + `creationflags=CREATE_SUSPENDED | CREATE_BREAKAWAY_FROM_JOB`
  → `AssignProcessToJobObject` → `ResumeThread`（race-free 绑定）
- 不可用时优雅降级：检测 Windows API 可用性 → 不可用则 warn + fallback Passthrough
- CLI 支持：`--sandbox winjob`（扩展 `--sandbox` 参数）
- `.env` 支持：`SANDBOX_BACKEND=winjob`

**验收标准：**
- Windows 上 `WinJobBackend.run("echo hello")` → 正常输出
- 父进程异常退出后，job 内子进程被 OS 自动清理（KILL_ON_JOB_CLOSE）
- `WinJobBackend.available()` 在非 Windows 返回 False
- Linux 上 `--sandbox winjob` → warn + fallback Passthrough
- 与 FirejailBackend 同为 `CommandRunner` 实现，互不依赖

### FR-A4：安全声明更新（健壮性硬化）

**优先级：P2**

同步 `CLAUDE.md` / `docs/frame.md` 的安全声明与已知缺口——文件锁、Cron 扩展、Windows 沙箱。

- `CLAUDE.md` 安全声明：更新 engine sandbox 后端说明（新增 Windows Job Objects 支持）
- `docs/frame.md` 已知缺口：文件锁项标记为「已交付（可选锁）」；Windows sandbox 标记为「已交付 WinJobBackend（非完美边界）」；Cron 范围表达式移除缺口清单

### FR-A5：沙箱 profile 字段死代码清理

**优先级：P2**

`sandbox_hardening` 周期（S1-S4）引入了 `sandbox_profile` slot 和 profile 映射表，
但运行时测试覆盖了有 profile 和无 profile 路径。确认无死代码残留。

- 审查 `tools/sandbox.py` 的 `_PROFILE_MAP`、`SandboxProfileSlot`、`build_argv` 中无未使用分支
- 确认 `EngineContainer` 的 `sandbox_profile` 参数在所有注入路径被正确消费

---

## 3. 方向 C：质量与工程化

### FR-C1：测试覆盖率 80% → 90%

**优先级：P0**

CI `--cov-fail-under` 从 80 提升到 90。补齐覆盖率缺口：

- `engine/executor.py`：并发 lease 竞争、自定义 executor 错误恢复
- `engine/persist.py`：锁路径（FR-A1 联动）、并发读写兜底
- `engine/observability.py`：事件发布/订阅边缘路径
- `memory/skills.py`：并发 `record_usage` + 损坏 SKILL.md 恢复
- `cli.py`：交互模式异常路径（输入中断、stream 异常恢复）
- `agent/tool_execution.py`：handler 抛非 Exception 的子类（如 CancelledError 传播路径）

**目标**：覆盖率 ≥90%，每模块至少 80%。

### FR-C2：CI 多平台矩阵

**优先级：P1**

扩展 GitHub Actions CI 矩阵：

- **OS 矩阵**：`ubuntu-latest` + `windows-latest` + `macos-latest`
- **Python 矩阵**：`3.11` + `3.12` + `3.13`
- **策略**：全组合（9 jobs），但 sandbox 测试仅 Linux 跑真 firejail、Windows 跑 WinJob
- **集成测试分离**：`pytest -m "integration"` 作为 optional job（手动触发或 nightly）
- **覆盖率合并**：三平台覆盖率报告合并上传

**验收标准：**
- CI pass on ubuntu-latest (3.11/3.12/3.13)
- CI pass on windows-latest (3.11/3.12/3.13)
- CI pass on macos-latest (3.11/3.12/3.13)
- 每个 job 独立跑 `pytest`（不共享缓存）

### FR-C3：静态分析硬化

**优先级：P1**

增强代码质量门禁：

- **Ruff 扩展规则集**：启用 `B`（flake8-bugbear）、`C90`（mccabe 圈复杂度，max 15）、
  `S`（flake8-bandit 安全规则，排除误报项）、`SIM`（flake8-simplify）、
  `TCH`（flake8-type-checking-imports）
- **Bandit 安全扫描**：CI 加 `bandit -r src/` 步骤（排除测试代码）
- **依赖审计**：CI 加 `pip-audit` 步骤（周期性，允许已知安全公告的非影响项 skip）
- **pre-commit 更新**：`.pre-commit-config.yaml` 同步新规则

**验收标准：**
- `ruff check --select=B,C90,S,SIM,TCH` 零告警（含新规则）
- `bandit -r src/ -s B101` 零 MEDIUM+ 告警
- `pip-audit` 不报 CRITICAL（周期容忍 LOW）
- 新增规则不引入大规模批量忽略

### FR-C4：性能基准回归

**优先级：P2**

给性能敏感路径加可量化的基准测试：

- **Token 估算精度**：`estimate_text_tokens()` vs `tiktoken` 真值，误差 ≤20%
  （CJK 路径已知偏差更大，仅记录不硬拦）
- **上下文压缩效率**：压缩前后 token 数比率 ≥50% 缩减
- **工具注册性能**：100 个工具注册 < 10ms
- 基准作为 `pytest --benchmark` 步骤（CI 中警告不硬拦，吞吐量敏感）

### FR-C5：代码复杂度治理

**优先级：P2**

对圈复杂度超标的核心模块做局部重构（不改变行为）：

- `agent/loop.py`：当前主函数行数较多，评估是否可拆（不硬性要求）
- `engine/policy.py`：注解裁决逻辑集中，可读性优先于拆分
- 每个超标函数必须：有明确拆分理由 or 有合理复杂度注释解释

### FR-C6：文档与版本号同步

**优先级：P2**

迭代后文档收尾：

- `pyproject.toml` 版本号 bump（按本周期增量，如 0.7.0 → 0.8.0）
- `docs/frame.md` 更新：已知缺口、引擎沙箱章节、CI 概述
- `docs/iteration.md` 更新时间线
- `CLAUDE.md` 更新：已知缺口、安全声明
- `sprint-status.yaml` 维护

---

## 4. 非功能需求

### NFR-1：向后兼容

所有改动**不破坏既有 API**：
- `atomic_write_text` 新 kwargs 全部带默认值（`lock=False`）
- `CronParser` 新方法不影响现有解析逻辑
- `WinJobBackend` 新实现不影响 `Passthrough`/`FirejailBackend`
- 测试套件全量回归

### NFR-2：平台可移植性

- POSIX 文件锁不依赖 Linux 专有 syscall
- Windows 文件锁用 `msvcrt`（stdlib）
- WinJobBackend 用 `ctypes`（stdlib，无需 pip install）
- CI 三平台验证

### NFR-3：无新运行时依赖

- 不引入 `croniter`、`portalocker`、`filelock` 等第三方库
- 文件锁用 stdlib
- Windows Job Objects 用 ctypes（stdlib）
- 若有不可避免的新依赖（如 benchmark 用的 `pytest-benchmark`），仅限 dev

### NFR-4：确定性

- `CronParser` 的 `_expand_range`/`_parse_field` 纯函数，输出仅取决于输入
- 文件锁语义确定性：lock→write→unlock，中间不抛异常时保证写入完整
- 覆盖率门禁确定性：CI 闸门 `--cov-fail-under=90`

---

## 5. FR 覆盖 vs Brief

| Brief 问题 | FR 映射 |
|-----------|---------|
| 问题 1 · 跨进程文件锁 | FR-A1 |
| 问题 2 · Cron 范围表达式 | FR-A2 |
| 问题 3 · Windows 沙箱 | FR-A3 |
| — · 安全声明更新 | FR-A4 |
| — · 沙箱 dead code 清理 | FR-A5 |
| 问题 4 · 测试覆盖率 | FR-C1 |
| 问题 5 · CI 矩阵 | FR-C2 |
| 问题 6 · 静态分析 | FR-C3 |
| — · 性能基准 | FR-C4 |
| — · 复杂度治理 | FR-C5 |
| — · 文档版本同步 | FR-C6 |

---

## 6. 决策定稿（来自 brief D1–D4）

| 决策 | 定稿 |
|------|------|
| D1 · 文件锁粒度 | **单文件 fcntl/msvcrt 锁**。粒度适中，不引入重量级锁服务。锁开关经 `EngineContainer` 注入。 |
| D2 · Windows 沙箱方案 | **Windows Job Objects**。纯 stdlib ctypes，零依赖。不可用时 fallback Passthrough（优雅降级）。 |
| D3 · Cron 解析器 | **扩展现有 parser**。不引入 `croniter`（DAG 简单优先）。 |
| D4 · 测试覆盖率刚性 | **90%，CI 硬拦**。方向 C 的核心交付物。 |

---

## 7. 周期结构提案

方向 A 和 C 互相正交（文件锁不依赖 CI 矩阵），可并行推进。按 P 级拆 Epic：

| Epic | 优先级 | 主题 | FR |
|------|--------|------|-----|
| Epic A | P0–P2 | 健壮性硬化 | FR-A1~A5 |
| Epic C | P0–P2 | 质量工程化 | FR-C1~C6 |

两 epic 可并行开发/审查，无顺序依赖。收尾 story 整体更新文档。

---

## 8. 下游

- 架构（`bmad-architecture`）：文件锁接入点与 API 设计、Cron parser 扩展方案、
  WinJobBackend ctypes 架构、CI 矩阵配置方案。
- Epics（`bmad-create-epics-and-stories`）：按 Epic A / Epic C 拆 story。
