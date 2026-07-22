# HeAgent 质量工程深化 — Product Brief

> BMad Method · Step 1: brief
> 日期: 2026-07-22
> 状态: draft

## 一、产品意图

HeAgent 当前质量基线：911 tests / 90% 行覆盖率 / ruff+mypy 零告警 / 三级 CI 门禁。**骨架完整，但工具链存在结构性半成品**——benchmark 框架已安装但未真正接入（手工 `perf_counter()` 而非 `pytest-benchmark` fixture）、coverage 配置散落在 CI 脚本中不可本地复现、Docker 健康检查指向不存在的 HTTP 端点。

本次周期的目标：**把质量工程从「能用」推到「业界 best practice」**，让本地开发循环与 CI 完全一致、性能回归可自动检测、容器化无已知缺陷。

## 二、目标与非目标

### 目标（In Scope）

1. **Coverage 工程化**：`[tool.coverage]` 配置段落地，branch coverage 启用，本地 `coverage run/report` 等价 CI
2. **Benchmark 体系重构**：`perf_counter()` → `pytest-benchmark` fixture，JSON 报告可持久化、可跨 commit 对比
3. **Benchmark CI job**：性能回归自动检测，退化告警
4. **Docker 修复**：HEALTHCHECK 修复 + `.dockerignore` + base image digest 锁定
5. **CI 效能**：pip 缓存、Python 3.14 预发布验证
6. **安全左移**：CodeQL SAST + dependency-review
7. **pre-commit 加固**：基础文件卫生 hooks + bandit hook
8. **ruff 规则扩展**：PLC / RUF / PT / PIE 规则组

### 非目标（Out of Scope）

- 覆盖率推至 95%+（本次聚焦工具链，覆盖率数值提升为副作用）
- TUI / HTTP API / 插件市场（属产品化周期，与质量工程无关）
- 性能优化（本次只建回归检测体系，不主动做代码级性能调优）
- K8s / Terraform IaC（超出单机部署范围）
- 联网搜索增强（独立周期 A，不混入）

## 三、成功标准

| # | 标准 | 衡量方式 |
|---|------|----------|
| 1 | 本地 `coverage run -m pytest && coverage report` 输出与 CI 完全一致 | 手工验证 |
| 2 | `pytest --benchmark-only` 生成 JSON 报告，`pytest-benchmark compare` 可跨 commit 对比 | 手工验证 |
| 3 | CI benchmark job 在性能退化 >20% 时 fail | CI 日志 |
| 4 | Docker `docker compose up` 后 `docker ps` 显示 healthy | 手工验证 |
| 5 | CI lint job 因新规则新增告警时 fail | CI 日志 |
| 6 | CodeQL / dependency-review 在 PR 上运行且不报高危 | CI 日志 |

## 四、约束

- 不引入新的运行时 Python 依赖（dev 依赖可加）
- 不改动 `src/heagent/` 下的任何产品代码（纯工程配置周期）
- 测试数量不减少，覆盖率不下降
- CI 总耗时不超过当前基线的 1.5 倍

## 五、风险

- `pytest-benchmark` JSON 报告需要 storage backend（GitHub Actions artifacts / S3），否则跨 commit 对比不可用
- CodeQL 对 Python 的检查较有限，可能回报率低于预期
- 新 ruff 规则可能触发大量既有告警，需逐条评估 `per-file-ignores` 豁免策略

## 六、决策日志

| ID | 决策 | 理由 | 日期 |
|----|------|------|------|
| D1 | 质量工程周期不碰产品代码 | 纯工程配置变更，风险隔离，可独立 revert | 2026-07-22 |
| D2 | 覆盖率目标保持 88%（本次不提升） | 工具链落地后再评估数值目标 | 2026-07-22 |
| D3 | benchmark 用 GitHub Actions artifacts 做持久化 | 零成本、零新依赖 | 2026-07-22 |
