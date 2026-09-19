"""``/goal`` 域层 —— 目标驱动工作流中可独立成模块的部分。

目前只有需求文档层（:mod:`heagent.goal.document`）：goal 目录的 ``require.md``（存量 goal
为 ``GOAL.md``）的定位、命名与增量更新——文档约定一律不落进 CLI 代码。

分层：本子包属**入口层**（供 ``cli_goal`` 使用），依赖 ``heagent.persist`` 等下层模块，
不被任何下层模块导入，不构成反向依赖。
"""
