"""``scripts/setup_ws_external.py`` 的纯函数边界与**落盘 EOL 保真**。

脚本不是包（``scripts/`` 无 ``__init__.py``），按路径用 importlib 加载，不做 sys.path 注入。
核心判据是「写回后字节级 EOL 不变」：``Path.read_text`` / ``Path.write_text`` 的默认 newline
模式会折 CRLF、并在 Windows 上把行尾翻成 ``os.linesep`` —— 用它落盘即破坏 EOL 口径。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup_ws_external.py"
_SPEC = importlib.util.spec_from_file_location("setup_ws_external_under_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
setup_ws = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(setup_ws)


# ---------------------------------------------------------------- 端到端：EOL 保真


def _run(
    tmp_path: Path,
    *,
    env_text: str,
    setting_text: str | None = None,
    token: str = "test-token-123",
    host: str = "192.168.1.23",
) -> tuple[Path, Path]:
    """在 tmp_path 造一组文件并跑 ``main(--apply)``，返回 ``(.env, setting.md)`` 路径。"""
    env = tmp_path / ".env"
    env.write_bytes(env_text.encode("utf-8"))
    setting = tmp_path / "setting.md"
    if setting_text is not None:
        setting.write_bytes(setting_text.encode("utf-8"))
    rc = setup_ws.main(
        [
            "--host",
            host,
            "--token",
            token,
            "--env-file",
            str(env),
            "--setting-md",
            str(setting),
            "--backup-dir",
            str(tmp_path / "backups"),
            "--apply",
        ]
    )
    assert rc == 0
    return env, setting


def test_apply_keeps_crlf_env(tmp_path: Path) -> None:
    env, setting = _run(tmp_path, env_text="A=1\r\nB=2\r\n")
    raw = env.read_bytes()
    assert b"\r\r\n" not in raw, "写回时把 CRLF 翻成了 CRCRLF"
    assert raw.count(b"\r\n") == 3
    assert raw.replace(b"\r\n", b"").count(b"\n") == 0, "混入了裸 LF"
    assert raw.endswith(b"WS_EXTERNAL_HOST=192.168.1.23\r\n")
    assert b"ws_auth_token: test-token-123" in setting.read_bytes()


def test_apply_keeps_lf_and_absent_trailing_newline(tmp_path: Path) -> None:
    env, _ = _run(tmp_path, env_text="A=1\nB=2")
    raw = env.read_bytes()
    assert b"\r" not in raw, "写回时把 LF 翻成了 CRLF"
    assert raw.endswith(b"WS_EXTERNAL_HOST=192.168.1.23"), "末行无换行的状态被改写"


def test_apply_is_idempotent(tmp_path: Path) -> None:
    env, setting = _run(tmp_path, env_text="A=1\n")
    first = (env.read_bytes(), setting.read_bytes())
    _run(tmp_path, env_text=env.read_bytes().decode("utf-8"))
    assert (env.read_bytes(), setting.read_bytes()) == first


def test_apply_keeps_existing_setting_md_crlf(tmp_path: Path) -> None:
    _, setting = _run(tmp_path, env_text="A=1\n", setting_text="---\r\nmodel: x\r\n---\r\n")
    raw = setting.read_bytes()
    assert b"\r\r\n" not in raw
    assert b"ws_auth_token: test-token-123\r\n" in raw


# ---------------------------------------------------------------- 纯函数：dotenv 改写


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A=1\nB=2", "A=1\nB=2\nWS_EXTERNAL_HOST=new"),
        ("A=1\nWS_EXTERNAL_HOST=old\nB=2\n", "A=1\nWS_EXTERNAL_HOST=new\nB=2\n"),
        ("# WS_EXTERNAL_HOST=example\nA=1\n", "# WS_EXTERNAL_HOST=example\nA=1\nWS_EXTERNAL_HOST=new\n"),
        ("A=1\r\nB=2\r\n", "A=1\r\nB=2\r\nWS_EXTERNAL_HOST=new\r\n"),
        ("ws_external_host=old\n", "WS_EXTERNAL_HOST=new\n"),
    ],
)
def test_upsert_env_value(raw: str, expected: str) -> None:
    assert setup_ws.upsert_env_value(raw, "WS_EXTERNAL_HOST", "new") == expected


# ---------------------------------------------------------------- 纯函数：frontmatter


def test_frontmatter_inserts_before_closing_delimiter() -> None:
    assert (
        setup_ws.upsert_frontmatter_value("---\nmodel: x\n---\n正文\n", "ws_auth_token", "tk")
        == "---\nmodel: x\nws_auth_token: tk\n---\n正文\n"
    )


def test_frontmatter_replaces_existing_key() -> None:
    assert (
        setup_ws.upsert_frontmatter_value("---\nws_auth_token: old\n---\n", "ws_auth_token", "new")
        == "---\nws_auth_token: new\n---\n"
    )


def test_frontmatter_keeps_crlf() -> None:
    assert (
        setup_ws.upsert_frontmatter_value("---\r\nmodel: x\r\n---\r\n", "ws_auth_token", "tk")
        == "---\r\nmodel: x\r\nws_auth_token: tk\r\n---\r\n"
    )


@pytest.mark.parametrize("raw", ["model: x\n", "---\nmodel: x\n"])
def test_frontmatter_refuses_to_guess(raw: str) -> None:
    with pytest.raises(setup_ws.SetupError):
        setup_ws.upsert_frontmatter_value(raw, "ws_auth_token", "tk")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("---\nws_auth_token: 'abc'\n---\n", "abc"),
        ("---\nmodel: x\n---\n", None),
    ],
)
def test_read_frontmatter_value(raw: str, expected: str | None) -> None:
    assert setup_ws.read_frontmatter_value(raw, "ws_auth_token") == expected


# ---------------------------------------------------------------- 绑定地址校验


def test_validate_host_accepts_lan_ip() -> None:
    assert setup_ws.validate_host(" 192.168.1.23 ") == "192.168.1.23"


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0", "myhost.local", ""])
def test_validate_host_rejects(host: str) -> None:
    with pytest.raises(setup_ws.SetupError):
        setup_ws.validate_host(host)
