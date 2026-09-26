/* HeAgent 内置网页脚本（Epic 49 的对话页 + Epic 50 的项目 / 会话 / 设置面板）。
 *
 * 约束（改这里前先读 docs/frame.md 4.17）：
 *   - 纯原生 JS：不加载、不依赖任何第三方脚本（严格 CSP 下也只允许同源 /app.js）；
 *   - 提示词、回答、工具名与工具输出、**配置值**一律按纯文本渲染（createTextNode / textContent），
 *     绝不使用 innerHTML —— Agent 输出与工作区里的 `.env` 都是不可信内容，HTML 注入会变成页面内
 *     的脚本执行；
 *   - 所有请求同源（页面与 /api/* 由同一个 ASGI app 提供），不配置 CORS、不带凭据；
 *   - 状态词表集中在 SERVICE_TEXT / RUN_TEXT / SOURCE_TEXT / ERROR_TEXT，UI 只映射服务端给出的事实，
 *     不自行推断「大概成功了」——运行终态一律等 SSE 的终态事件（或重新同步后的会话快照）；
 *   - **项目/会话的「当前选择」只是本页状态**（localStorage 里的一个 id）：切换项目不修改任何进程级
 *     状态、不改进程 cwd，也不取消既有运行；服务端每个请求都自带项目参数（脊柱 D2）。
 */
(() => {
  "use strict";

  const HEALTH_POLL_MS = 5000;
  const MAX_LOG_ENTRIES = 500;
  /** 面板里**展示**有效值的字符上限（超长显式标注，绝不静默截断）；编辑框里始终是完整值。 */
  const MAX_VALUE_CHARS = 400;
  /** localStorage 里只放「看哪个项目」这一个 UI 偏好，不放任何服务端状态。 */
  const SELECTION_KEY = "heagent.console.project_id";

  const SERVICE_TEXT = {
    connecting: "连接中…",
    ready: "服务就绪",
    offline: "服务不可达",
  };

  const RUN_TEXT = {
    idle: "空闲",
    starting: "提交中…",
    running: "运行中…",
    cancelling: "取消中…",
    reconnecting: "连接中断，正在重连…",
    done: "已完成",
    failed: "失败",
    disconnected: "连接已断开",
  };

  // 「忙」状态：这些状态下禁止重复提交（服务端也会回 run_conflict）。
  const BUSY_STATES = new Set(["starting", "running", "cancelling", "reconnecting"]);

  // 来源徽标（与 network.http_console_protocol.ConfigSourceValue 的取值一一对应）。
  const SOURCE_TEXT = {
    default: "默认值",
    global_env: "全局 .env",
    project_env: "项目 .env",
    system_env: "系统环境变量",
  };

  // 稳定错误码 → 中文文案（`HttpErrorCode` 闭集；未列出的码回落到服务端文案）。
  const ERROR_TEXT = {
    invalid_request: "请求不合法：服务端拒绝了这个请求。",
    empty_prompt: "提示词不能为空。",
    request_too_large: "请求体过大：请缩短提示词。",
    run_conflict: "该项目已有运行在进行：请等它结束，或先点「停止」。",
    unknown_run: "运行不存在或已结束。",
    unknown_project: "项目不存在或已被移除：请刷新项目列表。",
    invalid_project_path: "目录无效：必须是已存在的目录的绝对路径。",
    project_unavailable: "项目目录已失效（不存在或不可访问）：请重新登记或移除它。",
    project_not_removable: "默认项目（服务工作区）不能移除登记。",
    project_busy: "该项目有运行在进行：请等它结束或先停止，再移除登记。",
    project_limit_reached: "已登记项目数达到上限：请先移除一些项目。",
    unknown_session: "会话不存在或已被删除：请刷新会话列表。",
    invalid_session_id: "会话标识非法：服务端拒绝了这个请求。",
    session_conflict: "会话已被其它地方（CLI 或另一个页面）修改：请重新加载后再试。",
    session_busy: "该会话正被一次运行使用：请先停止或等它结束。",
    session_unreadable: "会话文件无法解析（这不是空会话）：请备份后删除它，不要继续往它上面写。",
    confirm_required: "服务端要求显式确认：本次操作没有执行。",
    loopback_required: "该操作只允许来自本机回环地址。",
    dialog_unavailable: "本机没有可用的图形目录选择器（或服务启动时禁用了它）：请手工填写目录的绝对路径。",
    dialog_busy: "已经有一个目录选择窗口开着：请先完成或关掉它，再点一次。",
    write_disabled: "服务启动时未开启配置写入（HTTP_CONSOLE_WRITE_ENABLED）：本次没有改动任何文件。",
    field_not_writable: "该键当前不可写（不在白名单，或被系统环境变量提供）：本次没有改动任何文件。",
    invalid_value: "值不合法：本次没有改动任何文件。",
    config_conflict: "项目 .env 已被外部修改（指纹不符）：面板已重新加载，请重新编辑后再保存。",
    config_write_failed: "写入失败：服务端已尝试恢复备份，请检查项目 .env 与 .env.lock。",
    resync_required: "事件游标已越出服务端缓存窗口：已改为重新同步。",
    rate_limited: "请求过于频繁：请稍后再试。",
    timeout: "请求超时。",
    origin_forbidden: "来源（Origin）不被接受：请用页面本身的地址访问。",
    not_found: "接口不存在（页面与服务端版本可能不匹配）。",
    method_not_allowed: "该接口不接受这种请求方法。",
    agent_error: "运行失败。",
    shutting_down: "服务正在关闭。",
    server_error: "服务端错误：详情只写进服务端日志。",
  };

  // 这些码的服务端文案带有可操作细节（字段级原因、重名条目…），值得一并显示。
  const DETAIL_CODES = new Set([
    "invalid_value",
    "field_not_writable",
    "invalid_project_path",
    "session_conflict",
    "project_limit_reached",
    "dialog_unavailable",
  ]);

  // 侧栏会话列表默认只渲染最近这么多条（服务端已按时间降序给出；展开是本地 slice，不再发请求）。
  const SESSION_VISIBLE_DEFAULT = 10;

  const el = {
    service: document.getElementById("service-status"),
    sidebarToggle: document.getElementById("sidebar-toggle"),
    settingsButton: document.getElementById("settings-button"),
    console: document.getElementById("console"),
    sidebar: document.getElementById("sidebar"),
    projectList: document.getElementById("project-list"),
    projectEmpty: document.getElementById("project-empty"),
    projectForm: document.getElementById("project-form"),
    projectPath: document.getElementById("project-path"),
    projectName: document.getElementById("project-name"),
    projectRegister: document.getElementById("project-register"),
    projectPick: document.getElementById("project-pick"),
    projectStatus: document.getElementById("project-status"),
    activeProject: document.getElementById("active-project"),
    sessionList: document.getElementById("session-list"),
    sessionEmpty: document.getElementById("session-empty"),
    sessionCount: document.getElementById("session-count"),
    sessionMore: document.getElementById("session-more"),
    sessionCreate: document.getElementById("session-create"),
    sessionStatus: document.getElementById("session-status"),
    chatTitle: document.getElementById("chat-title"),
    chatMeta: document.getElementById("chat-meta"),
    otherRunNote: document.getElementById("other-run-note"),
    log: document.getElementById("chat-log"),
    empty: document.getElementById("empty-state"),
    form: document.getElementById("prompt-form"),
    input: document.getElementById("prompt-input"),
    send: document.getElementById("send-button"),
    stop: document.getElementById("stop-button"),
    run: document.getElementById("run-status"),
    settingsPanel: document.getElementById("settings-panel"),
    settingsProject: document.getElementById("settings-project"),
    settingsStatus: document.getElementById("settings-status"),
    settingsGate: document.getElementById("settings-gate"),
    settingsResult: document.getElementById("settings-result"),
    settingsDiagnostics: document.getElementById("settings-diagnostics"),
    settingsDiagnosticsSummary: document.getElementById("settings-diagnostics-summary"),
    settingsGroups: document.getElementById("settings-groups"),
    unknownList: document.getElementById("unknown-keys"),
    unknownEmpty: document.getElementById("unknown-empty"),
    unknownSummary: document.getElementById("settings-unknown-summary"),
    settingsPending: document.getElementById("settings-pending"),
    settingsSave: document.getElementById("settings-save"),
    settingsRefresh: document.getElementById("settings-refresh"),
    settingsClose: document.getElementById("settings-close"),
    confirmOverlay: document.getElementById("confirm-overlay"),
    confirmTitle: document.getElementById("confirm-title"),
    confirmText: document.getElementById("confirm-text"),
    confirmInput: document.getElementById("confirm-input"),
    confirmInputLabel: document.getElementById("confirm-input-label"),
    confirmOk: document.getElementById("confirm-ok"),
    confirmCancel: document.getElementById("confirm-cancel"),
  };

  const state = {
    projects: [],
    activeProjectId: null,
    sessions: [],
    activeSessionId: null,
    sessionUnreadable: false,
    /** 会话列表是否展开显示全部（默认只渲染最近 SESSION_VISIBLE_DEFAULT 条）。 */
    sessionShowAll: false,
    /** 原生目录选择是否在途（按钮禁用用；原生窗口不能叠着开）。 */
    picking: false,
    runSessionId: null,
    activeRunId: null,
    runState: "idle",
    switching: false,
    sidebarCollapsed: false,
    settingsOpen: false,
    config: null,
    configProjectId: null,
    configInputs: new Map(),
    configOriginals: new Map(),
    saving: false,
    /** 离开某个仍在运行的项目时留下的提示（只断本页事件流，服务端运行继续）。 */
    otherRun: "",
  };

  let stream = null;
  let assistantEntry = null;
  const pendingToolEntries = new Map();

  /** 只把字符串交给 textContent；其它类型（数字/对象/undefined）一律折叠为可读文本。 */
  function asText(value) {
    if (typeof value === "string") return value;
    if (value === null || value === undefined) return "";
    return String(value);
  }

  function makeEl(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.appendChild(document.createTextNode(asText(text)));
    return node;
  }

  function makeButton(label, className) {
    const button = document.createElement("button");
    button.type = "button";
    if (className) button.className = className;
    button.appendChild(document.createTextNode(asText(label)));
    return button;
  }

  function clearChildren(node) {
    node.replaceChildren();
  }

  function setStatus(node, text, code) {
    node.textContent = asText(text);
    if (code !== undefined) node.dataset.state = code;
  }

  // ── 本地 UI 偏好（唯一用途：记住看哪个项目；绝不写任何服务端状态） ──

  function storageGet(key) {
    try {
      return asText(window.localStorage.getItem(key)) || null;
    } catch (error) {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, asText(value));
    } catch (error) {
      /* 隐私模式等场景下不可用：选择只是本页便利，失败无影响。 */
    }
  }

  // ── 状态反馈（UX-DR3/DR4/DR5 的可见出口） ──

  function setServiceState(code) {
    el.service.dataset.state = code;
    el.service.textContent = SERVICE_TEXT[code] || SERVICE_TEXT.connecting;
  }

  function setRunState(code, text) {
    state.runState = code;
    el.run.dataset.state = code;
    el.run.textContent = text || RUN_TEXT[code] || code;
    refreshComposer();
  }

  /** 提交/取消按钮的可用性：**忙**（有在途运行）或**被挡住**（项目失效 / 会话不可读）都禁用并给原因。 */
  function refreshComposer() {
    const busy = BUSY_STATES.has(state.runState);
    const blocked = runBlockReason();
    el.input.disabled = busy || blocked !== null;
    el.send.disabled = busy || blocked !== null;
    el.stop.disabled = !(state.runState === "running" || state.runState === "reconnecting");
    if (busy) return; // 忙态文案由 setRunState 决定（「运行中…」「取消中…」…）
    if (blocked !== null) {
      el.run.dataset.state = "failed";
      el.run.textContent = blocked;
    } else if (state.runState === "idle") {
      // 阻塞消失后不留旧文案（例如「正在切换项目…」在切换结束后必须回到「空闲」）。
      el.run.dataset.state = "idle";
      el.run.textContent = RUN_TEXT.idle;
    }
  }

  /** 现在能不能起新运行；不能则返回**可读原因**（不静默禁用）。 */
  function runBlockReason() {
    if (state.switching) return "正在切换项目…";
    const project = activeProject();
    if (!project) return "请先选择项目";
    if (!project.available) return "项目目录已失效：请重新登记或移除该项目";
    if (state.sessionUnreadable) return "当前会话不可读：请先处理或删除该文件";
    return null;
  }

  function activeProject() {
    return state.projects.find((item) => item.id === state.activeProjectId) || null;
  }

  function projectName(projectId) {
    const project = state.projects.find((item) => item.id === projectId);
    return project ? project.name : asText(projectId);
  }

  function sessionTitle(sessionId) {
    const session = state.sessions.find((item) => item.session_id === sessionId);
    return session ? session.title : "";
  }

  function formatTime(value) {
    const text = asText(value);
    if (!text) return "";
    const when = new Date(text);
    if (Number.isNaN(when.getTime())) return text;
    return when.toLocaleString();
  }

  // ── 二次确认（危险操作与配置写入的唯一入口） ──

  let confirmPending = null;

  function askConfirm(options) {
    return new Promise((resolve) => {
      const wantsInput = Boolean(options.input);
      // 同一时刻只允许一个确认框：被顶掉的那个**以「取消」结算**，绝不留下悬着的 promise
      // （悬着 = 那次危险操作既没执行也不会走到后面的代码，未来任何 `await askConfirm` 之后
      // 的分支都会静默不执行 —— 与 49 的「忙时不静默」同一条纪律）。
      if (confirmPending) settleConfirm(false);
      confirmPending = { resolve, wantsInput };
      el.confirmTitle.textContent = asText(options.title) || "请确认";
      el.confirmText.textContent = asText(options.text);
      el.confirmOk.textContent = asText(options.okText) || "确认";
      el.confirmInput.hidden = !wantsInput;
      el.confirmInputLabel.hidden = !wantsInput;
      el.confirmInput.value = wantsInput ? asText(options.input.value) : "";
      el.confirmInput.maxLength = wantsInput ? Number(options.input.maxLength) || 120 : 120;
      el.confirmOverlay.hidden = false;
      if (wantsInput) el.confirmInput.focus();
      else el.confirmOk.focus();
    });
  }

  function settleConfirm(confirmed) {
    const pending = confirmPending;
    confirmPending = null;
    // 先隐藏遮罩、再处理 pending：用户点了「取消 / 确认」，遮罩就必须消失。
    // 否则一旦出现「遮罩可见但没有 pending」的组合，两个按钮会永久失效（只能靠刷新页面脱身）。
    el.confirmOverlay.hidden = true;
    if (!pending) return;
    const value = pending.wantsInput ? asText(el.confirmInput.value) : "";
    pending.resolve({ confirmed, value });
  }

  el.confirmOk.addEventListener("click", () => settleConfirm(true));
  el.confirmCancel.addEventListener("click", () => settleConfirm(false));
  el.confirmOverlay.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      settleConfirm(false);
    }
  });
  if (typeof document.addEventListener === "function") {
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && confirmPending) {
        event.preventDefault();
        settleConfirm(false);
      }
    });
  }

  // ── 错误映射（稳定码 → 可理解文案；文案里的 HTML 永远不会被解析） ──

  async function readError(response) {
    try {
      const payload = await response.json();
      const detail = payload && payload.error ? payload.error : {};
      return { code: asText(detail.code), message: asText(detail.message), status: response.status };
    } catch (error) {
      return { code: "", message: "", status: response.status };
    }
  }

  function describeError(failure) {
    const code = asText(failure && failure.code);
    const message = asText(failure && failure.message);
    const mapped = ERROR_TEXT[code];
    if (!mapped) {
      if (message) return message;
      return `请求被拒绝（HTTP ${asText(failure && failure.status) || "?"}）`;
    }
    if (message && DETAIL_CODES.has(code)) return `${mapped} 服务端说明：${message}`;
    return mapped;
  }

  // ── 对话区（Epic 49 的行为原样保留：流式文本、工具活动、停止、重连） ──

  function appendEntry(kind, text) {
    const item = document.createElement("li");
    item.className = "entry entry-" + kind;
    if (kind === "tool") item.dataset.error = "false";
    item.appendChild(document.createTextNode(asText(text)));
    el.log.appendChild(item);
    while (el.log.children.length > MAX_LOG_ENTRIES) {
      el.log.removeChild(el.log.firstChild);
    }
    el.empty.hidden = el.log.children.length > 0;
    el.log.scrollTop = el.log.scrollHeight;
    return item;
  }

  function appendText(node, text) {
    node.appendChild(document.createTextNode(asText(text)));
    el.log.scrollTop = el.log.scrollHeight;
  }

  function showToolCall(payload) {
    const target = asText(payload.tool_target);
    const label = target ? `${asText(payload.tool_name)} → ${target}` : asText(payload.tool_name);
    // 同一工具名会被连续/并发调用多次（工具结果事件里没有 call id），所以按「先到先配」排队：
    // 用「一名一条队列」而不是「一名一条」，否则后一次调用会覆盖前一次的条目，
    // 结果被写到错误的行上、前一行永远停在「运行中」。
    const key = asText(payload.tool_name);
    const node = appendEntry("tool", `▶ ${label}`);
    // 结果事件不带作用对象，而 Story 50-8 R5 要求「不显示读取内容」时仍能看到**读了哪个文件**，
    // 所以把作用对象留在条目节点上，结果行复用它（不新增第二处箭头拼接）。
    node.dataset.toolTarget = target;
    const queue = pendingToolEntries.get(key);
    if (queue) {
      queue.push(node);
    } else {
      pendingToolEntries.set(key, [node]);
    }
  }

  function showToolResult(payload) {
    const key = asText(payload.tool_name);
    const queue = pendingToolEntries.get(key);
    const entry = queue && queue.length ? queue.shift() : null;
    if (queue && queue.length === 0) pendingToolEntries.delete(key);
    const isError = Boolean(payload.tool_error);
    const output = asText(payload.tool_output);
    const target = entry ? asText(entry.dataset.toolTarget) : "";
    // 无内容 = 服务端对读取类工具做了收敛（R5）：这时改显示「工具名 → 作用对象」，避免退化成空行；
    // 有内容时维持既有格式（`✔ 工具名：输出`），其它工具因此零变化。
    const line = output
      ? `${isError ? "✘" : "✔"} ${key}：${output}`
      : `${isError ? "✘" : "✔"} ${key}${target ? ` → ${target}` : ""}`;
    const node = entry || appendEntry("tool", line);
    node.dataset.error = isError ? "true" : "false";
    if (entry) node.textContent = line;
    el.log.scrollTop = el.log.scrollHeight;
  }

  function clearChat() {
    el.log.replaceChildren();
    el.empty.hidden = false;
    assistantEntry = null;
    pendingToolEntries.clear();
  }

  function closeStream() {
    if (stream) {
      stream.close();
      stream = null;
    }
    state.activeRunId = null;
    state.runSessionId = null;
    assistantEntry = null;
    pendingToolEntries.clear();
  }

  /** 离开「正在运行的会话」所在的项目/会话：只断**本页**事件流，绝不取消服务端运行。 */
  function detachRun(reason) {
    if (!state.activeRunId) return;
    closeStream();
    setRunState("idle");
    state.otherRun = `${reason}：本页已断开它的实时流（断线不会取消运行），切回该会话即可重新接手。`;
    renderOtherRunNote();
  }

  function renderOtherRunNote() {
    el.otherRunNote.hidden = !state.otherRun;
    el.otherRunNote.textContent = state.otherRun;
  }

  function finishRun(code, text) {
    closeStream();
    setRunState(code, text);
    void refreshSessionList();
  }

  function handleEvent(payload) {
    switch (payload && payload.kind) {
      case "text":
        if (!assistantEntry) assistantEntry = appendEntry("assistant", "");
        appendText(assistantEntry, payload.text);
        break;
      case "tool_call":
        showToolCall(payload);
        break;
      case "tool_result":
        showToolResult(payload);
        break;
      case "done":
        if (!assistantEntry && payload.text) assistantEntry = appendEntry("assistant", payload.text);
        finishRun("done");
        break;
      case "error":
        appendEntry("error", asText(payload.message) || "运行失败");
        finishRun("failed");
        break;
      case "cancelled":
        appendEntry("error", asText(payload.message) || "已取消");
        finishRun("failed", "已取消");
        break;
      case "timed_out":
        appendEntry("error", asText(payload.message) || "运行超时");
        finishRun("failed", "运行超时");
        break;
      default:
        // 未知事件类型不猜语义（服务端新增事件时旧页面保持可用，只忽略）。
        break;
    }
  }

  function subscribe(runId) {
    stream = new EventSource(`/api/runs/${runId}/events`);
    const kinds = ["text", "tool_call", "tool_result", "done", "error", "cancelled", "timed_out"];
    for (const kind of kinds) {
      stream.addEventListener(kind, (event) => {
        let payload = null;
        try {
          payload = JSON.parse(event.data);
        } catch (error) {
          payload = null;
        }
        handleEvent(payload);
      });
    }
    stream.addEventListener("error", () => {
      if (!stream) return;
      // EventSource 会在连接断开时自动重连（并带上 Last-Event-ID）；服务端对越过缓存窗口的
      // 游标回 409，浏览器无法读到该响应体，所以这里统一「如实显示重连中 + 拉一次会话快照」：
      // 若服务端已终结或事件已淘汰，快照会告诉我们真实状态，页面据此收敛而不是无限重试。
      setRunState("reconnecting");
      void resyncFromSession();
    });
  }

  async function resyncFromSession() {
    const runId = state.activeRunId;
    const projectId = state.activeProjectId;
    const sessionId = state.runSessionId;
    if (!runId || !projectId || !sessionId) return;
    let snapshot;
    try {
      const response = await fetch(sessionUrl(projectId, sessionId), { headers: { accept: "application/json" } });
      if (!response.ok) return;
      snapshot = await response.json();
    } catch (error) {
      return; // 服务不可达：保持「重连中」，由 EventSource 继续尝试。
    }
    if (state.activeRunId !== runId) return; // 已经切到别的运行，别用旧快照覆盖。
    const terminal = ["completed", "failed", "cancelled", "timed_out"].includes(snapshot.status);
    if (terminal || snapshot.run_id !== runId) {
      closeStream();
      appendEntry("error", "连接中断后已与服务端重新同步（可能有事件未送达）。");
      if (snapshot.status === "completed") await loadSessionDetail(sessionId);
      // 文案要与服务端事实一致：completed 就是「已完成」，不能让状态词表里的「失败」顶上去。
      const code = snapshot.status === "completed" ? "done" : "failed";
      setRunState(code, RUN_TEXT[code]);
      void refreshSessionList();
    }
  }

  function sessionUrl(projectId, sessionId) {
    return `/api/projects/${encodeURIComponent(projectId)}/sessions/${encodeURIComponent(sessionId)}`;
  }

  function sessionsUrl(projectId) {
    return `/api/projects/${encodeURIComponent(projectId)}/sessions`;
  }

  function configUrl(projectId) {
    return `/api/projects/${encodeURIComponent(projectId)}/config`;
  }

  function runsUrl(projectId) {
    return `/api/projects/${encodeURIComponent(projectId)}/runs`;
  }

  // ── 项目层（T3） ──

  function renderProjects() {
    clearChildren(el.projectList);
    el.projectEmpty.hidden = state.projects.length > 0;
    for (const project of state.projects) {
      const item = makeEl("li", "list-item");
      item.dataset.projectId = project.id;
      item.dataset.available = project.available ? "true" : "false";
      if (project.id === state.activeProjectId) {
        item.dataset.active = "true";
        item.setAttribute("aria-current", "true");
      }
      const select = makeButton(project.name, "list-button");
      select.addEventListener("click", () => void selectProject(project.id));
      item.appendChild(select);

      const meta = makeEl("div", "item-meta");
      meta.appendChild(makeEl("span", "item-path", project.path));
      if (project.is_default) meta.appendChild(makeEl("span", "badge", "服务工作区"));
      if (!project.available) {
        const flag = makeEl("span", "badge badge-unavailable", "目录已失效");
        flag.dataset.available = "false";
        meta.appendChild(flag);
      }
      if (project.last_opened_at) meta.appendChild(makeEl("span", null, `最近打开 ${formatTime(project.last_opened_at)}`));
      item.appendChild(meta);

      const actions = makeEl("div", "item-actions");
      const rename = makeButton("重命名");
      rename.addEventListener("click", () => void renameProject(project.id));
      actions.appendChild(rename);
      if (!project.is_default) {
        const remove = makeButton("移除登记", "danger");
        remove.addEventListener("click", () => void removeProject(project.id));
        actions.appendChild(remove);
      }
      item.appendChild(actions);
      el.projectList.appendChild(item);
    }
    el.activeProject.textContent = activeProject() ? asText(activeProject().name) : "未选择项目";
  }

  async function loadProjects() {
    let response;
    try {
      response = await fetch("/api/projects", { headers: { accept: "application/json" } });
    } catch (error) {
      setStatus(el.projectStatus, "无法连接到服务", "failed");
      return null;
    }
    if (!response.ok) {
      setStatus(el.projectStatus, describeError(await readError(response)), "failed");
      return null;
    }
    const payload = await response.json();
    state.projects = Array.isArray(payload.projects) ? payload.projects : [];
    renderProjects();
    return state.projects;
  }

  /** 切换项目：**只改本页状态**（服务端每个请求都自带项目参数，进程状态一律不动）。 */
  async function selectProject(projectId, options) {
    const force = Boolean(options && options.force);
    if (state.switching && !force) return;
    const project = state.projects.find((item) => item.id === projectId);
    if (!project) return;
    if (projectId === state.activeProjectId && !force) return;
    // 先清掉上一次的「别的项目还在跑」提示，再按本次是否需要「脱离」重新置上（顺序反了会把刚设的提示抹掉）。
    state.otherRun = "";
    renderOtherRunNote();
    if (state.activeRunId) detachRun(`项目「${projectName(state.activeProjectId)}」的一个运行仍在继续`);
    state.activeProjectId = projectId;
    state.activeSessionId = null;
    state.sessionUnreadable = false;
    state.sessions = [];
    state.sessionShowAll = false; // 切项目回到「只显示最近 N 条」的默认（截断是每项目的视图状态）
    storageSet(SELECTION_KEY, projectId);
    renderProjects();
    renderSessions();
    clearChat();
    setStatus(el.chatMeta, "", "idle");
    el.chatTitle.textContent = "未选择会话";

    state.switching = true;
    el.projectRegister.disabled = true;
    el.sessionCreate.disabled = true;
    setStatus(el.sessionStatus, `正在切换到「${project.name}」…`, "busy");
    refreshComposer();
    try {
      await loadSessions(projectId);
      await restoreSession();
    } finally {
      state.switching = false;
      el.projectRegister.disabled = false;
      el.sessionCreate.disabled = false;
      setStatus(el.sessionStatus, "", "idle");
      refreshComposer();
    }
    if (state.settingsOpen) await loadConfig();
  }

  async function registerProject(event) {
    event.preventDefault();
    const path = asText(el.projectPath.value).trim();
    if (!path) {
      setStatus(el.projectStatus, "请填写目录的绝对路径", "failed");
      return;
    }
    const name = asText(el.projectName.value).trim();
    const body = { path };
    if (name) body.name = name;
    setStatus(el.projectStatus, "正在登记…", "busy");
    el.projectRegister.disabled = true;
    let response;
    try {
      response = await fetch("/api/projects", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (error) {
      el.projectRegister.disabled = false;
      setStatus(el.projectStatus, "无法连接到服务", "failed");
      return;
    }
    el.projectRegister.disabled = false;
    if (!response.ok) {
      setStatus(el.projectStatus, describeError(await readError(response)), "failed");
      return;
    }
    const entry = await response.json();
    el.projectPath.value = "";
    el.projectName.value = "";
    await loadProjects();
    setStatus(el.projectStatus, `已登记「${asText(entry.name)}」`, "done");
    await selectProject(entry.id);
  }

  /**
   * 「选择文件夹…」：请**服务端所在机器**弹出原生目录选择窗口（Story 50-8 R2）。
   *
   * 页面拿不到本机路径（浏览器没有这个能力），所以这一步只能由服务端做；选中后填入既有路径输入框，
   * 之后仍走**同一套** `POST /api/projects` 校验（选择器不是权限）。取消/超时按「没选」处理，
   * 后端不可用时把原因说清楚（本机无图形界面 / 服务启动时用了 `--dialog-backend none`）。
   */
  async function pickProjectDirectory() {
    if (state.picking) return;
    state.picking = true;
    el.projectPick.disabled = true;
    el.projectRegister.disabled = true;
    setStatus(el.projectStatus, "已在服务端打开目录选择窗口…", "busy");
    let response;
    try {
      response = await fetch("/api/dialogs/pick-directory", { method: "POST" });
    } catch (error) {
      state.picking = false;
      el.projectPick.disabled = false;
      el.projectRegister.disabled = false;
      setStatus(el.projectStatus, "无法连接到服务", "failed");
      return;
    }
    state.picking = false;
    el.projectPick.disabled = false;
    el.projectRegister.disabled = false;
    if (!response.ok) {
      setStatus(el.projectStatus, describeError(await readError(response)), "failed");
      return;
    }
    const payload = await response.json();
    const path = asText(payload.path);
    if (!path) {
      setStatus(el.projectStatus, "没有选择目录（已取消或等待超时）", "idle");
      return;
    }
    el.projectPath.value = path;
    setStatus(el.projectStatus, `已选中：${path}（确认无误后点「登记项目」）`, "done");
  }

  async function renameProject(projectId) {
    const project = state.projects.find((item) => item.id === projectId);
    if (!project) return;
    const answer = await askConfirm({
      title: "重命名项目",
      text: "输入新的显示名（1–64 字符）。只改本页显示的称呼：不改目录名，也不改项目身份（id）。",
      input: { value: project.name, maxLength: 64 },
      okText: "保存名称",
    });
    if (!answer.confirmed) return;
    const name = answer.value.trim();
    if (!name) {
      setStatus(el.projectStatus, "显示名不能为空", "failed");
      return;
    }
    let response;
    try {
      response = await fetch(`/api/projects/${encodeURIComponent(projectId)}`, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name }),
      });
    } catch (error) {
      setStatus(el.projectStatus, "无法连接到服务", "failed");
      return;
    }
    if (!response.ok) {
      setStatus(el.projectStatus, describeError(await readError(response)), "failed");
      return;
    }
    await loadProjects();
    setStatus(el.projectStatus, `已重命名为「${name}」`, "done");
  }

  async function removeProject(projectId) {
    const project = state.projects.find((item) => item.id === projectId);
    if (!project) return;
    if (project.is_default) {
      setStatus(el.projectStatus, ERROR_TEXT.project_not_removable, "failed");
      return;
    }
    const answer = await askConfirm({
      title: `移除项目登记：${project.name}`,
      text:
        `影响范围：只移除这条登记，磁盘目录与其中的数据保持不变` +
        `（${project.path} 下的 .heagent/ 会话、记忆、技能都还在）。\n` +
        "移除后本页会切回服务工作区项目。",
      okText: "移除登记",
    });
    if (!answer.confirmed) return;
    let response;
    try {
      response = await fetch(`/api/projects/${encodeURIComponent(projectId)}?confirm=true`, { method: "DELETE" });
    } catch (error) {
      setStatus(el.projectStatus, "无法连接到服务", "failed");
      return;
    }
    if (!response.ok) {
      setStatus(el.projectStatus, describeError(await readError(response)), "failed");
      return;
    }
    await loadProjects();
    setStatus(el.projectStatus, `已移除登记「${project.name}」`, "done");
    if (state.activeProjectId === projectId) {
      const fallback = state.projects.find((item) => item.is_default) || state.projects[0];
      if (fallback) await selectProject(fallback.id, { force: true });
    }
  }

  // ── 会话层（T4） ──

  function renderSessions() {
    clearChildren(el.sessionList);
    el.sessionEmpty.hidden = state.sessions.length > 0;
    const total = state.sessions.length;
    const activeIndex = state.sessions.findIndex((item) => item.session_id === state.activeSessionId);
    // 截断规则（R1）：默认只渲染最近 N 条；**当前选中的会话永远可见**——它落在窗口之外时自动展开
    // 并把展开按钮藏起来（按钮点了也不会收起，留着只会误导），展开状态因此不会出现「点了没反应」。
    const overflows = total > SESSION_VISIBLE_DEFAULT;
    const autoExpanded = activeIndex >= SESSION_VISIBLE_DEFAULT;
    const visible = state.sessionShowAll || autoExpanded ? state.sessions : state.sessions.slice(0, SESSION_VISIBLE_DEFAULT);
    for (const session of visible) {
      const item = makeEl("li", "list-item");
      item.dataset.sessionId = session.session_id;
      item.dataset.unreadable = session.unreadable ? "true" : "false";
      if (session.session_id === state.activeSessionId) {
        item.dataset.active = "true";
        item.setAttribute("aria-current", "true");
      }
      const select = makeButton(session.title, "list-button");
      select.addEventListener("click", () => void selectSession(session.session_id));
      item.appendChild(select);

      const meta = makeEl("div", "item-meta");
      meta.appendChild(
        makeEl("span", null, typeof session.message_count === "number" ? `${session.message_count} 条消息` : "消息数未统计"),
      );
      if (session.updated_at) meta.appendChild(makeEl("span", null, formatTime(session.updated_at)));
      if (session.unreadable) {
        const flag = makeEl("span", "badge badge-unreadable", "无法解析");
        flag.dataset.unreadable = "true";
        meta.appendChild(flag);
      }
      item.appendChild(meta);

      const actions = makeEl("div", "item-actions");
      const rename = makeButton("重命名");
      rename.addEventListener("click", () => void renameSession(session.session_id));
      actions.appendChild(rename);
      const remove = makeButton("删除", "danger");
      remove.addEventListener("click", () => void deleteSession(session.session_id));
      actions.appendChild(remove);
      item.appendChild(actions);
      el.sessionList.appendChild(item);
    }
    renderSessionCount(total, overflows, autoExpanded);
  }

  /** 列表规模提示 + 展开/收起按钮（R1：默认只显示最近 `SESSION_VISIBLE_DEFAULT` 条，超出部分可展开）。 */
  function renderSessionCount(total, overflows, autoExpanded) {
    const expanded = state.sessionShowAll || autoExpanded;
    if (!overflows) {
      el.sessionCount.textContent = total ? `共 ${total} 个会话` : "";
      el.sessionCount.dataset.state = "idle";
    } else {
      el.sessionCount.textContent = expanded
        ? autoExpanded && !state.sessionShowAll
          ? `共 ${total} 个会话（当前会话不在最近 ${SESSION_VISIBLE_DEFAULT} 条内，已展开）`
          : `共 ${total} 个会话（已展开）`
        : `共 ${total} 个会话 · 只显示最近 ${SESSION_VISIBLE_DEFAULT} 条`;
      el.sessionCount.dataset.state = "idle";
    }
    el.sessionMore.hidden = !overflows || autoExpanded;
    el.sessionMore.textContent = state.sessionShowAll ? `只看最近 ${SESSION_VISIBLE_DEFAULT} 条` : `显示全部（${total}）`;
  }

  async function loadSessions(projectId) {
    let response;
    try {
      response = await fetch(sessionsUrl(projectId), { headers: { accept: "application/json" } });
    } catch (error) {
      return;
    }
    if (!response.ok) {
      if (projectId === state.activeProjectId) {
        setStatus(el.sessionStatus, describeError(await readError(response)), "failed");
      }
      return;
    }
    const payload = await response.json();
    if (projectId !== state.activeProjectId) return; // 期间已切走：不把别的项目的会话画到这儿
    state.sessions = Array.isArray(payload.sessions) ? payload.sessions : [];
    renderSessions();
    if (state.activeSessionId && !state.sessions.some((item) => item.session_id === state.activeSessionId)) {
      state.activeSessionId = null;
    }
  }

  /** 载入当前项目的「当前会话」（存在则沿用，否则取最近一个可读会话）——刷新后可继续对话。 */
  async function restoreSession() {
    const projectId = state.activeProjectId;
    if (!projectId) return;
    let sessionId = state.activeSessionId;
    if (sessionId && !state.sessions.some((item) => item.session_id === sessionId)) sessionId = null;
    if (!sessionId) {
      const usable = state.sessions.find((item) => !item.unreadable);
      sessionId = usable ? usable.session_id : null;
    }
    state.activeSessionId = sessionId;
    state.sessionUnreadable = false;
    renderSessions();
    if (!sessionId) {
      el.chatTitle.textContent = "未选择会话";
      setStatus(el.chatMeta, state.sessions.length ? "该项目只有无法解析的会话" : "还没有会话：提交提示词会自动新建一个", "idle");
      refreshComposer();
      return;
    }
    await loadSessionDetail(sessionId);
  }

  async function selectSession(sessionId) {
    if (state.switching) return;
    if (sessionId === state.activeSessionId && !state.sessionUnreadable) return;
    if (state.activeRunId) detachRun(`会话「${sessionTitle(state.activeSessionId) || state.activeSessionId}」的运行仍在继续`);
    state.activeSessionId = sessionId;
    state.sessionUnreadable = false;
    renderSessions();
    await loadSessionDetail(sessionId);
  }

  async function loadSessionDetail(sessionId) {
    const projectId = state.activeProjectId;
    if (!projectId) return;
    let response;
    try {
      response = await fetch(sessionUrl(projectId, sessionId), { headers: { accept: "application/json" } });
    } catch (error) {
      appendEntry("error", "无法连接到服务");
      return;
    }
    if (projectId !== state.activeProjectId || sessionId !== state.activeSessionId) return;
    if (!response.ok) {
      const failure = await readError(response);
      if (failure.code === "session_unreadable") {
        // 关键区分（T4/D1）：文件损坏 ≠ 空会话。绝不在这里显示成空对话或允许继续写。
        clearChat();
        state.sessionUnreadable = true;
        el.chatTitle.textContent = sessionTitle(sessionId) || sessionId;
        appendEntry("error", "该会话文件无法解析（这不是空会话）：请先用编辑器或 CLI 检查、备份后删除它。");
        setStatus(el.chatMeta, "会话文件无法解析", "failed");
        refreshComposer();
        return;
      }
      appendEntry("error", describeError(failure));
      setStatus(el.chatMeta, "", "idle");
      return;
    }
    const detail = await response.json();
    renderChat(detail);
  }

  function renderChat(detail) {
    clearChat();
    el.chatTitle.textContent = asText(detail.title) || asText(detail.session_id);
    const messages = Array.isArray(detail.messages) ? detail.messages : [];
    for (const message of messages) {
      appendEntry(message.role === "user" ? "user" : "assistant", message.text);
    }
    const parts = [];
    if (typeof detail.version === "number") parts.push(`版本 ${detail.version}`);
    if (detail.messages_truncated) parts.push(`只显示最后 ${messages.length} 条消息（更早的仍在会话文件里）`);
    setStatus(el.chatMeta, parts.join(" · "), "idle");
    // 服务端仍有在途运行时不能显示「空闲」：接手它的事件流（终态仍由 SSE 给出），
    // 否则用户以为可以提交，实际只会收到 run_conflict。
    if (detail.status === "running" && detail.run_id) {
      closeStream();
      state.activeRunId = detail.run_id;
      state.runSessionId = detail.session_id;
      setRunState("running");
      subscribe(detail.run_id);
    } else {
      setRunState("idle");
    }
  }

  async function createSession() {
    const projectId = state.activeProjectId;
    if (!projectId || state.switching) return;
    el.sessionCreate.disabled = true;
    setStatus(el.sessionStatus, "正在新建会话…", "busy");
    let response;
    try {
      response = await fetch(sessionsUrl(projectId), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({}),
      });
    } catch (error) {
      el.sessionCreate.disabled = false;
      setStatus(el.sessionStatus, "无法连接到服务", "failed");
      return;
    }
    el.sessionCreate.disabled = false;
    if (!response.ok) {
      setStatus(el.sessionStatus, describeError(await readError(response)), "failed");
      return;
    }
    const entry = await response.json();
    if (projectId !== state.activeProjectId) return;
    await loadSessions(projectId);
    state.activeSessionId = entry.session_id;
    state.sessionUnreadable = false;
    renderSessions();
    await loadSessionDetail(entry.session_id);
    setStatus(el.sessionStatus, `已新建会话「${asText(entry.title)}」`, "done");
  }

  async function renameSession(sessionId) {
    const projectId = state.activeProjectId;
    const session = state.sessions.find((item) => item.session_id === sessionId);
    if (!projectId || !session) return;
    const answer = await askConfirm({
      title: "重命名会话",
      text: "输入新的标题（1–120 字符）。只改标题，不改对话内容。",
      input: { value: session.title, maxLength: 120 },
      okText: "保存标题",
    });
    if (!answer.confirmed) return;
    const title = answer.value.trim();
    if (!title) {
      setStatus(el.sessionStatus, "标题不能为空", "failed");
      return;
    }
    let response;
    try {
      response = await fetch(sessionUrl(projectId, sessionId), {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title, fingerprint: session.version }),
      });
    } catch (error) {
      setStatus(el.sessionStatus, "无法连接到服务", "failed");
      return;
    }
    if (!response.ok) {
      const failure = await readError(response);
      setStatus(el.sessionStatus, describeError(failure), "failed");
      if (failure.code === "session_conflict") await loadSessions(projectId);
      return;
    }
    await loadSessions(projectId);
    if (sessionId === state.activeSessionId) el.chatTitle.textContent = title;
    setStatus(el.sessionStatus, `已重命名为「${title}」`, "done");
  }

  async function deleteSession(sessionId) {
    const projectId = state.activeProjectId;
    const session = state.sessions.find((item) => item.session_id === sessionId);
    if (!projectId || !session) return;
    const answer = await askConfirm({
      title: `删除会话：${session.title}`,
      text:
        `影响范围：删除该会话文件（${session.session_id}.json），这段对话历史不可恢复。\n` +
        "项目本身与其它会话不受影响；正在被运行使用的会话会被服务端拒绝删除。",
      okText: "删除会话",
    });
    if (!answer.confirmed) return;
    let response;
    try {
      response = await fetch(`${sessionUrl(projectId, sessionId)}?confirm=true`, { method: "DELETE" });
    } catch (error) {
      setStatus(el.sessionStatus, "无法连接到服务", "failed");
      return;
    }
    if (!response.ok) {
      setStatus(el.sessionStatus, describeError(await readError(response)), "failed");
      return;
    }
    if (sessionId === state.activeSessionId) {
      state.activeSessionId = null;
      state.sessionUnreadable = false;
      clearChat();
      el.chatTitle.textContent = "未选择会话";
    }
    await loadSessions(projectId);
    setStatus(el.sessionStatus, `已删除会话「${session.title}」`, "done");
    await restoreSession();
  }

  /** 运行结束后刷新侧栏：标题由首条用户消息派生、最近排序会变（会话文件是唯一权威）。 */
  async function refreshSessionList() {
    const projectId = state.activeProjectId;
    if (!projectId) return;
    await loadSessions(projectId);
  }

  // ── 提交与取消 ──

  async function submitPrompt(prompt) {
    const projectId = state.activeProjectId;
    if (!projectId) return;
    const createdNewSession = !state.activeSessionId;
    state.otherRun = "";
    renderOtherRunNote();
    setRunState("starting");
    appendEntry("user", prompt);
    const body = { prompt };
    if (state.activeSessionId) body.session_id = state.activeSessionId;
    let response;
    try {
      response = await fetch(runsUrl(projectId), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (error) {
      appendEntry("error", "无法连接到服务");
      setRunState("failed");
      return;
    }
    if (!response.ok) {
      appendEntry("error", describeError(await readError(response)));
      setRunState("failed");
      return;
    }
    const created = await response.json();
    if (projectId !== state.activeProjectId) return; // 期间切走了：运行仍归属原项目（不取消）
    if (created.session_id) state.activeSessionId = created.session_id;
    state.activeRunId = created.run_id;
    state.runSessionId = created.session_id || state.activeSessionId;
    setRunState("running");
    subscribe(created.run_id);
    if (createdNewSession) await refreshSessionList();
  }

  async function cancelRun() {
    const runId = state.activeRunId;
    if (!runId) return;
    setRunState("cancelling");
    try {
      const response = await fetch(`/api/runs/${runId}`, { method: "DELETE" });
      if (!response.ok) {
        appendEntry("error", describeError(await readError(response)));
        setRunState("failed");
        return;
      }
      // 成功时不在这里宣布结果：终态由 SSE 的 `cancelled` 事件给出（服务端是唯一事实源）。
    } catch (error) {
      appendEntry("error", "无法连接到服务");
      setRunState("disconnected");
    }
  }

  // ── 设置面板（T5 / T6） ──

  function setSettingsOpen(open) {
    state.settingsOpen = open;
    el.settingsPanel.hidden = !open;
    el.console.dataset.settingsOpen = open ? "true" : "false";
    el.settingsButton.setAttribute("aria-expanded", open ? "true" : "false");
    el.settingsButton.textContent = open ? "关闭设置" : "设置";
    if (open) {
      if (state.config && state.configProjectId === state.activeProjectId) renderConfig();
      else void loadConfig();
    }
  }

  async function loadConfig() {
    const projectId = state.activeProjectId;
    if (!projectId) {
      setStatus(el.settingsStatus, "请先选择项目", "failed");
      return false;
    }
    // 面板头**只跟随已载入的配置**（由 renderConfig 写 `state.configProjectId` 的名字）：读失败时
    // 头部保持上一个项目的名字，与仍在屏上的行一致——否则会出现「头部写着 B、内容与徽标都是 A」的
    // 撒谎状态（切项目时读取失败/在途都会命中）。
    setStatus(el.settingsStatus, "正在读取有效配置…", "busy");
    el.settingsRefresh.disabled = true;
    let response;
    try {
      response = await fetch(configUrl(projectId), { headers: { accept: "application/json" } });
    } catch (error) {
      el.settingsRefresh.disabled = false;
      setStatus(el.settingsStatus, "无法连接到服务", "failed");
      return false;
    }
    el.settingsRefresh.disabled = false;
    if (!response.ok) {
      setStatus(el.settingsStatus, describeError(await readError(response)), "failed");
      return false;
    }
    const config = await response.json();
    if (projectId !== state.activeProjectId) return false;
    state.config = config;
    state.configProjectId = projectId;
    state.configInputs = new Map();
    state.configOriginals = new Map();
    renderConfig();
    setStatus(el.settingsStatus, `已载入 ${asText(config.field_count)} 个字段的有效值`, "done");
    return true;
  }

  function renderConfig() {
    const config = state.config;
    if (!config) return;
    el.settingsProject.textContent = projectName(state.configProjectId);
    const gateOpen = Boolean(config.write_enabled);
    const labels = config.labels || {};
    if (gateOpen) {
      el.settingsGate.hidden = true;
      el.settingsGate.textContent = "";
      el.settingsGate.title = "";
    } else {
      // R9：闸门关闭只在**项目名后面**挂一个紧凑徽标（不再独占一行，也不再逐项各铺一句）。
      // 「为什么只读」没有丢：短状态 + 长解释都挂在 title 上（悬停可达），逐项则保持不可编辑。
      el.settingsGate.hidden = false;
      el.settingsGate.textContent = asText(labels.write_channel_badge) || "只读";
      el.settingsGate.title = [asText(labels.write_channel_short), asText(labels.write_channel_disabled)]
        .filter(Boolean)
        .join("\n");
    }
    renderDiagnostics(config);
    clearChildren(el.settingsGroups);
    for (const group of config.groups || []) {
      const block = makeEl("section", "group");
      block.dataset.group = asText(group.id);
      const title = makeEl("h3", "group-title", group.label);
      block.appendChild(title);
      const list = makeEl("ul", "list");
      for (const item of group.items || []) list.appendChild(renderConfigItem(item, gateOpen));
      block.appendChild(list);
      el.settingsGroups.appendChild(block);
    }
    renderUnknownKeys(config);
    updatePending();
  }

  function renderConfigItem(item, gateOpen) {
    const row = makeEl("li", "config-item");
    row.dataset.key = asText(item.key);
    row.dataset.source = asText(item.source);
    row.dataset.writable = item.writable ? "true" : "false";
    const editable = Boolean(item.writable) && gateOpen;
    row.dataset.editable = editable ? "true" : "false";
    if (item.read_only_reason) row.dataset.readOnlyReason = asText(item.read_only_reason);

    const head = makeEl("div", "config-head");
    head.appendChild(makeEl("code", "config-key", item.key));
    // R10：值**直接跟在键名后面**（不再另起一行）。类名沿用 `config-value`（只是从 `<p>` 变成 `<span>`），
    // 因此外部选择器（验收脚本、面板自测）与既有判据都不用改。
    head.appendChild(makeEl("span", "config-value", describeValue(item)));
    const badge = makeEl("span", "badge badge-source", `来源：${SOURCE_TEXT[asText(item.source)] || asText(item.source)}`);
    badge.dataset.source = asText(item.source);
    head.appendChild(badge);
    if (item.is_secret) head.appendChild(makeEl("span", "badge", "凭证"));
    row.appendChild(head);

    if (item.routing) row.appendChild(renderRouting(item.routing));

    if (editable) {
      row.appendChild(buildEditor(item, true));
      const hint = guardHint(item.guards);
      if (hint) row.appendChild(makeEl("p", "config-guard", hint));
    } else if (item.writable) {
      // 白名单内、但写入闸门关着：**仍然显示为不可编辑**（AC5 / UX-DR5 不变）。
      // R9：**不再逐项铺「只读：未开启配置写入」**——同一句在面板头部（项目名后面的徽标）已经挂过一次，
      // 上百个可写项各铺一遍只是噪音；「为什么只读」在 `#settings-gate` 的 `title` 里完整可达。
      const editor = buildEditor(item, false);
      editor.disabled = true;
      row.appendChild(editor);
    } else {
      // 只读原因同样只留一句（含「为什么」的短标签），解释性长句移进 title。
      const reason = makeEl("p", "config-reason", `只读：${labelFor(item.read_only_reason)}`);
      reason.title = "本页只读，且写入通道同样会拒绝该键";
      row.appendChild(reason);
    }

    // 逐项说明（notes）压缩成短徽标 + title：信息还在（悬停可见），但不再每个键都铺一段长文案。
    for (const note of item.notes || []) {
      const text = labelFor(note);
      const chip = makeEl("span", "badge badge-note", text);
      chip.title = text;
      row.appendChild(chip);
    }
    return row;
  }

  /** 稳定码 → 文案：**只用服务端给的 labels**，缺失时回落到原始码（可见，而不是空白）。 */
  function labelFor(code, labels) {
    const table = labels || (state.config && state.config.labels) || {};
    const codeText = asText(code);
    if (!codeText) return "";
    return asText(table[codeText]) || codeText;
  }

  function describeValue(item) {
    if (item.is_secret) {
      return item.configured ? `已配置 ${asText(item.masked) || "********"}` : "未配置（本页不提供密钥输入）";
    }
    const value = item.value;
    if (value === null || value === undefined) return "（未设置）";
    if (value === "") return "（空字符串）";
    const text = typeof value === "string" ? value : JSON.stringify(value);
    const rendered = asText(text);
    if (rendered.length > MAX_VALUE_CHARS) {
      return `${rendered.slice(0, MAX_VALUE_CHARS)}…（已截断显示，共 ${rendered.length} 字符）`;
    }
    return rendered;
  }

  function guardHint(guards) {
    if (!guards) return "";
    if (guards.kind === "enum") {
      const values = (guards.values || []).join(" | ");
      return values ? `可选值：${values}${guards.allow_empty ? "（空 = 回退）" : ""}` : "";
    }
    const parts = [];
    if (guards.minimum !== null && guards.minimum !== undefined) {
      parts.push(`${guards.exclusive_minimum ? ">" : "≥"} ${guards.minimum}`);
    }
    if (guards.maximum !== null && guards.maximum !== undefined) {
      parts.push(`${guards.exclusive_maximum ? "<" : "≤"} ${guards.maximum}`);
    }
    if (guards.min_length !== null && guards.min_length !== undefined) parts.push(`长度 ≥ ${guards.min_length}`);
    return parts.length ? `取值范围：${parts.join("，")}` : "";
  }

  function buildEditor(item, register) {
    const guards = item.guards;
    const current = rawValue(item);
    if (guards && guards.kind === "enum" && Array.isArray(guards.values) && guards.values.length) {
      const select = document.createElement("select");
      select.className = "config-input config-select";
      const values = guards.values.slice();
      if (guards.allow_empty && !values.includes("")) values.unshift("");
      if (current !== "" && !values.includes(current)) values.unshift(current);
      for (const value of values) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value === "" ? "（空 = 回退）" : value;
        select.appendChild(option);
      }
      select.value = current;
      return trackEditor(item, select, register);
    }
    const input = document.createElement("input");
    input.className = "config-input";
    input.type = "text";
    input.value = current;
    return trackEditor(item, input, register);
  }

  function trackEditor(item, node, register) {
    node.dataset.key = asText(item.key);
    if (register) {
      node.addEventListener("change", updatePending);
      node.addEventListener("input", updatePending);
      state.configInputs.set(asText(item.key), node);
      state.configOriginals.set(asText(item.key), asText(node.value));
    }
    return node;
  }

  /** 编辑框里始终是**原始值**（绝不把展示用的截断文本写回文件）。 */
  function rawValue(item) {
    const value = item.value;
    if (value === null || value === undefined) return "";
    return typeof value === "string" ? value : JSON.stringify(value);
  }

  function renderRouting(routing) {
    const list = makeEl("ul", "config-routing");
    if (routing.invalid_json) {
      list.appendChild(makeEl("li", "diag-warn", "ROUTING_POOLS 不是合法 JSON：整份配置被忽略（已回落各条目 MODEL）"));
    }
    for (const pool of routing.effective || []) {
      const tiers = Object.keys(pool.tiers || {})
        .map((name) => `${name}=${pool.tiers[name]}`)
        .join(" / ");
      const roles = Object.keys(pool.roles || {})
        .map((name) => `${name}→${pool.roles[name]}`)
        .join(" / ");
      const parts = [`${asText(pool.entry)}：${tiers || "（无档位）"}`];
      if (roles) parts.push(`角色 ${roles}`);
      if (pool.default) parts.push(`默认档 ${asText(pool.default)}`);
      list.appendChild(makeEl("li", null, parts.join("；")));
    }
    for (const entry of routing.ignored_entries || []) {
      list.appendChild(makeEl("li", "diag-warn", `${asText(entry)}：被整条忽略（未知条目名或规格非法）`));
    }
    return list;
  }

  function renderDiagnostics(config) {
    clearChildren(el.settingsDiagnostics);
    const envFile = config.env_file || {};
    el.settingsDiagnostics.appendChild(makeEl("p", "diag-path", `项目 .env：${asText(envFile.path) || "（未知）"}`));
    const facts = [];
    facts.push(envFile.exists ? "存在" : "不存在（全部回退到全局 .env / 默认值）");
    if (envFile.exists) {
      facts.push(envFile.readable ? "可读" : "不可读");
      facts.push(`${asText(envFile.line_count)} 行`);
    }
    if (asText(envFile.fingerprint)) facts.push(`指纹 ${asText(envFile.fingerprint).slice(0, 12)}…`);
    el.settingsDiagnostics.appendChild(makeEl("p", null, facts.join(" · ")));
    // R4：诊断块折进「默认收起的 `<details>`」，但**收起时也要能看出有几条告警**——否则
    // 「以为生效其实没生效」（重复键 / 空值键 / BOM / 无效 JSON）就被折叠藏掉了。
    const warnings = [];
    if (envFile.exists && !envFile.readable) warnings.push("项目 .env 不可读");
    if (envFile.has_bom) warnings.push("文件带 UTF-8 BOM：按容差读取（盘上字节未改）");
    if (Array.isArray(envFile.duplicate_keys) && envFile.duplicate_keys.length) {
      warnings.push(`重复键（后者生效）：${envFile.duplicate_keys.join("、")}`);
    }
    if (Array.isArray(envFile.blank_keys) && envFile.blank_keys.length) {
      warnings.push(`空值键（显式置空，不生效）：${envFile.blank_keys.join("、")}`);
    }
    for (const note of config.notes || []) warnings.push(labelFor(note, config.labels));
    for (const text of warnings) el.settingsDiagnostics.appendChild(makeEl("p", "diag-warn", text));
    if (el.settingsDiagnosticsSummary) {
      el.settingsDiagnosticsSummary.textContent = warnings.length
        ? `项目 .env 诊断（${warnings.length} 条需要注意）`
        : "项目 .env 诊断";
      el.settingsDiagnosticsSummary.dataset.state = warnings.length ? "failed" : "idle";
    }
  }

  function renderUnknownKeys(config) {
    clearChildren(el.unknownList);
    const keys = config.unknown_keys || [];
    el.unknownEmpty.hidden = keys.length > 0;
    if (el.unknownSummary) {
      el.unknownSummary.textContent = keys.length ? `未知键（${keys.length} 条，不生效）` : "未知键（不生效）";
      el.unknownSummary.dataset.state = keys.length ? "failed" : "idle";
    }
    for (const entry of keys) {
      const item = makeEl("li", "list-item");
      item.dataset.unknownKey = asText(entry.key);
      const head = makeEl("div", "config-head");
      head.appendChild(makeEl("code", "config-key", entry.key));
      const badge = makeEl("span", "badge badge-source", `来源：${SOURCE_TEXT[asText(entry.source)] || asText(entry.source)}`);
      badge.dataset.source = asText(entry.source);
      head.appendChild(badge);
      item.appendChild(head);
      item.appendChild(makeEl("p", "config-reason", "不生效：键名不在 Settings 字段集内（拼写错误或已废弃）"));
      el.unknownList.appendChild(item);
    }
  }

  function collectChanges() {
    const changes = [];
    if (!state.config) return changes;
    for (const [key, node] of state.configInputs) {
      const original = state.configOriginals.get(key);
      if (asText(node.value) !== asText(original)) changes.push({ key, value: asText(node.value) });
    }
    return changes;
  }

  function updatePending() {
    const changes = collectChanges();
    const gateOpen = Boolean(state.config && state.config.write_enabled);
    el.settingsSave.disabled = state.saving || !gateOpen || changes.length === 0;
    setStatus(
      el.settingsPending,
      changes.length ? `有 ${changes.length} 项未保存` : "没有未保存的改动",
      changes.length ? "busy" : "idle",
    );
  }

  function showResult(kind, title, lines) {
    el.settingsResult.hidden = false;
    el.settingsResult.dataset.state = kind;
    clearChildren(el.settingsResult);
    el.settingsResult.appendChild(makeEl("p", "result-title", title));
    for (const line of lines) el.settingsResult.appendChild(makeEl("p", null, line));
  }

  async function saveConfig() {
    const projectId = state.activeProjectId;
    const config = state.config;
    if (!projectId || !config || state.saving) return;
    // 屏上的行必须属于**当前**项目。切换项目时若配置读取失败（或仍在途），面板会留着上一个项目的行与
    // 未保存改动，而写路径取 `state.activeProjectId` ⇒ 会把 A 的改动写进 B 的 `.env`（两侧都没有
    // `.env` 时指纹都是 null，服务端的指纹闸门拦不住这种组合）。归属不符就拒绝，并把原因说出来。
    if (state.configProjectId !== projectId) {
      setStatus(el.settingsStatus, "面板显示的不是当前项目的配置，请先重新载入设置再保存", "failed");
      return;
    }
    const changes = collectChanges();
    if (!changes.length) return;
    const keys = changes.map((change) => change.key);
    const answer = await askConfirm({
      title: `写入项目 .env：${projectName(projectId)}`,
      text:
        `将修改这些键：${keys.join("、")}\n` +
        `写入路径：${asText((config.env_file || {}).path) || ".env"}\n` +
        "生效范围：只对下一次运行生效——正在进行的运行继续使用旧配置快照。写前自动备份，写后回读校验。",
      okText: "写入",
    });
    if (!answer.confirmed) return;
    state.saving = true;
    updatePending();
    setStatus(el.settingsStatus, `正在写入 ${changes.length} 项…`, "busy");
    let response;
    try {
      response = await fetch(configUrl(projectId), {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ changes, fingerprint: (config.env_file || {}).fingerprint }),
      });
    } catch (error) {
      state.saving = false;
      updatePending();
      setStatus(el.settingsStatus, "无法连接到服务", "failed");
      showResult("failed", "写入未完成", ["无法连接到服务：本次没有改动任何文件。"]);
      return;
    }
    state.saving = false;
    if (!response.ok) {
      const failure = await readError(response);
      showResult("failed", "写入被拒绝（文件未改动）", [describeError(failure)]);
      if (failure.code === "config_conflict") await loadConfig();
      else updatePending();
      // 放在刷新**之后**：全量刷新会把状态行写成「已载入…」，失败文案必须留下来。
      setStatus(el.settingsStatus, describeError(failure), "failed");
      return;
    }
    const result = await response.json();
    const written = (result.changes || []).map((item) => asText(item.key));
    const lines = [`已写入 ${written.length || keys.length} 个键：${(written.length ? written : keys).join("、")}`];
    if (result.backup) lines.push(`写入前备份：${asText(result.backup)}（备份不提供网页下载）`);
    lines.push("下一次运行生效：本次改动不会改变正在进行的运行。");
    for (const note of result.notes || []) lines.push(labelFor(note, result.labels));
    for (const item of result.changes || []) replaceConfigRow(item);
    if (state.config && state.config.env_file) {
      state.config.env_file.fingerprint = result.fingerprint;
      state.config.env_file.exists = true;
    }
    showResult("ok", "保存成功", lines);
    updatePending(); // 就地刷新后「未保存项」必须归零（刷新失败时也一样）
    const refreshed = await loadConfig(); // 同一页刷新来源徽标 / 文件诊断（服务端是唯一事实源）
    if (refreshed) {
      // 全量刷新会把状态行写成「已载入…」，因此成功文案放在刷新**之后**。
      setStatus(el.settingsStatus, "已保存：下一次运行生效", "done");
    } else {
      // 面板刷新失败时不能只说「已保存」：文件已改、但页面显示的是写入响应里的那几项。
      setStatus(
        el.settingsStatus,
        "已保存：下一次运行生效（但面板刷新失败，写过的行显示的是服务端返回的写入结果，其余项可能已过时）",
        "failed",
      );
    }
  }

  /** 用写响应里回来的**写后条目**就地更新那一行（值、来源徽标、可编辑性都按服务端事实）。 */
  function replaceConfigRow(item) {
    const current = findConfigRow(el.settingsGroups, asText(item.key));
    if (!current || !current.parentNode) return;
    const replacement = renderConfigItem(item, Boolean(state.config && state.config.write_enabled));
    current.parentNode.replaceChild(replacement, current);
  }

  function findConfigRow(root, key) {
    for (const group of root.children) {
      for (const child of group.children) {
        if (child.className !== "list") continue;
        for (const row of child.children) {
          if (row.dataset && row.dataset.key === key) return row;
        }
      }
    }
    return null;
  }

  // ── 顶栏与启动 ──

  function toggleSidebar() {
    state.sidebarCollapsed = !state.sidebarCollapsed;
    el.console.dataset.sidebarCollapsed = state.sidebarCollapsed ? "true" : "false";
    el.sidebarToggle.setAttribute("aria-expanded", state.sidebarCollapsed ? "false" : "true");
    el.sidebarToggle.textContent = state.sidebarCollapsed ? "展开侧栏" : "收起侧栏";
  }

  async function checkHealth() {
    try {
      const response = await fetch("/api/health", { headers: { accept: "application/json" } });
      if (!response.ok) {
        setServiceState("offline");
        return;
      }
      const payload = await response.json();
      setServiceState(payload && payload.status === "ok" ? "ready" : "offline");
    } catch (error) {
      setServiceState("offline");
    }
  }

  async function bootstrap() {
    const projects = await loadProjects();
    if (!projects || !projects.length) {
      setStatus(el.sessionStatus, "没有可用的项目", "failed");
      refreshComposer();
      return;
    }
    const saved = storageGet(SELECTION_KEY);
    const preferred = saved && projects.some((item) => item.id === saved) ? saved : null;
    const fallback = projects.find((item) => item.is_default) || projects[0];
    await selectProject(preferred || fallback.id, { force: true });
  }

  el.form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (state.activeRunId) {
      // 运行中禁止重复提交（服务端也会回 run_conflict），但**不静默吞掉**这次点击：
      // 取消失败或连接中断时发送按钮可能已解禁，用户需要一个可读的原因。
      appendEntry("error", "已有运行进行中：请等待它结束，或点「停止」后再提交。");
      return;
    }
    const blocked = runBlockReason();
    if (blocked) {
      appendEntry("error", blocked);
      return;
    }
    const prompt = asText(el.input.value).trim();
    if (!prompt) return;
    el.input.value = "";
    void submitPrompt(prompt);
  });

  el.stop.addEventListener("click", () => {
    void cancelRun();
  });

  el.input.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    // 输入法组合中（中文/日文选词时敲回车）绝不当作发送：交给 IME 完成候选词。
    // keyCode === 229 是组合态的老式信号（部分浏览器/输入法仍只给这个）。
    if (event.isComposing || event.keyCode === 229) return;
    // Shift+Enter 不拦截 ⇒ 走浏览器在 textarea 内的默认行为（插入换行）。
    if (event.shiftKey) return;
    // 其余 Enter 一律等同点击「发送」（Ctrl/Cmd+Enter 因此仍是等价快捷键，行为不变）。
    event.preventDefault();
    el.form.requestSubmit();
  });

  el.sidebarToggle.addEventListener("click", toggleSidebar);
  el.settingsButton.addEventListener("click", () => setSettingsOpen(!state.settingsOpen));
  el.settingsClose.addEventListener("click", () => setSettingsOpen(false));
  el.settingsRefresh.addEventListener("click", () => void loadConfig());
  el.settingsSave.addEventListener("click", () => void saveConfig());
  el.sessionCreate.addEventListener("click", () => void createSession());
  el.sessionMore.addEventListener("click", () => {
    state.sessionShowAll = !state.sessionShowAll;
    renderSessions();
  });
  el.projectForm.addEventListener("submit", (event) => void registerProject(event));
  el.projectPick.addEventListener("click", () => void pickProjectDirectory());

  setServiceState("connecting");
  setRunState("idle");
  setSettingsOpen(false);
  renderProjects();
  renderSessions();
  renderOtherRunNote();
  refreshComposer();
  checkHealth();
  void bootstrap();
  window.setInterval(checkHealth, HEALTH_POLL_MS);
})();
