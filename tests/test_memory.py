"""Tests for memory: skills, facts, profile."""

from __future__ import annotations

from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillStore


class TestSkillStore:
    def test_save_and_load(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("deploy", "Deploy app", "git push && deploy", ["push", "deploy"])
        content = s.load("deploy")
        assert content is not None
        assert "1. push" in content

    def test_list(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("a", "a", "p", ["x"])
        s.save("b", "b", "q", ["y"])
        assert s.list_skills() == ["a", "b"]

    def test_delete(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("rm_me", "x", "p", [])
        assert s.delete("rm_me") is True
        assert s.load("rm_me") is None

    def test_all_skills_content(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("a", "desc a", "p", [])
        assert len(s.all_skills_content()) == 1

    def test_name_sanitization(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("my skill/here", "d", "p", [])
        assert s.load("my skill/here") is not None

    def test_parse_existing_skill(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("deploy", "Deploy app", "when deploying to production", ["push code", "run deploy"])
        parsed = s.parse("deploy")
        assert parsed is not None
        assert parsed.name == "deploy"
        assert parsed.description == "Deploy app"
        assert "deploying" in parsed.pattern
        assert parsed.steps == ["push code", "run deploy"]
        assert parsed.created  # 非空

    def test_parse_nonexistent(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        assert s.parse("ghost") is None

    def test_update_description_only(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("skill_a", "old desc", "old pattern", ["old step"])
        s.update("skill_a", description="new desc")
        parsed = s.parse("skill_a")
        assert parsed is not None
        assert parsed.description == "new desc"
        assert parsed.pattern == "old pattern"
        assert parsed.steps == ["old step"]

    def test_update_steps_only(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("skill_b", "desc", "pat", ["step1"])
        s.update("skill_b", steps=["step2", "step3"])
        parsed = s.parse("skill_b")
        assert parsed is not None
        assert parsed.description == "desc"
        assert parsed.steps == ["step2", "step3"]

    def test_update_nonexistent(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        assert s.update("ghost", description="x") is None

    def test_matching_skills_basic(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("deploy", "Deploy", "deploy to production", ["step"])
        matched = s.matching_skills("deploy the app to production", threshold=0.3)
        assert "deploy" in matched

    def test_matching_skills_threshold(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("sparse", "Sparse", "alpha beta gamma delta epsilon", ["step"])
        # "alpha beta" = 2/5 = 0.4 → 匹配 threshold=0.3
        assert "sparse" in s.matching_skills("alpha beta", threshold=0.3)
        # 但不匹配 threshold=0.8
        assert "sparse" not in s.matching_skills("alpha beta", threshold=0.8)

    def test_matching_skills_no_match(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("deploy", "Deploy", "deploy production", ["step"])
        assert s.matching_skills("weather forecast", threshold=0.3) == []

    def test_matching_skills_empty_prompt(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("deploy", "Deploy", "deploy production", ["step"])
        assert s.matching_skills("", threshold=0.3) == []
        assert s.matching_skills("   ", threshold=0.3) == []

    def test_matching_skills_sorted_by_relevance(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("low", "Low", "a b c d e f g", ["step"])  # 1/7 ≈ 0.14
        s.save("high", "High", "a b c", ["step"])  # 3/3 = 1.0
        s.save("mid", "Mid", "a b c d e", ["step"])  # 3/5 = 0.6
        matched = s.matching_skills("a b c", threshold=0.1)
        assert matched == ["high", "mid", "low"]


class TestFactStore:
    def test_add_and_load(self, tmp_path: object) -> None:
        f = FactStore(path=str(tmp_path / "mem.md"))  # type: ignore[operator]
        assert f.add("Python is great") is True
        assert f.add("Rust is fast") is True
        assert f.load() == ["Python is great", "Rust is fast"]

    def test_dedup(self, tmp_path: object) -> None:
        f = FactStore(path=str(tmp_path / "mem.md"))  # type: ignore[operator]
        f.add("the user prefers dark mode")
        assert f.add("user prefers dark mode always") is False
        assert len(f.load()) == 1

    def test_clear(self, tmp_path: object) -> None:
        f = FactStore(path=str(tmp_path / "mem.md"))  # type: ignore[operator]
        f.add("x")
        f.clear()
        assert f.load() == []

    def test_load_empty(self, tmp_path: object) -> None:
        f = FactStore(path=str(tmp_path / "mem.md"))  # type: ignore[operator]
        assert f.load() == []


class TestProfileStore:
    def test_save_and_load(self, tmp_path: object) -> None:
        p = ProfileStore(path=str(tmp_path / "u.md"))  # type: ignore[operator]
        p.save("## Background\nSenior dev")
        assert "Senior dev" in p.load()

    def test_update_section_new(self, tmp_path: object) -> None:
        p = ProfileStore(path=str(tmp_path / "u.md"))  # type: ignore[operator]
        p.update_section("Style", "concise")
        p.update_section("Level", "advanced")
        assert "concise" in p.load()
        assert "advanced" in p.load()

    def test_update_section_replace(self, tmp_path: object) -> None:
        p = ProfileStore(path=str(tmp_path / "u.md"))  # type: ignore[operator]
        p.update_section("Style", "verbose")
        p.update_section("Style", "concise")
        assert "concise" in p.load()
        assert "verbose" not in p.load()

    def test_load_empty(self, tmp_path: object) -> None:
        assert ProfileStore(path=str(tmp_path / "u.md")).load() == ""  # type: ignore[operator]

    def test_clear(self, tmp_path: object) -> None:
        p = ProfileStore(path=str(tmp_path / "u.md"))  # type: ignore[operator]
        p.save("data")
        p.clear()
        assert p.load() == ""
