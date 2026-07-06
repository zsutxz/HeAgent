"""用户画像 — 分节管理的 USER.md 用户信息存储。

存储路径：.heagent/user/USER.md
使用 Markdown 二级标题（## Section）作为分节标记。
支持更新单个节而不影响其他节。

接入路径：``cli.py`` 实例化 → ``AgentLoop`` 持有 → 经 ``system_prompt`` 注入 SYSTEM；
LLM 可经 ``profile_update`` 内置工具（``tools/builtins/memory.py``）写入。
"""

from __future__ import annotations

from pathlib import Path


class ProfileStore:
    """用户画像存储管理器，支持分节更新。"""

    def __init__(self, path: str = ".heagent/user/USER.md") -> None:
        self._path = Path(path)

    def load(self) -> str:
        """加载完整的用户画像内容。"""
        if not self._path.exists():
            return ""
        return self._path.read_text(encoding="utf-8").strip()

    def save(self, content: str) -> None:
        """覆盖保存完整的用户画像。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(content, encoding="utf-8")

    def update_section(self, section: str, value: str) -> None:
        """更新或追加指定节的值。

        逻辑：
          1. 扫描现有内容，查找 ## {section} 标题
          2. 找到 → 替换该节内容（直到下一个 ## 标题或文件末尾）
          3. 未找到 → 在文件末尾追加新节
        """
        current = self.load()
        header = f"## {section}"
        lines = current.splitlines() if current else []
        new_lines: list[str] = []
        replaced = False
        i = 0
        while i < len(lines):
            if lines[i].strip() == header:
                # 找到目标节：写入新值，跳过旧内容
                new_lines.append(header)
                new_lines.append(value)
                replaced = True
                i += 1
                # 跳过该节下的所有行（直到下一个 ## 标题）
                while i < len(lines) and not lines[i].startswith("## "):
                    i += 1
            else:
                new_lines.append(lines[i])
                i += 1
        # 未找到目标节 → 追加到末尾
        if not replaced:
            if new_lines:
                new_lines.append("")
            new_lines.extend([header, value])
        self.save("\n".join(new_lines) + "\n")

    def clear(self) -> None:
        """清除用户画像（删除文件）。"""
        if self._path.exists():
            self._path.unlink()
