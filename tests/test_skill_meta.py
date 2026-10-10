"""meta.yaml 契约单测 + 仓库格式契约（SKILL.md 四键 / meta.yaml 可无损往返）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from heagent.skills.skill_meta import (
    META_FILENAME,
    META_KEYS,
    SKILL_MD_KEYS,
    SkillMeta,
    SkillMetaError,
    detect_legacy_skill_md_keys,
    load_meta,
    normalize_meta_key,
    parse_meta_yaml,
    render_meta_yaml,
)
from heagent.skills.skill_models import parse_skill_md
from heagent.pub.frontmatter import FRONTMATTER_NEWLINE_RE


class TestSkillMetaModel:
    def test_round_trips_all_fields(self) -> None:
        meta = SkillMeta(
            canonical_id="he-goal",
            source_id="legacy",
            aliases=["goal", "g"],
            version="1.0",
            available=False,
            tags=["goal", "workflow"],
            created="2026-09-19",
            priority=3,
            usage_count=7,
            last_used="2026-10-08T17:30:30",
        )
        assert parse_meta_yaml(render_meta_yaml(meta)) == meta

    def test_empty_render_parses_to_defaults(self) -> None:
        assert parse_meta_yaml(render_meta_yaml(SkillMeta())) == SkillMeta()

    def test_render_omits_defaults_and_always_writes_usage_count(self) -> None:
        text = render_meta_yaml(SkillMeta(tags=["a"], usage_count=0))
        assert text == "tags: [a]\nusage_count: 0\n"
        assert "available" not in text and "priority" not in text and "last_used" not in text

    def test_camel_case_aliases_normalize(self) -> None:
        meta = parse_meta_yaml("canonicalId: he-goal\nsourceId: legacy\n")
        assert meta.canonical_id == "he-goal"
        assert meta.source_id == "legacy"
        assert normalize_meta_key("canonicalId") == "canonical_id"

    def test_unknown_key_raises(self) -> None:
        with pytest.raises(SkillMetaError, match="outside the contract"):
            parse_meta_yaml("tags: [a]\nmystery: 1\n")

    def test_invalid_available_flag_raises(self) -> None:
        with pytest.raises(SkillMetaError, match="available flag"):
            parse_meta_yaml("available: maybe\n")

    def test_non_integer_usage_count_raises(self) -> None:
        with pytest.raises(SkillMetaError, match="non-integer"):
            parse_meta_yaml("usage_count: many\n")

    def test_bom_is_stripped(self) -> None:
        assert parse_meta_yaml("﻿".encode().decode() + "tags: [a]\n").tags == ["a"]

    def test_load_meta_missing_file_returns_defaults(self, tmp_path: Path) -> None:
        assert load_meta(tmp_path) == SkillMeta()

    def test_load_meta_reads_file(self, tmp_path: Path) -> None:
        (tmp_path / META_FILENAME).write_text("canonical_id: he-goal\n", encoding="utf-8")
        assert load_meta(tmp_path).canonical_id == "he-goal"


class TestLegacyDetection:
    def test_detects_meta_keys_in_skill_md_frontmatter(self) -> None:
        assert detect_legacy_skill_md_keys("name: x\ncanonical_id: he-x\nusage_count: 1\n") == [
            "canonical_id",
            "usage_count",
        ]

    def test_four_keys_are_not_legacy(self) -> None:
        assert detect_legacy_skill_md_keys("name: x\ntriggers: [a]\n") == []

    def test_parse_skill_md_rejects_legacy_keys(self) -> None:
        raw = "---\nname: x\ncreated: 2026-01-01\n---\n\n# x\n"
        with pytest.raises(SkillMetaError, match="migrate_skill_meta"):
            parse_skill_md("x", raw)

    def test_parse_skill_md_keeps_trigger_surface(self) -> None:
        raw = "---\nname: x\ndescription: d\ntriggers: [t1, t2]\nnegative_triggers: [n]\n---\n\n# x\n"
        parsed = parse_skill_md("x", raw)
        assert parsed.description == "d"
        assert parsed.triggers == ["t1", "t2"]
        assert parsed.negative_triggers == ["n"]
        assert parsed.usage_count == 0  # 计数字段不在 SKILL.md，恒为默认


class TestRepoFormatContract:
    """仓库契约：所有 SKILL.md frontmatter 只含四键，所有 meta.yaml 可被解析器无损往返。

    同时是 _bmad 再生成器/手写技能写回旧格式的拦截网——违反即 CI 红。
    """

    def test_every_skill_md_frontmatter_holds_only_the_trigger_surface(self) -> None:
        skills_root = Path(__file__).resolve().parents[1] / ".heagent" / "skills"
        violations: list[str] = []
        for skill_md in sorted(skills_root.glob("*/SKILL.md")):
            match = FRONTMATTER_NEWLINE_RE.match(skill_md.read_text(encoding="utf-8"))
            if match is None:
                continue
            for line in match.group(1).splitlines():
                key = normalize_meta_key(line.split(":", 1)[0].strip())
                if line.strip() and key not in SKILL_MD_KEYS:
                    violations.append(f"{skill_md.parent.name}: {key}")
        assert violations == []

    def test_every_meta_yaml_round_trips(self) -> None:
        skills_root = Path(__file__).resolve().parents[1] / ".heagent" / "skills"
        violations: list[str] = []
        for meta_file in sorted(skills_root.glob(f"*/{META_FILENAME}")):
            text = meta_file.read_text(encoding="utf-8")
            try:
                if parse_meta_yaml(render_meta_yaml(parse_meta_yaml(text))) != parse_meta_yaml(text):
                    violations.append(meta_file.parent.name)
            except SkillMetaError as exc:
                violations.append(f"{meta_file.parent.name}: {exc}")
        assert violations == []

    def test_contract_key_sets_are_disjoint_and_complete(self) -> None:
        assert not (SKILL_MD_KEYS & META_KEYS)
        assert set(SkillMeta.model_fields) == META_KEYS
