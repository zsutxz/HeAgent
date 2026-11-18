---
title: 'Story 64.8 为工具执行添加进度条'
type: feature
ticket: 8
created: '2026-11-18'
status: done
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

**Problem:** `run_stream` 在工具执行期间只吐两条事件（`tool_call` / `tool_result`），中间是一段
**静默期**。慢工具（容器沙箱里的 `shell`、MCP 调用、10 MB 级文件读写）期间终端停在
`[calling shell → pytest]` 一行不动，用户无法区分「还在跑」与「卡死」。票面要求**超过 3 秒**的
工具执行展示实时进度提示，且不得拖慢工具执行。

**Approach:** 新增进度原语 `heagent/cli/progress.py::ToolProgress`——纯展示层、**惰性**计时：

- `on_event()` 是同步、零 I/O 的事件分类入口，只记 `tool_call` 的开表时刻与 `tool_result` 的停表；
- 只有**真的越过 3 秒**才起一个 `asyncio.Task`（首个 `await asyncio.sleep(3.0)` 返回后才首次刷新），
  因此 <3 秒的工具**一个额外字节都不写**，也不产生任何任务；
- 刷新循环每次 `await asyncio.sleep(0.5)`，用 `\r` 原地重写单行；停表时清掉该行并给最终耗时；
- 非 tty（管道 / 重定向）降级为**至多一行**收尾摘要；`ANNOUNCE_PROGRESS=false` 时整体静默
  （沿用既有「operator 静音横幅」开关，不新造 `--quiet`）。

**实测偏差（票面前提 vs 现状）：**

- 票面「进度条」在本终端形态下落为**单行原地刷新**（`\r` 重写），不引入 ANSI 光标控制序列——
  仓库既有 `_icon()` 已在 cp936/重定向下做编码降级，硬编码 ANSI 会破坏该口径；
- 票面 `verify: 「进度实时更新且不影响性能」` 的「不影响性能」在本实现里取**结构保证**而非采样：
  未越过阈值时任务数为 0（测试断言 `tracker.task is None` 与 stderr 为空），越过阈值后刷新次数
  被 `PROGRESS_REFRESH_SECONDS` 限频（测试断言上界）。

**共享原语:** 与 Story 64.9 共用同一个 `cli/progress.py`：本票实装 `ToolProgress`（计时 / 限频 /
`\r` 重写 / 降级 / 收尾）；64.9 在同一模块内补 `FileProgressSample` + `format_file_progress`
（已处理 / 总量 / 百分比 / ETA）与 `FileProgressBridge`，由 `ToolProgress` 的刷新行拼接展示。
两票的常量互不重叠：本票 `TOOL_PROGRESS_MIN_SECONDS` / `PROGRESS_REFRESH_SECONDS`，
64.9 的 `FILE_PROGRESS_MIN_BYTES` / `FILE_PROGRESS_CHUNK_BYTES`（唯一真源在
`tools/builtins/file.py`，见 64.9 的 plan）。

## Boundaries & Constraints

- **只改**：新建 `src/heagent/cli/progress.py`；`src/heagent/cli/display.py`（新增
  `tool_progress_label()` 接入点，`_print_stream_event` 行为不变）；`src/heagent/cli/interactive.py`
  （`_consume_stream` 内极小改动：构造 tracker、逐事件喂入、`finally` 收尾）；
  新建 `tests/test_cli_progress.py`。
- **禁止**：`cli/console.py`、`agent/*`、`engine/*`（进度不新增 `StreamEvent` 类型、不改事件协议）、
  `tools/builtins/__init__.py`、`tests/test_architecture_contracts.py`、`docs/frame.md`、`CHANGELOG.md`。
- **依赖方向**：`cli/progress.py` 属入口层，可向下引用 `config` / `tools`；**不新增任何下层对
  `cli/` 的引用**，因此 `tests/test_architecture_contracts.py` 的 `FORBIDDEN_RUNTIME_IMPORTS`
  **不需要**加 `progress` 条目（它只登记被禁的反向边；本模块只是 `cli/` 包内新文件）。
- **异步纪律**：库代码无同步 I/O；刷新只经 `asyncio.Task` + `asyncio.sleep`，不起线程、不常驻；
  run 结束（含取消 / 异常）后必须无残留任务。
- **不阻塞事件循环**：`on_event()` 内不做 I/O，唯一写操作发生在 ticker 协程里。
- **不硬编码 ANSI**：只用 `\r` 重写与空格补齐；非 ASCII 标签写失败时按目标流编码降级（同 `_icon` 立场）。
- **零魔法数**：阈值与刷新间隔是模块级常量，docstring 写明单位（秒）。

## Code Map

| 落点 | 作用 |
| --- | --- |
| `src/heagent/cli/progress.py`（新建） | `TOOL_PROGRESS_MIN_SECONDS = 3.0`、`PROGRESS_REFRESH_SECONDS = 0.5`、`ToolProgress` |
| `src/heagent/cli/display.py` | 新增 `tool_progress_label(event) -> str \| None`：工具事件的进度标签（`activity_label` 同口径），`on_event` 不自行解读事件形状 |
| `src/heagent/cli/interactive.py::_consume_stream` | `progress = ToolProgress()`；循环内 `progress.on_event(event)`；`finally: await progress.aclose()` |
| `tests/test_cli_progress.py`（新建） | <3s 不显示 / >3s 限频刷新 / 停表给终值 / 无残留任务 / 非 tty 单行 / 静音开关 / 常量默认值 |

`ToolProgress` 契约（`cli/progress.py`，对外只有四个成员）：

```python
ToolProgress(*, enabled: bool | None = None, stream: TextIO | None = None,
             min_seconds: float = TOOL_PROGRESS_MIN_SECONDS,
             refresh_seconds: float = PROGRESS_REFRESH_SECONDS, now=time.monotonic)
  .on_event(event: StreamEvent) -> None     # 同步；tool_call 开表、tool_result 停表、text/done 清行
  .task -> asyncio.Task | None              # 在跑的刷新任务（测试断言无残留用）
  .reported_lines -> int                    # 已写出的进度行数（测试断言限频上界）
  async .aclose() -> None                   # 取消任务、清行、清空在途表（幂等）
```

`enabled=None` 时按 `get_settings().announce_progress and stream.isatty()` 推导；`enabled=True` 但
`isatty()` 为假 ⇒ **非 tty 降级模式**（不起任务、不刷新，仅在停表且耗时 ≥ 阈值时写一行终值）。

## Tasks & Acceptance

- [x] `cli/progress.py`：常量 + `ToolProgress`（惰性起任务、限频刷新、`\r` 重写、停表终值、
      非 tty 单行降级、`aclose` 幂等）。
- [x] `cli/display.py`：`tool_progress_label()`。
- [x] `cli/interactive.py`：`_consume_stream` 接入 + `finally` 收尾。
- [x] `tests/test_cli_progress.py`。
- [x] `pytest tests/test_cli_progress.py -q` 全绿（**11 passed**；收口时补 `tests/test_cli_single_progress.py` 12 例覆盖单次模式）。

**Acceptance（对应票面 verify）：**

1. 耗时 < 3 s 的工具：stderr 无任何新增行，且 `tracker.task is None`；
2. 耗时 > 3 s 的工具：出现 `[calling … N.Ns]` 行，刷新次数 ≤ `ceil(elapsed/refresh)+2`；
3. `tool_result` 后：给出含最终耗时的单行，`tracker.task is None`（无残留任务）；
4. 非 tty：中间不刷新，收尾至多一行；
5. `ANNOUNCE_PROGRESS=false`：零输出。

## Implementation Notes

- **为什么是「惰性任务」而不是「常驻 ticker」**：常驻 ticker 每 0.5 s 醒一次，即使绝大多数工具
  <3 s 也在烧唤醒；惰性形态下未越阈值的工具**完全不产生任务**，这就是「不影响性能」的结构保证。
- **为什么 `on_event` 不做 I/O**：它跑在 `run_stream` 的消费协程里，任何写操作都会与
  `_print_stream_event` 抢同一行。渲染统一放在 ticker 协程，`on_event` 只改内存状态。
- **多工具并发**：`tool_result` 只带 `tool_name`（无调用 id）⇒ 按「同名最早一条」出表；行内
  在途数 >1 时附 `(+N more)`，不伪造逐条进度。
- **行尾卫生**：`text` 事件到达时先清掉进度行（`\r` + 空格补齐 + `\r`），否则模型正文会粘在
  半个进度行后面。
- **与 64.9 的拼接**：`ToolProgress` 若持有 `FileProgressBridge`，刷新行尾追加
  `format_file_progress(...)` 片段；无样本时不追加（见 64.9 plan）。

## Verification

命令：`/workspace/.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_cli_progress.py -q`
（实测：**11 passed**；3.6s 工具出 2 行刷新 + 收尾行共 125 字节，1.2s 工具 0 字节）。测试全程不联网、不调真实 API：`StreamEvent` 直接构造，
时钟与刷新间隔用注入的小值（`min_seconds=0.01`）与注入的 `now` 假时钟，真实 `asyncio.sleep`
只在小量级下跑。

实测（本机容器内 py311 venv，**真实常量** 3.0 s / 0.5 s）：

- 1.2 s 工具：`reported_lines = 0`、stderr **0 字节**（未越阈值不产生任务与输出）；
- 3.6 s 工具：3 行（3.0 s 与 3.5 s 各一次刷新 + 收尾），stderr **125 字节**，
  收尾行 `[calling shell → sleep done in 3.6s]`，`tool_result` 后 `task is None`；
- 两个新测试文件合计 **29 passed / 3.8 s**；`ruff check` / `ruff format --check` /
  `mypy --strict` 全通过；
- 连带回归无变化：`tests/test_file_edit.py`、`tests/test_cli.py`、`tests/test_cli_display.py`、
  `tests/test_cli_run_prompt.py`、`tests/test_cli_ws_publish.py`、`tests/test_call_summary.py`
  共 **175 passed**。

⚠ **共享文件待集成**：`tests/test_architecture_contracts.py::test_cli_package_layout_is_pinned`
的钉死清单已由 orchestrator 一次性并入 `cron_cmd` / `progress` / `suggestions` / `wizard` 四行（字母序）。

## Review Triage Log

- 2026-11-18 quick lens（本批 2 条 patch）：
  - `cli/progress.py` 模块 docstring 说「非 tty 降级为至多一行收尾摘要」，实测生产路径（`ToolProgress()`
    默认 `enabled=None`）在非 tty 下**一个字节都不写** ⇒ 改 docstring 与实现对齐（别让注释描述不可达分支）。
  - `_pop` 用 `label.startswith(tool_name)` 出表：将来出现 `cron` / `file` 这类短名工具会把 `cron_list`
    的在途记录误弹掉 ⇒ 改「名字相等 或 名字 + 空格」匹配。
- false：`<3s` 零任务零输出、`tool_end` 后无残留 task、非 tty 不刷屏、进度开关不影响工具语义。
- 留待：单次执行（`loop.run` 非流式）不走 `_consume_stream`，故没有 3s 耗时行——见 64.9 plan 的范围说明。
