"""``/goal`` 域层 —— 目标驱动工作流中可独立成模块的部分。

目前只有问卷（:mod:`heagent.goal.questionnaire`）：工作流在 goal 需求文档（``require.md``）
/ workflow Markdown 里
**声明**问卷，本子包负责解析声明、校验回答、收集与写回——产品规则一律不落进 CLI 代码。

分层：本子包属**入口层**（供 ``cli_goal`` 使用），依赖 ``engine.persist`` 等下层模块，
不被任何下层模块导入，不构成反向依赖。
"""
