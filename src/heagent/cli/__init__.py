"""CLI 入口层命名空间（Epic 48/49/50 之后的入口层模块群）。

层级：本包与 ``goal/`` / ``gui/`` 同属**入口层**——组合根与展示适配只在这里，
下层（providers/tools/engine/agent/memory/context/cron/events/network）一律不得反向导入。

布局（2026-09-26 起，原 ``src/heagent/cli*.py`` 七个平铺模块收进本包）：

- ``console.py`` —— Click 命令组 + 单次/交互执行（旧 ``cli.py``；入口脚本指向它）
- ``init.py``    —— ``heagent init`` 子命令（旧 ``cli_init.py``）
- ``goal.py``    —— ``/goal`` 命令族（旧 ``cli_goal.py``）
- ``http.py``    —— ``http-server`` 子命令与 HTTP/控制台装配（旧 ``cli_http.py``）
- ``tcp.py``     —— ``tcp-server`` 子命令与 Agent 请求适配（旧 ``cli_tcp.py``）
- ``dialogs.py`` —— 服务端原生目录选择（旧 ``cli_dialogs.py``）
- ``display.py`` —— 终端渲染辅助（旧 ``cli_display.py``，CLI 与 GUI 共用）

**本文件必须保持零 import**（契约测试钉死）：包一旦在 ``__init__`` 里导入任何子模块，
``import heagent.cli.display``（GUI 的轻量用法）就会先执行 ``console.py`` 的整条装配图
（click + wiring + provider + engine），把「轻量展示层」变成重型入口导入。入口脚本与
``__main__.py`` 因此直接指向 ``heagent.cli.console:main``，不再经包级 re-export。
"""
