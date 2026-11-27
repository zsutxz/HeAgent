"""``scripts/cpolar_publish.py`` 的回填活性闸门（A78）。

脚本不是包（``scripts/`` 无 ``__init__.py``），按路径 importlib 加载，不做 sys.path 注入；
网络与 adb 全部用替身 —— 判据是「死地址会不会被写进 App」，不是「真的连了一次公网」。

真事故形状（2026-11-27 代码审查 A78）：四级回读里只有管理面是权威来源，其余三个来源可能是
上一次运行留下的死地址；付费档的预留地址又常常长期不变 ⇒ 没有闸门时 ``--apply`` 会把 App
指向一个连不上的端点，且现场看日志是「地址回读成功」。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cpolar_publish.py"
_SPEC = importlib.util.spec_from_file_location("cpolar_publish_under_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
publish_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(publish_mod)


class _Spy:
    """``apply_to_app`` 替身：记录被写入的 url，按需返回 / 抛错。"""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[str] = []
        self._error = error

    def __call__(self, url: str) -> bool:
        self.calls.append(url)
        if self._error is not None:
            raise self._error
        return True


# ── probe_reachable：只认「连上了」 ──


def test_probe_reachable_true_when_the_socket_connects(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[tuple[str, int], float]] = []

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    def _fake(address: tuple[str, int], timeout: float):
        seen.append((address, timeout))
        return _Conn()

    monkeypatch.setattr(publish_mod.socket, "create_connection", _fake)

    assert publish_mod.probe_reachable("1.tcp.vip.cpolar.cn:20046") is True
    assert seen == [(("1.tcp.vip.cpolar.cn", 20046), 3.0)]


@pytest.mark.parametrize("error", [OSError("refused"), TimeoutError("tcp connect timed out")])
def test_probe_reachable_false_on_any_connect_failure(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    def _boom(address: tuple[str, int], timeout: float):
        raise error

    monkeypatch.setattr(publish_mod.socket, "create_connection", _boom)

    assert publish_mod.probe_reachable("1.tcp.vip.cpolar.cn:20046") is False


def test_probe_reachable_false_on_a_malformed_address() -> None:
    """没有端口就 ``int("")`` 抛 ``ValueError``：形状坏 = 不可达，不许冒出异常。"""
    assert publish_mod.probe_reachable("1.tcp.vip.cpolar.cn") is False


# ── verified_address：只有证明活着 / 用户显式给的才放行 ──


def test_admin_source_and_explicit_address_skip_the_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """管理面是权威来源（隧道活着才列 public_url）；``--address`` 是用户显式承担风险。"""

    def _must_not_probe(address: str, timeout: float = 3.0) -> bool:
        raise AssertionError("这两个来源不该被探测")

    monkeypatch.setattr(publish_mod, "probe_reachable", _must_not_probe)

    assert publish_mod.verified_address("h:1", publish_mod._SOURCE_ADMIN) is True
    assert publish_mod.verified_address("h:1", "预留地址", explicit=True) is True


def test_fallback_source_is_rejected_when_the_probe_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publish_mod, "probe_reachable", lambda address, timeout=3.0: False)

    assert publish_mod.verified_address("1.2.3.4:20046", "cpolar-address.txt") is False


def test_fallback_source_passes_when_the_probe_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publish_mod, "probe_reachable", lambda address, timeout=3.0: True)

    assert publish_mod.verified_address("1.2.3.4:20046", "隧道日志") is True


# ── publish：死地址不得写进 App ──


def test_publish_refuses_to_write_a_dead_fallback_address(monkeypatch: pytest.MonkeyPatch) -> None:
    """核心判据：``--apply`` + 回退来源 + 探不通 ⇒ 退出码 1 且**一次都不写**。"""
    monkeypatch.setattr(publish_mod, "probe_reachable", lambda address, timeout=3.0: False)
    spy = _Spy()
    monkeypatch.setattr(publish_mod, "apply_to_app", spy)

    code = publish_mod.publish("1.2.3.4:20046", "预留地址", True, False)

    assert code == 1
    assert spy.calls == [], "死地址绝不能进 App 的 websocket_endpoint"


def test_publish_writes_an_admin_address_without_probing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _must_not_probe(address: str, timeout: float = 3.0) -> bool:
        raise AssertionError("管理面来源不该被探测")

    monkeypatch.setattr(publish_mod, "probe_reachable", _must_not_probe)
    spy = _Spy()
    monkeypatch.setattr(publish_mod, "apply_to_app", spy)

    code = publish_mod.publish("1.2.3.4:20046", publish_mod._SOURCE_ADMIN, True, False)

    assert (code, spy.calls) == (0, ["wss://1.2.3.4:20046"])


def test_publish_print_only_warns_and_exits_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """不带 ``--apply`` 时没有任何副作用：死地址只给 WARNING，不改变退出码。"""
    monkeypatch.setattr(publish_mod, "probe_reachable", lambda address, timeout=3.0: False)
    spy = _Spy()
    monkeypatch.setattr(publish_mod, "apply_to_app", spy)

    code = publish_mod.publish("1.2.3.4:20046", "隧道日志", False, False)

    assert code == 0
    assert spy.calls == []
    assert "[warn]" in capsys.readouterr().out


def test_publish_writes_an_explicit_address_even_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--address`` 显式给 = 用户承担风险（隧道未起来时也会用它做预演回填）。"""

    def _must_not_probe(address: str, timeout: float = 3.0) -> bool:
        raise AssertionError("显式地址不该被探测")

    monkeypatch.setattr(publish_mod, "probe_reachable", _must_not_probe)
    spy = _Spy()
    monkeypatch.setattr(publish_mod, "apply_to_app", spy)

    code = publish_mod.publish("1.2.3.4:20046", "--address 显式指定", True, False, explicit=True)

    assert (code, spy.calls) == (0, ["wss://1.2.3.4:20046"])


def test_publish_surfaces_an_apply_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """回填本身失败（adb 不通 / 设备离线）仍然回 1，与「拒绝回填」同一退出码语义。"""
    monkeypatch.setattr(publish_mod, "probe_reachable", lambda address, timeout=3.0: True)
    monkeypatch.setattr(publish_mod, "apply_to_app", _Spy(error=RuntimeError("adb 调用失败")))

    assert publish_mod.publish("1.2.3.4:20046", "cpolar-address.txt", True, False) == 1
