"""``/goal`` 域层 —— 目标驱动工作流中可独立成模块的部分。

- 确定性内核（:mod:`heagent.goal.application`，2026-09-21 Phase 3 自 ``cli/goal.py``
  迁入）：workflow 校验、gate 渲染、story 选择、checkpoint 恢复与推进 use-case、
  prompt 装配——click-free，用户可见文案以结构化 outcome 携带，由 cli/goal 统一渲染
  （架构契约测试钉死其 import 图）。
- 需求文档层（:mod:`heagent.goal.document`）：goal 目录的 ``brief.md``（存量 goal 为
  ``require.md`` / ``GOAL.md``）的定位、命名规则与增量更新——文档约定一律不落进 CLI 代码。
- LLM 项目命名（:mod:`heagent.goal.naming`）：``/goal new`` 的 goal_id 由一次性
  provider 调用生成，失败/非法显性回退固定名 ``project``；清洗与校验复用
  document.py 的确定性常量。
- 声明式工作流装载（:mod:`heagent.goal.workflow_loader`，2026-09-20 自
  ``memory/skill_packages.py`` 迁入）：把技能包 ``workflow.md``（frontmatter 策略 / 内嵌
  步骤 / ``required_resources`` 模板必需性）确定性装配成 ``engine/workflow_resource.py``
  的运行时模型；步骤 ``validation:`` 的结构化证据子句（section / command / artifact /
  git / gate）在此解析（未知子句 fail-loud）。
- 结构化执行证据（:mod:`heagent.goal.evidence`，Story 51-3）：版本化证据模型 +
  追加式存储（id 定位、跨 Story 拒绝、脱敏与上限）。**证据生成只消费受治理执行结果**
  （``ToolExecutor`` 链路的 ToolCall / ToolResult），本模块不执行任何命令；
  只读 Git 查询在 :mod:`heagent.goal.git_port`——那是**白名单内的确定性只读子进程查询**
  （固定旗标模板），不经 ToolExecutor、也不是模型可调用的工具入口。
- 只读 Git 端口（:mod:`heagent.goal.git_port`，Story 51-3）：base / head / 变更集与
  工作区冲突状态；只读子命令白名单 + 固定旗标模板，从不 commit（AD-11）。

分层：本子包属**入口层**（供 ``cli/goal`` 使用），依赖 ``heagent.pub.persist`` /
``heagent.pub.safe_logging`` / ``heagent.engine`` / ``heagent.memory`` / ``heagent.tools``
（call_summary 与 sandbox 公共内核）等下层模块，不被任何下层模块导入，不构成反向依赖。
application/document/workflow_loader 不依赖 Click；naming 的 click.echo 是入口侧回退提示。
"""
