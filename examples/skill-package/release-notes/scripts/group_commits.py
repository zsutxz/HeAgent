"""技能包的辅助资源脚本：把 `git log --oneline` 输出按 Conventional Commit 前缀粗分组。

用法（仓库根）：

    git log --oneline v0.9.0..HEAD | python examples/skill-package/release-notes/scripts/group_commits.py

这是技能包演示用的最小脚本：只做分组，不做发布说明的措辞转换。
"""

from __future__ import annotations

import sys

# 前缀 → 归入的发布说明栏目
GROUPS = {
    "feat": "新增",
    "fix": "修复",
    "perf": "新增",
    "refactor": "内部重构（通常不进发布说明）",
    "docs": "内部重构（通常不进发布说明）",
    "test": "内部重构（通常不进发布说明）",
    "chore": "内部重构（通常不进发布说明）",
}
BREAKING_MARK = "!"
#: `git log --oneline` 里短 sha 的字符数——判「行首是 sha 前缀」用。
SHORT_SHA_LEN = 7


def group(lines: list[str]) -> dict[str, list[str]]:
    """按前缀分组；识别 `type(scope)!:` 形式的破坏性标记。"""
    buckets: dict[str, list[str]] = {}
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        # 去掉常见的 "<sha> " 前缀
        if (
            len(line) > SHORT_SHA_LEN
            and line[SHORT_SHA_LEN] == " "
            and all(c in "0123456789abcdef" for c in line[:SHORT_SHA_LEN])
        ):
            line = line[SHORT_SHA_LEN + 1 :]
        head = line.split(":", 1)[0]
        kind = head.split("(", 1)[0]
        bucket = "破坏性变更" if BREAKING_MARK in head else GROUPS.get(kind, "未分类")
        buckets.setdefault(bucket, []).append(line)
    return buckets


def main() -> int:
    buckets = group(sys.stdin.read().splitlines())
    if not buckets:
        print("（没有输入；把 git log 的输出通过管道传进来）")
        return 0
    for name in ("破坏性变更", "新增", "修复", "未分类", "内部重构（通常不进发布说明）"):
        items = buckets.get(name)
        if not items:
            continue
        print(f"== {name} ({len(items)}) ==")
        for item in items:
            print(f"  - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
