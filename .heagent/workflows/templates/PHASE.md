---
type: phase
status: planning
title: <阶段标题>
role: <已安装的 skill id>
checkpoint: true
---
# <阶段标题>

> Phase 不是 `artifacts.py` 的 Goal/Epic/Story 层级产物，不能传给 `parse_artifact()`。
> `role` 必须解析到 `.heagent/skills/<role>/SKILL.md`；不支持内联角色契约。

## Inputs
- <前序步骤提供的产物或上下文>
## Outputs
- <本阶段产出的持久化产物>
## Gates
- <进入下一步骤前必须满足的确定性条件>

## Write Boundary

<本阶段允许创建或修改的内容，以及保持只读的内容>
