# ADR-001 · CI 基准回归强制门禁

> **状态**：accepted（Epic 63 retro 提案，2026-11-18 用户批准）
> **来源**：plan `tickets/epic-63-测试体系增强/tickets/story-63.5-perf-baseline-plan.md`；commit `cab4552`
> **治理面**：`.github/workflows/ci.yml` benchmark job

**Context.** benchmark job 早已存在且跑得动，但回归只进 step summary：compare 步骤带 `continue-on-error: true`，命令尾部 `|| true`，性能劣化不会让 CI 变红；同时 autosave 实际落盘在 `benchmark-data/<机器名>/NNNN_*.json`，summary 步骤用顶层 `ls benchmark-data/*.json` 从未匹配，比较分支恒为空转。

**Decision.** benchmark 步骤改为「取最近一次落盘为基线 + `--benchmark-compare-fail=mean:10%` 强制门禁」：有基线即比较、回归超 10% 直接 exit 1；无基线（首次运行）只 autosave 不比较。基线查找与 summary 的 glob 一并改为 `find benchmark-data -name "*.json"`，兼容嵌套布局；autosave 显式给 `--benchmark-storage=./benchmark-data/` 让落盘布局确定。

**Why.** 性能基线的价值在拦截回归而不是出报表，只记录不失败等于没有门禁；`mean:10%` 是票面给定阈值，本地端到端已验证过严阈值（mean:1ns）必红、宽松 50% 必绿，两向可控。已声明的限制：真实 CI 行为只能在 GitHub Actions 上验证，共享 runner 噪声若造成误红，调阈值属后续常量微调，不动本结构。
