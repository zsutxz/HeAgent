"""Deterministic characterization of the SkillPackage resolve/read TOCTOU window."""

from __future__ import annotations

import errno
import os
import stat
from types import SimpleNamespace
from pathlib import Path

import pytest

from heagent.skills.skill_packages import SkillPackage, SkillPackageResourceError
from heagent.tools.path_safety import _WALK_SUPPORTED, _walkable_parts, read_bytes_under_root

# 逐组件通道是否生效：**独立**重算一遍平台能力（导入期冻结），**刻意不复用**被测模块的常量——
# 用它做 skipif 会让「常量被改错」表现为**跳过**而不是失败（自证式跳过，实测变异体不红）。
# 二者是否一致由下面的 `test_walk_gate_matches_platform_capability` 正面钉住。
_WALK_ACTIVE = (
    getattr(os, "O_DIRECTORY", 0) != 0
    and getattr(os, "O_NOFOLLOW", None) is not None
    and os.open in getattr(os, "supports_dir_fd", frozenset())
)
_needs_walk = pytest.mark.skipif(not _WALK_ACTIVE, reason="需要 POSIX dir_fd + O_NOFOLLOW")
_needs_fallback = pytest.mark.skipif(_WALK_ACTIVE, reason="仅在不支持 dir_fd 的平台有意义")


def _record_opens(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """记录每次 ``os.open`` 的 (path, flags, dir_fd)，并原样转发（含 kwargs）。"""
    calls: list[dict[str, object]] = []
    original = os.open

    def hooked(path: str | os.PathLike[str], flags: int, *args: object, **kwargs: object) -> int:
        calls.append({"path": path, "flags": flags, "dir_fd": kwargs.get("dir_fd")})
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", hooked)
    return calls


def _make_package(root: Path) -> SkillPackage:
    (root / "SKILL.md").write_text("---\nname: he-build\n---\n", encoding="utf-8")
    return SkillPackage(skill_id="he-build", root=root)


def _replace_after_is_file(monkeypatch: pytest.MonkeyPatch, victim: Path, content: str) -> dict[str, bool]:
    """Characterize the legacy check-then-read window without invoking the hardened reader."""
    original = Path.is_file
    state = {"swapped": False}

    def hooked(path: Path) -> bool:
        result = original(path)
        if not state["swapped"] and path == victim and result:
            victim.write_text(content, encoding="utf-8")
            state["swapped"] = True
        return result

    monkeypatch.setattr(Path, "is_file", hooked)
    return state


def test_legacy_resolve_then_read_window_remains_characterized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    resource = tmp_path / "step.md"
    resource.write_text("trusted", encoding="utf-8")
    resolved = package._resolve("step.md")
    state = _replace_after_is_file(monkeypatch, resolved, "replaced")

    assert resolved.is_file()
    assert resolved.read_text(encoding="utf-8") == "replaced"
    assert state["swapped"] is True


def test_resource_readers_use_one_opened_descriptor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """每个读取器：**读到内容的**描述符恰好一个，其余（逐组件通道的中间目录）开完即关。

    2026-09-27 逐组件硬化后，这条判据从「总共只 open 一次」改成「叶描述符唯一 + 不泄漏 fd」——
    原因是 POSIX 通道**必须**为每个中间组件各开一次（那正是它收窄窗口的方式），断言总数会把
    正确的实现判红；真正要钉的是「内容只从一个描述符读出」与「中间 fd 不泄漏」。
    """
    package = _make_package(tmp_path)
    readers = {
        "read_entry": ("SKILL.md", lambda: package.read_entry().text),
        "read_resource": ("step.md", lambda: package.read_resource("step.md")),
        "read_step": ("step.md", lambda: package.read_step("step.md")),
        "read_reference": ("references/ref.md", lambda: package.read_reference("ref.md")),
        "read_template": ("templates/template.md", lambda: package.read_template("template.md")),
        "read_asset": ("assets/asset.md", lambda: package.read_asset("asset.md")),
        "read_script": ("scripts/script.md", lambda: package.read_script("script.md")),
    }
    opened: dict[int, tuple[Path, int]] = {}
    fdopen_fds: list[int] = []
    closed_fds: list[int] = []
    original_open = os.open
    original_fdopen = os.fdopen
    original_close = os.close

    def record_open(path: str | os.PathLike[str], flags: int, *args: object, **kwargs: object) -> int:
        descriptor = original_open(path, flags, *args, **kwargs)
        opened[descriptor] = (Path(path), flags)
        return descriptor

    class TrackingStream:
        def __init__(self, stream: object) -> None:
            self.stream = stream

        def __enter__(self) -> TrackingStream:
            self.stream.__enter__()  # type: ignore[attr-defined]
            return self

        def __exit__(self, *args: object) -> object:
            return self.stream.__exit__(*args)  # type: ignore[attr-defined]

        def read(self, *args: object) -> bytes:
            return self.stream.read(*args)  # type: ignore[attr-defined,no-any-return]

    def record_fdopen(descriptor: int, *args: object, **kwargs: object) -> TrackingStream:
        fdopen_fds.append(descriptor)
        return TrackingStream(original_fdopen(descriptor, *args, **kwargs))

    def record_close(descriptor: int) -> None:
        closed_fds.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(os, "open", record_open)
    monkeypatch.setattr(os, "fdopen", record_fdopen)
    monkeypatch.setattr(os, "close", record_close)
    for resource_name, reader in readers.values():
        resource = tmp_path / resource_name
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_text("trusted", encoding="utf-8")
        assert reader() == "trusted"
        # 内容只从一个描述符读出（fdopen 的唯一一次），且它就是**非目录**的那次 open。
        assert len(fdopen_fds) == 1
        leaf = fdopen_fds[0]
        _, leaf_flags = opened[leaf]
        assert not leaf_flags & getattr(os, "O_DIRECTORY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            assert leaf_flags & os.O_NOFOLLOW
        # 其余描述符（逐组件通道的 root 与中间目录）必须开完即关，不泄漏 fd。
        assert set(opened) - {leaf} <= set(closed_fds)
        opened.clear()
        fdopen_fds.clear()
        closed_fds.clear()


@_needs_walk
def test_posix_walk_opens_every_component_with_nofollow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """逐组件通道的形状：root（O_DIRECTORY，无 dir_fd）→ 中间组件（dir_fd +
    O_DIRECTORY|NOFOLLOW）→ 叶（dir_fd + NOFOLLOW）。"""
    package = _make_package(tmp_path)
    resource = tmp_path / "references" / "ref.md"
    resource.parent.mkdir(parents=True, exist_ok=True)
    resource.write_text("trusted", encoding="utf-8")
    calls = _record_opens(monkeypatch)

    assert package.read_reference("ref.md") == "trusted"

    assert len(calls) == 3, [call["path"] for call in calls]
    root_call, middle_call, leaf_call = calls
    assert root_call["dir_fd"] is None and root_call["flags"] & os.O_DIRECTORY, "root 用绝对路径打开"
    assert Path(str(root_call["path"])) == tmp_path.resolve()
    assert middle_call["path"] == "references" and middle_call["dir_fd"] is not None
    assert middle_call["flags"] & os.O_DIRECTORY and middle_call["flags"] & os.O_NOFOLLOW
    assert leaf_call["path"] == "ref.md" and leaf_call["dir_fd"] is not None
    assert leaf_call["flags"] & os.O_NOFOLLOW and not leaf_call["flags"] & os.O_DIRECTORY


@_needs_walk
def test_replaced_intermediate_directory_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """围栏之后把**中间目录**换成指向 root 之外的符号链接 → 逐组件 open 在那一层 ELOOP。

    这是本条硬化真正要收的竞态：旧通道（整路径 open）会跟着链接走出去，把 root 之外的内容读进来；
    逐组件通道在 `nested` 组件上直接拒绝，且**从没**打开过外面的文件。
    """
    outside = tmp_path.parent / "outside-nested"
    outside.mkdir(exist_ok=True)
    (outside / "step.md").write_text("outside", encoding="utf-8")
    package_root = tmp_path / "pkg"
    nested = package_root / "nested"
    nested.mkdir(parents=True, exist_ok=True)
    (nested / "step.md").write_text("trusted", encoding="utf-8")
    package = SkillPackage(skill_id="he-build", root=package_root)

    original = os.open
    state = {"swapped": False}

    def hooked(path: str | os.PathLike[str], flags: int, *args: object, **kwargs: object) -> int:
        if not state["swapped"] and Path(path).name == "nested" and flags & os.O_DIRECTORY:
            nested.rename(package_root / "nested-real")
            nested.symlink_to(outside, target_is_directory=True)
            state["swapped"] = True
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", hooked)

    with pytest.raises(SkillPackageResourceError, match="symlink"):
        package.read_resource("nested/step.md")
    assert state["swapped"] is True


@_needs_fallback
def test_without_dir_fd_the_resolved_path_is_opened_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """回退通道的形状（Windows）：只对 resolve 后的**整条路径** open 一次——窗口因此更宽。"""
    package = _make_package(tmp_path)
    resource = tmp_path / "references" / "ref.md"
    resource.parent.mkdir(parents=True, exist_ok=True)
    resource.write_text("trusted", encoding="utf-8")
    calls = _record_opens(monkeypatch)

    assert package.read_reference("ref.md") == "trusted"

    assert len(calls) == 1, [call["path"] for call in calls]
    assert Path(str(calls[0]["path"])) == resource.resolve()
    assert calls[0]["dir_fd"] is None


@_needs_walk
def test_walk_gate_matches_platform_capability() -> None:
    """平台支持 dir_fd 时，模块的能力常量必须为真——**静默降级**是这条硬化最容易踩的坑。

    实现里该常量在导入期算一次（`os.open in os.supports_dir_fd` 是函数对象身份比较，任何包一层
    `os.open` 的代码都会让它变假）；这里从**外部**再确认一次，避免哪天改成每次调用重算、或被
    「顺手包一层」的观测代码悄悄关掉整条通道。
    """
    assert _WALK_SUPPORTED is True


def test_walkable_parts_refuses_dotdot_and_foreign_roots(tmp_path: Path) -> None:
    """`_walkable_parts` 的 fail-closed 分支：`..` 与「不在 root 之下」都回退整路径通道。"""
    root = tmp_path / "root"
    root.mkdir()
    nested = root / "a" / "b.md"
    nested.parent.mkdir()
    nested.write_text("x", encoding="utf-8")

    assert _walkable_parts(nested, root) == ("a", "b.md")
    assert _walkable_parts(Path(str(root) + "/a/../a/b.md"), root) is None
    assert _walkable_parts(tmp_path / "other.md", root) is None
    assert _walkable_parts(root, root) is None


def test_final_symlink_replacement_is_rejected_when_supported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    target = tmp_path / "target.md"
    link = tmp_path / "step.md"
    outside = tmp_path.parent / "outside-target.md"
    target.write_text("trusted", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    probe = tmp_path / "probe-target"
    probe_link = tmp_path / "probe-link"
    probe.write_text("probe", encoding="utf-8")
    try:
        probe_link.symlink_to(probe)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    finally:
        probe_link.unlink(missing_ok=True)
        probe.unlink(missing_ok=True)
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW unavailable")
    original = os.open
    state = {"swapped": False}

    def hooked(path: str | os.PathLike[str], flags: int, *args: object, **kwargs: object) -> int:
        # 按**组件名**匹配：逐组件通道传的是「组件名 + dir_fd」，不再是 resolve 后的绝对路径。
        if not state["swapped"] and Path(path).name == target.name and not flags & getattr(os, "O_DIRECTORY", 0):
            target.unlink()
            target.symlink_to(outside)
            state["swapped"] = True
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", hooked)

    with pytest.raises(SkillPackageResourceError, match="symlink"):
        package.read_resource("step.md")
    assert state["swapped"] is True


def test_final_symlink_replacement_uses_compatibility_fallback_without_nofollow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = _make_package(tmp_path)
    target = tmp_path / "target.md"
    link = tmp_path / "step.md"
    outside = tmp_path.parent / "outside-target.md"
    target.write_text("trusted", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    original = os.open
    state = {"swapped": False}

    def hooked(path: str | os.PathLike[str], flags: int, *args: object, **kwargs: object) -> int:
        if not state["swapped"] and Path(path) == target:
            target.unlink()
            target.symlink_to(outside)
            state["swapped"] = True
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", hooked)
    assert package.read_resource("step.md") == "outside"
    assert state["swapped"] is True


def test_nofollow_einval_uses_compatibility_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    resource = tmp_path / "step.md"
    resource.write_text("trusted", encoding="utf-8")
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW unavailable")
    nofollow = os.O_NOFOLLOW
    original = os.open
    calls: list[int] = []

    def hooked(path: str | os.PathLike[str], flags: int, *args: object, **kwargs: object) -> int:
        # 只统计**叶**组件的 open：逐组件通道另会为 root 与中间目录各开一次（带 O_DIRECTORY）。
        if not flags & getattr(os, "O_DIRECTORY", 0):
            calls.append(flags)
            if len(calls) == 1:
                raise OSError(errno.EINVAL, "nofollow unsupported")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", hooked)
    assert package.read_resource("step.md") == "trusted"
    assert len(calls) == 2
    assert calls[0] & nofollow
    assert not calls[1] & nofollow


def test_non_regular_resource_is_rejected(tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    (tmp_path / "directory").mkdir()
    with pytest.raises(SkillPackageResourceError, match="cannot read resource"):
        package.read_resource("directory")


def test_fifo_descriptor_is_rejected_without_reading(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    resource = tmp_path / "fifo"
    resource.write_text("unused", encoding="utf-8")
    monkeypatch.setattr(os, "fstat", lambda _fd: SimpleNamespace(st_mode=stat.S_IFIFO))

    with pytest.raises(SkillPackageResourceError, match="cannot read resource"):
        package.read_resource("fifo")
