"""Story 49-6：内置网页的静态契约（元素、纯文本渲染、无第三方资源、状态词表）。

这些断言刻意盯着「页面**必须**有的东西」与「页面**绝不能**有的东西」：前者保证 UX-DR1/DR3/DR6
的关键反馈不会在后续改动里被删掉，后者保证严格 CSP 与「不渲染不可信 HTML」这两条不是口号。

浏览器里的真实交互（点击、重连观感）由 `tests/test_http_agent_api.py` 的 HTTP 端到端与人工验收覆盖。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from heagent.network.http_server import read_web_asset

_NODE = shutil.which("node")
_PROBE = Path(__file__).parent / "js" / "app_probe.js"

_HTML = read_web_asset("index.html").decode("utf-8")
_JS = read_web_asset("app.js").decode("utf-8")
_CSS = read_web_asset("styles.css").decode("utf-8")


class TestPageStructure:
    @pytest.mark.parametrize(
        "element_id",
        [
            "service-status",  # 服务可用性（UX-DR6）
            "chat-log",  # 消息列表（UX-DR1）
            "empty-state",  # 空状态（UX-DR1）
            "prompt-form",  # 输入与提交（UX-DR1）
            "prompt-input",
            "send-button",
            "stop-button",  # 取消（UX-DR3）
            "run-status",  # 运行状态（UX-DR3）
        ],
    )
    def test_required_elements_are_present(self, element_id: str) -> None:
        assert f'id="{element_id}"' in _HTML

    def test_prompt_input_is_multiline_and_bounded(self) -> None:
        assert "textarea" in _HTML
        assert re.search(r'id="prompt-input"[\s\S]*?rows="\d+"', _HTML), "输入框应当是多行输入"
        assert "maxlength=" in _HTML, "输入框必须有长度上限（与服务端协议上限一致）"

    def test_keyboard_contract_is_documented_and_ime_safe(self) -> None:
        """Enter 发送 / Shift+Enter 换行必须写进 placeholder，且实现里有输入法组合态防护。

        没有 ``isComposing`` 防护时，中文/日文选词时敲回车会把**半个词**当提示词发出去。
        """
        assert "Enter 发送" in _HTML
        assert "Shift+Enter 换行" in _HTML
        assert "isComposing" in _JS
        assert "event.shiftKey" in _JS

    def test_page_is_self_contained(self) -> None:
        """只引用同源绝对路径的样式与脚本，且不写死端口/域名。"""
        refs = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', _HTML)

        assert refs == ["/styles.css", "/app.js"]
        assert "http://" not in _HTML and "https://" not in _HTML


class TestCspCompatibility:
    def test_no_inline_script_or_style(self) -> None:
        """严格 CSP（无 'unsafe-inline'）要求 HTML 里没有内联脚本/样式。"""
        assert "<style" not in _HTML.lower()
        assert not re.search(r"<script(?![^>]*\bsrc=)", _HTML, re.IGNORECASE), "不允许内联 <script>"
        assert not re.search(r"\sstyle\s*=", _HTML), "不允许 style= 属性"

    def test_stylesheet_has_no_external_references(self) -> None:
        assert "@import" not in _CSS
        assert "url(http" not in _CSS

    def test_script_has_no_remote_or_dynamic_code_execution(self) -> None:
        assert "eval(" not in _JS
        assert "new Function" not in _JS
        assert "document.write" not in _JS

    def test_script_does_not_import_anything(self) -> None:
        """无模块导入、无第三方脚本注入点（严格 CSP 下也只能加载同源 /app.js）。"""
        assert not re.search(r"^\s*import\s", _JS, re.MULTILINE)
        assert 'appendChild(document.createElement("script"))' not in _JS


class TestPlainTextRendering:
    def test_untrusted_content_goes_through_text_nodes(self) -> None:
        assert "createTextNode" in _JS
        assert "textContent" in _JS

    def test_no_html_injection_path(self) -> None:
        assert ".innerHTML" not in _JS
        assert ".outerHTML" not in _JS
        assert "insertAdjacentHTML" not in _JS


class TestRunFlowContract:
    """页面必须真的调用这些端点（否则「网页能跑一次 Agent」只是文档里的承诺）。"""

    def test_submits_runs_and_subscribes_to_events(self) -> None:
        assert '"/api/runs"' in _JS
        assert "EventSource" in _JS
        assert "/api/runs/${" in _JS

    def test_cancels_via_delete(self) -> None:
        assert 'method: "DELETE"' in _JS

    def test_restores_session_on_load(self) -> None:
        assert '"/api/session"' in _JS
        assert "restoreSession()" in _JS

    @pytest.mark.parametrize("state", ["starting", "running", "cancelling", "reconnecting", "done", "failed"])
    def test_run_state_vocabulary_is_complete(self, state: str) -> None:
        """运行状态词表覆盖 UX-DR3：连接中 / 重连中 / 取消中 / 完成 / 失败。"""
        assert f"{state}:" in _JS

    def test_service_state_vocabulary_is_complete(self) -> None:
        assert "offline:" in _JS  # 服务关闭/不可达（UX-DR6）

    def test_duplicate_submissions_are_blocked_client_side(self) -> None:
        """忙状态下的提交必须被挡下**且如实说明**，不能静默吞掉这次点击。"""
        assert "BUSY_STATES" in _JS
        assert "已有运行进行中" in _JS

    def test_health_polling_reports_service_loss(self) -> None:
        assert '"/api/health"' in _JS
        assert "HEALTH_POLL_MS" in _JS


def _run_probe(case: str, tmp_path: Path) -> dict[str, Any]:
    """在 node 里跑一次前端行为探针（真实脚本 + 最小 DOM / EventSource / fetch 替身）。

    探针脚本输出一行 ``PROBE_RESULT {json}``；断言落在可观察结果上（DOM 行、状态栏、是否发请求），
    而不是「源码里有没有某个字符串」。
    """
    asset = tmp_path / "app.js"
    asset.write_bytes(read_web_asset("app.js"))
    # 固定 argv（node + 仓库内的探针脚本 + 临时文件路径），不经 shell、不含外部输入。
    completed = subprocess.run(  # noqa: S603
        [_NODE, str(_PROBE), str(asset), case],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    marker = "PROBE_RESULT "
    line = next((line for line in completed.stdout.splitlines() if line.startswith(marker)), None)
    assert line is not None, completed.stdout
    return json.loads(line[len(marker) :])


@pytest.mark.skipif(_NODE is None, reason="需要 node 才能执行前端行为回归（CI 镜像自带 node）")
class TestWebUiBehaviour:
    """前端可执行回归：状态文案、同名工具配对、刷新接手在途运行、忙时提交不静默。

    这四条以前都只靠「源码字符串匹配」间接保证，实测在缺陷存在时字符串断言照样全绿。
    """

    def test_same_name_tool_results_are_paired_in_order(self, tmp_path: Path) -> None:
        result = _run_probe("A", tmp_path)

        assert result["pairing"] == ["✔ shell：first result", "✔ shell：second result"]

    def test_resync_after_completion_shows_the_server_side_fact(self, tmp_path: Path) -> None:
        result = _run_probe("B", tmp_path)

        assert result["state"] == "done"
        assert result["text"] == "已完成"

    def test_in_flight_run_is_adopted_on_load(self, tmp_path: Path) -> None:
        result = _run_probe("C", tmp_path)

        assert result["state"] == "running"
        assert result["sendDisabled"] is True
        assert result["stopDisabled"] is False
        assert result["subscribed"] == "/api/runs/run-9/events"

    def test_busy_submission_reports_instead_of_silently_doing_nothing(self, tmp_path: Path) -> None:
        result = _run_probe("D", tmp_path)

        assert result["posted"] is False
        assert result["newEntries"] >= 1
        assert "已有运行进行中" in result["lastLine"]

    def test_enter_sends_shift_enter_newlines_and_ime_does_not_send(self, tmp_path: Path) -> None:
        """真实键盘语义：Enter 发送、Shift+Enter 保留换行、组合输入中的回车不发送。"""
        result = _run_probe("E", tmp_path)

        assert result["enterPosted"] is True, "Enter 应当发送"
        assert result["enterPrevented"] is True, "Enter 必须被接管（否则会同时插入一个换行）"
        assert result["enterCleared"] is True, "发送后输入框应当清空"
        assert result["shiftPosted"] is False, "Shift+Enter 不得发送"
        assert result["shiftPrevented"] is False, "Shift+Enter 必须保留浏览器默认的换行行为"
        assert result["shiftValue"] == "想在这里换行", "Shift+Enter 后输入内容不得被清空"
        assert result["composingPosted"] is False, "输入法组合中的回车不得发送"
        assert result["composingPrevented"] is False
