"""同源 API 探索器的静态契约（Epic 70，Story 70.3）。

本机没有 node（`tests/fixtures/js/app_probe.js` 那类探针会 skip），因此这里用**源码级**契约钉死
可验证的部分。每条断言都对着一条真实不变量，而不是「源码里有没有某个词」：

- 面板真的挂在页面上：脚本在白名单内、`index.html` 有全部元素与默认收起、脚本在面板桥之后加载；
- 不渲染 HTML、不引第三方资源、不绕开面板桥自己发 fetch；
- **写方法在发请求之前**过一次 `window.confirm`（顺序断言 + 取消分支必须 return）；
- 预置端点与后端路由**双向一致**：从 ``network/http_server/app.py`` 的模块级 ``_XXX_PATH`` 常量与
  ``routing.Route(...)`` 注册行还原 ``(method, path)`` 集合，与 ``api-console.js`` 的 PRESETS 逐对比对。
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

from heagent.network.http_server import _WEB_ASSETS, read_web_asset

_JS = read_web_asset("api-console.js").decode("utf-8")
_HTML = read_web_asset("index.html").decode("utf-8")

_REMOTE_PATTERNS = ("http://", "https://", "//cdn", "cdn.", "unpkg", "jsdelivr", "googleapis")

# 面板与脚本必须互相认得的元素 id（`index.html` 提供，`api-console.js` 全部绑定）。
_REQUIRED_IDS = (
    "api-button",
    "api-console",
    "api-form",
    "api-method",
    "api-path",
    "api-body",
    "api-send",
    "api-presets",
    "api-status",
    "api-output",
    "api-close",
)

# 会话路径的**兜底**路由（多出来的段一律回 invalid_session_id），不是面向用户的端点 ⇒ 不做预置按钮。
_FALLBACK_ROUTES = frozenset({"/api/projects/{project_id}/sessions/{session_id}/{extra:path}"})

_APP_MODULE = importlib.import_module("heagent.network.http_server.app")
_APP_SOURCE = Path(_APP_MODULE.__file__).read_text(encoding="utf-8")

# `routing.Route(<常量或字面量>, endpoint=…, methods=[...])`：首参允许跨行（兜底路由那条就是多行）。
_ROUTE_RULE = re.compile(r"routing\.Route\(\s*([^,\n]+?),\s*[^)]*?methods=\[([^\]]*)\]", re.S)
_PRESET_RULE = re.compile(r'\{\s*method:\s*"([A-Z]+)",\s*path:\s*"([^"]+)"\s*\}')
_API_LITERAL_RULE = re.compile(r'"(/api[^"]*)"')


# ── 源码工具：掩码 + 括号配对（本机无 node，JS 语法完整性只能这样自查） ──


def _mask_literals(source: str) -> str:
    """把注释与字符串字面量替换成同长空白（换行保留）：长度不变，索引仍可回查原文。"""
    out = list(source)
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        following = source[index + 1] if index + 1 < length else ""
        if char == "/" and following == "/":
            while index < length and source[index] != "\n":
                out[index] = " "
                index += 1
            continue
        if char == "/" and following == "*":
            end = source.find("*/", index + 2)
            end = length if end == -1 else end + 2
            for position in range(index, end):
                if source[position] != "\n":
                    out[position] = " "
            index = end
            continue
        if char in "\"'`":
            quote = char
            out[index] = " "
            index += 1
            while index < length:
                current = source[index]
                if current == "\\" and index + 1 < length:
                    out[index] = " "
                    if source[index + 1] != "\n":
                        out[index + 1] = " "
                    index += 2
                    continue
                if current == quote:
                    out[index] = " "
                    index += 1
                    break
                if current != "\n":
                    out[index] = " "
                index += 1
            continue
        index += 1
    return "".join(out)


def _bracket_problems(masked: str) -> list[str]:
    """掩码文本里的括号配对问题；空列表 = 配对正常。"""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[tuple[str, int]] = []
    problems: list[str] = []
    for index, char in enumerate(masked):
        if char in "([{":
            stack.append((char, index))
            continue
        if char not in ")]}":
            continue
        if not stack or stack[-1][0] != pairs[char]:
            problems.append(f"位置 {index} 的 {char} 没有配对的开括号")
            continue
        stack.pop()
    problems.extend(f"位置 {index} 的 {char} 未闭合" for char, index in stack)
    return problems


def _function_span(source: str, header: str) -> tuple[int, int]:
    """`header`（如 `async function send(`）所在函数的原文区间 `[起, 止)`。

    配对在掩码文本上做（字符串/注释里的花括号不参与），索引直接用于切原文。
    """
    masked = _mask_literals(source)
    start = source.index(header)
    open_at = masked.index("{", start)
    depth = 0
    for position in range(open_at, len(masked)):
        if masked[position] == "{":
            depth += 1
        elif masked[position] == "}":
            depth -= 1
            if depth == 0:
                return start, position + 1
    raise AssertionError(f"{header} 的函数体没有闭合")


def _presets() -> list[tuple[str, str]]:
    return [(match.group(1), match.group(2)) for match in _PRESET_RULE.finditer(_JS)]


def _backend_routes() -> set[tuple[str, str]]:
    """后端实际注册的 `/api` 路由 `(method, path)`：常量表 + `routing.Route(...)` 注册行。"""
    constants = {
        name: value for name, value in vars(_APP_MODULE).items() if name.endswith("_PATH") and isinstance(value, str)
    }
    routes: set[tuple[str, str]] = set()
    for match in _ROUTE_RULE.finditer(_APP_SOURCE):
        target = match.group(1).strip()
        path = constants.get(target)
        if path is None and target.startswith('"'):
            path = target.strip('"')
        if path is None or not path.startswith("/api"):
            continue
        routes.update((method, path) for method in re.findall(r'"([A-Z]+)"', match.group(2)))
    return routes


# ── 资源挂载面 ──


class TestAssetIsServed:
    def test_script_is_in_the_whitelist_and_readable(self) -> None:
        assert "api-console.js" in _WEB_ASSETS
        assert _WEB_ASSETS["api-console.js"].startswith("text/javascript")
        assert '\n  "use strict";\n' in _JS
        assert _JS.rstrip().endswith("})();"), "必须是 IIFE，避免往 window 上挂全局变量"

    def test_page_loads_the_script_after_the_panel_bridge(self) -> None:
        assert _HTML.index('<script src="/panels.js">') < _HTML.index('<script src="/api-console.js">')
        assert _HTML.index('<script src="/api-console.js">') < _HTML.index('<script src="/app.js">')

    @pytest.mark.parametrize("element_id", _REQUIRED_IDS)
    def test_page_provides_the_element(self, element_id: str) -> None:
        assert f'id="{element_id}"' in _HTML

    @pytest.mark.parametrize("element_id", _REQUIRED_IDS)
    def test_script_binds_the_element(self, element_id: str) -> None:
        assert f'getElementById("{element_id}")' in _JS

    def test_panel_starts_closed_and_get_is_the_default_method(self) -> None:
        assert re.search(r'id="api-console"[^>]*\shidden(\s|>)', _HTML), "弹层默认收起（不进首屏动线）"
        assert re.search(r"<option[^>]*\sselected[^>]*>GET</option>", _HTML), "GET 必须是默认选中的方法"

    def test_no_third_party_resources(self) -> None:
        for pattern in _REMOTE_PATTERNS:
            assert pattern not in _JS, f"api-console.js 引用了第三方资源：{pattern}"

    @pytest.mark.parametrize("token", ["innerHTML", "outerHTML", "insertAdjacentHTML"])
    def test_no_html_injection_path(self, token: str) -> None:
        assert token not in _JS, "响应体是服务端事实，只能按纯文本渲染"

    def test_requests_go_through_the_panel_bridge(self) -> None:
        masked = _mask_literals(_JS)
        assert "fetch(" not in masked, "请求必须经 HePanels.request（同源 + 统一错误信封）"
        assert masked.count("window.HePanels") == 1

    def test_script_brackets_are_balanced(self) -> None:
        assert _bracket_problems(_mask_literals(_JS)) == []


# ── 开合与渲染 ──


class TestPanelBehaviour:
    def test_open_close_keep_hidden_and_aria_expanded_in_sync(self) -> None:
        assert "el.panel.hidden = !open;" in _JS
        assert 'el.button.setAttribute("aria-expanded", open ? "true" : "false");' in _JS
        assert re.search(r'el\.button\.addEventListener\("click"', _JS)
        assert re.search(r'el\.close\.addEventListener\("click"', _JS)

    def test_escape_closes_and_hash_deeplink_opens(self) -> None:
        assert re.search(r'event\.key === "Escape" && !el\.panel\.hidden', _JS)
        assert '=== "#api"' in _JS

    def test_opening_prefills_the_default_path(self) -> None:
        assert 'DEFAULT_PATH = "/api/projects"' in _JS
        assert "el.path.value = DEFAULT_PATH;" in _JS

    def test_result_rendering_is_plain_text_and_marks_truncation(self) -> None:
        assert "el.output.textContent" in _JS
        assert "MAX_OUTPUT_CHARS = 20000;" in _JS
        assert "…（已截断，共 " in _JS, "超长必须显式标注原始长度，不能静默截断"
        assert '"HTTP " + status + " (" + String(result.elapsed) + " ms)"' in _JS
        assert "JSON.stringify(payload, null, 2)" in _JS, "对象要格式化缩进"
        assert "无法连接到服务" in _JS, "网络异常给可理解的文案"

    def test_failure_status_comes_from_the_panel_bridge(self) -> None:
        start, end = _function_span(_JS, "function renderResult(")
        body = _JS[start:end]
        assert "panels.describeFailure(result)" in body
        assert '"failed"' in body
        assert '"done"' in body


# ── 发送前的本地判定与写方法闸门 ──


class TestSendGuards:
    def test_path_and_body_are_validated_before_the_request(self) -> None:
        start, end = _function_span(_JS, "async function send(")
        body = _JS[start:end]
        request_at = body.index(".request(")
        assert 'path.indexOf("/") !== 0' in body, "路径必须以 / 开头"
        assert body.index('path.indexOf("/") !== 0') < request_at
        assert "JSON.parse(rawBody)" in body, "请求体必须能被解析"
        assert body.index("JSON.parse(rawBody)") < request_at
        assert body.count("return;") >= 4, "每个失败判定都要 return（不落到请求）"

    def test_write_methods_are_the_four_state_changing_verbs(self) -> None:
        assert 'WRITE_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);' in _JS

    def test_confirm_happens_before_the_request(self) -> None:
        start, end = _function_span(_JS, "async function send(")
        body = _JS[start:end]
        assert "WRITE_METHODS.has(method) && !window.confirm(" in body, "取消分支必须是否定式守卫"
        assert body.index("WRITE_METHODS.has(method)") < body.index("window.confirm(")
        assert body.index("window.confirm(") < body.index(".request("), "确认必须早于发请求"
        between = body[body.index("window.confirm(") : body.index(".request(")]
        assert "return;" in between, "取消后必须在到达 request( 之前返回"

    def test_delete_confirmation_mentions_the_confirm_query(self) -> None:
        start, end = _function_span(_JS, "function confirmText(")
        body = _JS[start:end]
        assert 'method === "DELETE"' in body
        assert "?confirm=true" in body

    def test_get_and_delete_without_a_body_send_no_body(self) -> None:
        """空文本 = `payload` 保持 `undefined` ⇒ 面板桥不带 body（GET/DELETE 尤其不能带）。"""
        assert "let payload;" in _JS
        assert "if (rawBody) {" in _JS
        assert "panels.request(method, path, payload)" in _JS


# ── 预置端点与后端路由的一致性 ──


class TestPresets:
    def test_every_api_path_literal_matches_a_backend_route(self) -> None:
        backend_paths = {path for _, path in _backend_routes()}
        literals = set(_API_LITERAL_RULE.findall(_JS))
        assert literals, "api-console.js 里应当出现 /api 路径"
        assert sorted(literals - backend_paths) == [], "有路径在后端不存在（拼错或端点已下线）"

    def test_presets_cover_exactly_the_backend_routes(self) -> None:
        presets = {(method, path) for method, path in _presets()}
        backend = {(method, path) for method, path in _backend_routes() if path not in _FALLBACK_ROUTES}
        assert sorted(backend - presets) == [], "后端有路由没有预置按钮"
        assert sorted(presets - backend) == [], "预置按钮指向不存在的路由"

    def test_preset_count_is_pinned(self) -> None:
        presets = _presets()
        assert len(presets) == 20
        assert len(set(presets)) == len(presets), "同一 method+path 不得重复预置"

    def test_every_write_verb_is_reachable_from_the_presets(self) -> None:
        methods = {method for method, _ in _presets()}
        assert {"POST", "PATCH", "PUT", "DELETE"} <= methods, "否则写方法闸门永远不会被走到"

    def test_preset_methods_exist_in_the_method_select(self) -> None:
        for method in {method for method, _ in _presets()}:
            assert f">{method}</option>" in _HTML

    def test_clicking_a_preset_only_fills_the_form(self) -> None:
        start, end = _function_span(_JS, "function applyPreset(")
        body = _JS[start:end]
        assert ".request(" not in body, "预置按钮只填方法 + 路径，不自动发送"
        assert "el.path.value = path;" in body
        assert "el.method.value = preset.method;" in body

    def test_placeholders_are_filled_from_the_current_selection(self) -> None:
        assert "panels.activeProjectId()" in _JS
        assert "panels.activeSessionId()" in _JS
        assert "先选择项目" in _JS
        assert "先选择会话" in _JS
        assert 'path.split("{project_id}")' in _JS
        assert 'path.split("{session_id}")' in _JS
