"""服务器状态面板（Epic 71，Story 71.6）的静态契约与字段覆盖。

只钉三类事实：

- **页面必须有的**：`#server-status` 徽标、`#server-details` / `#server-groups` / `#server-panel-status`
  三个面板元素、`/status-panel.js` 的白名单条目与页面引用、轮询启停与可见性分支、失败文案。
- **页面绝不能有的**：HTML 注入 sink、第三方资源、`/api/status` 之外的端点字面量、硬编码版本号/主机名、
  徽标里的 `active_runs / max_inflight_runs` 比率、`app.js` 里的 `/api/status`（状态不进 5 秒 health 循环）。
- **字段覆盖**：`StatusResponse` 及其嵌套模型的字段名必须全部出现在脚本里 —— 后端加字段而面板不跟进即红。
  服务身份三字段豁免：顶栏 `#service-meta` 已从 `/api/health` 展示它们（Story 70.2 的既有契约）。

真实浏览器里的轮询节奏由 node 探针覆盖（本机无 node ⇒ skip），因此静态断言只保证「可检形态」，
不假装是运行时结果。
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from pydantic import BaseModel

from heagent.network.http_protocol import (
    CronJobInfo,
    ErrorCodeCount,
    ListenerInfo,
    RequestMetricsSummary,
    RoutingPoolInfo,
    RunStatusCounts,
    StatusResponse,
    WsConnectionCounts,
)
from heagent.network.http_server import _WEB_ASSETS, read_web_asset

_HTML = read_web_asset("index.html").decode("utf-8")
_JS = read_web_asset("status-panel.js").decode("utf-8")
_APP_JS = read_web_asset("app.js").decode("utf-8")
_CSS = read_web_asset("styles.css").decode("utf-8")

# 第三方资源排除模式（与 test_http_web_ui 同一张表：严格 CSP 下也加载不了，出现即是坏味道）。
_REMOTE_PATTERNS = ("http://", "https://", "//cdn", "cdn.", "unpkg", "jsdelivr", "googleapis")
# 「把服务端字符串当 HTML 插进去」的入口：本仓一律 textContent。
_INJECTION_SINKS = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function")
# 脚本里的路径字面量（`"/api/status"`）：状态面板只允许发这一条端点。
_QUOTED_PATH_RE = re.compile(r"""["'](/[^"'\n]*)["']""")
# 版本号形态 `1.2.3`：版本真源在服务端，页面不许持有常量。
_VERSION_LITERAL = re.compile(r"v?\d+\.\d+\.\d+")

# 顶栏 `#service-meta` 已从 `/api/health` 展示服务身份，状态面板刻意不重复。
_EXEMPT_FIELDS = frozenset({"service", "version", "schema_version"})
_STATUS_MODELS: tuple[type[BaseModel], ...] = (
    StatusResponse,
    RunStatusCounts,
    WsConnectionCounts,
    ListenerInfo,
    RoutingPoolInfo,
    CronJobInfo,
    ErrorCodeCount,
    RequestMetricsSummary,
)


def _strip_comments(source: str) -> str:
    """去掉行注释与块注释：注释里提到 `innerHTML` 或旧端点名不该让契约变红。"""
    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^[ \t]*//.*$", "", without_block, flags=re.M)


_CODE = _strip_comments(_JS)


def _function_body(name: str) -> str:
    """取 `function <name>(…) { … }` 的函数体（按大括号配平，找不到即失败）。"""
    start = _CODE.find("function " + name + "(")
    assert start != -1, f"脚本里找不到函数 {name}"
    brace = _CODE.find("{", start)
    assert brace != -1, f"函数 {name} 没有函数体"
    depth = 0
    for index in range(brace, len(_CODE)):
        if _CODE[index] == "{":
            depth += 1
        elif _CODE[index] == "}":
            depth -= 1
            if depth == 0:
                return _CODE[brace : index + 1]
    raise AssertionError(f"函数 {name} 的大括号不配平")


def _missing_fields(models: Sequence[type[BaseModel]], source: str) -> list[str]:
    """模型字段在脚本里找不到出现的那些（`字段名` 字面量即算被消费）。"""
    missing: list[str] = []
    for model in models:
        for name in model.model_fields:
            if name in _EXEMPT_FIELDS:
                continue
            if name not in source:
                missing.append(f"{model.__name__}.{name}")
    return missing


class TestAssetWiring:
    def test_script_is_whitelisted_with_the_js_media_type(self) -> None:
        assert "status-panel.js" in _WEB_ASSETS
        assert _WEB_ASSETS["status-panel.js"] == "text/javascript; charset=utf-8"
        assert _JS.strip(), "status-panel.js 不能是空文件"

    def test_page_loads_the_script_after_the_panel_bridge(self) -> None:
        assert '<script src="/status-panel.js">' in _HTML, "页面没有加载 status-panel.js，面板永远不会渲染"
        assert _HTML.index('<script src="/panels.js">') < _HTML.index('<script src="/status-panel.js">')
        assert _HTML.index('<script src="/status-panel.js">') < _HTML.index('<script src="/app.js">')

    def test_panel_elements_are_declared_and_bound(self) -> None:
        for element_id in ("server-status", "server-details", "server-groups", "server-panel-status"):
            assert f'id="{element_id}"' in _HTML, f"页面缺少 #{element_id}"
            assert f'"{element_id}"' in _CODE, f"脚本没有绑定 #{element_id}"

    def test_panel_styles_exist(self) -> None:
        for selector in (".status-tabs", ".status-tab", ".status-tabpanel", ".status-rows"):
            assert selector in _CSS, f"样式表缺少 {selector}"
        assert ".status-group-title" not in _CSS, "分组已改成 tab，旧的纵向组标题样式成了死规则"


class TestRenderingDiscipline:
    def test_brackets_are_balanced(self) -> None:
        """无 node 环境下代替 `node --check` 的结构自查（字符串与注释里的括号不参与配对）。"""
        pairs = {")": "(", "]": "[", "}": "{"}
        stack: list[str] = []
        stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', _CODE)
        stripped = re.sub(r"'(?:[^'\\]|\\.)*'", "''", stripped)
        stripped = re.sub(r"`(?:[^`\\]|\\.)*`", "``", stripped)
        for char in stripped:
            if char in "([{":
                stack.append(char)
            elif char in pairs:
                assert stack and stack.pop() == pairs[char], f"括号不配平：多余的 {char}"
        assert stack == [], f"括号不配平：未闭合的 {stack}"

    def test_only_the_status_endpoint_is_called(self) -> None:
        paths = {path.split("?", 1)[0].rstrip("/") for path in _QUOTED_PATH_RE.findall(_CODE)}
        assert {path for path in paths if path.startswith("/api")} == {"/api/status"}
        assert "window.HePanels" in _CODE, "取数必须经面板公共桥（同源 + HTTP 错误即结果）"
        # 方法也要钉住：只改一个词（GET → POST）会让每次轮询拿 405、面板永久停在离线态。
        assert 'panels.request("GET"' in _CODE
        assert "panels.request(" in _CODE

    def test_no_html_injection_sink(self) -> None:
        for sink in _INJECTION_SINKS:
            assert sink not in _CODE, f"status-panel.js 出现注入入口：{sink}"
        assert "textContent" in _CODE

    def test_no_third_party_resource(self) -> None:
        for pattern in _REMOTE_PATTERNS:
            assert pattern not in _CODE

    def test_no_hardcoded_version_or_host(self) -> None:
        assert _VERSION_LITERAL.search(_JS) is None, "版本号真源在服务端，页面不许写常量"
        for host in ("localhost", "127.0.0.1", "0.0.0.0"):
            assert host not in _CODE, f"页面不应写死主机名：{host}"


class TestPollingDiscipline:
    def test_status_is_not_part_of_the_health_loop(self) -> None:
        assert "/api/status" not in _APP_JS, "状态取数必须留在 status-panel.js，不进 5 秒 health 循环"

    def test_interval_is_a_constant_and_no_setinterval(self) -> None:
        assert re.search(r"const POLL_MS = \d+;", _CODE), "轮询间隔必须是常量"
        assert "setInterval" not in _CODE, "用 setTimeout 串排程，避免请求重叠"

    def test_closing_the_panel_stops_polling(self) -> None:
        body = _function_body("schedulePoll")
        assert "shouldPoll()" in body
        assert "stopPolling();" in body
        toggle = _CODE[_CODE.find('"toggle"') : _CODE.find('"toggle"') + 400]
        assert "stopPolling();" in toggle, "收起面板必须停表"

    def test_hidden_tab_pauses_polling(self) -> None:
        assert '"visibilitychange"' in _CODE
        assert "document.hidden" in _CODE

    def test_groups_are_rendered_lazily(self) -> None:
        assert "if (el.details.open) renderGroups(status);" in _CODE, "收起时不该渲染明细（懒加载）"


class TestTabLayout:
    """五组事实装进一条横向 tab 条：一次只有一组的行在 DOM 里，切 tab 不额外取数。"""

    def test_tab_semantics_are_declared(self) -> None:
        tokens = ('role", "tablist', 'role", "tab', 'role", "tabpanel')
        tokens += ('"aria-selected"', '"aria-controls"', '"aria-labelledby"')
        for token in tokens:
            assert token in _CODE, f"tab 缺少无障碍属性：{token}"

    def test_tabs_are_buttons_with_keyboard_navigation(self) -> None:
        assert 'createElement("button")' in _CODE, "tab 必须是按钮元素，键盘才能聚焦"
        for key in ("ArrowLeft", "ArrowRight", "Home", "End"):
            assert key in _CODE, f"tab 条缺少 {key} 键处理"
        assert ".focus()" in _CODE, "键盘切换后焦点要跟着走"

    def test_only_the_active_group_is_rendered(self) -> None:
        body = _function_body("renderActiveGroup")
        assert "replaceChildren" in body, "切 tab 必须换掉面板内容"
        assert "GROUPS[activeGroup]" in body, "面板只渲染选中的那一组"

    def test_tabs_keep_group_order(self) -> None:
        titles = ["运行态", "部署面", "依赖态", "资源", "请求计数"]
        positions = [_CODE.find('"' + title + '"') for title in titles]
        assert all(position != -1 for position in positions), "五个分组的标题必须都在脚本里"
        assert positions == sorted(positions), "tab 顺序必须与 GROUPS 声明顺序一致"

    def test_switching_tabs_does_not_refetch(self) -> None:
        body = _function_body("selectGroup")
        assert "panels.request(" not in body
        assert "loadStatus(" not in body, "切页签不是取数理由：用最近一次快照重渲染"

    def test_tablist_is_built_once(self) -> None:
        assert "if (tablist !== null) return;" in _function_body("buildTabs")


class TestFailureSemantics:
    def test_failure_keeps_the_last_rendered_values(self) -> None:
        body = _function_body("markOffline")
        assert "replaceChildren" not in body, "失败必须保留上次值，不得清空"
        assert 'dataset.state = "offline"' in body

    def test_failure_uses_the_shared_error_mapping(self) -> None:
        assert "panels.describeFailure(result)" in _CODE
        assert "无法连接到服务" in _CODE


class TestBadge:
    def test_badge_does_not_render_a_ratio(self) -> None:
        body = _function_body("renderBadge")
        assert "active_runs" in body
        assert "max_inflight_runs" not in body, "服务级在途数与每项目上限不得按比率渲染（71.1 评审裁定）"
        assert "/" not in body, "徽标里不应出现除号形态的比率"

    def test_badge_shows_mode_uptime_run_and_connections(self) -> None:
        body = _function_body("renderBadge")
        for token in ('"up "', '"run "', '"WS "', "modeOf(", "totalConnections("):
            assert token in body
        for label in ("本地", "对外", "未暴露"):
            assert label in _CODE


class TestFieldCoverage:
    def test_every_status_field_is_rendered_or_exempted(self) -> None:
        assert _missing_fields(_STATUS_MODELS, _CODE) == []

    def test_guard_sees_the_real_fields(self) -> None:
        """守卫自己要先看得见东西：模型字段被清空/import 失效时，「全绿」毫无意义。"""
        total = sum(len(model.model_fields) for model in _STATUS_MODELS)
        assert total >= 45, f"只数到 {total} 个状态字段 —— 守卫失效了"

    def test_guard_detects_an_unrendered_field(self) -> None:
        class _ProbeModel(BaseModel):
            rendered_by_nobody: int = 0

        assert _missing_fields((_ProbeModel,), _CODE) == ["_ProbeModel.rendered_by_nobody"]
