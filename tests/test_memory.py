"""Tests for memory: skills, facts, profile."""

from __future__ import annotations

import logging
import threading

import pytest

from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skills import SkillRewriteError, SkillStore


ROLE_CONTRACT = """---
name: code_review
description: "手写角色契约：以三镜头审查代码变更"
created: 2026-01-01T00:00:00
tags: [code-review, adversarial, edge-case, verification-gap, goal-workflow, epic-closure]
usage_count: 0
---

# code_review

## 角色与职责

你是一名对抗式评审员。

## 镜头一（对抗式）

先假设变更是错的，再看它为何能通过测试。

## 镜头二（边界追踪）

追踪空值、并发与超长输入边界。

## 输出格式

- 每条发现带严重度与处置

## 禁止

- 不得修改期望值来迁就实现
"""


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

    def test_update_and_usage_from_separate_stores_do_not_lose_counter(
        self, tmp_path: object, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        base_dir = tmp_path / "sk"  # type: ignore[operator]
        updater = SkillStore(base_dir=str(base_dir))
        recorder = SkillStore(base_dir=str(base_dir))
        updater.save("shared", "old", "pattern", ["step"])
        rendering = threading.Event()
        release = threading.Event()
        original_render = updater._render_skill_md

        def blocked_render(*args: object, **kwargs: object) -> str:
            rendering.set()
            assert release.wait(timeout=5)
            return original_render(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(updater, "_render_skill_md", blocked_render)
        update_thread = threading.Thread(target=updater.update, kwargs={"name": "shared", "description": "new"})
        update_thread.start()
        assert rendering.wait(timeout=5)
        usage_thread = threading.Thread(target=recorder.record_usage, args=("shared",))
        usage_thread.start()
        release.set()
        update_thread.join(timeout=5)
        usage_thread.join(timeout=5)

        assert not update_thread.is_alive() and not usage_thread.is_alive()
        parsed = updater.parse("shared")
        assert parsed is not None
        assert parsed.description == "new"
        assert parsed.usage_count == 1

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

    def test_cjk_pattern_matches_without_whitespace(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("stock_analysis", "A-share analysis", "股票 技术分析", ["step"])
        assert s.matching_skills("帮我分析股票走势", threshold=0.3) == ["stock_analysis"]

    def test_trigger_beats_pattern_and_priority_breaks_ties(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("pattern", "Pattern", "部署", ["step"], priority=99)
        s.save("trigger_low", "Trigger", "无关", ["step"], triggers=["发布生产"], priority=1)
        s.save("trigger_high", "Trigger", "无关", ["step"], triggers=["发布生产"], priority=2)
        assert s.matching_skills("请部署并发布生产", threshold=0.3) == ["trigger_high", "trigger_low", "pattern"]

    def test_negative_trigger_rejects_an_otherwise_matching_skill(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save(
            "deploy",
            "Deploy",
            "部署 生产",
            ["step"],
            triggers=["部署"],
            negative_triggers=["不要执行"],
        )
        assert s.matching_skills("部署生产环境，但不要执行", threshold=0.3) == []

    def test_new_metadata_round_trips_and_update_preserves_it(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("deploy", "Deploy", "部署", ["step"], triggers=["发布"], negative_triggers=["只读"], priority=7)
        s.update("deploy", description="Updated")
        parsed = s.parse("deploy")
        assert parsed is not None
        assert parsed.triggers == ["发布"]
        assert parsed.negative_triggers == ["只读"]
        assert parsed.priority == 7

    def test_matching_skills_sorted_by_relevance(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("low", "Low", "a b c d e f g", ["step"])  # 1/7 ≈ 0.14
        s.save("high", "High", "a b c", ["step"])  # 3/3 = 1.0
        s.save("mid", "Mid", "a b c d e", ["step"])  # 3/5 = 0.6
        matched = s.matching_skills("a b c", threshold=0.1)
        assert matched == ["high", "mid", "low"]

    def test_record_usage_increments_counters_for_canonical_skill(self, tmp_path: object) -> None:
        s = SkillStore(base_dir=str(tmp_path / "sk"))  # type: ignore[operator]
        s.save("canon", "Canonical", "canonical pattern", ["step one", "step two"])
        s.record_usage("canon")
        parsed = s.parse("canon")
        assert parsed is not None
        assert parsed.usage_count == 1
        assert parsed.last_used
        assert parsed.pattern == "canonical pattern"
        assert parsed.steps == ["step one", "step two"]

    def test_record_usage_preserves_sections_the_renderer_cannot_express(self, tmp_path: object) -> None:
        """回归：正文含 Pattern/Steps 之外的章节时不得整体重渲染（原缺陷会丢正文）。"""
        base = tmp_path / "sk"  # type: ignore[operator]
        skill_dir = base / "role_contract"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        md.write_text(ROLE_CONTRACT, encoding="utf-8")
        s = SkillStore(base_dir=str(base))
        s.record_usage("role_contract")
        after = md.read_text(encoding="utf-8")
        parsed = s.parse("role_contract")
        assert parsed is not None
        assert parsed.usage_count == 1
        assert parsed.last_used
        assert "usage_count: 1" in after
        # 正文（frontmatter 之后）逐字节保留，只有 frontmatter 计数被就地改写
        assert after.split("\n---\n", 1)[1] == ROLE_CONTRACT.split("\n---\n", 1)[1]

    def test_record_usage_keeps_extra_sections_beside_pattern_and_steps(self, tmp_path: object) -> None:
        """deploy_production 形态：既有 Pattern/Steps，又有额外阶段章节，两者都须保留。"""
        base = tmp_path / "sk"  # type: ignore[operator]
        s = SkillStore(base_dir=str(base))
        s.save("deploy", "Deploy", "deploy to production", ["push"])
        md = base / "deploy" / "SKILL.md"
        before = md.read_text(encoding="utf-8")
        extra = "## 阶段一：检查\n\n先跑全量测试。\n"
        md.write_text(before + extra, encoding="utf-8")
        s.record_usage("deploy")
        after = md.read_text(encoding="utf-8")
        parsed = s.parse("deploy")
        assert parsed is not None
        assert parsed.usage_count == 1
        # 解析器把未识别的 ## 章节折进 Steps（重渲染即 mangle 正文），故断言正文逐字节保留
        assert after.split("\n---\n", 1)[1] == before.split("\n---\n", 1)[1] + extra

    def test_auto_matched_contract_skill_survives_usage_recording(self, tmp_path: object) -> None:
        """端到端回归：tags 词元命中 → 注入 → record_usage 后契约仍是全文（曾 130 行 → 411 字符）。"""
        base = tmp_path / "sk"  # type: ignore[operator]
        skill_dir = base / "code_review"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        md.write_text(ROLE_CONTRACT, encoding="utf-8")
        s = SkillStore(base_dir=str(base))
        prompt = "please review this code and check the workflow for the epic"
        assert s.matching_skills(prompt, threshold=0.3) == ["code_review"]
        s.record_usage("code_review")
        after = md.read_text(encoding="utf-8")
        parsed = s.parse("code_review")
        assert parsed is not None
        assert parsed.steps == []  # 该形态本无 Steps，正是原缺陷的触发条件
        assert parsed.usage_count == 1
        assert "## 禁止" in after
        assert len(after) >= len(ROLE_CONTRACT)

    def test_record_usage_leaves_frontmatter_less_skill_untouched(
        self, tmp_path: object, caplog: pytest.LogCaptureFixture
    ) -> None:
        base = tmp_path / "sk"  # type: ignore[operator]
        skill_dir = base / "raw"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        original = "# raw\n\n## 手写契约\n\n正文。\n"
        md.write_text(original, encoding="utf-8")
        s = SkillStore(base_dir=str(base))
        with caplog.at_level(logging.WARNING):
            s.record_usage("raw")
        assert md.read_text(encoding="utf-8") == original
        assert "usage not recorded" in caplog.text

    def test_update_refuses_body_rewrite_and_keeps_the_contract(self, tmp_path: object) -> None:
        """回归：正文含 Pattern/Steps 之外的章节时，改 pattern/steps 必须显式拒绝而非静默丢正文。"""
        base = tmp_path / "sk"  # type: ignore[operator]
        skill_dir = base / "code_review"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        md.write_text(ROLE_CONTRACT, encoding="utf-8")
        s = SkillStore(base_dir=str(base))
        with pytest.raises(SkillRewriteError):
            s.update("code_review", steps=["rewritten"])
        with pytest.raises(SkillRewriteError):
            s.update("code_review", pattern="rewritten")
        assert md.read_text(encoding="utf-8") == ROLE_CONTRACT  # 一字未改

    def test_update_metadata_in_place_preserves_the_contract(self, tmp_path: object) -> None:
        """元数据字段可就地改写：正文逐字节保留，新值可被 parse 读回。"""
        base = tmp_path / "sk"  # type: ignore[operator]
        skill_dir = base / "code_review"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        md.write_text(ROLE_CONTRACT, encoding="utf-8")
        s = SkillStore(base_dir=str(base))
        path = s.update("code_review", description="新描述", triggers=["评审"], priority=7)
        assert path == str(md)
        parsed = s.parse("code_review")
        assert parsed is not None
        assert parsed.description == "新描述"
        assert parsed.triggers == ["评审"]
        assert parsed.priority == 7
        after = md.read_text(encoding="utf-8")
        assert after.split("\n---\n", 1)[1] == ROLE_CONTRACT.split("\n---\n", 1)[1]

    def test_update_removes_metadata_lines_that_become_empty(self, tmp_path: object) -> None:
        """清空 tags / priority=0 → 规范行被删除（与渲染器的省略规则一致），正文不动。"""
        original = ROLE_CONTRACT.replace(
            "tags: [code-review, adversarial, edge-case, verification-gap, goal-workflow, epic-closure]\n",
            "tags: [x]\npriority: 3\n",
        )
        base = tmp_path / "sk"  # type: ignore[operator]
        skill_dir = base / "code_review"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        md.write_text(original, encoding="utf-8")
        s = SkillStore(base_dir=str(base))
        s.update("code_review", tags=[], priority=0)
        after = md.read_text(encoding="utf-8")
        frontmatter = after.split("\n---\n", 1)[0]
        assert "tags:" not in frontmatter
        assert "priority:" not in frontmatter
        assert after.split("\n---\n", 1)[1] == original.split("\n---\n", 1)[1]

    def test_update_without_frontmatter_is_refused(self, tmp_path: object) -> None:
        """无 frontmatter 块时无法就地改元数据 → 拒绝，而不是重写整个文件。"""
        base = tmp_path / "sk"  # type: ignore[operator]
        skill_dir = base / "raw"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        original = "# raw\n\n## 手写契约\n\n正文。\n"
        md.write_text(original, encoding="utf-8")
        s = SkillStore(base_dir=str(base))
        with pytest.raises(SkillRewriteError):
            s.update("raw", description="x")
        assert md.read_text(encoding="utf-8") == original

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ("# t\n\n## Pattern\n\np\n\n## Steps\n\n1. s\n", True),
            ("# t\n\n## Steps\n\n1. s\n", True),
            ("# t\n\n## 角色与职责\n\n正文\n", False),
            ("# t\n\n## Pattern\n\np\n\n## Steps\n\n1. s\n\n## 附加\n\nx\n", False),
            ("# t\n\n开头说明\n\n## Pattern\n\np\n", False),
            ("# t\n\n## Pattern\n\np\n\n### 小节\n\nx\n", False),
        ],
    )
    def test_body_survives_rerender_detection(self, body: str, expected: bool) -> None:
        assert SkillStore._body_survives_rerender(body) is expected


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
