---
epic: epic-66-性能优化
date: 2026-11-18
verdict: accepted
criteria: declared
headless: false
---

# Epic 66 Retrospective

> 路径约定：`tickets/story-66.*` 均相对 `_bmad-output/initiative-heagent/tickets/epic-66-性能优化/`；
> 其余路径相对仓库根。实测为收口现场取证（2026-11-18，容器内 `.heagent/tmp/py311-venv-linux/bin/python`）。

## Epic summary

**Epic**：epic-66-性能优化（R4；5 story，全部新建）

**票态**：5/5 `done`（`tickets.py mark` 逐条置位），无 `dropped`。

| Entry | 交付 | 提交 |
|---|---|---|
| 66.1 Provider 元数据缓存 | `providers/metadata_cache.py`（LRU + `hits`/`misses`/`hit_rate`），接入 `SwitchableProvider` / `ProviderChain` | `f826aaf` |
| 66.2 技能匹配结果缓存 | `skills/skill_catalog.py::SkillMatchCache` + `skill_library_fingerprint()`（mtime/size 摘要） | `6752b96` |
| 66.3 批量预计算 | `SkillMatchIndex` / `build_skill_index()`，`match_skill_details` 改为「取索引 → 集合运算」 | `6752b96` |
| 66.4 技能包懒加载 | `SkillCatalog._index_package` 复用首次 entry 解析（2 读 → 1 读） | `d542a22` |
| 66.5 延迟导入大型依赖 | `providers/{openai,anthropic,responses}.py` 的 SDK 导入改 PEP 562；`providers/__init__.py` 改 `_EXPORTS` 路由表 | `0b1b156` |

## 收口现场补的两件事

1. **66.1 的聚合层没接全**：Intent 点名 `SwitchableProvider` / `ProviderChain` / `RoutingProvider` 三层，
   实际只接了前两层，`KeyRotatingProvider` 在 Implementation 里被写成「留作后续 backlog」但台账无登记。
   收口按同一套纪律补齐：
   - `RoutingProvider` 池结构在 `__init__` 固定、叶元数据构造后不可变 ⇒ 缓存**不需要失效点**；
     顺带修掉 `_build_metadata` 对每个叶 provider 取 3 次元数据（model / streaming / tools 各一次）的重复构造；
   - `KeyRotatingProvider` 的 `_current_index` 收编为唯一写点 `_set_current_index()`（真变才失效），
     与 `SwitchableProvider._set_active` / `ProviderChain._set_current_index` 同形；
   - 判据：`tests/providers/test_metadata_cache.py` 19 例（新增 5 例：池级缓存、`set_force` 不失效、
     轮换后跟随、成功不空转失效、共享缓存注入）。
2. **「冷启动降低 >20%」此前无判据**：66.4 / 66.5 的 `verify` 与 Epic `Done when` 都要求它，
   但仓库里只有「`openai`/`anthropic` 不在 `sys.modules`」这一条**性质**判据；66.5 记的 13208ms→1074ms
   是 9p 抖动旁证。收口补成**比值判据**（`tests/test_deferred_imports.py::test_cold_import_is_at_least_twenty_percent_cheaper_than_loading_sdks`）：
   干净子进程里 `import heagent` 的最快耗时必须 < `import openai, anthropic` 最快耗时的 80%
   （本机实测比值 ≈ 0.08，阈值 0.8 留足余量；绝对毫秒数不参与断言）。

## 收口现场发现的真缺陷：benchmark job 把比值判据整片跳过

`ci.yml` 的 `benchmark` job 用 `pytest --benchmark-only -m benchmark`。`--benchmark-only` 只跑**使用
`benchmark` fixture** 的用例 ⇒ 66.2 的「提速 >30%」与本次新增的冷启动判据（都是纯计时比值、不用 fixture）
在 CI 里**从未执行**（实测 `pytest --benchmark-only -m benchmark -q tests/test_skill_match_cache.py`
→ `1 skipped`）。处置：两处 `pytest ... -m benchmark` 去掉 `--benchmark-only`（`-m benchmark` 已把范围收在
性能面），并把理由写进 `docs/performance.md` 与 `ci.yml` 注释。

## 门禁实测（2026-11-18 收口）

```text
pytest -q                                        → 5208 passed / 51 skipped / 30 deselected / 1 xfailed（296 s）
pytest -m benchmark（口径确认用）                 → 2 passed / 18 deselected（32 s）
ruff check src tests scripts examples            → All checks passed
ruff format --check src tests scripts examples   → 499 files already formatted
mypy src                                         → Success（229 files）
bandit -r src/ -ll                               → 退出码 0（High-confidence 8 条均为既有低严重度项）
mkdocs build --strict                            → 0 warning
```

## 决策与刻意不做的事

- **不给缓存加 TTL / 锁**（66.1 的四条设计前提）：失效条件是「活跃指针变了」，用显式 `invalidate` 表达；
  `get_metadata()` 同步无 await 点，单线程事件循环内访问。
- **不给叶 provider 接缓存**：叶元数据构造便宜且不可变，接入只会多一层无意义抽象。
- **不做跨进程的技能匹配持久缓存**：指纹只覆盖本进程能读到的文件状态，跨进程一致性没有真源。
- **冷启动判据用比值不用绝对毫秒**：CI 机器与 9p 挂载的绝对耗时不可比（本机首轮测得的
  13208ms 就是挂载抖动，不是代码差异）。
- **不把 `benchmark` 从 `-m benchmark` 移进默认门**：冷启动判据要起 5 个子进程，默认门（5208 例 / 296 s）
  不该再为它付 30 s。

## Open questions / 残留

1. **缓存观测面没有运行时出口**（登记 **A59**）：`hits` / `misses` / `hit_rate` 只能在代码里读
   （`metadata_cache` 属性），容量也只有构造参数（无 Settings 键）⇒ Epic `Done when` 的「命中 >80%」
   目前是单测合成证据，不是线上事实。触发条件 = 需要判断缓存是否真生效，或要一个配置旋钮。
2. **`KeyRotatingProvider` 的缓存收益未经真实池验证**：池内各实例通常同模型 ⇒ 元数据相同，
   失效只在「池成员配了不同模型」时才有可观测差异；本 story 只保证语义正确，不宣称收益。
3. **技能库指纹依赖文件 `mtime_ns` / `size`**：粗粒度时间戳的文件系统（FAT、部分网络盘）上，
   「同一毫秒内改两次且大小不变」会漏失效；本仓技能库写入是低频人工操作，暂不作处理。
