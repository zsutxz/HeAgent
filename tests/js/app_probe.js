/* 内置网页的行为探针（Epic 49 评审修复的回归 + Epic 50 控制台 UI 的回归）。
 *
 * app.js 是一个 IIFE，内部状态不可从外部注入，因此这里用**最小 DOM / EventSource / fetch 替身**
 * 加载真实脚本，再驱动真实分支（提交 → SSE 事件 → 重连 → 项目/会话切换 → 设置面板 → 保存）并打印
 * 可观察结果。这样前端契约就不再只能靠「字符串是否出现在源码里」来证明。
 *
 * 用法：node app_probe.js <app.js 路径> <index.html 路径> <A|B|…|M>
 * 输出：一行 ``PROBE_RESULT {json}``（由 tests/test_http_web_ui.py 解析并断言）。
 *
 * 元素清单**从 index.html 解析**：脚本里 getElementById 拿不到的 id 会返回 null（而不是凭空造一个
 * 假元素），因此「JS 引用了页面上不存在的 id」会立刻炸成 PROBE_ERROR，而不是静默通过。
 */
"use strict";

const fs = require("fs");

const SRC_PATH = process.argv[2];
const HTML_PATH = process.argv[3];
const CASE = process.argv[4] || "A";
const src = fs.readFileSync(SRC_PATH, "utf8");
const html = fs.readFileSync(HTML_PATH, "utf8");

// ── 最小 DOM 替身 ──

function createTextNode(value) {
  return { text: String(value) };
}

function makeEl(tag) {
  const el = {
    tagName: tag,
    children: [],
    dataset: {},
    attributes: {},
    className: "",
    hidden: false,
    disabled: false,
    checked: false,
    type: "",
    value: "",
    maxLength: 0,
    scrollTop: 0,
    scrollHeight: 0,
    parentNode: null,
    _tc: null,
    _handlers: {},
    appendChild(child) {
      this.children.push(child);
      if (child && typeof child === "object") child.parentNode = this;
      return child;
    },
    removeChild(child) {
      const index = this.children.indexOf(child);
      if (index >= 0) this.children.splice(index, 1);
      if (child && typeof child === "object") child.parentNode = null;
      return child;
    },
    replaceChild(newChild, oldChild) {
      const index = this.children.indexOf(oldChild);
      if (index >= 0) this.children[index] = newChild;
      if (newChild && typeof newChild === "object") newChild.parentNode = this;
      if (oldChild && typeof oldChild === "object") oldChild.parentNode = null;
      return oldChild;
    },
    get firstChild() {
      return this.children.length ? this.children[0] : null;
    },
    replaceChildren(...nodes) {
      this.children = [];
      this._tc = null;
      for (const node of nodes) this.appendChild(node);
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
    },
    removeAttribute(name) {
      delete this.attributes[name];
    },
    addEventListener(kind, fn) {
      this._handlers[kind] = fn;
    },
    dispatchEvent(event) {
      const fn = this._handlers[event && event.type];
      if (fn) fn(event);
      return true;
    },
    focus() {
      this.focused = true;
    },
    requestSubmit() {
      if (this._handlers.submit) return this._handlers.submit({ preventDefault() {} });
      return undefined;
    },
    click() {
      if (this._handlers.click) this._handlers.click();
    },
  };
  Object.defineProperty(el, "textContent", {
    get() {
      if (this._tc !== null) return this._tc;
      return this.children.map((child) => (child && child.text !== undefined ? child.text : child.textContent)).join("");
    },
    set(value) {
      this._tc = String(value);
      this.children = [];
    },
  });
  return el;
}

const ids = Array.from(new Set(Array.from(html.matchAll(/id="([^"]+)"/g)).map((match) => match[1])));
const els = {};
for (const id of ids) els[id] = makeEl(id);

const documentHandlers = {};
global.document = {
  createElement: (tag) => makeEl(tag),
  createTextNode,
  getElementById: (id) => (Object.prototype.hasOwnProperty.call(els, id) ? els[id] : null),
  addEventListener(kind, fn) {
    documentHandlers[kind] = fn;
  },
};

const store = new Map();
global.window = {
  setInterval: () => 0,
  localStorage: {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  },
};

const sources = [];
class FakeEventSource {
  constructor(url) {
    this.url = url;
    this.handlers = {};
    this.closed = false;
    sources.push(this);
  }
  addEventListener(kind, fn) {
    this.handlers[kind] = fn;
  }
  close() {
    this.closed = true;
  }
  emit(kind, payload) {
    const fn = this.handlers[kind];
    if (fn) fn({ data: JSON.stringify(payload) });
  }
}
global.EventSource = FakeEventSource;

// ── fetch 替身：按「方法 + 路径」路由（未注册的路径回 404，避免测试对着静默的假数据断言） ──

const net = { calls: [], routes: new Map() };

function jsonResponse(status, body) {
  return { ok: status < 400, status, json: async () => body };
}

function route(method, path, handler) {
  net.routes.set(`${method} ${path}`, handler);
}

global.fetch = async (url, options = {}) => {
  const method = options.method || "GET";
  net.calls.push(`${method} ${url}`);
  const handler = net.routes.get(`${method} ${url}`);
  if (!handler) {
    return jsonResponse(404, { error: { code: "not_found", message: `no route for ${method} ${url}` } });
  }
  return handler(options, url);
};

// ── 可变的「世界」：项目 / 会话 / 配置都由用例改写 ──

const ISO = "2026-09-24T11:00:00Z";

function project(id, name, overrides = {}) {
  return {
    id,
    name,
    path: `C:/ws/${id}`,
    available: true,
    last_opened_at: null,
    is_default: false,
    ...overrides,
  };
}

function session(sessionId, title, overrides = {}) {
  return {
    session_id: sessionId,
    title,
    message_count: 2,
    version: 3,
    updated_at: ISO,
    unreadable: false,
    ...overrides,
  };
}

const world = {
  projects: [
    project("default", "服务工作区", { is_default: true, path: "C:/ws" }),
    project("pB", "项目 B", { last_opened_at: ISO }),
    project("pGone", "已失效项目", { available: false, last_opened_at: "2026-09-24T09:00:00Z" }),
  ],
  sessions: {
    default: [session("s1", "会话一")],
    pB: [],
    pGone: [],
  },
  details: {
    s1: {
      session_id: "s1",
      title: "会话一",
      version: 3,
      messages: [
        { role: "user", text: "你好" },
        { role: "assistant", text: "你好，我是 HeAgent" },
      ],
      messages_truncated: false,
      run_id: null,
      status: null,
    },
  },
  createSession: session("s9", "未命名会话", { message_count: 0, version: 1 }),
  renameSession: session("s1", "新标题"),
  run: { run_id: "run-1", session_id: "s1", status: "running" },
  configError: null,
  writeError: null,
  // 写成功之后让面板的**后续刷新**失败：用来验证「写过的行仍按写响应显示写后事实」。
  failConfigReadAfterWrite: false,
  configReadFails: false,
  writeFingerprint: "fp-1",
};

const LABELS = {
  credential: "凭证项：永不回传、永不写入",
  sandbox_posture: "沙箱与执行后端：改动等于改变 OS 级隔离姿态",
  console_itself: "控制台自身开关：写入面不得给自己解锁",
  project_env_missing: "项目 .env 不存在：全部字段回退到全局 .env / 默认值",
  audit_not_recorded: "写入已生效，但审计记录未能落盘（服务端有 ERROR 日志）",
  write_channel_disabled: "服务启动时未开启配置写入（HTTP_CONSOLE_WRITE_ENABLED）：所有可写项在本页只读",
};

function guardRange(minimum, maximum) {
  return {
    kind: "range",
    values: [],
    minimum,
    maximum,
    exclusive_minimum: false,
    exclusive_maximum: false,
    min_length: null,
    allow_empty: false,
  };
}

const configItems = {
  MAX_ITERATIONS: {
    key: "MAX_ITERATIONS",
    group: "limits",
    value: 25,
    // 起始来源是**全局 .env**：写进项目 .env 之后来源徽标必须变成「项目 .env」——
    // 这正是 AC6「保存后刷新该项的来源徽标」要证明的可观察差异。
    source: "global_env",
    writable: true,
    read_only_reason: null,
    is_secret: false,
    configured: true,
    masked: null,
    guards: guardRange(1, 100),
    notes: ["duplicate_in_project_env"],
    routing: null,
  },
  CONTEXT_STRATEGY: {
    key: "CONTEXT_STRATEGY",
    group: "context",
    value: "compressor",
    source: "default",
    writable: true,
    read_only_reason: null,
    is_secret: false,
    configured: false,
    masked: null,
    guards: {
      kind: "enum",
      values: ["compressor", "reset"],
      minimum: null,
      maximum: null,
      exclusive_minimum: false,
      exclusive_maximum: false,
      min_length: null,
      allow_empty: false,
    },
    notes: [],
    routing: null,
  },
  KIMI_API_KEY: {
    key: "KIMI_API_KEY",
    group: "credentials",
    value: null,
    source: "project_env",
    writable: false,
    read_only_reason: "credential",
    is_secret: true,
    configured: true,
    masked: "********",
    guards: null,
    notes: [],
    routing: null,
  },
  SANDBOX_MODE: {
    key: "SANDBOX_MODE",
    group: "sandbox",
    value: "workspace-write",
    source: "system_env",
    writable: false,
    read_only_reason: "sandbox_posture",
    is_secret: false,
    configured: true,
    masked: null,
    guards: null,
    notes: [],
    routing: null,
  },
  HTTP_CONSOLE_WRITE_ENABLED: {
    key: "HTTP_CONSOLE_WRITE_ENABLED",
    group: "console",
    value: true,
    source: "project_env",
    writable: false,
    read_only_reason: "console_itself",
    is_secret: false,
    configured: true,
    masked: null,
    guards: null,
    notes: [],
    routing: null,
  },
};

function configPayload(writeEnabled) {
  return {
    project_id: "default",
    field_count: 111,
    write_enabled: writeEnabled,
    groups: [
      { id: "limits", label: "迭代与限额", items: [configItems.MAX_ITERATIONS] },
      { id: "context", label: "上下文", items: [configItems.CONTEXT_STRATEGY] },
      { id: "credentials", label: "凭证", items: [configItems.KIMI_API_KEY] },
      { id: "sandbox", label: "沙箱与执行后端", items: [configItems.SANDBOX_MODE] },
      { id: "console", label: "控制台自身", items: [configItems.HTTP_CONSOLE_WRITE_ENABLED] },
    ],
    env_file: {
      path: "C:/ws/.env",
      exists: true,
      readable: true,
      fingerprint: world.writeFingerprint,
      has_bom: false,
      line_count: 12,
      duplicate_keys: ["MAX_ITERATIONS"],
      blank_keys: [],
    },
    unknown_keys: [{ key: "TOTALLY_UNKNOWN", source: "project_env" }],
    labels: LABELS,
    notes: ["project_env_missing"],
  };
}

let configWriteEnabled = false;

function installRoutes() {
  route("GET", "/api/health", () => jsonResponse(200, { status: "ok", service: "heagent-http", version: "test" }));
  route("GET", "/api/projects", () => jsonResponse(200, { projects: world.projects.map((item) => ({ ...item })) }));
  route("POST", "/api/projects", (options) => {
    const body = JSON.parse(options.body || "{}");
    const created = project("pNew", body.name || "新项目", { path: body.path, last_opened_at: ISO });
    world.projects = [...world.projects.filter((item) => item.id !== "pNew"), created];
    world.sessions.pNew = [];
    return jsonResponse(201, created);
  });
  route("PATCH", "/api/projects/pB", (options) => {
    const body = JSON.parse(options.body || "{}");
    world.projects = world.projects.map((item) => (item.id === "pB" ? { ...item, name: body.name } : item));
    return jsonResponse(200, world.projects.find((item) => item.id === "pB"));
  });
  route("DELETE", "/api/projects/pB?confirm=true", () => {
    world.projects = world.projects.filter((item) => item.id !== "pB");
    return { ok: true, status: 204, json: async () => ({}) };
  });
  for (const projectId of ["default", "pB", "pGone", "pNew"]) {
    route("GET", `/api/projects/${projectId}/sessions`, () =>
      jsonResponse(200, { sessions: (world.sessions[projectId] || []).map((item) => ({ ...item })) }),
    );
  }
  route("POST", "/api/projects/default/sessions", () => {
    world.sessions.default = [world.createSession, ...world.sessions.default];
    world.details[world.createSession.session_id] = {
      session_id: world.createSession.session_id,
      title: world.createSession.title,
      version: 1,
      messages: [],
      messages_truncated: false,
      run_id: null,
      status: null,
    };
    return jsonResponse(201, world.createSession);
  });
  route("PATCH", "/api/projects/default/sessions/s1", (options) => {
    const body = JSON.parse(options.body || "{}");
    world.sessions.default = world.sessions.default.map((item) =>
      item.session_id === "s1" ? { ...item, title: body.title, version: item.version + 1 } : item,
    );
    world.details.s1 = { ...world.details.s1, title: body.title, version: world.details.s1.version + 1 };
    return jsonResponse(200, world.sessions.default.find((item) => item.session_id === "s1"));
  });
  route("DELETE", "/api/projects/default/sessions/s1?confirm=true", () => {
    world.sessions.default = world.sessions.default.filter((item) => item.session_id !== "s1");
    return { ok: true, status: 204, json: async () => ({}) };
  });
  route("GET", "/api/projects/default/sessions/s1", () =>
    jsonResponse(200, { ...world.details.s1 }),
  );
  route("GET", "/api/projects/default/sessions/sBad", () =>
    jsonResponse(409, { error: { code: "session_unreadable", message: "session file cannot be parsed" } }),
  );
  route("POST", "/api/projects/default/runs", () =>
    jsonResponse(201, { run_id: world.run.run_id, session_id: world.run.session_id, status: "running" }),
  );
  route("GET", "/api/projects/default/config", () => {
    if (world.configReadFails) {
      return jsonResponse(500, { error: { code: "server_error", message: "config panel exploded" } });
    }
    if (world.configError) return jsonResponse(world.configError.status, world.configError.body);
    return jsonResponse(200, configPayload(configWriteEnabled));
  });
  route("PUT", "/api/projects/default/config", (options) => {
    const body = JSON.parse(options.body || "{}");
    world.lastWrite = body;
    if (world.writeError) return jsonResponse(world.writeError.status, world.writeError.body);
    if (world.failConfigReadAfterWrite) world.configReadFails = true;
    configWriteEnabled = Boolean(configWriteEnabled);
    world.writeFingerprint = "fp-2";
    const changed = (body.changes || []).map((change) => ({
      ...configItems[change.key],
      value: change.key === "MAX_ITERATIONS" ? Number(change.value) : change.value,
      source: "project_env",
    }));
    for (const item of changed) configItems[item.key] = { ...item, value: item.value };
    return jsonResponse(200, {
      project_id: "default",
      fingerprint: world.writeFingerprint,
      applied: "next_run",
      backup: "env-20260924T164712123456Z-abcdef01.bak",
      audit_recorded: false,
      changes: changed,
      notes: ["audit_not_recorded"],
      labels: LABELS,
    });
  });
}

installRoutes();

// ── 驱动与观察工具 ──

const tick = () => new Promise((resolve) => setImmediate(resolve));

async function settle(count = 6) {
  for (let index = 0; index < count; index += 1) await tick();
}

async function load() {
  // 每次用例都重新执行脚本，得到干净的闭包状态（模拟一次页面载入）。
  // eslint-disable-next-line no-new-func
  new Function(src)();
  await settle();
}

async function submit(text) {
  els["prompt-input"].value = text;
  els["prompt-form"].requestSubmit();
  await settle();
}

function lines() {
  return els["chat-log"].children.map((child) => child.textContent);
}

function walk(node, visit) {
  if (!node || !node.children) return;
  for (const child of node.children) {
    visit(child);
    walk(child, visit);
  }
}

function findByDataset(root, key, value) {
  let found = null;
  walk(root, (node) => {
    if (!found && node.dataset && node.dataset[key] === value) found = node;
  });
  return found;
}

function findConfigRow(key) {
  return findByDataset(els["settings-groups"], "key", key);
}

function textOf(node) {
  return node ? node.textContent : null;
}

function inputsOf(root) {
  const inputs = [];
  walk(root, (node) => {
    if (node.tagName === "input" || node.tagName === "select") inputs.push(node);
  });
  return inputs;
}

function fire(node, kind, payload) {
  node.dispatchEvent({ type: kind, preventDefault() {}, ...(payload || {}) });
}

function callsMatching(pattern) {
  return net.calls.filter((call) => call.includes(pattern));
}

function resetCalls() {
  net.calls.length = 0;
}

function lastStream() {
  return sources.length ? sources[sources.length - 1] : null;
}

function openSettings() {
  els["settings-button"].click();
  return settle();
}

function setInput(node, value) {
  node.value = value;
  fire(node, "input");
}

function clickOk() {
  els["confirm-ok"].click();
  return settle();
}

function clickCancel() {
  els["confirm-cancel"].click();
  return settle();
}

/** 会话项里的 [重命名, 删除] 按钮。 */
function sessionAction(sessionId, index) {
  const item = findByDataset(els["session-list"], "sessionId", sessionId);
  return item ? item.children[2].children[index] : null;
}

function projectButton(projectId) {
  const item = findByDataset(els["project-list"], "projectId", projectId);
  return item ? item.children[0] : null;
}

function projectAction(projectId, index) {
  const item = findByDataset(els["project-list"], "projectId", projectId);
  return item ? item.children[2].children[index] : null;
}

// ── 用例 ──

const CASES = {
  async A() {
    // 同名工具连续两次调用：两次 tool_result 必须各归其行，先到先配。
    await load();
    await submit("hi");
    const stream = lastStream();
    stream.emit("tool_call", { kind: "tool_call", tool_name: "shell", tool_target: "pytest -q" });
    stream.emit("tool_call", { kind: "tool_call", tool_name: "shell", tool_target: "mypy src" });
    stream.emit("tool_result", { kind: "tool_result", tool_name: "shell", tool_output: "first result", tool_error: false });
    stream.emit("tool_result", { kind: "tool_result", tool_name: "shell", tool_output: "second result", tool_error: false });
    return { pairing: lines().filter((line) => line.includes("shell")) };
  },

  async B() {
    // 连接中断后重新同步，而服务端事实是 completed：状态文案必须与服务端一致。
    world.details.s1 = { ...world.details.s1, run_id: "run-1", status: "completed" };
    await load();
    await submit("hi");
    lastStream().emit("error", {});
    await settle(10);
    return { state: els["run-status"].dataset.state, text: els["run-status"].textContent };
  },

  async C() {
    // 载入时服务端仍有在途运行：页面必须接手该运行的事件流，而不是显示「空闲」。
    world.details.s1 = { ...world.details.s1, run_id: "run-9", status: "running" };
    await load();
    return {
      state: els["run-status"].dataset.state,
      text: els["run-status"].textContent,
      sendDisabled: els["send-button"].disabled,
      stopDisabled: els["stop-button"].disabled,
      subscribed: lastStream() ? lastStream().url : null,
    };
  },

  async D() {
    // 已有在途运行时的再次提交：不得静默吞掉（要有可读原因、且不真的发请求）。
    await load();
    await submit("first");
    resetCalls();
    const before = els["chat-log"].children.length;
    await submit("second");
    return {
      newEntries: els["chat-log"].children.length - before,
      posted: callsMatching("POST /api/projects/default/runs").length > 0,
      lastLine: lines()[lines().length - 1],
    };
  },

  async E() {
    // 键盘语义：Enter 发送 / Shift+Enter 换行（不吞默认行为）/ 组合输入（IME）不发送。
    const pressEnter = async (overrides = {}) => {
      const handler = els["prompt-input"]._handlers.keydown;
      if (!handler) throw new Error("app.js 未注册 prompt-input 的 keydown 监听");
      let prevented = false;
      handler({ key: "Enter", preventDefault() { prevented = true; }, ...overrides });
      await settle(2);
      return prevented;
    };
    const posted = () => callsMatching("POST /api/projects/default/runs").length > 0;

    await load();
    els["prompt-input"].value = "靠回车发送";
    const enterPrevented = await pressEnter();
    const enterPosted = posted();
    const enterCleared = els["prompt-input"].value === "";

    resetCalls();
    await load();
    els["prompt-input"].value = "想在这里换行";
    const shiftPrevented = await pressEnter({ shiftKey: true });
    const shiftPosted = posted();
    const shiftValue = els["prompt-input"].value;

    resetCalls();
    await load();
    els["prompt-input"].value = "选词中的回车";
    const composingPrevented = await pressEnter({ isComposing: true });
    const composingPosted = posted();

    return {
      enterPrevented,
      enterPosted,
      enterCleared,
      shiftPrevented,
      shiftPosted,
      shiftValue,
      composingPrevented,
      composingPosted,
    };
  },

  async F() {
    // 项目层：列表渲染（含失效标记）、切换只改本页状态、切走不取消在途运行。
    await load();
    const rendered = findByDataset(els["project-list"], "projectId", "pGone");
    const unavailableFlag = rendered
      ? rendered.children[1].children.find((child) => child.textContent.includes("目录已失效"))
      : null;
    const initialActive = els["active-project"].textContent;

    await submit("先起一个运行");
    resetCalls();
    projectButton("pB").click();
    await settle(8);

    const result = {
      initialActive,
      unavailableMarked: Boolean(unavailableFlag),
      unavailableDataset: rendered ? rendered.dataset.available : null,
      activeProject: els["active-project"].textContent,
      sessionCalls: callsMatching("GET /api/projects/pB/sessions").length,
      runCancelled: callsMatching("DELETE /api/runs/").length,
      streamClosed: lastStream() ? lastStream().closed : null,
      chatEntries: els["chat-log"].children.length,
      noteHidden: els["other-run-note"].hidden,
      noteText: els["other-run-note"].textContent,
      stored: store.get("heagent.console.project_id"),
      sessionEmptyHidden: els["session-empty"].hidden,
      sendEnabled: !els["send-button"].disabled,
    };
    return result;
  },

  async G() {
    // 设置面板：闸门关闭时全部可写项不可编辑 + 原因 + 无任何开启入口（AC5）。
    configWriteEnabled = false;
    await load();
    await openSettings();
    const iterationsRow = findConfigRow("MAX_ITERATIONS");
    const iterationsInput = findByDataset(iterationsRow, "key", "MAX_ITERATIONS");
    const secretRow = findConfigRow("KIMI_API_KEY");
    const sandboxRow = findConfigRow("SANDBOX_MODE");
    const gateRow = findConfigRow("HTTP_CONSOLE_WRITE_ENABLED");
    const reason = iterationsRow
      ? iterationsRow.children.find((child) => child.className === "config-reason")
      : null;
    const sourceBadge = iterationsRow
      ? iterationsRow.children[0].children.find((child) => child.className === "badge badge-source")
      : null;
    return {
      gateHidden: els["settings-gate"].hidden,
      gateText: els["settings-gate"].textContent,
      saveDisabled: els["settings-save"].disabled,
      editable: iterationsRow ? iterationsRow.dataset.editable : null,
      writable: iterationsRow ? iterationsRow.dataset.writable : null,
      inputDisabled: iterationsInput ? iterationsInput.disabled : null,
      reasonText: textOf(reason),
      secretText: secretRow ? secretRow.children[1].textContent : null,
      secretHasInput: secretRow ? inputsOf(secretRow).length : null,
      sandboxReasonState: sandboxRow ? sandboxRow.dataset.readOnlyReason : null,
      sandboxReasonText: textOf(sandboxRow ? sandboxRow.children[2] : null),
      gateKeyEditable: gateRow ? gateRow.dataset.editable : null,
      enabledInputs: inputsOf(els["settings-panel"]).filter(
        (node) => !node.disabled && node.dataset.key !== undefined,
      ).length,
      sourceBadgeText: textOf(sourceBadge),
      sourceBadgeDataset: sourceBadge ? sourceBadge.dataset.source : null,
      unknownKeys: els["unknown-keys"].children.map((child) => child.children[0].children[0].textContent),
      unknownEmptyHidden: els["unknown-empty"].hidden,
      diagnostics: els["settings-diagnostics"].textContent,
      groupIds: els["settings-groups"].children.map((child) => child.dataset.group),
      pendingText: els["settings-pending"].textContent,
      panelShown: !els["settings-panel"].hidden,
      consoleFlag: els["console"].dataset.settingsOpen,
    };
  },

  async H() {
    // 保存流程：确认框 → PUT（changes + fingerprint）→ 成功结果 + 「下一次运行生效」+ 徽标刷新。
    configWriteEnabled = true;
    await load();
    await openSettings();
    const iterationInput = findByDataset(findConfigRow("MAX_ITERATIONS"), "key", "MAX_ITERATIONS");
    const enumSelect = findByDataset(findConfigRow("CONTEXT_STRATEGY"), "key", "CONTEXT_STRATEGY");
    setInput(iterationInput, "30");
    const pendingAfterEdit = els["settings-pending"].textContent;
    const saveEnabledAfterEdit = !els["settings-save"].disabled;

    els["settings-save"].click();
    await settle();
    const confirmText = els["confirm-text"].textContent;
    const confirmShown = !els["confirm-overlay"].hidden;
    const putBeforeConfirm = callsMatching("PUT /api/projects/default/config").length;

    await clickOk();
    await settle(8);
    const badge = findByDataset(findConfigRow("MAX_ITERATIONS"), "key", "MAX_ITERATIONS");
    const row = findConfigRow("MAX_ITERATIONS");
    return {
      pendingAfterEdit,
      saveEnabledAfterEdit,
      confirmShown,
      confirmText,
      putBeforeConfirm,
      writeBody: world.lastWrite,
      resultHidden: els["settings-result"].hidden,
      resultState: els["settings-result"].dataset.state,
      resultText: els["settings-result"].textContent,
      statusText: els["settings-status"].textContent,
      rowValue: row ? row.children[1].textContent : null,
      rowSource: row ? row.children[0].children[1].textContent : null,
      inputAfterSave: badge ? badge.value : null,
      pendingAfterSave: els["settings-pending"].textContent,
      saveDisabledAfterSave: els["settings-save"].disabled,
      enumOptions: enumSelect ? enumSelect.children.map((option) => option.value) : null,
      enumValue: enumSelect ? enumSelect.value : null,
    };
  },

  async I() {
    // 保存失败：稳定码 → 文案；config_conflict 会自动重新加载面板。
    configWriteEnabled = true;
    await load();
    await openSettings();
    setInput(findByDataset(findConfigRow("MAX_ITERATIONS"), "key", "MAX_ITERATIONS"), "30");
    world.writeError = { status: 409, body: { error: { code: "config_conflict", message: "fingerprint mismatch" } } };
    els["settings-save"].click();
    await settle();
    await clickOk();
    await settle(8);
    const conflict = {
      resultState: els["settings-result"].dataset.state,
      resultText: els["settings-result"].textContent,
      statusText: els["settings-status"].textContent,
      reloads: callsMatching("GET /api/projects/default/config").length,
    };

    world.writeError = { status: 400, body: { error: { code: "invalid_value", message: "MAX_ITERATIONS: must be <= 100" } } };
    setInput(findByDataset(findConfigRow("MAX_ITERATIONS"), "key", "MAX_ITERATIONS"), "999");
    els["settings-save"].click();
    await settle();
    await clickOk();
    await settle(6);
    const invalidValue = els["settings-result"].textContent;

    world.writeError = { status: 403, body: { error: { code: "write_disabled", message: "config writing is disabled" } } };
    setInput(findByDataset(findConfigRow("MAX_ITERATIONS"), "key", "MAX_ITERATIONS"), "40");
    els["settings-save"].click();
    await settle();
    await clickOk();
    await settle(6);
    const gateClosed = els["settings-result"].textContent;

    world.writeError = null;
    return { conflict, invalidValue, gateClosed };
  },

  async J() {
    // 会话层：新建 / 重命名（确认框带输入）/ 删除（确认 + ?confirm=true）/ 损坏会话的区分处理。
    await load();
    els["session-create"].click();
    await settle(8);
    const created = findByDataset(els["session-list"], "sessionId", "s9");
    const createdActive = created ? created.dataset.active : null;
    const detailCalls = callsMatching("GET /api/projects/default/sessions/s9").length;

    sessionAction("s1", 0).click();
    await settle();
    const renamePrefill = els["confirm-input"].value;
    const renameShown = !els["confirm-input"].hidden;
    els["confirm-input"].value = "新标题";
    await clickOk();
    await settle(6);
    const renamed = findByDataset(els["session-list"], "sessionId", "s1");

    resetCalls();
    sessionAction("s1", 1).click();
    await settle();
    const deleteText = els["confirm-text"].textContent;
    await clickCancel();
    const afterCancel = {
      deletes: callsMatching("DELETE /api/projects/default/sessions/s1").length,
      stillListed: Boolean(findByDataset(els["session-list"], "sessionId", "s1")),
    };
    resetCalls();
    sessionAction("s1", 1).click();
    await settle();
    await clickOk();
    await settle(8);
    const afterDelete = {
      deletes: callsMatching("DELETE /api/projects/default/sessions/s1?confirm=true").length,
      stillListed: Boolean(findByDataset(els["session-list"], "sessionId", "s1")),
      listTitles: els["session-list"].children.map((child) => child.children[0].textContent),
    };

    // 损坏会话：列表仍要列出它（unreadable=true），打开时详情回 session_unreadable —— 绝不能显示成空会话。
    world.sessions.default = [session("sBad", "不可读会话", { unreadable: true, message_count: null })];
    await load();
    const badItem = findByDataset(els["session-list"], "sessionId", "sBad");
    const badFlag = badItem
      ? walkFind(badItem, (node) => node.dataset && node.dataset.unreadable === "true")
      : null;
    const badMetaBeforeOpen = badItem ? badItem.children[1].textContent : null;
    const autoOpened = els["chat-log"].children.length;
    badItem.children[0].click();
    await settle(6);
    return {
      createdShown: Boolean(created),
      createdActive,
      detailCalls,
      renameShown,
      renamePrefill,
      renamedTitle: renamed ? renamed.children[0].textContent : null,
      deleteText,
      afterCancel,
      afterDelete,
      badListed: Boolean(badItem),
      badFlagged: Boolean(badFlag),
      badMeta: badMetaBeforeOpen,
      badAutoOpened: autoOpened,
      badChatLines: lines(),
      badChatMeta: els["chat-meta"].textContent,
      badChatMetaState: els["chat-meta"].dataset.state,
      badSendDisabled: els["send-button"].disabled,
      badRunStatus: els["run-status"].textContent,
      badTitle: els["chat-title"].textContent,
    };
  },

  async K() {
    // 移除项目登记：二次确认文案说明「保留磁盘数据」；确认后带 ?confirm=true。
    await load();
    resetCalls();
    projectAction("pB", 1).click();
    await settle();
    const confirmShown = !els["confirm-overlay"].hidden;
    const confirmText = els["confirm-text"].textContent;
    const deletesBeforeConfirm = callsMatching("DELETE /api/projects/pB").length;
    await clickCancel();
    await settle();
    const afterCancel = {
      deletes: callsMatching("DELETE /api/projects/pB").length,
      stillListed: Boolean(findByDataset(els["project-list"], "projectId", "pB")),
    };
    projectAction("pB", 1).click();
    await settle();
    await clickOk();
    await settle(8);
    return {
      confirmShown,
      confirmText,
      deletesBeforeConfirm,
      afterCancel,
      afterRemove: {
        deletes: callsMatching("DELETE /api/projects/pB?confirm=true").length,
        stillListed: Boolean(findByDataset(els["project-list"], "projectId", "pB")),
        activeProject: els["active-project"].textContent,
      },
      defaultHasRemove: Boolean(projectAction("default", 1)),
    };
  },

  async L() {
    // 顶栏：侧栏收起/展开（窄屏降级时的可达性出口）。
    await load();
    els["sidebar-toggle"].click();
    await settle(2);
    const collapsed = {
      flag: els["console"].dataset.sidebarCollapsed,
      aria: els["sidebar-toggle"].getAttribute("aria-expanded"),
      label: els["sidebar-toggle"].textContent,
    };
    els["sidebar-toggle"].click();
    await settle(2);
    return {
      collapsed,
      expanded: {
        flag: els["console"].dataset.sidebarCollapsed,
        aria: els["sidebar-toggle"].getAttribute("aria-expanded"),
        label: els["sidebar-toggle"].textContent,
      },
    };
  },

  async M() {
    // 错误码映射：不同语义必须给不同文案；未知码回落到服务端文案。
    await load();
    resetCalls();
    const conflicts = [];
    const submitAndRead = async (routeHandler) => {
      net.routes.set("POST /api/projects/default/runs", routeHandler);
      await submit("x");
      return lines()[lines().length - 1];
    };
    conflicts.push({
      code: "run_conflict",
      text: await submitAndRead(() =>
        jsonResponse(409, { error: { code: "run_conflict", message: "a run is already in flight" } }),
      ),
    });
    conflicts.push({
      code: "project_unavailable",
      text: await submitAndRead(() =>
        jsonResponse(409, { error: { code: "project_unavailable", message: "project dir is gone" } }),
      ),
    });
    conflicts.push({
      code: "weird_code",
      text: await submitAndRead(() => jsonResponse(400, { error: { code: "weird_code", message: "server said boom" } })),
    });
    net.routes.set("POST", "/api/projects/default/runs");
    const callsAfterSubmitErrors = net.calls.length;

    world.sessions.default = [session("s1", "会话一")];
    route("DELETE", "/api/projects/default/sessions/s1?confirm=true", () =>
      jsonResponse(409, { error: { code: "session_busy", message: "session is in use by an in-flight run" } }),
    );
    await load();
    sessionAction("s1", 1).click();
    await settle();
    await clickOk();
    await settle(6);
    conflicts.push({ code: "session_busy", text: els["session-status"].textContent });

    route("PATCH", "/api/projects/default/sessions/s1", () =>
      jsonResponse(409, { error: { code: "session_conflict", message: "session changed on disk" } }),
    );
    world.details.s1 = { ...world.details.s1, status: null, run_id: null };
    sessionAction("s1", 0).click();
    await settle();
    await clickOk();
    await settle(6);
    conflicts.push({ code: "session_conflict", text: els["session-status"].textContent });

    route("DELETE", "/api/projects/pB?confirm=true", () =>
      jsonResponse(409, { error: { code: "project_busy", message: "project has a run in progress" } }),
    );
    projectAction("pB", 1).click();
    await settle();
    await clickOk();
    await settle(6);
    conflicts.push({ code: "project_busy", text: els["project-status"].textContent });

    route("POST", "/api/projects", () =>
      jsonResponse(400, { error: { code: "invalid_project_path", message: "path must be an existing directory" } }),
    );
    els["project-path"].value = "C:/nope";
    els["project-form"].requestSubmit();
    await settle(6);
    conflicts.push({ code: "invalid_project_path", text: els["project-status"].textContent });
    return { conflicts, callsAfterSubmitErrors, projectCalls: callsMatching("POST /api/projects").length };
  },

  async N() {
    // 写成功、但面板的后续刷新失败：写过的行**仍须**显示写响应里的写后事实（值 + 来源徽标），
    // 否则刷新失败时页面会退回旧值 = 对用户撒谎（而文件其实已经改了）。
    configWriteEnabled = true;
    await load();
    await openSettings();
    const before = findConfigRow("MAX_ITERATIONS");
    const sourceBefore = before.children[0].children[1].textContent;
    setInput(findByDataset(before, "key", "MAX_ITERATIONS"), "30");
    world.failConfigReadAfterWrite = true;
    els["settings-save"].click();
    await settle();
    await clickOk();
    await settle(10);
    const row = findConfigRow("MAX_ITERATIONS");
    const result = {
      sourceBefore,
      rowValue: row.children[1].textContent,
      rowSource: row.children[0].children[1].textContent,
      rowInput: findByDataset(row, "key", "MAX_ITERATIONS").value,
      resultState: els["settings-result"].dataset.state,
      resultText: els["settings-result"].textContent,
      statusState: els["settings-status"].dataset.state,
      statusText: els["settings-status"].textContent,
      pending: els["settings-pending"].textContent,
    };
    world.failConfigReadAfterWrite = false;
    world.configReadFails = false;
    return result;
  },

  async O() {
    // 遮罩「可见但没有 pending」（历史缺陷：CSS 的 `.overlay{display:flex}` 压过 hidden 属性，
    // 于是首页加载即弹出）时，点「取消 / 确认」都必须真的把它关掉。
    // settleConfirm 曾在隐藏遮罩**之前** return ⇒ 两个按钮永久失效、只能刷新页面脱身。
    await load();
    els["confirm-overlay"].hidden = false;
    await clickCancel();
    const afterCancel = els["confirm-overlay"].hidden;
    els["confirm-overlay"].hidden = false;
    await clickOk();
    const afterOk = els["confirm-overlay"].hidden;
    return { afterCancel, afterOk };
  },
};

function walkFind(root, predicate) {
  let found = null;
  walk(root, (node) => {
    if (!found && predicate(node)) found = node;
  });
  return found;
}
(async () => {
  const runner = CASES[CASE];
  if (!runner) throw new Error(`unknown case ${CASE}`);
  const result = await runner();
  console.log(`PROBE_RESULT ${JSON.stringify(result)}`);
})().catch((error) => {
  console.log(`PROBE_ERROR ${error && error.stack ? error.stack : String(error)}`);
  process.exitCode = 1;
});
