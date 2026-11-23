# ADR-005 · 远程多项目控制 = WS 单通道 + 项目编址

> **状态**：accepted（2026-11-23 设计访谈收口；实现未排期，票树待立项）
> **来源**：远程 app 多项目控制设计访谈（grill-with-docs 三轮定案，决策树无静默假设）
> **治理面**：WS 远程面协议形状、HTTP 面暴露边界、远程会话/审批语义、多项目并发口径

**Context.**
远程 app（自研 APK 客户端）要经本 agent 驱动多个独立项目并行开发（2~5 个、单机 Windows）。
现状两条入口能力错位：WS external 档有完整认证（Bearer+TLS pin+节流+slot 池）但提交帧只有
`prompt` 一个字段（`extra="forbid"`），指不了项目；而项目编址与按项目运行时（围栏根、会话、
产物、ledger、memory 全部 per-project 根 + 项目独立并发名额）已在 HTTP 回环控制台面完备
（`POST /api/projects/{id}/runs` → `HttpProjectConsole`）。即**「认证 + 项目编址」没有一条
同时成立的远程通道**——这是本决策要补的核心缺口。

配套事实（访谈中核实）：服务面审批 = fail-safe 拒绝不挂死（`HttpAgentHandler` 刻意不装
审批 handler，`APPROVAL_REQUIRED` 被 executor 等同 BLOCKED，工具转 error 结果、run 继续
终态）；容器沙箱档实际生效时可放松审批；HTTP 项目链会话缺省续该项目最近会话（同 CLI
`--continue` 口径），WS 提交链无会话语义（每次新会话且不落盘）。

**Decision.**
远程面收敛为 **WS 单通道**，项目编址进 WS 协议：

- 提交帧加**可选 `project_id`**：缺省 = 启动工作区（现状行为不变），带值 = 走项目链
  （吃该项目并发名额、per-project 运行时）。HTTP 面维持回环本机语义**完全不动**，
  不给 HTTP 新建远程认证体系。
- 远程面**四件事**：列项目（新控制帧；远程投影只给 `id/name/available`，不带 path）、
  提交项目 run、订阅事件流（复用现有 `/api/runs/{run_id}/ws`）、取消 run（新增
  `cancel_run` 帧）。配置读写、项目注册、会话历史浏览**不开放**给远程端（远程注册
  维持 403，准入仍在回环面）。
- **一次性任务提交**：WS 帧不暴露 `session_id`；带 `project_id` 的 run 会话语义
  **对齐 HTTP 项目链**（缺省续该项目最近会话），保证同一项目从网页与从 app 提交行为一致。
- 审批维持现状 fail-safe 拒绝（远程端在事件流里只见 `tool_error=True` 的 tool_result），
  不加远程审批通道；误拒压力由容器沙箱档的既有放松路径缓解。
- run 事件信封**不加** project_id 字段（app 侧提交时本地记 `run_id → project` 映射）；
  并发容量参数全不动（`HTTP_MAX_CONNECTIONS`/`HTTP_MAX_INFLIGHT_RUNS`/
  `HTTP_MAX_TOTAL_INFLIGHT` 维持默认）；沙箱维持「强烈建议 docker」口径，external 档
  非 docker 沙箱补一条启动 WARNING。

**Why.**
认证、TLS、限速、slot 语义全在 WS 侧现成；给 HTTP 另起一套远程认证等于再造半个安全面，
且与「HTTP = 本机控制台」的现行立场冲突（**否决方案 B**：认证化 HTTP 项目链对外）。
per-project 端口 / 多实例编队对单机 2~5 项目是运维面膨胀（**否决方案 C**）。同一项目的
run 在两条入口必须同语义，故项目 run 会话取 HTTP 项目链口径而非 WS 现状口径。审批交互
与「一次性提交、控制面四件事」的范围裁定直接冲突，且经查挂死风险不存在（拒绝而非等待）。

**Consequences / 风险.**
- 实现切口集中：`network/ws_protocol.py`（帧模型 + 契约测试随迁）、
  `network/ws_server.py::_submit_run` 按 project_id 路由项目链、`cli/http.py`/`ws_host.py`
  装配点注入项目控制台、external 档启动 WARNING、`docs/framework.md` 远程面一节。
- WS 协议新增三种帧 ⇒ 契约测试是硬要求；APK 客户端将按此契约开发，帧形状变更即破坏性变更。
- 远程端不能写配置、注册项目、浏览会话历史——有意的最小面，不是缺陷；操作须回本机
  web 控制台 / CLI。
- 验收基线：APK 列项目 → 两项目**同时**各提交一个 run → 各自收完整事件流 → 取消其一 →
  断线重连凭 cursor 续流不丢事件。
- 挂账（本访谈明确不做，升级须再议）：per-project token、两段式注册确认、多轮续聊 /
  session 寻址、远程审批通道、per-project provider/model、跨项目协同、沙箱 fail-closed
  强制、goal/loop 远程驱动。
