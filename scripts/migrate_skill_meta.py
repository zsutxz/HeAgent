"""一次性迁移：把 .heagent/skills/*/SKILL.md frontmatter 的 meta 契约键移入 meta.yaml。

用法：
    python scripts/migrate_skill_meta.py             # dry-run，只打印每包计划
    python scripts/migrate_skill_meta.py --write     # 落盘（原子写）

规则：SKILL.md 只保留 name/description/triggers/negative_triggers 四键（原始行字节
保序保留）；meta 契约键（含驼峰别名）写入 <pkg>/meta.yaml（render_meta_yaml 规范
形态）；`updated` 死键丢弃；未知键 / 键形不明的行 / 已存在的 meta.yaml 与迁移渲染
不一致 / manifest 凭据在场 → abort（显性失败，不做猜测性改写）。

幂等：已迁移的仓库重跑为 no-op（重建产物与原文件逐字节比对相等即跳过）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from heagent.pub.frontmatter import FRONTMATTER_NEWLINE_RE
from heagent.pub.persist import atomic_write_text
from heagent.skills.skill_meta import (
    META_FILENAME,
    META_KEYS,
    SKILL_MD_KEYS,
    SkillMetaError,
    detect_legacy_skill_md_keys,
    normalize_meta_key,
    parse_meta_yaml,
    render_meta_yaml,
)

#: 历史死键（全仓库无解析器读），迁移时丢弃并报告。
DROP_KEYS = frozenset({"updated"})
_KEY_SHAPE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


class MigrationAbort(Exception):
    """单包迁移遇到需人工介入的状态；该包不写盘，其余包继续。"""


def _classify_frontmatter(fm_text: str, pkg_name: str) -> tuple[list[str], list[str], list[str]]:
    """逐行分类 frontmatter：返回 (SKILL.md 保留行, meta 迁移行, 丢弃键)。

    键形不明 / 契约外键 → :class:`MigrationAbort`（显性失败，不做猜测性改写）。
    """
    keep_lines: list[str] = []
    moved_lines: list[str] = []
    dropped: list[str] = []
    for line in fm_text.splitlines():
        stripped = line.strip()
        if not stripped:
            keep_lines.append(line)  # 空行原位保留
            continue
        key = stripped.split(":", 1)[0].strip()
        if ":" not in line or line[:1].isspace() or not _KEY_SHAPE_RE.fullmatch(key):
            raise MigrationAbort(f"{pkg_name}: unrecognizable frontmatter line {line!r}")
        normalized = normalize_meta_key(key)
        if normalized in SKILL_MD_KEYS:
            keep_lines.append(line)
        elif normalized in META_KEYS:
            moved_lines.append(stripped)
        elif normalized in DROP_KEYS:
            dropped.append(normalized)
        else:
            raise MigrationAbort(f"{pkg_name}: unknown frontmatter key '{key}'")
    return keep_lines, moved_lines, dropped


def migrate_package(pkg_dir: Path, root: Path, *, write: bool) -> str:
    """迁移一个技能包，返回动作描述；需人工介入抛 :class:`MigrationAbort`。"""
    if (pkg_dir / "manifest.json").is_file() or (root / "manifest.lock").is_file():
        raise MigrationAbort(f"{pkg_dir.name}: manifest credential present; refusing to rewrite pinned content")
    md_path = pkg_dir / "SKILL.md"
    raw = md_path.read_text(encoding="utf-8")
    match = FRONTMATTER_NEWLINE_RE.match(raw)
    if match is None:
        return "skip: no frontmatter"

    keep_lines, moved_lines, dropped = _classify_frontmatter(match.group(1), pkg_dir.name)
    if not moved_lines and not dropped:
        return "skip: already migrated"

    new_raw = raw[: match.start(1)] + "\n".join(keep_lines) + raw[match.end(1) :]
    residual = FRONTMATTER_NEWLINE_RE.match(new_raw)
    if residual is not None and detect_legacy_skill_md_keys(residual.group(1)):
        raise MigrationAbort(f"{pkg_dir.name}: internal error, meta keys survived the rewrite")

    meta_new: str | None = render_meta_yaml(parse_meta_yaml("\n".join(moved_lines))) if moved_lines else None
    meta_note = "no meta.yaml"
    meta_path = pkg_dir / META_FILENAME
    if meta_path.is_file():
        if meta_new is None:
            meta_note = "existing meta.yaml left untouched"
        else:
            existing = meta_path.read_text(encoding="utf-8")
            if existing != meta_new:
                raise MigrationAbort(
                    f"{pkg_dir.name}: {META_FILENAME} exists and differs from the migration render; resolve manually"
                )
            meta_new = None  # 已一致，不重写
            meta_note = "meta.yaml already up to date"

    moved_text = ", ".join(normalize_meta_key(line.split(":", 1)[0].strip()) for line in moved_lines) or "nothing"
    note = f"move [{moved_text}]"
    if dropped:
        note += f", drop {dropped}"
    note += f"; {meta_note}"
    if write:
        if new_raw != raw:
            atomic_write_text(md_path, new_raw)
        if meta_new is not None:
            atomic_write_text(meta_path, meta_new)
        note += "; written"
    else:
        note += "; write=off"
    return note


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".heagent/skills", help="技能库根目录（默认 .heagent/skills）")
    parser.add_argument("--write", action="store_true", help="落盘；缺省为 dry-run")
    args = parser.parse_args()

    root = Path(args.root)
    if not root.is_dir():
        print(f"root not found: {root}", file=sys.stderr)
        return 1
    packages = sorted(p for p in root.iterdir() if p.is_dir() and p.name != ".archive" and (p / "SKILL.md").exists())
    aborts: list[str] = []
    for pkg in packages:
        try:
            print(f"{pkg.name}: {migrate_package(pkg, root, write=args.write)}")
        except (MigrationAbort, SkillMetaError, OSError) as exc:
            aborts.append(str(exc))
            print(f"{pkg.name}: ABORT — {exc}", file=sys.stderr)
    print(f"\n{len(packages)} package(s) scanned, {len(aborts)} aborted, mode={'write' if args.write else 'dry-run'}")
    return 1 if aborts else 0


if __name__ == "__main__":
    sys.exit(main())
