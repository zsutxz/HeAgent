---
epic: epic-71-web-server-status
date: 2026-11-19
verdict: accepted-with-open-items
criteria: declared
headless: false
---

# Epic 71 Retrospective

> 路径约定：`tickets/story-71.*` 均相对 `_bmad-output/initiative-heagent/tickets/epic-71-web-server-status/`；
> 其余路径相对仓库根。实测为收口现场取证（2026-11-19，容器内 `.heagent/tmp/py311-venv-linux/bin/python`）。

## Epic summary

**Epic**：epic-71-web-server-status（R10 / R13；6 story，全部新建）

**票态**：6/6 `done`，无 `dropped`。

| Entry | 交付 | 提交 |
|---|---|---|
| 71.1 状态协议与聚合端点 | 只读 `GET /api/status`：`StatusResponse`（`extra="forbid"`）+ `StatusSource` Protocol + 端点闭包（来源异常 → 500 固定文案）+ 入口层适配器注入 | `98928cb4` |
| 71.2 部署面视图 | 请求时读 listener 实际端口、`ListenerMode`、TLS、沙箱档位、写入闸门、`ACTIVE_PROVIDER`、路由池档位名（只报名字与布尔） | `6345abd1` |
| 71.3 uptime 与依赖态 | `HttpServer.start()` 成功后记单调钟 + UTC 墙钟；cron 作业 / 技能数 / 记忆条数走来源侧 5 秒缓存 | `e06be7b0` |
| 71.4 进程资源采样 | `network/proc_stats.py`：Linux `/proc`、Windows `ctypes`，零新增依赖，不可采样即 `unavailable` + 三 `null` | `ef0d23cc` |
| 71.5 请求计数与延迟 | `RequestMetrics` + `_AccessLogMiddleware` 就地记账（整数自增 + 有界延迟窗口），`/api/status` 只读快照 | `c0acda0c` |
| 71.6 网页端面板与徽标 | `web/status-panel.js`：顶栏徽标 + 懒加载五组页签面板，展开才轮询、收起/隐藏即停、失败保留上次值；白名单与文档同步 | `14f237fc` |

## 收口时补的三件事（review 轮）

**① 6 条 story 全部跑完两个镜头**（`edge-case-hunter` + `verification-gap`，12 个独立子代理），
按 triage → route 落地：**14 个 patch 当场修掉**（含 2 条 decision 按裁定落地）、**11 条 defer 折进 A74**、
**33 条 rejected**（含 12 条 `false` 与 9 条 `low`）。逐条正文写进各 plan 的 `## Code Review` 节。

**② 当场修掉的实质缺陷**（都有判据）：

| 缺陷 | 位置 | 判据 |
|---|---|---|
| `/provider` 运行期切换后状态仍报启动时的 provider | `cli/http_status.py`（装配期抄字符串） | `test_active_provider_is_the_live_instance_not_a_snapshot` |
| `jobs[:32]` 截断先于畸形条目过滤 ⇒ 正常作业被坏条目挤掉 | `cli/http_status.py::_cron_jobs` | `test_a_malformed_entry_is_dropped_instead_of_failing_the_whole_status`（已有）+ 顺序修正 |
| `/proc` 截断 / `SC_CLK_TCK=0` 抛 `IndexError` / `ZeroDivisionError` 穿透成 500 | `network/proc_stats.py` | `TestProcessResources`（捕获元组扩到 5 类） |
| 半开连接时面板永久卡在「取数中」（`fetch` 不 settle） | `web/status-panel.js` | `REQUEST_TIMEOUT_MS` 的 `Promise.race`（探针待 A74） |
| 面板未标注依赖态统计范围（epic 残差要求） | `web/status-panel.js` | 依赖组首行「统计范围: 本进程工作区」 |
| 沙箱档位报请求值（`auto`）而引擎已降级成 `passthrough` | `cli/http.py` 两处装配点 + `cli/http_status.py` | `_effective_sandbox_backend` 取 `sandbox_decision.effective_backend`；3 条用例（`http-server` 命令 / 内嵌入口 / 助手本身） |
| SSE 连接寿命被当成「请求延迟」计入 p50 / max | `http_server/metrics.py` + `middleware.py` | `is_event_stream()` 判定 → `record(streamed=True)` 只计总数；`test_streaming_response_is_counted_but_kept_out_of_the_latency_window` |

**③ 补强的判据**（原用例「看起来覆盖了、其实不红」的 7 处）：档位上限用例 17 → 100 条（截断切片此前恒 no-op）、
p50 中位数（取 `ordered[0]` 也过）、16 码截断（此前只造 1 个码）、`status=0` 中止请求（中间件不许自己抛）、
`threads` 数值断言、损坏 `jobs.json`、依赖态缓存**用假时钟**驱动过期（原先手动清缓存）。

## 门禁实测

```text
pytest -q                                   → 5441 passed / 51 skipped / 30 deselected / 1 xfailed（0 failed）
pytest tests/test_http_status_api.py \
       tests/test_web_server_status_panel.py \
       tests/test_http_web_ui.py \
       tests/test_cli_http.py tests/network   → 899 passed / 34 skipped
ruff check src tests                        → All checks passed
ruff format --check src tests               → 475 files already formatted
mypy src                                    → no issues in 233 source files
mkdocs build --strict                       → 0 warning
```

## 教训

- **「静态契约」不是行为验证**。71.6 的 6 条用例全是源码子串/结构断言，`status-panel.js` 从未被执行过；
  删掉 `void loadStatus()`、去掉 `shouldPoll` 的 `open` 条件、把失败分支写反，全部照绿。计划里写的
  「node 探针覆盖行为」在本仓是不存在的（`app_probe.js` 只加载 `app.js`）——**引用既有探针前先确认它加载的是哪个文件**。
- **守卫也要有判据**。71.6 的字段覆盖守卫是「字段名出现在文件任意位置」，实测 29 行里 12 行删掉仍绿
  （`active_runs` 被徽标里的同名字符串遮蔽、`failed` 被 `dataset.state = "failed"` 遮蔽）。守卫的作用域应与它保护的结构同粒度。
- **上限类断言必须真的越界**。71.2 的「超量档位」用例造 17 条而字段上限是 64，等于没测；这类用例的
  数字应从常量派生（`_MAX_TIERS + 1`）而不是手写。
- **缓存过期必须由时钟驱动**。71.3 原用例用「手动清缓存」代替时间推进 ⇒ 常量从 5 秒改成 3600 秒也绿；
  假 `time.monotonic` 是这类测试的标准形态（本仓已有先例）。
- **「实际档位」与「请求档位」是两个事实**。`SANDBOX_BACKEND=auto` / daemon 不可用时引擎降级为 `passthrough`，
  而状态面报 `auto` —— 安全姿态类字段宁可多报一列，也不要只报意图（见 A74 / 待裁定项）。

## 残差与待裁定

- **A74（新增，`active`）**：Epic 71 review 的证据补齐批（11 条 defer）——前端执行级探针、真实来源的请求计数映射、
  两处 provider 接线与 `_clip` 上限、`http-server` 装配点依赖态、fail-soft 降级、`/proc` 失败路径与 Windows 分支、
  `/proc` 文本固定、字段覆盖守卫作用域、关闭后 `uptime_seconds` 自洽、`_read_windows` 的 ctypes 签名。
- **两项 design 裁定已于同日落地（用户「按推荐」）**：① 沙箱档位改报**生效值**（`_effective_sandbox_backend` 取 `sandbox_decision.effective_backend`，两处装配点「生效优先、取不到回落请求值」）；② SSE 响应只计总数与错误码、**不进延迟窗口**（`metrics.is_event_stream` 按 content-type 判定）。判据：`test_effective_sandbox_backend_is_read_from_the_engine_decision` / `test_embedded_wiring_prefers_the_engine_effective_backend` / `test_http_server_command_wires_the_status_source` / `test_streaming_response_is_counted_but_kept_out_of_the_latency_window`。
- 既有残差不变：网页进程不启动 cron 调度器（只报 `jobs.json` 与 `last_run`）、多项目 `jobs.json` 分散、
  无 node 时前端行为无回归。

## Open questions

1. 前端行为回归是否值得为「无 node 环境」提供第二通路（如纯函数导出 + Python 侧 `jsonschema` 式断言）？
2. `/api/status` 每次请求都读两次 procfs（微秒级）——是否需要与依赖态同款的缓存，把「每请求采样」也收敛成 5 秒？
