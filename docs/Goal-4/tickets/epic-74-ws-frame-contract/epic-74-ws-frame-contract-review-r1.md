---
epic: epic-74-ws-frame-contract
code: E74
round: R1
axis: 规格与实现对账
skill: bmad-code-review
review_loop_iteration: 1
date: 2026-11-23
verdict: 有条件的通过
critical: 0
high: 0
medium: 2
low: 8
---

# E74 收口三审 · R1 规格与实现对账

## 范围

- **判据来源**：`docs/Goal-4/tickets/epic-74-ws-frame-contract/epic-74-ws-frame-contract.md` 的 R1–R7 / Outcome / Boundaries / 已知 Done when（5 条）+ 同目录 `tickets/` 五份 plan 的 `## Verification`（74.1–74.5）。
- **本轮技能**：`bmad-code-review`（R1 轴：规格↔实现对账 + 验证证据可复现性；不做风格挑刺）。
- **改动文件面**（`git diff d6e705de^..HEAD --stat`，5 个提交 d6e705de / eeb7fee9 / e0e9d411 / ae1809f9 / 8b78186c）：

| 文件 | 变化 | 现状行数 |
|---|---|---|
| `src/heagent/network/ws_commands.py` | +253（新文件） | 253 |
| `src/heagent/network/ws_protocol.py` | +199 / 少量改写 | 426 |
| `src/heagent/network/ws_server.py` | 247 行变动（多为迁出） | 698 |
| `tests/network/test_ws_command_fields.py` | +131（新） | — |
| `tests/network/test_ws_project_submit.py` | +258（新） | — |
| `tests/network/test_ws_cancel_run.py` | +228（新） | — |
| `tests/network/test_ws_event_contract.py` | +95（新） | — |
| `tests/network/test_ws_error_codes.py` | +111（新） | — |
| `tests/network/test_ws_protocol.py` | +40（**纯增、无删除**） | 既有断言逐字未改 |
| `tests/test_architecture_contracts.py` | +4/-1（封闭命令集扩到 4 值） | — |

- **本轮实测复跑**（`.heagent/tmp/py311-venv-linux/bin/python -m pytest`）：
  - `tests/network tests/test_architecture_contracts.py -q` → **709 passed, 1 warning**（与 74.5 plan 逐字一致；宿主另跑一次同样 709）
  - `wc -l` → 698 / 253 / 426
  - `transport_errors.json` 核对 → 七条 code **全部落在 `entries`**（`unmapped_codes` 仍是原来 5 条）
  - ⚠ 评审子会话**首次**执行同一命令给出 `5 failed / 704 passed`（`test_ws_event_contract.py`×3 + `test_ws_error_codes.py::test_network_never_imports_the_runtime_stack_or_config` + `test_ws_protocol.py::test_event_frame_round_trip_preserves_nested_sse_payload`），随后 3 次与宿主 1 次全绿 ⇒ 见 M-2

## 发现

### 逐条 Requirements 对账

| 条目 | 判定 | 证据 |
|---|---|---|
| **R1** 命令帧白名单单表 + 可选 `project_id` | **已交付** | `ws_protocol.py:87` `_FRAME_FIELDS`（4 成员全覆盖）/ `:97` `_OPTIONAL_FRAME_FIELDS` / `:100` `required_frame_fields` / `:105` `_unexpected_fields`；`:233` `project_id: str \| None = Field(min_length=1, max_length=16)`（无 strip）；`:357` 解析器与模型校验器读**同一张表**；判据 `test_ws_command_fields.py:84-86`（`set(_FRAME_FIELDS) == set(WsCommand)`）、`:89-95`、`:98-103`（`""` → malformed） |
| **R2** 注入端口形状 | **部分** | `SubmittedRun`（`ws_protocol.py:326`，`extra="forbid"`，只有 `run_id` / `status`）✅；`ProjectChannelService`（`:339`，方法参数名恰 `{project_id, prompt}` / `{project_id}`，判据 `test_ws_project_submit.py:252`）✅；两个构造器关键字参数 `ws_server.py:228` / `:362` ✅；`None` 护栏单处 `ws_commands.py:154-160`，判据 `test_ws_command_fields.py:115-131`（`start_run` 0 次）✅。**偏差**：R2 字面要求 Protocol「声明在 `network/ws_server.py`」，实际声明在 `ws_protocol.py:339`（74.3 拆分所致，`ws_server.py:690`/`:692` 重导出，对外名不减）→ L-3 |
| **R3** `ensure_available` → `start_project_run` 次序 / 码透传 / 零副作用 | **已交付** | `ws_commands.py:161-162`；`except` 单处 `:191-192`（`_send_error_frame(exc.code, str(exc))`，不断连）；判据 `test_ws_project_submit.py:194`（`calls == ["ensure_available:p1234abcd", "start_project_run:p1234abcd"]`、`start_run_calls == 0`）、`:213`（ensure 失败：两启动路径 0 次 + 后续 ping 仍 ack + `closed_code is None`）、`:235`（start 失败：`start_run` 仍 0 次） |
| **R4** 七条 code 均为既有成员且在基线有条目；不新增码、不重生成快照 | **已交付** | 实测七条全在 `transport_errors.json` 的 `entries`；判据 `test_ws_error_codes.py:63-66`（⊆ `HttpErrorCode`）、`:69-74`（逐条读基线，不硬编码）；`src/` 在 s04/s05 零改动 |
| **R5** `cancel_run` 帧 + 与 `cancel` 同源 + readonly / 绑定 run / 幂等 / `unknown_run` | **部分** | 帧面：`ws_protocol.py:80` + `:234` `run_id`（min 1 / max 64，不入全局可选集 ⇒ 必带），判据 `test_ws_protocol.py:211-249`；同源：`ws_commands.py:120` 与 `:129` 同一 `service.cancel_run(run_id)`，判据 `test_ws_cancel_run.py:215-227`；只动目标 run：`:140-152`；幂等终态 ack：`:156-165`；绑定 run 比对：`ws_commands.py:113-119`；readonly：`:106-112`。**两处口径差**：单 run 端点 `unknown_run` 仍断连（L-1）、集合面 `cancel_run` 无 readonly 判据（L-2） |
| **R6** 事件面零变更 + 不新增路由 | **已交付** | `test_ws_event_contract.py:43-45` / `:48-51` / `:54-56`（`WsFrameType` 五档封闭）/ `:59-63`（golden 逐字节）/ `:66-78`（帧层 + 负载层都拒 `project_id`）/ `:81-95`（路由集对 `transport_routes.json`）；`src/` 中 `WsEventFrame` / `WsAckFrame` / `WsFrameType` 零改动 |
| **R7** `network/` 仍是哑传输 | **已交付** | AST 导入面断言 `test_ws_error_codes.py:77-84`（含 `TYPE_CHECKING`）、`is_dir` 零命中 `:87-94`、同层互不依赖 `:97-110`（含新 `ws_commands.py`）；`pytest tests/test_architecture_contracts.py -q` 绿（封闭命令集扩到 4 值） |

**Done when 五条**：① 带 / 不带 `project_id` 各有用例 ✅（`test_ws_project_submit.py:174` / `:194`；既有 `test_ws_protocol.py` 断言纯增无删）；② 未知 / 不可用 `project_id` 断言三件事——「无新 run」「错误码已登记」✅，**「名额计数不变」无直接判据**（M-1）；③ `cancel_run` 三判据 ✅；④ golden + `project_id` 拒收 ✅（实际判的是 `ValidationError`，见 L-5）；⑤ 依赖边界 + 架构契约绿 ✅。

### 分档发现表

| # | 严重度 | 位置 | 现象 | 正确口径 | 处置建议 | 谁守着 |
|---|---|---|---|---|---|---|
| M-1 | Medium | `tests/network/test_ws_project_submit.py:213-234`；epic `已知 Done when` 第 2 条 | epic 要求「无新 run、**名额计数不变**、错误码已登记」三件，测试只断言 `start_run_calls == 0` 与 `start_project_run_calls == 0`，无 inflight / 名额计数读数 | 「名额计数不变」应是可读计数断言，或当场裁定「零启动调用 ⇒ 必然未占名额」为可接受的间接覆盖并回写 | 转 E75（适配器落地时连带补计数断言）；本轮记入 `brief.md`「延期项」 | 无守卫（当前无测试钉住该子句） |
| M-2 | Medium | `story-e74-s05-error-codes-plan.md:38`（`709 passed, 1 warning`） | 评审子会话**首跑** 5 红（node id 见「范围」），随后 3 次 + 宿主 1 次全绿 709，谱不可复现 | plan 的 Verification 数字可复现（709 ✅），但一次性红谱必须归档而非判「从未发生」 | 已归档于本报告与 `brief.md`「延期项」；同一谱再现时按环境产物分诊 | 无守卫（flake 本身无判据） |
| L-1 | Low | `src/heagent/network/ws_commands.py:132-134` | 单 run 端点 `cancel_run` 命中「绑定 run 记录已消失」时走 `_send_error(..., close_code=WS_CLOSE_POLICY)` ⇒ **断连** | R5 字面「目标不存在回 `unknown_run` 且不断连」；plan 74.3 Design Notes 显式登记为刻意（该连接唯一目标已不存在） | 保持实现，文本口径记入「延期项」待 E76 文档收口时统一措辞 | `test_ws_cancel_run.py:169-180` 只覆盖集合面不断连 |
| L-2 | Low | `src/heagent/network/ws_commands.py:233-243` + `src/heagent/network/ws_host.py:261` | 集合级 `cancel_run` 分支无 `readonly` 判据；readonly 口径由「只读 listener 不注册集合端点」结构兜住 | readonly 对「命令可达性」成立即可，但该前提应写在端点 docstring 里 | 记入「延期项」，E76 白名单收口时补 docstring 或形参 | `test_ws_cancel_run.py:200-211` 只覆盖单 run 端点 |
| L-3 | Low | `src/heagent/network/ws_protocol.py:339`；`ws_server.py:690`/`:692` | R2 字面「Protocol 声明在 `ws_server.py`」，实际在 `ws_protocol.py` 并重导出 | 契约位置以「对外可用名 + 依赖方向」为实质；R2 为拆分前表述（epic Requirements 冻结，不回改） | 记入「延期项」；后续 entry 按 `ws_protocol.py` 找 | `test_ws_project_submit.py:252` 与 `ws_server.__all__` 生效 |
| L-4 | Low | `ws_protocol.py:233`；`test_ws_command_fields.py:98-111` | `max_length=16` 无判据（只测 `""` 与未知键），而 `run_id` 侧有 65 字符用例 | 字段边界应对称 | 补一例 17 字符 ⇒ `malformed`（本轮不扩范围，记「延期项」） | 无守卫 |
| L-5 | Low | `test_ws_event_contract.py:75-78`；epic Done when 第 4 条 | 字面「判 `WsFrameError`」，实际断言 pydantic `ValidationError`（出站帧模型不经 `parse_command_frame`） | 入站路径 `WsFrameError`、出站帧模型 `ValidationError`，两档都合法 | 口径记入「延期项」 | 测试本身绿 |
| L-6 | Low | `ws_server.py:362`（`project_service` 形参） | 单 run 端点接受 `project_service` 但从不使用（docstring 已声明） | 空挂参数有被误读成「订阅端点支持项目寻址」的风险 | 保持现状，E75 装配时再定 | 无判据 |
| L-7 | Low | `story-e74-s03-cancel-run-plan.md:46` 记 425 / 实测 426 | plan 行数口径差 1 | plan 数字应与 HEAD 逐字一致 | 已在 `progress.md` 决策日志登记；plan 归属 entry 已 built，不回改冻结段 | `test_architecture_contracts.py` 只判 ≤1000 |
| L-8 | Low | `ws_commands.py:180-190` | `RunRequest` 校验先于项目护栏 ⇒ `project_id` + 空 prompt 回 `empty_prompt` 而非 `invalid_request` | plan 74.2 已登记为有意次序 | 记入「延期项」 | `test_ws_command_fields.py:115` 只测合法 prompt |

## 结论

**有条件的通过。**

- Critical **0**、High **0**；Medium **2**（M-1 名额计数缺直接判据、M-2 一次性红谱不可复现）、Low **8**（其中 L-1 / L-2 / L-3 是**文本↔实现偏差**，均已在 plan Design Notes 或本条发现显式登记，非静默缺口）。
- R1–R7 中 **5 条已交付、2 条部分交付**（R2 = 声明位置偏离字面但实质约束满足；R5 = 主体全交付、两处口径差已登记）。
- 验证证据可信：`709 passed, 1 warning` 与 74.5 plan 逐字复现（宿主独立复跑同值）；`wc -l` 仅 1 行偏差（L-7）；七条 code 实测全在 `transport_errors.json` 的 `entries`；`test_contract_baselines` 的预期红已在 `progress.md` 如实登记为 76.6 交付项。
- 无 Critical / High ⇒ 本轮**无落改**，M-1 / M-2 与 8 条 Low 全部进 `brief.md`「延期项」，放行至 R2。
