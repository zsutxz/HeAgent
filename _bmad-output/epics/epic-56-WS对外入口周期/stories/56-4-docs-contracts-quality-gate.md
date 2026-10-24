---
title: '56-4 文档、契约与质量门'
type: 'feature'
created: '2026-10-24'
status: 'done'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: 'a08ea29'
context: []
---

<!-- 交付物与验收边界 = epics.md 56-4 行；含 Epic 53/54 retro 挂给本周期会话的 3 条 action item。 -->

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 56-1/56-2/56-3 把拓扑、认证与提交能力改完了，但文档面仍是拆分前的口径（`frame.md` 4.17
仍称 WS 挂在 HTTP app、配置表缺 TLS 两行、`README` 只写 HTTP 入口），部署文档没有端口迁移与对外模式
说明，`AGENTS.md` 的安全声明仍按「WS 无认证」一刀切；同时 Epic 53 / 54 retro 挂给本周期会话的 3 条
action item（F4 关停面裁定、F5/F6 测试缺口、硬化旗标负向变异）尚无处置证据。

**Approach:** 以**可执行判据**收口：把双 server 拓扑、三条 WS 端点、本地/对外两档语义写进 `frame.md`
4.17/4.18 与配置表；`README` + `deploy/README` 写端口迁移与对外部署（token 在用户级 `setting.md`、TLS、
Epic 53 沙箱档强烈建议）；`AGENTS.md` 安全声明分两档并同步「对外能提交 run ⇒ 沙箱档强烈建议」。
契约侧补三条：`ws_server` 不得导入 `http_server`（56-3 的重构要钉住）、WS 慢消费者判据、缺 `websockets`
时的升级探针。三条继承项逐条裁定（F4 给结论文档化、F5/F6 用新判据闭合、F10 用变异脚本实证）。

## Boundaries & Constraints

**Always:**
- 文档只写**实测**事实；每条判据必须能被命令复现，不写「应该」「大概」
- 安全声明分档表述：本地模式（回环、无认证、无 TLS、非安全边界）与对外模式（token 强制、fail-closed、
  仍非绝对边界）分别写清；不出现「WS 更安全」这类扩大宣称
- 端口迁移与 breaking change 在**面向使用者的文档**可见（`README` / `deploy/README` / `.env.example`）
- 继承项处置要么闭环（附实测证据），要么显式再延并写明触发条件与负责人，**不留悬空**
- `pytest` / ruff / format / mypy / bandit / 架构契约 全绿（本机 3 条环境红单列并给 HEAD 对照证据）

**Never:**
- 不改 HTTP/SSE 与本机 HTTP API 契约，不改 WS 端点路径，不改冻结决策 D1–D7
- 不为了「文档好看」放宽任何判据，也不把 defer 写成 done
- 不引入新依赖、不新增 `HttpErrorCode`

</frozen-after-approval>

## I/O & Edge-Case Matrix

| 场景 | 输入/状态 | 预期行为 | 错误处理 |
|---|---|---|---|
| 文档与代码漂移 | 改 `network/ws_*` 端点或配置面 | 契约测试能抓到（端点矩阵 / 配置行 / 依赖方向） | 测试红即漂移 |
| `ws_server` 反向导入传输层 | 有人图省事 `from heagent.network.http_server import …` | 架构契约测试立即红 | AST 断言 |
| WS 慢消费者 | 订阅者队列满（落后一整窗口） | 该流被结束、哨兵入队、连接注销；客户端带游标重连可补齐 | 不静默丢事件 |
| 缺 `websockets` 包 | 子进程注入 import 阻断 | WS 升级回 404；同一进程 HTTP 面照常 200 | 安装诊断一条 |
| 硬化旗标被删 | 变异 `docker.py` 的 flag 列表 | 对应单测必红（逐条记录测试名） | 变异脚本输出 N/N |
| 质量门 | 全量 `scripts/quality_gate.py` | 覆盖率 ≥87%、静态门全绿 | 3 条环境红单列并给 HEAD 对照 |

## Code Map

- `docs/frame.md` — 4.17（HTTP 入口）/ 4.17.1（WS 入口）/ 4.17.1.1（CLI 旁路）拓扑与配置表；
  四「模块详解」network 条目；五「已知缺口」WS 口径
- `README.md` — 命令表与「HTTP 网页入口」节：补 WS 入口（9001）、三条端点、对外模式
- `deploy/README.md` — 端口迁移 + 对外模式部署（token / TLS / 沙箱）+ 反向代理不支持声明
- `AGENTS.md` — 安全声明与「已知缺口」：本地/对外两档 + Epic 53 沙箱档强烈建议 + MCP stdio 未覆盖
- `tests/test_architecture_contracts.py` — 新增 `ws_server` ↛ `http_server` 契约（+ 现有 network 禁入清单核对）
- `tests/network/test_ws_server.py` — WS 慢消费者判据（`_drop_lagging_ws_subscriber` 语义）
- `tests/network/test_ws_missing_dependency.py` — 新建：子进程阻断 `websockets` 的升级 404 探针
- `.agent` 之外的一次性脚本：`.heagent/tmp/mutate_hardening.py`（变异体，gitignore）

## Tasks & Acceptance

**Execution:**
- [ ] `docs/frame.md` — 4.17/4.17.1/4.17.1.1 按双 server 拓扑重写；配置表补 `ws_tls_cert_file` /
      `ws_tls_key_file` / 提交席位口径；五 已知缺口 WS 口径同步
- [ ] `README.md` / `deploy/README.md` — WS 入口、端口 8766→9001 breaking change、对外模式部署
- [ ] `AGENTS.md` — 安全声明分档 + Epic 53 沙箱档强烈建议
- [ ] `tests/test_architecture_contracts.py` — `ws_server` ↛ `http_server` 契约
- [ ] `tests/network/test_ws_server.py` — 慢消费者判据（替身队列）
- [ ] `tests/network/test_ws_missing_dependency.py` — 缺依赖 404 探针（子进程 + 裸 socket）
- [ ] 继承项 item-4（F4）/ item-5（F5+F6）/ item-10（硬化旗标变异）逐条处置 + `sprint-status.yaml` 回写
- [ ] 全量质量门亲跑登记（本 story 的 Verification 节写实测值）

**Acceptance Criteria:**
- Given 新读者只读 `README` + `frame.md`，when 找 WS 入口，then 能查到端口 9001、三条端点与「8766 不再接 WS」
- Given 部署到对外网络，when 读 `deploy/README`，then 能查到 token 放 `~/.heagent/setting.md`、TLS 两个键、
  缺 token 拒绝启动、沙箱档强烈建议
- Given `AGENTS.md` 安全声明，when 通读，then 本地/对外两档口径分明，且没有「WS 比 HTTP 更安全」的措辞
- Given 有人让 `ws_server` 导入 `http_server`，when 跑架构契约测试，then 变红
- Given WS 订阅者不消费，when 队列满，then 该流结束且客户端带游标可补齐（自动化判据）
- Given 缺 `websockets`，when 发起 WS 升级，then 404 且 HTTP 面 200（自动化判据）
- Given 逐条删除硬化旗标，when 跑对应单测，then 每条都变红（变异脚本 N/N 记录）
- Given 全量质量门，when 亲跑，then 覆盖率 ≥87%、静态门全绿、仅 3 条已知环境红（附 HEAD 对照）

## Verification

**Commands:**
- `pytest tests/test_architecture_contracts.py tests/network/test_ws_server.py tests/network/test_ws_missing_dependency.py -q`
- `pytest -q`（全量；3 条环境红单列）
- `python scripts/quality_gate.py`
- `python scripts/mutate_sandbox_hardening.py`（变异体，期望 N/N 变红）

**实测结果（2026-10-24）:**
- `pytest tests/test_architecture_contracts.py tests/network -q` → **467 passed**（架构契约 33，含本 story 新增 2）
- `pytest -q --ignore=tests/test_cli_http_lifecycle.py` → **3911 passed / 50 skipped / 25 deselected**
- `ruff check src tests scripts` / `ruff format --check src tests scripts` / `mypy src` / `mypy src --platform linux` /
  `bandit -r src/ -ll` → 全绿
- `scripts/quality_gate.py` → 覆盖率 **92.44%**（门限 87%）；唯一失败 = 3 条已知环境红（HEAD 副本复现，见 56-2）
- `scripts/mutate_sandbox_hardening.py` → 基线绿，**9/9 变异体变红**
- `test_shutdown_closes_websocket_and_cancels_run_within_budget` 连跑 **10/10 绿**（F4 复验）

## Spec Change Log

<!-- Append-only. -->

- 2026-10-24：`Epic 54 retro A2` 的两个「未发现自动化判据」项（慢消费者 / 缺依赖 404）在**本 story**
  补齐，而不是按原计划「随 56-1 顺带」——56-1 只重建了替身纯逻辑面，这两条留到文档/契约 story 更自然。
- 2026-10-24：`Epic 53 retro A53-3`（硬化旗标负向变异）的取证脚本**入库**为
  `scripts/mutate_sandbox_hardening.py`。原计划写「放 `.heagent/tmp/`」——改为入库，理由见
  Review Triage Log 第 1 条（gitignore 里的变异结论不可独立复核，正是 epic-54 retro 批评过的形态）。

## Implementation Notes

<!-- Agent-owned. Append-only during implementation. -->

- **文档面**（4 处）：`docs/frame.md` — 4.17 增「同进程双 server」段、传输层行改为「HTTP/SSE 独占且零 WS
  路由」、4.17.1 重写为独立 listener（三条端点矩阵 + 生命周期/就绪 + 配置面）、配置表补
  `ws_tls_cert_file` / `ws_tls_key_file` 两行并订正 `ws_host` / `ws_port` / `ws_max_connections`、
  五「已知缺口」WS 行改写为本地/对外两档并写入「对外能提交 run ⇒ 沙箱档强烈建议」、六目录树补
  `ws_host.py` / `ws_auth.py`、调用链图重画为双 listener + 三条 WS 端点。
- **README / deploy/README**：新增「WebSocket 入口（9001）」整节（三条端点、提交示例、本地/对外两档对照
  表、token 位置、TLS 两个键、沙箱强烈建议）与部署侧「网络入口」节（双 listener 表、端口迁移 breaking
  change、三种部署姿态、`.env` 与 `setting.md` 示例、安全前置）。`AGENTS.md` 安全声明新增「网络入口分两档」
  四条 + 硬约束新增 `ws_server ↛ http_server`。
- **契约面**（3 条新判据）：`test_ws_server_does_not_import_the_http_transport_module`（AST 断言
  `ws_server` / `ws_auth` / `ws_protocol` 均不导入 `http_server`，且 `ws_host` 只取 `_require_module`）；
  `test_ws_endpoints_and_commands_stay_closed`（三条端点路径与 `{run,cancel,ping}` 命令集封闭）；
  WS 慢消费者两条（队列满 ⇒ 哨兵结束该流 + 连接注销；WS 与 SSE 订阅池背压互不牵连）。
- **缺依赖探针**：`tests/network/test_ws_missing_dependency.py` 起独立解释器，在 import 前把
  `sys.modules["websockets"]=None`，真实绑定双 listener，用裸 socket 断言「WS 升级 404、HTTP /api/health 200」。
  单例耗时 ~17s（本机 E: 9p 挂载下 `import heagent` 本身就要 14s；CI 本地盘会低一个数量级）。
- **继承项三连**：item-4（F4）裁定为**测试过断言**并文档化（原断言依赖「close 返回瞬间 serve 协程已退出」
  的调度巧合；`WsServer._stop_listener` 只 `await server.shutdown()`，不 await `main_loop`，故该时序不是契约；
  56-1 改为 `await asyncio.wait_for(task)` 后再断言，本 story 复跑 10/10 绿）；
  item-5（F5/F6）由上述慢消费者 + 缺依赖探针闭合；item-10（硬化旗标变异）由入库脚本实证 **9/9 变红**。
- 实测：`pytest -q --ignore=tests/test_cli_http_lifecycle.py` → **3911 passed / 50 skipped / 25 deselected**；
  架构契约 33 passed（+2）；`scripts/quality_gate.py` 覆盖率 **92.44%**（门限 87%），静态门全绿；
  `python scripts/mutate_sandbox_hardening.py` → 9/9 红。

## Review Triage Log

<!-- 2026-10-24 step-04。三层指令（blind-hunter / edge-case-hunter / verification-gap）逐层执行；
无子代理独立性（同 56-2/56-3 的说明）。 -->

| # | 发现 | 判定 | 证据 / 路由 |
|---|---|---|---|
| 1 | 变异体脚本留在 `.heagent/tmp/`（gitignore）⇒ 「9/9 变红」的结论无法被独立复核——正是 epic-54 retro 批评过的形态（「变异体脚本在 .heagent/tmp/（gitignore）未入库」） | medium（真） | 自审时对照 retro 原文 → **patch**（入库 `scripts/mutate_sandbox_hardening.py`，`ROOT` 按 `scripts/` 修正为 `parents[1]`，复跑 9/9 红；ruff/format 覆盖 `scripts/` 已绿） |
| 2 | 缺依赖探针断言 uvicorn 的英文诊断原文（`No supported WebSocket library detected`）⇒ 措辞随版本变化就假红 | low（真） | 判据本质是 404 vs 200 → **patch**（改宽松匹配 `"websocket" in stderr.lower()`，注释写明诊断只作旁证） |
| 3 | 探针用最小 env（只给 `PYTHONPATH`）⇒ Windows 下缺 `SYSTEMROOT` 等基础变量，子解释器起不来 | low（真） | → **patch**（`{**os.environ, "PYTHONPATH": …}`） |
| 4 | 探针首版触发 `ruff` 的 S603 与 E501 | low（真） | `ruff check` 实测 → **patch**（`# noqa: S603` 附理由 + 结构化 env 行；`tests/` 不在 bandit 扫描面，故无需镜像 nosec） |
| 5 | 端点封闭性判据用正则从源码抓三个路径常量，属源码级断言（脆） | low（接受） | 仓库既有 source-level contract 先例（`test_uvicorn_ws_options_moved_to_ws_host` 等同型）；同时断言 `WsCommand` 枚举与 `__all__`，路径漂移仍会被抓起 |
| 6 | F4 的「close() 返回即 serve 任务已退出」是否其实是保证（若保证，显式 wait 就多余） | false（驳回） | 读 `WsServer.close → _stop_listener`：只 `await server.shutdown()`，而 `main_loop` 靠 `should_exit` 轮询（0.1s）退出 ⇒ 时序是巧合不是契约；实测 5/5 `task.done()` 为 True 只说明「通常够快」，据此删掉显式等待会把测试重新绑回调度竞态 |
| 7 | 文档称 `ws_max_connections` 同时管「每 run 订阅 / hub 总额 / 提交席位」 | false（驳回） | 读代码核对三处计数点（`try_add_ws_subscriber` / `CliEventHub(max_connections=…)` / `_SubmissionSlots(max_connections)`）与配置表；描述与实现一致 |
| 8 | 4.17.1「可选依赖」行没有可执行判据指引（只描述行为） | low（真） | → **patch**（补 `tests/network/test_ws_missing_dependency.py` 引用与「子进程阻断 import + 裸 socket」方法说明） |
| 9 | 0 文档没有 `WS_AUTH_TOKEN` 的推荐生成方式（用户可能用弱串） | low（真） | → **patch**（`deploy/README` 给出 `openssl rand -hex 32` 建议） |
| 10 | 缺依赖探针单例 ~17s，拖慢套件 | low（接受） | 实测分解：`import heagent` 在本机 9p 挂载下就占 14s（`-X importtime` 实测），与探针逻辑无关；CI 本地盘低一个数量级。若将来成为瓶颈，可改为「并入 `test_sandbox` 式 subprocess 批」而不是跳过它 |
