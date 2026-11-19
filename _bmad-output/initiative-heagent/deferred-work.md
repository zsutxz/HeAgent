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
- source_plan: `_bmad-output/initiative-heagent/tickets/epic-71-web-server-status/tickets/story-71.6-web-status-panel-plan.md`
  summary: Epic 71 review 的证据补齐批（11 条）统一折进台账 **A74**，不随 epic 收口逐条立项。
  evidence: 2026-11-19 两个镜头（`edge-case-hunter` + `verification-gap`）× 6 story 的独立子代理评审；当场修 12 处（provider 运行期读、cron 先过滤再截断、proc_stats 捕获面、面板取数超时、统计范围标注等），余下 11 条为「行为已正确但无判据」的证据缺口（前端执行级探针缺失、真实来源计数映射、装配接线与 `_clip` 上限、`/proc` 失败路径与 Windows 分支等），逐条正文见各 plan 的 `## Code Review` 与 `open-items.md` A74 行。另两项为待用户裁定（沙箱档位报请求值 vs 生效值；SSE 延迟是否计入 p50）。
  closure: 2026-11-19 逐项补判据闭合（A74 移入 `retrospective-all-cycles.md` §三「本轮闭合」）——9 项测试证据 + 2 项 code 修复（Win32 签名声明、关闭后清启动起点）；node 探针在无 node 的 CI 恒 skip，CI 侧字段覆盖证据由结构守卫承担。
