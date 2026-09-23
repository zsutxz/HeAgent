"""Story 49-6：内置网页的静态契约（元素、纯文本渲染、无第三方资源、状态词表）。

这些断言刻意盯着「页面**必须**有的东西」与「页面**绝不能**有的东西」：前者保证 UX-DR1/DR3/DR6
的关键反馈不会在后续改动里被删掉，后者保证严格 CSP 与「不渲染不可信 HTML」这两条不是口号。

浏览器里的真实交互（点击、重连观感）由 `tests/test_http_agent_api.py` 的 HTTP 端到端与人工验收覆盖。
"""

from __future__ import annotations

import re

import pytest

from heagent.network.http_server import read_web_asset

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
        assert "BUSY_STATES" in _JS
        assert "if (activeRunId) return;" in _JS

    def test_health_polling_reports_service_loss(self) -> None:
        assert '"/api/health"' in _JS
        assert "HEALTH_POLL_MS" in _JS
