"""Tests for engine.roles — RoleSpec model + role registry."""

from __future__ import annotations

import pytest

from heagent.engine.roles import RoleSpec, get_role, list_roles, register_role


class TestRoleSpec:
    def test_defaults(self) -> None:
        spec = RoleSpec(name="x", system="be x")
        assert spec.allowed_tools == []
        assert spec.blocked_tools == []
        assert spec.max_iterations == 20
        assert spec.metadata == {}

    def test_roundtrip(self) -> None:
        spec = RoleSpec(
            name="coder",
            system="write code",
            allowed_tools=["file_write"],
            max_iterations=30,
        )
        rebuilt = RoleSpec.model_validate(spec.model_dump())
        assert rebuilt == spec


class TestRegistry:
    def test_builtin_roles_registered(self) -> None:
        assert {"planner", "coder", "tester"} <= set(list_roles())

    def test_get_coder_role(self) -> None:
        coder = get_role("coder")
        assert coder.name == "coder"
        assert "file_write" in coder.allowed_tools

    def test_get_planner_role_read_only(self) -> None:
        planner = get_role("planner")
        assert "file_write" not in planner.allowed_tools
        assert "file_read" in planner.allowed_tools

    def test_get_unknown_role_raises(self) -> None:
        with pytest.raises(KeyError):
            get_role("nonexistent_role_xyz")

    def test_register_custom_role(self) -> None:
        spec = RoleSpec(
            name="custom_role_test",
            system="custom",
            allowed_tools=["file_read"],
        )
        register_role(spec)
        assert "custom_role_test" in list_roles()
        assert get_role("custom_role_test") is spec
