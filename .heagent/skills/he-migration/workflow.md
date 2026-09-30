---
name: he-migration
entrypoint: goal
on_create: persist_goal_identity
step_executor: subagent
checkpoint_mode: prompt
required_resources: prompt-template.md, gate-template.md
---

# migration workflow（迁移工作流）

本文件是本工作流的**完整可执行契约**：四步完成「盘点 → 映射 → 迁移 → 回滚预案」的受控迁移。
全部正文与产物使用中文；持久产物写入项目输出根 `_he-output/` 之下，源系统与目标系统留在
既有位置。迁移以「可回滚」为第一原则：回滚预案冻结之前，不得执行任何不可逆操作。

## Step 01: inventory-sources（源盘点）
input: user intent, existing project context
output: 源清单, 依赖与风险清单
validation: section: 源清单; 每项源对象带位置、用途与依赖，未探明的项显式标为未知

盘点待迁移的源对象（数据 / 配置 / 组件）：逐项记录位置、用途、规模与依赖关系，
标注迁移风险。探不明的项显式标为「未知」，不得臆测补齐。本步骤只读，不得改动源系统。
最终回复必须含 `## 源清单` 章节。

## Step 02: mapping-rules（映射规则）
input: 源清单, 依赖与风险清单
output: 映射表, 转换规则
validation: section: 映射规则; 源清单中每一项都有明确去向或显式的「不迁移」决定

为源清单逐项确定去向：映射表覆盖每一项（迁移到哪、如何转换），不迁移的项也要显式写出
「不迁移」及理由。转换规则必须可判定，不留「具体再看」的悬空条目。本步骤只读。
最终回复必须含 `## 映射规则` 章节。

## Step 03: execute-migration（执行迁移）
input: 映射表, 转换规则
output: 迁移记录, 差异报告
validation: section: 迁移记录; 逐项按映射表执行并记录结果，偏差与失败显式列出

按映射表逐项执行迁移：记录每项的执行结果；与映射规则的偏差、失败项显式列出，
不得静默跳过。执行范围严格限于映射表，不碰「不迁移」清单。
最终回复必须含 `## 迁移记录` 章节与差异报告。

## Step 04: rollback-plan（回滚预案）
input: 迁移记录, 差异报告
output: 回滚预案
checkpoint: true
validation: section: 回滚预案; 每类不可逆操作都有可执行的回退步骤与验证判据

针对迁移记录中的每类不可逆操作写回滚预案：回退步骤可执行（确切命令或操作序列）、
有验证判据（如何确认回退成功）。预案作为最终交付冻结：只有人能改。
最终回复必须含 `## 回滚预案` 章节。
