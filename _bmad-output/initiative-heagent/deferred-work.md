# Deferred Work — initiative-heagent

> 由 bmad-build split/拆分裁定产生的缓做项登记。台账（活动/未闭合问题）仍在根级 `open-items.md`，本文件只收从具体 plan 拆出去的目标。

- source_plan: `_bmad-output/initiative-heagent/tickets/epic-62-代码架构重构/tickets/story-62.1-network-http-server-py-plan.md`
  summary: 台账 A52（engine/hooks.py 坏 hooks.json fail-fast）不随 story 62.1 顺带实现，单独排队。
  evidence: 2026-11-15 bmad-build plan 体量 gate：62.1 本体 + A52 合并后约 2000+ token，超 1600 标准，用户裁定拆出 A52 以收窄 plan；A52 在根级 open-items.md 仍为 active，触发条件不变（下一实现周期 quick-dev 一发子弹）。
- source_plan: `_bmad-output/initiative-heagent/tickets/epic-62-代码架构重构/tickets/story-62.1-network-http-server-py-plan.md`
  summary: /loop workflow.md 悬空引用 `.heagent/tmp/bmad_sync/sync_roles.py`（盘面不存在，tmp 为草稿区）。
  evidence: 62.1 review 发现 F5，属实但非本 story 改动所致——源自上游独立提交 70f1484（/loop v7 工作流重写）；被提交的过程契约指向临时缺席路径，违反该工作流自身完整性标准；待 /loop 维护周期修正。
- source_plan: `_bmad-output/initiative-heagent/tickets/epic-62-代码架构重构/tickets/story-62.1-network-http-server-py-plan.md`
  summary: workflow.md 把 `pull` 文档化为可选 dir（`pull [<dir>] <ref>`），tickets.py 实为必填 `dir` + 参数名 `id`。
  evidence: 62.1 review 发现 F6，属实但非本 story 改动所致——同源 70f1484；tickets.py:1838-1840 实证 `add_argument("dir")` 无 nargs="?"；文档契约失真待 /loop 维护周期修正。
- source_plan: `_bmad-output/initiative-heagent/tickets/epic-62-代码架构重构/tickets/story-62.1-network-http-server-py-plan.md`
  summary: 治理：/loop v7 重写（70f1484）自成一体的第二改动集，无票树 coverage。
  evidence: 62.1 review 发现 F7——initiative 仅 62.1+catalog 两 plan，loop 文件不在任何 plan，违背「新工作唯一入口 = 票树」；非代码缺陷，呈报用户裁定补票或追认（2026-11-15 62.1 review 提出）。
  closure: 2026-11-15 用户裁定**追认闭合**——不补票（工作已落地且并行会话收尾中，事后簿记无调度价值；/loop 系 BMAD v7 工具链对齐，8 epic 无自然归属），票树规则只约束今后新工作。
