"""前端消费覆盖守卫（Story 70.4）：后端路由与网页端调用必须双向对得上。

两类失败各防一件事：

- **正向**（路由 → 前端）：后端新加了一条 HTTP 路由、网页端没人调、也没进白名单 ⇒ 红。
  这类缺口没有守卫时完全静默：`/api/tasks` 从 Story 64.11 交付到 Epic 70 之前一直零消费，
  只能靠人工对着路由表核对才发现。
- **反向**（前端 → 路由）：前端改了个路径（拼错、端点被删）⇒ 红，而不是等用户点下去看 404。

比对是**路径级**的（方法不进比较）：方法集合要从 `fetch(url, {method})` 这类调用点静态还原，
成本高而收益低；白名单条目里写清方法是哪个即可。路径模板的段位对齐规则见 :func:`_matches`。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from heagent.network.http_server import _WEB_ASSETS, read_web_asset
from heagent.network.http_server import app as http_app

_SRC = Path(__file__).parent.parent / "src"
_APP_PY = _SRC / "heagent" / "network" / "http_server" / "app.py"

# 前端路径字面量：普通字符串与模板串（`${...}` 在下面归一成 `{}`）。
_JS_PATH_RE = re.compile(r"""(?P<q>["'`])(?P<body>/api[^"'`]*)(?P=q)""")
# 模板串插值：本仓的插值表达式里不含引号与嵌套花括号（`${encodeURIComponent(x)}`）。
_INTERP_RE = re.compile(r"\$\{[^{}]*\}")
# 路由注册行：`routing.Route(<路径表达式>, endpoint=…, methods=[…])`（可跨行）。
_ROUTE_RE = re.compile(r"routing\.Route\(\s*([^,\n]+?)\s*,\s*endpoint=[^)]*?methods=\[([^\]]*)\]", re.S)
# 模块级路径常量：`_HEALTH_PATH = "/api/health"`。
_CONST_RE = re.compile(r'^(_[A-Z0-9_]+_PATH)\s*=\s*"([^"]+)"', re.M)

# 刻意不接网页端的路由：**理由必须写清楚**（空理由或一句「用不到」都不算）。
_WHITELIST: dict[str, str] = {
    "/api/runs": (
        "POST /api/runs 是非项目作用域的裸提交口；网页控制台一律走 "
        "POST /api/projects/{project_id}/runs（运行必须带项目归属，选择只是本页状态）"
    ),
    "/api/projects/{project_id}/sessions/{session_id}/{extra:path}": (
        "多段会话路径的兜底路由（%2F 在路由前被解码 ⇒ ../ 之类落成多段），只回 invalid_session_id；前端不该主动构造它"
    ),
}


def _route_constants() -> dict[str, str]:
    """`app.py` 里模块级 `*_PATH` 常量 → 路径。"""
    return {name: value for name, value in _CONST_RE.findall(_APP_PY.read_text(encoding="utf-8"))}


def _backend_routes() -> set[str]:
    """后端**实际注册**的 HTTP 路由路径（按 `routing.Route(...)` 行还原，常量名就地解析）。

    只收 `/api` 开头的路由：`/`（首页）与 `/{asset}`（静态资源）由浏览器按 `index.html` 的引用加载，
    不是前端脚本消费的对象 —— 它们的守卫是 `tests/test_http_web_ui.py` 的双向断言
    （引用的都在白名单 / 白名单里的都被引用）。
    """
    constants = _route_constants()
    source = _APP_PY.read_text(encoding="utf-8")
    paths: set[str] = set()
    for expr, _methods in _ROUTE_RE.findall(source):
        token = expr.strip()
        if token in constants:
            paths.add(constants[token])
        elif token.startswith('"') and token.endswith('"'):
            paths.add(token.strip('"'))
        else:  # 新增注册形态（非常量、非字面量）：宁可红，也别静默漏掉一条路由
            raise AssertionError(f"无法解析的路由注册表达式：{expr!r}（请让守卫认识它）")
    api_paths = {path for path in paths if path.startswith("/api")}
    assert len(api_paths) >= 10, f"只解析出 {sorted(api_paths)} —— 守卫本身失效了"
    return api_paths


def _segments(path: str) -> list[str]:
    return [segment for segment in path.strip("/").split("/") if segment]


def _is_param(segment: str) -> bool:
    return segment.startswith("{") and segment.endswith("}")


def _matches(pattern: str, route: str) -> bool:
    """前端路径 ``pattern`` 能否落在路由模板 ``route`` 上（段位逐一对齐）。

    规则：共同段必须「相等或路由侧是参数」；剩下的**路由**段必须全是参数
    ⇒ 前缀式路径（`/api/tasks`）能匹配 `/api/tasks/{task_id}`，而 `/api/typo` 匹配不上任何路由。
    """
    pattern_segments = _segments(pattern)
    route_segments = _segments(route)
    if len(pattern_segments) > len(route_segments):
        return False
    for mine, theirs in zip(pattern_segments, route_segments, strict=False):
        if _is_param(theirs):
            continue
        if mine != theirs:
            return False
    return all(_is_param(segment) for segment in route_segments[len(pattern_segments) :])


def _frontend_paths() -> dict[str, set[str]]:
    """`web/*.js` 里的 `/api...` 字面量：归一后 → 出现它的脚本名集合。"""
    found: dict[str, set[str]] = {}
    for name in _WEB_ASSETS:
        if not name.endswith(".js"):
            continue
        text = read_web_asset(name).decode("utf-8")
        for match in _JS_PATH_RE.finditer(text):
            body = match.group("body")
            body = _INTERP_RE.sub("{}", body).split("?", 1)[0].rstrip("/")
            if not body.startswith("/api"):
                continue
            found.setdefault(body, set()).add(name)
    return found


class TestBackendToFrontend:
    def test_every_http_route_is_consumed_or_whitelisted(self) -> None:
        frontend = _frontend_paths()
        missing = []
        for route in sorted(_backend_routes()):
            if route in _WHITELIST:
                continue
            if any(_matches(pattern, route) for pattern in frontend):
                continue
            missing.append(route)
        assert missing == [], (
            f"这些后端路由在网页端没有任何调用，也没进白名单 —— 接入网页端，或在 _WHITELIST 里写清理由：{missing}"
        )

    def test_whitelist_entries_still_exist_and_have_reasons(self) -> None:
        routes = _backend_routes()
        for route, reason in _WHITELIST.items():
            assert route in routes, f"白名单指向了不存在的路由：{route}"
            assert len(reason.strip()) >= 12, f"白名单理由太笼统（至少写清为什么不接）：{route}"

    def test_guard_detects_a_new_unconsumed_route(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """变异：假装后端多了一条没人调用的路由 ⇒ 正向断言必须红（守卫本身不能假绿）。"""
        routes = _backend_routes()
        monkeypatch.setattr(
            "tests.test_web_endpoint_coverage._backend_routes",
            lambda: routes | {"/api/guard-probe"},
        )
        with pytest.raises(AssertionError, match="guard-probe"):
            TestBackendToFrontend().test_every_http_route_is_consumed_or_whitelisted()


class TestFrontendToBackend:
    def test_every_frontend_path_hits_a_real_route(self) -> None:
        routes = _backend_routes()
        unknown = []
        for pattern, scripts in sorted(_frontend_paths().items()):
            if not any(_matches(pattern, route) for route in routes):
                unknown.append(f"{pattern}（{sorted(scripts)}）")
        assert unknown == [], f"网页端调用了不存在的路径：{unknown}"

    def test_frontend_paths_are_discovered(self) -> None:
        """守卫自己要先能看见东西：一条都提取不到时，「全绿」毫无意义。"""
        paths = _frontend_paths()
        assert len(paths) >= 10, f"提取到的前端路径过少：{sorted(paths)}"
        assert any(name == "api-console.js" for names in paths.values() for name in names)

    def test_guard_detects_a_typo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        frontend = _frontend_paths()
        monkeypatch.setattr(
            "tests.test_web_endpoint_coverage._frontend_paths",
            lambda: {**frontend, "/api/typo": {"app.js"}},
        )
        with pytest.raises(AssertionError, match="/api/typo"):
            TestFrontendToBackend().test_every_frontend_path_hits_a_real_route()


def test_backend_route_parser_sees_the_task_endpoints() -> None:
    """具体到 Epic 70 的两条端点：解析器必须看得见它们（否则正向断言等于没跑）。"""
    routes = _backend_routes()
    assert "/api/tasks" in routes
    assert "/api/tasks/{task_id}" in routes
    assert http_app is not None  # 模块可导入即说明常量定义处就是守卫读取处
