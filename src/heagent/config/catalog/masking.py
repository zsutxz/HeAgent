"""凭证掩码口径：定长掩码、秘密键后缀判定与「空值」识别。

自 ``heagent.config.catalog`` 单文件拆出（E3 绞杀者），行为零改动。
"""

from __future__ import annotations

from heagent.config import WS_AUTH_TOKEN_KEY

#: 凭证的**定长**掩码：常量、零信息量（既不反映长度也不含原文字符）。
MASK = "********"

#: 合法但**不属于** ``Settings`` 字段的用户级键：它们存在用户 ``setting.md`` 里却不是配置项。
#: 目前只有 WS 对外模式的 token（Epic 56 D3：凭证只认用户级文件，刻意不进「env > 项目 .env >
#: 用户 md」优先级链）。列入本集合的唯一作用是让「未知键」诊断不误报它；它**不**成为可写项，
#: 也不出现在配置面板条目里（面板按 ``Settings.model_fields`` 装配）。
USER_ONLY_SETTING_KEYS = frozenset({WS_AUTH_TOKEN_KEY})

_SECRET_SUFFIXES = ("_API_KEY", "_API_KEYS")


def is_secret_key(env_key: str) -> bool:
    """是否凭证键（``*_API_KEY`` / ``*_API_KEYS``）——这类键永不回传、永不写入。"""
    return env_key.endswith(_SECRET_SUFFIXES)
