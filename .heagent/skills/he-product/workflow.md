---
name: he-product
entrypoint: goal
on_create: persist_goal_identity
step_executor: subagent
checkpoint_mode: prompt
required_resources: prompt-template.md, gate-template.md
---

# product discovery workflow（产品探索工作流）

本文件是本工作流的**完整可执行契约**：三步把一个模糊的产品想法收敛成可验证的需求与验收口径。
全部正文与产物使用中文；持久产物写入项目输出根 `_he-output/` 之下，源代码留在仓库既有位置。
本工作流不写任何代码：实现类诉求应在验收口径冻结后另行立项。

## Step 01: clarify-needs（需求澄清）
input: user intent, existing project context
output: 需求清单, 假设与开放问题
validation: section: 需求清单; 每条需求可验证，事实与假设分开列出，未决问题显式留白

围绕原始需求做需求澄清：区分事实与假设，识别干系人与使用场景，把模糊表述收敛成明确、可验证、
无内部矛盾的需求清单。未经证实的市场或用户断言一律记为假设或开放问题，不得写成本产品承诺。
需求文档的文件名以 prompt 里 `Goal document` 行为准；「原始需求」段逐字冻结只读。
最终回复必须含 `## 需求清单` 章节，与写入需求文档的内容一致。

## Step 02: define-scope（范围与非目标）
input: 需求清单
output: 范围边界, 非目标清单, 优先级排序
validation: section: 范围与非目标; 范围边界、非目标与优先级全部显式且互相不矛盾

把需求清单收敛成本次交付的范围：明确「做什么」与「明确不做什么」，按价值与依赖排序，
记录关键产品决策及其理由。范围之外的诉求一律写进非目标清单，不留悬空引用。
最终回复必须含 `## 范围与非目标` 章节。

## Step 03: acceptance-criteria（验收口径）
input: 范围边界, 非目标清单
output: 验收口径
checkpoint: true
validation: section: 验收口径; 每条验收标准可判定且覆盖全部范围内需求

为范围内每条需求写验收口径：可判定（Given/When/Then 或同等可验证形式）、覆盖完整、
与范围边界一致。验收口径一经写出即冻结：只有人能改，后续任何步骤不得改写口径迁就实现。
最终回复必须含 `## 验收口径` 章节。
