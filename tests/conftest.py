"""pytest 共享配置。

测试环境禁用 ledger 自动清理（``LEDGER_RETENTION_DAYS=0``）：避免 default engine 的
``AgentLoop.run()`` 在每次启动时扫真实 ``.heagent/ledger/``（删用户数据 + 拖慢测试）。
生产默认 retention=7；测试经 env 关闭，穿越 ``reset_settings()``（env 持久，单例重载仍读到 0）。
直接测 prune 的用例手动覆盖 ``engine.ledger_retention_days``，不受此影响。
"""

from __future__ import annotations

import os

# 必须在 heagent.config 首次 import / get_settings() 之前设置（pydantic-settings 懒加载）。
# setdefault 不覆盖用户已在环境/.env 中显式设置的值。
os.environ.setdefault("LEDGER_RETENTION_DAYS", "0")
