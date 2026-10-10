---
name: he-engineering
entrypoint: goal
on_create: persist_goal_identity
step_executor: subagent
revision: "2"
checkpoint_mode: prompt
prompt_template: templates/prompt.md
gate_template: templates/gate.md
---

# engineering delivery workflow（工程实现工作流）

本文件是本工作流的**完整可执行契约**：三步完成「方案 → 实现 → 验证」的工程交付。
全部正文与产物使用中文；方案类持久产物写入项目输出根 `_he-output/` 之下，源代码留在
仓库既有位置。frontmatter 的 `revision: "2"` 是**声明 revision**：包内容改动不触发派生
漂移，改包必须同步推进 revision。

## Step 01: design-approach（方案设计）
input: user intent, existing project context
output: 技术方案, 实现约束与写集
validation: section: 技术方案; 边界、接口与失败处理显式，写集列出确切文件路径

产出精简的技术方案：模块归属、接口形状、不变量与失败处理，并列出实现步骤允许改动的
写集（确切文件路径）。只规划，不实现；写集之外的一切保持只读。
最终回复必须含 `## 技术方案` 章节。

## Step 02: implement-change（实现变更）
input: 技术方案, 实现约束与写集
output: 实现摘要, 变更文件清单
validation: section: 实现摘要; 改动严格落在方案声明的写集内且记录每处改动的动机

按方案实现变更：只改写集内的文件，逐处记录动机；发现方案本身有缺陷时停下来在最终回复
中显式提出，不得就地偏离方案。最终回复必须含 `## 实现摘要` 章节与变更文件清单。

## Step 03: verify-change（验证变更）
input: 实现摘要, 变更文件清单
output: 验证报告
checkpoint: true
validation: section: 验证报告; 每条验证都记录确切命令与观察结果，失败显式呈现不以声称代替

验证实现：重跑受影响的测试或执行方案声明的验证命令，记录确切命令、退出码与观察结果。
失败的验证如实呈现；不允许用「应该通过」之类声称代替已运行的证据。
最终回复必须含 `## 验证报告` 章节。
