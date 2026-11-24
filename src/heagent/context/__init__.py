"""上下文与上下文窗口管理包。

按职责分五个模块：会话持久化（:mod:`heagent.context.session`）、上下文文件装载
（:mod:`heagent.context.loader`）、压缩与窗口重置（:mod:`heagent.context.compressor` /
:mod:`heagent.context.window_reset`）、token 估算（:mod:`heagent.context.tokens`）与侧调用
（:mod:`heagent.context.sidecall`）。

对 ``engine`` 的引用仅限 ``TYPE_CHECKING``（架构契约：旁支档不反向依赖 engine 运行时）。
"""
