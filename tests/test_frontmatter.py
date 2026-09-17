"""共享 frontmatter 解析模块（``heagent.frontmatter``）的直测。

六个历史调用方（artifacts / skills / skill_packages ×2 / slash / roles）的行为由各自既有
测试锁定；本文件锁定共享内核自身的关键边界——尤其是**两个分隔符变体的差异**（收敛时有意
保留，统一会改变某一侧 EOF 结尾文件的解析结果）。
"""

from __future__ import annotations

import pytest

from heagent.frontmatter import (
    FrontmatterSyntaxError,
    parse_inline_pairs,
    parse_scalar,
    parse_strict_pairs,
    split_frontmatter,
)


class TestSplitFrontmatter:
    def test_eof_variant_accepts_frontmatter_closed_at_eof(self) -> None:
        """EOF 变体：闭合 ``---`` 后没有换行（文件直接结束）也能解析。"""
        text = "---\nid: a\n---"
        split = split_frontmatter(text, closed_at_eof=True)
        assert split is not None
        raw, end, body = split
        assert raw == "id: a"
        assert end == len(text)
        assert body == ""

    def test_newline_variant_rejects_frontmatter_closed_at_eof(self) -> None:
        """换行变体：同样文本不匹配（历史 skills/slash/roles/metadata 语义）。"""
        assert split_frontmatter("---\nid: a\n---") is None

    def test_newline_variant_accepts_trailing_newline(self) -> None:
        text = "---\nid: a\n---\n正文"
        split = split_frontmatter(text)
        assert split is not None
        raw, _end, body = split
        assert raw == "id: a"
        assert body == "正文"

    def test_both_variants_agree_on_trailing_newline(self) -> None:
        """同一带尾随换行的文本，两变体的 (raw, end, body) 完全一致。"""
        text = "---\nid: a\n---\n正文"
        assert split_frontmatter(text, closed_at_eof=True) == split_frontmatter(text)

    def test_no_frontmatter_returns_none(self) -> None:
        assert split_frontmatter("没有 frontmatter 的正文") is None
        assert split_frontmatter("", closed_at_eof=True) is None

    def test_frontmatter_must_start_at_first_line(self) -> None:
        assert split_frontmatter("前言\n---\nid: a\n---\n") is None


class TestParseStrictPairs:
    def test_skips_blank_and_comment_lines(self) -> None:
        assert parse_strict_pairs("id: a\n\n# 注释\nname: b") == {"id": " a", "name": " b"}

    def test_raw_values_are_not_stripped(self) -> None:
        """返回冒号后的原始值（strip 是调用方职责——artifacts 的 parse_scalar 内部 strip）。"""
        assert parse_strict_pairs("k:  value  ") == {"k": "  value  "}

    def test_line_without_colon_raises_with_line_number(self) -> None:
        with pytest.raises(FrontmatterSyntaxError) as exc_info:
            parse_strict_pairs("ok: a\n没有冒号")
        assert exc_info.value.kind == "invalid_line"
        assert exc_info.value.line_number == 2
        assert exc_info.value.line == "没有冒号"

    def test_leading_whitespace_line_raises(self) -> None:
        with pytest.raises(FrontmatterSyntaxError) as exc_info:
            parse_strict_pairs("ok: a\n  缩进: b")
        assert exc_info.value.kind == "invalid_line"
        assert exc_info.value.line_number == 2

    def test_duplicate_key_raises(self) -> None:
        with pytest.raises(FrontmatterSyntaxError) as exc_info:
            parse_strict_pairs("k: a\nk: b")
        assert exc_info.value.kind == "bad_key"
        assert exc_info.value.key == "k"

    def test_empty_key_raises(self) -> None:
        with pytest.raises(FrontmatterSyntaxError) as exc_info:
            parse_strict_pairs("k: a\n: b")
        assert exc_info.value.kind == "bad_key"

    def test_line_number_counts_skipped_lines(self) -> None:
        """行号按 raw 块全部行计（与历史 artifacts 语义一致，空行/注释也占号）。"""
        with pytest.raises(FrontmatterSyntaxError) as exc_info:
            parse_strict_pairs("# c\n\n坏行")
        assert exc_info.value.line_number == 3


class TestParseInlinePairs:
    def test_prefix_mode_only_matches_known_keys(self) -> None:
        pairs = parse_inline_pairs("name: a\nunknown: x\ndescription: b", keys=("name", "description"))
        assert pairs == {"name": " a", "description": " b"}

    def test_prefix_mode_is_anchored(self) -> None:
        """``negative_triggers`` 不得命中 ``triggers`` 前缀（startswith 锚定在行首）。"""
        pairs = parse_inline_pairs("negative_triggers: [x]", keys=("triggers", "negative_triggers"))
        assert pairs == {"negative_triggers": " [x]"}

    def test_prefix_mode_duplicate_line_overrides(self) -> None:
        pairs = parse_inline_pairs("name: a\nname: b", keys=("name",))
        assert pairs == {"name": " b"}

    def test_prefix_mode_tolerates_indentation(self) -> None:
        assert parse_inline_pairs("  name: a", keys=("name",)) == {"name": " a"}

    def test_empty_keys_mode_accepts_any_colon_line(self) -> None:
        """keys=()：任意含冒号行按首个冒号拆分、key 取 strip（_parse_metadata 历史语义）。"""
        pairs = parse_inline_pairs("  k1: v1\nk2: v2")
        assert pairs == {"k1": " v1", "k2": " v2"}

    def test_empty_keys_mode_keeps_comment_lines(self) -> None:
        """历史语义：注释行不做特殊处理（`# foo` 作为 key 保留）。"""
        assert parse_inline_pairs("# tag: x") == {"# tag": " x"}

    def test_never_raises_on_malformed_content(self) -> None:
        assert parse_inline_pairs("没有冒号\n: 空键\n\t坏行") == {"": " 空键"}


class TestParseScalar:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("", ""),
            ("  ", ""),
            ("[1, 2]", [1, 2]),
            ('{"a": 1}', {"a": 1}),
            ("{invalid json: }", "{invalid json: }"),  # JSON 失败后 ast 亦失败 → 原样字符串
            ("(1, 2)", "(1, 2)"),  # 圆括号不走 json/ast 分支（仅 [/{ 开头尝试）
            ('"quoted"', "quoted"),
            ("'quoted'", "quoted"),
            ("true", True),
            ("False", False),
            ("TRUE", True),
            ("plain", "plain"),
            ("not a list [", "not a list ["),
        ],
    )
    def test_scalar_coercion(self, raw: str, expected: object) -> None:
        assert parse_scalar(raw) == expected
