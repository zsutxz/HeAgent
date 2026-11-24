---
type: review
code: E77-R3
epic: epic-77-remote-contract-hardening
review_loop_iteration: 0
lens: 三镜头对抗式（契约面 / 并发面 / 文档面）
reviewed_at: 2026-11-24
head: 669ed177
---

# E77 收口三审 · R3 三镜头对抗式

## 范围

三个镜头各扫一遍 E77 的**未提交工作树**，重点是「同一事实在多处被复述时是否已经漂移」——
E74 / E75 的 High 级发现全部出自这一类（规格文本自相矛盾、文档承诺与代码相反）。

| 镜头 | 扫什么 | 结果 |
|---|---|---|
| 契约面 | `HttpErrorCode` 集合、五份基线、帧面封闭集、ack 四格 | 无 Critical/High；只增语义成立（详见 R1） |
| 并发面 | 幂等窗口的在途合流 / 取消 / 淘汰 / 失败路径 | 2 条 Medium，已在 R2 落改并配反证 |
| 文档面 | AD-8 与 §4.16.1 与代码是否一致；同一文档内是否自相矛盾 | **2 条 Medium + 3 条 Low，全部落改** |

## 发现（文档面）

### R3-M-1（Medium，已落改）架构 §7 第 7 条仍写「`projects` 在只读 listener 上开放」

- 位置：`docs/Goal-4/architecture-ws-remote-project-channel/architecture-ws-remote-project-channel.md:311`。
- 现象：AD-8 正文已按 H-2 裁决改成「零能力面 ⇒ `projects` 不可达」，但同一份文档「刻意留开的项」
  第 7 条**原文不动**地写着「`projects` 帧在只读 listener 上开放（含项目名）…默认处置：允许」。
  两处相反，读者按哪段实现都能自证有据 —— 这正是 E75 R3 判 High 的那类「规格自相矛盾」。
- 处置：**已落改**为「关闭：不成立」——只读 listener 上集合级端点未注册 ⇒ 命令不可达，项目名
  根本不经过只读档，也不需要「只回 `id` + `available`」的退化形态。

### R3-M-2（Medium，已落改）架构 §7 第 1 条仍写「提交命令无幂等键 … 不在本 epic 范围」

- 位置：同上 `:305`。
- 现象：E77 的整个 R1 就是闭合这一条，但索引表里它仍是「刻意留开」的现状陈述 ⇒ 架构文档与 epic
  描述互相打脸；后来者会按「无幂等键」写客户端。
- 处置：**已落改**为已闭合 + **残余边界显式化**（窗口随进程重启失效 / TTL 从提交开始计时 /
  键不含 prompt / 不做落盘幂等及其理由），避免「闭合」被读成「已经彻底幂等」。

### R3-L-1（Low，已落改）`brief.md` §延期项 表头「两条」与正文三条不符

- 位置：`docs/Goal-4/brief.md:90`。
- 现象：`2026-11-23 复核` 那段写「当时只剩下面**两条**未裁决」，其下却列三条（M-4 / M-7 / H-2），
  且新加的表头写的是「下面三条」。H-2 确实在 2026-11-23 就被标为「需用户裁决」，属漏列。
- 处置：**已落改**为「当时只剩下面三条未裁决（M-4 / M-7 / H-2）」。

### R3-L-2（Low，已落改）架构文档三处指向不存在的 `docs/frame.md`、两处「四份基线」

- 位置：同文档 `:28`（依赖方向段）、`:85`（AD 验证判据）、`:131`（AD-8 决策行）；`:318`（实现期硬提醒）。
- 现象：`docs/frame.md` 是 v6 命名遗留、**仓库里不存在**（E75-S03 已按 `bad_spec` 记录一次）；本 epic
  的 AD-8 与硬提醒仍在教人「同批改 `docs/frame.md`」。同时「四份快照」也是旧数——现行五份
  （`public` / `routes` / `exceptions` / `transport_errors` / `error_codes`，`contract_snapshot.py --check` 实测五份）。
- 处置：**已落改**为 `docs/framework.md` §4.1 cli 子模块表 /「六、目录结构」，基线数改「**五份**」；
  保留一句「`docs/frame.md` 是 v6 命名遗留、不存在」，防止再被按字面新建第二份真相。

### R3-L-3（Low，记录不改）`docs/api/` 与 `docs/errors.md` 之外无新码的落点需求

- 核对：`project_channel_unavailable` 已进 `docs/errors.md` 表格行、`docs/framework.md` §4.16.1 两行、
  `web/app.js` 文案表；`docs/api/` 按包渲染 docstring，新增枚举成员自动可见（`tests/test_api_docs_pages.py`
  只管包级页集合）⇒ 无遗漏。

## 复核 R1 / R2 的落改（本镜头回看）

| 落改 | 复核结论 |
|---|---|
| `ws_submission_cache` 语义改「只清已完成项 + 容量优先淘汰已完成」 | 与模块 docstring / framework 两处措辞一致；注入即红（R2 反证 B） |
| 适配器 docstring 改写 + 连坐取消用例 | 与实测一致（去掉 shield 是兄弟收 `CancelledError`，不是 `InvalidStateError`）；行数仍 147 ≤ 150 预算 |
| `docs/errors.md` 37 / 78 | 与 AST 实测、`error_codes.json`（29）、CLI 12 条自洽 |
| 新增 `tests/test_ws_submission_cache.py` | 5 例全绿；`ruff format` 已格式化；未新增 `cli/*.py` ⇒ 布局白名单不需改 |

## 结论

**通过**（落改后复评）：Critical 0 / High 0 / Medium 2 / Low 3，全部当轮落改。E77 最初「单 lane 构建、
未跑三审」的差异已在 R1/R2/R3 补齐；文档面两处自相矛盾（M-1 / M-2）是本轮最值得记的教训——
**改 AD 正文时必须扫一遍同一文档里复述同一事实的索引段与「刻意留开项」**。

## 门禁实测（三审落改后）

| 命令 | 结果 |
|---|---|
| `pytest -q`（全量，带 node） | **5899 passed / 17 skipped / 30 deselected / 1 xfailed / 0 failed**（322s） |
| `pytest tests/network -q` | 742 passed |
| `ruff check src tests` / `ruff format --check src tests` | 全绿 / 512 files already formatted |
| `mypy src` | Success: no issues found in 242 source files |
| `bandit -r src/ -ll` | `No issues identified.`（4 处已知 `#nosec` 伴生噪声） |
| `python scripts/contract_snapshot.py --check` | 五份全 `[OK]` |
| `mkdocs build --strict` | exit 0，WARNING 计数 0 |
