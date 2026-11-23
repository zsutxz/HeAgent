---
epic: epic-74-ws-frame-contract
code: E74
round: R2
axis: 不变量与守卫反脆弱
skill: 宿主自扫 + 注入反证
review_loop_iteration: 1
date: 2026-11-23
verdict: 有条件的通过
critical: 0
high: 1
medium: 3
low: 2
---

# E74 收口三审 · R2 不变量与守卫反脆弱

## 范围

- **判据来源**：epic `Boundaries`（不改文档 / 不重生成快照 / 不动容量参数）+ `brief.md` Constraints（N2 哑传输、NG1–NG13）+ `docs/framework.md` §4.16 / §4.16.1 / §4.18 的现行口径。
- **本轮技能**：宿主自扫 + 注入反证（无外部技能）。
- **扫描面**：`src/heagent/network/ws_commands.py` / `ws_protocol.py` / `ws_server.py` / `ws_host.py` 全文；`tests/network/test_ws_error_codes.py` / `test_ws_event_contract.py` / `test_ws_command_fields.py` / `tests/test_architecture_contracts.py` 的守卫实现；`docs/framework.md` 命令面与目录树；`tests/fixtures/contract_baselines/transport_routes.json`。
- **反证脚本**（可复跑）：`.heagent/tmp/Goal-4/r2/guard_teeth.py`（A/B/C 三处注入）与 `.heagent/tmp/Goal-4/r2/guard_teeth_relative.py`（D 相对导入，含 HEAD 版本对照）。

## 发现

### 一、不变量自扫（逐条给证据）

| 不变量 | 结论 | 证据 |
|---|---|---|
| 凭据 / prompt 不进日志 | ✅ 成立 | `grep -n "prompt" src/heagent/network/*.py` 与日志调用交叉核对：`ws_server.py` 的 13 处 `logger.*` 只打 `connection_id` / `run_id` / `event` / `reason`，无 prompt、无 project 负载 |
| 路径不进错误帧（传输层不认识目录） | ⚠ 当前成立、E75 有前向风险 | `network/` 内 `is_dir` 零命中（AST 判据）且 `project_id` 是不透明短 id；但 `ws_commands.py:191-192` 把适配器异常的 `str(exc)` 原样放进错误帧 ⇒ E75 适配器若把路径写进异常消息即外泄（见 M-2） |
| 错误分类单源 | ✅ 成立 | 错误帧 code 全部取自 `HttpErrorCode`（`_send_error_frame` 形参类型 + `error_envelope`）；`test_ws_error_codes.py:63-74` 逐条核 `HttpErrorCode` 成员与 `transport_errors.json` 条目 |
| 端点可见性判定 | ✅ 成立（结构式） | `ws_host.py:261` 只在 `not config.readonly` 时注册集合级 `/api/runs/ws`；`ws_host.py:308` 通知流对所有 listener 注册；单 run 端点 `readonly` 透传到 `_handle_commands`（`ws_server.py:98-103`） |
| CLI 旁路 / 通知流不开放控制面 | ✅ 成立 | `ws_server.py:487` 与 `:608` 对 `CANCEL` 与 `CANCEL_RUN` 同档拒绝，文案沿用各自既有句 |
| 事件面零 `project_id` | ✅ 成立且有牙 | `test_ws_event_contract.py` 7 例 + 反证 C（注入 `project_id` 到 `WsEventFrame` ⇒ 3 例转红） |
| 契约数字与磁盘一致 | ✅ 成立 | `HttpErrorCode` 实测 35 成员 == `framework.md:1353` 的「封闭 **35** 码」；`transport_routes.json` `route_count=28` 与路由集断言一致、本 epic 未增路由 |
| 容量参数未动 | ✅ 成立 | 本 epic 零改动 `http_server/service.py` / 名额常量；`git diff d6e705de^..HEAD --stat` 只含 network 三文件 + 测试 |

### 二、守卫反脆弱（注入 → 判红 → 复原 → 转绿）

| # | 注入 | 命中守卫 | 结果 |
|---|---|---|---|
| A | `WsCommand` 加第 5 个成员 `PROJECTS`（不登记字段表） | `tests/network/test_ws_command_fields.py` + `test_ws_endpoints_and_commands_stay_closed` | 注入后 `2 failed, 4 passed`；复原后 `6 passed` ⇒ **有牙** |
| B | `ws_commands.py` 加 `import heagent.config` | `test_network_never_imports_the_runtime_stack_or_config` | 注入后 `1 failed`；复原后 `1 passed` ⇒ **有牙** |
| C | `WsEventFrame` 加 `project_id` 字段 | `tests/network/test_ws_event_contract.py` | 注入后 `3 failed, 4 passed`；复原后 `7 passed` ⇒ **有牙** |
| D | `ws_commands.py` 加 **`from ..config import get_settings`**（相对导入） | 依赖边界两条守卫 | **HEAD 版本：`1 passed`（无牙）**；工作树修补版：`1 failed, 1 passed`；无注入 `2 passed` ⇒ 修补后**有牙** |

### 三、分档发现表

| # | 严重度 | 位置 | 现象 | 正确口径 | 处置 |
|---|---|---|---|---|---|
| H-1 | **High** | `tests/network/test_ws_error_codes.py:51-70`（HEAD 版）、`tests/test_architecture_contracts.py:147-169`（HEAD 版） | 两条依赖边界守卫只看 `node.module` 的**绝对名**。包内最惯用的 `from ..config import get_settings` 因此整条绕过：反证 D 在 HEAD 上注入相对导入后守卫 **绿**（无牙）。这是「哑传输」这条核心不变量唯一的机器判据，失效即无判据 | 识别器必须按文件所属包补全相对导入（`level` → 去掉 `level-1` 段再加模块名）；`is_dir` 同理按 AST 判而不是文本 | **当轮落改**：已在工作树完成（`_absolute_module` / `_package_of` / `_imported_modules` + 两条新判据 `test_forbidden_import_detection_covers_relative_forms`、`test_relative_imports_are_detected_as_runtime_dependencies`），随 E74 收口提交 |
| M-1 | Medium | `docs/framework.md:1771`（目录树） | 新增模块 `network/ws_commands.py`（253 行）**未进架构目录树**；`grep -n ws_commands docs/` 在 `docs/framework.md` 零命中 | 架构权威文档的目录树必须与磁盘一致（本仓以「布局即契约」为口径，cli/pub 有白名单守卫，network 无 ⇒ 只能靠人工同步） | 转 **76.6**（文档收口）。考虑后续为 `network/` 补一条目录白名单守卫 |
| M-2 | Medium | `ws_commands.py:191-192`（`_send_error_frame(exc.code, str(exc))`） | 适配器异常消息原样上线；E74 无适配器所以当前无泄漏，但 E75 适配器一旦把路径 / 工作区名写进 `HttpRunConflictError` 消息，就经错误帧外泄 | 远程可见面只允许 `{id, name, available}` 类投影；异常消息里不得出现宿主路径 | 转 **75.2 / 75.3**：适配器侧约束 + 一条「错误帧不含 `/` 路径形态」判据 |
| M-3 | Medium | `docs/framework.md:1353` / `:1390` / `:1397` / `:1771` / `:1984` / `:1985`（六处） | 命令集口径仍写 `{run, cancel, ping}`，实际已 4 值（新增 `cancel_run`）；单 run 端点行仍 `{cancel, ping}` | 活文档口径必须与 `WsCommand` 成员一致 | 转 **76.6**：六处逐条改为 `{run, cancel, cancel_run, ping}` / `{cancel, cancel_run, ping}` |
| L-1 | Low | `ws_host.py:261` / `ws_commands.py:233-243` | 集合级端点无 `readonly` 形参，只读口径靠「不注册该端点」结构保证；端点 docstring 未写明这条前提 | 结构式保证应写明，否则后续给集合端点加注册条件时容易破 | 转 76.6 / 后续 entry（与 R1 L-2 同一条，不重复计） |
| L-2 | Low | `tests/network/test_ws_error_codes.py` 的 `is_dir` 判据 | 本工作树已从文本匹配改为 AST 判（注释/文档字符串提到 `is_dir` 不再误判）；口径变严，需要一次全量回归确认无新红 | AST 口径与本文件其余导入面断言一致 | 已随 H-1 落改，回归见 `## 结论` |

## 结论

**有条件的通过。**

- Critical **0**、High **1**、Medium **3**、Low **2**。
- H-1（依赖边界守卫对相对导入无牙）是**当轮落改**项：修补已在工作树完成并用反证 D 自证（HEAD 无牙 → 修补后有牙 → 无注入转绿）。
- M-1 / M-2 / M-3 全部转下游 entry（76.6 文档收口、75.2/75.3 适配器约束），已登记 `brief.md`「延期项」。
- 回归实测（修补后）：`pytest tests/network tests/test_architecture_contracts.py -q` = **711 passed**（+2 新判据）；`ruff check` / `ruff format --check` / `mypy src` 全绿。
