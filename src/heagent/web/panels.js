/* 面板公共桥（Epic 70）：任务面板与 API 探索器对 app.js 的唯一接口面。
 *
 * 约束与 app.js 一致：纯原生 JS、只发同源请求、不渲染不可信内容（一律 textContent / createTextNode）。
 *
 * 「当前选择」由 app.js 经 `window.HeConsole.currentSelection()` 暴露，本文件**按需读取、不做广播**——
 * 面板在用户点击时才取一次，因此不会缓存到过期值；app.js 未加载时回退到 localStorage 里的项目 id
 * （那个键只存「看哪个项目」这一条 UI 偏好，与 app.js 是同一个键）。
 */
(() => {
  "use strict";

  const SELECTION_KEY = "heagent.console.project_id";

  function selection() {
    const bridge = window.HeConsole;
    if (bridge && typeof bridge.currentSelection === "function") {
      const current = bridge.currentSelection();
      if (current && typeof current === "object") return current;
    }
    return null;
  }

  function activeProjectId() {
    const current = selection();
    if (current && current.projectId) return String(current.projectId);
    try {
      return (window.localStorage.getItem(SELECTION_KEY) || "").trim();
    } catch (error) {
      /* 隐私模式下 localStorage 不可用：只是拿不到「当前项目」，不影响面板本身。 */
      return "";
    }
  }

  function activeSessionId() {
    const current = selection();
    if (current && current.sessionId) return String(current.sessionId);
    return "";
  }

  /**
   * 同源请求：返回 `{status, ok, elapsed, payload, text}`。
   *
   * **HTTP 错误也是结果**（不抛）：面板要展示状态码与错误信封，而不是把 4xx 变成一次异常。
   * 网络层失败（连接被拒）仍会抛，由调用方给「无法连接到服务」。
   */
  async function request(method, path, body) {
    const init = { method: method, headers: { accept: "application/json" } };
    if (body !== undefined) {
      init.headers["content-type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const started = window.performance.now();
    const response = await fetch(path, init);
    const elapsed = Math.round(window.performance.now() - started);
    const text = await response.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch (error) {
      payload = text;
    }
    return { status: response.status, ok: response.ok, elapsed: elapsed, payload: payload, text: text };
  }

  /** 稳定错误码 + 服务端文案（如实展示，不推断成败）。 */
  function describeFailure(result) {
    const error = result && result.payload && result.payload.error;
    if (!error) return "HTTP " + String((result && result.status) || 0);
    return String(error.code || "error") + ": " + String(error.message || "");
  }

  /** ISO 时间 → 本地可读（解析失败原样返回，绝不显示 "Invalid Date"）。 */
  function formatTime(value) {
    if (!value) return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString("zh-CN", { hour12: false });
  }

  window.HePanels = Object.freeze({
    activeProjectId: activeProjectId,
    activeSessionId: activeSessionId,
    request: request,
    describeFailure: describeFailure,
    formatTime: formatTime,
  });
})();
