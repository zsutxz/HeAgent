---
title: 'Story 64.3 编写性能调优指南'
type: feature
ticket: 3
created: '2026-11-18'
status: built
baseline_revision: '198b2aa6a4af9bbdd7e6483f385db65a130de12c'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: false
context:
  - 'tests/test_benchmarks.py'
  - 'docs/README.md'
  - '.env.example'
  - 'mkdocs.yml'
---

## Intent

**Problem:** 票面要求 `docs/performance.md`：含分析方法、常见瓶颈、优化建议、参数说明与推荐值、
测试方法。当前 `docs/` 无此页；性能知识散在三处——`docs/README.md` 的「性能基准」节只有三条
benchmark 命令、`docs/testing.md` 讲门禁、`.env.example` 有参数但不说「什么时候该调」。

**Verify 拆解：**
- 「分析方法」→ 三层取证路径：日志/事件流的时点字段 → pytest-benchmark 基线 → 单点 profile。
- 「常见瓶颈」→ 按「时间花在哪一段」列，不写「代码很慢」这类空话；每条给可观测判据。
- 「优化建议」→ 每条对应一个开关或一次结构调整，并写明代价。
- 「参数说明与推荐值」→ 表格：键 / 默认 / 推荐 / 何时改；推荐的依据写在「何时改」列。
- 「测试方法」→ `pytest -m benchmark` 的入库-对比-判读闭环，与 `docs/README.md` 的「性能基准」
  节口径一致（那里是命令清单，本页是判读与调参）。

**Approach:** 新增 `docs/performance.md`；所有数字取自 `.env.example` 的默认值与
`tests/test_benchmarks.py` 的既有用例，不新造基准、不改代码。

## Boundaries & Constraints

**Always:**
- 默认值与键名必须与 `.env.example` 逐字一致；推荐值必须说明「为什么是这个值」与代价。
- 常见瓶颈必须有代码层判据（哪个事件、哪个配置、哪段调用），不写泛泛经验。
- benchmark 命令与 `docs/README.md`「性能基准」节一致：`-m benchmark` + `--benchmark-autosave`
  / `--benchmark-storage` / `--benchmark-compare` 都只认命令行旗标，且基准目录 `./benchmark-data/`
  已 gitignore。
- 与 `docs/frame.md` 的模块边界一致：不得把「优化」写成跨层直连（如 network 直接读运行栈）。

**Never:**
- 不宣称尚未实现的优化（Epic 66 的 provider 元数据缓存 / 技能匹配缓存 / 批量预计算 / 懒加载 /
  延迟导入全部是 planned）——只写**当前**存在的机制与开关。
- 不给「绝对值耗时」的承诺（机器与模型差异太大）；只给相对判据与回归方法。
- 不新建 `docs/` 之外目录，不改 `tests/test_benchmarks.py`。

## Code Map

- `docs/performance.md` — 新建：五节（分析方法 / 常见瓶颈 / 优化建议 / 参数与推荐值 / 测试方法）。
- `docs/README.md` — 索引表 + 条目列表补「性能调优」入口；「性能基准」节加一句指向本页的判读说明。
- `mkdocs.yml` — `nav:` 补 `性能调优: performance.md`。
- 事实源（只读）：`tests/test_benchmarks.py`（14 个既有基准：token 估算 / 压缩 / 工具注册 /
  技能匹配 / 大消息列表 / 单次迭代 / 8 个并发工具 / 恢复历史 / rollout 写 50 事件）、
  `.env.example`（第 5/6/7/8/9/11/17/18 节的默认值）、`docs/README.md`「性能基准」节（命令口径）、
  `docs/testing.md`（门禁判读）、`engine/observability` 的事件字段（`provider_call_completed`
  的 `duration_ms` / `actual_tokens`）。

## Tasks & Acceptance

**Execution:**
- [ ] `docs/performance.md` — 新建五节 — 票面主体
- [ ] `docs/README.md` — 索引表 + 条目列表各补一行，并在「性能基准」节指向本页 — 可发现性
- [ ] `mkdocs.yml` — nav 补 `性能调优: performance.md` — strict 构建一致性

**Acceptance Criteria:**
- Given 打开 `docs/performance.md`，when 看目录，then 五个二级节齐全（分析方法 / 常见瓶颈 /
  优化建议 / 参数说明与推荐值 / 测试方法）。
- Given 任一条「推荐值」，when 与 `.env.example` 对照，then 键名存在、默认值与文件一致，
  且给出改动的触发条件与代价。
- Given 「测试方法」节，when 照抄三条命令执行，then 与 `docs/README.md`「性能基准」节不矛盾
  （同旗标、同目录、显式说明 benchmark 默认被 deselect）。
- Given 全文，when 搜 Epic 66 的五个优化名（元数据缓存 / 匹配缓存 / 批量预计算 / 懒加载 / 延迟导入），
  then 不出现「已实现」表述。
- Given 仓库根，when 运行 `mkdocs build --strict`，then 构建成功无告警。

## Implementation Notes

## Implementation Notes

- `docs/performance.md`：五节（分析方法 3 层 / 常见瓶颈 9 行 / 优化建议 7 条 / 参数表 4 组 / 测试方法闭环）。
  所有键名与 `.env.example` 逐一核对（脚本 `for k in ...; grep -q "$k=" .env.example`，0 missing）。
- 用例数按实测改成 **14**（`pytest -m benchmark -q --co` 收 14 条），原稿写 15 是未核实数。
- `docs/README.md`：索引表 + 条目列表各补一行，「性能基准」节加一行指向本页的判读说明（命令仍只在该节）；
  `mkdocs.yml` nav 补 `性能调优: performance.md`；`mkdocs build --strict` 通过。
- 9p 新品同样要 `git add --chmod=-x docs/performance.md`。

## Review Triage Log

- 2026-11-18 quick lens（1 个 reviewer，17 findings）：patch 8 / false 7 / maybe-false 2。
- patch：用例数 15→14（含 plan 的 Verification 期望值）；`mode` 取值写实为
  `direct` / `sandbox_required` / `approval_required`（`engine/policy.py:68-70`）；
  `heagent replay` 示例补 `--json`（默认输出是渲染后的人读行，不含事件名）；
  `--benchmark-compare=0001` 说明为**示例 save id**（autosave 每次新增编号，不能一直写 0001）；
  「数量级守护」改为「劣化守护」（50% 不是数量级）；二表「长任务被误杀」不再把默认 0 的
  `HTTP_REQUEST_TIMEOUT` 当成成因；`TOKENIZER` 行的 `delta` 标明是日志文本而非事件字段；
  cProfile 示例改跨平台路径并要求在仓库根执行；`MAX_ITERATIONS` / `SUBAGENT_*` 从「并发与缓冲」
  拆出成「迭代预算」。
- false：`HTTP_MAX_CONNECTIONS` / `HTTP_MAX_SUBSCRIBERS` / `HTTP_MAX_TOTAL_INFLIGHT`「不在允许清单」——
  三者都在 `.env.example` 第 18 节真实存在，是 reviewer 拿到的清单不完整；「`heagent replay` 可能不存在」——
  `cli/console.py:445` 有该子命令、README 也列了（reviewer 把 open-items 里的「rollout 自动重放未做」
  误当成命令不存在）；`faq.md` / `errors.md` 两条「越范围/死链」——两者是 64.1/64.2 的产物、已在工作树。
- maybe-false：`100755` 文件模式（9p 不支持 chmod）；README 条目里的「35 码 + 9 异常」计数
  （两份文件都是封闭集合并有契约测试钉死，短期不会陈旧）。

## Plan Change Log

## Review Triage Log

## Design Notes

不写「各模块耗时占比表」：本仓没有跨机器可复现的占比数据，编一张表比不写更坏。改为给
「观测点 → 你能看到什么 → 怎么判读」的因果链，让读者在自己的机器上取样。

## Verification

**Commands:**
- `.heagent/tmp/py311-venv-linux/bin/python -m pytest -m benchmark -q --co` -- expected: 列出 14 条用例
- `.heagent/tmp/py311-venv-linux/bin/python -m mkdocs build --strict` -- expected: 构建成功（mkdocs 是构建期工具、不在依赖树，本机 venv 已装 1.6.1）
- `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_release_workflow_contract.py -q` -- expected: pass
