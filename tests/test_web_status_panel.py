"""Story 70.2：顶栏「服务身份」与「进程会话快照」两个徽标的静态契约 + 可执行回归。

静态契约钉的是**源码契约**（资源里必须有什么 / 绝不能有什么），不是像素级行为：

- 两个徽标的 id 必须在页面里声明，脚本必须真的引用它们（否则渲染是死代码）；
- 快照请求只走同源 ``/api/session``，且**不得**塞进 5 秒 health 轮询（无谓请求）；
- 版本号**只**来自 ``/api/health`` 响应体 —— 页面里出现硬编码版本号即视为契约破坏；
- 断连语义是「保留上次值 + 标注」，不是清空；
- 渲染纪律：只用 ``textContent``，没有任何 HTML 注入 sink。

可执行行为回归（真 app.js + node + 最小 DOM 替身，用例 ``Y``）在本文件末尾的
:class:`TestServiceIdentityProbe`：版本跟着响应变、快照两态、断连保留与恢复。没有 node 的环境
（本仓开发容器）那一类用例 skip，静态契约仍生效；``node --check`` 的替代自查见
:meth:`TestScriptStructure.test_brackets_are_balanced`。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from heagent.network.http_server import read_web_asset
from tests.helpers_js_probe import NODE, run_app_probe

_HTML = read_web_asset("index.html").decode("utf-8")
_APP_JS = read_web_asset("app.js").decode("utf-8")

# 三段式版本号（可带 v 前缀）：``"0.10.0"`` / ``'v1.2.3'`` 这类常量一律不许出现在页面脚本里。
# 中文注释里的 ``4.17``（文档小节号）只有两段，且注释已先被遮掉，不会误伤。
_VERSION_LITERAL = re.compile(r"v?\d+\.\d+\.\d+")


def _mask_js(source: str, *, mask_strings: bool) -> str:
    """把注释（以及可选的字符串/模板串）替换成等长空格，**长度与偏移保持不变**。

    两种遮法各有用途：

    - 只遮注释：用于「脚本里不许出现 X」类断言 —— 注释里提到 ``innerHTML`` 或版本号是说明文字，
      不该让契约变红；字符串保持原样，因为硬编码版本号恰恰会藏在字符串里；
    - 连字符串一起遮：只留结构字符，供括号配对自查与函数体切片（字符串里的括号不参与配对）。

    长度不变是这条函数的核心承诺：``_function_body`` 在遮过的文本上定位，再按同一偏移回原文切片。
    """
    out: list[str] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        following = source[index + 1] if index + 1 < length else ""
        if char == "/" and following == "/":
            end = source.find("\n", index)
            end = length if end == -1 else end
            out.append(" " * (end - index))
            index = end
        elif char == "/" and following == "*":
            found = source.find("*/", index + 2)
            end = length if found == -1 else found + 2
            out.append(" " * (end - index))
            index = end
        elif char in "'\"`" and mask_strings:
            quote = char
            out.append(" ")
            index += 1
            while index < length:
                current = source[index]
                if current == "\\":  # 转义：连下一个字符一起吃掉（长度按原样补齐）
                    out.append(" " * min(2, length - index))
                    index += 2
                    continue
                out.append("\n" if current == "\n" else " ")
                index += 1
                if current == quote:
                    break
        else:
            out.append(char)
            index += 1
    return "".join(out)


# 注释已遮：用来扫「不许出现」的字面量（保留字符串内容）。
_NO_COMMENTS = _mask_js(_APP_JS, mask_strings=False)
# 连字符串一起遮：只留结构（括号配对 / 函数体定位）。
_STRUCTURE = _mask_js(_APP_JS, mask_strings=True)


def _function_body(name: str) -> str:
    """取 ``function <name>(…) { … }`` 的函数体原文（按遮过的结构文本做花括号配对）。"""
    match = re.search(rf"function\s+{re.escape(name)}\s*\(", _STRUCTURE)
    assert match, f"app.js 里找不到函数 {name}"
    start = _STRUCTURE.index("{", match.end())
    depth = 0
    for index in range(start, len(_STRUCTURE)):
        char = _STRUCTURE[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return _APP_JS[start : index + 1]
    raise AssertionError(f"函数 {name} 的花括号不配对")


class TestMarkup:
    @pytest.mark.parametrize("element_id", ["service-meta", "session-snapshot"])
    def test_status_badges_are_declared(self, element_id: str) -> None:
        assert f'id="{element_id}"' in _HTML


class TestWiring:
    @pytest.mark.parametrize(
        ("element_id", "reference"),
        [("service-meta", "serviceMeta"), ("session-snapshot", "sessionSnapshot")],
    )
    def test_element_references_are_registered(self, element_id: str, reference: str) -> None:
        """脚本必须真的持有这两个节点：没有引用，渲染函数就成了死代码。"""
        assert f'{reference}: document.getElementById("{element_id}")' in _NO_COMMENTS

    def test_snapshot_loader_requests_the_same_origin_endpoint(self) -> None:
        body = _function_body("loadSessionSnapshot")
        assert 'fetch("/api/session"' in body

    def test_health_poll_does_not_fetch_the_snapshot(self) -> None:
        """5 秒轮询只问服务是否活着；快照另走「启动 + 运行终态」触发，避免无谓请求。"""
        body = _function_body("checkHealth")
        assert "/api/session" not in body
        assert "loadSessionSnapshot" not in body
        assert "window.setInterval(checkHealth, HEALTH_POLL_MS);" in _NO_COMMENTS

    def test_terminal_run_states_refresh_the_snapshot(self) -> None:
        assert 'const TERMINAL_RUN_STATES = new Set(["done", "failed", "disconnected"]);' in _NO_COMMENTS
        body = _function_body("setRunState")
        assert "TERMINAL_RUN_STATES.has(code)" in body
        assert "void loadSessionSnapshot();" in body

    def test_bootstrap_loads_the_snapshot_after_startup(self) -> None:
        body = _function_body("bootstrap")
        assert "void loadSessionSnapshot();" in body
        assert body.index("selectProject(") < body.index("void loadSessionSnapshot();")


class TestRenderingDiscipline:
    @pytest.mark.parametrize("sink", [".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write"])
    def test_no_html_injection_sinks(self, sink: str) -> None:
        assert sink not in _NO_COMMENTS, f"app.js 出现了 HTML 注入 sink：{sink}"

    @pytest.mark.parametrize("name", ["renderServiceMeta", "renderSessionSnapshot"])
    def test_badges_are_rendered_as_plain_text(self, name: str) -> None:
        body = _function_body(name)
        assert ".textContent = " in body

    def test_version_comes_from_the_response_not_from_a_constant(self) -> None:
        """版本真源只有服务端 ``heagent.__version__``：页面脚本不许持有任何版本号字面量。"""
        found = _VERSION_LITERAL.findall(_NO_COMMENTS)
        assert not found, f"app.js 里出现硬编码版本号：{found}"
        body = _function_body("renderServiceMeta")
        for field in ("payload.service", "payload.version", "payload.schema_version"):
            assert field in body
        assert "el.serviceMeta.textContent = parts.join(" in body
        assert "el.serviceMeta.hidden = false;" in body

    def test_offline_path_keeps_the_last_service_identity(self) -> None:
        """断连只标注 data-state=offline：**不清空、不隐藏**（上次的服务身份仍是有用信息）。"""
        body = _function_body("markServiceMetaOffline")
        assert 'dataset.state = "offline"' in body
        assert "textContent" not in body
        assert "hidden" not in body

    def test_snapshot_failure_keeps_the_last_text(self) -> None:
        body = _function_body("markSessionSnapshotStale")
        assert '"无法连接到服务"' in body
        assert "textContent" not in body
        assert "hidden" not in body

    def test_snapshot_shows_the_fields_and_the_empty_run_wording(self) -> None:
        body = _function_body("renderSessionSnapshot")
        for field in ("snapshot.session_id", "snapshot.run_id", "snapshot.status", "snapshot.messages"):
            assert field in body
        assert '"暂无运行"' in body
        assert "el.sessionSnapshot.textContent = parts.join(" in body
        assert "el.sessionSnapshot.hidden = false;" in body


class TestScriptStructure:
    def test_brackets_are_balanced(self) -> None:
        """本机没有 node：``node --check`` 的替代自查 —— 剥离字符串与注释后逐个配对括号。"""
        pairs = {")": "(", "]": "[", "}": "{"}
        stack: list[str] = []
        for index, char in enumerate(_STRUCTURE):
            if char in "([{":
                stack.append(char)
            elif char in pairs:
                assert stack, f"多余的 {char}（偏移 {index}）"
                opening = stack.pop()
                assert opening == pairs[char], f"{opening} 与 {char} 不配对（偏移 {index}）"
        assert not stack, f"未闭合的括号：{''.join(stack)}"

    def test_no_inline_script_or_remote_resource(self) -> None:
        """严格 CSP 前提：脚本只有同源 app.js，页面不引任何第三方资源。"""
        assert "http://" not in _NO_COMMENTS
        assert "https://" not in _NO_COMMENTS
        assert "//cdn" not in _NO_COMMENTS


@pytest.mark.skipif(NODE is None, reason="需要 node 才能执行前端行为探针（CI 镜像自带 node）")
class TestServiceIdentityProbe:
    """可执行回归：真 app.js + 最小 DOM 替身，断言落在徽标的可观察文本与 ``data-state`` 上。"""

    def test_version_comes_from_the_response(self, tmp_path: Path) -> None:
        result = run_app_probe("Y", tmp_path)
        initial = result["initial"]

        assert initial["meta"] == "heagent-http · v9.9.9 · schema 1"
        assert initial["metaState"] == "ready"
        assert initial["metaHidden"] is False, "拿到响应后徽标必须可见"
        assert result["changed"]["meta"] == "heagent-http · v1.2.3 · schema 2", (
            "换一个响应版本号，徽标必须跟着变（前端持任何版本常量都过不了这条）"
        )

    def test_session_snapshot_covers_both_run_states(self, tmp_path: Path) -> None:
        result = run_app_probe("Y", tmp_path)

        assert result["initial"]["snapshot"] == "本进程 · 会话 s1 · 暂无运行 · 消息 1", "run_id 为 null 时给占位文案"
        assert result["withRun"]["snapshot"] == "本进程 · 会话 s1 · 运行 run-7（running） · 消息 0"

    def test_offline_keeps_the_last_identity_then_recovers(self, tmp_path: Path) -> None:
        result = run_app_probe("Y", tmp_path)
        offline = result["offline"]

        assert offline["metaState"] == "offline"
        assert offline["serviceState"] == "offline"
        assert offline["meta"] == "heagent-http · v1.2.3 · schema 2", "断连时保留上次的服务身份，不清空"
        assert offline["metaHidden"] is False, "断连不得隐藏徽标（否则用户看不出自己连的是哪个版本）"
        assert result["recovered"]["metaState"] == "ready"
