# Story 54-4 · 文档、契约与质量门

状态：**planned**

## 范围

按 `epics.md` Story 列表行交付；收口 54-1/54-2/54-3 的文档面与质量门。**不改行为**——若本条发现行为问题，
回退到对应 story 修，不在文档里「写圆」。

## 交付物

### 1. `docs/frame.md`

- **4.17 内新增小节「WebSocket 入口（Epic 54）」**（4.17 是 HTTP 入口权威段，WS 与它同族）：
  - 端点 `GET /api/runs/{run_id}/ws`（单 run 订阅，D3）；与 SSE **并存**、SSE 契约零改动（D1）；
  - 帧契约：`event` / `ack` / `error` 三类（`ws_protocol.py`），事件负载**复用** `RunEventPayload`；
  - 命令集 `{cancel, ping}`（D2）+ `cancel` 与 `DELETE` 语义等价；
  - 续传：`?last_event_id=N` + ring buffer + 越窗 `resync_required` 错误帧（D5）；
  - 拒绝/错误分布：Origin 违规 = 未 accept 关闭（客户端 403、无 body）；其余 = `error` 帧 + 关闭码（D8）；
  - 限额 `HTTP_WS_MAX_CONNECTIONS`（per-run，独立于 SSE 订阅池，D6）；心跳 = 协议级 ping 15s（D7）；
    入站 4 KiB / 64 KiB（D9）；
  - **安全立场**：WS 同 HTTP —— 无认证、无 TLS、回环不等于可信、非安全边界；CSWSH 防线由 WS 层自行执行，
    既有三个 ASGI 中间件**不覆盖**非 `http` scope（写明原因，避免下次有人以为中间件管了）。
- 4.17 的**协议模型**行补 `ws_protocol.py`；**路由**行补 WS 端点；**依赖面**补 `websockets`（`http` extra）。
- 配置表（`:866` 一带）：新增 `http_ws_max_connections` 行（默认 16、字段计数按实测刷新）。
- 模块树（`:1440` 一带）：`network/` 清单补 `ws_protocol.py` / `ws_server.py`。
- 已知缺口表：新增 `/ 修订` 一行「WS 入口非安全边界 + 中间件不覆盖 WS 升级（WS 层自带 Origin 校验）」。
- **不**把 WS 写成「更安全的入口」；不得出现「回环即可信」类表述。

### 2. `AGENTS.md`

- 架构骨架 DAG 与「核心模块」的 `network/` 行：`入口传输层（HTTP + SSE + WebSocket；…）`。
- 硬约束段：`network/` 依赖方向约束**不变**（不导入运行栈与配置）——补一句 WS 端点同样适用。
- 安全声明段：WS 与 HTTP 同档（无认证 / 无 TLS / 非边界，OS 沙箱兜底立场不变）；**不扩大宣称**。

### 3. 契约测试

- `tests/test_architecture_contracts.py`：**预计零改动**——`FORBIDDEN_RUNTIME_IMPORTS["network"]` 按包扫描，
  新模块自动纳入；`:572` 的「starlette / uvicorn 只能延迟导入」也自动覆盖 `ws_server.py`。
  实跑后若确有缺口则同步补，并在本 story 记录「为何需要改」。
- 判据：`pytest tests/test_architecture_contracts.py -q` 全绿；另加一条**正面**判据：`ws_server.py` 的运行期
  import 集合不含 `starlette` / `uvicorn` / `websockets`（防止有人图省事把客户端库拖进服务端模块）。

### 4. 端到端验收（真回环）

- `tests/network/test_http_ws_e2e.py` 内的真 listener 用例（54-3 已建）作为**验收标准 1/5/6/7** 的证据；
  另写一次性探针 `.heagent/tmp/epic54/loopback_probe_ws.py <port>`（只用 `http.client` + `websockets` 客户端），
  实跑后把输出（事件序号、错误码、关闭码）贴进本 story 的验收证据。
- 关停面：真 listener 上 `server.close()` 期间观察 WS `close(1001)` 与 run 终态，登记实测耗时。

### 5. 质量门

- 亲跑并登记实测数字：`python scripts/quality_gate.py`（六门：goal 冒烟 / 回归+覆盖率 87% / ruff lint /
  ruff format / mypy / bandit `-ll`）。
- 覆盖率口径：新增 `network/ws_*.py` 不得把总覆盖率拖到 87% 以下；若临界，补判据而非改 omit。

## 验收标准

1. `docs/frame.md` 的 4.17 小节、配置表、模块树、已知缺口表四处齐备；文档里的**每条数字**（字段计数、默认值、
   超时、帧上界）与代码实测一致（复核方式：从 `Settings.model_fields` / `ws_protocol` 常量现场取值比对）。
2. `AGENTS.md` 三处同步，且安全声明**逐行比对**没被扩大（不得新增「WS 比 SSE 安全」这类断言）。
3. `tests/test_architecture_contracts.py` 全绿；`ws_server.py` 无 `starlette` / `uvicorn` / `websockets` 运行期导入。
4. 真回环证据四态齐全：事件流（含 seq）、续传补齐、`cancel` 生效、跨源 Origin 拒绝（403）。
5. `python scripts/quality_gate.py` 六门全绿（记录每条门的实测输出摘要）；本地不带 cov 的 `pytest` 亦全绿。
6. 台账/状态收口：`_bmad-output/epics/epic-54-WebSocket入口周期/epics.md` 的 Story 状态列与 `consolidated-overview.md`
   的 epic 状态行同步（若该文件登记了本 epic）。

## 任务

- [ ] frame.md 四处 + 小节正文
- [ ] AGENTS.md 三处
- [ ] 契约判据实跑（必要时补）
- [ ] 真回环探针实跑并贴证据
- [ ] `python scripts/quality_gate.py` 实跑并登记
- [ ] epics.md 状态列 / 总览同步

## 验证命令（规划，执行时亲跑并登记实测）

```bash
pytest tests/test_architecture_contracts.py tests/network -q
python scripts/quality_gate.py
pytest -q          # 不带 cov 的全量基线
```

## 风险与口径

- 文档里「WS 是新增能力」不能写成「更安全的通道」：它同样无认证、无 TLS，Origin 校验是**同源防线**、
  不是认证（与 `_OriginGuardMiddleware` docstring 同口径）。
- 中间件不覆盖非 `http` scope 这件事要写进文档：否则下一个人会以为「加了中间件就自动有 Origin 防护」。
- 若 54-3 的实现让 `network/` 依赖面发生变化（例如误 import 配置），本 story 只记录并回退，不放宽契约。
