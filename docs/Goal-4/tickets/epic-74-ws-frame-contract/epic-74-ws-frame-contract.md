---
type: epic
code: E74
parent: brief
slug: epic-74-ws-frame-contract
covers: ["R2", "R5", "R6", "R8", "R10"]
sources: ["docs/Goal-4/prd-ws-remote-project-channel/prd-ws-remote-project-channel.md", "docs/Goal-4/architecture-ws-remote-project-channel/architecture-ws-remote-project-channel.md", "docs/decisions/adr-0005-ws-remote-project-channel.md"]
after: []
risk: medium
refined: true
---

# E74 · WS 远程项目通道：协议与帧契约

## Description

远程提交帧现状：`external` 档帧族只有 `prompt` 一个字段，且 `ws_protocol.py` 6 处 `extra="forbid"` ⇒ 远程无法指定项目。本 epic 只做**协议与端口的形状**，不做运行时接线：

- 提交帧新增可选 `project_id`（`min_length=1`，缺省 `None` = 启动工作区，与改动前逐字等价）；不引入连接级项目绑定（D2）。
- 未知 / 不可用 `project_id` 的具名 `WsErrorFrame` 与错误码（登记进 `transport_errors`）；不建 run、不占名额。
- 新增 `cancel_run` 帧：与既有单 run 端点 `cancel` 同源 ⇒ readonly listener 下回 `invalid_request`（N8 / Q4）；不误杀其它 run。
- 事件面零变更：订阅复用既有 `/api/runs/{run_id}/ws`，事件信封不加 `project_id`（D7），带该键仍判 `WsFrameError`，golden 信封逐字不变。
- 传输层仍是哑传输：`RunWebSocketService` 是 Protocol（`network/ws_server.py:89` / `:110`）⇒ 加字段必须同改 Protocol 与实现；项目解析器与投影纯函数只以**注入端口**出现，装配在入口层（`cli/http.py:449` / `:789` 的 `run_service=` 先例），`network/` 不 import 运行栈 / 配置（N2）。

本 epic 不含：注册表读取与投影、会话续接、六项落点（E75）；并发编排、启动告警、契约快照收口（E76）。

## Requirements

- **R1** 命令帧：`run` 新增可选 `project_id`（`min_length=1` / `max_length=16` / 不做 strip）；键缺失或 `null` 时解析结果与改动前逐字等价，`""` 判 `malformed`；字段白名单由模块级 `_FRAME_FIELDS`（命令 → 允许键集合）单一映射表驱动，覆盖 `WsCommand` 全部成员，解析器与模型校验器读同一张表。（← PRD R2；AD-4）
- **R2** 注入端口形状：新增 `ProjectChannelService` Protocol（声明在 `network/ws_server.py`，方法参数名不含 path / workspace / session 类）与 `SubmittedRun`（不含 `session_id`）；两个端点构造器以**关键字参数** `project_service=None` 接收；`None` 时带 `project_id` 的提交回 `invalid_request` 且不触发任何启动路径——禁止静默按启动工作区执行。（← PRD R10；AD-1 §4.3）
- **R3** 带 `project_id` 的提交按「先 `ensure_available` 后 `start_project_run`」次序执行；失败时 `HttpRunConflictError.code` 逐字透传到错误帧、连接保留、零副作用（`start_run` 与 `start_project_run` 调用次数均为 0）。（← PRD R5）
- **R4** 提交 / 取消径可能产生的全部 code（`unknown_project` / `project_unavailable` / `project_busy` / `run_conflict` / `total_inflight_limit` / `unknown_run` / `invalid_request`）均为 `HttpErrorCode` **既有**成员（实测 `network/http_protocol.py:58` 起已全部存在），且在 `transport_errors` 基线内有条目；本 epic 不新增错误码、不重生成快照。（← PRD R5）
- **R5** 新增 `cancel_run` 帧（`run_id` 必带）：与既有单 run 端点的 `cancel` 同源（同一 `cancel_run(run_id)` 端口）；单 run 端点上 `run_id` 必须等于该连接绑定的 run，否则 `invalid_request` 且不断连；`readonly` listener 上 `cancel_run` 回 `invalid_request` 且不断连；目标已终止回终态 ack（幂等），目标不存在回 `unknown_run` 且不断连。（← PRD R8）
- **R6** 事件面零变更：`WsAckFrame` / `WsEventFrame` 的字段集合不变，事件帧带 `project_id` 仍判非法；golden 事件信封逐字相等；订阅仍复用既有 `/api/runs/{run_id}/ws`，本 epic 不新增任何路由。（← PRD R6）
- **R7** `network/` 保持哑传输：新增代码对 `heagent.cli` / `heagent.config` / `heagent.pub.projects` / `heagent.engine` / `heagent.agent` 零 import，`is_dir` 零命中，`pytest tests/test_architecture_contracts.py -q` 绿。（← PRD R10）

## Outcome

- 帧层扩张对既有消费方无感：不带 `project_id` 的提交与订阅行为逐字不变。
- 坏 `project_id` 是一次**判定过的失败**而不是错题：具名错误码 + 零副作用（无新 run、名额不动）。
- 取消变成一条有明确权限口径的路径：与既有 `cancel` 同源，readonly 下 `invalid_request`。
- 事件协议零漂移：golden 信封逐字相等，`project_id` 不出现在事件面。
- 依赖边界机器可判：架构契约测试绿，`network/` 对运行栈 / 配置零新增 import。

## Boundaries

- 不实现项目解析、投影、会话续接、六项落点（E75）；不重生成契约快照、不改文档（E76）。
- 不改 HTTP 回环控制台面任何语义（NG12）：既有项目链请求模型只作校验口径对齐源。
- 不新增端点、端口、证书物料或信任锚；不开远程审批通道（NG4）。
- 不动并发容量参数（NG11）；不做 per-project token（NG1）。
- 不做沙箱 fail-closed（NG7）—— 非 docker 沙箱的启动告警属 E76。

## 已知 Done when

- 提交帧带 / 不带 `project_id` 各有可跑用例；缺省路径的既有 WS 测试断言逐字未改且全绿。
- 未知 / 不可用 `project_id` 用例断言三件事：无新 run、名额计数不变、错误码已登记进 `transport_errors`。
- `cancel_run` 用例断言：目标 run 到终态、另一 run 仍活、readonly listener 回 `invalid_request`。
- golden 事件信封逐字相等用例 + 事件帧带 `project_id` 判 `WsFrameError` 用例。
- `network/` 依赖边界 grep 零命中，`pytest tests/test_architecture_contracts.py -q` 绿。
