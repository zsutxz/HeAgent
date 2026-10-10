"""``/skill-merge``——跨根同名技能的交互式收口（skills 双根，P3）。

冲突语义（P2）：全局根优先生效、本地根被遮蔽，每名警告一次。本命令逐个冲突给出三种
收口：全局覆盖本地 / 本地覆盖全局 / 跳过；覆盖是 copytree 级整目录替换，执行前需确认。
非 TTY 环境打印手动指引（不做猜测性合并——显性失败原则）。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from heagent.cli.slash import SlashRegistry
    from heagent.skills.skill_store import SkillConflict, SkillStore

#: 收口动作标签（顺序即编号选择序）。
_CHOICES = ("全局覆盖本地", "本地覆盖全局", "跳过")


def register_skill_merge(registry: SlashRegistry, skills: SkillStore) -> None:
    """把 ``skill-merge`` 注册进斜杠命令表（interactive._build_slash_registry 调用）。"""

    async def _merge(args: str) -> None:
        await run_skill_merge(skills)

    registry.register("skill-merge", "跨根同名技能收口（全局/本地覆盖或跳过）", _merge)


async def run_skill_merge(skills: SkillStore) -> None:
    """遍历跨根同名冲突，逐个交互收口；无冲突或非 TTY 时给指引。"""
    conflicts = skills.conflicts()
    if not conflicts:
        click.echo("[skill-merge] no cross-root skill conflicts.", err=True)
        return
    if not sys.stdin.isatty():
        for conflict in conflicts:
            _echo_conflict(conflict)
        click.echo(
            "[skill-merge] non-interactive session: nothing merged. Copy the winning directory "
            "over the shadowed one manually, or rerun /skill-merge in a TTY.",
            err=True,
        )
        return
    for conflict in conflicts:
        _echo_conflict(conflict)
        choice = click.prompt(
            "收口：1=全局覆盖本地  2=本地覆盖全局  3=跳过",
            type=click.IntRange(1, len(_CHOICES)),
            default=3,
        )
        if choice == 3:
            click.echo(f"[skill-merge] '{conflict.name}' skipped; global keeps winning.", err=True)
            continue
        winner = Path(conflict.effective_root if choice == 1 else conflict.shadowed_root)
        loser = Path(conflict.shadowed_root if choice == 1 else conflict.effective_root)
        if not click.confirm(
            f"将用 {winner} 下的 '{conflict.name}' 整目录覆盖 {loser} 下的同名技能，继续?",
            default=False,
        ):
            click.echo("[skill-merge] aborted by user; nothing changed.", err=True)
            continue
        _overwrite(loser, winner, conflict.name)
        click.echo(f"[skill-merge] '{conflict.name}': {_CHOICES[choice - 1]} done ({loser}).", err=True)


def _echo_conflict(conflict: SkillConflict) -> None:
    """展示一个冲突的两边（路径 / created / usage / description 截断）。"""
    click.echo(f"\n=== {conflict.name} ===", err=True)
    for label, root, meta in (
        ("[1] 生效(全局)", conflict.effective_root, conflict.effective_meta),
        ("[2] 被遮蔽(本地)", conflict.shadowed_root, conflict.shadowed_meta),
    ):
        description = _description_at(Path(root), conflict.name)
        click.echo(
            f"  {label}: {root}\n"
            f"      created={meta.created or '未知'}  usage={meta.usage_count}"
            f"  last_used={meta.last_used[:16] or '从未'}\n"
            f"      {description}",
            err=True,
        )


def _overwrite(loser_root: Path, winner_root: Path, name: str) -> None:
    """整目录替换：先删败者目录再复制胜者（目录级操作，不经 SkillStore 写路径）。"""
    dest = loser_root / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(winner_root / name, dest)


def _description_at(root: Path, name: str) -> str:
    """读该根下 SKILL.md 的 description（展示用；截断到 60 字符）。"""
    from heagent.skills.skill_models import parse_skill_md

    md = root / name / "SKILL.md"
    try:
        parsed = parse_skill_md(name, md.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "(SKILL.md 不可读)"
    text = parsed.description
    return text[:60] + ("..." if len(text) > 60 else "(空描述)")
