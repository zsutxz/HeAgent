---
name: matt-implement-spec
description: "按 spec 与 tickets 并行实现：把票当任务图取 frontier，用 implementer 子代理在各自 worktree 分支上 TDD 实现，汇到集成分支后统一 code-review，最后按 tracker 关票。 | Implement a spec and its tickets as a task graph: parallel implementer subagents on per-ticket worktrees, merged to one integration branch, one code review, then close the tickets."
triggers: [实现整份 spec, 按 spec 并行实现, 把这批票一次做完, 并行实现这些 ticket, implement the spec, implement these tickets in parallel, run implement-spec]
negative_triggers: [逐票实现, 评审改动, 排查失败原因, 写规格]
---

# matt-implement-spec

## Pattern
做什么：把一份 spec 及其关联 tickets 当作**任务图**实现——任意时刻都有可抓取的 frontier 票，用 implementer 子代理并发做，全部汇到一个**集成分支**，最后一次 code-review，再按 issue tracker 的收口方式关票。
何时用：用户给了 spec + tickets 并希望**一次并行推进整份规格**时；想逐票自己驱动、每票之间 /clear 的，走 matt-implement；只想评审既有改动走 matt-code-review。
要点：子代理一律用**全新上下文窗口**启动；与子代理的沟通要**稀疏**，主要靠 context 指针（spec、票、调研笔记、已有 commit），不复制已经能通过指针拿到的信息。implementer 子代理尽量放到后台跑以获得最大并发。
原文存档见 references/ORIGINAL.md（1.3.2 版）。

## Steps
1. 先读 spec 与关联 tickets，理清任务图，认准当前可抓取的 frontier（tickets 不是步骤清单，而是带 blocking 关系的图）。
2. 可选：先派一个探索子代理收集票里需要的代码库与外部文档信息，把笔记存到仓库外的共享目录供后续所有子代理读，让 implementer 子代理专注实现而不是探索。
3. 建集成分支；若 issue tracker 用 PR 收口、或用户要求 PR，等第 5 步完成第一次合并后再开 draft PR（分支上没有 main 之后的 commit 时开不出来），并标注关闭对应 spec 与 tickets。
4. 为 frontier 上的每张票派 implementer 子代理，各自独立 worktree 与独立分支：开工前确认所在 worktree 基于集成分支、否则 reset 上去；用 matt-tdd 实现该票；报完成前把集成分支 tip 合进自己的分支。
5. 某个 implementer 子代理完成后，用 merger 子代理把它的分支合进集成分支。
6. 合并让 frontier 前进就继续派新的 implementer 子代理，把并发用满。
7. 全部票完成后，在集成分支上跑 matt-code-review，并把评审提出的所有问题交给同一个 implementer 子代理统一修完。
8. 有 draft PR 就转为 ready for review；否则按 tracker 的收口方式逐票关闭，并报告集成分支。
9. 清理所有 implementer 子代理留下的 worktree。
