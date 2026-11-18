---
title: 'Story 66.1 实现 Provider 元数据缓存'
type: perf
ticket: 1
created: '2026-11-18'
status: done
baseline_revision: '0a70447'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'src/heagent/providers/metadata_cache.py'
  - 'src/heagent/providers/switchable.py'
  - 'src/heagent/providers/chain.py'
  - 'tests/providers/test_metadata_cache.py'
---

## Intent

`get_metadata()` 是同步、无 IO、却每轮都调用的方法：状态行（`cli/display.py`）、路由决策、
`/provider` 列表都会重建 `ProviderMetadata`（Pydantic 模型 ⇒ 每次构造都要校验）。聚合层
（`SwitchableProvider` / `ProviderChain` / `RoutingProvider`）转发到底层 provider，同一份
不变的信息被反复构造。

**Approach：** 新增 `providers/metadata_cache.py::ProviderMetadataCache`——以 provider 对象为
key 的 LRU（容量默认 64，可配置），提供 `get(provider)` / `invalidate(provider)` / `clear()` 与
`hits` / `misses` / `hit_rate` 观测面。接入点选**聚合层**（它们的返回随内部 active 变化）：

- `SwitchableProvider.get_metadata()` / `ProviderChain.get_metadata()` 经缓存取值，
  在 active 切换后与失败回退后 `invalidate(self)`；
- 叶子 provider 的 metadata 构造便宜且不可变，不接入（避免无意义抽象）。

## Verify

- 命中率：预热 1 次后连续 99 次调用，`hit_rate` = 99%；容量上限生效（max_size=2 时第 3 个
  provider 淘汰最旧）；`invalidate()` 后重新计算且计数正确。
- 正确性：`SwitchableProvider` 切 active 后再取 metadata，`name` 跟随新 active（证明失效接线到
  切换路径，不是过期值）。
- `pytest tests/providers -q` 全绿；`tests/test_architecture_contracts.py` 全绿。

## Boundaries

- 不加锁：`get_metadata()` 本身同步且无 await 点，缓存只在单线程事件循环内被访问。
- 不加 TTL：元数据的失效条件是「provider 内部状态变了」，用显式 `invalidate` 表达，时间无关。
- 不改 `BaseProvider` 协议，不改 `ProviderMetadata` 模型。
- 不把缓存做成全局单例（跨 provider 实例共享 key 会串味）。

## Implementation（实测）

- 落点：`providers/metadata_cache.py`（LRU + `hits/misses/hit_rate`）；`SwitchableProvider._set_active()` 与
  `ProviderChain._set_current_index()` 收编为活跃指针**唯一写点**，值真变才 `invalidate`（无操作切换不打穿命中率）。
- 实测：`pytest tests/providers -q` → 217 passed（新增 13 例）；命中率断言为 99 次调用 1 次未命中
  （`hits 99 / misses 1 / hit_rate 0.99`）；`ruff check` 与 `mypy src/heagent/providers` 全绿。
- 未接入 `KeyRotatingProvider`：同一模式的下一落点，留作后续 backlog，本 story 不扩范围。
