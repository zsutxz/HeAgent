# Story 50-7 验收：Epic 50 周期验收（brief §9 逐条）

- 日期：2026-09-24
- 基线提交：`4193eac`（Story 50-7 开工时 HEAD）
- 环境：Windows / Python 3.13.5 / Chrome 153.0.8010.48；`pytest` 默认参数（跳过 integration / benchmark）
- 结论：**§9 的 9 条全部有可复现命令与实测输出**；全量质量门与真实浏览器验收同时通过

> 口径：每条给出**命令 + 实测输出**；跨条重复引用的命令只在其首次出现处展开。所有数字均为当场实测，
> 没有估算值；命令行可在仓库根直接复现。

## 逐条（brief §9）

| # | 验收点（brief 原文要点） | 命令 | 实测输出 | 结论 |
|---|---|---|---|---|
| **1** | 两项目交替操作，会话 / 项目级记忆 / 运行状态归属正确；A 的请求不能误读或修改 B 的会话 | `pytest tests/network/test_http_console_e2e.py -q` | `9 passed`（含 `…cannot_touch_another_projects_sessions`：跨项目读取/重命名/删除均 404 `unknown_session`、B 的会话文件字节不变；`…loop_cannot_read_another_projects_files`：**真实工具路径** `file_read` 读 B 的绝对路径返回 `tool_error=True` 且 B 的文件内容一个字未进事件流）<br>`pytest tests/network/test_http_console_sessions.py tests/network/test_http_console_projects.py -q` → `41 passed` | ✅ |
| **2** | 已保存会话在刷新浏览器 / 重启服务后仍可列出、打开、继续；消息顺序与工具调用/结果配对完整 | `pytest tests/test_http_web_ui.py tests/test_config.py -q` → `206 passed`（含探针用例 A「同名工具两次调用按序配对」）<br>`node tests/js/console_acceptance.mjs` → **`ACCEPTANCE {"rows":18,"failed":0}`**（A8 刷新后仍在项目 B 且会话 id 不变；A9/A10 重命名与删除作用到磁盘会话文件） | 真浏览器 18 行清单：A8 刷新持久化、A9 重命名落盘、A10 删除磁盘文件 2→1 | ✅ |
| **3** | 切换项目不改变既有运行绑定；停止 / 重连 / 会话删除定位准确，冲突有明确结果 | `pytest tests/test_cli_http.py tests/test_http_agent_api.py tests/test_http_security.py tests/network/test_http_server.py -q` → `128 passed`（含 `test_delete_cancels_a_real_run`、`test_disconnect_does_not_cancel_the_run`、每项目独立 loop）<br>探针用例 F：切走时只断本页 SSE、**不取消**在途运行并留常驻提示 | 真浏览器 A7（B 的会话 1 个 / 服务工作区 0 个，无交集） | ✅ |
| **4** | 四级配置来源与新运行解析一致；移除项目覆盖后正确显示回退值与来源 | `pytest tests/test_config_catalog.py tests/test_config_write.py tests/network/test_http_console_config.py -q` → `216 passed`（`TestSourceSolve` 逐层：默认 / 全局 / 项目覆盖 / 系统环境变量优先 / 移除行后回退；`test_values_match_a_directly_constructed_settings` 把面板与直接构造的 `Settings` 对齐） | 真浏览器 A11：20 组 / 113 条 = 后端 113 字段，来源 `default + global_env + project_env` 三种徽标同时出现 | ✅ |
| **5** | 开关关闭 / 非允许来源 / 未知键 / 非法值 / 凭证键 / 外部修改冲突均**显式失败**，原配置保持完整 | 同上 `216 passed`（`TestGate` / `TestWhitelist`（23 个只读类键逐条）/ `TestValueValidation`（26 条非法值）/ `TestConflict`（指纹冲突与并发唯一胜者））<br>`pytest tests/network/test_http_console_e2e.py -q` → `9 passed`（含 T2：非回环来源在**登记 / 移除**上收 403 + **注册表逐字节不变**；`test_closed_gate_keeps_the_config_surface_read_only_but_runs_still_work`：闸门关闭时 PUT ⇒ 403 且 `.env` 字节不变） | 真浏览器 A14（非法值文案 + 文件 115 字节未变）、B1（闸门关闭：0 个可编辑控件） | ✅ |
| **6** | 保存成功后当前运行保持旧快照、下一次运行用新值；API 与 UI 如实表达生效时机 | `pytest tests/test_cli_http.py -k next_run -q` → 见上行 `128 passed` 中的 `test_write_channel_applies_on_the_next_run_only`（旧 loop 快照仍是 5、下一次解析出 42；响应 `applied=next_run`）<br>探针用例 H/N：结果区显示「下一次运行生效」且写后条目**就地**刷新 | 真浏览器 A13：`25 → 321`（磁盘 + 面板），来源转为 `project_env`，状态行「已保存：下一次运行生效」，磁盘备份 1 个 | ✅ |
| **7** | 配置响应 / 错误 / 日志 / 审计不出现密钥明文（覆盖短密钥、多密钥与备份访问的负向验证） | `pytest tests/network/test_http_console_e2e.py -q` → `9 passed` 中的 `test_no_credential_leaks_across_five_faces`：短密钥 `sk-SHRT1234` + 多密钥 `sk-POOLAAAA,sk-POOLBBBB` 在**配置响应 / 三类错误信封 / SSE 帧 / 全部日志记录 / 审计 JSONL** 五面逐一排除性断言；审计里只留 sha256 与长度<br>同文件 `test_backups_and_the_audit_log_have_no_download_endpoint`：4 个候选下载路径全部 404 | 真浏览器 A12：页面文本 / `documentElement.outerHTML` / 凭证行三处都没有标记，凭证行只有「已配置 \*\*\*\*\*\*\*\*」 | ✅ |
| **8** | 移除项目登记保留目录与数据；删除会话需要确认，不能静默覆盖正在进行的写入 | `pytest tests/network/test_http_console_sessions.py tests/network/test_http_console_projects.py -q` → `41 passed`（含 `session_busy` 拒删在途会话、`confirm_required`、`project_not_removable`）<br>探针用例 J/K：删除会话与移除登记都走二次确认，文案写明「删文件 / 保留目录数据」 | 真浏览器 A10（先取消后确认：取消保留、确认后文件消失）、A5/A6（登记与目录失效标记） | ✅ |
| **9** | Epic 49 的流式 / 工具活动 / 停止 / 重连 / 来源校验无回归；入口限制在 UI 与文档中可见 | `pytest tests/test_cli_http.py tests/test_http_agent_api.py tests/test_http_security.py tests/network/test_http_server.py -q` → `128 passed`（49 的 SSE / 取消 / 重连 / 同源防线用例原样全绿）<br>`pytest tests/network/test_http_console_e2e.py -k same_three_facts -q` → `1 passed`（非回环告警与 UI 常驻声明**同口径**：无认证 / 无 TLS / 非安全边界；`exposure_warning` 含「loopback client is not trusted either」）<br>文档：`docs/frame.md` 4.18 + 配置表 2 行 + 五 的新增缺口 | 真浏览器 18/18（含 A2 无第三方请求、A3 无 CSP 违规、A15 窄屏降级） | ✅ |

## 全量质量门（T11 实测）

```bash
$ python -m pytest -q --cov=heagent --cov-fail-under=87 --cov-report=term
TOTAL                                          12887    865   3506    390    92%
Required test coverage of 87% reached. Total coverage: 91.82%
3057 passed, 11 skipped, 18 deselected, 8 warnings in 189.36s (0:03:09)

$ ruff check src tests            → All checks passed!
$ ruff format --check src tests   → 277 files already formatted
$ mypy src                        → Success: no issues found in 146 source files
$ mypy src --platform linux       → Success: no issues found in 146 source files
$ node tests/js/console_acceptance.mjs
ACCEPTANCE {"rows":18,"failed":0,"workspace":"C:\\Users\\skype\\AppData\\Local\\Temp\\heagent-console-acZEgv","chrome":"Chrome/153.0.8010.48"}
```

覆盖率口径说明（R1 / 脊柱 D7 的实现期校正）：脊柱 §10 与 D7 预判控制台逻辑会拆到独立模块
`cli_console.py` 并「默认不 omit」，但该模块**从未落地** —— 控制台装配全在 `cli_http.py`，
而它**不在** `pyproject.toml` 的 omit 列表里（`omit` 只有 `*/gui/*` 与五个 CLI 交互层文件）⇒ 它计入
上面的总量并由测试覆盖。未新增任何 omit。

## 负向验证（DoD 四条 + 2 条凭证面）

`.heagent/tmp/mutate_50_7.py`，6 条变异全部**精确变红**后复原（每条回退后 sha256 与变异前一致）：

| 变异 | 目标 | 实测 |
|---|---|---|
| ① 网络层 `from heagent import projects` | `tests/test_architecture_contracts.py` | `1 failed`（`test_no_reverse_dependency_on_agent`） |
| ② 往写白名单塞 `KIMI_API_KEY` | 契约 + catalog | `3 failed`（含 `test_write_whitelist_is_a_subset_of_settings_and_holds_no_credentials`） |
| ③ 从 `.env.example` 删一个字段名 | `tests/test_config.py` | `1 failed`（`test_every_settings_field_is_documented_in_env_example`） |
| ④ 把非回环来源判定短路 | e2e + console 测试 | `5 failed`（含本 story 的 T2 用例） |
| ⑤ 面板回传凭证**原值** | e2e + catalog | `5 failed`（含 T3 五面用例） |
| ⑥ 审计写**原值**而非哈希 | e2e + write | `2 failed`（含 T3 审计断言） |

## 已知缺口（如实登记，见 `docs/frame.md` 五 与活动台账）

①网页入口非安全边界（无认证 / 无 TLS）；②全局 `~/.heagent/.env` 永久只读；③配置改动只对下一次 run
生效（无热生效）；④UI 无自动化回归（真浏览器清单只能手动跑）；⑤备份与审计不被工具读取、也无下载端点，
但仍在宿主文件系统上且**未加密**；⑥`cli_console.py` 从未落地（D7 作废，口径随模块走）；
⑦「只读」不是安全边界；⑧**「回环来源」不等于安全**——用户自己浏览器里打开的任意网页 peer 同为
`127.0.0.1`，真正的同源防线是 49-5 的 `Origin`/`Host` 校验；⑨跨项目并发无全局软上限
（在途 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`，默认最多 32；`HTTP_MAX_CONNECTIONS` 不随项目数放大）。
另：**非回环运行姿态未裁决**（项目重命名 / 四个会话写操作 / 项目内运行入口当前无回环门），
台账中标 `blocked` 待人裁决，本 story 未擅自改。
