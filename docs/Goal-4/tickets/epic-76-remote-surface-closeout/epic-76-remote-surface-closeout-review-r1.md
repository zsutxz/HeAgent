---
type: review
code: E76-R1
epic: epic-76-remote-surface-closeout
review_loop_iteration: 0
lens: 规格与实现对账（bmad-code-review）
reviewed_at: 2026-11-23
head: 3ef5be81
---

# E76 收口三审 · R1 规格与实现对账

## 范围

- 本 epic 六个提交：`bf0f2acb`(76.1) / `7387a271`(76.2) / `49aa206a`(76.3) / `a0720f6e`(76.4) / `62357e3d`(76.5) / `3ef5be81`(76.6)；范围 = `fda84d94..HEAD`。
- 实质代码改动只有 76.4（`cli/http_config.py` + `cli/http.py`）；76.1/76.2/76.3/76.5 纯测试增量；76.6 文档与基线（五份零 diff）。
- 实跑：`pytest tests/network tests/test_cli_http_lifecycle.py -q` = **746 passed**；`contract_snapshot.py --check` = 五份 `[OK]`；`grep -n "路径派生"` 两文档各 1 处命中。

## 发现

| # | 严重度 | 位置 | 现象 | 正确口径 | 处置 |
|---|---|---|---|---|---|
| 1 | Medium | epic R2「项目已有在途 run 回 `project_busy`」vs `ws_commands._submit_run` | WS 提交链上「同一项目已有在途」真实回的是 **`run_conflict`**（会话级冲突；WS 不带 `session_id`、恒续最近会话），`project_busy` 只由**删项目端点**产生。判据用桩端口制造 `project_busy` ⇒ 票面该子句在生产链上不成立 | R2 应写成「项目内占用的判据 = `run_conflict` 逐字透传；`project_busy` 属 HTTP 删项目面」。Requirements 冻结，记 epic Notes 裁定 | 记 Notes（`bad_spec`） |
| 2 | Medium | epic R6 只写 `external`；`_warn_external_without_sandbox` 也只判 `mode == "external"` | `lan` 档（**无认证**、明文、同网段任何设备可提交）在宿主执行时**完全不告警** —— 风险比 external 更高（少一层 token），却没声音 | R6 的字面只覆盖 external（不重切），但缺口要显式登记：`lan` + 非 docker 的告警是**已知缺口**，转 `brief.md` 延期项，由用户裁定是否补 | 进延期项 |
| 3 | Medium | `cli/http.py:879`（`http_server_cmd` 的回落链） | 回落链 `_effective_sandbox_backend(handler) or sandbox or settings.sandbox_backend`：`handler.engine` 未建时（`handler` 形态差异）取的是**请求值**而不是生效值 ⇒ 请求 `docker` 但引擎没建起来时**不告警**，而实际远端 run 会落在宿主 | 取不到生效值时宁可**照请求值喊**（提示不是闸门，多喊一条比静默好）；或让回落值参与文案（`sandbox=docker(requested)`) | 进延期项（低概率路径，需先确认 `engine` 何时为空） |
| 4 | Medium | `tests/network/test_ws_remote_flow.py`（76.5 全用 fake 端口） | 「ADR-005 验收基线一次跑通」仍在**端口替身**上完成：真 listener + 真 `HttpRunService` + 真 `AgentLoop` 的端到端未验（E75 R1 M-4 登记的同一缺口） | 端到端用例是 Step 08 / 后续 epic 的活；本 epic 范围内不扩 | 进延期项（承 E75 R1 M-4） |
| 5 | Low | `tests/test_cli_http_lifecycle.py`（76.4 三例） | 三例都直接调 `build_ws_servers`，**入口层是否把 `sandbox_backend` 传下来**原先无断言（回落链会让「没传」也能过） | 断言 `build_ws_servers` 的 kwargs 含 `sandbox_backend` | **当轮落改**：`_assert_single_adapter` 增一行（两条装配路径都跑到，17 passed） |
| 6 | Low | `cli/http.py:121`（`_serve_web` 的公告） | 同一次启动的两条公告口径不一致：`_serve_web` 打印的 `[ws] listening on …` 不带沙箱提示，`EmbeddedHttpService.start` 的 `[ws] event stream …` 带 | 两处共用同一个 note（`_serve_web` 拿不到生效档，需从 `ws_server` 或参数传） | 进延期项 |
| 7 | Low | epic R7「4 份契约快照」 | 实测是 **5 份**（含 Epic 70 的 `error_codes.json`），plan 已按 5 份记 | 口径按实测；R7 冻结不改 | 记 Notes（口径差） |

## Requirement 对账表

| Req | 交付证据 | 结论 |
|---|---|---|
| **R1** 两项目并发不串味 | `test_ws_project_admission.py:195`（并发提交 + `run_id` 交叉 0）、`test_ws_remote_flow.py:291` 第②③步（两条订阅流对位 + 归属交叉 0） | 已交付（端口替身；端到端进延期项） |
| **R2** 名额双层且参数不动 | `test_ws_project_admission.py:226/250/292`（`project_busy` / `total_inflight_limit` vs `run_conflict` / 三码不占名额）；`grep MAX_INFLIGHT\|Semaphore` = 0 | 部分（票面 `project_busy` 子句与生产链不符，见发现 1） |
| **R3** cursor 续流不丢 | `test_ws_resume.py:133`（首帧 ≤ N+1 且连续）、`test_ws_remote_flow.py:291` 第⑤步（两段拼接 == 1..终态） | 已交付 |
| **R4** 窗口不足必响 + 已清理具名错 | `test_ws_resume.py:167`（帧序恰 `["error"]`）、`:217`（`unknown_run` 非空流） | 已交付 |
| **R5** 远程可见面不扩张 | `test_ws_protocol.py` 的集合相等 + 词根守卫（WS 面五模块 0 命中）+ 复跑 403 / `tool_error` 留痕 | 已交付 |
| **R6** external + 非 docker 恰 1 条 | `http_config._warn_external_without_sandbox` + `tests/test_cli_http_lifecycle.py:600/619`（1 条 / 0 条）+ 落改的入口注入断言 | 已交付（`lan` 档缺口进延期项） |
| **R7** 契约与文档收口 | `--write` 零 diff + `--check` 五份 `[OK]`；`docs/errors.md` / `docs/framework.md` 的客户端对接口径与启动告警族；`mkdocs --strict` 0 warning | 已交付 |

## 结论

**有条件的通过**：Critical 0 / High 0 / Medium 4 / Low 3。发现 1 / 7 记 epic Notes（规格口径），发现 2 / 3 / 4 / 6 进 `brief.md` 延期项，发现 5 当轮落改并复跑（17 passed）。
