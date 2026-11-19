"""后台任务面板（Epic 70，Story 70.1）的静态契约。

与 ``tests/test_http_web_ui.py`` 同一口径的**静态**断言，只钉两类事实：

- 页面必须有的东西：任务面板的四个元素 id、条目/详情的渲染字段与类名、轮询的 2s 常量与停表路径；
- 页面绝不能有的东西：HTML 注入路径、第三方资源、`/api/tasks*` 之外的端点。

浏览器里的真实轮询节奏（谁在驱动定时器、可见性切换的观感）由 `tests/fixtures/js/panels_probe.js`
的可执行回归覆盖（见本文件末尾 :class:`TestTasksPanelProbe`）：本机无 node 时那类用例 skip，
静态断言只保证「可检形态」（常量、句柄、可见性分支），不假装是运行时结果。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from heagent.network.http_server import _WEB_ASSETS, read_web_asset
from tests.helpers_js_probe import NODE, run_panels_probe

_HTML = read_web_asset("index.html").decode("utf-8")
_JS = read_web_asset("tasks.js").decode("utf-8")
_CSS = read_web_asset("styles.css").decode("utf-8")

# 第三方资源排除模式（与 test_http_web_ui 同一张表：严格 CSP 下也加载不了，出现即是坏味道）。
_REMOTE_PATTERNS = ("http://", "https://", "//cdn", "cdn.", "unpkg", "jsdelivr", "googleapis")

# 脚本里的字符串字面量路径（`"/api/tasks"` 这类）：任务面板只允许发这两个端点的请求。
_QUOTED_PATH_RE = re.compile(r"""["'](/[^"'\n]*)["']""")

# 详情面板必须逐字段呈现的服务端字段（字段集合由 TaskProgressView 决定）。
_DETAIL_KEYS = ("task_id", "kind", "status", "percent", "message", "started_at", "updated_at")

_OPEN_TO_CLOSE = {"(": ")", "[": "]", "{": "}"}
_CLOSE_TO_OPEN = {close: open_ for open_, close in _OPEN_TO_CLOSE.items()}


def _strip_strings_and_comments(source: str) -> str:
    """剥离字符串与非代码区（行注释 / 块注释 / 模板字面量），只留下真正的代码字符。

    括号平衡必须在代码上判：字面量里的 `(` 或注释里的 `{` 都不该参与配对。
    """
    out: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char == "/" and index + 1 < length and source[index + 1] == "/":
            end = source.find("\n", index)
            index = length if end == -1 else end
            continue
        if char == "/" and index + 1 < length and source[index + 1] == "*":
            end = source.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        if char in ("'", '"', "`"):
            index += 1
            while index < length:
                if source[index] == "\\":
                    index += 2
                    continue
                if source[index] == char:
                    index += 1
                    break
                index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _bracket_faults(code: str) -> list[str]:
    """返回括号配对问题（空列表即平衡）；嵌套错配与多余闭括号都点名。"""
    stack: list[tuple[str, int]] = []
    faults: list[str] = []
    for offset, char in enumerate(code):
        if char in _OPEN_TO_CLOSE:
            stack.append((char, offset))
        elif char in _CLOSE_TO_OPEN:
            if not stack:
                faults.append(f"多余的 {char}（偏移 {offset}）")
            elif stack[-1][0] != _CLOSE_TO_OPEN[char]:
                faults.append(f"{char} 与未闭合的 {stack[-1][0]} 错配（偏移 {offset}）")
                stack.pop()
            else:
                stack.pop()
    faults.extend(f"未闭合的 {open_}（偏移 {offset}）" for open_, offset in stack)
    return faults


class TestAssetContract:
    """脚本必须是白名单资源、被页面引用，且面板的四个容器仍在页面上。"""

    def test_tasks_script_is_a_whitelisted_asset(self) -> None:
        assert "tasks.js" in _WEB_ASSETS
        assert _WEB_ASSETS["tasks.js"] == "text/javascript; charset=utf-8"
        assert read_web_asset("tasks.js").strip(), "tasks.js 不能是空文件"

    def test_page_references_the_script(self) -> None:
        refs = re.findall(r'<script src="/([^"]+)"', _HTML)
        assert "tasks.js" in refs, "页面没有加载 tasks.js，面板永远不会被渲染"

    @pytest.mark.parametrize("element_id", ["task-list", "task-empty", "task-detail", "task-status"])
    def test_panel_elements_are_present(self, element_id: str) -> None:
        assert f'id="{element_id}"' in _HTML

    def test_empty_and_detail_areas_start_hidden(self) -> None:
        """空状态与详情是脚本按事实切换的：初始必须收起，否则打开页面就显示「当前没有后台任务」。"""
        assert re.search(r'id="task-empty"[^>]*\bhidden\b', _HTML)
        assert re.search(r'id="task-detail"[^>]*\bhidden\b', _HTML)

    def test_status_line_declares_its_idle_state(self) -> None:
        assert re.search(r'id="task-status"[^>]*data-state="idle"', _HTML)


class TestNoUntrustedHtml:
    """不可信内容一律走文本节点：kind / message 都来自服务端，拼 HTML 就是页面内脚本执行。"""

    @pytest.mark.parametrize("api", [".innerHTML", ".outerHTML", "insertAdjacentHTML"])
    def test_no_html_injection_api(self, api: str) -> None:
        assert api not in _JS

    def test_untrusted_text_goes_through_text_nodes(self) -> None:
        assert "textContent" in _JS
        assert 'document.createElement("li")' in _JS

    @pytest.mark.parametrize("api", ["eval(", "new Function", "document.write"])
    def test_no_dynamic_code_execution(self, api: str) -> None:
        assert api not in _JS

    def test_no_inline_event_handlers_in_markup(self) -> None:
        """脚本只挂监听器：HTML 里出现 on* 属性会被严格 CSP 拦下。"""
        assert not re.search(r"\son[a-z]+\s*=", _HTML)


class TestSameOriginOnly:
    """请求只经面板桥、只打任务端点（CSP `connect-src 'self'`，且面板不该越界读别的面）。"""

    @pytest.mark.parametrize("pattern", _REMOTE_PATTERNS)
    def test_no_remote_urls(self, pattern: str) -> None:
        assert pattern not in _JS, f"tasks.js 引用了第三方资源：{pattern}"

    def test_only_task_endpoints_are_requested(self) -> None:
        paths = _QUOTED_PATH_RE.findall(_JS)
        assert paths, "脚本必须引用 /api/tasks"
        for path in paths:
            assert path.startswith("/api/tasks"), f"任务面板不得调用其它端点：{path}"

    def test_both_task_endpoints_are_used(self) -> None:
        paths = _QUOTED_PATH_RE.findall(_JS)
        assert "/api/tasks" in paths, "列表端点必须来自字面量（拼接会绕开上面的白名单断言）"
        assert "/api/tasks/" in paths, "单条详情端点必须来自字面量"

    def test_requests_go_through_the_panel_bridge(self) -> None:
        """不自己 fetch、不自己解析响应：错误信封与时间格式都由桥统一给出。"""
        assert "fetch(" not in _JS
        assert "HePanels" in _JS
        assert ".request(" in _JS
        assert "describeFailure" in _JS
        assert "formatTime" in _JS


class TestPollingContract:
    """轮询只在有在途任务时进行：2s 常量、句柄可停、全终态与隐藏标签页都停表。"""

    def test_poll_interval_constant_is_two_seconds(self) -> None:
        assert re.search(r"const\s+POLL_MS\s*=\s*2000\s*;", _JS), "轮询间隔必须是有名字的 2000ms 常量"
        assert re.search(r"\},\s*POLL_MS\s*\)", _JS), "定时器延迟必须用这个常量，而不是另写一个数字"

    def test_timer_is_saved_and_stoppable(self) -> None:
        assert re.search(r"window\.(?:setTimeout|setInterval)\(", _JS), "必须用 window 上的定时器"
        assert re.search(r"window\.(?:clearTimeout|clearInterval)\(", _JS), "必须有停表调用"
        assert re.search(r"let\s+timer\s*=\s*null\s*;", _JS), "必须保存句柄才能停"
        assert re.search(r"timer\s*=\s*null\s*;", _JS), "停表后句柄要归位（否则会重复排程）"

    def test_active_states_are_the_trigger_and_terminal_states_stop_it(self) -> None:
        assert re.search(r"ACTIVE_STATES\s*=\s*new\s+Set\(", _JS)
        for state in ("pending", "running", "completed", "failed"):
            assert f"{state}:" in _JS, f"状态词表缺少 {state}"
        assert re.search(r"if\s*\(\s*hasActive\(tasks\)\s*\)\s*schedulePoll\(\)", _JS), "有在途任务才继续排程"
        assert re.search(r"else\s+stopPolling\(\)", _JS), "全终态 / 空列表必须停表（不得空转）"

    def test_stop_polling_is_reachable_from_every_exit(self) -> None:
        assert "function stopPolling()" in _JS
        # 定义处 1 次 + 隐藏标签页 + 终态分支（+ 排程前先清旧句柄）。
        assert _JS.count("stopPolling()") >= 3, "停表路径不能只有定义没有人调用"

    def test_hidden_tab_pauses_and_resume_fetches_immediately(self) -> None:
        assert "document.hidden" in _JS
        assert 'addEventListener("visibilitychange"' in _JS
        hidden_branch = _JS.split("visibilitychange", 1)[1]
        assert "stopPolling()" in hidden_branch, "隐藏时必须停表"
        assert "loadTasks()" in hidden_branch, "恢复可见要立刻补一次取数"

    def test_first_load_happens_without_a_timer(self) -> None:
        """首屏立即取一次：不能等 2s 后的第一次 tick，否则打开页面看到的是空面板。"""
        assert _JS.rstrip().endswith("void loadTasks();\n})();") or _JS.count("void loadTasks();") >= 2


class TestRenderingContract:
    """条目与详情的可检形态：类名供 styles.css 上色，字段逐个呈现（不静默丢字段）。"""

    @pytest.mark.parametrize("class_name", ["task-row", "task-title", "task-meta"])
    def test_row_classes_match_the_stylesheet(self, class_name: str) -> None:
        assert class_name in _JS, f"条目缺少 {class_name}"
        assert f".{class_name}" in _CSS, f"styles.css 里没有 .{class_name}"

    def test_row_state_drives_the_stylesheet(self) -> None:
        assert "dataset.state" in _JS
        for state in ("running", "pending", "failed"):
            assert f'.task-row[data-state="{state}"]' in _CSS

    def test_row_shows_kind_percent_status_and_time(self) -> None:
        assert "percentOf(task)" in _JS, "条目必须显示百分比"
        assert "formatTime(task.updated_at)" in _JS, "条目必须显示更新时间"
        assert "task.message" in _JS, "有 message 时才追加（不得无条件铺空串）"

    @pytest.mark.parametrize("key", _DETAIL_KEYS)
    def test_detail_renders_every_field(self, key: str) -> None:
        assert f'"{key}"' in _JS, f"详情面板漏掉了字段 {key}"

    def test_detail_unhides_only_after_content_is_built(self) -> None:
        assert re.search(r"el\.detail\.hidden\s*=\s*false", _JS)

    def test_failures_are_stated_not_swallowed(self) -> None:
        assert "无法连接到服务" in _JS, "网络失败必须有可读文案"
        assert "renderDetailFailure" in _JS, "详情取失败也要说出来"
        assert 'setStatus("failed", "无法连接到服务")' in _JS, "列表取数失败必须在状态行如实说明"


class TestSourceShape:
    """源码形态：IIFE + 严格模式、括号平衡（本机无 node，这里做一次语法结构自查）。"""

    def test_iife_with_strict_mode(self) -> None:
        assert re.search(r"^\(\(\) => \{$", _JS, re.MULTILINE)
        assert '"use strict";' in _JS
        assert _JS.rstrip().endswith("})();")
        assert not re.search(r"^\s*import\s", _JS, re.MULTILINE), "不得使用模块导入"

    def test_brackets_are_balanced(self) -> None:
        code = _strip_strings_and_comments(_JS)
        assert _bracket_faults(code) == []

    def test_stripper_itself_rejects_an_unbalanced_snippet(self) -> None:
        """反向自证：剥壳函数不能把问题藏起来（否则本类断言全是假的）。"""
        assert _bracket_faults(_strip_strings_and_comments("(() => { if (x) { }")), "未闭合的块必须被抓到"
        assert _bracket_faults(_strip_strings_and_comments('const s = "( 未闭合";')) == []


@pytest.mark.skipif(NODE is None, reason="需要 node 才能执行面板行为探针（CI 镜像自带 node）")
class TestTasksPanelProbe:
    """可执行回归（`tests/fixtures/js/panels_probe.js`）：真 tasks.js + 可控定时器。"""

    def test_list_renders_rows_in_server_order(self, tmp_path: Path) -> None:
        first = run_panels_probe("tasks-list", tmp_path)["first"]

        assert [row["title"] for row in first["rows"]] == ["context_compression · 42%", "context_compression · 100%"]
        assert first["rows"][0]["state"] == "running"
        assert first["rows"][0]["meta"].startswith("运行中 · ")
        assert first["rows"][1]["meta"].startswith("已完成 · ")
        assert first["emptyHintHidden"] is True, "有任务时空态文案必须收起"
        assert first["status"] == "共 2 个任务"

    def test_polling_is_armed_while_active_and_stops_at_terminal(self, tmp_path: Path) -> None:
        result = run_panels_probe("tasks-list", tmp_path)

        assert result["first"]["timers"] == 1, "存在 running 时必须排下一轮"
        assert result["afterTerminal"]["armedBefore"] == 1
        assert result["afterTerminal"]["timers"] == 0, "全终态后必须停表（不留空转定时器）"
        assert result["afterEmpty"]["timers"] == 0, "空列表同样停表"
        assert result["afterEmpty"]["emptyHintShown"] is True

    def test_failures_are_stated_and_do_not_clear_the_list(self, tmp_path: Path) -> None:
        after_failure = run_panels_probe("tasks-list", tmp_path)["afterFailure"]

        assert after_failure["status"] == "server_error: request failed", "失败要显示稳定错误码与服务端文案"
        assert after_failure["state"] == "failed"
        assert after_failure["rows"] == 2, "取数失败不得清空已渲染的行"
        assert after_failure["timers"] == 1, "失败后继续排程（下次成功即恢复）"

    def test_detail_404_and_success_render_the_server_fact(self, tmp_path: Path) -> None:
        result = run_panels_probe("tasks-list", tmp_path)

        assert result["detail404"]["text"] == "not_found: no such task", (
            "未知 id 的错误码是 not_found（不是 unknown_task）"
        )
        assert result["detail404"]["state"] == "failed"
        assert result["detail404"]["rows"] == 1, "详情失败不得牵连列表"
        assert result["detailOk"] == {"percent": "100%", "status": "已完成"}

    def test_hidden_tab_stops_polling_and_resume_fetches_immediately(self, tmp_path: Path) -> None:
        result = run_panels_probe("tasks-visibility", tmp_path)

        assert result["armed"] == 1
        assert result["whenHidden"] == {"timers": 0, "calls": 1}, "不可见的标签页不打服务端"
        assert result["whenVisible"]["calls"] == 2, "恢复可见立刻补取一次"
        assert result["whenVisible"]["timers"] == 1
        assert result["whenVisible"]["rows"] == 1
