# Step 01 · market-research 报告

- 目标：`Goal-4`（实现 ADR-005 远程多项目控制的 WS 单通道 + 项目编址）
- 执行角色：`bmad-agent-analyst`（headless 子会话）
- 执行日期：2026-11-23
- 输入：`docs/Goal-4/brief.md`、`docs/decisions/adr-0005-ws-remote-project-channel.md`

## 环境限制（影响本轮证据强度）

- 本环境**无 web 检索能力**：宿主 `web_search` 报「未配置引擎密钥（`WEB_SEARCH_API_KEY`）」，
  子会话工具集同样没有 `web_search` / `web_fetch`。
- 与台账 `A55` 同源：`WEB_SEARCH_API_KEY` 未入 `.env`，web_search 全链未经真实密钥验证。
- 因此本轮**全部外部同类产品论断按契约记为 gap**，不以训练数据补写；可复核证据只来自本仓库代码。

## 需求总结

（正文与 `brief.md` 的「总结的需求」段逐字一致，见该文件。）

- **事实（现状）**：远程唯一可提交通道是 WS external 档（Bearer token + TLS pin + 节流 + slot 池），提交帧只有 `prompt` 一个字段且 `extra="forbid"`，指不了项目。
- **事实（现状）**：项目编址与按项目运行时已在回环 HTTP 控制台面完备（`POST /api/projects/{id}/runs` → `HttpProjectConsole`；`src/heagent/network/http_console_protocol.py:389/455` 已有 `project_id` 字段），但该面只挂回环、无远程可达性。
- **需求**：远程面收敛为 **WS 单通道**；提交帧新增**可选 `project_id`**——缺省 = 启动工作区（行为不变），带值 = 走项目链（per-project 围栏根 / 会话 / 产物 / ledger / memory / 项目独立并发名额）。
- **需求**：远程只开放四件事——列项目（远程投影仅 `id/name/available`，不带 path）、提交 run、订阅事件流（复用 `/api/runs/{run_id}/ws`）、取消 run（新增 `cancel_run` 帧）。
- **需求**：远程不开放配置读写、项目注册（维持 403）、会话历史浏览；WS 帧不暴露 `session_id`，带 `project_id` 的 run 缺省续该项目最近会话（对齐 HTTP 项目链语义）。
- **需求**：审批维持 fail-safe 拒绝（远程端只见 `tool_error=True` 的 tool_result），不加远程审批通道；external 档非 docker 沙箱时补一条启动 WARNING。
- **需求**：run 事件信封**不加** `project_id`（客户端本地维护 run→project 映射）；并发容量参数不动。
- **假设**：自研 APK 能在本地维护 run→project 映射并对 cursor 做持久化（否则「断线续流不丢事件」不成立）。
- **假设**：「缺省续该项目最近会话」在既有 HTTP 项目链里已有等价语义，可直接对齐而不新增状态机；复用单 run 事件端点无需改动事件协议。
- **假设**：新 `cancel_run` 帧与既有单 run 端点 `cancel` 同源，因此 readonly listener 下仍回 `invalid_request`。
- **验收基线**：APK 列项目 → 两项目**同时**各提交一 run → 各自收完整事件流 → 取消其一 → 断线重连凭 cursor 续流不丢事件。
- **明确不做**：per-project token、两段式注册确认、多轮续聊 / session 寻址、远程审批通道、per-project provider/model、跨项目协同、沙箱 fail-closed、goal/loop 远程驱动。
- **开放问题（4 条）**：① 「非 docker 沙箱」判据取 `SANDBOX_BACKEND` 配置值还是启动期实际生效后端？② 列项目的 `available` 判定口径（目录存在 / 配置完整 / 围栏根可解析）？③ run 被取消后 cursor 与尾部事件的续流语义？④ `cancel_run` 是否继承「readonly listener 下 cancel 回 `invalid_request`」的既有约束？

## 市场综述

> 本轮能力声明：子会话与宿主均无 web 检索能力，下表外部同类产品论断一律未取证，按契约记 gap，不以训练数据补写。带「本项目现状」标签的条目是仓库内可复核证据。

- [本项目现状] 项目编址能力已存在但只落在回环 HTTP 面：`http_console_protocol.py` 的请求模型普遍 `extra="forbid"`，项目链请求带 `project_id: str = Field(min_length=1)`（`:389`、`:455`），说明「编址字段」在本仓是已验证形态，只是未进 WS 帧。—— 来源：`src/heagent/network/http_console_protocol.py`（本地代码证据），发布：未知，访问：2026-11-23
- [本项目现状] 需求真源已把「远程面收敛为 WS 单通道 + 可选 `project_id`」定为 accepted 决策，并显式否决「认证化 HTTP 项目链对外」（方案 B）与「per-project 端口 / 多实例编队」（方案 C）。—— 来源：ADR-005，发布：2026-11-23（决策日期），访问：2026-11-23
- [本项目现状] WS 帧全族 `extra="forbid"`（`ws_protocol.py` 的 `WsHelloFrame` / `WsEventFrame` / `WsAckFrame` / `WsCommandFrame` 等 6 处 model_config 均如此）⇒ 新增字段是**破坏性变更**，必须同时改帧模型与契约测试。—— 来源：`src/heagent/network/ws_protocol.py`，发布：未知，访问：2026-11-23
- [gap] VS Code Remote-Tunnels 如何在「单 tunnel」下承载多文件夹 / 多工作区选择（目标选择放连接层还是请求层）——**未取证**。—— 来源：gap（无 web 检索能力），发布：未知，访问：2026-11-23
- [gap] VS Code Remote-SSH 的 host 条目 / 多文件夹窗口如何影响单个连接上的目标归属与重连语义——**未取证**。—— 来源：gap，发布：未知，访问：2026-11-23
- [gap] JetBrains Gateway 的「一个客户端 → 多个 backend」是每 backend 一条连接还是单连接内按请求路由，以及后端端口分配策略——**未取证**。—— 来源：gap，发布：未知，访问：2026-11-23
- [gap] MCP 客户端（Claude Desktop / Cline 类）在一个会话里「选 server」的机制（每 server 一个 stdio/SSE 连接，还是单连接内带 server 标识）——**未取证**。—— 来源：gap，发布：未知，访问：2026-11-23
- [gap] 单连接内「请求级编址」的已知故障模式（并发名额被单客户端吃满、事件流归属错判、断线续流 cursor 语义）是否有公开事故记录或规范约束——**未取证**。—— 来源：gap，发布：未知，访问：2026-11-23
- [gap] 同类移动端 / 远程 agent 控制台产品是否把「项目切换」做成连接级（换连接）而非帧级（换字段），缺少可比样本——**未取证**。—— 来源：gap，发布：未知，访问：2026-11-23

## 决策驱动因素

- **「认证」与「项目编址」当前分居两通道**（外部 WS 有认证无编址、回环 HTTP 有编址无认证）⇒ 迫使在既有认证的 WS 上**加字段**，而不是把 HTTP 项目链认证化对外；协议形状因此是「单通道 + 请求级可选字段」，不是「新端口 / 新服务」。
- **HTTP 回环面语义必须零变更** ⇒ 帧字段必须**可选且缺省保守**（缺省 = 启动工作区），否则既破坏 `extra="forbid"` 的向后兼容契约，又让本机消费者承担回归风险。
- **一次提交、不暴露 `session_id`** ⇒ 协议面保持最小，客户端状态（run→project 映射、cursor）外置到 APK 本地，事件信封因此不需要加 `project_id`。
- **审批 fail-safe 拒绝**（不新增远程审批通道）⇒ 远程面权限集合被钉死为「四件事」，任何新增能力都要重新过安全裁决；这也是「配置读写 / 项目注册 / 会话浏览不开放」的同一条约束来源。
- **单机 Windows 上真并行 2~5 个项目、名额按项目计** ⇒ 选择请求级编址而非「每项目一条连接」：否则单客户端会按连接数吃名额、事件归属与 cursor 续流要按连接分别维护，复杂度直接翻倍。
- **TLS pin 是唯一客户端信任锚** ⇒ 否决 per-project 端口 / 多实例编队（方案 C）：端口与证书物料随项目数倍增，客户端 pin 管理与轮换成本不可接受。

## 证据缺口

- **同类产品目标选择层级的直接证据全缺**（VS Code Tunnels / Remote-SSH 多文件夹、JetBrains Gateway 多 backend、MCP 客户端选 server 三处均未取证）—— 可补齐的查询：`VS Code Remote Tunnels multiple folders workspace routing`、`JetBrains Gateway multiple backends routing`、`MCP client multiple servers one connection`
- **单连接请求级路由的故障模式无公开样本**（并发名额吃满 / 事件归属错判 / cursor 续流）—— 可补齐的查询：`websocket multiplex request routing pitfalls event stream attribution resume cursor`；或退化为本仓内部推演 + `tests/` 现有契约测试反查
- **本仓 WS 提交帧逐字形状未在本轮复核完整**（帧类清单、是否已有 `cancel` 语义、`WsCommandFrame` 的 action 枚举）—— 可补齐：读 `src/heagent/network/ws_protocol.py` 与 `ws_server.py` 的提交分支
- **external 档「非 docker 沙箱」的现有判定键未核**（`SANDBOX_BACKEND` 配置值 vs 启动期实际生效后端及降级 WARNING 的既有位置）—— 可补齐：读 `src/heagent/cli/http_config.py` 与 `docs/sandbox.md` 的降级判据段
- **列项目 `available` 的既有 HTTP 语义未核**（远程投影要沿用还是另立口径）—— 可补齐：读 `http_console_protocol.py` 的 `ProjectEntryResponse` 与 `list_projects` 实现

## 宿主验收核对

| 核对项 | 结果 | 证据 |
|---|---|---|
| 最终回复含 `## 需求总结` | 通过 | 本报告与 `brief.md` 逐字一致 |
| 每条论断带来源 / 发布日期 / 访问日期 | 通过 | 市场综述 9 条，本地证据 3 条 + gap 6 条 |
| 缺失证据报为 gap | 通过 | 证据缺口 5 条，均给可补齐查询 |
| 原始需求段未被改写 | 通过 | `brief.md` 冻结段与 `new-goal.py` 渲染一致 |
| 只读边界（未建票树、未改实现） | 通过 | `tickets/tickets.toml` 仍为空表；`git status` 只有 goal 目录新增 |
| `http_console_protocol.py:389/455` 引用真实 | 通过 | 宿主实测 `grep -n project_id` 命中两行 |
| `ws_protocol.py` 帧 `extra="forbid"` 真实 | 通过 | 宿主实测 6 处 `model_config = ConfigDict(extra="forbid")` |
