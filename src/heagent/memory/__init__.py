"""长期记忆包。

按职责分六个模块：事实库读写（:mod:`heagent.memory.facts`，落 ``MEMORY.md``）、字节归档
（:mod:`heagent.memory.auto_archive`）、语义压缩（:mod:`heagent.memory.compact`）、定期整理
（:mod:`heagent.memory.dream`）、用户画像（:mod:`heagent.memory.profile`）与人格文件
（:mod:`heagent.memory.soul`）。

对 ``engine`` 的引用仅限 ``TYPE_CHECKING``（架构契约：旁支档不反向依赖 engine 运行时）。
"""
