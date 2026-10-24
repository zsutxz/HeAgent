# Story 54-1 · WS 帧契约与协议封套

状态：**planned**

## 范围

按 `epics.md` Story 列表行交付；冻结决策见 `../brief.md` D2 / D8 / D9。本 story 只交付**纯数据契约**
（无 IO、无端点），端点行为在 54-3。

## 交付物

- `src/heagent/network/ws_protocol.py`（新模块，`network/` 同层）：
  - `WsFrameType(StrEnum)`：`EVENT` / `ACK` / `ERROR`（封闭三值）；
  - `WsCommand(StrEnum)`：`CANCEL` / `PING`（D2 的封闭命令集，新增命令须改枚举）；
  - `WsEventFrame`：`{"type":"event","event":<RunEventPayload>}`——**嵌套**而非展平：`RunEventPayload`
    是 `extra="forbid"`，展平必须复制字段（复制即漂移），嵌套让 WS 事件负载与 SSE 事件负载**同一模型**；
  - `WsAckFrame`：`{"type":"ack","command":<WsCommand>,"run_id":str,"status":<RunStatus>}`；
  - `WsErrorFrame`：`{"type":"error","error":<HttpErrorEnvelope>}`——信封**复用** `error_envelope()`，
    `HttpErrorCode` 封闭枚举不扩（D8）；
  - `WsCommandFrame`：入站命令 `{"command":<WsCommand>}`（`extra="forbid"`）；
  - `parse_command_frame(text: str) -> WsCommandFrame`：纯函数。超长 → `WsFrameError(TOO_LARGE)`；
    非法 JSON / 结构不符 / 未知命令 → `WsFrameError(MALFORMED / UNKNOWN_COMMAND)`；
  - `WsFrameError`（`ValueError` 子类）+ `WsFrameErrorKind(StrEnum)`：`TOO_LARGE` / `MALFORMED` /
    `UNKNOWN_COMMAND`（封闭，调用方据此选错误码与关闭码，不靠异常文案分支）；
  - 常量：`WS_MAX_INBOUND_CHARS = 4096`（D9）；`WS_PING_INTERVAL_SECONDS = 15.0`（= `SSE_HEARTBEAT_SECONDS`，
    D7）；`WS_PING_TIMEOUT_SECONDS = 20.0`；`WS_MAX_FRAME_BYTES = 64 * 1024`（D9，供 54-2 传给 uvicorn）；
    关闭码 `WS_CLOSE_POLICY = 1008` / `WS_CLOSE_TOO_LARGE = 1009` / `WS_CLOSE_INTERNAL = 1011` /
    `WS_CLOSE_GOING_AWAY = 1001`（D8 分布的唯一来源）。
- `network/__init__.py`：不新增导出（协议模型按 `http_protocol` 惯例由使用者直接 import 子模块）。

## 验收标准（每条都要有判据）

1. 四个帧模型的 round-trip：`model_dump(mode="json")` → `model_validate` 等值；且 JSON 形状**逐键钉住**
   （`type` 判别键 + 嵌套 `event` / `error`），防止有人把事件帧展平。
2. `extra="forbid"` 生效：往 `WsEventFrame` 塞顶层 `text`（展平形态）、往 `RunEventPayload` 塞 `type`、
   往命令帧塞 `run_id` → 全部 `ValidationError`。
3. 未知 `type` / 未知 `command` → `ValidationError`（枚举封闭）；新增命令必须改枚举，不允许字符串透传。
4. `error` 帧只能由 `HttpErrorCode` 成员构造：判据遍历 `HttpErrorCode` 断言 `error_envelope(...)` 可包进
   `WsErrorFrame`；并断言 `ws_protocol` 内**零**自定义错误文案字面量（错误文案留在调用方，且调用方只能用
   `error_envelope`）。
5. `WS_PING_INTERVAL_SECONDS == SSE_HEARTBEAT_SECONDS`（D7 对齐判据，单一事实源：`http_protocol` 的常量）。
6. `parse_command_frame` 三类失败各一例（超长 / 非法 JSON / 未知命令），成功各一例（`cancel` / `ping`）；
   超长判定按**字符数**（`WS_MAX_INBOUND_CHARS`）且先于 JSON 解析（不让解析器吃 4 KiB 以上的输入）。
7. 依赖方向：`ws_protocol.py` 只 import 标准库 + `pydantic` + `heagent.network.http_protocol`
   （`tests/test_architecture_contracts.py` 既有 `network/` 断言不改即应通过）。
8. 变异体精确变红（脚本落 `.heagent/tmp/epic54/neg_54_1.py`）：
   ① 事件帧展平（判据 1/2 红）；② 命令枚举放开成 `str`（判据 3 红）；③ 超长判定改成字节数或去掉（判据 6 红）；
   ④ `WS_PING_INTERVAL_SECONDS` 改成 20.0（判据 5 红）；⑤ `WsErrorFrame` 自造 code 字段（判据 4 红）；
   ⑥ `parse_command_frame` 吞异常返回默认命令（判据 6 红）。

## 任务

- [ ] 写 `tests/network/test_ws_protocol.py`（判据 1–7，先红后绿）
- [ ] 实现 `ws_protocol.py`
- [ ] 写变异体脚本并实跑，记录「N/N 精确变红 + 字节还原后基线复绿」

## 验证命令（规划，执行时亲跑并登记实测）

```bash
pytest tests/network/test_ws_protocol.py -q
pytest tests/test_architecture_contracts.py -q
ruff check src/heagent/network/ws_protocol.py tests/network/test_ws_protocol.py
ruff format --check src/heagent/network/ws_protocol.py tests/network/test_ws_protocol.py
mypy src
```
