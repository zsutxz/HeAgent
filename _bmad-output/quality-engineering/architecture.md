# HeAgent 质量工程深化 — Architecture

> BMad Method · Step 3: architecture
> 日期: 2026-07-22
> 输入: prd.md

## 一、变更范围总览

本周期为**纯工程配置变更**，不修改 `src/heagent/` 下任何 `.py` 文件。变更仅涉及：

| 文件 | Epic | 操作 |
|------|------|------|
| `pyproject.toml` | 20, 21 | 新增 `[tool.coverage]`、`[tool.pytest-benchmark]` 配置段 |
| `tests/test_benchmarks.py` | 21 | 重构：`perf_counter()` → `benchmark` fixture |
| `.github/workflows/ci.yml` | 20, 21, 22, 23 | 新增 benchmark/benchmark-compare/codeql/dependency-review job；修改 coverage job 参数来源；`setup-python` 加 `cache: pip`；test matrix 加 3.14-dev |
| `Dockerfile` | 22 | HEALTHCHECK 修复 + base image digest 锁定 |
| `.dockerignore` | 22 | 新增文件 |
| `.pre-commit-config.yaml` | 23 | 新增 8 个 hooks |
| `ruff.toml` | 23 | `[lint] select` 扩展 + `[format]` 段 |
| `.gitignore` | 21 | 新增 `benchmark-data/` |

## 二、组件设计

### 2.1 Coverage 配置（Epic 20）

```
[tool.coverage.run]
source = ["src/heagent"]
branch = true
omit = ["tests/*", "*/venv/*", "*/__pycache__/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
]
fail_under = 88
```

CI coverage job 读取此配置，仅 `--cov-fail-under` 可 override（CI 可设更高门限）。

### 2.2 Benchmark 体系（Epic 21）

**技术选型**：`pytest-benchmark`（已在 `dev` 依赖中）。

配置：
```
[tool.pytest_benchmark]
min_rounds = 5
max_time = 1.0
timer = "time.perf_counter"
storage = "./benchmark-data/"
save = "ci"
autosave = true
```

数据流：
```
pytest --benchmark-only --benchmark-autosave
  → benchmark-data/<OS>_<Python>_<commit-short>.json
  → upload-artifact (name: benchmark-data, retention: 7 days)

benchmark-compare job:
  → download-artifact (上一次成功运行的)
  → pytest-benchmark compare --group=group,func <old>.json <new>.json
  → 退化 >20% → step warning
```

**重构原则**：每个 benchmark 测试使用 `benchmark` fixture 包裹被测函数调用：
```python
# Before
start = time.perf_counter()
result = some_func()
elapsed = time.perf_counter() - start
assert elapsed < 0.005

# After
def test_something(benchmark):
    result = benchmark(some_func)
    assert result == expected
```

### 2.3 CI 流水线变更（Epic 20-23）

```
lint (ruff + format + mypy + bandit + pip-audit)
  └─ 不变

test (matrix: os × python)
  ├─ setup-python 加 cache: pip           # FR-Q12
  ├─ test matrix 加 python 3.14-dev       # FR-Q13
  └─ 不变

coverage (ubuntu + 3.11)
  ├─ 读取 [tool.coverage] 配置            # FR-Q2
  └─ upload artifact: coverage-html       # FR-Q3

benchmark (ubuntu + 3.11)                 # FR-Q7 · 新增
  ├─ download-artifact: benchmark-data (上一次, 可选)
  ├─ pytest --benchmark-only --benchmark-autosave
  ├─ upload-artifact: benchmark-data
  └─ benchmark-compare step               # FR-Q8

codeql (每周一 9:00 UTC)                  # FR-Q14 · 新增
  └─ init → autobuild → analyze

dependency-review (PR)                    # FR-Q15 · 新增
  └─ dependency-review-action@v4

integration (手动) → 不变
```

### 2.4 Docker 修复（Epic 22）

**HEALTHCHECK 修复**：当前 CMD 是 `python -m heagent`（交互式 CLI），无 HTTP 端点。改为进程存活性检查：

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import heagent; print('ok')" || exit 1
```

**base image 锁定**：`python:3.11-slim` → `python:3.11-slim@sha256:<digest>`（实施时查最新 digest）。

### 2.5 Ruff 规则扩展策略（Epic 23）

新增规则组后的处置策略：

1. 运行 `ruff check` 获取新增告警清单
2. 对每条告警：优先**修复代码**（不抑制规则），仅在代码改动不合理时加 `per-file-ignores` 豁免
3. 豁免必须带注释说明理由（如 `# PLC0415: 循环导入避免，该 import 必须在此处`）
4. 新增 `[format]` 段后运行 `ruff format --check` 验证无意外格式化

## 三、技术决策

| ID | 决策 | 理由 |
|----|------|------|
| AD-1 | benchmark compare 退化阈值设为 20% | 避免 flaky CI——`perf_counter()` 在共享 CI runner 上波动大；20% 是真退化信号 |
| AD-2 | benchmark compare 用 warning 不 fail | 信息性门禁——CI runner 不可控，假阳性频繁 fail 会损害 CI 可信度 |
| AD-3 | CodeQL 仅 security 查询、每周定时 | 全量查询回报率低、耗时高；每周定时 + PR 手动触发是性价比最优 |
| AD-4 | Python 3.14-dev `continue-on-error: true` | 预发布不稳定，不应阻塞主流程 |
| AD-5 | HEALTHCHECK 用 `import heagent` 而不用 HTTP | HeAgent 是 CLI 库，无 HTTP 服务；进程存活性是最诚实的健康信号 |
| AD-6 | `[format]` line-ending 设为 `lf` | 跨平台一致性；Windows 开发者用 `git config core.autocrlf true` 适配 |
| AD-7 | 本周期不提升覆盖率 fail_under | 88% 是已达成基线；提升需伴随实际测试补写（超出纯配置周期范围） |

## 四、风险与缓解

| 风险 | 缓解 |
|------|------|
| `pytest-benchmark` fixture 重构破坏既有性能断言 | 逐测对比旧 `perf_counter` 与新 `benchmark` 的语义差异——`benchmark` 默认跑多轮取 median，旧代码是单次 `perf_counter`；对「须单次调用」的测试用 `benchmark.pedantic()` |
| CodeQL 首次运行可能发现大量告警 | 先手动运行评估，必要时只开 `security-and-quality` 或逐条 suppress |
| 新 ruff 规则触发数百条既有告警 | 分两阶段：先 `ruff check --statistics` 评估量级，决定是否拆到独立 story；豁免策略以 `per-file-ignores` 为主 |
