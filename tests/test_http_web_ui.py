"""内置网页的静态契约与前端行为回归（Epic 49 的对话页 + Epic 50 的控制台 UI）。

两类断言，各有各的职责：

- **静态契约**（直接读包内资源）：页面**必须**有的东西（元素、纯文本渲染、无第三方资源、状态词表）
  与**绝不能**有的东西（内联脚本/样式、`innerHTML`、任何远程 URL）。前者保证 UX-DR1/DR3/DR6 的关键
  反馈不会被后续改动删掉；后者保证严格 CSP 与「不渲染不可信 HTML」这两条不是口号。
- **可执行行为回归**（`tests/js/app_probe.js` + node + 最小 DOM 替身）：加载**真实 app.js** 并驱动真实
  分支（提交 → SSE → 重连 → 项目/会话切换 → 设置面板 → 保存 → 失败映射），断言可观察结果而不是
  「源码里有没有某个字符串」——实测在缺陷存在时字符串断言照样全绿（Epic 49 评审的教训）。

浏览器里的真实交互（点击、重连观感、窄屏布局）由人工验收清单覆盖（story 50-6 的产物）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from heagent.network.http_server import _WEB_ASSETS, read_web_asset

_NODE = shutil.which("node")
_PROBE = Path(__file__).parent / "js" / "app_probe.js"

_HTML = read_web_asset("index.html").decode("utf-8")
_JS = read_web_asset("app.js").decode("utf-8")
_CSS = read_web_asset("styles.css").decode("utf-8")
_ASSETS = {"index.html": _HTML, "app.js": _JS, "styles.css": _CSS}

# 第三方资源的排除性模式：协议 URL、协议相对 URL、常见 CDN 主机名。
_REMOTE_PATTERNS = ("http://", "https://", "//cdn", "cdn.", "unpkg", "jsdelivr", "googleapis")


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

    def test_every_referenced_asset_is_whitelisted(self) -> None:
        """页面引用的每个资源都必须能经 ``read_web_asset`` 取到（否则线上就是 404 白页）。"""
        for ref in re.findall(r'(?:src|href)\s*=\s*"/([^"]+)"', _HTML):
            assert ref in _WEB_ASSETS, f"{ref} 不在资源白名单里"
            assert read_web_asset(ref)


class TestConsoleLayout:
    """Epic 50 的两栏骨架、设置面板与常驻安全声明（AC1 / UX-DR1 / UX-DR6）。"""

    @pytest.mark.parametrize(
        "element_id",
        [
            "console",  # 主体网格
            "sidebar",  # 左栏
            "sidebar-toggle",  # 窄屏降级时的侧栏开合
            "project-list",  # 项目列表
            "project-form",  # 登记入口
            "session-list",  # 会话列表
            "session-create",  # 新建会话
            "settings-button",  # 设置入口
            "settings-panel",  # 独立设置面板
            "settings-groups",  # 分组条目容器
            "settings-save",  # 保存
            "settings-gate",  # 写入闸门说明
            "settings-result",  # 保存结果反馈
            "unknown-keys",  # 未知键单列
            "confirm-overlay",  # 二次确认
            "confirm-text",
            "confirm-input",
        ],
    )
    def test_console_elements_are_present(self, element_id: str) -> None:
        assert f'id="{element_id}"' in _HTML

    def test_security_notice_is_permanent_and_not_collapsible(self) -> None:
        """安全声明必须常驻：页面里有它、有三条事实，且**没有**任何折叠/关闭它的控件。"""
        assert 'id="security-notice"' in _HTML
        assert "无认证" in _HTML
        assert "无 TLS" in _HTML
        assert "非安全边界" in _HTML
        assert "securityNotice" not in _JS, "安全声明不得由脚本隐藏/折叠"
        assert not re.search(r'id="security-notice"[^>]*\bhidden\b', _HTML)

    def test_settings_panel_starts_closed_and_is_announced(self) -> None:
        assert re.search(r'id="settings-panel"[^>]*\bhidden\b', _HTML), "设置面板初始应是收起的"
        assert 'aria-controls="settings-panel"' in _HTML
        assert 'aria-expanded="false"' in _HTML

    def test_stylesheet_has_three_column_and_narrow_screen_layout(self) -> None:
        """三栏（侧栏 / 对话 / 设置）在宽屏，窄屏降级为单列堆叠 —— 均为纯 CSS（无内联样式）。"""
        assert "grid-template-columns" in _CSS
        assert '[data-settings-open="true"]' in _CSS
        assert "@media (max-width: 1000px)" in _CSS
        assert '[data-sidebar-collapsed="true"]' in _CSS
        # 窄屏规则必须真的把网格收成一列（否则「降级」只是句空话）。
        narrow = _CSS.split("@media (max-width: 1000px)", 1)[1]
        assert "grid-template-columns: minmax(0, 1fr)" in narrow

    def test_no_third_party_resources_in_any_asset(self) -> None:
        """三份资源都不得出现任何远程 URL（严格 CSP 下也加载不了；出现即是坏味道）。"""
        for name, text in _ASSETS.items():
            for pattern in _REMOTE_PATTERNS:
                assert pattern not in text, f"{name} 引用了第三方资源：{pattern}"


class TestCspCompatibility:
    def test_no_inline_script_or_style(self) -> None:
        """严格 CSP（无 'unsafe-inline'）要求 HTML 里没有内联脚本/样式。"""
        assert "<style" not in _HTML.lower()
        assert not re.search(r"<script(?![^>]*\bsrc=)", _HTML, re.IGNORECASE), "不允许内联 <script>"
        assert not re.search(r"\sstyle\s*=", _HTML), "不允许 style= 属性"

    def test_no_inline_event_handlers(self) -> None:
        """内联事件属性（onclick=）同样会被 CSP 拦下，且会让「纯文本渲染」的保证失效。"""
        assert not re.search(r"\son[a-z]+\s*=", _HTML), "不允许内联事件处理器"

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

    def test_confirm_dialog_renders_its_text_as_plain_text(self) -> None:
        """确认框文案里含项目路径与会话标题（都来自服务端/磁盘）⇒ 必须走 textContent。"""
        assert "el.confirmText.textContent" in _JS
        assert "el.confirmTitle.textContent" in _JS


class TestRunFlowContract:
    """页面必须真的调用这些端点（否则「网页能跑一次 Agent」只是文档里的承诺）。"""

    def test_submits_runs_in_the_active_project_and_subscribes_to_events(self) -> None:
        """Epic 50：提交走**项目内**运行入口（会话随之落盘），SSE 与取消仍复用 run_id 端点。"""
        assert '"/api/projects"' in _JS
        assert "runsUrl" in _JS
        assert "/api/projects/${encodeURIComponent(projectId)}/runs" in _JS
        assert "EventSource" in _JS
        assert "/api/runs/${" in _JS

    def test_cancels_via_delete(self) -> None:
        assert 'method: "DELETE"' in _JS

    def test_restores_project_and_session_on_load(self) -> None:
        """刷新后要能回到「哪个项目的哪个会话」，并接手该项目在途的运行。"""
        assert '"/api/projects"' in _JS
        assert "restoreSession()" in _JS
        assert "sessionsUrl" in _JS
        assert "/sessions/${encodeURIComponent(sessionId)}" in _JS

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


class TestConsoleApiContract:
    """控制台各层调用的端点与请求形状（方法 + 稳定码映射在协议里，不在 UI 里发明）。"""

    @pytest.mark.parametrize(
        "path",
        [
            '"/api/projects"',  # 列表 / 登记
            'method: "POST",',  # 登记项目
            'method: "PATCH",',  # 重命名项目 / 会话
            "?confirm=true",  # 删除类必须显式确认（服务端也要求）
            "/config",  # 设置面板读取与写入
            'method: "PUT",',
        ],
    )
    def test_endpoint_vocabulary_is_present(self, path: str) -> None:
        assert path in _JS, path

    @pytest.mark.parametrize(
        "code",
        [
            "session_unreadable",
            "session_conflict",
            "session_busy",
            "project_busy",
            "project_unavailable",
            "project_not_removable",
            "run_conflict",
            "write_disabled",
            "field_not_writable",
            "invalid_value",
            "config_conflict",
            "config_write_failed",
            "loopback_required",
            "confirm_required",
        ],
    )
    def test_every_console_error_code_has_a_readable_text(self, code: str) -> None:
        """稳定码必须有中文文案（静默失败 = 用户不知道发生了什么）。"""
        assert f"{code}:" in _JS

    def test_source_badges_cover_all_four_layers(self) -> None:
        for source in ("default", "global_env", "project_env", "system_env"):
            assert f"{source}:" in _JS


def _run_probe(case: str, tmp_path: Path) -> dict[str, Any]:
    """在 node 里跑一次前端行为探针（真实脚本 + 最小 DOM / EventSource / fetch 替身）。

    探针脚本输出一行 ``PROBE_RESULT {json}``；断言落在可观察结果上（DOM 行、状态栏、是否发请求），
    而不是「源码里有没有某个字符串」。
    """
    (tmp_path / "app.js").write_bytes(read_web_asset("app.js"))
    (tmp_path / "index.html").write_bytes(read_web_asset("index.html"))
    # 固定 argv（node + 仓库内的探针脚本 + 两个临时文件路径 + 用例名），不经 shell、不含外部输入。
    completed = subprocess.run(  # noqa: S603
        [_NODE, str(_PROBE), str(tmp_path / "app.js"), str(tmp_path / "index.html"), case],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    marker = "PROBE_RESULT "
    line = next((line for line in completed.stdout.splitlines() if line.startswith(marker)), None)
    assert line is not None, completed.stdout
    return json.loads(line[len(marker) :])


@pytest.mark.skipif(_NODE is None, reason="需要 node 才能执行前端行为回归（CI 镜像自带 node）")
class TestWebUiBehaviour:
    """Epic 49 的行为回归：状态文案、同名工具配对、刷新接手在途运行、忙时提交不静默、键盘语义。"""

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


@pytest.mark.skipif(_NODE is None, reason="需要 node 才能执行前端行为回归（CI 镜像自带 node）")
class TestConsoleProjectLayer:
    """AC2：项目列表（含失效标记）、切换只改本页状态、切走**不取消**在途运行。"""

    def test_projects_render_and_switching_is_local_only(self, tmp_path: Path) -> None:
        result = _run_probe("F", tmp_path)

        assert result["unavailableMarked"] is True, "目录失效的项目必须有可见标记"
        assert result["unavailableDataset"] == "false"
        assert result["activeProject"] == "项目 B"
        assert result["sessionCalls"] >= 1, "切换项目后必须刷新该项目的会话列表"
        assert result["sessionEmptyHidden"] is False
        assert result["chatEntries"] == 0, "切到没有会话的项目后对话区应为空"
        assert result["stored"] == "pB", "当前项目只是本页偏好（localStorage），不是服务端状态"

    def test_leaving_a_running_project_detaches_the_stream_without_cancelling(self, tmp_path: Path) -> None:
        result = _run_probe("F", tmp_path)

        assert result["runCancelled"] == 0, "切换项目绝不能取消在途运行（服务端绑定不变）"
        assert result["streamClosed"] is True, "本页应当断开该运行的事件流（断线不取消运行）"
        assert result["noteHidden"] is False, "必须如实告知「那个项目还在跑」"
        assert "仍在继续" in result["noteText"]
        assert "不会取消运行" in result["noteText"]
        assert result["sendEnabled"] is True, "新项目里应当可以正常提交"


@pytest.mark.skipif(_NODE is None, reason="需要 node 才能执行前端行为回归（CI 镜像自带 node）")
class TestConsoleSettingsPanel:
    """AC4/AC5/AC6/AC8：来源徽标、只读原因、凭证掩码、闸门关闭的只读态、保存流程与失败文案。"""

    def test_read_only_reasons_sources_and_secret_masking(self, tmp_path: Path) -> None:
        result = _run_probe("G", tmp_path)

        assert result["panelShown"] is True and result["consoleFlag"] == "true"
        assert result["sourceBadgeText"] == "来源：全局 .env"
        assert result["sourceBadgeDataset"] == "global_env"
        assert result["sandboxReasonState"] == "sandbox_posture"
        assert "沙箱与执行后端" in result["sandboxReasonText"], "只读项必须显示原因（UX-DR5）"
        assert result["secretText"] == "已配置 ********", "凭证只显示已配置 + 定长掩码"
        assert result["secretHasInput"] == 0, "凭证不得提供输入框"
        assert result["unknownKeys"] == ["TOTALLY_UNKNOWN"]
        assert result["unknownEmptyHidden"] is True
        assert "重复键" in result["diagnostics"]
        assert "项目 .env 不存在" in result["diagnostics"], "响应级诊断也要渲染出来"

    def test_closed_gate_makes_every_writable_field_read_only_with_a_reason(self, tmp_path: Path) -> None:
        """AC5：闸门关闭 ⇒ 全部可写项不可编辑 + 原因 + **没有任何开启入口**。"""
        result = _run_probe("G", tmp_path)

        assert result["gateHidden"] is False
        assert "未开启配置写入" in result["gateText"]
        assert result["writable"] == "true", "白名单判定本身仍是「可写」——差异只能来自闸门状态"
        assert result["editable"] == "false"
        assert result["inputDisabled"] is True
        assert "未开启配置写入" in result["reasonText"]
        assert result["saveDisabled"] is True
        assert result["gateKeyEditable"] == "false", "开关自身也是只读（不能给自己解锁）"
        assert result["enabledInputs"] == 0, "面板里不得留下任何一个可编辑的配置控件"

    def test_saving_writes_with_fingerprint_and_refreshes_the_badge(self, tmp_path: Path) -> None:
        result = _run_probe("H", tmp_path)

        assert result["pendingAfterEdit"] == "有 1 项未保存"
        assert result["saveEnabledAfterEdit"] is True
        assert result["confirmShown"] is True, "写入必须二次确认（UX-DR3）"
        assert "MAX_ITERATIONS" in result["confirmText"]
        assert "下一次运行生效" in result["confirmText"]
        assert result["putBeforeConfirm"] == 0, "未确认前不得发出写入请求"
        assert result["writeBody"] == {
            "changes": [{"key": "MAX_ITERATIONS", "value": "30"}],
            "fingerprint": "fp-1",
        }, "必须携带当前文件指纹（服务端据此拒绝覆盖外部修改）"
        assert result["resultState"] == "ok"
        assert "下一次运行生效" in result["resultText"]
        assert "备份" in result["resultText"]
        assert "审计记录未能落盘" in result["resultText"], "审计没落盘必须显式可见"
        assert "已保存" in result["statusText"]
        assert result["rowValue"] == "30"
        assert result["rowSource"] == "来源：项目 .env", "保存后要用服务端事实刷新该项的来源徽标"
        assert result["inputAfterSave"] == "30"
        assert result["pendingAfterSave"] == "没有未保存的改动"
        assert result["saveDisabledAfterSave"] is True

    def test_enum_guard_renders_a_select_with_the_allowed_values(self, tmp_path: Path) -> None:
        result = _run_probe("H", tmp_path)

        assert result["enumOptions"] == ["compressor", "reset"]
        assert result["enumValue"] == "compressor"

    def test_write_result_keeps_the_row_truthful_when_the_panel_refresh_fails(self, tmp_path: Path) -> None:
        """写成功、但面板刷新失败时：写过的行必须显示写响应里的写后事实。

        退回旧值等于对用户撒谎（文件其实已经改了），而「未保存项」也必须归零——这些都由写响应
        携带的**写后条目**支撑，因此不能只靠随后的全量刷新。
        """
        result = _run_probe("N", tmp_path)

        assert result["sourceBefore"] == "来源：全局 .env"
        assert result["rowValue"] == "30", "写响应里的写后值必须就地生效"
        assert result["rowSource"] == "来源：项目 .env", "来源徽标同样来自写响应"
        assert result["rowInput"] == "30"
        assert result["resultState"] == "ok"
        assert "下一次运行生效" in result["resultText"]
        assert result["statusState"] == "failed"
        assert "面板刷新失败" in result["statusText"], "面板已过时必须说出来"
        assert result["pending"] == "没有未保存的改动"

    def test_write_failures_map_to_distinct_readable_texts(self, tmp_path: Path) -> None:
        """AC8：非法值 / 冲突 / 闸门关 —— 三类失败各有可理解文案，且都说明「文件未改动」。"""
        result = _run_probe("I", tmp_path)

        conflict = result["conflict"]
        assert conflict["resultState"] == "failed"
        assert "已被外部修改" in conflict["resultText"]
        assert "文件未改动" in conflict["resultText"]
        assert "已被外部修改" in conflict["statusText"], "状态行也要留下失败原因（不被自动刷新冲掉）"
        assert conflict["reloads"] >= 2, "指纹冲突后必须重新加载面板（否则用户拿着旧指纹反复失败）"

        assert "值不合法" in result["invalidValue"]
        assert "服务端说明：MAX_ITERATIONS: must be <= 100" in result["invalidValue"], "字段级原因要带上"

        assert "未开启配置写入" in result["gateClosed"]
        assert "没有改动任何文件" in result["gateClosed"]


@pytest.mark.skipif(_NODE is None, reason="需要 node 才能执行前端行为回归（CI 镜像自带 node）")
class TestConsoleSessionLayer:
    """AC7 与 D1：会话的新建/重命名/删除（二次确认）、损坏会话与「冲突」文案必须区分开。"""

    def test_session_create_rename_and_delete_flow(self, tmp_path: Path) -> None:
        result = _run_probe("J", tmp_path)

        assert result["createdShown"] is True and result["createdActive"] == "true"
        assert result["detailCalls"] == 1, "新建后要打开这个新会话"
        assert result["renameShown"] is True
        assert result["renamePrefill"] == "会话一", "重命名要预填当前标题"
        assert result["renamedTitle"] == "新标题"
        assert result["deleteText"] and "删除该会话文件" in result["deleteText"]
        assert "不可恢复" in result["deleteText"], "删除文案必须说明影响范围（UX-DR3）"

    def test_delete_requires_confirmation_and_sends_confirm(self, tmp_path: Path) -> None:
        result = _run_probe("J", tmp_path)

        assert result["afterCancel"] == {"deletes": 0, "stillListed": True}, "取消后不得删除，会话仍在列表里"
        assert result["afterDelete"]["deletes"] == 1, "确认后必须带 ?confirm=true 删除"
        assert result["afterDelete"]["stillListed"] is False
        assert "会话一" not in result["afterDelete"]["listTitles"]

    def test_unreadable_session_is_not_shown_as_an_empty_conversation(self, tmp_path: Path) -> None:
        """D1：文件损坏 ≠ 空会话。列表仍列出它（带标记），打开时给可操作的说明并挡住提交。"""
        result = _run_probe("J", tmp_path)

        assert result["badListed"] is True, "损坏的会话不能被静默地从列表里丢掉"
        assert result["badFlagged"] is True
        assert "无法解析" in result["badMeta"]
        assert result["badAutoOpened"] == 0, "不该自动打开一个无法解析的会话"
        assert len(result["badChatLines"]) == 1
        assert "不是空会话" in result["badChatLines"][0]
        assert "已被其它地方" not in result["badChatLines"][0], "损坏 ≠ 版本冲突，文案不能混用"
        assert result["badChatMeta"] == "会话文件无法解析"
        assert result["badChatMetaState"] == "failed"
        assert result["badSendDisabled"] is True, "不可读的会话不能继续往里写"
        assert "不可读" in result["badRunStatus"]
        assert result["badTitle"] == "不可读会话"


@pytest.mark.skipif(_NODE is None, reason="需要 node 才能执行前端行为回归（CI 镜像自带 node）")
class TestConsoleProjectRemoval:
    """AC7：移除登记必须二次确认，文案说明「只移除登记、磁盘数据保留」。"""

    def test_removal_requires_confirmation_and_says_what_survives(self, tmp_path: Path) -> None:
        result = _run_probe("K", tmp_path)

        assert result["confirmShown"] is True
        assert "保持不变" in result["confirmText"]
        assert "磁盘目录" in result["confirmText"]
        assert "C:/ws/pB" in result["confirmText"], "文案要指明是哪个目录"
        assert result["deletesBeforeConfirm"] == 0
        assert result["afterCancel"] == {"deletes": 0, "stillListed": True}
        assert result["afterRemove"]["deletes"] == 1, "确认后必须带 ?confirm=true"
        assert result["afterRemove"]["stillListed"] is False
        assert result["afterRemove"]["activeProject"] == "服务工作区", "移除当前项目后要回落到服务工作区"

    def test_default_project_cannot_be_removed_from_the_ui(self, tmp_path: Path) -> None:
        result = _run_probe("K", tmp_path)

        assert result["defaultHasRemove"] is False


@pytest.mark.skipif(_NODE is None, reason="需要 node 才能执行前端行为回归（CI 镜像自带 node）")
class TestConsoleChrome:
    """AC9：窄屏降级下侧栏可收起/展开（核心操作仍可达）。"""

    def test_sidebar_toggle_reports_its_state(self, tmp_path: Path) -> None:
        result = _run_probe("L", tmp_path)

        assert result["collapsed"] == {"flag": "true", "aria": "false", "label": "展开侧栏"}
        assert result["expanded"] == {"flag": "false", "aria": "true", "label": "收起侧栏"}


@pytest.mark.skipif(_NODE is None, reason="需要 node 才能执行前端行为回归（CI 镜像自带 node）")
class TestConsoleErrorMapping:
    """AC8：稳定错误码 → 可理解文案（不同语义不同文案；未知码回落到服务端文案）。"""

    def test_each_stable_code_gets_its_own_text(self, tmp_path: Path) -> None:
        result = _run_probe("M", tmp_path)
        texts = {entry["code"]: entry["text"] for entry in result["conflicts"]}

        assert "该项目已有运行在进行" in texts["run_conflict"]
        assert "项目目录已失效" in texts["project_unavailable"]
        assert "该会话正被一次运行使用" in texts["session_busy"]
        assert "已被其它地方" in texts["session_conflict"]
        assert "服务端说明：session changed on disk" in texts["session_conflict"]
        assert "该项目有运行在进行" in texts["project_busy"]
        assert "目录无效" in texts["invalid_project_path"]
        assert "服务端说明：path must be an existing directory" in texts["invalid_project_path"]

    def test_unknown_codes_fall_back_to_the_server_message(self, tmp_path: Path) -> None:
        result = _run_probe("M", tmp_path)
        texts = {entry["code"]: entry["text"] for entry in result["conflicts"]}

        assert texts["weird_code"] == "server said boom", "新码出现时不能显示成空白或「未知错误」"

    def test_rejected_submissions_do_not_retry_or_hide_the_failure(self, tmp_path: Path) -> None:
        result = _run_probe("M", tmp_path)

        assert result["callsAfterSubmitErrors"] == 3, "每次被拒的提交恰好发一次请求（不重试、不静默）"
        assert result["projectCalls"] >= 1
