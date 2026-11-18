---
title: 'Story 65.7 实现结构化日志'
type: feature
ticket: 7
created: '2026-11-18'
status: done
baseline_revision: 'ae831fe'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'src/heagent/pub/log_config.py'
  - 'src/heagent/cli/console.py'
  - 'src/heagent/gui/cli.py'
  - 'src/heagent/config/__init__.py'
  - 'src/heagent/config/catalog/groups.py'
  - 'src/heagent/config/catalog/guards.py'
  - '.env.example'
  - 'docs/frame.md'
  - 'tests/test_structured_logging.py'
---

## Intent

**Problem:** 三个入口各自装配日志（`cli/console.py::_setup_logging` 写 stderr+文件、`gui/cli.py` 写文件、
`cli/http.py` 复用 console 的那份），格式字符串在**两处**重复硬编码为
`%(asctime)s %(levelname)s [%(name)s] %(message)s`，且没有任何机读格式可选。
票面 verify 要求「含时间戳、级别、模块、消息、上下文，可经环境变量切换格式」——现状零项达成
（前四项靠人眼从文本行里抠，上下文完全没有）。

**Approach：**

1. **格式实现单点** `src/heagent/pub/log_config.py`：`TEXT_FORMAT` / `TEXT_DATE_FORMAT` 常量 +
   `JsonFormatter` + `make_formatter(log_format)`。放 `pub/` 是因为它零运行栈依赖、而三个入口
   （CLI/GUI/HTTP）都要用——若放 `cli/`，GUI 与 HTTP 就得反向依赖 CLI 的私有函数。
2. **json 口径**：单行 JSON，键 `timestamp`（带本地时区偏移的 ISO-8601，毫秒）/ `level` / `logger` /
   `message`；`extra=` 注入的非标准字段落 `context`；异常落 `exc_info`（完整 traceback 字符串）；
   不可序列化的上下文值退化为 `str()`（日志设施故障不得让业务抛错，与 `pub/safe_logging` 同一立场）。
3. **设置面**：`Settings.log_format: Literal["text","json"] = "text"`。非法值在**加载时**炸
   （pydantic 校验），不静默回落——「我明明配了 json」不该只在排障时才发现。
   同步三处配置面登记：`.env.example`（`test_every_settings_field_is_documented_in_env_example` 钉）、
   `config/catalog/groups.py` 的 `observability` 组（否则分类完备性红）、
   `config/catalog/guards.py` 的枚举守卫（写通道先拦，别等启动才炸）。
4. **装配收口**：`cli/console.py` 与 `gui/cli.py` 各建 handler 后用 `make_formatter(settings.log_format)`
   设 formatter，`basicConfig` 里的 `format=` / `datefmt=` 随之移除（避免两份格式定义漂移）。
   `cli/http.py` 复用 console 的函数 ⇒ HTTP 入口自动获得同一口径。

**为什么默认 text 且逐字保持历史形状**：`runtime_stats`（`scripts/` 下 `collect.py`）按行正则解析
`provider_call_completed` 等日志行采样 token 与模型用量；默认格式一变就是静默失采。json 是 opt-in。

## Verify 实测

- `pytest tests/test_structured_logging.py -q` → **10 passed**（text 形状 regex 全匹配、json 可 `json.loads` +
  四键齐、timestamp 带 `±HH:MM` 偏移、extra → context、traceback 入 exc_info、不可序列化值退化、
  未知格式 `ValueError`、`Settings(log_format="yaml")` 抛 `ValidationError`、环境解析 json、
  `_setup_logging()` 装配 json 后**真写出的文件行**可解析且带 context、默认装配非 JsonFormatter）。
- `pytest tests/test_config_catalog.py tests/test_config.py tests/test_config_validation.py -q` →
  215 passed（含 `test_every_settings_field_is_documented_in_env_example`、白名单计数 51 → **52**）。
- `pytest tests/test_architecture_contracts.py -q` → 39 passed（`pub/` 布局清单加入 `log_config`）。
- `pytest tests/test_safe_logging.py` 不受影响（同步跑过）。

## Boundaries

- **不改 uvicorn / httpx 的日志配置**：uvicorn 自带 logger 层级与访问日志格式，改它属于运维面；
  本 story 只覆盖本仓 `logging` 行。
- **不做日志采样 / 轮转 / 远端投递**：`logs/` 的保留与清理归 `housekeeping`（已有），投递不在票面内。
- **不把 json 变默认**：默认变化属破坏性（见上）。
- `runtime_stats` 的解析器不随本 story 改造（json 模式下它读不到行，属「换格式就要换消费方」的已知前提，
  写在 `docs/frame.md` 的日志卫生段，并登记台账 **A58**）。
