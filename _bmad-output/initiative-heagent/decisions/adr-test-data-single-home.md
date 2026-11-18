# ADR-002 · 测试数据唯一宿 `tests/fixtures/`

> **状态**：accepted（Epic 63 retro 提案，2026-11-18 用户批准）
> **来源**：plan `tickets/epic-63-测试体系增强/tickets/story-63.7-test-data-mgmt-plan.md`；commit `b75075a`
> **治理面**：`tests/` 树内所有静态测试数据

**Context.** 测试数据此前散落在 `tests/js/`、`tests/contract_baselines/`、`tests/network/` 等多处，引用方式靠各文件自行拼路径，迁移一次就有断链风险（63.7 一次搬迁涉及 4 份契约基线 JSON 与 2 个 node 探针）。

**Decision.** `tests/fixtures/` 是 `tests/` 树内唯一的静态测试数据存放点，分域目录（`ws_tls/`、`contract_baselines/`、`js/`）+ 域名级 `README.md` 说明来源与再生方式；引用一律经 `Path(__file__)` 锚定或 conftest 的 `fixtures_dir` fixture，禁止裸 CWD 相对字符串。守卫是 `tests/test_fixtures_contract.py` 的三条可执行判据：stray 非 `.py` 文件即红并点名、`README.md` 必须登记全部数据域、`fixtures_dir` 必须解析到真实根且 `ws_tls` 材料在位。

**Why.** 约定写在文档里会腐化，写成判据才有强制力——新增数据一旦放错位置，测试立刻点名而不是等某次迁移后发现断链。`__file__` 锚定保证从任意 CWD 启动 pytest 都成立（裸相对路径在多项目控制台/容器场景会断）。
