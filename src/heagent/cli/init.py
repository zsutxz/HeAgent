"""``heagent init`` 子命令——全局配置模板与项目上下文模板生成。

**为什么单独成模块**（cli/wiring.py 先例）：此前这段 init 逻辑（约 130 行——两份模板字符串 +
命令定义）与 console.py 的 run/replay/交互编排混在一起——前者随配置项与模板文案变，后者随
交互体验变。拆出后 console.py 只保留命令注册（``main.add_command(init_cmd)``，与尾部
``gui_cmd`` 注册同模式）；测试直接 ``from heagent.cli.init import _init_project_context``。

分层：本模块是入口层（``heagent/cli/`` 包内，与 console 同级），仅依赖 click 与 heagent.config，
不被任何下层模块导入。``--interactive`` 分支把落盘工作交给同层的 ``cli/wizard.py``（延迟导入：
非交互路径不需要配置目录与求解器）。
"""

from __future__ import annotations

from pathlib import Path

import click

from heagent.cli.settings_audit import record_settings_write, snapshot_settings
from heagent.config import GLOBAL_CONFIG_DIR, GLOBAL_SETTING_FILE, LEGACY_GLOBAL_ENV_FILE
from heagent.config.user_settings import ensure_user_settings_migrated

_INIT_SETTING_TEMPLATE = """---
# HeAgent 用户级配置（~/.heagent/setting.md）
# 加载优先级：系统环境变量 > 项目 .env > 本文件 > 字段默认值
# 意即：本文件是**全机默认值**；单个项目可在其 .env 中覆盖。.env 是项目级专用格式。
# 写法：`KEY: value`（冒号+空格）；`#` 整行注释。值后面「空白 + #」起算行内注释、会被剥掉
# （与 dotenv 口径一致），要写字面 `#` 请确保前面没有空白（或用引号包起来）。
#
# WS 对外模式（Epic 56）：把 WS 入口绑到非回环地址（如 WS_HOST=0.0.0.0）时必须配本项，
# 否则对外监听器**拒绝启动**（fail-closed）。本项**只**从本文件读取——项目 .env 里写同名的
# 键不生效（凭证不进「env > 项目 .env > 本文件」优先级链）。随机长串即可，例如：
# WS_AUTH_TOKEN: <paste-a-long-random-string>
---

# HeAgent 用户级设置

本文件是 HeAgent 的**用户级**配置（全机默认值），正文可自由写文档。

## 密钥

## 各 Provider 默认模型

## 行为设置

## 覆盖方式
"""

_CONTEXT_TEMPLATE = """# CONTEXT.md

> HeAgent 每次运行会自动加载本文件（优先级：`.heagent/CONTEXT.md` > `AGENTS.md` > `CLAUDE.md`）。
> 在此填写项目的关键背景与约定，帮助 Agent 更好地理解本项目。

## 项目概述

<!-- 项目是做什么的、技术栈、目录结构 -->

## 关键约定

<!-- 命名规范、代码规范、构建 / 测试命令等 -->

## 注意事项

<!-- 哪些文件 / 目录不要修改、哪些是生成产物、安全边界等 -->
"""


def _init_project_context() -> None:
    """生成项目 ``.heagent/CONTEXT.md`` 模板（若不存在）。"""
    context_path = Path(".heagent") / "CONTEXT.md"
    if context_path.exists():
        click.echo(f"Already exists: {context_path} (not overwritten)")
        return
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(_CONTEXT_TEMPLATE, encoding="utf-8")
    click.echo(f"[OK] Created project context template: {context_path}")


def _init_interactive(project: bool) -> None:
    """``--interactive`` 分支：先做与非交互路径相同的目录创建与一次性迁移，再交给向导写文件。

    模板骨架不由本分支生成——向导会把用户确认的值直接写进 ``setting.md``（既有文件只改命中行），
    两份模板文案并存只会漂移。终端能力先判：非 tty 时不该顺手建目录或迁移旧文件。
    """
    from heagent.cli.wizard import require_interactive_terminal, run_wizard

    require_interactive_terminal()

    if not GLOBAL_CONFIG_DIR.exists():
        GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        click.echo(f"[OK] Created global config directory: {GLOBAL_CONFIG_DIR}")

    before_settings = snapshot_settings(GLOBAL_SETTING_FILE)
    migrated = ensure_user_settings_migrated(GLOBAL_SETTING_FILE, legacy_env_file=LEGACY_GLOBAL_ENV_FILE)
    if migrated:
        click.echo(f"[OK] Migrated legacy ~/.heagent/.env into {GLOBAL_SETTING_FILE} (renamed .env.migrated)")
        # 迁移同样是写 setting.md：转换后的键值可追证，值本身不进审计（只留摘要）。
        record_settings_write(target=GLOBAL_SETTING_FILE, before=before_settings)

    run_wizard(setting_file=GLOBAL_SETTING_FILE)
    if project:
        _init_project_context()


@click.command("init")
@click.option(
    "--project",
    "project",
    is_flag=True,
    default=False,
    help="Also generate project .heagent/CONTEXT.md template",
)
@click.option(
    "--interactive",
    "interactive",
    is_flag=True,
    default=False,
    help="Interactive wizard: ask for common settings, then verify the written ~/.heagent/setting.md",
)
def init_cmd(project: bool, interactive: bool) -> None:
    """初始化 HeAgent 全局配置目录。

    在用户主目录创建 ``~/.heagent/``；先执行一次性迁移（旧 ``~/.heagent/.env`` →
    ``setting.md``），再生成带注释的用户级配置模板 ``~/.heagent/setting.md``（已存在则不覆盖）。
    ``--project`` 时额外生成项目 ``.heagent/CONTEXT.md``。
    ``--interactive`` 时改走交互式配置向导（逐项询问常用配置并验证后原子写入同一个文件）。
    """
    if interactive:
        _init_interactive(project)
        return

    created_dir = False
    if not GLOBAL_CONFIG_DIR.exists():
        GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        created_dir = True

    before_settings = snapshot_settings(GLOBAL_SETTING_FILE)
    migrated = ensure_user_settings_migrated(GLOBAL_SETTING_FILE, legacy_env_file=LEGACY_GLOBAL_ENV_FILE)
    if migrated:
        click.echo(f"[OK] Migrated legacy ~/.heagent/.env into {GLOBAL_SETTING_FILE} (renamed .env.migrated)")
        # 迁移同样是写 setting.md：转换后的键值可追证，值本身不进审计（只留摘要）。
        record_settings_write(target=GLOBAL_SETTING_FILE, before=before_settings)

    created_file = False
    if not GLOBAL_SETTING_FILE.exists():
        before_settings = snapshot_settings(GLOBAL_SETTING_FILE)
        GLOBAL_SETTING_FILE.write_text(_INIT_SETTING_TEMPLATE, encoding="utf-8")
        record_settings_write(target=GLOBAL_SETTING_FILE, before=before_settings)
        created_file = True

    if created_dir and created_file:
        click.echo(f"[OK] Created global config directory: {GLOBAL_CONFIG_DIR}")
        click.echo(f"[OK] Created settings template: {GLOBAL_SETTING_FILE}")
        click.echo("")
        click.echo("Edit ~/.heagent/setting.md to set your API keys and preferences.")
        click.echo("Project-level .env files can still override per-project.")
    elif created_file:
        click.echo(f"[OK] Created settings template: {GLOBAL_SETTING_FILE}")
        click.echo("Edit it to set your API keys and preferences.")
    elif migrated:
        click.echo(f"[OK] Migrated legacy ~/.heagent/.env into {GLOBAL_SETTING_FILE}")
    else:
        click.echo(f"Already exists: {GLOBAL_SETTING_FILE} (not overwritten)")

    if project:
        _init_project_context()
