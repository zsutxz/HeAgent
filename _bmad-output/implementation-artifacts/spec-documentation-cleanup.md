---
title: '整理项目文档导航与事实状态'
type: 'chore'
created: '2026-09-02'
status: 'done'
review_loop_iteration: 0
baseline_commit: '2ee6fdaa827d36b61725fb988f636e16828b535e'
context: ['E:\\AI\\HeAgent\\docs\\README.md', 'E:\\AI\\HeAgent\\_bmad-output\\README.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 项目文档已有完整内容，但入口导航、当前实现状态和历史 BMad 产物的描述存在失配，容易让维护者沿着过时路径阅读或误判项目状态。

**Approach:** 以当前 `src/`、配置文件和实际目录为事实基准，修正 README、`docs/README.md` 与 `_bmad-output/README.md` 的导航、状态和链接说明；保留历史产物原貌，不重写专题架构内容。

## Boundaries & Constraints

**Always:** 文档输出使用中文；相对链接必须指向仓库内现有文件或目录；明确区分当前代码事实与历史规划产物；保留现有安全声明和“非安全边界”立场。

**Ask First:** 若发现需要改变架构结论、删除历史文档或重命名大量目录，先停止并征求确认。

**Never:** 不修改 `src/` 代码；不删除 `_bmad-output/` 产物；不把规划文档当作当前实现的权威；不伪造不存在的部署能力或测试状态。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|-----------------------------|----------------|
| HAPPY_PATH | README、docs 索引和 `_bmad-output` 目录 | 导航与实际文件、周期和事实来源一致 | N/A |
| STALE_REFERENCE | 文档引用已移动、遗漏或不存在的路径 | 改为现有路径，或明确标注历史归档/未实现 | 不确定时保留并标记，不猜测 |
| LICENSE_STATUS | 根目录存在 `LICENSE` | README 说明实际许可证文件和 MIT 状态 | 以文件内容为准 |

</frozen-after-approval>

## Code Map

- `README.md` — 面向首次使用者的项目状态、文档地图和许可证说明；当前许可证段落与根目录实际文件冲突。
- `docs/README.md` — 专题文档索引与事实来源优先级；需补充现有专题文档并保持阅读职责清晰。
- `_bmad-output/README.md` — BMad 历史产物导航；需以实际 `epics/` 目录校正周期清单、数量和归档说明。
- `docs/iteration.md` — 迭代历史与当前状态的补充入口；只校验导航引用，不重写历史记录。
- `docs/frame.md` — 架构事实参考；作为链接和模块名称的核对来源，不在本轮重构其正文。
- `deploy/README.md` — 部署资产边界；作为 README 文档地图的目标文件和状态核对来源。

## Tasks & Acceptance

**Execution:**
- [x] `README.md` — 修正许可证状态、文档地图和明显过时的入口描述 — 让首次阅读者获得可验证的当前信息。
- [x] `docs/README.md` — 补齐专题文档入口并明确各文档职责与事实来源 — 避免索引遗漏和职责重叠。
- [x] `_bmad-output/README.md` — 根据实际目录修正周期列表、数量和归档说明 — 使历史产物导航可检索。
- [x] `scripts/quality_gate.py` 或等价只读检查 — 验证 Markdown 相对链接和文档中的关键路径存在 — 防止整理引入断链。

**Acceptance Criteria:**
- Given 根目录和 `docs/`、`_bmad-output/epics/` 的实际文件结构，when 阅读三个入口索引，then 每个列出的当前文档和周期路径都存在且职责明确。
- Given 根目录存在 `LICENSE` 且内容为 MIT 许可证，when 阅读 README 许可证段落，then 文档不再声称缺少许可证。
- Given `_bmad-output/` 仅作为历史规划产物，when 当前实现与历史文档冲突，then 入口文档明确以 `src/` 和配置样例为准。
- Given 文档整理完成，when 执行链接/路径检查和 `git diff --check`，then 检查通过且不修改源代码。

## Design Notes

本轮采用“入口文档收敛、专题正文少动”的策略：README 负责使用者入口，`docs/README.md` 负责专题索引，`_bmad-output/README.md` 负责历史产物导航。这样可以降低大规模改写架构文档造成事实漂移的风险。

## Verification

**Commands:**
- `git diff --check` — expected: 无空白错误。
- `python scripts/quality_gate.py` — expected: 现有质量门禁通过；若环境缺少外部依赖，记录明确失败原因。
- PowerShell 文档链接/路径检查 — expected: 入口文档引用的仓库内路径全部存在。

## Suggested Review Order

**事实来源与入口**

- 先看用户入口与许可证事实
  [`README.md:19`](../../README.md#L19)
- 再看专题文档职责边界
  [`README.md:5`](../../docs/README.md#L5)

**历史产物导航**

- 核对周期目录与状态权威
  [`README.md:33`](../../_bmad-output/README.md#L33)
- 查看新增周期映射
  [`README.md:49`](../../_bmad-output/README.md#L49)

**实现对照**

- 核对当前模块目录
  [`frame.md:687`](../../docs/frame.md#L687)
- 核对目标工作流入口
  [`bmad-heagent-plan.md:123`](../../docs/bmad-heagent-plan.md#L123)

**验证与外围文档**

- 核对版本发布前置条件
  [`README.md:101`](../../deploy/README.md#L101)
- 核对当前状态与测试说明
  [`iteration.md:274`](../../docs/iteration.md#L274)
