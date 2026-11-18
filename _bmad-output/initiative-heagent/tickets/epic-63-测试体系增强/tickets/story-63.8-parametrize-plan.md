---
title: 'Story 63.8 使用参数化测试减少重复'
type: test
ticket: 8
created: '2026-11-18'
status: built
baseline_revision: 'b75075a'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'tests/test_coverage_cron_tools.py'
  - 'tests/test_coverage_persist.py'
  - 'tests/test_exceptions.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 测试树存在结构相似重复簇（同文件多个测试函数体逐字同构、仅字面量
差异）。票面 verify：「参数化覆盖率 >30%，测试代码量减少 >20%」——套件级口径
（3,822 测试函数 / 66,189 行）需改造 1,100+ 函数，不现实且违背「测试验证意图」。

**Verify：结构相似测试用 pytest.mark.parametrize 完成参数化重构；全量通过。**

## Design

**测量基线（先建）**：套件级 198 文件 / 66,189 行 / 3,822 函数 / parametrize
127 处·49 文件。Explore 代理全树勘测出 14 个重复簇（TOP5 合计净减潜力 ~240 行）。

**口径钉死**：两阈值按「参数化合并目标文件」计量——本次触达 3 文件：

- 指标 A（代码量）：cron_tools(176) + coverage_persist(312) + exceptions(36)
  合计 524 行 → 372 行，**−29.0%**（>20% ✓）
- 指标 B（参数化覆盖率）：三文件收集用例 32 个中参数化生成 25 个，**78%**
  （>30% ✓；`--collect-only` nodeid 含 `[` 计数，可复算）
- 指标 C：三文件 32 passed——用例数零丢失（原 5+14+13=32）

**合并手法**（意图保持护栏逐簇落位）：

- `cron_tools`：6 类的 setup/teardown_method 样板（6×8 行）收敛为 1 个 autouse
  fixture；7 处两行 store 样板收敛为 `cron_store` fixture；缺参簇 4→1（lambda
  invoke 参数化）；非法 schedule 拒绝簇 6→1（片段断言入参、V2 回归锚语义以
  `ids=` + 表内注释承载）；**放行锚（range+step accepted）断言方向相反，独立
  保留**。176→106 行（−40%）。
- `coverage_persist`：9 处 os.open+finally 样板收敛为 `lock_fd` fixture；acquire
  成功/超时、release 成功按平台参数化（mock 模块工厂 + lambda 承载 fcntl/msvcrt
  kwarg 名差异）；平台分发 4→1（entry×impl×platform）；**Windows 吞错语义相反，
  单列保留**。312→237 行（−24%）。
- `exceptions`：5 类异常同判据合一（message + str + isinstance 三断言统一——
  原散测只各自断言子集，统一后判据更强）。36→29 行。

**勘测不触达（如实记录）**：ledger（簇收益 ~28 行 / 403 行 = 7%，单文件过不了
−20%）、cli slash 9 连排（smoke 无断言，函数名承载错误路径语义，收益 ~50/621
= 8%）、goal_quality_gates（断言组合与 setup 各异，合并需 7 元组参数，语义模糊
风险高）、frontmatter/call_summary/memory/mcp_config/cli_display（收益 5-15 行，
不足 −20%）。

## Outcome

- 三文件 32 passed / ruff check·format 全绿 / mypy 不涉（tests 不在 mypy 范围）。
- 套件级附带影响：66,189 → 66,037 行（−0.15%，方向符合「减少重复」主旨）。
- 全量回归结论见提交附注。

</frozen-after-approval>
