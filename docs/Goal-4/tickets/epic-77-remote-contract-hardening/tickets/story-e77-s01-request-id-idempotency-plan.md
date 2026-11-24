---
ticket: 1
ref: 77.1
code: E77-S01
epic: epic-77-remote-contract-hardening
risk: medium
hitl: false
covers: ["R1"]
status: done
---

# E77-S01 · 提交幂等键 request_id：同键重发只起一个 run，失败不缓存

## Intent

<frozen-after-approval>

客户端拿不到 ack 时会重发，而现在重发一定起第二个 run（可能还撞 `run_conflict`）。给 `run` 帧加
可选 `request_id`，让**成功提交**在 60s 窗口内可安全重放：同 `(project_id, request_id)` 的在途请求
合流到同一个 Future，已完成的直接回缓存结果 ⇒ 客户端看到同一个 `run_id`。

幂等只覆盖成功路径。失败（含 `HttpRunConflictError` 与其它异常）立即移出缓存，客户端重试可以
重来——这与既有「提交失败不做原子性保证」是两条并存的语义，不是替代。

落点选入口层适配器而不是 `network/`：幂等是服务级语义，`network/` 保持哑传输（只把 `request_id`
原样透传给端口）。这也避免传输层出现第二份「提交结果」状态。

</frozen-after-approval>

## Boundaries & Constraints

**Always**

- `ack` 帧四格冻结（`{type,command,run_id,status}`）：不加回显字段，客户端按单飞 + `run_id` 关联。
- 无 `request_id` 的帧逐字走旧路径（每次都是新提交），旧客户端零影响。
- `request_id` 不 strip、不做语义解释（客户端不透明 id），长度界 1–64 与 `run_id` 同档。
- 缓存键含 `project_id`：两个项目用同一个 `request_id` 互不干扰。
- 检查与登记之间不得有 `await`（并发握手/并发提交会一起穿过限额，A9③ 老坑）。

**Never**

- 不落盘、不跨进程：进程重启后窗口消失，docstring 明说（不假装持久）。
- 不改名额、并发参数、`_SubmissionSlots` 语义。
- 不给失败补原子性、不新增提交事务/回滚。
- 不新增 WS 命令或帧类型。

## Code Map

- `src/heagent/network/ws_protocol.py`
  - `_FRAME_FIELDS`（`:97`）`run` 加 `request_id`；`_OPTIONAL_FRAME_FIELDS`（`:108`）加同名。
  - `WsCommandFrame`（`:256`）加 `request_id: str | None = Field(default=None, min_length=1, max_length=64)`。
  - `ProjectChannelService.start_project_run`（`:398`）签名加 `request_id: str | None = None`；
    三条实现方义务里的「无幂等键」改写成三态语义。
- `src/heagent/network/ws_commands.py`
  - `_start_project_run`（`:159`）透传 `request_id`；`_submit_run`（`:212`）从帧上取值。
- `src/heagent/cli/ws_project_adapter.py`
  - `start_project_run`（`:83`）加 `_idempotency` 表；新增私有缓存类（TTL 60s / 上限 256 / 在途 Future）。
- 测试：`tests/network/test_ws_protocol.py:365` 字段镜像、`tests/network/test_ws_project_commands.py:349`
  的 docstring 判据、`tests/network/test_ws_project_submit.py` 的两个 fake 签名、`tests/test_ws_project_adapter.py`
  新增幂等四例。

## Tasks & Acceptance

- [x] 帧面：`_FRAME_FIELDS` / `_OPTIONAL_FRAME_FIELDS` / `WsCommandFrame` 三处同步；解析带
      `request_id` 的帧成功，`>64` 字符按 `malformed`。
- [x] 端口：`ProjectChannelService.start_project_run` 加可选参数并改写 docstring 三态语义。
- [x] 传输：`_start_project_run` / `_submit_run` 透传帧上的 `request_id`（不改 ack）。
- [x] 适配器：新增 `_Idempotency`（在途 Future 合流 + 成功结果 TTL 缓存 + 失败移除 + 上限淘汰）。
- [x] 测试：四例（并发同键 1 次调用 / 不同键 2 次 / 无键 2 次 / 失败后重试再调用）+ 透传断言。
- [x] 文档：`project_id` 旁的帧字段说明（`docs/framework.md` 提交 run 行）本轮只在票内记，正文由
      E77-S03 统一收口，避免同文件二次改动。

## Verification

| 命令 | 期望 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_ws_project_adapter.py tests/network/test_ws_project_commands.py tests/network/test_ws_protocol.py tests/network/test_ws_project_submit.py -q` | 全绿 |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network -q` | 零回归 |
| `.heagent/tmp/py311-venv-linux/bin/python -m ruff check src tests` / `ruff format --check` | 干净 |
| `.heagent/tmp/py311-venv-linux/bin/python -m mypy src/heagent/network/ws_protocol.py src/heagent/network/ws_commands.py src/heagent/cli/ws_project_adapter.py` | no issues |

## 实测结果（2026-11-24）

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network -q` | **737 passed**（含新增 6 例适配器幂等 + 2 例协议界 + 1 例透传） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_ws_project_adapter.py -q` | 34 passed（行预算判据 `<= 150` 仍绿：148 → 146） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_architecture_contracts.py -q` | 40 passed（cli 布局白名单已含 `ws_submission_cache`） |
| `ruff check` / `ruff format --check`（4 个源文件） | 干净 |
| `mypy`（4 个源文件） | no issues |

## Implementation Notes

- **新模块而不是塞进适配器**：`tests/test_ws_project_adapter.py::test_adapter_stays_inside_its_line_budget`
  把适配器钉在 150 行内（「只翻译」的结构判据）。幂等表一进来就 193 行 ⇒ 拆成
  `cli/ws_submission_cache.py`（71 行），适配器 146 行。代价 = 新增 cli 子模块须同步两处契约：
  `tests/test_architecture_contracts.py::test_cli_package_layout_is_pinned` 白名单（字母序，`ws_submission_cache`
  排在 `ws_project_adapter` 之后）与 `docs/framework.md`（§4.1 cli 子模块表 + 六、目录结构的 `cli/` 段）。
  **两条都已在同一 story 内同步**，不必留到 S03。
- **合流用 `asyncio.shield`**：直接 `await future` 时，合流者被取消会把共享 `Future` 一起取消，owner 的
  `set_result` 随后撞 `InvalidStateError`；shield 把取消隔离在等待方。
- **owner 被取消**单独分支：`drop(key)` + `future.cancel()`，合流者看到 `CancelledError` 而不是假结果。
- **失败先 `set_exception` 再 `exception()`**：没有合流者时也标记「已取回」，避免 `Future exception was
  never retrieved` 噪声；异常随后原样 `raise`，错误帧路径与既有口径逐字一致。
- `request_id` 与 `run_id` 同档界（1–64、不 strip）：两者都是客户端原样回传的 opaque id；ack 四格冻结
  是刻意选择（`tests/network/test_ws_event_contract.py:51` 的封闭集断言不动）。
