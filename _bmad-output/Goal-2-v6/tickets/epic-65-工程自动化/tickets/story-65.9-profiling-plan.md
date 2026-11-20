---
title: 'Story 65.9 集成性能分析工具'
type: feature
ticket: 9
created: '2026-11-18'
status: done
baseline_revision: 'ae831fe'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'scripts/profile_run.py'
  - 'docs/performance.md'
  - 'tests/test_profile_script.py'
---

## Intent

**Problem:** 票面 verify「生成火焰图报告并指出热点函数，提供分析脚本」。勘差结论：`docs/performance.md`
只给了两条**手敲**的 `cProfile` 命令（`python -m cProfile -o profile.out -m heagent ...` +
一行 `pstats`），既没有脚本、也不给热点摘要——用户得自己记住 `sort_stats`、自己读数、自己判断
哪个函数值得改。而 `heagent "..."` 这种一次性运行里，`-m cProfile -m heagent` 的参数嵌套本身就容易写错。

**Approach：** 新增 `scripts/profile_run.py`（标准库 `cProfile` + `pstats`，**零新依赖**）：

- `--module NAME` / `--script PATH` 二选一；`--` 之后的参数原样转给目标（`pytest` 的参数因此可直接透传）；
- 目标在**同一进程内**执行（`runpy.run_module` / `run_path`）——这是能采集剖面的前提；
- 报告 = 运行元信息 + **按 `tottime` 排的热点函数（前 10）** + 按 `cumtime` 排的调用表（`--top` 控制条数）；
  默认落 `.heagent/tmp/profile-<时间戳>.txt`，stdout 同时打热点摘要；
- 目标崩溃**也留报告**（那正是最需要剖面的时刻），stderr 打 `target raised <Type>: <msg>`，退出码 1；
  目标的 `SystemExit` 如实转成退出码（`pytest` 失败 = 1，不是被吞成 0）。

**为什么热点用 `tottime` 而不是 `cumtime`**：`cumtime` 排在最前的永远是 `main` / `runpy` 这类调度壳，
对「改哪一行」零信息量；`tottime`（自身耗时，不含子调用）才是优化落点。实测：
`prof_target_demo.busy()` 以 `0.005s tottime` 排在首位，其余是 import 机器噪声。

**py-spy 的位置**：它是**外部二进制**（需 root / `ptrace`，容器内还要 `SYS_PTRACE`），价值在 attach
已在运行的 `heagent http-server`；因此不写进脚本依赖，只在 `docs/performance.md` 给「attach 活进程」
的两条命令（`py-spy record` 火焰图 / `py-spy top` 实时热点），与本脚本的「起一个新进程做剖面」互补。

## Verify 实测

`pytest tests/test_profile_script.py -q` → **5 passed**：

- `split_argv` 正确切分 `--` 前/后；
- 模块目标：报告落盘、含 `Hottest functions (by tottime)` 与 `Callers / callees` 两段，
  且 `-- alpha beta` 真的进了目标 `sys.argv`（`['alpha', 'beta']` 出现在 stdout）；
- 目标抛 `RuntimeError` ⇒ 退出码 1、stderr 点名 `RuntimeError: kaboom`、报告仍存在；
- 目标 `SystemExit(3)` ⇒ 退出码 3；
- 热点排序：忙函数 `busy` 排在第一条（不是 import 噪声）。

手工实测（本容器）：

```text
$ python scripts/profile_run.py --script tests/test_release_workflow_contract.py
[profile] script tests/test_release_workflow_contract.py → exit 0
[profile] hottest functions (tottime):
     0.010s tottime  ...  <built-in method builtins.compile>
...
[profile] full report: /workspace/.heagent/tmp/profile-20261118-140057.txt
```

## Boundaries

- **不装 py-spy**：外部二进制 + 权限要求，装进依赖树会污染「零额外系统依赖」的安装面。
- **不做异步感知的分段计时**：那属事件流（`provider_call_completed.duration_ms`）的职责，
  `docs/performance.md` 一节 1 已覆盖；cProfile 在 `await` 处的时间归因本就不可靠（文档已注明）。
- **不生成 SVG 火焰图**：需要 `gprof2dot` + graphviz，属外部工具链；脚本只产文本报告，
  attach 型火焰图交给 py-spy。
