# E77 回顾 · WS 远程项目通道：三处延迟裁决落地

- 收口日期：2026-11-24
- 规模：3 entry（幂等键 / 具名码 / 只读能力面与收口），全部 `done`
- 触发：E76 收口时挂进 `brief.md`「延期项」的三条（M-4 / M-7 / H-2），2026-11-24 用户逐条裁决

## 一、交付对照（裁决 → 落点）

| 裁决 | 结论 | 落点 | 判据 |
| --- | --- | --- | --- |
| R3 M-4 提交幂等 | 最小幂等：`request_id` + 60s 内存窗口 | `network/ws_protocol.py`（帧面/端口）、`network/ws_commands.py`（透传）、`cli/ws_submission_cache.py`（新增）、`cli/ws_project_adapter.py`（接线） | 适配器 6 例 + 协议 2 例 + 透传 1 例 |
| R3 M-7 错误码分流 | 新增 `project_channel_unavailable` | `network/http_protocol.py`、`network/ws_commands.py`、`web/app.js`、两份文档、`transport_errors.json` | 两条路径断言新码 + 帧拼错对照例 |
| E75 H-2 只读 listener | 维持零能力面，只改文档 | 架构 AD-8、`docs/framework.md` §4.16.1 | `grep` 架构 spine 零命中 + mkdocs strict |

## 二、做对了什么

- **先取证再动手**：H-2 的关键取证是「`WsServerConfig.readonly` 自 Epic 72 起无入口层配置键」——这一条直接
  把「要不要给只读 listener 开 `projects`」从设计题降级成文档题，避免了新端点 + 新权限语义的净负收益改动。
- **幂等落点按层选**：网络层只透传 `request_id`，状态与语义住入口层。收益是 `network/` 仍不认识提交结果，
  「传输层哑传输」这条结构不变量没有被破坏。
- **门禁当设计约束用**：适配器 150 行预算逼出了 `cli/ws_submission_cache.py` 这个干净拆分；反过来说，如果当初
  图省事把预算放宽，适配器会长成「翻译 + 状态机」的混合体。
- **全量门禁抓到了单文件单测抓不到的东西**：`test_http_web_ui` 要求每个 `HttpErrorCode` 在 `app.js` 有中文文案，
  只跑 `tests/network` 是绿的。这条记进 S02 的 plan。

## 三、代价与偏差（显式）

- **新增一个 cli 子模块 = 三处同步**（白名单 / §4.1 表 / 目录树）。这是仓库既有契约，不是本轮引入，但每次都要
  三处都改到，容易漏。
- **契约快照连带影响**：`exception_types.json` 收的是**所有类**（不只异常），所以「新增一个纯工具类」也会让它红。
  下一轮见到这类红先分辨「是不是新类」而不是「是不是异常层级变了」。
- **对比测试的替身语义**：`_ws_session` 在 session 返回后会补一次默认 `close(1000)`，替身只记最后一次 close ⇒
  试图用 `closed_code == WS_CLOSE_POLICY` 断言会红。判据改成「连接确实关了」并另加一条自证断言，避免把替身
  记法当协议事实。
- **构建轮没跑三审（R1/R2/R3）**：E74–E76 都有三份评审报告，E77 是单 lane 构建 + 用户直批，只有本回顾。
  ⇒ 2026-11-24 已补跑，见下节「三审记录」。

## 四、留给下一轮的东西

- **未闭合（不属本 epic）**：`_bmad-output/open-items.md` 的 A76 仍只剩「客户端 pin 对账」（另一仓）。
- **可观察（2026-11-24 E78-S01 已补）**：幂等窗口补了两条 DEBUG 事件——`ws event=idempotency_evicted reason=capacity`（容量淘汰）与 `ws event=idempotency_dropped reason=failed|cancelled`（键移出），日志只带 `project_id`（`request_id` 不进日志）。原文：若线上真出现
  「同键重复起 run」，现在只能靠 `run_conflict` 现象反推。要可观测就加一条 `ws event=idempotency_evicted`
  类日志，但那属于新增可观测面，需单独立项。
- **已知边界**：进程重启后窗口消失（显式选择，写进模块 docstring 与 `brief.md`），不假装持久。

## 五、三审记录（2026-11-24 补跑）

补审对象 = 未提交工作树（`HEAD 669ed177`），三份报告落 `-review-r1.md` / `-review-r2.md` / `-review-r3.md`。

| 轮次 | 镜头 | 计数 | 结论 |
|---|---|---|---|
| R1 | 规格对账（Requirements R1–R3 + Done-when 四条逐条对实测） | C0 / H0 / **M1** / L2 | 有条件的通过；M1 = `docs/errors.md` 传输层码计数 36（实际 37） |
| R2 | 不变量与守卫反脆弱（五条注入反证） | C0 / H0 / **M2** / L2 | 有条件的通过；M1 = `asyncio.shield` 零判据且 docstring 失败模式写错，M2 = 在途项被 TTL/容量淘汰 |
| R3 | 三镜头对抗式（契约 / 并发 / 文档） | C0 / H0 / **M2** / L3 | 通过（落改后复评）；M 两条都是同一文档内的自相矛盾 |

**落改合计 8 处**：

- 并发语义 2 处：`ws_submission_cache` 过期只清已完成项、容量满优先淘汰已完成项；
- docstring 2 处：`shield` 的真实必要性（连坐取消，不是 `InvalidStateError`）、键不含 prompt；
- 判据 2 处：新增 `tests/test_ws_submission_cache.py`（5 例）、`test_cancelling_one_joiner_does_not_cancel_the_other`（1 例）；
- 文档 4 处：`docs/errors.md` 37 / 78、`docs/framework.md` 两行补窗口边界、架构 §7 第 1/7 条按裁决闭合、
  `brief.md` 两条→三条、架构三处 `docs/frame.md` 与两处「四份基线」。

**教训（下一轮直接用）**：改 AD 正文后必须回扫同一文档里**复述同一事实**的段——「刻意留开的项」、
「依赖方向」、「实现期硬提醒」这三段最容易留下与正文相反的旧句（本轮 M-1 / M-2 / L-2 全出在这里）。

**门禁实测**：全量 `pytest` 5899 passed / 0 failed；`ruff` / `format` / `mypy 242` / `bandit` 干净；
五份契约基线 `[OK]`；`mkdocs build --strict` 0 warning。
