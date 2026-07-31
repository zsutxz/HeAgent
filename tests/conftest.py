"""pytest 共享配置。

测试环境禁用 ledger 自动清理（``LEDGER_RETENTION_DAYS=0``）：避免 default engine 的
``AgentLoop.run()`` 在每次启动时扫真实 ``.heagent/ledger/``（删用户数据 + 拖慢测试）。
生产默认 retention=7；测试经 env 关闭，穿越 ``reset_settings()``（env 持久，单例重载仍读到 0）。
直接测 prune 的用例手动覆盖 ``engine.ledger_retention_days``，不受此影响。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from heagent.config import Settings

# 必须在 heagent.config 首次 import / get_settings() 之前设置（pydantic-settings 懒加载）。
# setdefault 不覆盖用户已在环境/.env 中显式设置的值。
os.environ.setdefault("LEDGER_RETENTION_DAYS", "0")


@pytest.fixture(autouse=True)
def _isolate_dotenv_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[str]:
    """隔离全局（``~/.heagent/.env``）与项目（``.env``）两层配置加载。

    ``Settings.model_config.env_file`` 在模块导入时固化为
    ``[~/.heagent/.env, .env]``，``monkeypatch.chdir`` 对其无效。若开发者本机存在
    ``~/.heagent/.env``（如运行过 ``heagent init``）或项目根存在 ``.env``（真实 key /
    ``MAX_ITERATIONS`` 等），不带 ``_env_file`` 的 ``Settings()`` 会读到真实配置，
    使断言默认值的用例本地失败而 CI（无配置文件）通过——不可复现。两层都指向 tmp 下
    不存在的文件即可；显式传 ``_env_file`` 的用例不受影响（实例参数优先级高于
    ``model_config``）。返回改动前的原始 env_file 序列，供源码契约类测试断言。
    """
    source_env_files = list(Settings.model_config["env_file"])
    monkeypatch.setitem(
        Settings.model_config,
        "env_file",
        [
            str(tmp_path / "nonexistent_global.env"),
            str(tmp_path / "nonexistent_project.env"),
        ],
    )
    return source_env_files
