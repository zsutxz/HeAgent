"""`scripts/ws_tls_attest.py` 的契约（E79 / A76）：A76 的闭合工具本身得先可信。

承兑脚本要连真 listener，所以本文件**不碰生产入口**：用 `tests/fixtures/ws_tls/` 的自签材料在回环起
stub 跑全链，只验四件离线可判定的行为——自检全绿（`0`）、pin 不匹配判红（`1`）、材料缺失与目标未监听
走前提码（`2`）、`--help` 正常；再加一条静态断言钉住 token 纪律。
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ws_tls_attest.py"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
WS_TLS_CERT = FIXTURES / "ws_tls" / "cert.pem"
WS_TLS_KEY = FIXTURES / "ws_tls" / "key.pem"
OTHER_CERT = FIXTURES / "tls" / "cert.pem"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - 固定 argv（当前解释器 + 仓内脚本），不经 shell、无外部输入
        [sys.executable, str(SCRIPT), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def _closed_port() -> int:
    """取一个当前没人监听的端口（绑一下再放掉）：用来制造「目标未在跑」。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_self_check_passes_against_the_fixture_material() -> None:
    """四段全绿：自检必须能在无生产材料、无网络的机器上跑通，否则 A76 的闭合工具本身不可验。"""
    completed = _run("--self-check", "--cert", str(WS_TLS_CERT), "--key", str(WS_TLS_KEY))

    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert "[OK]   ① 绑定面" in completed.stdout
    assert "[OK]   ② TLS 握手" in completed.stdout
    assert "③ pin 对账" in completed.stdout
    assert "无 token → HTTP/1.1 403" in completed.stdout
    assert "带 token → HTTP/1.1 101" in completed.stdout


def test_a_different_local_certificate_is_reported_as_a_pin_mismatch() -> None:
    """对端证书与本地材料不是同一套 ⇒ 判据必须红（`1`），不能因为握手成功就算通过。"""
    completed = _run(
        "--self-check",
        "--cert",
        str(WS_TLS_CERT),
        "--serve-cert",
        str(OTHER_CERT),
        "--key",
        str(FIXTURES / "tls" / "key.pem"),
    )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 1, output
    assert "[FAIL] ③ pin 对账" in completed.stdout
    assert "pin 漂移" in completed.stdout


def test_missing_material_exits_with_the_precondition_code(tmp_path: Path) -> None:
    """材料不在 ⇒ `2`（前提缺失）+ 点名去哪生成，不当成判据失败。"""
    completed = _run("--self-check", "--cert", str(tmp_path / "nope.pem"), "--key", str(tmp_path / "nope.key"))

    output = completed.stdout + completed.stderr
    assert completed.returncode == 2, output
    assert "heagent tls init" in output


def test_unreachable_target_exits_with_the_precondition_code() -> None:
    """目标没在监听 ⇒ `2`，并提示先起服务；不是 `1`（那不是「判据失败」，是「还没到判据」）。"""
    port = _closed_port()
    completed = _run("--host", "127.0.0.1", "--port", str(port), "--timeout", "1")

    output = completed.stdout + completed.stderr
    assert completed.returncode == 2, output
    assert "未在监听" in output


def test_help_exits_zero() -> None:
    completed = _run("--help")

    assert completed.returncode == 0
    assert "--self-check" in completed.stdout
    assert "--expect-unauth" in completed.stdout


def test_the_token_is_never_interpolated_into_an_output_line() -> None:
    """凭证纪律：token 只进请求头，任何输出行都不许带值（只报长度）。"""
    source = SCRIPT.read_text(encoding="utf-8")

    offending = [
        line
        for line in source.splitlines()
        if "{token" in line and any(marker in line for marker in ("print(", ".note(", "logger."))
    ]
    assert offending == [], offending
    assert "Authorization: Bearer {token}" in source  # 唯一允许出现值的地方：请求头


def _module() -> object:
    """把 `scripts/` 放上 `sys.path` 后导入脚本本体（判纯函数用，不跑网络）。"""
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import ws_tls_attest  # noqa: PLC0415 - 需要先把 scripts/ 放上 sys.path

        return ws_tls_attest
    finally:
        sys.path.remove(str(SCRIPT.parent))


def test_ipv6_literal_addresses_are_split_without_the_brackets() -> None:
    """`[::1]:9201` 这类写法要脱方括号——否则探活拿到 `[::1]` 必失败。"""
    module = _module()

    assert module._split_host_port("[::1]:9201") == ("::1", 9201)  # type: ignore[attr-defined]
    assert module._split_host_port("192.168.2.226:9201") == ("192.168.2.226", 9201)  # type: ignore[attr-defined]
    # 脱括号只有一处实现（`network.exposure.unbracket_host`）：非 IPv6 字面量保留原样，
    # 自己 `strip("[]")` 会把 `[localhost]` 也剥掉，与配置面 / SAN 判定的口径分叉。
    assert module._split_host_port("[localhost]:9201") == ("[localhost]", 9201)  # type: ignore[attr-defined]


def test_bind_drift_is_a_judgement_failure_not_a_missing_precondition() -> None:
    """「期望拒绝却 OPEN」是暴露面漂移（判据失败 `1`），不能报成「服务未在监听」（前提缺失 `2`）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(4)
        port = int(listener.getsockname()[1])
        completed = _run(
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--refused",
            f"127.0.0.1:{port}",
            "--cert",
            str(WS_TLS_CERT),
            "--timeout",
            "1",
        )

    output = completed.stdout + completed.stderr
    assert completed.returncode == 1, output
    assert "暴露面漂移" in completed.stdout, output
    assert "未在监听" not in output, output


def test_unparseable_local_material_exits_with_the_precondition_code() -> None:
    """本地证书解不出（非 PEM / 截断）⇒ `2` + 提示重签，不是 traceback。"""
    completed = _run("--cert", str(FIXTURES / "tls" / "not-a-cert.pem"), "--timeout", "1")

    output = completed.stdout + completed.stderr
    assert completed.returncode == 2, output
    assert "解析不出" in output
    assert "Traceback" not in output


def test_a_bad_refused_argument_exits_with_the_precondition_code() -> None:
    """`--refused` 写法不合法 ⇒ `2` + 「参数错误」，不是未捕获的 ValueError traceback。"""
    completed = _run("--cert", str(WS_TLS_CERT), "--refused", "no-port", "--timeout", "1")

    output = completed.stdout + completed.stderr
    assert completed.returncode == 2, output
    assert "参数错误" in output
    assert "Traceback" not in output


def test_the_status_segment_compares_the_pin_passed_in() -> None:
    """第 ⑤ 段比的是第 ③ 段显式交出的指纹（不是从渲染文案反解析），缺指纹时判红而不是「空串命中」。"""
    module = _module()
    sha = "247a8b269307d2f682edad8c4f78d7896f99cb47e95a1279667d2de7750fd301"
    payload = json.dumps(
        {"listeners": [{"kind": "http", "tls": {"enabled": False}}, {"kind": "ws", "tls": {"spki_sha256": sha}}]}
    ).encode("utf-8")

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 的约定名
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:  # 探针不该往 stderr 刷访问日志
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/api/status"
    try:
        matching = module._segment_status(url, sha, 2)  # type: ignore[attr-defined]
        drifting = module._segment_status(url, "0" * 64, 2)  # type: ignore[attr-defined]
        missing = module._segment_status(url, "", 2)  # type: ignore[attr-defined]
    finally:
        server.server_close()

    assert matching.ok, matching.details
    assert not drifting.ok, drifting.details
    assert "不含对端叶证书" in drifting.details[-1]
    assert not missing.ok
    assert "无从对账" in missing.details[-1]
