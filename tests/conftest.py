"""pytest 共享配置。

测试环境禁用 ledger / run 两层自动清理（``LEDGER_RETENTION_DAYS=0`` +
``RUN_RETENTION_DAYS=0``）：``AgentLoop.run()`` 在每次全新 run 启动时都会触发
``prune_ledger_once`` + ``prune_runs_once``，而测试里 default engine 的
``.heagent/ledger`` / ``.heagent/runs`` 是**相对 cwd** 解析的——不关掉就会
（a）删开发机上的真实记录、（b）万级文件扫描把 run 启动拖到数秒（实测
``.heagent/runs`` 1.2 万条快照时单次扫描 >2s，会撞爆 pause/resume 测试里的
``wait_for(..., timeout=2)``）。

生产默认 retention=7；测试经 env 关闭，穿越 ``reset_settings()``（env 持久，
单例重载仍读到 0）。直接测 prune 的用例手动覆盖 ``engine.ledger_retention_days`` /
``engine.run_retention_days`` 或 ``monkeypatch.setenv``，不受此影响。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from heagent.config import Settings, reset_settings

# 必须在 heagent.config 首次 import / get_settings() 之前设置（pydantic-settings 懒加载）。
# setdefault 不覆盖用户已在环境/.env 中显式设置的值。
os.environ.setdefault("LEDGER_RETENTION_DAYS", "0")
os.environ.setdefault("RUN_RETENTION_DAYS", "0")
# 清理节流也关掉：测试里新建容器若读到真实 .heagent 的节流标记就会静默不清理，断言会假失败。
os.environ.setdefault("PRUNE_MIN_INTERVAL_SECONDS", "0")
# 运行时产物保留期（日志 / 会话 / 编辑快照 / 沙箱会话目录）同样关掉：测试会真的调 CLI 入口，
# 不关的话就会去扫/删开发机上的真实 logs/、.heagent/sessions、edit-snapshots、.heagent/sandboxes。
os.environ.setdefault("LOG_RETENTION_DAYS", "0")
os.environ.setdefault("SESSION_RETENTION_DAYS", "0")
os.environ.setdefault("EDIT_SNAPSHOT_RETENTION_DAYS", "0")
os.environ.setdefault("SANDBOX_DIR_RETENTION_DAYS", "0")


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
    # 隔离单例状态：每个测试从干净 Settings 开始（跨测试 env 泄漏如
    # GOAL_CHECKPOINT_MODE=auto 会污染后续断言默认值的用例）。
    reset_settings()
    return source_env_files


@pytest.fixture()
def goal_workflow_root(tmp_path: Path) -> Path:
    """在 tmp_path 下搭 ``he-goal`` 技能包骨架，模板复用仓库随包发布的真实文件。

    模板是 /goal 的硬性运行时依赖且 CLI 无内置兜底——此前两个 goal 测试文件各持一份
    copytree 副本，provisioning 规则变化时极易只改一处（此处收敛为唯一定义）。
    调用方 fixture 自行写入各自的 ``workflow.md`` 内容后 chdir 使用。
    """
    root = tmp_path / ".heagent" / "skills" / "he-goal"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\ncanonical_id: he-goal\nname: he-goal\ndescription: test package\n---\n\n# test package\n",
        encoding="utf-8",
    )
    shutil.copytree(
        Path(__file__).resolve().parents[1] / ".heagent" / "skills" / "he-goal" / "templates",
        root / "templates",
    )
    return root
