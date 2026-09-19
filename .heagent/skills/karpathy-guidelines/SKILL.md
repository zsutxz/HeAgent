---
name: karpathy-guidelines
description: "来自 Andrej Karpathy 对 LLM 编码通病的观察的行为准则：先想再写、简单优先、手术式改动、目标驱动验证。写 / 改 / 重构代码前应用，用来避免过度设计、避免顺手改动无关代码、避免把「大概能跑」当成功标准。"
created: 2026-09-15T16:00:10.214477
tags: [karpathy, coding-guidelines]
triggers: [karpathy, 卡帕西, 过度设计, 过度工程, avoid overcomplication, surgical change, simplicity first, think before coding, 最小改动, 手术式修改, 先说明假设, 只改必要的, 重构, refactor]
negative_triggers: [代码评审, 代码审查, code review, skill review, 技能评审]
priority: 2
usage_count: 10
last_used: "2026-09-19T13:40:24.728705"
---

# karpathy-guidelines

## Pattern
karpathy coding guidelines simplicity surgical changes minimal diff surface assumptions verifiable success criteria avoid overcomplication 过度设计 最小改动

## Steps
1. Think Before Coding 先想再写：动手前把假设显式写出来，别猜、别把困惑藏起来。存在多种解读时把选项摆给用户，不要沉默地替他选。发现更简单的做法就直接说，值得反对时就反对。有不清楚的地方就停下，指出究竟哪里不清楚，然后问。
2. Simplicity First 简单优先：只写解决问题所需的最小代码，不做任何投机性设计——不加没被要求的功能、不为一次性代码造抽象、不加没被要求的「灵活性 / 可配置性」、不为不可能发生的场景写错误处理。如果写了 200 行而 50 行就够，重写。自问一句：资深工程师会说这过度复杂吗？会就简化。
3. Surgical Changes 手术式改动：只碰必须碰的。不要顺手「改进」相邻的代码、注释或格式；不要重构没坏的东西；跟随既有风格，哪怕你更偏好别种写法；发现无关的死代码只提一句、不要删。当你的改动制造了孤儿（import / 变量 / 函数）时，只清理你自己造成的那些。判据：每一行改动都能直接追溯到用户的需求。
4. Goal-Driven Execution 目标驱动：先把任务转成可验证的成功标准，再循环到验证通过。示例：「加校验」变成「先为非法输入写测试，再让它们通过」；「修 bug」变成「先写能复现的测试，再让它通过」；「重构 X」变成「确保重构前后测试都通过」。多步任务先给一个简短计划，每步写明 verify 检查项。强成功标准让你能独立循环，弱标准（「让它能跑」）只会不断需要澄清。
5. Tradeoff 权衡：这套准则偏向谨慎而非速度。琐碎任务用判断力，不必全套走流程。
