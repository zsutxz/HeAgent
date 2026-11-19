/* 同源 API 探索器（Epic 70，Story 70.3）：在页面内对已存在的端点发请求并查看原始响应。
 *
 * 默认收起、不进首屏动线；只发同源请求（CSP `connect-src 'self'`），写方法需二次确认。
 * 响应一律按纯文本渲染（textContent），不解析成 DOM。
 *
 * 三条不变量：
 *   - 请求只经 `window.HePanels.request`（本文件不自己碰 fetch，也不改 URL 之外的东西）；
 *   - 路径/请求体先在本地判定，不合法就只改状态行、不发请求；
 *   - 写方法（POST/PATCH/PUT/DELETE）在发请求**之前**过一次 `window.confirm`，取消即什么都不做。
 */
(() => {
  "use strict";

  /** 输出区字符上限：超出时显式标注总数（截断必须可见，绝不静默丢内容）。 */
  const MAX_OUTPUT_CHARS = 20000;

  /** 写方法集合：这些方法会改服务端状态，发请求前必须二次确认。 */
  const WRITE_METHODS = new Set(["POST", "PATCH", "PUT", "DELETE"]);

  /** 面板打开时的预填路径（最常用的只读入口）。 */
  const DEFAULT_PATH = "/api/projects";

  /** 预置端点：路径模板与后端路由常量同名，`{project_id}` / `{session_id}` 按当前选择填充。 */
  const PRESETS = [
    { method: "GET", path: "/api/health" },
    { method: "POST", path: "/api/runs" },
    { method: "DELETE", path: "/api/runs/{run_id}" },
    { method: "GET", path: "/api/runs/{run_id}/events" },
    { method: "GET", path: "/api/session" },
    { method: "GET", path: "/api/projects" },
    { method: "POST", path: "/api/projects" },
    { method: "PATCH", path: "/api/projects/{project_id}" },
    { method: "DELETE", path: "/api/projects/{project_id}" },
    { method: "GET", path: "/api/projects/{project_id}/sessions" },
    { method: "POST", path: "/api/projects/{project_id}/sessions" },
    { method: "GET", path: "/api/projects/{project_id}/sessions/{session_id}" },
    { method: "PATCH", path: "/api/projects/{project_id}/sessions/{session_id}" },
    { method: "DELETE", path: "/api/projects/{project_id}/sessions/{session_id}" },
    { method: "POST", path: "/api/projects/{project_id}/runs" },
    { method: "GET", path: "/api/projects/{project_id}/config" },
    { method: "PUT", path: "/api/projects/{project_id}/config" },
    { method: "POST", path: "/api/dialogs/pick-directory" },
    { method: "GET", path: "/api/tasks" },
    { method: "GET", path: "/api/tasks/{task_id}" },
    { method: "GET", path: "/api/status" },
  ];

  const el = {
    button: document.getElementById("api-button"),
    panel: document.getElementById("api-console"),
    form: document.getElementById("api-form"),
    method: document.getElementById("api-method"),
    path: document.getElementById("api-path"),
    body: document.getElementById("api-body"),
    send: document.getElementById("api-send"),
    presets: document.getElementById("api-presets"),
    status: document.getElementById("api-status"),
    output: document.getElementById("api-output"),
    close: document.getElementById("api-close"),
  };

  /** 状态行只承载一句事实；`data-state` 决定配色（idle / busy / done / failed / warning）。 */
  function setStatus(text, state) {
    el.status.textContent = text;
    el.status.dataset.state = state;
  }

  /** 响应区一律写纯文本；超长截断并标注原始长度。 */
  function setOutput(text) {
    if (text.length <= MAX_OUTPUT_CHARS) {
      el.output.textContent = text;
      return;
    }
    el.output.textContent = text.slice(0, MAX_OUTPUT_CHARS) + "\n…（已截断，共 " + text.length + " 字符）";
  }

  /** 面板公共桥：请求与「当前选择」都取自 panels.js，本文件不自己发 fetch。 */
  function bridge() {
    const panels = window.HePanels;
    if (!panels || typeof panels.request !== "function") return null;
    return panels;
  }

  /** 第一个 `{…}` 占位符（含花括号）；没有则回空串。占位符名与后端路由模板一致。 */
  function firstPlaceholder(path) {
    const open = path.indexOf("{");
    if (open === -1) return "";
    const close = path.indexOf("}", open);
    if (close === -1) return "";
    return path.slice(open, close + 1);
  }

  /** 确认文案说明即将发生什么；DELETE 未带 confirm=true 时点明服务端可能拒绝执行。 */
  function confirmText(method, path) {
    const head = "将向服务端发出 " + method + " " + path + "。";
    if (method === "DELETE" && path.indexOf("confirm=true") === -1) {
      return head + "\n这是删除操作：服务端可能要求 ?confirm=true 才会执行。";
    }
    return head + "\n继续吗？";
  }

  /** 响应体文本：对象/数组格式化缩进，字符串原样（服务端也可能回纯文本）。 */
  function payloadText(payload) {
    if (payload === null || payload === undefined) return "";
    if (typeof payload === "string") return payload;
    try {
      return JSON.stringify(payload, null, 2);
    } catch (error) {
      return String(payload);
    }
  }

  /** 渲染结果：首行状态码与耗时，其后是格式化后的响应体；一律 textContent。 */
  function renderResult(panels, result) {
    const status = String(result.status);
    const head = "HTTP " + status + " (" + String(result.elapsed) + " ms)";
    const text = payloadText(result.payload);
    setOutput(text ? head + "\n" + text : head);
    if (result.ok) {
      setStatus("请求完成：HTTP " + status, "done");
      return;
    }
    setStatus(panels.describeFailure(result), "failed");
  }

  /** 发送：本地判定 → 写方法确认 → 经面板桥发请求 → 渲染。 */
  async function send() {
    const panels = bridge();
    if (!panels) {
      setStatus("面板桥（panels.js）未加载：无法发请求", "failed");
      return;
    }
    const method = String(el.method.value || "GET").toUpperCase();
    const path = el.path.value.trim();
    const rawBody = el.body.value.trim();
    if (path.indexOf("/") !== 0) {
      setStatus("路径必须以 / 开头：只能请求本站同源端点", "failed");
      return;
    }
    const placeholder = firstPlaceholder(path);
    if (placeholder) {
      setStatus("路径里还有占位符 " + placeholder + "：请先换成真实 id", "failed");
      return;
    }
    let payload;
    if (rawBody) {
      try {
        payload = JSON.parse(rawBody);
      } catch (error) {
        setStatus("请求体不是合法 JSON：本次没有发出请求", "failed");
        return;
      }
    }
    // 写方法先确认：取消就到此为止，绝不把「再点一次发送」变成已执行的副作用。
    if (WRITE_METHODS.has(method) && !window.confirm(confirmText(method, path))) {
      setStatus("已取消：" + method + " " + path + " 没有发出请求", "idle");
      return;
    }
    setStatus("正在请求 " + method + " " + path, "busy");
    el.send.disabled = true;
    let result;
    try {
      result = await panels.request(method, path, payload);
    } catch (error) {
      el.output.textContent = "无法连接到服务";
      setStatus("无法连接到服务", "failed");
      return;
    } finally {
      el.send.disabled = false;
    }
    renderResult(panels, result);
  }

  /** 点预置按钮：只填方法 + 路径（不自动发送）；占位符按当前选择填充。 */
  function applyPreset(preset) {
    const panels = bridge();
    let path = preset.path;
    if (path.indexOf("{project_id}") !== -1) {
      const projectId = panels ? String(panels.activeProjectId() || "").trim() : "";
      if (!projectId) {
        setStatus("先选择项目：该端点属于某个项目", "warning");
        return;
      }
      path = path.split("{project_id}").join(encodeURIComponent(projectId));
    }
    if (path.indexOf("{session_id}") !== -1) {
      const sessionId = panels ? String(panels.activeSessionId() || "").trim() : "";
      if (!sessionId) {
        setStatus("先选择会话：该端点属于某个会话", "warning");
        return;
      }
      path = path.split("{session_id}").join(encodeURIComponent(sessionId));
    }
    el.method.value = preset.method;
    el.path.value = path;
    const rest = firstPlaceholder(path);
    if (rest) {
      setStatus("已填入路径：请把 " + rest + " 换成真实 id 再发送", "warning");
      return;
    }
    setStatus("已填入 " + preset.method + " " + path + "：点「发送」执行", "idle");
  }

  /** 预置按钮按路由清单静态生成一次（文本一律 textContent）。 */
  function buildPresets() {
    PRESETS.forEach((preset) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = preset.method + " " + preset.path;
      button.addEventListener("click", () => applyPreset(preset));
      el.presets.appendChild(button);
    });
  }

  /** 开合面板：`aria-expanded` 与 `hidden` 必须同步，键盘与读屏拿到同一个事实。 */
  function setOpen(open) {
    el.panel.hidden = !open;
    el.button.setAttribute("aria-expanded", open ? "true" : "false");
    if (!open) return;
    // 只在空白时预填：重开面板不覆盖用户已经输入的路径。
    if (!el.path.value.trim()) el.path.value = DEFAULT_PATH;
    el.path.focus();
  }

  el.button.addEventListener("click", () => setOpen(el.panel.hidden));
  el.close.addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !el.panel.hidden) {
      event.preventDefault();
      setOpen(false);
    }
  });
  el.form.addEventListener("submit", (event) => {
    event.preventDefault();
    void send();
  });

  buildPresets();
  // 深链：直接访问 `#api` 时启动即打开面板。
  if (String(window.location.hash || "") === "#api") setOpen(true);
})();
