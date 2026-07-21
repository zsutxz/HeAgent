---
title: "HeAgent 健壮性与质量硬化"
status: draft
cycle: robustness-hardening
preceded_by: _bmad-output/mcp-client-v2/（Epic 14-17，MCP 全原语 + 内置工具扩展，已冻结交付）
created: 2026-07-21
updated: 2026-07-21
---

# Product Brief: HeAgent 健壮性与质量硬化

> 此前所有 17 个 Epic 已交付、deferred work 全部关闭。本周期不开发新功能，而是**夯实已有系统**：
> 把既有的健壮性缺口补齐、把工程质量拉到能支撑长期演进的水平。
> 方向 A（健壮性/安全）+ 方向 C（质量/工程化）合并为一个周期。

## 概述

HeAgent 经过 17 个 Epic 的迭代，功能面已完整——多 Provider、工具生态、记忆系统、上下文管理、
子 Agent、MCP 全原语、cron、运行时治理，全部可运行。但「可运行」与「可靠运行」之间仍有 gap：
部分边缘路径无上界、跨进程安全无保障、测试覆盖率停留在基线门槛、CI 矩阵单一。

本周期聚焦**已有模块的硬化**，不做新原语、不引入外部依赖升级。两个方向：

1. **健壮性/安全（方向 A）**：填已知缺口中可低成本修复的项——跨进程文件锁、Cron 范围表达式、
   OS 沙箱 Windows 支持。
2. **质量/工程化（方向 C）**：拉高工程质量基线——测试覆盖率 80%→90%、CI 多平台矩阵、
   静态分析加严、性能基准回归。

## 问题

### 问题 1：跨进程持久化无文件锁（A1，frame.md 已知缺口）

`engine/` 的 `RunStore` 和 `ExecutionLedger` 使用普通文件 I/O（`atomic_write_text` 单文件原子写），
但在**多进程 / 多 loop 同写 `.heagent/`** 时无文件锁——两个进程读到同一 `run_node.json`、
各自 `os.replace`，最后一个写入盖掉前一个的 checkpoint。当前 `asyncio.to_thread` 只保证单进程串行，
跨进程竞态是真实风险。

**触发场景**：`task_parallel` 中 supervisor + 多个 SubAgent 各自写自己的 `run_id` 不会撞 key
（key 唯一）——但 `build_run_tree()` 聚合时若读取到半写文件（被另一个进程的 `os.replace` 中断），
会返回损坏或不完整的树。**单进程场景不影响**——这是 infrastructure hardening，非 bug fix。

### 问题 2：Cron 范围表达式不支持（A2，frame.md 已知缺口）

`CronParser` 当前仅支持 `*`、逗号、步进——不支持行业标准 cron 的范围表达式（`1-5`）和
`*/15` 语法。用户期待的日常 cron 模式（"工作日 9-17 点每 30 分钟"）目前无法表达。

### 问题 3：OS 沙箱 Linux-only（A3，frame.md 已知缺口）

`FirejailBackend`（唯一真实 sandbox 后端）依赖 Linux 专有 API（`os.killpg`、cgroups、namespaces）。
Windows 开发者无法享受任何 OS 级沙箱保护。需要 Windows 等价物（如 Windows Job Objects 或
`CreateProcess` 受限令牌，或 Docker Desktop 集成）。

### 问题 4：测试覆盖率基线偏低（C1）

CI 当前 `--cov-fail-under=80`，仅够防大面积回归。几个关键模块覆盖率不足：
- `engine/` 的边缘路径（损坏 JSON 容错已测、并发 lease 竞争没测）
- `memory/` 的并发场景
- `cli.py` 的交互模式错误恢复路径
- 工具 handler 的异常短路路径

### 问题 5：CI 矩阵单一（C2）

当前 CI 仅在 `ubuntu-latest` + Python 3.11 上跑，不验证 Windows/macOS 兼容性，
也不验证 Python 3.12/3.13。`FirejailBackend` 测试在 Linux runner 上才是活得，
但 CI 没跑——sandbox 测试靠开发者的本地 pytest。

### 问题 6：静态分析偏软（C2/C3）

当前仅 `ruff check` + `mypy strict` + `ruff format --check`。缺少：
- 复杂度门禁（圈复杂度/认知复杂度/cognitive complexity）
- 安全 lint（bandit 或 ruff 安全规则）
- 依赖审计（`pip-audit`）
- 性能回归基准（token 估算精度 benchmark）

## 方案

### 方向 A：健壮性/安全

**A1 · 跨进程文件锁**：给 `persist.py` 的 `atomic_write_text` 加可选的进程间排他锁。
方案：用 `fcntl.flock`（POSIX）+ `msvcrt.locking`（Windows）实现平台自适应文件锁。
锁仅在 `EngineContainer.default()` 路径默认开启、`EngineContainer(enable_file_locks=False)`
可关闭（单进程场景禁用锁，消除无谓开销）。

**A2 · Cron 范围表达式**：扩展 `CronParser` 支持 `1-5`（范围）和 `*/N`（步进快捷）。
不改字段结构——纯 parser 层扩展，零数据库迁移。

**A3 · Windows 沙箱后端**：研究 Windows Job Objects（`CreateJobObject`/`AssignProcessToJobObject`）
作为 `CommandRunner` 的 Windows 实现。若实现复杂度过高（Windows API 需 ctypes/win32 绑定），
则退而求其次：提供 Docker 后端 (`docker run --rm --network=none ...`) 作为跨平台替代。
最终交付一个 Windows 可用的 `Passthrough` 替代品。

### 方向 C：质量/工程化

**C1 · 测试覆盖率 80%→90%**：给覆盖率缺口模块补测试。重点：
- `engine/` 边缘路径（并发 lease、corrupt JSON recovery）
- `memory/` 并发安全
- CLI 交互模式异常路径
- 工具 handler 异常短路

**C2 · CI 多平台矩阵**：加 `windows-latest` + `macos-latest` runner。
Python 3.12/3.13 矩阵测试。Sandbox 测试在 Linux runner 执行、
Windows/macOS 上 skip 或用 Passthrough。

**C3 · 静态分析硬化**：
- Ruff 启用更多规则（安全规则集 `S`、bugbear `B`、复杂度 `C90`）
- Bandit 安全扫描
- 依赖审计 `pip-audit`（周期性，非每次 commit）
- CI 加 pre-commit 钩子健康检查

**C4 · 性能基准**（可选，epic 收尾）：
- token 估算精度 benchmark（与 tiktoken 真值对比）
- 上下文压缩效率回归测试

## 差异化

本周期不与其他 Agent 框架竞争——这是**基础设施硬化**，是把 HeAgent 从「实验场」
升级为「可长期演进的工程仓库」。差异化在于：

1. **真跨平台**：让 Windows 开发者不只靠 `Passthrough` 裸跑
2. **真并发安全**：跨进程持久化带文件锁（同类 Agent 框架少有考虑）
3. **完整 cron**：行业标准 cron 语法（不是 V1 那种残缺解析器）

## 受众

- **主要**：HeAgent 开发者——在当前仓库上继续迭代时，基础设施不崩。
- **次要**：开源用户——Windows 上也能有基本沙箱保护。
- **成功画像**：(1) 两个 `python -m heagent` 进程同时跑，`.heagent/` 不损坏；
  (2) Cron 能配 "工作日 9-17 点每 30 分钟"；(3) Windows 用户有非透传沙箱可用；
  (4) 测试覆盖率 ≥90% 且 CI 三平台全绿。

## 成功标准

- ✅ **文件锁可用**：并发写 `.heagent/` 时不丢失 checkpoint
- ✅ **Cron 范围表达式可工作**：`1-5`、`*/15` 正确匹配
- ✅ **Windows 沙箱可运行**：Windows 上有 `Passthrough` 以外的 sandbox 后端
- ✅ **测试覆盖率 ≥90%**：`--cov-fail-under=90`
- ✅ **CI 三平台全绿**：Linux + Windows + macOS 全部通过
- ✅ **静态分析无回归**：ruff/bugbear/bandit/mypy 全绿

## 范围

**In：**
- 跨进程文件锁（`persist.py` + `EngineContainer` 开关）
- Cron 范围表达式（`cron/jobs.py` parser）
- Windows 沙箱后端（`tools/sandbox.py` 新 backend）
- 测试覆盖率补齐到 90%
- CI 多平台矩阵（Linux/Windows/macOS, Python 3.11/3.12/3.13）
- 静态分析硬化（Ruff 规则集、Bandit、pip-audit）

**Out（明确不做）：**
- 新功能开发（无新工具、无新 Provider、无新原语）
- 架构重构（不改 DAG、不改核心循环）
- Docker 化部署（非本周期，留给 deploy/）
- 完整的跨平台 `firejail` 等价品（只做 Windows 可用替代，不追求安全等价）
- E2E 集成测试自动化（需真实 API key，留给下一周期）

## 技术约束

- **Python 3.11+** 不变
- **无新运行时依赖**（文件锁用 stdlib、Windows sandbox 尽量避免 ctypes）
- **不破坏 DAG**（文件锁在 `engine/persist.py`，属叶子层）
- **向后兼容**：单进程场景文件锁可关闭，行为不回归

## 关键决策提案

- **D1 · 文件锁粒度**：提案 = 单文件 `fcntl.flock`。备选 = 全局 `.lock` 文件（粗粒度，简单但争用高）或 SQLite（重量级，超出周期范围）。
- **D2 · Windows 沙箱方案**：提案 = Windows Job Objects（轻量、stdlib 可绑）。备选 = Docker Desktop 集成（需额外安装、非真正 OS 级）或纯 WSL2 限定。
- **D3 · Cron 解析器重构程度**：提案 = 扩展现有 parser（加 `_expand_range`/`_parse_step` helper）。备选 = 引入 `croniter` 库（重但完整，引入新依赖）。
- **D4 · 测试覆盖率刚性**：提案 = 90%，CI 硬拦。备选 = 85%（渐进）或 95%（可能过度）。

## 愿景

HeAgent 不仅是「功能最多的自学习 Agent 实验场」，也是「工程质量最扎实的 Agent 脚手架」——
CI 三平台全绿、覆盖率刚性强、数据不因并发损坏、Windows 用户不裸跑。从「能用」升级为「耐用的工程基础」。

---

## 下游

- PRD（`bmad-prd`）：把本 brief 展开为 FR/NFR，定稿 D1–D4 决策。
- 架构（`bmad-architecture`）：文件锁接入点、Cron parser 扩展方案、Windows sandbox 架构。
- Epics（`bmad-create-epics-and-stories`）：按方向 A/C 拆 epic。
