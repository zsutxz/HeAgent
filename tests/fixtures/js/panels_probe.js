/* 面板层的行为探针（Epic 70 评审：tasks.js / api-console.js 此前只有源码级静态契约）。
 *
 * 三个面板脚本都是 IIFE，内部状态无法从外部注入，因此这里用**最小 DOM 替身 + 可控定时器 + fetch 替身**
 * 加载**真实的** `panels.js` / `tasks.js` / `api-console.js`，驱动真实分支并打印可观察结果。
 *
 * 用法：node panels_probe.js <tasks.js> <api-console.js> <panels.js> <index.html> <CASE>
 * 输出：一行 ``PROBE_RESULT {json}``；异常则 ``PROBE_ERROR …`` 且退出码 1
 *（由 tests/test_web_tasks_panel.py / tests/test_web_api_console.py 的探针用例解析）。
 *
 * 用例：
 *   tasks-list        任务列表渲染与轮询启停、详情 404 文案、列表 500 不清空已渲染内容
 *   tasks-visibility  标签页不可见即停表，恢复可见立刻补一次
 *   api-get           GET 成功（状态码 + 耗时 + 格式化 JSON）与 400 错误信封（code: message）
 *   api-guard         本地拦截：路径不以 / 开头 / 请求体非 JSON / 占位符未替换 ⇒ 一个请求都不发
 *   api-confirm       写方法二次确认：取消不发、确认才发；预置按钮只填表单不发送
 *
 * 保真边界（与 app_probe.js / status_panel_probe.js 同一套约定，误用会得到假绿）：
 * ① 没有 DOM 树：元素是**扁平注册表**（按 index.html 的 id 建）⇒ 别在这里验嵌套关系；
 * ② 不含 HTML 静态文本；③ 没有 CSS（`hidden` 与样式表的相互作用只能靠真浏览器）；
 * ④ 定时器是**手动推进**的：只有 `pendingTimers()` 与 `fireTimers()` 证明「排程 / 停表」，不代表真实时长。
 */
"use strict";

const fs = require("fs");

const TASKS_PATH = process.argv[2];
const APICONSOLE_PATH = process.argv[3];
const PANELS_PATH = process.argv[4];
const HTML_PATH = process.argv[5];
const CASE = process.argv[6] || "tasks-list";

if (!TASKS_PATH || !APICONSOLE_PATH || !PANELS_PATH || !HTML_PATH) {
  console.log("PROBE_ERROR 用法：node panels_probe.js <tasks.js> <api-console.js> <panels.js> <index.html> <CASE>");
  process.exit(1);
}

const sources = {
  tasks: fs.readFileSync(TASKS_PATH, "utf8"),
  apiConsole: fs.readFileSync(APICONSOLE_PATH, "utf8"),
  panels: fs.readFileSync(PANELS_PATH, "utf8"),
};
const html = fs.readFileSync(HTML_PATH, "utf8");

// ── 最小 DOM 替身 ──

function createTextNode(value) {
  return { text: String(value) };
}

function makeEl(tagName) {
  const el = {
    tagName: tagName,
    id: "",
    className: "",
    children: [],
    dataset: {},
    attributes: {},
    handlers: {},
    hidden: false,
    disabled: false,
    title: "",
    value: "",
    tabIndex: 0,
    focused: false,
    _tc: null,
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    removeChild(child) {
      const index = this.children.indexOf(child);
      if (index >= 0) this.children.splice(index, 1);
      return child;
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
    addEventListener(kind, fn) {
      this.handlers[kind] = fn;
    },
    dispatchEvent(event) {
      const fn = this.handlers[event && event.type];
      if (fn) fn(event);
      return true;
    },
    click() {
      const fn = this.handlers.click;
      if (fn) fn({ type: "click" });
    },
    focus() {
      this.focused = true;
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

const els = {};
for (const tag of html.match(/<[a-zA-Z][^>]*>/g) || []) {
  const nameMatch = /^<([a-zA-Z][a-zA-Z0-9]*)/.exec(tag);
  const idMatch = /\bid="([^"]+)"/.exec(tag);
  if (!nameMatch || !idMatch) continue;
  els[idMatch[1]] = makeEl(nameMatch[1].toLowerCase());
}
for (const match of html.match(/id="([^"]+)"/g) || []) {
  const id = match.slice(4, match.length - 1);
  if (!Object.prototype.hasOwnProperty.call(els, id)) els[id] = makeEl("div");
}

function mustEl(id) {
  const node = els[id];
  if (!node) throw new Error("从 index.html 解析不到 #" + id + "（页面结构变了？）");
  return node;
}

const documentHandlers = {};
global.document = {
  hidden: false,
  createElement: (tagName) => makeEl(tagName),
  createTextNode: createTextNode,
  getElementById: (id) => (Object.prototype.hasOwnProperty.call(els, id) ? els[id] : null),
  addEventListener(kind, fn) {
    documentHandlers[kind] = fn;
  },
};

// ── 可控定时器：只有显式推进才走下一轮（真实时长不在判据里） ──

const timers = { queue: new Map(), nextId: 1 };

function pendingTimers() {
  return timers.queue.size;
}

async function fireTimers() {
  const pending = Array.from(timers.queue.values());
  timers.queue.clear();
  for (const timer of pending) timer.fn();
  await settle();
}

// ── fetch 替身：按「方法 + 路径」路由；未注册的路由回 404（与 app_probe.js 同一约定） ──

const net = { calls: [], routes: new Map() };

function route(method, path, handler) {
  net.routes.set(method + " " + path, handler);
}

function response(status, payload) {
  return {
    ok: status < 400,
    status: status,
    text: async () => (payload === undefined ? "" : JSON.stringify(payload)),
  };
}

function resetCalls() {
  net.calls.length = 0;
}

function callsMatching(pattern) {
  return net.calls.filter((call) => call.includes(pattern));
}

// ── 浏览器面替身（panels.js 需要 localStorage / performance / fetch） ──

const store = new Map();
const clock = { ms: 1000 };
const confirm = { answer: true, prompts: [] };

global.fetch = async (url, options = {}) => {
  const method = (options.method || "GET").toUpperCase();
  net.calls.push(method + " " + url);
  const handler = net.routes.get(method + " " + url);
  if (!handler) return response(404, { error: { code: "not_found", message: "no route for " + method + " " + url } });
  return handler(options, url);
};

const windowHandlers = {};
global.window = {
  setTimeout: (fn, ms) => {
    const id = timers.nextId++;
    timers.queue.set(id, { fn: fn, ms: ms });
    return id;
  },
  clearTimeout: (id) => {
    timers.queue.delete(id);
  },
  confirm: (text) => {
    confirm.prompts.push(String(text));
    return confirm.answer;
  },
  performance: {
    now: () => {
      clock.ms += 12; // 每次读表前进 12ms ⇒ 耗时是确定值，可断言
      return clock.ms;
    },
  },
  location: { hash: "" },
  localStorage: {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  },
  addEventListener: (kind, fn) => {
    windowHandlers[kind] = fn;
  },
};

// ── 驱动工具 ──

const tick = () => new Promise((resolve) => setImmediate(resolve));

async function settle(count = 8) {
  for (let index = 0; index < count; index += 1) await tick();
}

/** 载入顺序与 index.html 一致：公共桥在前，面板脚本各自独立。 */
async function loadPage(scripts) {
  // eslint-disable-next-line no-new-func
  new Function(sources.panels)();
  await settle(2);
  for (const name of scripts) {
    // eslint-disable-next-line no-new-func
    new Function(name === "tasks" ? sources.tasks : sources.apiConsole)();
    await settle(2);
  }
}

function fire(node, kind) {
  node.dispatchEvent({ type: kind, preventDefault() {} });
}

function taskRows() {
  return mustEl("task-list").children.map((row) => ({
    state: row.dataset.state,
    title: row.children[0] ? row.children[0].textContent : "",
    meta: row.children[1] ? row.children[1].textContent : "",
  }));
}

function taskDetailRows() {
  const detail = mustEl("task-detail");
  const list = detail.children[0];
  if (!list) return [];
  const pairs = [];
  for (let index = 0; index + 1 < list.children.length; index += 2) {
    pairs.push([list.children[index].textContent, list.children[index + 1].textContent]);
  }
  return pairs;
}

function taskDetailValue(label) {
  const found = taskDetailRows().find((pair) => pair[0] === label);
  return found ? found[1] : null;
}

function taskPayload(tasks) {
  return { tasks: tasks };
}

function task(id, status, percent, extra = {}) {
  return Object.assign(
    {
      task_id: id,
      kind: "context_compression",
      status: status,
      percent: percent,
      message: null,
      started_at: "2026-11-20T02:00:00Z",
      updated_at: "2026-11-20T02:01:00Z",
    },
    extra,
  );
}

function apiForm() {
  return mustEl("api-form");
}

function apiPath(value) {
  mustEl("api-path").value = value;
}

function apiMethod(value) {
  mustEl("api-method").value = value;
}

function apiBody(value) {
  mustEl("api-body").value = value;
}

async function apiSend() {
  fire(apiForm(), "submit");
  await settle(6);
}

const results = {};

function caseTasksList() {
  const both = () =>
    response(200, taskPayload([task("t1", "running", 42, { message: "压缩中" }), task("t2", "completed", 100)]));
  route("GET", "/api/tasks", both);
  return (async () => {
    await loadPage(["tasks"]);
    const first = {
      rows: taskRows(),
      emptyHintHidden: mustEl("task-empty").hidden,
      status: mustEl("task-status").textContent,
      timers: pendingTimers(),
    };

    // 列表 500：状态行报错并继续排程（失败时没有可信快照，已渲染的行保持上一次的事实）。
    route("GET", "/api/tasks", () => response(500, { error: { code: "server_error", message: "request failed" } }));
    await fireTimers();
    const afterFailure = {
      status: mustEl("task-status").textContent,
      state: mustEl("task-status").dataset.state,
      rows: taskRows().length,
      timers: pendingTimers(),
    };

    // 空列表：空态文案出现，且不再排程。
    route("GET", "/api/tasks", () => response(200, taskPayload([])));
    await fireTimers();
    const afterEmpty = {
      rows: taskRows().length,
      emptyHintShown: mustEl("task-empty").hidden === false,
      timers: pendingTimers(),
    };

    // 重新载入页面，验「全终态即停表」与详情两条路径（停表后就没有下一轮可推了）。
    route("GET", "/api/tasks", both);
    await loadPage(["tasks"]);
    route("GET", "/api/tasks", () => response(200, taskPayload([task("t2", "completed", 100)])));
    const beforeTerminal = pendingTimers();
    await fireTimers();
    const afterTerminal = {
      rows: taskRows().length,
      timers: pendingTimers(),
      armedBefore: beforeTerminal,
    };

    // 详情 404：详情区自己说清楚，列表不被牵连。
    route("GET", "/api/tasks/t2", () => response(404, { error: { code: "not_found", message: "no such task" } }));
    mustEl("task-list").children[0].click();
    await settle(6);
    const detail404 = {
      text: mustEl("task-detail").textContent,
      state: mustEl("task-detail").dataset.state,
      rows: taskRows().length,
    };

    // 详情成功：percent 带百分号、状态用中文文案。
    route("GET", "/api/tasks/t2", () => response(200, task("t2", "completed", 100)));
    mustEl("task-list").children[0].click();
    await settle(6);
    const detailOk = { percent: taskDetailValue("进度"), status: taskDetailValue("状态") };

    return { first, afterFailure, afterEmpty, afterTerminal, detail404, detailOk };
  })();
}

function caseTasksVisibility() {
  route("GET", "/api/tasks", () => response(200, taskPayload([task("t1", "running", 10)])));
  return (async () => {
    await loadPage(["tasks"]);
    const armed = pendingTimers();

    global.document.hidden = true;
    documentHandlers.visibilitychange();
    await settle(2);
    const whenHidden = { timers: pendingTimers(), calls: callsMatching("GET /api/tasks").length };

    global.document.hidden = false;
    documentHandlers.visibilitychange();
    await settle(6);
    const whenVisible = { timers: pendingTimers(), calls: callsMatching("GET /api/tasks").length, rows: taskRows().length };

    return { armed, whenHidden, whenVisible };
  })();
}

function caseApiGet() {
  route("GET", "/api/health", () => response(200, { status: "ok", service: "heagent-http" }));
  return (async () => {
    await loadPage(["apiConsole"]);
    apiMethod("GET");
    apiPath("/api/health");
    await apiSend();
    const ok = {
      output: mustEl("api-output").textContent,
      status: mustEl("api-status").textContent,
      state: mustEl("api-status").dataset.state,
    };

    route("GET", "/api/typo", () => response(400, { error: { code: "bad_request", message: "path is required" } }));
    apiPath("/api/typo");
    await apiSend();
    const bad = {
      output: mustEl("api-output").textContent,
      status: mustEl("api-status").textContent,
      state: mustEl("api-status").dataset.state,
    };
    return { ok, bad };
  })();
}

function caseApiGuard() {
  route("GET", "/api/projects", () => response(200, []));
  return (async () => {
    await loadPage(["apiConsole"]);
    apiMethod("GET");

    resetCalls();
    apiPath("api/projects"); // 少了前导 /
    await apiSend();
    const noLeadingSlash = { calls: net.calls.length, status: mustEl("api-status").textContent };

    resetCalls();
    apiPath("/api/projects/{project_id}"); // 占位符未替换
    await apiSend();
    const placeholder = { calls: net.calls.length, status: mustEl("api-status").textContent };

    resetCalls();
    apiPath("/api/projects");
    apiMethod("PATCH");
    confirm.answer = true;
    apiBody("{not json");
    await apiSend();
    const badBody = { calls: net.calls.length, status: mustEl("api-status").textContent };

    return { noLeadingSlash, placeholder, badBody };
  })();
}

function caseApiConfirm() {
  route("POST", "/api/projects", () => response(200, { id: "pX" }));
  return (async () => {
    await loadPage(["apiConsole"]);
    apiMethod("POST");
    apiPath("/api/projects");
    apiBody('{"path":"C:/ws"}');

    resetCalls();
    confirm.answer = false;
    await apiSend();
    const cancelled = { calls: net.calls.length, status: mustEl("api-status").textContent, prompts: confirm.prompts.length };

    resetCalls();
    confirm.answer = true;
    await apiSend();
    const accepted = {
      calls: net.calls.length,
      posted: callsMatching("POST /api/projects").length,
      status: mustEl("api-status").textContent,
    };

    // 预置按钮：只填表单，不发请求。
    resetCalls();
    const presets = mustEl("api-presets").children;
    presets[0].click();
    await settle(2);
    const preset = {
      count: presets.length,
      firstLabel: presets[0].textContent,
      method: mustEl("api-method").value,
      path: mustEl("api-path").value,
      calls: net.calls.length,
    };
    return { cancelled, accepted, preset };
  })();
}

const CASES = {
  "tasks-list": caseTasksList,
  "tasks-visibility": caseTasksVisibility,
  "api-get": caseApiGet,
  "api-guard": caseApiGuard,
  "api-confirm": caseApiConfirm,
};

(async () => {
  const runner = CASES[CASE];
  if (!runner) throw new Error("未知用例：" + CASE);
  const result = await runner();
  console.log("PROBE_RESULT " + JSON.stringify(Object.assign({ case: CASE }, result)));
})().catch((error) => {
  console.log("PROBE_ERROR " + (error && error.stack ? error.stack : String(error)));
  process.exit(1);
});
