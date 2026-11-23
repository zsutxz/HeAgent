---
ticket: 1
ref: 75.1
code: E75-S01
epic: epic-75-project-channel-runtime
status: done
baseline_revision: 604b4fb4cfebc7a47f8cfe8a2d342c50dbbd1de4
risk: medium
hitl: false
covers: ["R5", "R7"]
---

# E75-S01 · 注册表健康探针与项目错误码

## Tasks & Acceptance

- [x] `pub/projects.py` 新增 `ProjectRegistryHealth`（Pydantic，`frozen` + `extra="forbid"`）：`code: Literal["ok","unreadable"]`、`detail: str`（`max_length=MAX_HEALTH_DETAIL_CHARS`=200，`ok` 时为空串）。进 `__all__`（字母序，三个既有 `MAX_*` 常量原样保留）。
- [x] `ProjectRegistry.health()`：**纯读、不写盘**；`OSError` / `UnicodeError` / `_RegistryCorrupt` 三类一律映射 `unreadable`；文件不存在映射 `ok`（空表是合法状态，`default` 由 `list()` 补齐）。
- [x] 复用**一次私有读径** `_read_raw() -> (raw | None, error | None)`：`load()` 与 `health()` 都只经它读盘，读径内**不打日志**，两个调用方各自决定是否告警。
- [x] 告警按「句柄 × 成因」去重（`_warn_once` + 实例级 `_warned`，`_READ_FAILED` / `_CONTENT_CORRUPT` 两类）：同一注册表句柄上 `health()` + `list()` 反复调用合计**恰 1 条** WARNING，不随请求数刷屏。文案逐字沿用既有两条（`Unable to read project registry %s: %s` / `Invalid project registry; using an empty registry (%s)`）。
- [x] `load()` / `find()` / `list()` 的 fail-soft 语义不变（不可读 ⇒ 空表 ⇒ `list()` 仍回 `default` 一条）；写路径 `_decode_or_raise` 的 fail-closed 语义不动。
- [x] `network/http_protocol.py::HttpErrorCode` 新增 `PROJECT_REGISTRY_UNREADABLE = "project_registry_unreadable"`，类 docstring 的「项目与会话类」分组补名；其余项目侧 code 实测已存在（`unknown_project` / `invalid_project_path` / `project_unavailable` / `project_not_removable` / `project_busy` / `project_limit_reached`），复用不重复定义。
- [x] 新增 `tests/test_project_registry_health.py`（6 例）：正常文件判 `ok`（且探针不建文件、不改字节）；坏 JSON / BOM / 超 32 条参数化三例 + 目录不可读一例判 `unreadable`、`detail` 不含路径、`list()` 仍回 `default` 一条、`caplog` 恰 1 条 WARNING；重复探针只出 1 条。
- [x] 契约基线重生成并人工 review diff（`exception_types.json` + `transport_errors.json`）。

**写集扩写（票面 write_set 漏列，实测必需，逐条显式声明）**

| 路径 | 为什么必需 |
|---|---|
| `src/heagent/network/http_server/pipeline.py` | `_CONSOLE_ERROR_STATUS` 是错误码 → HTTP 状态的**唯一**声明表，也是 `transport_errors` 基线 `status` / `status_source` 的静态来源。新码不进表 ⇒ 基线落 `status: null` + `unmapped`，且运行时按「未列出码」退回 400，与 spine「`project_registry_unreadable` 走 5xx」相反。补 `PROJECT_REGISTRY_UNREADABLE: 500`（与同表的 `SERVER_ERROR: 500` 同组）。 |
| `tests/fixtures/contract_baselines/exception_types.json` | 该基线顶层是 `{classes, http_error_codes}`，新增枚举成员必然漂移，只能脚本重生成。 |
| `tests/network/test_http_protocol.py` | 该文件以**封闭列表**断言项目与会话类错误码全集，新成员不进列表即红。 |
| `docs/errors.md` | 客户端错误契约表（`aihome-client` 直接对读）。新码是客户端会收到的具名错误，表里缺行即契约不完整；只加一行，不改任何既有行。 |
| `src/heagent/web/app.js` | `ERROR_TEXT` 是「每个后端稳定码都要有中文文案」的守卫源（`tests/test_http_web_ui.py::test_every_console_error_code_has_a_readable_text` 从枚举派生参数），新码缺行即红且控制台对该码静默。补一行文案，不动 `DETAIL_CODES` 与其余既有文案。 |

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_project_registry_health.py -q` | **6 passed**（1.29s） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_projects.py tests/test_contract_baselines.py tests/network -q` | **699 passed, 1 warning**（28.45s；唯一 warning 是 starlette TestClient 的 DeprecationWarning） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_contract_baselines.py tests/test_architecture_contracts.py -q` | **45 passed**（17.23s） |
| `.heagent/tmp/py311-venv-linux/bin/python scripts/contract_snapshot.py --check` | 五份全 `[OK]`（exit 0） |
| `.heagent/tmp/py311-venv-linux/bin/ruff check src tests` | All checks passed! |
| `.heagent/tmp/py311-venv-linux/bin/ruff format --check src tests` | 500 files already formatted |
| `.heagent/tmp/py311-venv-linux/bin/python -m mypy src` | Success: no issues found in 239 source files |
| `.heagent/tmp/py311-venv-linux/bin/bandit -r src/ -ll` | No issues identified（4 条 `nosec encountered ... no failed test` 是既有抑制噪声） |
| `wc -l src/heagent/pub/projects.py tests/test_project_registry_health.py` | 382 / 86（单文件上限 1000） |

**契约基线 diff（人工 review 结论）**

- `transport_errors.json`：新增一条 `project_registry_unreadable`（`status: 500` / `status_source: console_status_map`），`status_sources.console_status_map` 24 → 25；`unmapped_codes` 与 `envelope` 未变 ⇒ 新增码的唯一必然位移，无其它字段漂移。
- `exception_types.json`：新增 `http_error_codes.PROJECT_REGISTRY_UNREADABLE` 与 `pub.projects.ProjectRegistryHealth`（`bases: BaseModel`）；**同批吸收了 E74 的既有陈旧漂移**——`network.ws_protocol` 的 `ProjectChannelService` / `RunWebSocketService` / `SubmittedRun` / `WebSocketLike` 四条（74.1 拆模块后基线仍记在 `network.ws_server`）。这正是不属任何 entry 的退避项（E74 回顾列为「已知预期红，由 76.6 重生成」），随机生成一并闭合：`tests/test_contract_baselines.py` 由红转绿（9 例全过）。`classes` 段除此之外零增删。

## Code Map

| 文件 | 改动 |
|---|---|
| `src/heagent/pub/projects.py` | 新增 `MAX_HEALTH_DETAIL_CHARS` / `_READ_FAILED` / `_CONTENT_CORRUPT` / `ProjectRegistryHealth` / `_read_failure_detail()` / `_corrupt_detail()` / `ProjectRegistry._read_raw()` / `._warn_once()` / `.health()`；`load()` 改走共用读径；`_decode()` 由 classmethod 改实例方法（只为复用去重告警）；`__all__` 补两个名字 |
| `src/heagent/network/http_protocol.py` | `HttpErrorCode.PROJECT_REGISTRY_UNREADABLE` + docstring 分组 |
| `src/heagent/network/http_server/pipeline.py` | `_CONSOLE_ERROR_STATUS` 补 `PROJECT_REGISTRY_UNREADABLE: 500` |
| `tests/test_project_registry_health.py` | 新建，6 例 |
| `tests/network/test_http_protocol.py` | 封闭码集断言补一个成员 |
| `tests/fixtures/contract_baselines/{transport_errors,exception_types}.json` | `scripts/contract_snapshot.py --write` 重生成 |
| `docs/errors.md` | 项目与会话类表补一行 |
| `docs/Goal-4/tickets/.../story-e75-s01-plan.md` | 本文件 |

## Design Notes

- **`health()` 不走 `_decode()`**：`_decode` 是读路径 fail-soft 内核（吞掉 `_RegistryCorrupt` 后回空表），探针必须区分「解析不了」与「空表」，故直接调严格内核 `_parse()` 并自行捕获 `_RegistryCorrupt`——两条判定分支不重叠，`_decode` 仍只服务 `load()`。
- **告警去重的落点**：`_read_raw()` 是纯读（不打日志），`load()` 与 `health()` 各自经 `_warn_once()` 决定是否告警。这样「一次不可读判定 = 1 条 WARNING」在 `health()` + `list()` 的组合下也成立（否则同一次请求会出两条），且 `load()` 的文案不动。去重键是**成因**而非 message——同一成因换异常实例不该再刷一条。
- **`detail` 无路径**：读失败取 `strerror`（不含路径）、解析失败只按成因归类（`json.JSONDecodeError` 给行列，`ValidationError` 折叠成一句 schema 不符）——Pydantic 的校验消息会把条目字段（含登记路径）原样带出来，不能透传。
- **探针与写路径的对称破缺是刻意的**：`_decode_or_raise()` 仍是 classmethod（它不告警、不需要实例状态），`_decode()` 变实例方法只为共享去重集。两处共用 `_parse()`，判定内核仍只有一份。
- **状态码选 500 不选 409**：注册表读不出是服务端侧状态失败（与 `SERVER_ERROR: 500` 同组），客户端重试同样失败；409 会让客户端以为「改一下请求就行」。

## Plan Change Log

- 2026-11-23：实现子会话在 26 次迭代处超限退出（未回报），留下 `projects.py` / `http_protocol.py` / `pipeline.py` / 新测试 / 两份基线与本 plan 的骨架，**并越界改了两处**（`network/ws_protocol.py` 的 `ProjectChannelService` docstring、`tests/network/test_ws_project_submit.py` +99 行——均属 75.2 范围，另建了一份 75.2 plan）。宿主接手：`git restore` 回退这两处越界改动、删除越界的 75.2 plan，补回被误删的三个 `MAX_*`（`__all__` 少列会让既有公共导出面静默缩水），补 `docs/errors.md` 一行，按实测重写本 plan 并逐条跑验证。
- 2026-11-23 Decision：基线**全量**重生成而非 `--only transport_errors` —— `exception_types.json` 含 `http_error_codes`，新枚举成员必然漂移；同批顺带吸收 E74 的陈旧 `classes` 漂移（`ws_server` → `ws_protocol` 四条），把 76.6 的「已知预期红」提前闭合。`docs/framework.md` 4.16 的错误码表仍归 76.6（R14 的一次性文档收口）。

## 宿主复核（2026-11-23，批末串行门禁）

- `pytest tests/test_project_registry_health.py -q` → 6 passed（子会话自测 6 passed，宿主复跑同值）
- `pytest tests/network tests/test_architecture_contracts.py tests/test_project_registry_health.py tests/test_projects.py tests/test_contract_baselines.py tests/network/test_http_protocol.py -q` → **772 passed, 1 warning**
- `python scripts/contract_snapshot.py --check` → 五份全 `[OK]`（`exception_types.json` 由宿主按批级派生重生成，见批收尾提交）
- `ruff check src tests` / `ruff format --check src tests`（501 files）/ `mypy src`（239 files）/ `bandit -r src/ -ll`（No issues identified）全绿
- 写集扩写 3 处（`http_server/pipeline.py` 状态表、`tests/network/test_http_protocol.py` 码清单、`web/app.js` 文案）+ 批级派生 2 处（`exception_types.json`、`docs/errors.md`）已由宿主确认并随本 entry 或批收尾提交
