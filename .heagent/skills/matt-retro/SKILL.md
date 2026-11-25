---
name: matt-retro
description: "对一次编码会话做复盘，产出针对编码代理**环境**的改进建议：导航指针、自动化检查、编码规范、steering 文件、工具经济、信息获取；不改代码。 | Retrospective on a coding session: suggest improvements to the coding agent's environment (navigation pointers, automated checks, coding standards, steering files, tool economy, information access), not the code."
triggers: [复盘这次会话, 做一次 retro, 这次构建哪里可以更好, 什么能预防这个 bug, run a retro, retrospective on this session]
negative_triggers: [继续实现, 评审改动, 排查失败原因, 写规格]
---

# matt-retro

## Pattern
做什么：回看一次编码会话，提出对代理**环境**（不是代码）的改进——导航指针、自动化检查、编码规范、steering 文件、工具经济、信息获取——让下一次构建从更好的环境起步。
何时用：一次构建之后、尤其是走得磕磕绊绊的那次；bug 修完也可以在同一会话里跑，问「什么本可以预防这个 bug」。
原则：机械性失误转成确定性检查，判断题转成编码规范；报告只给候选，按严重度排序，不直接改代码。
原文存档见 references/ORIGINAL.md（1.3.2 版）。

## Steps
1. 先用 matt-writing-for-agents 取写作风格指南。
2. 读用户指定会话的一手材料（可能要翻本机会话日志）；没指定就默认当前会话。
3. 按七类找改进候选：导航（找文件是否费时、是否存在隐藏依赖）、自动化检查（代理犯的错能否被 lint/类型/测试/文件系统检查抓住，先读仓库现有 check 命令与 CI，别重造；完全没有护栏本身就是一条发现）、编码规范（评审代理是否该新增或删改规则）、全局 AGENTS.md（是否过大、是否有指令该挪到规范或检查）、工具经济（是否有昂贵且可精简的工具调用、是否有 token 低效的自建 CLI/MCP）、空操作指令（steering 文件里对行为无影响的条目）、信息获取（能否给代理更多一手信息，如 dev server 日志、第三方只读访问）。
4. 先给违规分类：机械违规（固定语法模式、禁用 API、导入形状、文件位置）默认写确定性检查——自定义 linter 规则、pre-commit 钩子或 CI job，选仓库语言与现有护栏最便宜的那个；CODING_STANDARDS.md 只留给真正的判断题（跨文件一致性、贴合周边风格这类护栏无法替代的判断）。
5. 记住实现与评审的分工：实现代理上下文压力最大，评审代理只拿 diff、压力最小，所以规范应由评审代理施加而不是实现代理。
6. 文件层面收紧：CLAUDE.md/AGENTS.md 只放导航指针、用量极省；编码规范文件超过约 1000 行就加指向 docs 目录的导航指针；写新文档前先找既有 docs，技能里的文档按 matt-writing-for-agents 的口径写。
7. 按严重度排序把候选清单呈给用户，等选择再动手。
