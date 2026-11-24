# E78 回顾 · 活动台账的仓库内跟办

## 一、做成了什么

| entry | 交付 | 判据 |
|---|---|---|
| 78.1 | 幂等窗口两条 DEBUG 事件（容量淘汰 / 键移出）+ `drop(reason=…)` | 5 例（含「日志里无 `request_id`」、TTL 静默、重复 drop 不刷第二条） |
| 78.2 | `scripts/web_search_smoke.py`：四段判据 + `--self-check` + 退出码 0/1/2 | 7 例（离线 / 无 key / `--help` / 四例解析与口径） |
| 78.3 | A55 / A67 / A76 三条台账「操作卡」 | 台账守卫 12 passed，条数与 ID 集合不变 |

## 二、代价与偏差（显式）

- **没有新登 A77**：可观测面在本 epic 内当场实现并闭合，立一个「立完即闭合」的 A 号只会给台账加一次迁移成本；
  闭合证据写进 E77 回顾原本那条「可观察但未做」。
- **跑到了三个环境坑**：① 台账表格里的 `netstat -ano | findstr` 的 `|` 会拆单元格（台账守卫当场红，改成
  「`netstat -ano`（再用 `findstr` 过滤）」）② 9p 上 `write_text` 又出现一次 `Errno 22`（重试即成功）
  ③ `tickets.py` 的状态词表只认 `draft / ready-for-dev / in-progress / in-review / built / done / blocked / dropped`，
  我先后写了 `building`（非法，被判 blocked）——以后立项先照词表写。
- **三审形态变更**：用户 2026-11-24 裁定「三审合并为一个文档，以后也一样」⇒ 本轮起单文档三镜头，
  `closeout.md` 已同步；历史 epic 的三份保持原样。

## 三、留给下一轮的东西

- **A55 仍未闭合**：脚本就绪，缺 `WEB_SEARCH_API_KEY`；拿到 key 后一条命令即可（`python scripts/web_search_smoke.py --query …`）。
- **A67 / A76 仍等宿主**：本容器 `docker` not found、shell 也在容器内；操作卡已写进台账正文，宿主侧照做即可。
- **可观测面只到日志**：`/api/status` 不带窗口计数，命中率/淘汰率仍需 grep 日志（刻意不扩，见 epic Boundaries）。

## 三审记录

| 镜头 | 结论 | 计数 | 落改去向 |
|---|---|---|---|
| 一 · 规格对账 | 通过 | C0 / H0 / M0 / L0 | — |
| 二 · 不变量与守卫反脆弱 | 有条件的通过 | C0 / H0 / **M2** / L0 | 当轮落改（冒烟条目解析改块级、段 2 的 0 条改 note）+ 3 例新判据；7 条注入反证全「红→复原→绿」 |
| 三 · 三镜头对抗（契约 / 并发 / 文档） | 通过 | C0 / H0 / M0 / **L1** | L1（无 key 时 `[FAIL]` 与 exit 2 并存）记录不改 |

报告：`epic-78-open-items-followthrough-review.md`（单文档三镜头）。
