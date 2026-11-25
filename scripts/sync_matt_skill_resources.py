#!/usr/bin/env python3
"""把 mattpocock 技能包的非 SKILL.md 资源同步进全局技能库。

背景：HeAgent 的技能写入工具（skill_create / skill_update）只能改 SKILL.md 与 meta.yaml，
改不了 ``references/``、``scripts/``、模板等包内资源；而全局技能根
（``~/.heagent/skills``，Windows = ``%USERPROFILE%\\.heagent\\skills``）不在容器挂载面内，
容器侧无法直接写。本脚本补上这一段：资源包在仓库内生成，脚本在**宿主**跑一次即完成同步。

用法::

    python scripts/sync_matt_skill_resources.py --dry-run              # 先看会改哪些文件
    python scripts/sync_matt_skill_resources.py                        # 实际同步
    python scripts/sync_matt_skill_resources.py --meta-version 1.3.2   # 顺带把 meta.yaml 版本对齐
    python scripts/sync_matt_skill_resources.py --fix-name-field       # 修 frontmatter 名字事故
    python scripts/sync_matt_skill_resources.py --verify               # 只核对现状，不写盘

行为：

- 只复制 ``<source>/<skill>/references/**`` 下的文件，**绝不**触碰目标目录的 ``SKILL.md``
  （那个由技能工具维护，含正文与触发面）；``meta.yaml`` 只在你显式传 ``--meta-version`` 或
  ``--fix-name-field`` 时改写单行，其余字段原样保留（含 usage_count 等运行期计数）。
- 目标已存在且内容相同的文件跳过；内容不同的覆盖前打印一行 ``overwrite``。
- 缺少目标技能目录时按原样创建（用于补装新技能的资源）。
- ``--fix-name-field`` 校准 ``SKILL.md`` 的 ``name:`` 与 ``meta.yaml`` 的 ``canonical_id:``
  为目录名，用于修历史导入事故（例如 ``matt-teach`` 的 frontmatter 被写成 ``matt-each``）。
  只改 frontmatter 内那两行，其它正文一字不动。
- 退出码：``0`` 正常，``2`` 前提缺失（源包或目标根不存在）。
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

PROTECTED = {"SKILL.md", "meta.yaml", "SKILL.md.lock", "meta.yaml.lock"}
FRONTMATTER_SCAN_LINES = 40


def _default_source() -> Path:
    return Path(__file__).resolve().parent.parent / ".heagent" / "tmp" / "matt-resources-1.3.2"


def _default_target() -> Path:
    return Path.home() / ".heagent" / "skills"


def _replace_leading_key(path: Path, key: str, value: str, *, limit: int | None, dry_run: bool = False) -> bool:
    """把文件里第一条 ``key: ...`` 换成 ``key: value``；找不到或值已一致时返回 False。"""
    if not path.is_file():
        return False
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    scope = lines if limit is None else lines[:limit]
    for index, line in enumerate(scope):
        if line.startswith(f"{key}:"):
            replacement = f"{key}: {value}\n"
            if line == replacement:
                return False
            if not dry_run:
                lines[index] = replacement
                path.write_text("".join(lines), encoding="utf-8")
            return True
    return False


def _verify(target: Path, skills: list[str]) -> int:
    print("== verify ==")
    for skill in skills:
        skill_dir = target / skill
        if not skill_dir.is_dir():
            print(f"missing   {skill}/")
            continue
        version = "?"
        meta_path = skill_dir / "meta.yaml"
        if meta_path.is_file():
            for line in meta_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("version:"):
                    version = line.split(":", 1)[1].strip()
                    break
        refs = skill_dir / "references"
        names = sorted(p.name for p in refs.iterdir()) if refs.is_dir() else []
        print(f"{skill}: version={version} references={len(names)}")
        if names:
            print(f"    {', '.join(names)}")
    return 0


def sync(
    source: Path,
    target: Path,
    *,
    dry_run: bool,
    meta_version: str | None = None,
    fix_name_field: bool = False,
) -> int:
    if not source.is_dir():
        print(f"error: source directory not found: {source}", file=sys.stderr)
        return 2
    if not target.is_dir():
        print(f"error: target skills root not found: {target}", file=sys.stderr)
        return 2

    copied = skipped = missing = 0
    skills = sorted(p.name for p in source.iterdir() if p.is_dir())
    for skill in skills:
        skill_dir = source / skill
        skill_target = target / skill
        if not skill_target.is_dir():
            missing += 1
            print(f"create    {skill}/ (not installed in target root)")
        for src in sorted(p for p in skill_dir.rglob("*") if p.is_file()):
            if src.name in PROTECTED:
                continue
            rel = src.relative_to(skill_dir)
            dst = skill_target / rel
            if dst.exists() and filecmp.cmp(src, dst, shallow=False):
                skipped += 1
                continue
            action = "overwrite" if dst.exists() else "write"
            print(f"{action:9} {skill}/{rel.as_posix()}")
            copied += 1
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
        if meta_version and _replace_leading_key(
            skill_target / "meta.yaml", "version", meta_version, limit=None, dry_run=dry_run
        ):
            print(f"{'would bump' if dry_run else 'bump':10} {skill}/meta.yaml version -> {meta_version}")
        if fix_name_field:
            if _replace_leading_key(
                skill_target / "SKILL.md", "name", skill, limit=FRONTMATTER_SCAN_LINES, dry_run=dry_run
            ):
                print(f"{'would fix' if dry_run else 'fix':10} {skill}/SKILL.md name -> {skill}")
            if _replace_leading_key(skill_target / "meta.yaml", "canonical_id", skill, limit=None, dry_run=dry_run):
                print(f"{'would fix' if dry_run else 'fix':10} {skill}/meta.yaml canonical_id -> {skill}")

    verb = "would write" if dry_run else "wrote"
    print(f"\n{verb} {copied} file(s), skipped {skipped} identical, {missing} skill dir(s) to create")
    if dry_run:
        print("dry-run only; re-run without --dry-run to apply")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync mattpocock skill resources into the global skills root.")
    parser.add_argument("--source", type=Path, default=_default_source())
    parser.add_argument("--target", type=Path, default=_default_target())
    parser.add_argument("--meta-version", default=None, help="rewrite meta.yaml version to this value (e.g. 1.3.2)")
    parser.add_argument(
        "--fix-name-field",
        action="store_true",
        help="align SKILL.md name and meta.yaml canonical_id with the directory name",
    )
    parser.add_argument("--verify", action="store_true", help="only report current version and references per skill")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.source.is_dir():
        print(f"error: source directory not found: {args.source}", file=sys.stderr)
        return 2
    skills = sorted(p.name for p in args.source.iterdir() if p.is_dir())
    if args.verify:
        return _verify(args.target, skills)

    print(f"source: {args.source}\ntarget: {args.target}\n")
    return sync(
        args.source,
        args.target,
        dry_run=args.dry_run,
        meta_version=args.meta_version,
        fix_name_field=args.fix_name_field,
    )


if __name__ == "__main__":
    raise SystemExit(main())
