# HeAgent 质量工程深化 — Epic Breakdown

> BMad Method · Step 4: epics
> 日期: 2026-07-22
> 输入: prd.md, architecture.md

## Overview

纯工程配置周期——4 个 Epic，20 个 FR，不改动 `src/heagent/` 下任何 `.py` 文件。

## FR Coverage Map

| FR | Epic | 主题 |
|----|------|------|
| FR-Q1 | 20 | `[tool.coverage]` 配置段 |
| FR-Q2 | 20 | CI coverage job 参数迁移 |
| FR-Q3 | 20 | coverage HTML artifact 上传 |
| FR-Q4 | 21 | benchmark fixture 重构 |
| FR-Q5 | 21 | `[tool.pytest-benchmark]` 配置段 |
| FR-Q6 | 21 | `.gitignore` benchmark-data |
| FR-Q7 | 21 | CI benchmark job |
| FR-Q8 | 21 | CI benchmark compare |
| FR-Q9 | 22 | `.dockerignore` |
| FR-Q10 | 22 | HEALTHCHECK 修复 |
| FR-Q11 | 22 | base image digest 锁定 |
| FR-Q12 | 23 | CI pip 缓存 |
| FR-Q13 | 23 | CI Python 3.14-dev |
| FR-Q14 | 23 | CI CodeQL job |
| FR-Q15 | 23 | CI dependency-review |
| FR-Q16 | 23 | pre-commit 卫生 hooks |
| FR-Q17 | 23 | pre-commit bandit hook |
| FR-Q18 | 23 | ruff 规则扩展 |
| FR-Q19 | 23 | 新规则告警修复/豁免 |
| FR-Q20 | 23 | ruff `[format]` 段 |

## Epic 20: Coverage 工程化

用户成果：本地 `coverage run/report` 与 CI 完全等价，branch coverage 启用

### Story 20.1: `[tool.coverage]` 配置段落入

**AC:**
- `pyproject.toml` 新增 `[tool.coverage.run]`：`source = ["src/heagent"]`、`branch = true`、`omit`（tests/venv/__pycache__）
- `[tool.coverage.report]`：`exclude_lines`（4 类）+ `fail_under = 88`
- 本地 `coverage run -m pytest && coverage report` 可运行，无需 CLI 参数

### Story 20.2: CI coverage job 迁移

**AC:**
- CI coverage job 移除 `--cov=src/heagent --cov-branch --cov-report=term`，改为读取 `pyproject.toml`
- 保留 `--cov-fail-under=90`（CI 门限高于本地 88，体现 CI 更严）
- 覆盖率不低于当前基线

### Story 20.3: Coverage HTML artifact

**AC:**
- CI coverage job 新增 `coverage html` + `upload-artifact`（name: `coverage-html`，retention: 7 days）
- artifact 可从 GitHub Actions UI 下载查看

## Epic 21: Benchmark 体系重构 + CI

用户成果：性能基准测试可历史对比，性能退化自动检测

### Story 21.1: benchmark fixture 重构

**AC:**
- `tests/test_benchmarks.py` 全部 10 个测试从 `time.perf_counter()` 断言改为 `benchmark` fixture
- `benchmark(some_func)` 包裹被测调用，断言逻辑保留
- 原单次调用语义保留（用 `benchmark.pedantic()` 处理「只许调用一次」的测试）
- 全量 benchmark 测试通过 `pytest --benchmark-only`

### Story 21.2: `[tool.pytest-benchmark]` 配置

**AC:**
- `pyproject.toml` 新增 `[tool.pytest_benchmark]`：`min_rounds=5`、`max_time=1.0`、`storage="./benchmark-data/"`、`save="ci"`、`autosave=true`
- `.gitignore` 新增 `benchmark-data/`
- `pytest --benchmark-only --benchmark-autosave` 生成 JSON 到 `benchmark-data/`

### Story 21.3: CI benchmark job

**AC:**
- CI 新增 `benchmark` job（ubuntu + 3.11，独立于 test matrix）
- 运行 `pytest --benchmark-only --benchmark-autosave`
- `upload-artifact`（name: `benchmark-data`，retention: 7 days）

### Story 21.4: CI benchmark compare

**AC:**
- benchmark job 内 `download-artifact` 上一次成功运行的 `benchmark-data`（失败时不阻塞）
- `pytest-benchmark compare` 对比新旧 JSON，输出到 step summary
- 性能退化 >20% 时 step 标 warning（不 fail）
- 无法下载历史 artifact 时跳过 compare 步骤

## Epic 22: Docker 修复

用户成果：Docker 构建瘦身、健康检查正确、可重现构建

### Story 22.1: `.dockerignore` 新增

**AC:**
- 新增 `.dockerignore`：排除 `.venv/`、`__pycache__/`、`.mypy_cache/`、`.pytest_cache/`、`.ruff_cache/`、`node_modules/`、`.git/`、`_bmad-output/`、`benchmark-data/`、`*.pyc`、`*.pyo`、`.DS_Store`
- `docker build` 后 image size 不增加（排除缓存目录后应略小）

### Story 22.2: HEALTHCHECK 修复

**AC:**
- `Dockerfile` HEALTHCHECK 从 `CMD curl localhost:8080` 改为 `CMD python -c "import heagent; print('ok')"`
- `docker compose up` 后 `docker ps` 显示 `(healthy)`

### Story 22.3: base image digest 锁定

**AC:**
- `Dockerfile` `FROM python:3.11-slim` → `FROM python:3.11-slim@sha256:<当前最新 digest>`
- 注释标注锁定日期和原因

## Epic 23: CI 效能 + 安全 + pre-commit + ruff

用户成果：CI 更快、供应链可审查、本地提交质量更高、更多 lint 规则

### Story 23.1: CI pip 缓存

**AC:**
- `setup-python` action 新增 `cache: "pip"`
- CI test job 耗时因缓存减少（首次不变，二次起效）

### Story 23.2: CI Python 3.14-dev

**AC:**
- CI test matrix 新增 `python-version: "3.14-dev"`（`continue-on-error: true`）
- 3.14-dev 失败不阻塞其他 job

### Story 23.3: CI CodeQL

**AC:**
- CI 新增 `codeql` workflow（独立文件 `.github/workflows/codeql.yml`）
- 触发器：`schedule: cron(0 9 * * 1)`（每周一 9:00 UTC）+ `workflow_dispatch`
- 仅 `security` 查询套件，语言 `python`

### Story 23.4: CI dependency-review

**AC:**
- CI 新增 `dependency-review` job（在 `ci.yml`，PR 触发）
- `actions/dependency-review-action@v4`

### Story 23.5: pre-commit 卫生 hooks

**AC:**
- `.pre-commit-config.yaml` repos 列表新增 `pre-commit-hooks` repo（`rev: v5.0.0`）
- hooks: `trailing-whitespace`、`end-of-file-fixer`、`check-yaml`、`check-toml`、`check-merge-conflict`、`check-added-large-files`（`args: ['--maxkb=500']`）

### Story 23.6: pre-commit bandit hook

**AC:**
- `.pre-commit-config.yaml` repos 列表新增 bandit hook（`rev: 1.8.3`，`args: ['-ll']`）
- `pre-commit run --all-files` 通过

### Story 23.7: ruff 规则扩展

**AC:**
- `ruff.toml` `[lint] select` 新增 `"PLC"`、`"RUF"`、`"PT"`、`"PIE"`
- `ruff.toml` 新增 `[format]` 段：`quote-style = "double"`、`indent-style = "space"`、`line-ending = "lf"`

### Story 23.8: 新规则告警修复

**AC:**
- `ruff check` 零告警（新增规则触发的问题全部修复或 `per-file-ignores` 豁免）
- 每条 `per-file-ignores` 豁免带注释说明理由
- `ruff format --check` 零格式差异
