---
type: review
code: E76-R3
epic: epic-76-remote-surface-closeout
review_loop_iteration: 0
lens: code_review 三镜头（对抗 / 边界 / 验证缺口）
reviewed_at: 2026-11-23
head: 3ef5be81
---

# E76 收口三审 · R3 代码评审（三镜头）

## 镜头一：对抗式（找「缺什么」）

| # | 严重度 | 位置 | 缺什么 | 处置 |
|---|---|---|---|---|
| A1 | Medium | `http_config._warn_external_without_sandbox` | 只覆盖 `external`；`lan`（无认证 + 明文 + 可提交 run）在宿主执行时**零告警** | 延期项（R6 冻结不含 lan，需用户裁定补喊） |
| A2 | Medium | `http.py:879` 回落链 | `handler.engine` 为空时回落**请求值**，请求 `docker` 而未生效时不喊 | 延期项（需先确认 engine 为空的触发条件） |
| A3 | Medium | `tests/network/test_ws_remote_flow.py` | 五步串跑全在端口替身上；真 listener + 真服务未验 | 延期项（承 E75 R1 M-4） |
| A4 | Low | `_serve_web` 的 `[ws] listening on …` | 不带沙箱提示，与 `EmbeddedHttpService.start` 的公告不同口径 | 延期项 |
| A5 | Low | `test_ws_protocol.py` 词根守卫 | 用**子串**匹配能力族（`write`/`delete`/`remove`），未来正当符号（`writelines`/`removeprefix`）会被判红，可能逼人放宽守卫 | 已记；若真触发再改词根为「动词 + 边界」 |
| A6 | Low | 告警计数判据 | 按「消息里出现锚点」计数，若将来两条日志合并成一条，计数仍 1 而看不出 | 已记 |

## 镜头二：边界

- `sandbox_backend=None` + `settings.sandbox_backend="auto"` ⇒ 文案 `sandbox=auto`，会喊（正确：auto 在 daemon 不可用时降级宿主）。
- `sandbox_backend=""`（空串）⇒ 文案 `sandbox=unknown`，**仍会喊**（诚实，不静默）；无用例，低风险。
- `mode == "lan"` / `"local"` ⇒ 直接 `return None`（A1 的同一处）。
- cursor 边界（`0` / 未来值 / 非数字）由 `_parse_cursor` 与 E75 用例覆盖，本 epic 未改该函数。
- 项目通道 `project_id` 归属、`unknown_run`、`shutting_down` 三路错误帧均由 E74/E75 既有用例钉住。

## 镜头三：验证缺口

- **已在当轮闭合 1 条**：验证 R6 判据取的是「生效档位」而非「请求值」——`_assert_single_adapter` 增 `assert "sandbox_backend" in calls[0]`，两条装配路径（`EmbeddedHttpService` / `http_server_cmd`）都跑到，`tests/test_cli_http_lifecycle.py` = **17 passed**。
- 未闭合（均已转延期项）：真 listener 端到端（A3）、`lan` 档告警（A1）、engine 为空的回落（A2）。
- 门禁实测：`pytest tests/network tests/test_cli_http_lifecycle.py -q` = 746 passed；`contract_snapshot.py --check` 五份 OK；`mkdocs build --strict` 0 warning。

## 结论

**通过（有条件）**：未见 Critical / High；Medium 3 条全为「规格边界或端到端缺口」，已登记延期项，不阻塞本 epic 收口。
