---
stepsCompleted: []
status: draft
inputDocuments:
  - docs/frame.md
  - _bmad-output/epics/epic-56-WS对外入口周期/brief.md
---

# HeAgent - Epic Breakdown（Epic 56：WS 对外入口）

将 HTTP 与 WS **完全分离**：HTTP server 纯 HTTP+SSE（回环 only，移除全部 WS 路由与 `ws_*` 配置）；
新 WS server 独立 ASGI app + `WsServerConfig`（默认 `127.0.0.1:9001`，零 HTTP 路由），两条既有 WS
端点（`/api/runs/{run_id}/ws`、`/api/cli/ws`）迁入，路径不变、端口 8766 → 9001（**唯一 breaking
change**）。对外模式（非回环绑定）= 认证强制（静态 token fail-closed）+ TLS 可选；本地模式保持
Epic 54/55 语义。经 WS **提交 run** 翻 Epic 54 D2 案；配置/项目/会话/对话框只走本机 HTTP。

**立场口径**：WS 与 HTTP/SSE 同样是**入口面，不是安全边界**；本地模式无认证 / 无 TLS 的既有声明
逐字适用，OS 级沙箱兜底立场不变（`AGENTS.md` 安全声明）。对外能提交 run ⇒ **Epic 53 沙箱档从
建议升级为强烈建议**（文档义务落在 56-4）。

## Story 列表

| Story | 名称 | 依赖 | 状态 | 交付物 | 验收要点 |
|---|---|---|---|---|---|
| 56-1 | WS server 拆分与端点迁移 | 无 | backlog | `WsServerConfig`（自 `HttpServerConfig` 剥离 `ws_max_connections` 等旋钮 + Settings / CLI / `.env.example` 三处同步）；新 WS server 独立 ASGI app（默认 `127.0.0.1:9001`）+ 有界生命周期（start/serve_forever/close 对齐 `HttpServer` 口径）；HTTP app 拆除 WS 路由、`cli_hub` 缝与 `ws_max_connections`；两条 WS 端点迁入（逻辑复用 `ws_server.py` 不重写）；uvicorn WS 参数（`ws_max_size` / ping）随迁；架构契约测试同步 | 分离判据可执行：8766 上 WS 升级 404，SSE/REST/静态页零改动（既有测试全绿即证）；9001 上两条端点本机语义保持（订阅/续传/cancel/ping + CLI 旁路跨轮流）；9001 无任何 HTTP API 面；限额检查与登记同一步；缺 `websockets` 时 WS server 启动给安装诊断且不拖死 HTTP |
| 56-2 | 对外模式：认证与 TLS | 56-1 | backlog | 绑定地址切模式（D5）：回环 = 本地模式（Origin 防线、无认证）；非回环 = 对外模式（认证强制、Origin 不适用）；token 真源用户级 `setting.md`（配置面声明 + fail-closed 启动判定）；Bearer 握手校验（未 accept 前 close(1008)）+ 认证失败限速；TLS 可选（cert/key 配置，配齐 wss；不配明文 + 启动告警）；uvicorn ssl 装配 | 非回环 + 无 token ⇒ 拒绝启动（变异体：token 空串/全空白同判）；无效/缺失 token 握手 1008；回环绑定行为与 Epic 54/55 逐字保持；正确 token 正常订阅与提交；明文启动告警日志；TLS 模式 wss 握手 |
| 56-3 | 经 WS 提交 run | 56-1 | backlog | 帧协议扩面：`run` 提交命令帧（带 prompt）+ ack（`run_id` + 初始 status），校验复用 `RunRequest` 语义与 `HttpErrorCode`；提交语义等价 `POST /api/runs`：名额满 `run_conflict` 不排队、`shutting_down` 拒绝；期一交互形状：提交连接**不转**事件流，回 ack 后由客户端经既有 `/api/runs/{run_id}/ws` 订阅（保持单 run 端点形状，周期会话可复核）；D2 边界判据 | 提交 → ack(run_id) → 订阅 → 事件 seq 单调 → `cancel` 等价 DELETE；同项目第二个提交收 `run_conflict`（单用户共享名额，D6）；空 prompt 回 `empty_prompt`；对外模式触达不了配置/项目/会话/对话框（D2 边界的可执行判据） |
| 56-4 | 文档、契约与质量门 | 56-2, 56-3 | backlog | `docs/frame.md` 4.17/4.18 重写（双 server 拓扑、配置表、错误码表、依赖面、已知缺口口径）；`deploy/README` 端口迁移与对外模式部署说明；`.env.example`（`WS_HOST`/`WS_PORT`/token/TLS）；`AGENTS.md` 安全声明同步（本地模式无认证口径 + 对外认证口径 + **Epic 53 沙箱档强烈建议**）；架构契约同步；全量质量门亲跑登记 | `frame.md`/`AGENTS.md` 无「WS 更安全」扩大宣称，对外模式认证口径写明；breaking change（9001）在部署文档可见；架构契约同步后全绿；`pytest` + `ruff check` + `ruff format --check` + `mypy` + `bandit -ll` 全绿 |

> story 正文（`stories/*.md`）由周期会话按 bmad-build 流程生成；本表交付物与验收要点即正文范围边界。

## 实施约束

1. 交付顺序 `56-1 → (56-2 ∥ 56-3) → 56-4`；56-2/56-3 可并行，均只依赖 56-1。
2. **D1–D7 冻结在 `brief.md`**，任一变更须经用户裁定并回写 brief；实现期发现与冻结值冲突时**先报告再改**，不静默偏离。
3. 传输层职责边界不变：`network/` 不导入运行栈与配置；跨模块数据一律 Pydantic 模型，**禁原始 dict**。
4. 端点与事件分发**不重写**：`ws_server.py` 端点逻辑复用；`_RunRecord` / `CliEventHub` 状态源不动。
5. **错误信封单出口**：`error` 帧内容由既有 `error_envelope` + `sanitize_message` 生成；`HttpErrorCode` 封闭不新增。
6. **限额原子性**：连接/订阅的「检查 + 登记」在同一个无 `await` 的同步方法内完成（A9③ 口径）。
7. **断线语义**：连接关闭只注销订阅者与登记，**绝不**取消运行；取消只来自显式 `cancel` 命令或 `DELETE`。
8. 新增/迁移 Settings 字段按三处同步口径：`.env.example` + `catalog.classify` 归组 + `docs/frame.md` 配置表。
9. **认证 fail-closed 红线**：非回环绑定 + 无 token ⇒ 拒绝启动，绝不降级为「无认证对外」；token 真源用户级 `setting.md`，**禁**项目 `.env` 与代码副本。
10. HTTP/SSE 零改动；分离判据（8766 无 WS、9001 无 HTTP）必须是可执行测试，不是文档句。
11. 每个 story 的验证命令是规划口径，执行后登记**实测**结果；不伪造未运行的命令。

## 决策 → story 映射

| 决策 | 落点 |
|---|---|
| D1 完全分离、D7 CLI 旁路随迁 | 56-1（拆分 + 迁移） |
| D3 认证、D4 TLS、D5 监听模式 | 56-2 |
| D2 提交 run、D6 单用户共享 | 56-3 |
| 全部判据收口与文档义务 | 56-4 |
