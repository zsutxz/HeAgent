---
ticket: 6
title: E75-S06 · 契约基线与文档收口
status: done
baseline_revision: e9d6bfd4
covers: [R1, R5, R7]
---

## Story

重生成五份契约基线并人工 review diff；把 `docs/framework.md` 的 WS 段收口到 Epic 75 的现口径
（5 值命令面 / `projects` 命令 / 项目通道注入链路 / 错误码总数），复核 `docs/frame.md`。

## Tasks & Acceptance

- [x] `python scripts/contract_snapshot.py --write` 全量重生成五份基线，`--check` 五份全 `[OK]`。
- [x] `docs/framework.md` 命令面口径：陈旧 `{run, cancel, ping}` / `{cancel, ping}` 全部改净
      （`grep -n` 复核无残留），改后命令面为 `run` / `cancel` / `cancel_run` / `ping` / `projects`，
      单 run 端点为 `{cancel, cancel_run, ping}`。
- [x] 目录树 `network/` 段补 `ws_commands.py`（74.3 拆出的命令循环簇）。
- [x] 新增「项目通道（Epic 75）」行：注入链路 + 适配器职责 + 六项落点 + 未注入时的 `invalid_request`。
- [x] `HttpErrorCode` 总数 `35` → `36`（实测 `len(list(HttpErrorCode))`），项目侧新码
      `project_registry_unreadable`（HTTP 500，仅提交径产生）在 WS 段点名。
- [x] `docs/frame.md` 不存在 ⇒ 不新建（见 `## Design Notes` bad_spec）。
- [x] 门禁：`ruff check` / `ruff format --check` / `mypy src` / `bandit -r src/ -ll` 全绿；
      `mkdocs build --strict` 0 warning；受影响子集全绿（数字见 `## Verification`）。

## Design Notes

- **票面 verify 与现状的口径差（1）**：票面写「`--write` 后 `git diff --stat
  tests/fixtures/contract_baselines/` 仅 `transport_errors.json` 一行变更」。该口径写于基线**尚未**
  重生成之时；75.1 已用 `--only transport_errors` 落过 `project_registry_unreadable`，批级派生又用
  `--only exceptions` 重生成过异常基线。因此本 entry 实测 `--write` 后基线目录 **零 diff**
  （`--check` 五份全 `[OK]`），「只多一行」这一位移已在前序 entry 完成。这是口径差、不是缺项。
- **票面 verify 与现状的口径差（2）= bad_spec**：票面要求「`docs/frame.md` 复核」，但该文件
  **不存在**（v6 命名遗留；75.3 已确认并把 cli 子模块表同步到 `docs/framework.md`）。真源
  `docs/framework.md` 是唯一架构权威，新建 `docs/frame.md` 只会造第二份真相并触发 mkdocs 无 nav
  告警 ⇒ 本 entry 不新建，仅在 `docs/framework.md` 的 cli 与 `network` 两段复核。
- **命令面的 5 值 vs 票面的「只提 projects」**：票面 description 只点到 `projects`，实测 `WsCommand`
  是 `{run, cancel, cancel_run, ping, projects}` 五值（`cancel_run` 由 74.2 引入，`projects` 由本 epic
  引入）。文档按 5 值写，并点明 **`run` 与 `projects` 都只在集合级端点有效**，单 run 端点、CLI
  旁路与通知流收到它们回 `invalid_request` 且不断连。
- **项目通道的「只翻译」边界**：文档正文按结构事实写——适配器不解析项目目录、不探测目录在盘、
  不读注册表文件，判断全在 `cli/http_console.py` 与 `pub/projects.py`；六项落点（`workspace_root` /
  会话文件 / 产物目录 / ledger / `RunContext.state_root` / memory 根）由
  `HttpProjectConsole.start_project_run` 经 `for_workspace` 派生 per-project 运行时保证，不是适配器
  的职责。
- **未注入时的语义必须写进文档**：`project_service=None` 时 `projects` 与带 `project_id` 的 `run`
  回 `invalid_request`，**不静默按启动工作区执行**——这是本 epic 的核心不变量（「装配漏了」不能
  变成「跑错项目」），文档漏写就会退化成纪律要求。

## Code Map

| 文件 | 落点 |
| --- | --- |
| `docs/framework.md` §4.16 协议模型行 | `HttpErrorCode` 码数 35 → 36；WS 命令面改 5 值 |
| `docs/framework.md` §4.16.1 端点表 | 单 run 端点命令面 `{cancel, cancel_run, ping}` |
| `docs/framework.md` §4.16.1 帧契约行 | 命令集封闭为 5 值 + `run` / `projects` 都只在集合级有效 |
| `docs/framework.md` §4.16.1 项目通道行（新增） | 注入链路 / 适配器 / 六项落点 / 未注入语义 / `project_registry_unreadable` 500 |
| `docs/framework.md` §4.16.1 提交 run 行 | 补 `project_id` 分支与 `projects` 列表命令 |
| `docs/framework.md` §4.16.1 CLI 旁路 / 通知流行 | 拒绝集补 `projects` |
| `docs/framework.md` 六、目录结构 `network/` 段 | 补 `ws_commands.py` |
| `docs/framework.md` 调用链树 | 单 run 端点命令面 `{cancel, cancel_run, ping}` |
| `tests/fixtures/contract_baselines/*.json`（4 份） | `--write` 全量重生成；本次零 diff（前序 entry 已落） |

源码侧本 entry **零改动**（只动文档与基线），故 `src/` 无 Code Map 条目。

## Verification

所有命令在仓库根跑；Python 一律 `.heagent/tmp/py311-venv-linux/bin/python -m …`。

### 契约基线

```text
$ python scripts/contract_snapshot.py --write
[WRITE] public -> tests/fixtures/contract_baselines/public_exports.json (17216 bytes)
[WRITE] routes -> tests/fixtures/contract_baselines/transport_routes.json (9836 bytes)
[WRITE] exceptions -> tests/fixtures/contract_baselines/exception_types.json (29561 bytes)
[WRITE] transport_errors -> tests/fixtures/contract_baselines/transport_errors.json (7891 bytes)
[WRITE] error_codes -> tests/fixtures/contract_baselines/error_codes.json (3975 bytes)
```

- 首次执行在 `exception_types.json` 上抛 `OSError: [Errno 22] Invalid argument`（挂载层偶发），
  **重跑即成功**（不是权限或文件损坏）；同一轮里另有脚本外的探针写过该文件验证过可写性。
- `git diff --stat tests/fixtures/contract_baselines/` ⇒ **空**（0 文件变更）⇒ 与 `## Design Notes`
  的口径差（1）一致：四份基线（实测是**五份**，另有 Epic 70 的 `error_codes.json`）已在前序 entry
  全部落定，本次重生成零漂移。
- `python scripts/contract_snapshot.py --check` ⇒ 五份全 `[OK]`（public / routes / exceptions /
  transport_errors / error_codes）。
- 基线目录**实际是 5 份**（票面写「四份」）：`public_exports` / `transport_routes` /
  `exception_types` / `transport_errors` / `error_codes`（后者为 Epic 70 新增）。
- `len(list(HttpErrorCode))` ⇒ **36**。

### 文档门

```text
$ python -m mkdocs build --strict        # exit=0，WARNING 计数 = 0
INFO    -  Documentation built in 7.19 seconds
```

未新增/删除任何标题，故 `docs/framework.md` 手写 TOC 与跨文件锚点无需改动；
`tests/test_docs_links.py` 4 例在下面的受影响子集里全绿。

### 静态门

| 命令 | 结果 |
| --- | --- |
| `ruff check src tests` | `All checks passed!` |
| `ruff format --check src tests` | `504 files already formatted` |
| `mypy src` | `Success: no issues found in 240 source files` |
| `bandit -r src/ -ll` | `No issues identified.` |

### 测试

- 受影响子集（`tests/network` + `test_architecture_contracts` + `test_cli_http_lifecycle` +
  `test_project_registry_health` + `test_ws_project_adapter` + `test_http_console_project_run` +
  `test_docs_links` + `test_security_posture_contract`）：

  ```text
  854 passed, 1 warning in 41.25s
  ```

- 全量（带 node，前端探针不 skip）：

  ```text
  5816 passed, 17 skipped, 30 deselected, 1 xfailed, 2 warnings in 386.53s
  ```

  0 failed ⇒ 无回归。

### 工作树

```text
 M docs/framework.md
?? docs/Goal-4/tickets/epic-75-project-channel-runtime/tickets/story-e75-s06-closeout-plan.md
docs/framework.md | 21 ++++++++++++---------
1 file changed, 12 insertions(+), 9 deletions(-)
```

12 处新增 = 3 条新行（项目通道表行 / `ws_commands.py` 树行 / 调用链 `projects` 行）+ 9 行改写；
`src/` 零改动，基线零 diff。

## 宿主复核（2026-11-23，串行门禁）

- 契约基线：`--write` 全量重生成后 `git diff --stat tests/fixtures/contract_baselines/` = **空**；`--check` 五份（票面写四份，第五份 `error_codes.json` 属 Epic 70）全 `[OK]` ⇒ 75.1 与批级派生已先行落地，票面「只多一行」的口径差已记 Design Notes。
- `docs/framework.md`：陈旧命令面 grep 残留 **0**；命令面 5 值落在协议模型行 / 端点表 / 帧契约 / 目录树 / 调用链，且 CLI 旁路与通知流的拒绝集补了 `projects`；新增「项目通道（Epic 75）」整行（注入链路 + 适配器只翻译 + 六项落点 + 未注入回 `invalid_request` + 错误码 35 → 36）；目录树补 `ws_commands.py`。
- `HttpErrorCode` 实测 **36** 成员，两处写死数字（§4.16 协议模型行、§4.17 错误码分组行）同步改正，分组和 7+5+5+2+2+1+14 = 36 自洽。
- `mkdocs build --strict` → exit 0、0 warning（宿主复跑 5.61s）。
- 宿主合成复跑 `test_docs_links + test_security_posture_contract + test_api_docs_pages + tests/network + 架构契约 + cli_http_lifecycle + registry_health + ws_project_adapter + http_console_project_run + 契约基线` → **863 passed, 1 warning**。
- 子会话另跑带 node 的**全量** `pytest` → 5816 passed / 17 skipped / 1 xfailed / **0 failed**（386s）；本轮不复跑全量以省时，以此记录为证。
