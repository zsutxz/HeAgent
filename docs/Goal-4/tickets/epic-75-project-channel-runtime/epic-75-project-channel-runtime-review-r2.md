---
type: review
code: E75-R2
epic: epic-75-project-channel-runtime
review_loop_iteration: 0
lens: 不变量与守卫反脆弱（宿主自扫 + 反证）
reviewed_at: 2026-11-23
head: da29790d
---

# E75 收口三审 · R2 不变量与守卫反脆弱

## 范围

宿主自扫（不委派）：E75 全部改动的**安全与不变量**面 + **跨产物一致性** + **守卫是否有牙**。
评审对象 = `git diff 604b4fb4..HEAD` 的源码与测试，加 `docs/framework.md` / `docs/errors.md` /
`tests/fixtures/contract_baselines/` 的一致性对读。R1 的三条当轮落改（适配器提交径健康守卫等）
也在本轮范围内（它们是新的不变量来源）。

实跑命令与结果（本轮末次）：

| 命令 | 结果 |
|---|---|
| `pytest tests/network tests/test_architecture_contracts.py tests/test_ws_project_adapter.py tests/test_project_registry_health.py tests/test_http_console_project_run.py tests/test_cli_http_lifecycle.py tests/test_projects.py tests/test_contract_baselines.py -q` | **818 passed, 1 warning**（50.30s） |
| `pytest tests/test_docs_links.py tests/test_security_posture_contract.py -q` | 62 passed |
| `python -m mkdocs build --strict` | exit 0，WARNING 计数 0 |
| `ruff check` / `ruff format --check`（504 files）/ `mypy src`（240 files）/ `bandit -r src/ -ll` | 全绿（bandit：`No issues identified`） |
| `python scripts/contract_snapshot.py --check` | 五份全 `[OK]` |

## 守卫反证（三条，红 → 复原 → 绿）

| # | 守卫 | 注入 | 结果 | 复原 | 结果 |
|---|---|---|---|---|---|
| A | `test_architecture_contracts.py::test_ws_endpoints_and_commands_stay_closed`（命令集封闭） | 在 `ws_protocol.WsCommand` 加 `PROBE_EXTRA = "probe_extra"` | **1 failed**（`:1158`） | 删除该成员 | **1 passed** |
| B | `tests/network/test_ws_error_codes.py::test_network_never_touches_the_filesystem_to_resolve_projects`（AST：`network/` 无 `is_dir`） | 在 `ws_commands.py` 注入 `Path(".").is_dir()` | **1 failed**（`:126`） | 删除函数与 import（`git diff src/heagent/network/` 空） | **18 passed** |
| C | 新增 `test_submit_path_rejects_an_unreadable_registry_with_the_named_code`（R1 落改的守卫） | 把 `_guard_registry` 的条件改成 `if False:` | **2 failed**（两方法各一） | 复原条件 | **26 passed** |

结论：三条守卫都有牙（不是恒真断言）；C 证明 R1 的落改不是「先写用例再写实现」的假绿。

## 发现

| # | 严重度 | 位置 | 现象 | 正确口径 | 处置 |
|---|---|---|---|---|---|
| 1 | **Medium** | `pub/projects.py` `_warn_once` / `_warned`（R1 落改前） | 告警去重集**只增不减**：注册表坏 → 1 条 WARNING；运维修好 → 再坏时**完全静默**（同句柄上第二次故障没有声音）。fail-loud 在「第二次故障」处失效 | 去重只压**同一段故障期**：读/解析成功即复位该成因的告警位 | **当轮落改**：`health()` / `load()` 读成功 `discard(_READ_FAILED)`、解析成功 `discard(_CONTENT_CORRUPT)`；新增 `test_a_second_outage_after_recovery_warns_again`（1 条 → 修好 → 再坏 = 2 条） |
| 2 | Medium | `cli/http.py:377-379` + `cli/ws_project_adapter.py:_guard_registry` | 一次提交现在读注册表 **3 次**（`_guard_registry` 的 health + `ensure_available` 的 console 解析 + `start_project_run` 的 console 解析）；两次读之间注册表若被改，守卫与解析看到不同快照 | 单次读单源（与 R1 M-1 同根） | **进延期项**（R1 M-1 已登记同根缺口，收口轮不扩范围）。风险已收敛：守卫放行后若解析失败，最坏退化回 `unknown_project`（旧行为），**不会**变成「跑错项目」 |
| 3 | Medium | `cli/http.py:355-380`（`_project_channel` 闭包） | 健康探针是「注册表句柄 × 请求时点」求值：`HttpProjectConsole.registry` 若被替换（配置写入后重建实例），闭包跟着换 —— 这是**想要的**；但闭包本身无测试直调（R1 发现 2 的从属项） | 闭包行为由 75.5 的 wiring 用例间接覆盖（`adapter._console is consoles[0]`） | **进延期项**（一条「闭包真调一次 health」的用例即可钉住） |
| 4 | Low | `network/ws_host.py:225` / `:346`、`cli/http_config.py:238` | `project_service` 声明成 `Any \| None`（同类既有的 `run_service` 是具体 Protocol），类型面放弃了对「收下却用错」的守卫 | 收窄成 `ProjectChannelService \| None`（`ws_protocol` 与两处同层，无循环风险） | **进延期项**（纯类型面，不影响运行期语义） |
| 5 | Low | `network/ws_commands.py:192` / `:229` | 端口异常的 `str(exc)` 原样进错误帧：当前所有生产文案都不含路径（实测 `no project 'p…'` / `project 'p…' is unavailable` / `the project registry is unreadable`），但「不含路径」仍只是各处置文案的自觉，无集中守卫 | 一条「错误帧不出现路径形态」的用例（E74 R2 M-2 已登记同项） | **进延期项**（E74 R2 M-2 的同一缺口，指向 75.3 的端口义务） |
| 6 | Low | `docs/framework.md:1402`（R1 落改前） | 文档写「`project_registry_unreadable`（HTTP 500，**仅提交径**产生）」，但当时**没有任何生产代码产生它** —— 文档声称 > 可执行证据（R1 发现 1 的同一条） | 落改后文档与实现一致；本轮补写「提交前先跑健康探针」的口径 | **当轮落改**（`framework.md` 该行补探针口径，`mkdocs --strict` 0 warning） |
| 7 | Low | `tests/network/test_ws_project_submit.py:344` | 端点级「码逐字透传」用例用**桩端口**抛码 ⇒ 它证明的是转译层，不是「生产里真会发生这个码」。R1 发现 1 的假绿正是这条用例 + 两条 adapter 桩用例造成的 | 桩用例保留（它们守的是转译），但「码有生产来源」必须另有真件用例 | **已由 R1 落改覆盖**（`test_submit_path_rejects_an_unreadable_registry_with_the_named_code` 用真 `ProjectRegistry` + 坏文件） |

## 不变量与一致性对读（无发现，记录证据）

| 不变量 | 证据 |
|---|---|
| `network/` 不 import 运行栈/配置面、不 `is_dir` | `test_network_never_imports_the_runtime_stack_or_config` / `test_network_never_touches_the_filesystem_to_resolve_projects`（反证 B） |
| 命令面封闭 5 值、帧类型封闭 6 值 | `test_ws_endpoints_and_commands_stay_closed`（反证 A）、`test_ws_event_contract.py::test_frame_type_set_stays_closed` |
| `projects` 在非集合级端点一律 `invalid_request` 且不断连 | `test_ws_project_commands.py` 四端点用例（集合级 / 单 run / CLI 旁路 / 通知流） |
| 未装配（`project_service=None`）不得静默按启动工作区执行 | `test_project_id_without_project_service_…` + `test_projects_without_project_service_…`（两者都断言 `ping` 仍通 ⇒ 连接未断） |
| 帧面不含 `path` / `session_id` | `test_projects_frame_entry_has_exactly_three_keys_and_no_path`、`SubmittedRun.model_fields == {run_id,status}` |
| 健康探针 `detail` 不含路径、不含异常类名 | `test_unreadable_content_reports_unreadable` 参数化三例 + 目录例 |
| `HttpErrorCode` 总数 36 ↔ 磁盘实测 | `len(list(HttpErrorCode))` = 36，`docs/framework.md:1354/1486` 同值 |
| `transport_errors.json` 里 `project_registry_unreadable` 的 status 来源 | `--check` 五份 `[OK]`；`_CONSOLE_ERROR_STATUS` 落 500 |
| 目录树含新模块 | `framework.md:165`（cli 子模块表）/ `:1626`（cli 树）/ `:1792`（network 树）与 `ls` 一致 |

## 删除检查

diff 删除了三处有意义的代码，均已核「行为重新建立」：

1. `pub/projects.py::load` 原来的就地 `except` 分支 → 收敛进 `_read_raw()`，判据 `test_projects.py` 全绿；
2. `_decode` 由 `classmethod` 改实例方法（只为共享去重集）→ 调用点 `load()` 一个、判据同上；
3. `_decode_or_raise` 的评审期注释（H2 叙事）→ 按「注释只写当前不变量」清理，行为（fail-closed）未动，`test_projects.py` 的写路径用例全绿。

## 落改（当轮）

| 落改 | 文件 | 判据 |
|---|---|---|
| 告警去重按故障期复位（修好后再坏会再响） | `src/heagent/pub/projects.py` | `tests/test_project_registry_health.py::test_a_second_outage_after_recovery_warns_again` |
| `framework.md` 项目通道行补「提交径先跑健康探针」口径 | `docs/framework.md` | `mkdocs build --strict` 0 warning + `test_docs_links.py` |

## 结论

**有条件的通过**：Medium 一条（告警静默，发现 1）当轮落改并补判据；发现 2/3/4/5 进
`brief.md` 延期项（同根于 R1 M-1 与 E74 R2 M-2）；三条守卫反证全部「红 → 绿」，无恒真断言。
无遗留 Critical / High。
