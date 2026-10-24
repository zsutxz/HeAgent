---
epic: 56
phase: 2
date: 2026-10-24
verdict: accepted
criteria: declared
headless: false
---

# Epic 56 期二 · 双 WS 监听并存 · Retrospective（2026-10-24）

## Epic summary

- **期二**：双 WS 监听并存（本机免 token + 对外带 token 同时服务）——期一 D5 明确「不做，期二另裁」的那条，
  由用户 2026-10-24 拍板「按推荐的走」后立项，同日完成 3 个 story。
- **Diff range**：基线 `bab1dc5`（期一 retro 收口）→ 本期工作区改动（未提交；HEAD 期间被并发会话推进到 `169d3f9`）
- **Stories**：56-5 / 56-6 / 56-7 全部 `done`
- **决策**：D8（配置双键）/ D9（端点可见性 + 连带收紧）/ D10（对外 TLS 成对继承）/ D11（限额）/
  D12（装配与生命周期）/ D13（观测）/ D14（文档契约）——提案 `phase2-proposal.md`，冻结值写进 `brief.md`

## Behavior verification（实测，含三条 action item 落地后的最终一轮）

- `scripts/quality_gate.py` → **六门全过**（goal 冒烟 → 全量回归 + 覆盖率 → ruff lint → ruff format →
  mypy → bandit `-ll`），覆盖率 **92.43%**（门限 87%），**3947 passed / 50 skipped / 25 deselected**
- 期二收口中间一轮曾报 3 条 `test_cli_http_lifecycle.py` 失败（`bind` 撞 TIME_WAIT）；P2-A1 修判据后**归零**
- `scripts/verify_baseline.py tests/test_cli_http_lifecycle.py -q` → 工作区 `10 passed` / HEAD 副本
  `7 passed, 3 failed` ⇒ `VERDICT: environmental`（证明那 3 条是**旧判据**的缺陷，不是环境限制）
- `pytest tests/network -q` → **455 passed**；`pytest tests/test_architecture_contracts.py -q` → **35 passed**
- `ruff check src tests scripts`（347 files）/ `ruff format --check` / `mypy src` 与 `mypy src --platform linux`
  （174 files）/ `bandit -r src/ -ll`（Medium 0 / High 0）→ 全绿

## Findings

### 实现类

- **F1（medium，已修）提案里的 `WsServerConfig.listener` 字段与 `mode` 语义重叠**：`mode` 是绑定地址的派生
  只读属性，再加一个「listener 标签」会让两者不一致成为可能。处置：不新增字段，日志标记直接取 `mode`
  （`ws event=started … listener=local|external`）。story 的交付物文字按实现实况修正并登记。
- **F2（medium，已修）TLS 跨对混搭**：初版「对外 cert 独配 + 继承 key」的写法会拿 A 的证书配 B 的私钥。
  处置：**成对**规则（都设或都不设，半配 fail-loud），判据 `test_external_tls_files_must_be_set_as_a_pair`。
- **F3（medium，已修）hub 创建与跳过判定分叉风险**：期一在 `build_http_service` 里建 hub，期二的「跳过旁路」
  判定在 `build_ws_servers`——两处会漂移。处置：hub 创建收进 `build_ws_servers`，返回 `(servers, hub)`；
  `EmbeddedHttpService.cli_hub` 语义 = 「实际挂载的 hub」。
- **F4（medium，已修）对外 listener 的端点可见性只在装配层挡住**：直接构造 `WsServer(config, cli_hub=hub)`
  仍会把终端流推出去。处置：`build_ws_app` 再判一次 `mode`（defense-in-depth），契约测试直接构造最坏情况
  断言路由集恰为 `{提交, 订阅}`。
- **F5（low，已修）命令层对对外 listener 误报「no authentication」**：`http-server` 原先对所有 WS listener
  套 `exposure_warning`。处置：按 `config.requires_auth` 分流（`external mode; Bearer token required; …`），
  与 `WsServer.start()` 的 `event=exposed` 口径一致。

- **F8（medium，已修）三个周期把「判据缺陷」误归因为环境噪声**：`test_cli_http_lifecycle.py` 的端口探针用
  `bind` 判「已释放」，撞上关停后的 TIME_WAIT（正常 OS 行为）⇒ 恒红。处置：改 `connect` 判据（未监听 ⇒
  `ECONNREFUSED`），修后 10 passed；并把判读流程写进 `docs/testing.md` + `scripts/verify_baseline.py`，
  让下一轮不必再靠记忆判断。

### 流程类

- **F6（process）并发会话推进 HEAD**：开工后另一个会话提交 `169d3f9`。本期遵循「每轮先 `git status --porcelain`」
  纪律，改动全部落在自己的文件集内；门禁基线取 HEAD 干净 worktree 时天然包含了那次提交（不影响结论）。
- **F7（process）「已知环境红」的取证方式固化**：`git worktree add --detach <tmp> HEAD` → 复跑目标文件 →
  `worktree remove`，比 `git stash` 安全（不碰工作区、不影响并发会话）。

## Action items（提案，待人确认后执行）

| # | 类型 | 内容 | 负责人 | 状态（2026-10-24 用户裁定「三条都要做」） |
|---|---|---|---|---|
| P2-A1 | verify | `test_cli_http_lifecycle.py` 的 3 条端口释放探针已连续三个周期归因为环境噪声（WSL2/容器 bind 语义） | 流程-测试基建 | **done（根因修复，非 skip）**：探针从 `bind` 改 `connect` 判据——TIME_WAIT 会让 `bind` 误报 `EADDRINUSE`，而 connect 的「还有人在听吗」才是真实语义；修后该文件 **10 passed**（原 7 passed / 3 failed）。判据说明写入 `docs/testing.md` 四 |
| P2-A2 | process | 「已知环境红」取证脚本化 | 流程-质量门 | **done**：`scripts/verify_baseline.py <pytest args…>`（worktree 复跑 + 对照打印 + `VERDICT: environmental/REGRESSION/clean/inconclusive`，退出码 0/1/2）；用法与判读表写入 `docs/testing.md` 二 |
| P2-A3 | defer | 对外 listener「只读模式」 | 下一周期 | **done（本期落地为 story 56-8）**：`WS_EXTERNAL_READONLY`（默认关）+ `--ws-external-readonly/--ws-external-writable`；不注册提交端点、`cancel` 拒绝不断连 |

## Acceptance

**accepted**（criteria: declared——3 个 story 各有可执行判据与实测数字；期二验收 7 条逐条有判据）：

1. 零行为变化：默认配置的单 listener 路径由既有 452 例网络测试 + 全量 3933 例覆盖
2. 双监听并存：`test_dual_listeners_serve_the_same_run_with_identical_event_streams`（同源 `seq`）
3. 对外 listener 无 CLI 旁路：e2e 403 + 契约路由集 + 装配层 `cli_hub is None`
4. 配置 fail-loud 四例：`test_external_listener_rejects_a_loopback_address` /
   `…_rejects_an_already_external_primary` / `…_fails_closed_without_a_token` / `…_tls_files_must_be_set_as_a_pair`
5. 提交席位双 listener 独立：`test_submit_slots_are_counted_per_listener_while_subscriptions_are_shared`
6. 启动/关停有界且可回滚：`test_embedded_service_rolls_back_every_listener_when_the_external_one_fails`
7. 全量门禁：见 Behavior verification

## Open questions

1. 对外 listener 的「只读旁观」是否需要（P2-A3）——取决于是否真出现「给看不给下命令」的场景。
2. 双监听为同一状态机共享（D6 单用户语义）在多人场景下仍是瓶颈；多租户隔离已明确不做。
