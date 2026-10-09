---
id: 52-4
title: 声明面收口——loader 提示、技能包与文档
status: done
parent_epic: E52
priority: P2
depends_on: [52-2]
blocks: [52-5]
created: '2026-10-09'
---

## 交付记录（2026-10-09）

- loader `_parallel_limit` WARNING → 条件说明 INFO（`tests/test_workflow_resources.py:76` 翻转 + 无 WARNING 断言）。
- 技能包：Step 06 增「并行声明与写集完备性」段 + 三字段 bullet；Step 07 正文改写（七条件逐字、
  围栏/审计/撤销闩、批=单 checkpoint 单元每批一次确认、验证工作区 per-story `.heagent/tmp/<goal-id>/s-<n>/`）；
  :59 概览行「同一 Epic 内批量」旧语义一并修正；`templates/STORY.md` 补三字段示例与完备性提示。
  revision 已由 66cf196 预先 bump "1"→"2"，本批内容补齐该契约。
- `docs/frame.md`：4.13 story_loop bullet 更新 + 新增「声明门控并行与写集围栏」小节（path_safety 同构
  非安全边界措辞）；4.16 事件表 `workflow_step_*` 行更新 + 新增 `workflow_story_batch_scheduled` /
  `workflow_write_audit` 两行。
- `docs/goal-workflow.md`：新增「声明门控并行」节（七条件与 spine §2 逐字一致）+ Phase 5 状态行更新。
- 声明翻转演示（AC 3）由 52-2 测试锚点留档：`test_declared_disjoint_stories_run_parallel_and_checkpointed`
  （峰值并发 2）+ `test_non_conforming_declarations_degrade_to_serial` 参数化反例矩阵，`src/` 零改动。

# Story 52-4：声明面收口——loader 提示、技能包与文档

## 用户故事

作为 workflow 模板作者，我希望包与文档如实描述「声明门控并行」的语义，step 06 产出的 story 清单自带
三字段与写集完备性指导，不再有「文档说并行、代码只串行」的裂缝。

## 声明面（主要交付物）

- `.heagent/skills/he-goal/workflow.md`（**revision bump "1" → "2"**，he-goal 冻结契约）：
  - Step 07 正文（现 :222-227 描述已删除的批次语义）改写：串行默认、七条件声明门控并行、
    写集围栏与 Git 审计语义、批 = 单 checkpoint 单元（manual 确认每批一次）、
    验证工作区细化 per-story 子目录 `.heagent/tmp/<goal-id>/s-<n>/`；
  - Step 06：指导生成 `02-epics.md` 时逐 story 声明 `depends_on` / `parallel_group` / `write_set`，
    且 write_set 须覆盖该 story 及其验证命令实际修改的全部 tracked 文件（新源文件声明进 write_set）；
  - 正文零「并发度=声明值」的暗示——声明只是门控输入。
- `.heagent/skills/he-goal/templates/STORY.md`：补三字段示例与写集完备性提示。
- `docs/frame.md`：4.16 事件表更新（`workflow_step_*` 行措辞、新增 `workflow_story_batch_scheduled`
  与 `workflow_write_audit` 行）；补写集围栏小节（纵深防御非安全边界措辞，对齐 path_safety 先例）。
- `docs/goal-workflow.md`：并行语义、七条件、审计与撤销闩、恢复语义、worktree 后续层定位（AD-20）。

## 引擎面（最小）

- `src/heagent/goal/workflow_loader.py` `_parallel_limit`：fail-closed WARNING 改条件说明 INFO
  （">1 = 声明门控并行可用，实际并发仍受 write_set / parallel_group / depends_on 门控"）。
- `tests/test_workflow_resources.py:76` 断言同步（INFO 不再 WARNING）。

## 验收标准

1. `test_workflow_resources.py:76` 翻转后全绿；`pytest tests/test_workflow_resources.py -q` 无回归。
2. revision bump 后既有 goal 恢复按冻结契约处理（漂移 fail-loud 行为有既有测试锚点，不改引擎）。
3. **只改声明即可改变并行授权结果**（AD-13/14 验收演示）：引擎级测试里给 story 文档加/去
   `parallel_group` → 批派生翻转，`src/` 零改动。
4. frame.md 事件表与新事件一致；goal-workflow.md 与 spine 七条件逐字一致。
5. 技能包内不再存在与 51-8 后实际行为矛盾的批次并发描述（grep 无残留）。

## 任务

- [ ] loader INFO + 测试翻转。
- [ ] 技能包正文与模板改写 + revision bump。
- [ ] frame.md / goal-workflow.md 收口。
- [ ] 声明翻转演示（测试形态留档）。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_workflow_resources.py tests/test_goal_declarative_workflow.py -q
pytest tests/test_architecture_contracts.py -q
pytest
ruff check src tests
grep -n "批次方式并发" .heagent/skills/he-goal/workflow.md   # 预期无输出
```

### Review Findings（2026-10-09 四层对抗式评审）

- [x] [Review][Decision→已裁决：改文档钉实际形状] frame.md 事件表「并行批逐成员各发一组 workflow_step_*」与实现不符（实际单组：started 带首成员、completed 无 story 归因）——改文档如实钉形状，或改实现逐成员发事件 [docs/frame.md:1172]
- [x] [Review][Patch] goal-workflow.md 残留「487 passed（2026-10-07）」过期验证数字 [docs/goal-workflow.md]
- [x] [Review][Patch] max_parallel_stories 合法域 1..5 与超限行为未进声明面 [workflow.md / STORY.md]
