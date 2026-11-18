---
title: 'Story 63.5 建立核心路径性能基线'
type: ci
ticket: 5
created: '2026-11-18'
status: built
baseline_revision: '0d13b6c'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'tests/test_benchmarks.py'
  - '.github/workflows/ci.yml'
  - 'pyproject.toml'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 票面 verify「基准测试纳入 CI，性能回归超 10% 时 CI 失败」此前不满足：
12 条基准已存在（test_benchmarks.py，覆盖 token 估算/压缩/工具注册/skill 匹配/单轮
循环/批量工具，远超 ≥5 条要求），CI benchmark job 已存在，但 compare 步骤
`continue-on-error: true` + `|| true`——回归只进 step summary，不拦 CI。

**Ruling（2026-11-18 用户批复：按方案执行 CI compare 强制门禁）**

## Survey（baseline 0d13b6c）

- pytest-benchmark 5.2.3：`--benchmark-compare=<json路径>`（路径式基线）+
  `--benchmark-compare-fail=mean:10%`（回归即 exit 1）。本地端到端验证：伪造过严
  阈值 mean:1ns → `Performance has regressed` + exit 1；宽松 mean:50% → 全绿。
- **现存 bug 一并修**：autosave 实际落盘 `benchmark-data/<机器名>/NNNN_*.json`
  （机器名子目录嵌套）——原 summary 步骤 `ls benchmark-data/*.json` 顶层 glob 从未
  匹配过，compare summary 恒走「No previous benchmark data」死分支。
- `tests/test_release_workflow_contract.py:81` 钉 ci.yml job 集合
  （含 benchmark job 必须存在）；本改动不动 job 集合，契约不受影响（实跑 9 passed）。
- pyproject **刻意不设** `[tool.pytest_benchmark]` 表（2026-09-28 实测 ini 项不生效），
  全部旗标必须在 CLI 显式给出——本改动遵守该约定（旗标进 run 命令行）。

## Design

ci.yml benchmark job 两处：

1. **Run benchmarks**：基线取 `find benchmark-data -name "*.json" | sort | tail -1`
   （零填充序号 tail = 最新落盘）；有基线 →
   `--benchmark-compare="$BASELINE" --benchmark-compare-fail=mean:10%` 强制门禁；
   无基线（首次运行）只 autosave 不比较。autosave 改为显式
   `--benchmark-storage=./benchmark-data/`（布局确定性）。
2. **Compare benchmarks（summary）**：glob 从顶层 `ls benchmark-data/*.json` 改
   `find benchmark-data -name "*.json"`（修复嵌套布局下恒空的死分支），仍
   informational（`|| true`），summary 语义不变。

**已声明限制**：CI 侧实际行为无法本地验证（GitHub Actions 才是真值）；门禁阈值
mean:10% 在共享 runner 上对快基准可能有噪声性红——若出现噪声红，调阈值属后续
微调（改一个常量），不影响本结构。

</frozen-after-approval>

## Outcome

- 契约测试 9 passed（job 集合不变）；YAML 语法验证通过（PyYAML safe_load）。
- 门禁行为本地端到端验证（过严红/宽松绿）如 Survey 所记。
