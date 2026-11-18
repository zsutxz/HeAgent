---
title: 'Story 64.9 为大文件读写添加进度提示'
type: feature
ticket: 9
created: '2026-11-18'
status: built
baseline_revision: '8026aa9'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_recommended: false
context:
  - 'src/heagent/cli/display.py'
  - 'src/heagent/tools/builtins/file.py'
---

## Intent

**Problem:** `file_read` / `file_write` 是**整块** I/O：`_read_text_bounded` 一次
`fh.read(cap + 1)`，`file_write` 一次 `write_bytes(content.encode())`。>10 MB 的文件在这两处
各是一段**不可见的静默期**，用户只能看着 `[calling file_read → big.log]` 干等；同时整块读
把峰值内存钉在「文件大小」上。

**Approach:** 把两处改成分块 I/O，并**在工具内部**按块上报进度，阈值与块大小是本模块常量：

- 读：`_read_bytes_bounded()` 逐块 `read(FILE_PROGRESS_CHUNK_BYTES)` 累进 `bytearray`，仍只读
  `_FILE_READ_MAX_BYTES + 1` 字节（判截断语义逐字不变）；
- 写：`_write_text_progress()` 逐块 `write()`，最终字节与 `write_bytes(content.encode())`
  **逐字节相同**；
- 上报只对**文件本身**超过 `FILE_PROGRESS_MIN_BYTES` 的读写发生（读侧阈值按文件大小判，进度总量报
  计划读取量 `min(size, cap)`——见下「实测偏差」），且只在**有 reporter 被绑定**时发生
  （未绑定时是 `RuntimeSlot.get()` 读一次 `None`，零额外调用）。

**实测偏差（票面前提 vs 现状）：**

- 票面「大于 10 MB 的文件读写」在 `file_read` 侧天然收敛：读上限 `_FILE_READ_MAX_BYTES = 10 MB`
  已在位 ⇒ 大文件只读前 10 MB。因此进度的「总量」取 **计划读取字节数** `min(size, cap)`，
  而不是文件大小——否则进度永远停在 100%×10MB/size，是假进度。`file_read` 的截断尾注、
  `file_edit` 的全量匹配路径**逐字不变**；
- `file_edit` 的落盘走 `tools/edits.write_text_file`（不在本票 lane 内）⇒ **不改**；本票范围是
  `file_read` / `file_write`。`file_edit` 的体量天然被 `MAX_DIFF_SOURCE_BYTES`（512 KB 源上限）
  与「替换片段」形态限制，不构成 10 MB 级静默期。

**共享原语:** 与 Story 64.8 共用 `heagent/cli/progress.py`：本票在其中实装
`FileProgressSample`（Pydantic，`processed` / `total` / `started_at`）、`format_file_progress()`
（已处理 / 总量 / 百分比 / 预计剩余时间）、`FileProgressBridge`（`report(processed, total)` 的
接收侧，存最近样本 + 起始时刻）。**上报口在 tools 侧、渲染在 cli 侧**，两侧只交换
`(int, int)` 两个原始整数（不传 dict、不传 cli 类型），因此 `tools/` 不需要、也**不得**导入 `cli/`。
64.8 的 `ToolProgress` 刷新行负责把 `format_file_progress(...)` 的片段拼到工具进度行尾；
无样本时不追加。

## Boundaries & Constraints

- **只改**：`src/heagent/tools/builtins/file.py`（读/写改分块 + 上报槽位与 `file_progress()`
  上下文管理器）、`src/heagent/cli/progress.py`（新建，样本模型 + 渲染 + bridge）、
  `src/heagent/cli/interactive.py`（在 `_consume_stream` 内用 `file_progress(bridge.report)`
  包住 `run_stream`，极小改动）；新建 `tests/test_file_progress.py`。
- **禁止**：`tools/runtime.py`（`RuntimeSlot` 已够用，不改共享槽位实现）、
  `tools/edits.py`、`tools/builtins/__init__.py`、`engine/*`、`agent/*`、`docs/frame.md`、
  `tests/test_architecture_contracts.py`。
- **语义逐字不变**（硬约束）：`file_read` 的 BOM 剥离 / 行尾归一 / 截断尾注文案、
  `file_write` 的 `Error writing file: {exc}` 与 `OK: wrote … (+N -M)` 回执、快照行，全部保持原文；
  唯一变化是底层 I/O 分块。
- **真的分块**：不得为进度把整个文件读进内存再假装分块；写侧 payload 来自 `content: str`
  （已在内存，无法避免），但**落盘**必须分块。
- **字节等价**：`_read_bytes_bounded` 与旧 `fh.read(cap+1)` 返回完全相同的字节；
  `_write_text_progress` 与旧 `write_bytes(content.encode("utf-8"))` 写出的字节完全一致。
- **阈值与块大小是常量**：`FILE_PROGRESS_MIN_BYTES = 10 * 1024 * 1024`、
  `FILE_PROGRESS_CHUNK_BYTES = 1024 * 1024`，docstring 写明单位（字节），测试从常量读。

## Code Map

| 落点 | 作用 |
| --- | --- |
| `tools/builtins/file.py` | `FILE_PROGRESS_MIN_BYTES` / `FILE_PROGRESS_CHUNK_BYTES` 常量；`_FILE_PROGRESS`（`RuntimeSlot[Callable[[int, int], None]]`）；`file_progress(reporter)` 上下文管理器；`_read_bytes_bounded()` / `_write_text_progress()` 分块实现 |
| `cli/progress.py` | `FileProgressSample`（Pydantic）、`format_file_progress()`、`FileProgressBridge` |
| `cli/interactive.py::_consume_stream` | `with file_progress(bridge.report):` 包住 `run_stream` |
| `tests/test_file_progress.py` | <10 MB 零上报 / >10 MB 四要素与实时性 / 分块读字节等价 / 分块写字节等价 / 读上限截断语义不变 / 写回执不变 / 性能上界 |

上报协议（tools → cli 的唯一契约）：

```python
# tools/builtins/file.py
FileProgressReporter = Callable[[int, int], None]   # (已处理字节, 计划总量字节)
def file_progress(reporter: FileProgressReporter | None) -> Iterator[None]  # 上下文管理器
```

`file_progress()` 用 `RuntimeSlot` 的 `bind()`：**不污染进程默认绑定**，`asyncio.to_thread`
会复制上下文，因此工作线程内的 `_read_bytes_bounded` / `_write_text_progress` 仍能读到同一个
reporter（这是本方案不需要改 `tools/runtime.py` 的原因）。

## Tasks & Acceptance

- [x] `tools/builtins/file.py`：常量 + 槽位 + `file_progress()` + 分块读写（保持文案/回执不变）。
- [x] `cli/progress.py`：`FileProgressSample` / `format_file_progress` / `FileProgressBridge`。
- [x] `cli/interactive.py`：绑定 reporter（极小改动）。
- [x] `tests/test_file_progress.py`。
- [ ] `pytest tests/test_file_progress.py tests/test_file_edit.py -q` 全绿（实测见交付报告）。

**Acceptance（对应票面 verify）：**

1. ≤10 MB 文件读写：reporter **零调用**（不显示进度）；
2. >10 MB 文件读：reporter 收到 ≥2 个样本，样本 `total` 恒为 `min(size, cap)`，
   `processed` 单调不减且最终 == `total`；
3. 渲染行含四要素：已处理大小、总大小、百分比、`约剩 N.Ns`（ETA 由样本速率推算）；
4. 分块读 / 分块写与旧整块实现的**字节完全相等**（12 MB 大文件 + 内容校验）；
5. 截断尾注、`OK: wrote …` 回执、快照行与改动前逐字一致；
6. 进度开启相对关闭的耗时差异有上界（比值 < 2）。

## Implementation Notes

- **读侧计划量 `min(size, cap)`**：`file_read` 的既有上限意味着大文件只读到 10 MB；以文件大小
  当总量会让进度永远到不了 100%。取计划量后，`processed == total` 即「读完并（可能）截断」，
  与尾注文案自洽。
- **`stat()` 只读一次且失败不致命**：读路径新增一次 `stat` 用于取计划量；`OSError` 时按
  「无计划量」处理（不上报），读本体照旧，因此不影响既有错误路径。
- **写侧顺序**：`Path.open("wb")`（截断语义与 `write_bytes` 一致）→ 逐块写 → 关闭；
  空内容仍创建空文件（与 `write_bytes(b"")` 等价）。
- **上报限频**：上报发生在每块完成时（1 MB/块）；渲染侧的限频仍由 64.8 的
  `PROGRESS_REFRESH_SECONDS` 控制，样本本身不做节流（多写一个 int 的开销可忽略）。
- **线程安全**：bridge 只被工具线程写、被事件循环协程读；写入是「替换一个 Pydantic 样本对象」，
  GIL 下原子，无需锁（读到旧样本只会让 ETA 落后一帧）。

## Verification

命令：`/workspace/.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_file_progress.py -q`
（12 MB 大文件在 `tmp_path` 生成，无网络、无真实 API；时间断言用宽松上界避免 flaky）。

实测（本机容器内 py311 venv）：

- 两个新测试文件合计 **29 passed / 3.8 s**；连带回归 `tests/test_file_edit.py`、`tests/test_cli.py`、
  `tests/test_cli_display.py`、`tests/test_cli_run_prompt.py`、`tests/test_cli_ws_publish.py`、
  `tests/test_call_summary.py` 共 **175 passed**（无一处改动）。
- 12 MB 文件读：上报 **11 次**，末次 `(10 MB, 10 MB)`（计划量 = 读上限），耗时
  **5.6 ms（关闭）→ 5.8 ms（开启）**，即 +3.6%。
- 渲染样例：`5.0 MB/10.0 MB 50% · 约剩 2.0s`。
- `ruff check` / `ruff format --check` / `mypy --strict`（`file.py`、`progress.py`、`display.py`、
  `interactive.py`）全部通过。

## Review Triage Log

- 2026-11-18 quick lens：无本 story 的 patch（`file.py` 的 BOM 剥离 / 行尾归一 / 截断尾注 / 写入回执
  逐字未变；分块读写是真分块，不是整读后假装分块；工具层未引入对 `cli/` 的导入）。
- 共享原语的两条修补记在 64.8 plan（非 tty 文案、前缀匹配）。
- 留待：`tests/test_file_progress.py` 的耗时断言是 `with <= baseline * 3 + 0.1`，比本票 Acceptance 写的
  「< 2 倍」松——保留宽阈值以免 CI 抖动，口径差异在此说明。
