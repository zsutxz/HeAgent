"""事实记忆 — 持久化的事实存储，支持跨会话召回。

存储格式：.heagent/memory/MEMORY.md（Markdown 列表）
去重策略：新事实与已有事实进行关键词交集比较，重叠率 > 70% 视为重复。

接入路径：``cli.py`` 实例化 → ``AgentLoop`` 持有 → 经 ``system_prompt`` 注入 SYSTEM；
LLM 可经 ``fact_add`` 内置工具（``tools/builtins/memory.py``）写入。
"""

from __future__ import annotations

from pathlib import Path

from heagent.persist import atomic_update_text


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
        # 单次读取：同时用于去重判断与拼接写入，规避两次独立读取之间的多进程竞态
        # （若去重用 _load_facts() 而拼接用 read_text()，两次读之间外部写入会丢失）。
        if self._path.exists():
            raw = self._path.read_text(encoding="utf-8")
        else:
            raw = ""

        existing = self._parse_facts(raw)

        fact_words = set(fact.lower().split())  # 新事实的单词集合
        for ef in existing:
            overlap = fact_words & set(ef.lower().split())  # 关键词交集
            if len(overlap) / max(len(fact_words), 1) > 0.7:  # 70% 阈值
                return False
        # 追加写入（原子写整文件，防崩溃中途截断）
        return atomic_update_text(self._path, lambda current: self._append_fact(current, fact))

    @classmethod
    def _append_fact(cls, raw: str, fact: str) -> tuple[str, bool]:
        existing = cls._parse_facts(raw)
        words = set(fact.lower().split())
        for old in existing:
            if len(words & set(old.lower().split())) / max(len(words), 1) > 0.7:
                return raw, False
        return raw + f"- {fact}\n", True

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
        return self._parse_facts(self._path.read_text(encoding="utf-8"))

    @staticmethod
    def _parse_facts(raw: str) -> list[str]:
        """Parse Markdown bullet facts from already-loaded text."""
        return [line[2:] for line in raw.strip().splitlines() if line.startswith("- ")]
