"""事实记忆 — 持久化的事实存储，支持跨会话召回。

存储格式：.heagent/memory/MEMORY.md（Markdown 列表）
去重策略：新事实与已有事实进行关键词交集比较，重叠率 > 70% 视为重复。

接入路径：``cli.py`` 实例化 → ``AgentLoop`` 持有 → 经 ``system_prompt`` 注入 SYSTEM；
LLM 可经 ``fact_add`` 内置工具（``tools/builtins/memory.py``）写入。
"""

from __future__ import annotations

from pathlib import Path

from heagent.engine.persist import atomic_write_text


class FactStore:
    """追加式事实记忆存储，带关键词去重。"""

    def __init__(self, path: str = ".heagent/memory/MEMORY.md") -> None:
        self._path = Path(path)

    def add(self, fact: str) -> bool:
        """添加一条事实。

        去重逻辑：将新事实与所有已有事实进行单词集合交集比较，
        重叠率（交集/新事实词数）超过 70% 则视为重复，拒绝添加。
        返回 True 表示添加成功，False 表示重复。
        """
        existing = self._load_facts()
        fact_words = set(fact.lower().split())  # 新事实的单词集合
        for ef in existing:
            overlap = fact_words & set(ef.lower().split())  # 关键词交集
            if len(overlap) / max(len(fact_words), 1) > 0.7:  # 70% 阈值
                return False
        # 追加写入（原子写整文件，防崩溃中途截断）
        prior = self._path.read_text(encoding="utf-8") if self._path.exists() else ""
        atomic_write_text(self._path, prior + f"- {fact}\n")
        return True

    def load(self) -> list[str]:
        """加载所有已存储的事实列表。"""
        return self._load_facts()

    def clear(self) -> None:
        """清除所有事实（删除文件）。"""
        if self._path.exists():
            self._path.unlink()

    def _load_facts(self) -> list[str]:
        """从 MEMORY.md 解析所有 `- ` 开头的行。"""
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").strip().splitlines()
        return [line[2:] for line in lines if line.startswith("- ")]
