---
name: he-security
entrypoint: goal
on_create: persist_goal_identity
step_executor: subagent
checkpoint_mode: prompt
prompt_template: templates/prompt.md
gate_template: templates/gate.md
---

# security assessment workflow（安全评估工作流）

本文件是本工作流的**完整可执行契约**：三步完成「攻击面收集 → 风险评估 → 处置方案」。
全部正文与产物使用中文；持久产物写入项目输出根 `_he-output/` 之下。全程**只读**：
不执行利用代码、不做拒绝服务验证、不关闭或绕过任何防御机制；处置步骤只产出书面方案。

## Step 01: collect-surface（攻击面收集）
input: user intent, existing project context
output: 攻击面清单, 信任边界图
validation: section: 攻击面清单; 每个入口带位置、暴露方式与可达的资产，未核实的项显式标为未验证

从代码、配置与部署声明中收集攻击面：外部入口、认证与授权点、反序列化与命令执行点、
跨信任边界的数据流。逐项记录位置、暴露方式与可达资产；未经复核的项标为「未验证」，
不得当作事实。本步骤只读。
最终回复必须含 `## 攻击面清单` 章节。

## Step 02: assess-risks（风险评估）
input: 攻击面清单, 信任边界图
output: 风险登记册
validation: section: 风险登记册; 每条风险带证据位置、影响与可行性的说明及优先级

对攻击面逐项评估风险：引用清单里的证据位置，说明影响（可达资产与最坏后果）、
利用可行性（前提条件）与优先级。推断性结论必须标注依据与不确定性，不得以结论代替证据。
最终回复必须含 `## 风险登记册` 章节。

## Step 03: remediation-plan（处置方案）
input: 风险登记册
output: 处置方案
checkpoint: true
validation: section: 处置方案; 每条中高风险都有显式处置决定且方案不引入新的信任边界缺口

按风险优先级给出处置方案：每条中高风险都有显式决定（缓解 / 转移 / 接受，接受必须带理由），
缓解措施落到确切位置（文件 / 配置点）并复核不引入新的信任边界缺口。方案一经写出即冻结：
只有人能改，实施另行立项。
最终回复必须含 `## 处置方案` 章节。
