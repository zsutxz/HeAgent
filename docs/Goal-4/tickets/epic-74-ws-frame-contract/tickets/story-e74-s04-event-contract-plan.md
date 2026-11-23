---
ticket: 4
ref: 74.4
code: E74-S04
epic: epic-74-ws-frame-contract
status: built
baseline_revision: e0e9d411248f5144706da6687c9f14313f8aa838
risk: low
hitl: false
covers: ["R6"]
---

# E74-S04 · 事件面零漂移契约钉子

## Tasks & Acceptance

- [x] 新增 `tests/network/test_ws_event_contract.py`（7 例，**零 src 改动** —— 本 entry 就是「不改协议」的可执行承诺）：
  - [x] `WsEventFrame.model_fields` 恰为 `{type, event}`；
  - [x] `WsAckFrame.model_fields` 恰为 `{type, command, run_id, status}`，并显式断言 `session_id` 不在其中；
  - [x] 帧类型集合 `WsFrameType` 封闭为 `{hello, event, ack, error, notification}`（项目通道复用既有五档，不新增 `project` 类帧）；
  - [x] golden 事件信封 `model_dump_json()` 与固定字面**逐字相等**（顺序 + 默认值 + `ensure_ascii` 行为一起钉住）；
  - [x] 事件面**两层**都拒绝 `project_id`：帧层带该键、负载层（`RunEventPayload`）带该键都抛 `ValidationError`；
  - [x] WS 路由集与 `tests/fixtures/contract_baselines/transport_routes.json` 的 `ws_host.py` 段逐字一致（四条路径常量：提交 / 订阅 / 旁路 / 通知），并断言命名里不含 `project`；
  - [x] 命令集与路由的交叉核对：`{run, cancel, cancel_run, ping}`（命令集扩展不伴随端点扩展）。

验收（对应 entry 的 `verify`）：
- 字段集合三例（事件帧 / ack 帧 / 帧类型集）全绿。
- golden 信封逐字相等一例。
- 事件帧带 `project_id` ⇒ 帧校验失败一例（参数化覆盖负载层）。
- 路由集与基线一致一例。

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network/test_ws_event_contract.py -q` | **7 passed** |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network tests/test_architecture_contracts.py -q` | **692 passed, 1 warning** |
| `.heagent/tmp/py311-venv-linux/bin/ruff check src tests` | All checks passed |
| `.heagent/tmp/py311-venv-linux/bin/ruff format --check src tests` | 498 files already formatted |
| `.heagent/tmp/py311-venv-linux/bin/python -m mypy src` | Success: no issues found in 239 source files |

## Code Map

- `tests/network/test_ws_event_contract.py`（新）—— 6 个用例 + 1 组参数化（两层 `project_id` 拒绝）。
- 未改任何 `src/` 文件：本 entry 的价值是**判据**，不是实现。

## Design Notes

- **为什么要有 golden 字面**：字段集合相等只说明「名字没变」，顺序、默认值、`ensure_ascii` 行为都还能漂。客户端是按字节解信封的（APK 侧不重排字段），所以真正的兼容面是 `model_dump_json()` 的输出，一条字符串断言比十条字段断言更贴近失败现场。
- **`project_id` 要测两层**：`WsEventFrame(extra="forbid")` 挡帧层，`RunEventPayload` 自己的 `extra="forbid"` 挡负载层——只测帧层会漏掉「负载层被加上 project_id」这条路（两个模型是两处 `ConfigDict`，不是一处）。
- **路由用基线而不是硬编码**：`transport_routes.json` 是**已经存在**的契约快照（E76.6 才重生成），与它比对等于把「本 epic 不新增端点」挂到既有守卫上，避免本 entry 自造第二份路径清单。
- **不动 `WsCommandFrame`**：本 entry 只钉**出站**面（what the server sends）。入站帧在 74.1 / 74.3 已各自钉死，重复钉会让「改一处要改三处」。

## Plan Change Log

- 2026-11-23：宿主直接实现（本 entry 预期零 src 改动、单文件测试；实现子会话在本轮前一条 74.3 上已撞 25 次迭代上限，故本 entry 由宿主一次写完并实测）。`ruff format` 首轮把过长的正则行折行，`ruff check` / `format --check` / `pytest` 复跑全绿。
