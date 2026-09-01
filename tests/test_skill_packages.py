"""Tests for declarative skill-package resource access."""

from __future__ import annotations

import os
import asyncio
from pathlib import Path

import pytest

from heagent.memory.skill_packages import (
    SkillCatalog,
    SkillPackage,
    SkillPackageEntryError,
    SkillPackageResourceError,
    SkillResolutionError,
    SkillResolver,
    SkillRunner,
    SkillRunnerState,
    SkillStep,
    SkillStepResult,
)


def make_package(root: Path) -> None:
    (root / "SKILL.md").write_text(
        "---\nname: he-build\ndescription: Build a feature\nversion: 1.2.3\ntags: [build, release]\n---\n\n# Build\n",
        encoding="utf-8",
    )


class TestSkillPackage:
    def test_reads_entry_with_structured_metadata(self, tmp_path: Path) -> None:
        make_package(tmp_path)

        entry = SkillPackage(skill_id="he-build", root=tmp_path).read_entry()

        assert entry.text.endswith("# Build\n")
        assert entry.metadata.skill_id == "he-build"
        assert entry.metadata.name == "he-build"
        assert entry.metadata.description == "Build a feature"
        assert entry.metadata.version == "1.2.3"
        assert entry.metadata.tags == ["build", "release"]
        assert entry.metadata.package_root == str(tmp_path.resolve())

    def test_package_boundary_fields_are_immutable(self, tmp_path: Path) -> None:
        make_package(tmp_path)
        package = SkillPackage(skill_id="he-build", root=tmp_path)

        with pytest.raises((TypeError, ValueError)):
            package.root = tmp_path.parent  # type: ignore[misc]
        with pytest.raises((TypeError, ValueError)):
            package.entrypoint = "../outside.md"  # type: ignore[misc]

    def test_missing_entry_is_a_diagnostic_error(self, tmp_path: Path) -> None:
        package = SkillPackage(skill_id="he-build", root=tmp_path)

        with pytest.raises(SkillPackageEntryError, match=r"he-build.*SKILL.md.*missing"):
            package.read_entry()

    def test_reads_only_the_requested_resource(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        make_package(tmp_path)
        (tmp_path / "step-01.md").write_text("first", encoding="utf-8")
        (tmp_path / "step-02.md").write_text("second", encoding="utf-8")
        reads: list[Path] = []
        original_read_text = Path.read_text

        def record_read(path: Path, *args: object, **kwargs: object) -> str:
            reads.append(path.resolve())
            return original_read_text(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", record_read)

        assert SkillPackage(skill_id="he-build", root=tmp_path).read_step("step-01.md") == "first"
        assert reads == [(tmp_path / "step-01.md").resolve()]

    @pytest.mark.parametrize("path", ["/tmp/outside.md", "C:/outside.md", "../outside.md"])
    def test_rejects_absolute_and_traversal_resource_paths(self, tmp_path: Path, path: str) -> None:
        make_package(tmp_path)

        with pytest.raises(SkillPackageResourceError, match=r"he-build.*(absolute|traverses parent)"):
            SkillPackage(skill_id="he-build", root=tmp_path).read_resource(path)

    def test_missing_resource_is_a_diagnostic_error(self, tmp_path: Path) -> None:
        make_package(tmp_path)

        with pytest.raises(SkillPackageResourceError, match=r"he-build.*references/missing.md.*missing"):
            SkillPackage(skill_id="he-build", root=tmp_path).read_reference("missing.md")

    @pytest.mark.parametrize("path", ["/tmp/outside.md", "C:/outside.md", "../outside.md"])
    def test_directory_helpers_reject_unsafe_raw_paths(self, tmp_path: Path, path: str) -> None:
        make_package(tmp_path)

        with pytest.raises(SkillPackageResourceError, match=r"he-build.*(absolute|traverses parent)"):
            SkillPackage(skill_id="he-build", root=tmp_path).read_reference(path)

    def test_invalid_utf8_entry_is_a_diagnostic_error(self, tmp_path: Path) -> None:
        (tmp_path / "SKILL.md").write_bytes(b"\xff\xfe")

        with pytest.raises(SkillPackageEntryError, match=r"he-build.*cannot read entrypoint"):
            SkillPackage(skill_id="he-build", root=tmp_path).read_entry()

    def test_invalid_utf8_resource_is_a_diagnostic_error(self, tmp_path: Path) -> None:
        make_package(tmp_path)
        (tmp_path / "references").mkdir()
        (tmp_path / "references" / "bad.md").write_bytes(b"\xff\xfe")

        with pytest.raises(SkillPackageResourceError, match=r"he-build.*cannot read resource"):
            SkillPackage(skill_id="he-build", root=tmp_path).read_reference("bad.md")

    @pytest.mark.parametrize(
        ("method_name", "relative_path"),
        [
            ("read_reference", "reference.md"),
            ("read_template", "template.md"),
            ("read_asset", "asset.txt"),
            ("read_script", "script.py"),
        ],
    )
    def test_reads_declared_resource_directories(self, tmp_path: Path, method_name: str, relative_path: str) -> None:
        make_package(tmp_path)
        directory = {
            "read_reference": "references",
            "read_template": "templates",
            "read_asset": "assets",
            "read_script": "scripts",
        }[method_name]
        path = tmp_path / directory / relative_path
        path.parent.mkdir()
        path.write_text(directory, encoding="utf-8")

        assert getattr(SkillPackage(skill_id="he-build", root=tmp_path), method_name)(relative_path) == directory

    @pytest.mark.skipif(os.name == "nt" and not hasattr(os, "symlink"), reason="symlinks unavailable")
    def test_rejects_symlink_that_escapes_package_root(self, tmp_path: Path) -> None:
        make_package(tmp_path)
        outside = tmp_path.parent / "outside.md"
        outside.write_text("secret", encoding="utf-8")
        link = tmp_path / "references" / "escape.md"
        link.parent.mkdir()
        try:
            link.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        with pytest.raises(SkillPackageResourceError, match=r"he-build.*references/escape.md.*escapes"):
            SkillPackage(skill_id="he-build", root=tmp_path).read_reference("escape.md")

    def test_rejects_entrypoint_symlink_that_escapes_package_root(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside-entry.md"
        outside.write_text("secret", encoding="utf-8")
        entry = tmp_path / "SKILL.md"
        try:
            entry.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlink creation unavailable: {exc}")

        with pytest.raises(SkillPackageEntryError, match=r"he-build.*SKILL.md.*escapes"):
            SkillPackage(skill_id="he-build", root=tmp_path).read_entry()


class TestSkillCatalog:
    @staticmethod
    def _write_package(root: Path, name: str, *, version: str = "", entry: bool = True) -> Path:
        package = root / name
        package.mkdir()
        if entry:
            package.joinpath("SKILL.md").write_text(
                f"---\nname: {name}\nversion: {version}\n---\n# {name}\n", encoding="utf-8"
            )
        return package

    def test_scans_multiple_sources_in_canonical_order(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        user = tmp_path / "user"
        project.mkdir()
        user.mkdir()
        self._write_package(project, "bmad-prd", version="1.0")
        self._write_package(user, "he-build", version="2.0")

        entries = SkillCatalog([user, project]).scan()

        assert [entry.canonical_id for entry in entries] == ["he-build", "he-prd"]
        assert entries[1].source_id == "bmad-prd"
        assert entries[1].version == "1.0"
        assert all(entry.available for entry in entries)

    def test_does_not_scan_archived_skill_directory(self, tmp_path: Path) -> None:
        archive = tmp_path / ".archive"
        archive.mkdir()
        self._write_package(archive, "he-old")

        assert SkillCatalog([tmp_path]).scan() == []

    def test_resolves_canonical_and_bmad_alias_to_same_package(self, tmp_path: Path) -> None:
        self._write_package(tmp_path, "bmad-prd")
        resolver = SkillResolver(SkillCatalog([tmp_path]))
        resolver.catalog.scan()

        assert resolver.resolve("he-prd") is resolver.resolve("bmad-prd")
        assert resolver.resolve("he-prd").skill_id == "he-prd"

    def test_resolves_declared_custom_alias(self, tmp_path: Path) -> None:
        package = self._write_package(tmp_path, "legacy")
        package.joinpath("SKILL.md").write_text(
            "---\ncanonical_id: he-prd\nsource_id: legacy-prd\naliases: [old-prd]\n---\n", encoding="utf-8"
        )
        resolver = SkillResolver(SkillCatalog([tmp_path]))
        resolver.catalog.scan()

        assert resolver.resolve("legacy-prd").skill_id == "he-prd"
        assert resolver.resolve("old-prd").skill_id == "he-prd"

    def test_rejects_invalid_availability_flag(self, tmp_path: Path) -> None:
        package = self._write_package(tmp_path, "he-invalid")
        package.joinpath("SKILL.md").write_text("---\nname: he-invalid\navailable: maybe\n---\n", encoding="utf-8")
        entry = SkillCatalog([tmp_path]).scan()[0]
        assert not entry.available
        assert entry.error is not None and "available flag" in entry.error

    def test_canonical_request_has_priority_over_alias_match(self, tmp_path: Path) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        self._write_package(first, "he-prd")
        self._write_package(second, "bmad-prd")
        catalog = SkillCatalog([first, second])
        catalog.scan()

        with pytest.raises(SkillResolutionError, match=r"he-prd.*ambiguous"):
            SkillResolver(catalog).resolve("he-prd")

    def test_reports_conflicting_aliases_without_choosing(self, tmp_path: Path) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        self._write_package(first, "he-prd")
        self._write_package(second, "he-prd")
        catalog = SkillCatalog([first, second])
        catalog.scan()

        with pytest.raises(SkillResolutionError, match=r"he-prd.*first.*second"):
            SkillResolver(catalog).resolve("bmad-prd")

    def test_missing_entry_is_indexed_as_unavailable_with_diagnostic(self, tmp_path: Path) -> None:
        self._write_package(tmp_path, "he-missing", entry=False)

        entry = SkillCatalog([tmp_path]).scan()[0]

        assert not entry.available
        assert entry.error is not None and "missing" in entry.error
        with pytest.raises(SkillResolutionError, match=r"he-missing.*missing"):
            SkillResolver([entry]).resolve("he-missing")

    def test_invalid_metadata_is_indexed_as_unavailable(self, tmp_path: Path) -> None:
        package = self._write_package(tmp_path, "he-invalid")
        package.joinpath("SKILL.md").write_text("---\nname: not valid\n---\n", encoding="utf-8")

        entry = SkillCatalog([tmp_path]).scan()[0]

        assert not entry.available
        assert entry.error is not None and "invalid metadata" in entry.error


class TestSkillRunner:
    def test_runs_one_step_and_keeps_waiting_step(self, tmp_path: Path) -> None:
        make_package(tmp_path)
        (tmp_path / "step-01.md").write_text("first", encoding="utf-8")
        (tmp_path / "step-02.md").write_text("second", encoding="utf-8")
        runner = SkillRunner(SkillPackage(skill_id="he-build", root=tmp_path), ["step-01.md", "step-02.md"])
        seen: list[int] = []

        async def callback(step: SkillStep) -> SkillStepResult:
            seen.append(step.index)
            return SkillStepResult(status="waiting_user", reason="needs input")

        state = asyncio.run(runner.run(callback))
        assert state.status == "waiting_user"
        assert state.active_step == 0
        assert seen == [0]

    def test_completed_step_advances_only_on_next_run(self, tmp_path: Path) -> None:
        make_package(tmp_path)
        (tmp_path / "one.md").write_text("one", encoding="utf-8")
        (tmp_path / "two.md").write_text("two", encoding="utf-8")
        runner = SkillRunner(SkillPackage(skill_id="he-build", root=tmp_path), ["one.md", "two.md"])
        seen: list[int] = []

        async def callback(step: SkillStep) -> SkillStepResult:
            seen.append(step.index)
            return SkillStepResult(status="completed")

        asyncio.run(runner.run(callback))
        assert runner.state.active_step == 0
        asyncio.run(runner.run(callback))
        assert seen == [0, 1]
        assert runner.state.status == "completed"
        assert runner.done

    def test_invalid_active_step_is_rejected(self, tmp_path: Path) -> None:
        make_package(tmp_path)
        (tmp_path / "one.md").write_text("one", encoding="utf-8")
        with pytest.raises(ValueError, match="out of range"):
            SkillRunner(
                SkillPackage(skill_id="he-build", root=tmp_path),
                ["one.md"],
                SkillRunnerState(active_step=2),
            )

    def test_failed_step_is_explicit_and_does_not_advance(self, tmp_path: Path) -> None:
        make_package(tmp_path)
        (tmp_path / "one.md").write_text("one", encoding="utf-8")
        runner = SkillRunner(SkillPackage(skill_id="he-build", root=tmp_path), ["one.md"])

        async def callback(step: SkillStep) -> SkillStepResult:
            return SkillStepResult(status="failed", reason="bad input")

        state = asyncio.run(runner.run(callback))
        assert state.status == "failed"
        assert state.reason == "bad input"
        assert state.active_step == 0
        asyncio.run(runner.run(callback))
        assert state.reason == "bad input"

    def test_blocked_step_keeps_active_index_with_sync_callback(self, tmp_path: Path) -> None:
        make_package(tmp_path)
        (tmp_path / "one.md").write_text("one", encoding="utf-8")
        runner = SkillRunner(SkillPackage(skill_id="he-build", root=tmp_path), ["one.md"])

        def callback(step: SkillStep) -> SkillStepResult:
            assert step.instructions == "one"
            return SkillStepResult(status="blocked", reason="approval required")

        state = asyncio.run(runner.run(callback))
        assert state.status == "blocked"
        assert state.active_step == 0
