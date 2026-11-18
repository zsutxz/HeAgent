# Changelog

本文件记录 HeAgent 的对外可见变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号使用纯 `X.Y.Z`（0.x 阶段 **minor 即破坏性变更**，发布流程见 `deploy/README.md`）。

约定：

- `## [Unreleased]` 段常驻，下一个版本的改动先写这里；
- 每个已发布版本一节，标题形如 `## [0.9.0] - 2026-11-11`；
- 发布前先 bump `pyproject.toml` 与 `src/heagent/__init__.py`（两处必须一致），
  再把 `Unreleased` 的内容落成版本节 —— 这三点由 `tests/test_release_workflow_contract.py` 守住。

## [Unreleased]

### Changed

- 日志装配收敛：CLI 与 GUI 的 `basicConfig(format=…)` 改为 `make_formatter(settings.log_format)`，行格式只在 `pub/log_config.py` 定义一次（默认 text 输出逐字不变）。
- `release` job 增加 `if: failure()` 的失败摘要 step：写入 `$GITHUB_STEP_SUMMARY`（失败版本号 + 「PyPI 是否已占用该版本」「两处版本真源是否一致」两条重跑前必核事项 + run 链接），通知通道复用 GitHub 自带的工作流失败邮件，不引入外部 webhook secret。
- 网络层单源化清理批（A54 网络族，行为保持型）：WS run 订阅与 SSE 的「快照重放 + 水位去重」收敛到 `http_protocol.replay_then_follow` 唯一实现——WS 侧终态判定随之改为**快照时刻捕获**，微竞态窗口内客户端改收终态事件而非裸关闭（对齐 AD-4「终态事件先于流结束」）；`resync_required` 判据算术单源 `http_protocol.cursor_out_of_window`（run/SSE/CLI 旁路/通知流四处共用）；WS 连接登记与有界关停收敛到 `event_stream_hub.WsRegistry`（`HttpRunService` 组合接入，其关停日志去掉 `close_code` 字段与 hub 口径统一）；ws_server 四条端点构造器的公共骨架（握手门→accept/hello→关停检查→会话体→异常收敛→有界收尾）收进 `_ws_session`，日志事件名逐字节保持。
- 内部单源化清理批（行为零变化，判据全绿）：词级判重公式三份拷贝收单点（`compact.word_overlap_duplicate`，`FactStore.add` 反向复用）；归档小节构造与字节账收敛到 `auto_archive._append_archive`/`_fact_line_bytes`（`compact._append_archive_section` 退化为薄委托）；`auto_archive` 跨进程节流改用 `pub.persist` 的 `stamp_is_recent`/`touch_prune_stamp`（与 store/ledger/housekeeping 同一节流序列）；`EngineContainer` 两处 prune 同构孪生收敛 `_prune_gate_once`（日志文案逐字节不变）；`setup_ws_external` / `envscan` 改用 `envfile.replace_or_append` / `envfile.fingerprint`。
- 代码门禁范围扩到 `examples/`：`ruff check` / `ruff format --check` 的路径面加入 `examples`（CI、pre-commit、`scripts/quality_gate.py`、`docs/testing.md` 同步），示例代码漂移不再静默；`examples/**` 只放行 RUF001/002/003（全角标点是中文示例的写作约定），其余规则与 `src` 同标准。`mypy src` 仍不含 `examples`。
- `/help` 渲染面（列表版 / 详情版 / 未知命令建议）自 `cli/interactive.py` 拆到 `cli/help_view.py`：纯展示模块，注册与派发仍在 `interactive.py`，`/help` 输出逐字不变。

### Added

- **结构化日志**（Epic 65 / R13）：`LOG_FORMAT=json` 时日志行改为单行 JSON——`timestamp`（带本地时区偏移、毫秒）/ `level` / `logger` / `message`，`extra=` 注入落 `context`，异常落 `exc_info`；实现单点 `pub/log_config.py`，CLI（stderr+文件）/ GUI（文件）/ HTTP（复用 CLI）三个装配点共用。默认 `text`，与历史输出逐字一致（`runtime_stats` 的按行解析不受影响）；非法取值在加载期失败（`Literal` 校验）。
- **调试模式**（`DEBUG_MODE=true`）：日志级别强制 `DEBUG`（打开既有的入参与中间量插桩），CLI 错误出口在既有三段之后追加 `Traceback (DEBUG_MODE=true):` 段；无异常在飞时不追加假 traceback。默认关，不改任何安全面。
- **性能分析脚本** `scripts/profile_run.py`：标准库 `cProfile` 剖面任意模块或脚本（`--` 之后参数原样透传），报告含按 `tottime` 排的热点函数与按 `cumtime` 排的调用表，默认落 `.heagent/tmp/profile-<时间戳>.txt`；目标崩溃仍留报告，`SystemExit` 如实转成退出码。
- **开发容器** `.devcontainer/`：Python 3.11 基础镜像 + `postCreateCommand` 安装 `.[dev,gui,http]` 与 pre-commit 钩子，转发 9101/9201/9301 三条 listener 默认端口（由 `tests/test_devcontainer_contract.py` 钉住与 `Settings` 默认值一致）。
- **CI 门禁一致性契约** `tests/test_ci_gate_parity.py`：本地 7 门 ↔ CI job 的显式映射（加门不接线即红）、PR 触发面与分支过滤守卫、integration 仅 `workflow_dispatch`、`release` 失败摘要存在性。
- **PostToolUse hook 的 stdout 进对话上下文**（活动台账 A53）：非空 stdout 以 `[PostToolUse hook output]` 附注追加到工具结果——不改工具正文、不落成用户消息（hook 输出不获得用户指令权重），注入点在 ledger 记账之后（幂等缓存只存原始工具输出）；预算为单条 ≤2000 / 单次调用累计 ≤4000 字符，超限打显式截断标记。
- **重启后的运行事件回放**（活动台账 A35）：`EVENTS_ROLLOUT_ENABLED=true` 时 `GET /api/runs/<id>/events` 在进程内无该记录时从 `<项目根>/.heagent/runs/<id>/rollout.jsonl` 一次性回放（响应头 `x-heagent-replay: rollout`，支持 `Last-Event-ID`），旧 run 在页面刷新后不再只剩 404。回放是粗粒度的且如实标注：rollout 不记工具输出原文、不记文本增量（最终答案仍完整）。
- **全局级 MCP 注入签名入口**（活动台账 A36）：`<用户 home>/.heagent/injection_signatures.json` 现已**真的加载**，与项目级合并（全局作底、同名 `pattern` 项目级覆盖），坏条目报错带来源；此前该文件只触发一条「被忽略」告警。
- `tests/test_architecture_contracts.py::test_source_files_stay_under_the_line_ceiling`：`src/heagent/**/*.py` 单文件 ≤1000 行的常驻门禁（超限点名文件与行数）。Epic 62 的「单文件均低于 1000 行」Outcome 此前只有手工 `wc -l` 记账、无判据。
- web_search 内建工具（Epic 61）：按主题检索发现新 URL。引擎可插拔（`WEB_SEARCH_ENGINE`，默认 Tavily）；无密钥工具常在、调用显性报错（`WEB_SEARCH_API_KEY`）；条数/摘要/title/url/汇总四层确定性预算 + `guard_content` 注入围栏；dreamer 与主 loop 同面开放。
- `RunStore.close_stale_running`：把陈旧 running 快照收尾为 FAILED（崩溃进程遗留的 running 不再污染统计；`updated_at` 保持末次真实活动时刻，不回填时钟）。已接线：新 run 启动时自动触发一次（去重），阈值 `RUN_STALE_IDLE_HOURS`（默认 6h，0=禁用）。

### Fixed

- `ProviderChain` / `KeyRotatingProvider` / `SwitchableProvider` 的 `send` 不再持锁跨网络 I/O（与 stream 同口径：锁内快照索引，调用不持锁），并发 LLM 调用不再被串行化。
- `RunStore.build_run_tree` 改为单次线程卸载批量读取、只校验 `context`，万级快照下运行树查询不再逐个解析整份快照。
- 池内回退纳入 404 model 不可用：失效档位由池内兄弟模型接管（判据 `is_pool_fallback_error`；同步覆盖 OpenAI 兼容端点的 "does not exist" 措辞）。

## [0.9.0] - 2026-11-11

### Changed（破坏性）

- **斜杠命令硬改名**：`/route` → `/model`（路由池档位切换），`/model` → `/provider`（provider 切换）。
  两个旧名**都不注册、无别名** —— 输入旧名不会报错，会被当作普通 prompt 交给 `AgentLoop`
  （静默多花一次 LLM 调用）。迁移时把脚本与笔记里的 `/route` 改成 `/model`、旧 `/model` 改成 `/provider`。
- **`config/catalog.py` 拆为子包**：1350 行单文件 → `config/catalog/` 9 个文件（最大 307 行）。
  公共名 `heagent.config.catalog` 与 `__all__` 的 34 项**零变化**，子模块属内部实现细节。

### Added

- **契约基线第四份** `tests/contract_baselines/transport_errors.json`：35 个错误码的
  `status` / `code` / `keys`，配套「错误码只增不减」（INV-8）与信封键集冻结守卫。
- **WS 路由进快照**：`transport_routes.json` 从 21 条增至 25 条，补上 `/api/runs/ws`、
  `/api/runs/{run_id}/ws`、`/api/cli/ws`、`/api/notifications/ws`。
- `scripts/contract_snapshot.py --print --only <kind>`：打印当前快照、不落盘、不比对。
- **文档构建严格门**：新增 `mkdocs.yml`，CI 的 `lint` job 加 `mkdocs build --strict` step（不新建 job）。
- **发布契约断言** `tests/test_release_workflow_contract.py`：release job 的触发面 / `environment: release` /
  `id-token: write`、job 数恒 8，以及**版本号单一真源**（`__version__` == `pyproject.toml`，
  HEAD 带 `v*` tag 时 tag 必须等于版本）。
- **传输层零文档 URL 守卫** `tests/network/test_transport_no_doc_links.py`：`src/heagent/network/**`
  的字符串常量不得出现 `/docs/`、`mkdocs`、`readthedocs`。
- `deep-research` 技能：特定主题深度调研。
- WS 连接首帧 `hello` 下发服务器版本。

### Fixed

- 契约基线的描述措辞跟上第四份快照（`scripts/quality_gate.py` 第 0 门注释、`tests/test_contract_baselines.py` docstring）。

### 未回填说明

**0.9.0 之前的历史版本未逐条回填**：本文件 2026-11-11 才建立，早期版本的发布日期与条目分类无法从仓库
可靠重建（记错日期或臆造分类比留白更糟）。需要追溯时用 git 历史，它才是那些版本的权威记录：

```bash
git log v0.3.0..HEAD --oneline          # 自最后一个 tag 起的全部提交
git log --oneline --grep="!:"           # 破坏性变更
git log --oneline --grep="^feat"        # 新特性
```
