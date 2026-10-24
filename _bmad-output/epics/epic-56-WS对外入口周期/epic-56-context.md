# Epic 56 Context: WS 对外入口周期

<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->

## Goal

将 HTTP 与 WS **完全分离**为同进程两个独立 server：HTTP server 纯 HTTP+SSE（回环 only，控制台页 + REST + SSE，不再挂任何 WS 路由）；新 WS server 独立 ASGI app + 独立配置 + 独立监听器（默认 `127.0.0.1:9001`），零 HTTP 路由，是所有 WS 能力（run 订阅、CLI 旁路、经 WS 提交 run）的唯一宿主。WS 端口 8766 → 9001 是唯一 breaking change。经 WS 提交 run 翻 Epic 54 D2 案，使外部客户端（IDE 插件、桌面端、远程协作）获得生产价值；配置/项目/会话/对话框只走本机 HTTP。（注：本周期无 PRD/架构等标准规划工件，规划权威 = 周期目录内 brief.md + epics.md。）

## Stories

- Story 56.1: WS server 拆分与端点迁移
- Story 56.2: 对外模式：认证与 TLS
- Story 56.3: 经 WS 提交 run
- Story 56.4: 文档、契约与质量门

## Requirements & Constraints

- 分离判据必须**可执行测试**：8766 上 WS 升级不可达（非 101）；9001 上无任何 HTTP API 面（控制台页/静态资源/REST/健康检查全 404）；HTTP/SSE 与本机 HTTP API 契约零改动。
- 端点与事件分发**不重写**：`ws_server.py` 端点逻辑复用；`_RunRecord` / `CliEventHub` 状态源不动。
- 错误信封单出口（`error_envelope` + `sanitize_message`），`HttpErrorCode` 封闭不新增。
- 限额原子性：「检查 + 登记」同一无 `await` 同步方法（A9③ 口径）。
- 断线语义：连接关闭只注销订阅者与登记，绝不取消运行；取消只来自显式 `cancel` 命令或 `DELETE`。
- 传输层职责边界不变：`network/` 不导入运行栈与配置；跨模块数据一律 Pydantic 模型。
- 新增/迁移 Settings 字段三处同步：`.env.example` + `catalog.classify` 归组 + `docs/frame.md` 配置表。
- `pytest` / ruff / mypy / bandit / 架构契约测试全绿。

## Technical Decisions

- **D1 拓扑**：HTTP 与 WS 完全分离；既有两条 WS 端点（`/api/runs/{run_id}/ws`、`/api/cli/ws`）路径不变、换端口。
- **D2 能力边界**：WS = 订阅 + `cancel`/`ping` + 提交 run（等价 `POST /api/runs`）；配置/项目/会话/对话框 WS 不可达。
- **D3 认证**：静态 token（用户级 setting.md 真源），Bearer 握手校验，失败未 accept 前 close(1008)。
- **D4 TLS**：原生 TLS 可选（cert/key 配齐即 wss）；不配 = 明文 + 启动告警；不引入反向代理。
- **D5 监听模式**：单监听器按绑定地址切模式——回环 = 本地模式（Origin 防线、无认证）；非回环 = 对外模式（token 缺失拒绝启动 fail-closed、认证强制、Origin 不适用）。
- **D6 并发语义**：期一单用户不变，所有 WS 连接共享同一运行状态机与名额。
- **D7 CLI 旁路归属**：`/api/cli/ws` 随迁移进 WS server。
- 立场口径：WS 与 HTTP/SSE 同为入口面**非安全边界**，OS 沙箱兜底立场不变；对外能提交 run ⇒ Epic 53 沙箱档从建议升级为强烈建议（文档义务在 56-4）。
- 任一冻结决策（D1–D7）变更须经用户裁定并回写 brief.md；实现期发现冲突先报告再改。

## Cross-Story Dependencies

- 交付顺序 `56-1 → (56-2 ∥ 56-3) → 56-4`；56-2/56-3 只依赖 56-1，可并行；56-4 依赖 56-2 与 56-3。
- 56-1 同时承担 Epic 54 retro 遗留的测试面重建（替身纯逻辑面 `test_ws_server.py` / WS 端到端）。
- 与 Epic 54 D1（WS 与 SSE 同 app 同端口）冲突已显性取代其拓扑部分；与 Epic 49 AD-6（无反向代理）不冲突。
