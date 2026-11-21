"""服务器状态面板（Epic 71，Story 71.6）的静态契约与字段覆盖。

只钉三类事实：

- **页面必须有的**：`#server-status` 徽标、`#server-details` / `#server-groups` / `#server-panel-status`
  三个面板元素、`/status-panel.js` 的白名单条目与页面引用、轮询启停与可见性分支、失败文案。
- **页面绝不能有的**：HTML 注入 sink、第三方资源、`/api/status` 之外的端点字面量、硬编码版本号/主机名、
  徽标里的 `active_runs / max_inflight_runs` 比率、`app.js` 里的 `/api/status`（状态不进 5 秒 health 循环）。
- **字段覆盖**：`StatusResponse` 及其嵌套模型的字段必须以**消费形态**（`.field` 或 `["field"]`）出现在脚本里
  —— 后端加字段而面板不跟进即红；名字只是出现在别的列表 / 字面量 / 局部变量里不算被渲染（C2 的修补点）。
  服务身份三字段豁免：顶栏 `#service-meta` 已从 `/api/health` 展示它们（Story 70.2 的既有契约）。

**真实渲染结果**由 node 探针覆盖（`tests/fixtures/js/status_panel_probe.js`：最小 DOM 替身加载真实
`status-panel.js` 并驱动一份完整 `StatusResponse`）。没有 node 的环境跳过该类用例（本机实测 `which node`
无输出），因此这里的静态断言只保证「可检形态」，不假装是运行时结果。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from heagent.network.http_protocol import (
    CronJobInfo,
    ErrorCodeCount,
    ListenerInfo,
    RequestMetricsSummary,
    RoutingPoolInfo,
    RunStatusCounts,
    StatusResponse,
    TlsIdentityInfo,
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
_EXEMPT_FIELDS = frozenset(
    {
        "service",
        "version",
        "schema_version",
        # TLS 身份面只上面板两项人读值（短指纹 + 到期日）：完整 SHA-256 与 SAN 留给
        # `heagent tls fingerprint`（同一个实现源），侧栏 280px 里贴全量摘要只是噪声。
        "spki_sha256",
        "san",
    }
)
_STATUS_MODELS: tuple[type[BaseModel], ...] = (
    StatusResponse,
    RunStatusCounts,
    WsConnectionCounts,
    ListenerInfo,
    TlsIdentityInfo,
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

# 可执行探针：在真 node 里加载真实脚本、渲染一份完整 StatusResponse。
# 没有 node 的环境跳过相关用例（静态断言仍然生效）。
_NODE = shutil.which("node")
_PROBE = Path(__file__).parent / "fixtures" / "js" / "status_panel_probe.js"


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


def _field_access_pattern(field: str) -> re.Pattern[str]:
    """字段的**消费形态**：属性访问 `.field` 或下标访问 `["field"]` / `['field']`。

    不能用子串匹配（`field in source`）：「名字还在别处出现」不等于「渲染行还在」。实测把
    `["请求总数", num(requests.total)]` 整行删掉，`total` 仍出现在 `duration()` 的局部变量里，
    子串守卫因此继续全绿 —— 面板已经不再展示请求总数，契约却毫无反应。
    """
    name = re.escape(field)
    return re.compile(rf"\.{name}\b|\[\s*[\"']{name}[\"']\s*\]")


def _missing_fields(models: Sequence[type[BaseModel]], source: str) -> list[str]:
    """模型字段在脚本里没有以消费形态出现的那些（`.字段` / `["字段"]` 才算被渲染）。"""
    missing: list[str] = []
    for model in models:
        for name in model.model_fields:
            if name in _EXEMPT_FIELDS:
                continue
            if _field_access_pattern(name).search(source) is None:
                missing.append(f"{model.__name__}.{name}")
    return missing


def _drop_lines_containing(source: str, needle: str) -> str:
    """删掉所有包含 `needle` 的行（删除敏感性用例用；一行都没删掉即视为用例自身失效）。"""
    lines = source.splitlines(keepends=True)
    kept = [line for line in lines if needle not in line]
    assert len(kept) < len(lines), f"脚本里没有包含 {needle} 的行，用例已失效"
    return "".join(kept)


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

    def test_request_timeout_is_cleared_and_aborts_the_connection(self) -> None:
        """超时定时器必须收尾清掉，且超时要真的 abort 连接（半开连接不能一直挂着）。"""
        body = _function_body("loadStatus")
        assert "clearTimeout(timeoutId)" in body, "每次取数都会留下一个未清的游离定时器"
        assert "AbortController" in body and ".abort()" in body
        assert "loading = false" in body, "finally 里必须复位 loading（否则轮询永久卡死）"


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


class TestTlsIdentityRow:
    """Story 73.4：部署面多一行 `TLS: wss · pin XXXX-XXXX-XXXX · 到期 YYYY-MM-DD`。"""

    def test_identity_row_exists_only_for_tls_listeners(self) -> None:
        body = _function_body("deploymentRows")
        assert "if (identity.enabled) {" in body, "未启用 TLS 的 listener 不该出身份行"
        assert 'rows.push(["TLS", tlsRow(identity)]);' in body

    def test_identity_row_shape(self) -> None:
        """`wss · pin <短指纹> · 到期 <YYYY-MM-DD>`：值全部来自后端，前端只拼接与截日期。"""
        body = _function_body("tlsRow")
        assert '"wss · pin "' in body
        assert '" · 到期 "' in body
        assert "identity.short_fingerprint" in body
        assert "dateOnly(identity.not_after)" in body

    def test_expiry_is_a_plain_date_not_a_localized_stamp(self) -> None:
        body = _function_body("dateOnly")
        assert "slice(0, 10)" in body
        assert "UNAVAILABLE" in body, "形态不对时如实标不可用，不编日期"

    def test_deleting_the_identity_values_turns_the_guard_red(self) -> None:
        """删除敏感性：删掉渲染短指纹与到期日的那一行，守卫必须点名这两项。

        行的存在性由上面那条字面量断言兜住（删掉 ``rows.push(["TLS", …])`` 即红）；这里钉的是
        「值真的被消费」——``identity.enabled`` 仍在 listener 行的标记位置上，故不该被点名。
        """
        pruned = _drop_lines_containing(_CODE, "identity.short_fingerprint")

        assert _missing_fields((TlsIdentityInfo,), pruned) == [
            "TlsIdentityInfo.short_fingerprint",
            "TlsIdentityInfo.not_after",
        ]


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

    def test_only_all_loopback_listeners_count_as_local(self) -> None:
        """`lan`（非回环 + 免认证）必须报「对外」：把暴露面写成「本地」是本面板最不能犯的错。"""
        body = _function_body("modeOf")
        assert '"local"' in body, "判定必须以 local 为唯一「本地」条件"
        assert '"external"' not in body, "只认 external 会让 lan 档漏报成「本地」"
        assert "every(" in body


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

    def test_guard_requires_a_consumption_form(self) -> None:
        """C2：出现形态必须是 `.字段` / `["字段"]`；裸单词（局部变量、函数名、字符串）不算渲染。"""

        class _ProbeModel(BaseModel):
            total: int = 0

        bare_word = "const total = Math.max(0, seconds); function totalConnections() {}"
        assert _missing_fields((_ProbeModel,), bare_word) == ["_ProbeModel.total"]
        for consumed in ("num(requests.total)", 'row["total"]', "row['total']", "requests.total;"):
            assert _missing_fields((_ProbeModel,), consumed) == [], consumed

    def test_deleting_the_rendering_line_turns_the_guard_red(self) -> None:
        """删除敏感性：删掉渲染行，守卫必须报出该字段（子串匹配时代不会——名字还在别处）。"""
        pruned = _drop_lines_containing(_CODE, "requests.total")
        assert _missing_fields(_STATUS_MODELS, pruned) == ["RequestMetricsSummary.total"]
        # 旧口径（整份脚本子串命中即算）在同样的删改后仍然看不出问题，这正是 C2 的缺陷。
        assert "total" in pruned

    def test_deleting_every_active_runs_consumer_turns_the_guard_red(self) -> None:
        """`active_runs` 有两个消费点（徽标与运行态行）：两行都删掉才算「面板不再展示在途数」。"""
        pruned = _drop_lines_containing(_CODE, "status.active_runs")
        assert _missing_fields(_STATUS_MODELS, pruned) == ["StatusResponse.active_runs"]


def _run_probe(tmp_path: Path) -> dict[str, Any]:
    """在 node 里跑一次状态面板探针（真实 `status-panel.js` + 最小 DOM 替身）。

    探针输出一行 ``PROBE_RESULT {json}``；断言落在可观察的渲染结果上（徽标文案、页签行值），
    而不是「源码里有没有某个字符串」。
    """
    (tmp_path / "status-panel.js").write_bytes(read_web_asset("status-panel.js"))
    (tmp_path / "index.html").write_bytes(read_web_asset("index.html"))
    # 固定 argv（node + 仓库内探针 + 两个临时文件路径），不经 shell、不含外部输入。
    completed = subprocess.run(  # noqa: S603
        [_NODE, str(_PROBE), str(tmp_path / "status-panel.js"), str(tmp_path / "index.html")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    marker = "PROBE_RESULT "
    line = next((line for line in completed.stdout.splitlines() if line.startswith(marker)), None)
    assert line is not None, completed.stdout
    return json.loads(line[len(marker) :])


class TestStatusPanelProbe:
    """C1：`status-panel.js` 的执行级回归（无 node 的环境跳过，静态契约仍然生效）。"""

    def test_probe_fixture_is_committed(self) -> None:
        """不依赖 node：探针文件在位，且按 PROBE_RESULT 契约执行真实脚本。"""
        assert _PROBE.is_file(), "缺少 tests/fixtures/js/status_panel_probe.js"
        text = _PROBE.read_text("utf-8")
        assert "PROBE_RESULT " in text
        assert "PROBE_ERROR" in text
        assert "process.argv[2]" in text, "真实脚本路径必须由 argv 传入（跑的就是包内那一份）"
        assert "new Function(src)()" in text, "探针执行真实脚本，而不是复述它的字符串"

    @pytest.mark.skipif(_NODE is None, reason="需要 node 才能执行前端行为回归（本机实测无 node）")
    def test_real_script_renders_a_full_status_payload(self, tmp_path: Path) -> None:
        result = _run_probe(tmp_path)

        assert result["checks"] >= 20, f"探针检查项只有 {result['checks']} 条，跑通也不构成覆盖"
        observed = result["observed"]
        assert observed["badge"] == "对外 · up 1h2m · run 3 · WS 5"
        assert observed["tabs"] == ["运行态", "部署面", "依赖态", "资源", "请求计数"]
        assert observed["calls"] == ["GET /api/status"]
        assert ["2xx / 3xx", "111 / 4"] in observed["requestRows"]
        assert ["RSS", "不可用"] in observed["resourceRows"]
        assert observed["unexposedBadge"].startswith("未暴露")
