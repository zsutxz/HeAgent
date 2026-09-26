"""事实记忆 — 持久化的事实存储，支持跨会话召回。

存储格式：.heagent/memory/MEMORY.md（Markdown 列表）
去重策略：新事实与已有事实进行关键词交集比较，重叠率 > 70% 视为重复。

接入路径：``cli.py`` 实例化 → ``AgentLoop`` 持有 → 经 ``system_prompt`` 注入 SYSTEM；
LLM 可经 ``fact_add`` 内置工具（``tools/builtins/memory.py``）写入。
"""

from __future__ import annotations

import logging
from pathlib import Path

from heagent.pub.persist import atomic_update_text

logger = logging.getLogger(__name__)

_BOM = "\ufeff"


def _strip_bom(raw: str) -> str:
    """剥离文本头部的 UTF-8 BOM 字符（``\\ufeff``）。

    以「UTF-8 with BOM」（如记事本另存）保存的 MEMORY.md 会把 ``\\ufeff`` 留在首行行首，
    使 ``_parse_facts`` 的 ``startswith("- ")`` 判定失败 ⇒ **静默丢掉首条事实**（探针实测：
    盘上 2 条 → ``load()`` 返回 1 条，且无任何告警）。读路径一律经此剥离；``add`` 写回时
    同样剥离（2026-09-23 用户裁定「方案 B：读写口径一致优先于保留 BOM 字节」）。

    归一化**只发生在真正走 ``atomic_update_text`` 的路径**（评审更正：此前 docstring 声称
    「即便判重也会原子写一次」，对**外层预读判重命中**的路径不成立——那条路径直接
    ``return False``、不写盘，盘上 BOM 保留；只有锁内 ``_append_fact`` 判重命中时，才因该
    原语无 no-op 短路而重写一次）。
    """
    return raw.lstrip(_BOM)


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
            try:
                raw = _strip_bom(self._path.read_text(encoding="utf-8"))
            except UnicodeDecodeError as exc:
                # `UnicodeDecodeError` 文本**不含路径**，直接冒到工具层只会得到无法定位的
                # codec 报错（Z-D12 冻结边界要求「错误可定位到该文件」），故点名后再抛。
                raise ValueError(f"MEMORY.md is not valid UTF-8 ({self._path}): {exc}") from exc
        else:
            raw = ""

        existing = self._parse_facts(raw)

        fact_words = set(fact.lower().split())  # 新事实的单词集合
        for ef in existing:
            overlap = fact_words & set(ef.lower().split())  # 关键词交集
            if len(overlap) / max(len(fact_words), 1) > 0.7:  # 70% 阈值
                return False
        # 追加写入（原子写整文件，防崩溃中途截断）；`current` 由 `atomic_update_text` 以
        # 普通 UTF-8 读出（BOM 字符仍在），故写回前同样剥离 ⇒ 与读路径口径一致，并把文件
        # 归一化为 UTF-8 无 BOM（见 `_strip_bom`）。
        return atomic_update_text(self._path, lambda current: self._append_fact(_strip_bom(current), fact))

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
        """从 MEMORY.md 解析所有 `- ` 开头的行。

        文件被非 UTF-8 编辑器（如 GBK）保存时**跳过本次加载**并打一条 WARNING，而不是抛出：
        本方法在 run 初始化链上（``system_prompt._memory_block`` ← ``AgentLoop._build_system``
        ← ``run_lifecycle`` 的新 run 初始化），抛出会把**整个 run** 带崩，而 MEMORY.md 是非
        关键资产（deferred-work 条目 Z-D12，2026-09-23 用户裁定按 fail-soft 闭合）。
        读取失败的所有形态都按同一原则降级（评审补：守卫原先只兜 ``UnicodeDecodeError``，
        实测 ``PermissionError``（路径被目录占据等）与 ``FileNotFoundError``（``exists()`` 与
        ``read_text()`` 之间被删/被清）仍会逃到 run 初始化 ⇒ 与「非关键资产不拖死 run」相悖，
        故一并纳入 ``OSError``）。
        文件本体**一字不动**——用户以 UTF-8 重存后记忆即恢复（写路径 ``add`` 的同类失败由
        ``ToolExecutor`` 的 catch-all 兜成工具错误，不会中断循环）。
        首行若带 UTF-8 BOM 亦经 ``_strip_bom`` 剥离——否则该行不满足 ``- `` 前缀而被**静默丢弃**。
        """
        if not self._path.exists():
            return []
        try:
            raw = self._path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            logger.warning(
                "MEMORY.md is not valid UTF-8 (%s); skipping memory injection until %s is re-saved as UTF-8",
                exc,
                self._path,
            )
            return []
        except OSError as exc:
            # 非解码类的读取失败（权限 / 竞态删除 / 路径异常）。OSError 自带路径，够定位；
            # 仍显式带上 self._path 以免依赖异常文本的形态。
            logger.warning(
                "Cannot read %s (%s: %s); skipping memory injection for this run",
                self._path,
                type(exc).__name__,
                exc,
            )
            return []
        return self._parse_facts(_strip_bom(raw))

    @staticmethod
    def _parse_facts(raw: str) -> list[str]:
        """Parse Markdown bullet facts from already-loaded text."""
        return [line[2:] for line in raw.strip().splitlines() if line.startswith("- ")]
