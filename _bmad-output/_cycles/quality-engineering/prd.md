# HeAgent 质量工程深化 — PRD

> BMad Method · Step 2: prd
> 日期: 2026-07-22
> 输入: brief.md

## 一、功能需求（FR）

### Coverage 工程化

- **FR-Q1**：`[tool.coverage]` 配置段落入 `pyproject.toml`，含 `source`（`src/heagent`）、`branch = true`、`omit`（tests/venv）、`exclude_lines`（`pragma: no cover` / `if TYPE_CHECKING:` / `raise NotImplementedError`）、`fail_under = 88`
- **FR-Q2**：CI coverage job 从行内参数迁移到读取 `pyproject.toml` 配置，仅在 `--cov-fail-under` 处保留覆盖门限覆盖（CI 可设更高门限，但不低于 88）
- **FR-Q3**：coverage HTML/XML 报告上传为 GitHub Actions artifact（`upload-artifact`），保留 7 天

### Benchmark 体系重构

- **FR-Q4**：`tests/test_benchmarks.py` 全部 10 个测试从 `time.perf_counter()` 断言改为 `pytest-benchmark` 的 `benchmark` fixture
- **FR-Q5**：`pyproject.toml` 新增 `[tool.pytest-benchmark]` 配置段：`min-rounds=5`、`max-time=1.0`、`timer=time.perf_counter`、`storage=./benchmark-data/`、`save=ci`、`autosave=true`
- **FR-Q6**：`.gitignore` 添加 `benchmark-data/`（CI 产物由 artifact 管理，不入库）

### Benchmark CI

- **FR-Q7**：CI 新增 `benchmark` job（ubuntu + Python 3.11）：运行 `pytest --benchmark-only --benchmark-autosave`，上传 `benchmark-data/` 为 artifact
- **FR-Q8**：benchmark job 下载**上一次**成功运行的 benchmark artifact，执行 `pytest-benchmark compare --group=group,func` 输出对比报告；性能退化 >20% 时 step 标黄（warning，不 fail——纯信息性，避免 flaky CI）

### Docker 修复

- **FR-Q9**：新增 `.dockerignore`：排除 `.venv/`、`__pycache__/`、`.mypy_cache/`、`.pytest_cache/`、`.ruff_cache/`、`node_modules/`、`.git/`、`_bmad-output/`、`benchmark-data/`、`*.pyc`
- **FR-Q10**：修复 `Dockerfile` 的 `HEALTHCHECK`——当前 CMD 调 `localhost:8080` 无对应服务；改为 `CMD heagent --version && echo OK` 或使用 `ps aux | grep` 检查进程存活性
- **FR-Q11**：`Dockerfile` base image 从 `python:3.11-slim` 改为 `python:3.11-slim@sha256:<当前最新 digest>`，锁定可重现构建

### CI 效能

- **FR-Q12**：CI `setup-python` action 启用 `cache: pip`
- **FR-Q13**：CI test matrix 增加 Python 3.14-dev（允许 fail，`continue-on-error: true`），标记为 experimental

### 安全左移

- **FR-Q14**：CI 新增 `codeql` job：每周一 9:00 UTC scheduled 运行 + PR 手动触发（`workflow_dispatch`），语言 `python`，仅 `security` 查询套件
- **FR-Q15**：CI 新增 `dependency-review` job：PR 触发，`action: dependency-review-action@v4`

### pre-commit 加固

- **FR-Q16**：`.pre-commit-config.yaml` 新增 hooks：`trailing-whitespace`、`end-of-file-fixer`、`check-yaml`、`check-toml`、`check-merge-conflict`、`check-added-large-files`（上限 500KB）
- **FR-Q17**：pre-commit 新增 `bandit` hook（`-ll`，与 CI 一致）

### Ruff 规则扩展

- **FR-Q18**：`ruff.toml` `[lint] select` 新增规则组：`PLC`（Pylint 约定）、`RUF`（ruff 专项）、`PT`（pytest 专项）、`PIE`（flake8-pie）
- **FR-Q19**：新规则触发的既有告警逐条评估：全部修复或加 `per-file-ignores` 豁免（含注释说明豁免理由）
- **FR-Q20**：`ruff.toml` 新增 `[format]` 段：`quote-style = "double"`、`indent-style = "space"`、`line-ending = "lf"`（跨平台一致性）

## 二、非功能需求（NFR）

- **NFR-Q1**：所有变更不修改 `src/heagent/` 下任何 `.py` 文件（纯工程配置周期）
- **NFR-Q2**：CI 总耗时 ≤ 当前基线的 1.5 倍（当前约 6 分钟，上限 9 分钟）
- **NFR-Q3**：现有 911 测试全量通过，覆盖率不下降（≥88%）
- **NFR-Q4**：新增配置项有注释说明用途，不引入无文档的魔法数字

## 三、FR 与 Epic 预映射

| Epic | FR | 主题 |
|------|-----|------|
| Epic 20 | FR-Q1~Q3 | Coverage 工程化 |
| Epic 21 | FR-Q4~Q8 | Benchmark 体系 + CI |
| Epic 22 | FR-Q9~Q11 | Docker 修复 |
| Epic 23 | FR-Q12~Q20 | CI 效能 + 安全左移 + pre-commit + ruff |

> 注：质量工程各 Epic 高度独立，可并行推进（不同文件、零代码耦合）。

## 四、UX 设计

不适用——本周期为纯工程配置变更，无面向终端用户的功能。
