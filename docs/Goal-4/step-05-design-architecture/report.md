# Step 05 · design-architecture 报告

- 目标：`Goal-4`
- 执行角色：`bmad-architecture`（headless 子会话）
- 产物：`architecture-ws-remote-project-channel/architecture-ws-remote-project-channel.md`（8 章 / 8 条 AD / 10 条不变量）
- 采纳：三个 epic 文件的 `sources:` 已加入 spine

## 八条架构决策（摘要）

| AD | 决策 | 落点 |
|---|---|---|
| AD-1 | 新增 `ProjectChannelService` Protocol 注入项目能力，`network/` 保持哑传输 | `network/ws_server.py` + `cli/ws_project_adapter.py`（新文件）+ `cli/http.py` 两处装配 |
| AD-2 | 帧转译单源：适配器包同一个 `HttpProjectConsole`，WS 与 HTTP 共用同一次调用；缺省路径完全不走适配器 | `cli/http_console.py:642` 的 `start_project_run` |
| AD-3 | 帧面最小扩张：`WsCommand` +2（`projects` / `cancel_run`）、`WsCommandFrame` +2 可选字段、新增 3 字段 `ProjectChannelEntry` + `WsProjectsFrame`；`WsAckFrame` / `WsEventFrame` 零改动 | `network/ws_protocol.py` |
| AD-4 | `parse_command_frame` 的字段白名单从二元 if/else 升级为 `_FRAME_FIELDS` 单一映射表 | `network/ws_protocol.py:226` |
| AD-5 | R7 的可判定形态 = at-least-once + 客户端按事件 id 去重 + `resync_required` 兜底（**验收而非新建**） | `http_protocol.replay_then_follow`（既有）+ 新判据 `tests/network/test_ws_resume.py` |
| AD-6 | 名额分层：全局沿用 run 服务、项目内沿用 console，不新增信号量、不动参数 | `_submit_run` 的 `HttpRunConflictError` 分支 |
| AD-7 | 错误码三分 + `ProjectRegistry.health()` 只读探针；读径 fail-soft、写径与提交径 fail-loud | `pub/projects.py`、`network/http_protocol.py::HttpErrorCode` |
| AD-8 | 远程暴露面不扩张 + `external` 档非 docker 沙箱一条启动 WARNING + 契约/文档收口 | `cli/http_config.py`、`cli/http.py::_ws_access_note` |

## 子会话的三处实测偏差（已采纳，宿主抽验通过）

1. **engine 里没有并发名额** —— `src/heagent/engine/` 只有 `checkpoint.py` 的 `tool_in_flight`；名额实际在 run 服务（全局）与 console（项目内）。原 Step 02/03 假设「engine 查名额」不成立。
2. **`RunWebSocketService` 不扩展** —— 新增并列 `ProjectChannelService`；偏离 R10 的字面表述但满足其意图（声明与实现同批改），理由已写进 AD-1。
3. **`start_project_run` 返回带 `session_id`** —— WS 侧必须收窄为 `SubmittedRun(run_id, status)`，否则 R4 被实现层无意破坏。

## 宿主抽验（2026-11-23 实测）

| 核对项 | 结果 | 证据 |
|---|---|---|
| `HttpProjectConsole` 在入口层、可被 WS 复用 | 通过 | `cli/http_console.py:465 class HttpProjectConsole`、`:642 async def start_project_run(project_id, request: ProjectRunRequest) -> ProjectRunResponse` |
| `start_project_run` 返回含 `session_id` | 通过 | `cli/http_console.py:663 return ProjectRunResponse(run_id=…, session_id=session_id, status=…)` |
| `project_has_inflight_run` 存在（项目内名额探针） | 通过 | `cli/http_console.py:544` |
| engine 无名额实现 | 通过 | `grep -rn "Semaphore\|MAX_CONCURRENT\|inflight_limit" src/heagent/engine/` 零命中；仅 `ws_server.py:263 class _SubmissionSlots`（连接席位） |
| 命令帧字段白名单是二元分支 | 通过 | `ws_protocol.py:226 allowed_keys = {"command","prompt"} if RUN else {"command"}` |
| `ProjectEntryResponse` 带 `path`（投影必须收窄） | 通过 | `http_console_protocol.py:69` 起，字段含 `path` / `last_opened_at` / `is_default` |
| spine 被 epic 采用 | 通过 | 三个 epic 的 `sources:` 均已加 spine 路径 |
| 文档链接守卫 | 待复跑 | 见 progress 决策日志 |
