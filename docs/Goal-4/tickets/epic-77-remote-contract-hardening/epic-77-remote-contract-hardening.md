---
type: epic
code: E77
parent: brief
slug: epic-77-remote-contract-hardening
covers: ["R1", "R2", "R3"]
sources: ["docs/Goal-4/brief.md", "docs/Goal-4/architecture-ws-remote-project-channel/architecture-ws-remote-project-channel.md", "docs/decisions/adr-0005-ws-remote-project-channel.md"]
after: ["epic-74-ws-frame-contract", "epic-75-project-channel-runtime", "epic-76-remote-surface-closeout"]
risk: medium
refined: true
status: done
---

# E77 · WS 远程项目通道：三处延迟裁决落地（幂等键 / 具名码 / 只读能力面）

## Description

E76 收口时把三条**超出当轮落改范围**的裁决挂到 `brief.md`「延期项」：M-4 提交无幂等键、M-7
「未装配」与「帧拼错」共用 `invalid_request`、H-2 只读 listener 是否需要 `projects`。2026-11-24
用户逐条裁决（M-4 取最小幂等形态、M-7 新增具名码、H-2 维持零能力面只改措辞）⇒ 本 epic 把三条
裁决落成代码与文档，并把裁决结果回写需求真源。

## Requirements

- **R1**（← 延期项 M-4，最小幂等形态）`run` 帧新增**可选** `request_id`（1–64 字符、不 strip）；
  同一 `(project_id, request_id)` 在 60s 窗口内重复提交时服务端只调用一次控制台
  `start_project_run`、两个 ack 的 `run_id` 相同；不带 `request_id` 的旧帧逐字等价（每次都是新提交）。
  幂等只覆盖**成功**提交：失败不缓存（重试可以重来），「提交失败不做原子性保证」这条既有口径不变。
- **R2**（← 延期项 M-7）「项目通道未装配」可凭**码**分流：`project_channel_unavailable`（run 与
  `projects` 两条路径），而「帧字段拼错」仍是 `invalid_request`；`HttpErrorCode` 只增
  （36 → 37），`transport_errors` 基线重生成后 diff 只含这一条。
- **R3**（← 延期项 H-2）只读 listener 的能力面写成**可判定**的「零能力面」：其上不注册集合级端点
  ⇒ `projects` 不可达；架构 AD-8 的「只读 listener 上 `projects` 允许」与代码矛盾处改成与实现一致
  的措辞；`brief.md` 三条延期项全部带裁决结果与落点。

## Outcome

- 远程客户端可以安全重试一次提交：拿不到 ack 时用同一 `request_id` 重发，服务端不会再起第二个 run。
- 「服务端没装好项目通道」与「我的帧写错了」在客户端是两种处置：换环境 / 改代码，不用读文案。
- 只读 listener 的对外承诺与代码一致，不再留一条「文档说允许、代码不可达」的矛盾；延期项段不留
  「待裁决」字样。

## Boundaries

- 不做跨进程 / 落盘幂等（进程重启后窗口消失，这是**显式**选择，写进 docstring 与文档，不假装持久）。
- 不给提交失败补原子性、不新增「提交事务」概念；不改名额与并发参数。
- 不新增 WS 命令、不新增帧类型、不给 ack 加字段（`{type,command,run_id,status}` 四格冻结）。
- 不给只读 listener 新开端点或放开 `projects`（H-2 裁决 = 维持零能力面）。
- 不动 HTTP 回环面语义，不改 `project_id` 派生规则。

## Done when

- `pytest tests/network tests/test_ws_project_adapter.py -q` 全绿，且含：同 `request_id` 重发 ⇒ 控制台
  调用 1 次、两 ack 同 `run_id`；未装配 ⇒ `project_channel_unavailable`；帧拼错 ⇒ `invalid_request`。
- `python scripts/contract_snapshot.py --check` 五份全 `[OK]`，`transport_errors.json` diff 只含
  `project_channel_unavailable` 一条。
- `mkdocs build --strict` 0 warning；`brief.md` 延期项三条均带「裁决日期 + 结论 + 落点」。
- `ruff check` / `ruff format --check` / `mypy src` / `bandit -r src/ -ll` 与 HEAD 同谱。

## References

- `docs/Goal-4/brief.md`（需求真源兼信封，延期项段即本 epic 的来源）
- `docs/Goal-4/architecture-ws-remote-project-channel/architecture-ws-remote-project-channel.md`（AD-8）
- `docs/framework.md` §4.16 / §4.16.1（WS 帧面、项目通道、只读旁观、错误码表）

## Notes

- 2026-11-24 Decision：M-4 只做**内存**幂等（60s TTL / 256 条上限 / 在途 Future 合流），理由是落盘
  幂等会把「提交」升级成有持久状态的事务，与既有「不提供原子性」立场冲突；进程重启后窗口消失属
  已知且有意的边界。
- 2026-11-24 Decision：H-2 不新增能力。取证依据 = `WsServerConfig.readonly` 自 Epic 72 起**无入口层
  配置键**（`docs/framework.md` §4.16.1 只读旁观行），生产实例不存在只读 listener ⇒ 给它开端点没有
  消费方。
