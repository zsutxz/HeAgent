---
type: migration
title: "Move v6 planning and implementation artifacts into the v7 initiative layout"
status: draft
created: 2026-11-15
module: method
from: "6"
to: "7"
---

# 迁移计划：v6 产物 → v7 initiative 布局

> 备份：`.v6-v7-migration-backup-20261115-1530/`（`_bmad/` + `_bmad-output/` 全量，341 文件已核对；内部 `*` .gitignore，永不提交）。批准前唯一写入 = 本计划文件 + 该备份。

## 一、问答记录

| 问题 | 答案 |
|---|---|
| 规划内容 / 实现内容位置是否正确，是否另有他处？ | 是：planning=`_bmad-output/planning-artifacts/`（4 文件）、implementation=`_bmad-output/implementation-artifacts/`（8 文件）。另处内容 = `epics/`（27 周期目录 306 文件）+ 根级 5 台账文件，用户确认**原地保留**（历史归档，非 v6 源文件夹） |
| 是否拆独立仓库 / workspace？ | 否——store 继续随主仓库 git 管理，所有移动用 `git mv` 保历史 |
| Story 是否有进行中/评审中需先在 v6 收尾？ | 无（sprint-status.yaml 无 in-progress/review/blocked） |

## 二、移动映射（Documents）

| v6 源 | v7 目标 | 处理 |
|---|---|---|
| `planning-artifacts/`（目录整体） | `initiative-heagent/` | 目录更名，未识别文件随迁 |
| `planning-artifacts/prd.md` | `initiative-heagent/prd-heagent/prd-heagent.md` | 平文件入同名文件夹、主文件随文件夹名；frontmatter 补 `type: prd`（title/created 已有） |
| `planning-artifacts/project-improvement-report.md` | `initiative-heagent/project-improvement-report/project-improvement-report.md` | 同上，补 `type: report` |
| `planning-artifacts/story-estimates.md` | `initiative-heagent/story-estimates/story-estimates.md` | 同上，补 `type: report` |
| `planning-artifacts/epics.md` | 票树（见 §三）→ `initiative-heagent/archive-v6/epics.md` | 转写后原样归档，不改内容 |
| `_bmad-output/sprint-status.yaml` | `initiative-heagent/archive-v6/sprint-status.yaml` | 原样归档（action_items 见 §五） |

## 三、票树（The ticket tree）

- Initiative 信封 `initiative-heagent/initiative-heagent.md`：Title=HeAgent 项目改进计划；Description/Outcome 取 PRD §一（背景+四目标）；Requirements = **R1–R16（FR1–FR16 一行一条）+ R17–R23（NFR1–7，横切、无 epic covers）**；Constraints = PRD §四（架构 3/测试 3/性能 2/安全 2）；Done when = PRD §六五组验收指标；`sources:` prd-heagent/；`companions:` 无；References 列三个文档文件夹；Notes 记 action item（见 §五）。
- 8 个 epic（slug 取标题、covers 取 FR Coverage Map→R 映射）：epic-代码架构重构(covers R1,R3) / epic-测试体系增强(R5,R6) / epic-用户体验优化(R7,R9,R10,R11) / epic-工程自动化(R12,R13) / epic-性能优化(R4) / epic-安全增强(R14,R15,R16) / epic-文档与API(R8) / epic-异常体系完善(R2)。Epic 文件：Description/Outcome 取 epics.md 各 Epic 目标行；Requirements 为所辖 R 行；`parent: initiative-heagent`；**全部 backlog 不写 status 行**。
- **59 个 `[[entry]]`** 与 epics.md `### Story N.M:` 一一对应（title 取原 Story 标题；description=「我想要」句改写为完成时态；verify=验收标准蒸馏一行；after=[]；hitl=false；risk=low；v6_key=`N-M-<slug>`）。covers 映射：

| Epic | Story→covers |
|---|---|
| 1 | 1.1–1.4→R1；1.5–1.7→R3 |
| 2 | 2.1–2.5→R5；2.6–2.8→R6 |
| 3 | 3.1–3.4→R7；3.5–3.7→R9；3.8–3.11→R10；3.12–3.14→R11 |
| 4 | 4.1–4.5→R12；4.6–4.9→R13 |
| 5 | 5.1–5.5→R4 |
| 6 | 6.1–6.5→R14；6.6–6.8→R15；6.9–6.10→R16 |
| 7 | 7.1–7.3→R8 |
| 8 | 8.1–8.3→R2 |

## 四、Story 状态与 build record

- sprint-status.yaml **不含任何改进计划 story 键**（grep=0）→ 58 个 story 无 build record、tracking 无键 ⇒ **entry only（无 plan）**，状态语义 = backlog。
- **例外 Story 1.4（拆分 config/catalog.py）**：epics.md 勘误（2026-11-13，用户授权）明确「已交付，标 Done」⇒ 写**最小 plan** `story-config-catalog-split-plan.md`（frontmatter `ticket: 4`、`status: done`、`type: refactor`），正文声明 **build record 缺失、证据为勘误非 sprint-status**，不推断 baseline_revision。计划批准即视为对该状态的确认。
- 无 6.13 预发布 spec 文件夹命中折叠规则（`.memlog.md` 仅存在于 epics/ 历史目录内，非 `spec-<slug>/` 形态）→ 无折叠动作。

## 五、原地保留（含理由）与 action item

| 保留项 | 理由 |
|---|---|
| `epic-overview.md` / `open-items.md` / `README.md` / `retrospective-all-cycles.md`（根级） | 迁移不识别的项目自建台账体系；被契约测试钉死（test_deferred_ledger 67 ID / test_deferred_id_registry 四站点）；用户确认保留。**例外**：其中指向已移动路径的引用行按 §六 改写（仅路径文本，不碰 ID/台账节） |
| `epics/`（27 周期目录，306 文件，61 个已交付 epic 的 story/retro/spec 归档） | 非两个源文件夹内容；历史档案，用户确认保留。epic-61（唯一 backlog）的 SPEC.md+.memlog.md 一并保留（非 spec-<slug>/ 文件夹形态，不触发预发布折叠） |
| `implementation-artifacts/`（arch-optimization-cycle/ 7 文件 + README.md） | 实现文件夹中无任何改进计划 story 的 build record，迁移不识别 → 原地保留 |
| 根级无其他散文件 | — |

- action_items 唯一 open 项（`epic-52-retro-item-1-真实-llm-全链冒烟…`，owner=tan，epic=52）⇒ 按规则记入 initiative Notes 为 `Action item:` 行（属历史 Epic 52 的 provenance，非本计划 8 epic）；done 项丢弃。

## 六、路径改写（Path rewrites）

**store 内（批准后改写，仅动路径文本/链接目标，不碰 ID、台账节、勘误表）：**

| 文件 | 位置 | 改写 |
|---|---|---|
| `epic-overview.md` | :3、:11、:13、:41、:52、:53 权威性提法；:90、:114 文档地图行 | `sprint-status.yaml` → `initiative-heagent/archive-v6/sprint-status.yaml`；`planning-artifacts/` → `initiative-heagent/`（地图行路径与说明更新） |
| `README.md` | :3、:12、:21、:41 及目录树块 | 同上两路径改写 + 树中 planning-artifacts 行更新 |
| `retrospective-all-cycles.md` | :8、:147、:163 口径提法 | sprint-status.yaml 权威口径注明已归档至新路径 |
| `open-items.md` | 无命中（已核） | 不动 |

**store 外（只登记、永不改动，由用户自行更新）：** `docs/bmad/learning_bmad.md`、`.heagent/skills/he-goal/workflow.md`、`.heagent/skills/loop/workflow.md`、`.claude/reviews/full-codebase-2026-07-20.md`（`.heagent/tmp/baseline-*` 为临时基线副本，随环境自净）。

## 七、配置与清理（Configuration and cleanup）

- `_bmad/custom/config.user.toml` `[core]` 写入 `active_initiative = "initiative-heagent"`（文件新建）。**注意**：该文件被 `_bmad/custom/.gitignore`（`*.user.toml`）忽略，属个人配置不入库——本地生效、不随仓库分发，此为 installer 设计。
- 删除清空后的 `planning-artifacts/`；新建空目录 `initiative-heagent/backlog/`、`initiative-heagent/archive/` 各补 `.gitkeep`（initiative/tickets 均有内容无需 gitkeep）。
- `_bmad/` 除上述 config.user.toml 外零改动（bmad setup 管辖）。

## 八、提交序列（guide 要求逐步提交、永不提交备份）

前置状态=HEAD f293521 干净 ✓。执行批准后拟 3 笔提交（用户已在计划批准时一并授权）：

1. `docs(bmad): migration step 7 —— 规划文档迁入 initiative-heagent`（步骤 7 后）
2. `docs(bmad): migration step 8 —— 写入 initiative 票树（8 epic / 59 entry / 1 最小 plan）`（步骤 8 后）
3. `docs(bmad): migration step 13+14 —— 台账路径改写 + active_initiative 配置 + 空目录清理`（步骤 13、14 后，config.user.toml 因 gitignore 天然不入库）

## 九、验证清单（步骤 15 执行后逐项记录结果于此）

[待执行后回填 14 项 checklist 结果 + 契约测试 34 项复跑结果 + `tickets.py status` 输出]
