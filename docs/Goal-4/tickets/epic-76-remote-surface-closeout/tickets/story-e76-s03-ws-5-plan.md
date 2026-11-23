---
ticket: 3
ref: 76.3
code: E76-S03
epic: epic-76-remote-surface-closeout
risk: low
hitl: false
covers: ["R5"]
status: built
---

# E76-S03 · 远程可见面白名单收口：WS 命令面 5 值封闭、无配置/注册/历史族

## Tasks & Acceptance

- [x] `tests/network/test_ws_protocol.py` 增补 E76-S03 一节（+~170 行，既有用例全保留）：命令面与帧面**集合相等**断言 + 能力族词根守卫 + WS 面源码符号守卫三组。
- [x] **命令值集合相等**：`len(WsCommand) == 5` 且 `{c.value for c in WsCommand} == {cancel, cancel_run, ping, projects, run}`（多一条即红）。
- [x] **命令 → 字段白名单逐条镜像**：`_EXPECTED_REMOTE_FRAME_FIELDS` 与生产 `_FRAME_FIELDS` **逐条相等**（不是子集）；`set(_FRAME_FIELDS) == set(WsCommand)`。
- [x] **出站帧字段白名单**：九个帧模型（含 `WsProjectsFrame` / `ProjectChannelEntry` / `SubmittedRun`）的 `model_fields` 集合逐条相等。
- [x] **入站字段不越界**：`WsCommandFrame.model_fields` ⊆ 各命令字段白名单的并集（`project_id` 只出现在 `run`）。
- [x] **能力族词根双向守卫**：命令值、入站/出站字段名、以及五个 WS 面模块（`ws_auth` / `ws_commands` / `ws_host` / `ws_protocol` / `ws_server`）的**符号名**中，都不出现 `setting` / `config` / `register` / `session` / `history` / `write` / `delete` / `remove` / `rename` / `approve` / `dialog` 词根。
- [x] **解析器行为**：这类帧一律 `unknown_command`（不以「静默忽略」收场）。
- [x] HTTP 面与审批面**零代码改动**，只复跑既有断言留痕（见 Verification）。
- [x] 写集严守票面：只动 `tests/network/test_ws_protocol.py` + 本 plan；`src/` **零改动**；未动 `docs/`（远程可见面表由 76.6 收口）。

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network/test_ws_protocol.py -q` | **47 passed**（原 40 + 新 7） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network -q -k "ws_protocol or ws_server"` | **全绿**（含命令集合相等断言） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network -q` | **728 passed, 1 warning** |
| 复跑留痕（远程注册仍 403） | `tests/network/test_endpoint_security.py` + `tests/test_http_security.py` ⇒ **192 passed** |
| 复跑留痕（审批仍只见 `tool_error=True`） | 同上批次含 `tests/test_mcp_manager.py` ⇒ **192 passed**（三文件合计） |
| `grep -rEn "set_setting\|write_config\|register_project\|list_sessions" src/heagent/network/` | **11 命中，全部在回环 HTTP 控制台三模块**（`http_console_protocol.py` / `http_server/app.py` / `http_server/endpoints_console.py`），WS 面五个模块 **0 命中**（见 Design Notes 的口径修正） |
| `grep -c` 于 `src/heagent/network/http_protocol.py` 的配置/注册/历史类新码 | **0**（`HttpErrorCode` 36 码，本 entry 未新增） |
| `.heagent/tmp/py311-venv-linux/bin/python -m ruff check src tests` / `ruff format --check src tests` | 全绿（506 files） |
| `wc -l tests/network/test_ws_protocol.py` | 466（单文件上限 1000） |

## Code Map

| 文件 | 改动 |
|---|---|
| `tests/network/test_ws_protocol.py` | +~170 行：`_WS_SURFACE_MODULES` / `_LOOPBACK_CONSOLE_MODULES` / `_FORBIDDEN_REMOTE_STEMS` / `_EXPECTED_REMOTE_FRAME_FIELDS` / `_REMOTE_FRAME_MODELS` 常量 + 三个投影函数 + 七例 |
| `docs/Goal-4/tickets/.../story-e76-s03-ws-5-plan.md` | 本文件 |
| `src/` | **无改动** |

## Design Notes

1. **口径修正（`bad_spec` 记录）**：票面 verify 写「`content_search` 在 `src/heagent/network/` 内对 `set_setting|write_config|register_project|list_sessions` **恒 0 命中**」——该字面**在 HEAD 上为假**，因为**回环 HTTP 控制台本身就住 `network/`**（`http_console_protocol.py` 的 `ConsoleHandler.register_project` / `list_sessions`、`http_server/app.py` 与 `endpoints_console.py` 的路由注册）。R5 的真口径是「**WS 面**不扩张」（远程注册仍走 HTTP 且回 403）。⇒ 守卫按**模块面**实施：WS 面五个模块 0 命中，回环控制台三模块是白名单（显式列出、不靠通配）。不改 epic Requirements（冻结），本记录即裁定载体。
2. **为什么取「集合相等」而不是「包含」**：白名单的本意是「多一条远程能力 = 显性新增」。子集断言会让「多加一条命令」静默通过；相等断言把它变成红。
3. **词根用子串、大小写不敏感**：`set_setting` / `update_setting` / `setting_value` 都要命中。为了避免误伤，口径里显式说明 `registry_state`（含 `registr` 但**不含** `register`）不会被判成「项目注册」——这条踩过一次就会想放宽成前缀匹配。
4. **符号名守卫的范围**：只扫五个 WS 面模块的**标识符**（AST/正则取名字），不扫注释与 docstring —— 注释里提「不得 import 配置面」是正当说明（E74-S05 已踩过纯文本搜的坑）。
5. **不重复钉端点**：四条 WS 端点路径由 `tests/test_architecture_contracts.py::test_ws_endpoints_and_commands_stay_closed` 钉死，本 entry 不复制第二份端点清单（避免两处真相）。

## 宿主复核（2026-11-23，批末串行门禁）

- 实现子会话在 25 次迭代处超限退出（未回报），工作树留下 `tests/network/test_ws_protocol.py` 的增补（+~170 行）但**未写 plan**；宿主按实测补本 plan、修掉一处重复 import（`WsAckFrame` 两次）与一处格式问题后跑门禁。
- `pytest tests/network/test_ws_protocol.py -q` → **47 passed**；`pytest tests/network -q` → **728 passed**。
- 票面 verify 的 `content_search 恒 0 命中` 口径按模块面修正（见 Design Notes 第 1 条），已同步记入 epic Notes。
