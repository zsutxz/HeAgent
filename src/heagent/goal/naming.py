"""goal 项目命名（/goal 命令族的 LLM 命名层）。

**为什么单独成模块**（document.py 先例）：document.py 只做「文档与命名」中的确定性
部分且承诺不依赖 providers；LLM 命名必须持有 provider，落在这里保持 document.py 纯函数
可独立测试。本模块同为入口层域模块，依赖 types/providers.base（TYPE_CHECKING）与
goal.document 的命名常量，不依赖 agent/cron。

**命名契约**：``/goal new`` 的 goal_id（即 ``_he-output/goals/<id>`` 目录名）由 LLM 按
需求描述生成；清洗/校验/去重（``-a``..``-z`` 后缀）均为代码内确定性逻辑。LLM 调用失败
或输出非法时**显性回退**固定名 ``project``（stderr 提示，不静默）——goal 创建不因命名
中断。id 字符集仍锁定 ``^[a-z][a-z-]*$``：current 指针校验、cron prompt 解析、旧 job
注销匹配三处下游依赖该契约。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import click

from heagent.goal.document import _GOAL_ID_RE, _slug
from heagent.types import Message, Role

if TYPE_CHECKING:
    from heagent.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# 兜底名：与历史行为一致（原 _goal_project_id 的 or "project" 分支）。
_FALLBACK_ID = "project"
# 目录名长度上限：约束 LLM 失控输出（啰嗦解释 slug 后仍合法但不可用）。
_MAX_ID_LENGTH = 48
# 一次性命名 prompt：只输出 id 本身，格式约束与 _GOAL_ID_RE 对齐。
_GOAL_NAME_PROMPT = (
    "Name a software project based on the request below.\n"
    "Rules: 1-3 English words; lowercase letters and single hyphens only; start with a "
    "letter; no digits, spaces, or punctuation; capture the project's essence.\n"
    "Output ONLY the project id itself, nothing else.\n\nRequest:\n"
)


async def llm_project_id(provider: BaseProvider, description: str) -> str:
    """Generate the goal id via a one-shot LLM call; fall back loudly on failure.

    一次性直调 ``provider.send``（同 context/window_reset、context/compressor 先例），
    不经 SubAgent 会话。任何失败（调用异常/空内容/清洗后非法/超长）都回退
    ``_FALLBACK_ID`` 并向 stderr 显性提示。
    """
    try:
        resp = await provider.send([Message(role=Role.USER, content=f"{_GOAL_NAME_PROMPT}{description}")])
        candidate = _slug(resp.content.strip().strip("`").strip().casefold())
    except Exception as exc:  # provider 网络故障、假 provider 缺 send 等一律走回退
        logger.warning("goal naming via llm call failed: %s", exc)
        return _fallback()
    if _GOAL_ID_RE.fullmatch(candidate) and len(candidate) <= _MAX_ID_LENGTH:
        return candidate
    logger.warning("goal naming via llm returned unusable output: %r", resp.content)
    return _fallback()


def _fallback() -> str:
    """Announce and return the fallback id — the fallback must be observable."""
    click.echo(f"[goal] project naming via llm failed; using default id '{_FALLBACK_ID}'", err=True)
    return _FALLBACK_ID
