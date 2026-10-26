---
title: '57-1 实现会话收尾清单落盘'
type: 'docs'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
baseline_commit: '54aa99e9a988839b1c4cd05b200069f1b350e9c9'
context: []
---

<!-- 闭环 sprint-status 4 条 open action items：epic-54-retro-item-6 / item-7、epic-53-retro-item-8 / item-9。 -->

## Intent

**Problem:** 4 条流程纪律 action item 的共同落点「实现会话收尾清单」在仓库中不存在——53/54 两份 retro 各自提案「并入收尾清单」，但清单从未建立，规则无处附着，同类失误（状态漏回写、评审未读全文、squash 丢 backup、docs 提交绕过契约测试）会复发。

**Approach:** 在 `docs/iteration.md` §一「迭代模型」新增 §1.6「实现会话收尾清单」，一次落盘 4 条规则：

1. **状态回写**（54-A3）：story 实现完成即回写两处——story 文件 frontmatter `status` + sprint-status 对应 story 行；会话收尾前核对无 `in-progress`/`review` 残留。
2. **squash 保留 backup ref**（54-A4）：squash/amend 类改写历史操作后必须真实创建 `git branch backup/pre-<op>-<short-sha>` 并保留至验收期满；提交信息引用的 backup ref 必须真实存在。
3. **评审前置**（53-A53-1）：评审/验收论断前必须读完 story 全文 + 实际运行行为验证（跑测试/复现路径），禁止仅凭 diff 或描述下结论。
4. **契约测试子集不豁免**（53-A53-2）：政策/台账/纯 docs 类提交也须跑 `pytest tests/test_architecture_contracts.py -q`（台账契约与文档强耦合，非代码提交同样能打破）。

## Acceptance Criteria

1. `docs/iteration.md` 存在 §1.6，含上述 4 条规则，每条注明来源 retro 与根因。
2. sprint-status 4 条对应 action item 状态转 `done`，备注指向 §1.6。
3. 纯文档变更仍跑契约测试子集通过（按规则 4 自证）。
