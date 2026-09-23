"""SkillPackage 内容完整性校验（复用渲染器 manifest.json 的 outputs 表）。

覆盖三层：
1. 内核：`read_bytes_under_root` / `read_text_with_digest_under_root` 的字节语义与围栏；
2. `SkillPackage` 的校验语义（漂移即显性失败；未托管包零行为变化；凭据不可用时不误伤）；
3. 契约护栏：读路径必须走**带摘要**的通道（回退到纯文本通道 = 静默丢掉校验）。
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

import pytest

from heagent.memory.skill_packages import (
    SkillPackage,
    SkillPackageEntryError,
    SkillPackageResourceError,
)
from heagent.tools.path_safety import (
    WorkspacePathError,
    read_bytes_under_root,
    read_text_with_digest_under_root,
)

_ENTRY = "---\nname: he-build\ndescription: Build\n---\n\n# Build\n"
_NOTE = "note body\n"
_TEMPLATE = "template body\n"


def _write(path: Path, text: str, *, newline: str = "\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _managed_package(root: Path, *, newline: str = "\n", upper: bool = False) -> dict[str, str]:
    """建一个「渲染器托管包」：文件 + manifest.json（outputs 为逐文件 sha256）。"""
    files = {"SKILL.md": _ENTRY, "references/note.md": _NOTE, "templates/x.md": _TEMPLATE}
    for name, text in files.items():
        _write(root / name, text, newline=newline)
    outputs = {name: _digest(root / name) for name in files}
    if upper:
        outputs = {name: value.upper() for name, value in outputs.items()}
    (root / "manifest.json").write_text(
        json.dumps({"schema_version": "1", "skill": "he-build", "outputs": outputs}, ensure_ascii=False),
        encoding="utf-8",
    )
    return outputs


class TestManagedPackage:
    """合法凭据在位的正常路径。"""

    def test_reads_entry_and_resources(self, tmp_path: Path) -> None:
        _managed_package(tmp_path)
        package = SkillPackage(skill_id="he-build", root=tmp_path)

        assert package.read_entry().metadata.name == "he-build"
        assert package.read_reference("note.md") == _NOTE
        assert package.read_template("x.md") == _TEMPLATE

    def test_modified_resource_is_rejected(self, tmp_path: Path) -> None:
        """生成后被改写：读取显性失败（不再静默把漂移内容喂进上下文）。"""
        _managed_package(tmp_path)
        _write(tmp_path / "references" / "note.md", "tampered\n")
        package = SkillPackage(skill_id="he-build", root=tmp_path)

        with pytest.raises(SkillPackageResourceError, match="content hash differs from manifest.json"):
            package.read_reference("note.md")

    def test_modified_entry_is_rejected(self, tmp_path: Path) -> None:
        _managed_package(tmp_path)
        _write(tmp_path / "SKILL.md", _ENTRY + "injected\n")

        with pytest.raises(SkillPackageEntryError, match="content hash differs from manifest.json"):
            SkillPackage(skill_id="he-build", root=tmp_path).read_entry()

    def test_truncated_resource_is_rejected(self, tmp_path: Path) -> None:
        _managed_package(tmp_path)
        (tmp_path / "templates" / "x.md").write_bytes(b"")

        with pytest.raises(SkillPackageResourceError, match="content hash differs"):
            SkillPackage(skill_id="he-build", root=tmp_path).read_template("x.md")

    def test_crlf_files_verify_against_raw_byte_hash(self, tmp_path: Path) -> None:
        """固有 CRLF 的文件必须校验通过——摘要取**原始字节**，而非归一化后的文本。"""
        outputs = _managed_package(tmp_path, newline="\r\n")
        assert "\r" in (tmp_path / "references" / "note.md").read_bytes().decode("utf-8")
        assert outputs["references/note.md"] == _digest(tmp_path / "references" / "note.md")

        text = SkillPackage(skill_id="he-build", root=tmp_path).read_reference("note.md")

        assert text == _NOTE  # 文本侧仍是 LF 归一（历史行为不变）

    def test_uppercase_hashes_accepted(self, tmp_path: Path) -> None:
        _managed_package(tmp_path, upper=True)
        assert SkillPackage(skill_id="he-build", root=tmp_path).read_reference("note.md") == _NOTE

    def test_unlisted_resource_is_allowed(self, tmp_path: Path) -> None:
        """清单只钉它生成的那批文件；包内新增文件不是本校验的对象。"""
        _managed_package(tmp_path)
        _write(tmp_path / "references" / "extra.md", "extra\n")

        assert SkillPackage(skill_id="he-build", root=tmp_path).read_reference("extra.md") == "extra\n"

    def test_manifest_is_read_once_per_package(self, tmp_path: Path) -> None:
        """凭据懒加载并缓存：首次读后即便清单被改坏，同一实例行为稳定（不中途变脸）。"""
        _managed_package(tmp_path)
        package = SkillPackage(skill_id="he-build", root=tmp_path)
        assert package.read_reference("note.md") == _NOTE

        (tmp_path / "manifest.json").write_text("{ not json", encoding="utf-8")

        assert package.read_reference("note.md") == _NOTE


class TestUnmanagedOrUnusable:
    """无凭据 / 凭据不可用：不得误伤（手写技能占多数）。"""

    def test_absent_manifest_is_transparent(self, tmp_path: Path) -> None:
        _write(tmp_path / "SKILL.md", _ENTRY)
        _write(tmp_path / "references" / "note.md", _NOTE)
        package = SkillPackage(skill_id="he-build", root=tmp_path)

        assert package._pinned_hashes() == {}
        assert package.read_reference("note.md") == _NOTE
        assert package.read_entry().metadata.name == "he-build"

    def test_corrupt_manifest_is_ignored_with_warning(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        _managed_package(tmp_path)
        (tmp_path / "manifest.json").write_text("{ not json", encoding="utf-8")

        with caplog.at_level("WARNING", logger="heagent.memory.skill_packages"):
            package = SkillPackage(skill_id="he-build", root=tmp_path)
            assert package._pinned_hashes() == {}
            assert package.read_reference("note.md") == _NOTE

        assert "not valid JSON" in caplog.text

    def test_manifest_without_usable_hashes_is_ignored_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """装有 manifest.json 但不是哈希清单（可能是别的工具）→ 跳过校验并告警。"""
        _write(tmp_path / "SKILL.md", _ENTRY)
        (tmp_path / "manifest.json").write_text(json.dumps({"outputs": {"SKILL.md": "not-a-hash"}}), encoding="utf-8")

        with caplog.at_level("WARNING", logger="heagent.memory.skill_packages"):
            package = SkillPackage(skill_id="he-build", root=tmp_path)
            assert package._pinned_hashes() == {}
            assert package.read_entry().metadata.name == "he-build"

        assert "no usable 'outputs' hashes" in caplog.text

    def test_pinned_hashes_are_cached(self, tmp_path: Path) -> None:
        _managed_package(tmp_path)
        package = SkillPackage(skill_id="he-build", root=tmp_path)

        first = package._pinned_hashes()
        assert package._pinned_hashes() is first  # 同一对象：确实走了缓存


class TestSafeOpenKernel:
    """内核的字节语义与围栏（内容校验依赖它们）。"""

    def test_read_bytes_returns_raw_bytes(self, tmp_path: Path) -> None:
        _write(tmp_path / "x.md", "a\nb\n", newline="\r\n")

        assert read_bytes_under_root(tmp_path, tmp_path / "x.md") == b"a\r\nb\r\n"

    def test_digest_is_over_raw_bytes_while_text_is_normalized(self, tmp_path: Path) -> None:
        _write(tmp_path / "x.md", "a\nb\n", newline="\r\n")

        text, digest = read_text_with_digest_under_root(tmp_path, tmp_path / "x.md")

        assert text == "a\nb\n"
        assert digest == hashlib.sha256(b"a\r\nb\r\n").hexdigest()

    def test_kernel_still_fences_escapes(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside.md"
        outside.write_text("secret\n", encoding="utf-8")

        with pytest.raises(WorkspacePathError):
            read_bytes_under_root(tmp_path, outside)


class TestCredentialProbe:
    """凭据读取本身的行为（解释「为什么读资源时会多一次 open」）。"""

    def test_credential_is_probed_once_at_package_root(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _managed_package(tmp_path)
        opened: list[Path] = []
        original_open = os.open

        def record_open(path: str | os.PathLike[str], flags: int, *args: object) -> int:
            opened.append(Path(path).resolve())
            return original_open(path, flags, *args)

        monkeypatch.setattr(os, "open", record_open)
        package = SkillPackage(skill_id="he-build", root=tmp_path)

        assert package.read_reference("note.md") == _NOTE
        assert package.read_template("x.md") == _TEMPLATE

        manifest_reads = [path for path in opened if path.name == "manifest.json"]
        assert manifest_reads == [(tmp_path / "manifest.json").resolve()]  # 懒加载 + 缓存：至多一次


def test_skill_package_reads_go_through_the_digest_channel() -> None:
    """契约：`SkillPackage` 的读必须走带摘要的通道。

    回退成纯文本通道（`open_text_under_root`）会**静默**丢掉内容校验——本断言把这条
    只写在文档里的约束钉成可执行检查。
    """
    source = Path("src/heagent/memory/skill_packages.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

    assert "read_text_with_digest_under_root" in called
    assert "open_text_under_root" not in called
