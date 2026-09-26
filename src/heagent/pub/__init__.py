"""HeAgent 公共层（``pub/``）：零运行栈依赖的基础设施。

层次契约（见 ``docs/frame.md`` 三、``tests/test_architecture_contracts.py``）：

- 本包内模块**只**依赖标准库、Pydantic 与同层公共模块——不依赖 ``providers`` / ``tools`` /
  ``context`` / ``engine`` / ``agent`` / ``network``，也不依赖任何入口层模块。
- 任何层都可以依赖 ``pub``；``pub`` 不依赖任何层。
- 配置面（``Settings`` / 来源求解 / 写通道 / ``.env`` 保真读写）在**上一层**：``heagent.config``
  （依赖 ``pub``，被运行栈与入口层共同依赖）。
- 本 ``__init__`` **刻意零 import**：``from heagent.pub import types`` 不应触发其余公共模块的加载
  （与 ``heagent/cli/__init__.py`` 同款约定，断言见 ``test_pub_package_shell_stays_thin``）。
"""
