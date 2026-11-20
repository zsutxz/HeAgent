---
title: 'Story 65.8 提供调试模式'
type: feature
ticket: 8
created: '2026-11-18'
status: done
baseline_revision: 'ae831fe'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'src/heagent/config/__init__.py'
  - 'src/heagent/cli/console.py'
  - 'src/heagent/cli/errors.py'
  - 'src/heagent/config/catalog/groups.py'
  - '.env.example'
  - 'docs/frame.md'
  - 'tests/test_debug_mode.py'
---

## Intent

**Problem:** 票面 verify「输出完整堆栈追踪与中间变量，可经环境变量启用」。勘差结论：

- 「中间变量」其实**已经存在**（运行栈里有大量 `logger.debug` 记入参/中间量），但没有单一开关能整体打开——
  用户得同时改 `LOG_LEVEL` 与 `LOG_FILE_LEVEL`，且不知道有这个前提；
- 「完整堆栈」**完全不存在**：`cli/errors.py` 的错误出口刻意只渲染
  `message + Try: + Docs:`（+ 命令建议），异常堆栈在任何模式下都不出现，排障只能靠复现 + 猜。

**Approach：** `Settings.debug_mode`（env `DEBUG_MODE`，默认 False）驱动两处：

1. **日志级别**（`cli/console.py::_setup_logging`）：`debug_mode` 为真时两个 handler 都强制 `DEBUG`，
   压过 `LOG_LEVEL`；装配后打一条 `DEBUG_MODE enabled — log level forced to DEBUG (...)`，
   让「为什么日志忽然这么啰嗦」当场可读。
2. **错误出口**（`cli/errors.py::with_hints`）：调试模式**且当前确有异常在飞**时，在既有三段
   （+ 建议段）之后追加 `Traceback (DEBUG_MODE=true):` 段。`with_hints` 是所有
   `exit_with_hints` / `report_with_hints` 的渲染底座 ⇒ 一次覆盖全部 CLI 失败分支。
   无异常在飞时**不追加**（否则会写出 `NoneType: None` 这种假 traceback）。

`_debug_traceback()` 惰性导入 `heagent.config`：`cli/errors.py` 其余部分只依赖 click 与同层建议表，
不让 pydantic-settings 拖进入口层轻量路径；`get_settings()` 有进程级缓存，开销可忽略。

## Verify 实测

`pytest tests/test_debug_mode.py -q` → **7 passed**：

- 默认关：`Settings().debug_mode is False`；
- 环境解析：`DEBUG_MODE=true` ⇒ `get_settings().debug_mode is True`；
- 关闭时错误块**逐字不变**：`"boom\n  Try:\n    - do this\n  Docs: docs/errors.md"`；
- 开启时（在 `except` 内调用）追加段含 `Traceback (most recent call last)` 与 `ValueError: boom-debug`，
  顺序恒在既有三段之后、traceback 收尾；
- 开启但无异常在飞 ⇒ 不追加；
- `LOG_LEVEL=INFO` + `DEBUG_MODE=true` ⇒ root level 与两个 handler 均为 `DEBUG`；
- 未开调试模式时 `LOG_LEVEL=WARNING` 照常生效（调试模式不是唯一入口）。

配套一致性：`.env.example` 补 `DEBUG_MODE`（`test_every_settings_field_is_documented_in_env_example` 钉）、
`config/catalog/groups.py` 的 `observability` 组补键（分类完备性），白名单计数 52 → **53**
（`tests/test_config_catalog.py`）；`docs/frame.md` 4.10 配置表补一行。

## Boundaries

- **不新增 CLI `--debug` 旗标**：票面要求「经环境变量启用」，且旗标需要贯穿 `http-server` / `gui`
  每个子命令的装配面，收益不抵面。
- **不改安全面**：调试模式不绕过审批、不放宽沙箱、不改 plan mode——两层非边界立场不变。
- **不把 traceback 变成默认**：既有错误块形状是契约（三段 + 可选建议段），默认输出必须逐字保持。
