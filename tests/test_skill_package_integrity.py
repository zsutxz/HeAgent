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

from heagent.memory import skill_packages as skill_packages_module
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
        opened: list[str] = []
        original_open = os.open

        def record_open(path: str | os.PathLike[str], flags: int, *args: object, **kwargs: object) -> int:
            # 逐组件通道下路径是**组件名**（中间目录带 O_DIRECTORY）⇒ 按名字记，跨通道同义。
            opened.append(Path(path).name)
            return original_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", record_open)
        package = SkillPackage(skill_id="he-build", root=tmp_path)

        assert package.read_reference("note.md") == _NOTE
        assert package.read_template("x.md") == _TEMPLATE

        manifest_reads = [name for name in opened if name == "manifest.json"]
        assert manifest_reads == ["manifest.json"]  # 懒加载 + 缓存：至多一次


def _imported_package(
    tmp_path: Path,
    *,
    resources: dict[str, str] | None = None,
    overrides: dict[str, object] | None = None,
    lock_text: str | None = None,
) -> tuple[Path, dict[str, str]]:
    """建一个「导入器托管包」：``<tmp>/skills/he-build/`` + **兄弟** ``manifest.lock``。

    包放在子目录里是**必须**的：lock 的查找位置是 ``root.parent``，而 pytest 的 ``tmp_path`` 之父
    （``pytest-N``）在同一次运行里被多个用例共享——直接写在 ``tmp_path.parent`` 会串味到别的用例。
    """
    root = tmp_path / "skills" / "he-build"
    files = {"SKILL.md": _ENTRY, "references/note.md": _NOTE, "templates/x.md": _TEMPLATE}
    for name, text in files.items():
        _write(root / name, text)
    hashes = {name: _digest(root / name) for name in files} if resources is None else resources
    entry: dict[str, object] = {
        "canonical_id": "he-build",
        "source_id": "he-build",
        "source_path": str(tmp_path / "source" / "he-build"),
        "destination_path": str(root),
        "version": "1.0",
        "source_hash": hashes.get("SKILL.md", ""),
        "resources": hashes,
    }
    if overrides:
        entry.update(overrides)
    text = lock_text if lock_text is not None else json.dumps({"version": 1, "entries": [entry]}, ensure_ascii=False)
    (root.parent / "manifest.lock").write_text(text, encoding="utf-8")
    return root, hashes


class TestImportedPackageCredential:
    """A1④ 的读侧：``manifest.lock`` 的 ``resources`` 也参与内容校验（与渲染器凭据同形）。"""

    def test_reads_entry_and_resources(self, tmp_path: Path) -> None:
        root, _ = _imported_package(tmp_path)
        package = SkillPackage(skill_id="he-build", root=root)

        assert package.read_entry().metadata.name == "he-build"
        assert package.read_reference("note.md") == _NOTE
        assert package.read_template("x.md") == _TEMPLATE

    def test_modified_resource_is_rejected(self, tmp_path: Path) -> None:
        """导入后被改写 ⇒ 读取显性失败（此前 lock 只钉入口 ⇒ 包内漂移无人发现）。"""
        root, _ = _imported_package(tmp_path)
        _write(root / "references" / "note.md", "tampered\n")

        with pytest.raises(SkillPackageResourceError, match="content hash differs from manifest.lock"):
            SkillPackage(skill_id="he-build", root=root).read_reference("note.md")

    def test_modified_entry_is_rejected(self, tmp_path: Path) -> None:
        root, _ = _imported_package(tmp_path)
        _write(root / "SKILL.md", _ENTRY + "injected\n")

        with pytest.raises(SkillPackageEntryError, match="content hash differs from manifest.lock"):
            SkillPackage(skill_id="he-build", root=root).read_entry()

    def test_unlisted_resource_is_allowed(self, tmp_path: Path) -> None:
        """与渲染器凭据同口径：只钉列出的文件，包内新增文件不拒读。"""
        root, _ = _imported_package(tmp_path)
        _write(root / "references" / "extra.md", "extra\n")

        assert SkillPackage(skill_id="he-build", root=root).read_reference("extra.md") == "extra\n"

    def test_lock_without_this_package_is_transparent(self, tmp_path: Path) -> None:
        root, _ = _imported_package(
            tmp_path,
            overrides={"canonical_id": "bmad-other", "destination_path": str(tmp_path / "skills" / "bmad-other")},
        )
        package = SkillPackage(skill_id="he-build", root=root)

        assert package._pinned_hashes() == {}
        assert package.read_reference("note.md") == _NOTE

    def test_corrupt_lock_is_ignored_with_warning(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        root, _ = _imported_package(tmp_path, lock_text="{ not json")

        with caplog.at_level("WARNING", logger="heagent.memory.skill_packages"):
            package = SkillPackage(skill_id="he-build", root=root)
            assert package._pinned_hashes() == {}
            assert package.read_reference("note.md") == _NOTE

        assert "manifest.lock is not valid JSON" in caplog.text

    def test_legacy_lock_entry_is_transparent_without_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """老 lock（有条目但没 ``resources``）= 升级路径：既不改行为、也不刷告警。"""
        root, _ = _imported_package(tmp_path)
        lock_path = root.parent / "manifest.lock"
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
        del payload["entries"][0]["resources"]  # 2026-09-28 之前写下的 lock 就是没有这个键
        lock_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        with caplog.at_level("WARNING", logger="heagent.memory.skill_packages"):
            package = SkillPackage(skill_id="he-build", root=root)
            assert package._pinned_hashes() == {}
            assert package.read_reference("note.md") == _NOTE

        assert "manifest.lock" not in caplog.text

    def test_lock_with_unusable_hashes_is_ignored_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        root, _ = _imported_package(tmp_path, overrides={"resources": {"SKILL.md": "not-a-hash"}})

        with caplog.at_level("WARNING", logger="heagent.memory.skill_packages"):
            package = SkillPackage(skill_id="he-build", root=root)
            assert package._pinned_hashes() == {}
            assert package.read_reference("note.md") == _NOTE

        assert "no usable 'resources' hashes" in caplog.text

    def test_renderer_credential_takes_precedence(self, tmp_path: Path) -> None:
        """两种凭据同时存在（包内 ``manifest.json`` **优先**）：渲染器是包内容的直接生产者。

        这里让 lock 的摘要与文件不符：若 precedence 反了，读取会失败。
        """
        root = tmp_path / "skills" / "he-build"
        _managed_package(root)
        _imported_package(tmp_path, resources={"SKILL.md": "0" * 64})

        assert SkillPackage(skill_id="he-build", root=root).read_reference("note.md") == _NOTE

    def test_lock_entry_matches_by_canonical_id_when_the_path_moved(self, tmp_path: Path) -> None:
        """包被移动/改名（``destination_path`` 对不上）时按 ``canonical_id`` 兜底——凭据是内容寻址的。"""
        root, _ = _imported_package(tmp_path, overrides={"destination_path": str(tmp_path / "elsewhere" / "he-build")})
        _write(root / "references" / "note.md", "tampered\n")

        with pytest.raises(SkillPackageResourceError, match="content hash differs from manifest.lock"):
            SkillPackage(skill_id="he-build", root=root).read_reference("note.md")

    @pytest.mark.parametrize("lock_text", ['{"entries": "nope"}', '{"entries": [42]}', "[]"])
    def test_malformed_lock_shape_is_transparent_without_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, lock_text: str
    ) -> None:
        """形状不符（``entries`` 不是列表 / 条目不是对象）既不告警也不改行为——只当没有凭据。"""
        root, _ = _imported_package(tmp_path, lock_text=lock_text)

        with caplog.at_level("WARNING", logger="heagent.memory.skill_packages"):
            package = SkillPackage(skill_id="he-build", root=root)
            assert package._pinned_hashes() == {}
            assert package.read_reference("note.md") == _NOTE

        assert "manifest.lock" not in caplog.text

    def test_lock_deleted_between_stat_and_read_is_transparent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """stat 通过后、open 之前被删 ⇒ 等同未托管（不告警、不改行为）。"""
        root, _ = _imported_package(tmp_path)

        def gone(*_args: object, **_kwargs: object) -> bytes:
            raise FileNotFoundError("raced away")

        monkeypatch.setattr(skill_packages_module, "read_bytes_under_root", gone)
        with caplog.at_level("WARNING", logger="heagent.memory.skill_packages"):
            package = SkillPackage(skill_id="he-build", root=root)
            assert package._pinned_hashes() == {}
            assert package.read_reference("note.md") == _NOTE

        assert "manifest.lock" not in caplog.text

    def test_lock_read_failure_is_ignored_with_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """读凭据本身失败（权限 / 符号链接等）⇒ 告警后跳过，不拒读内容。"""
        root, _ = _imported_package(tmp_path)

        def denied(*_args: object, **_kwargs: object) -> bytes:
            raise PermissionError("nope")

        monkeypatch.setattr(skill_packages_module, "read_bytes_under_root", denied)
        with caplog.at_level("WARNING", logger="heagent.memory.skill_packages"):
            package = SkillPackage(skill_id="he-build", root=root)
            assert package._pinned_hashes() == {}
            assert package.read_reference("note.md") == _NOTE

        assert "manifest.lock unreadable" in caplog.text


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
