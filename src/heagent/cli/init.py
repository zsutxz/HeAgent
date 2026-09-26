"""``heagent init`` 子命令——全局配置模板与项目上下文模板生成。

**为什么单独成模块**（cli/wiring.py 先例）：此前这段 init 逻辑（约 130 行——两份模板字符串 +
命令定义）与 console.py 的 run/replay/交互编排混在一起——前者随配置项与模板文案变，后者随
交互体验变。拆出后 console.py 只保留命令注册（``main.add_command(init_cmd)``，与尾部
``gui_cmd`` 注册同模式）；测试直接 ``from heagent.cli.init import _init_project_context``。

分层：本模块是入口层（``heagent/cli/`` 包内，与 console 同级），仅依赖 click 与 heagent.config，
不被任何下层模块导入。
"""

from __future__ import annotations

from pathlib import Path

import click

from heagent.config import GLOBAL_CONFIG_DIR, GLOBAL_CONFIG_FILE

_INIT_ENV_TEMPLATE = """# HeAgent 全局配置文件
# 存放路径：{path}
# 加载优先级：显式环境变量 > 项目 .env > 本文件 > 字段默认值
# 意即：在任意项目目录下运行 heagent 时，本文件中的配置作为默认值自动生效，
#       可在单个项目的 .env 中覆盖。

# ---- 活跃 Provider ----
# ACTIVE_PROVIDER=deepseek

# ---- API 密钥 ----
# DEEPSEEK_API_KEY=your-deepseek-key
# OPENAI_API_KEY=your-openai-key
# ANTHROPIC_API_KEY=your-anthropic-key
# KIMI_API_KEY=your-kimi-key
# GLM_API_KEY=your-glm-key

# ---- API 基础 URL（用于代理或自营服务）----
# DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
# OPENAI_BASE_URL=
# ANTHROPIC_BASE_URL=
# KIMI_BASE_URL=https://api.moonshot.cn/v1
# GLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4

# ---- 各 Provider 默认模型 ----
# DEFAULT_MODEL=gpt-4o
# DEEPSEEK_MODEL=deepseek-v4-pro
# KIMI_MODEL=kimi-k3
# GLM_MODEL=glm-5.3

# ---- 本地 Ollama（OpenAI 兼容 /v1，显式 opt-in；无需真实 API Key）----
# OLLAMA_ENABLED=true
# OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
# OLLAMA_MODEL=qwen3:8b
# MAX_OUTPUT_TOKENS=4096   # 可选：单次输出上限（本地思考模型建议设，防无限生成）
# 本地模型窗口通常远小于默认 512000（Ollama 取 Modelfile 的 num_ctx），请按实际值下调
# MAX_CONTEXT_TOKENS，否则压缩/窗口重置阈值永不触发、先撞 API 400。

# ---- Anthropic 提示词缓存 ----
# ANTHROPIC_PROMPT_CACHING=true

# ---- 重试策略 ----
# RETRY_MAX_ATTEMPTS=3
# RETRY_BASE_DELAY=1.0
# RETRY_MAX_DELAY=30.0

# ---- 日志 ----
# LOG_LEVEL=INFO
# LOG_FILE_LEVEL=DEBUG
# LOG_DIR=logs

# ---- 沙箱后端 ----
# SANDBOX_BACKEND=passthrough
# SANDBOX_FIREJAIL_PATH=firejail

# ---- MCP ----
# MCP_ENABLED=true
# MCP_CONFIG_PATH=.mcp.json
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


@click.command("init")
@click.option(
    "--project",
    "project",
    is_flag=True,
    default=False,
    help="Also generate project .heagent/CONTEXT.md template",
)
def init_cmd(project: bool) -> None:
    """初始化 HeAgent 全局配置目录。

    在用户主目录创建 ``~/.heagent/``，并生成带注释的配置模板 ``~/.heagent/.env``。
    如果文件已存在，则保留不覆盖。``--project`` 时额外生成项目 ``.heagent/CONTEXT.md``。
    """
    created_dir = False
    if not GLOBAL_CONFIG_DIR.exists():
        GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        created_dir = True

    created_file = False
    if not GLOBAL_CONFIG_FILE.exists():
        template = _INIT_ENV_TEMPLATE.format(path=str(GLOBAL_CONFIG_FILE))
        GLOBAL_CONFIG_FILE.write_text(template, encoding="utf-8")
        created_file = True

    if created_dir and created_file:
        click.echo(f"[OK] Created global config directory: {GLOBAL_CONFIG_DIR}")
        click.echo(f"[OK] Created config template: {GLOBAL_CONFIG_FILE}")
        click.echo("")
        click.echo("Edit ~/.heagent/.env to set your API keys and preferences.")
        click.echo("Project-level .env files can still override per-project.")
    elif created_file:
        click.echo(f"[OK] Created config template: {GLOBAL_CONFIG_FILE}")
        click.echo("Edit it to set your API keys and preferences.")
    else:
        click.echo(f"Already exists: {GLOBAL_CONFIG_FILE} (not overwritten)")

    if project:
        _init_project_context()
