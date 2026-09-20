"""``/goal`` 域层 —— 目标驱动工作流中可独立成模块的部分。

- 需求文档层（:mod:`heagent.goal.document`）：goal 目录的 ``require.md``（存量 goal 为
  ``GOAL.md``）的定位、命名与增量更新——文档约定一律不落进 CLI 代码。
- 声明式工作流装载（:mod:`heagent.goal.workflow_loader`，2026-09-20 自
  ``memory/skill_packages.py`` 迁入）：把技能包 ``workflow.md``（frontmatter 策略 / 内嵌
  步骤 / ``required_resources`` 模板必需性）确定性装配成 ``engine/workflow_resource.py``
  的运行时模型。

分层：本子包属**入口层**（供 ``cli_goal`` 使用），依赖 ``heagent.persist`` /
``heagent.engine`` / ``heagent.memory`` 等下层模块，不被任何下层模块导入，不构成反向依赖。
"""
