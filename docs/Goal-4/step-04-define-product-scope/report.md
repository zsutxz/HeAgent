# Step 04 · define-product-scope 报告

- 目标：`Goal-4`
- 执行角色：`bmad-agent-pm`（PRD）→ `bmad-agent-po`（epic 切片），均为 headless 子会话
- 产物：
  - PRD：`prd-ws-remote-project-channel/prd-ws-remote-project-channel.md`（10 章）
  - 信封段：`brief.md` 的 `## 目标与产出`（Requirements R1–R14 / Constraints / Done when / Boundaries / Notes）
  - 票树：`tickets/tickets.toml`（`[[epic]]` ×3）+ 三个薄 epic 文件（`refined: false`，无 Requirements）
- 状态：**审批门待确认**

## PRD 要点

- 需求 14 条（R1–R14），优先级 P0 ×11 / P1 ×3；每条对得上 AC1–AC10 或标 `AC gap`
- 唯一 `AC gap` = **R7 断线重连 cursor 续流**（AC1–AC10 无一条覆盖）⇒ 指定由 E76 落成可跑断言
- 决策：D1–D10 沿用 ADR-005（冻结）+ N1–N8 本 PRD 新定（真源 = 注册表、注入式接线、id 保持 path-derived、`list()` 顺序以实现为准、注册表不可读分路、提交前二次校验、无会话即新建、`cancel_run` 与既有 cancel 同源）
- 非目标：NG1–NG13（ADR-005 挂账清单 + HTTP 回环面零变更 + id 语义不改）
- 未决决策 Q1–Q9 全部给默认处置（关闭时机统一 Step 06）

## Epic 切片

| Epic | 标题 | covers | after |
|---|---|---|---|
| `E74` `epic-74-ws-frame-contract` | 协议与帧契约 | R2 R5 R6 R8 R10 | —（risk medium） |
| `E75` `epic-75-project-channel-runtime` | 项目链运行时与投影注入 | R1 R3 R4 R13 | E74（risk high） |
| `E76` `epic-76-remote-surface-closeout` | 并发隔离与远程面收口 | R7 R9 R11 R12 R14 | E74 + E75（risk medium） |

- 切分轴 = **验收面**（契约 → 运行时 → 收口），不是代码目录：本需求横跨 `network/` · `agent/` · `cli/` 三层且层内文件高度重叠，按目录切会把一次协议变更拆成多次构建与多次快照漂移。
- 被否掉的切法：① 单 epic 全包（14 条需求混一次构建，红的层次定位不到）；② 每个 R 一个 epic（多数单 story 量级，构建顺序失去意义）；③ 按远程四件事切（共用同一帧族与注入端口，拆开即四次快照漂移）。
- 编号续编：既有最大 `E73` ⇒ 新 epic 取 `E74`/`E75`/`E76`，不复用。
- 目录形态：`epic-<编号>-<slug>`（票树脚本 `EPIC_RE` 只认 `epic-*`、`epic_folders()` 只 glob `epic-*`；纯 `<e编号>-…` 形态需改脚本且补丁会被角色包重装覆盖）。人读编号写三处：`code = "E74"` / `title` 前缀 `E74 · …` / frontmatter `code: E74`。

## 宿主验收核对

| 核对项 | 结果 | 证据 |
|---|---|---|
| 产品价值 / 范围 / 非目标 / 决策显式 | 通过 | PRD §1–§4、§6 |
| `tickets.py status` 读出全部 epic | 通过 | `epics` = 74 / 75 / 76 |
| `problems` 为空 | 通过 | `problems` = null |
| `unpinned_after` / `undeclared_after` / `order_conflict` 全空 | 通过 | 三者均为 `[]` |
| 新 epic `refined: false` 且无 Requirements | 通过 | 三份 epic 文件 frontmatter 均 `refined: false`，正文仅 Description / Outcome / Boundaries / 已知 Done when |
| `covers` 全覆盖 R1–R14 且不重叠 | 通过 | 5 + 4 + 5 = 14，逐条人工核对无重复 |
| `after` 引用更早 epic | 通过 | E74 `[]`、E75 `[E74]`、E76 `[E74, E75]` |
| 未产 `initiative-<slug>.md` / 未写 `active_initiative` | 通过 | goal 目录下无该文件；未动 `_bmad/custom/config.user.toml` |
| 文档链接守卫 | 通过 | `pytest tests/test_docs_links.py -q` → 4 passed |
