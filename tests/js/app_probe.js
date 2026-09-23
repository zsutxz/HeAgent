/* 内置网页的行为探针（Epic 49 评审修复回归）。
 *
 * app.js 是一个 IIFE，内部状态不可从外部注入，因此这里用**最小 DOM / EventSource / fetch 替身**
 * 加载真实脚本，再驱动真实分支（提交 → SSE 事件 → 重连 → 刷新载入）并打印可观察结果。这样前端
 * 契约就不再只能靠「字符串是否出现在源码里」来证明。
 *
 * 用法：node app_probe.js <app.js 路径> <A|B|C|D|E>
 * 输出：一行 ``PROBE_RESULT {json}``（由 tests/test_http_web_ui.py 解析并断言）。
 */
"use strict";

const fs = require("fs");

const SRC_PATH = process.argv[2];
const CASE = process.argv[3] || "A";
const src = fs.readFileSync(SRC_PATH, "utf8");

function createTextNode(value) {
  return { text: String(value) };
}

function makeEl(tag) {
  const el = {
    tagName: tag,
    children: [],
    dataset: {},
    className: "",
    hidden: false,
    disabled: false,
    value: "",
    scrollTop: 0,
    scrollHeight: 0,
    _tc: null,
    _handlers: {},
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    removeChild(child) {
      const index = this.children.indexOf(child);
      if (index >= 0) this.children.splice(index, 1);
      return child;
    },
    get firstChild() {
      return this.children.length ? this.children[0] : null;
    },
    replaceChildren(...nodes) {
      this.children = [];
      this._tc = null;
      for (const node of nodes) this.appendChild(node);
    },
    addEventListener(kind, fn) {
      this._handlers[kind] = fn;
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

const els = {};
for (const id of [
  "service-status",
  "chat-log",
  "empty-state",
  "prompt-form",
  "prompt-input",
  "send-button",
  "stop-button",
  "run-status",
]) {
  els[id] = makeEl(id);
}

global.document = {
  createElement: (tag) => makeEl(tag),
  createTextNode,
  getElementById: (id) => els[id] || null,
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
global.window = { setInterval: () => 0 };

const net = {
  session: { ok: true, body: { session_id: "s", run_id: null, status: null, messages: [] } },
  runs: { ok: true, body: { run_id: "run-1", status: "running" } },
  calls: [],
};
global.fetch = async (url, options = {}) => {
  net.calls.push(`${options.method || "GET"} ${url}`);
  const pick = url === "/api/session" ? net.session : url === "/api/runs" ? net.runs : { ok: true, body: {} };
  return {
    ok: pick.ok,
    status: pick.status || (pick.ok ? 200 : 500),
    json: async () => pick.body,
  };
};

const tick = () => new Promise((resolve) => setImmediate(resolve));
const lines = () => els["chat-log"].children.map((child) => child.textContent);

async function load() {
  // 每次用例都重新执行脚本，得到干净的闭包状态（模拟一次页面载入）。
  // eslint-disable-next-line no-new-func
  new Function(src)();
  await tick();
  await tick();
}

async function submit(text) {
  els["prompt-input"].value = text;
  els["prompt-form"].requestSubmit();
  await tick();
}

/** 在输入框上敲一次 Enter，返回「是否被 preventDefault」（= 是否吞掉了浏览器默认行为）。 */
async function pressEnter(overrides = {}) {
  const handler = els["prompt-input"]._handlers.keydown;
  if (!handler) throw new Error("app.js 未注册 prompt-input 的 keydown 监听");
  let prevented = false;
  handler({
    key: "Enter",
    preventDefault() {
      prevented = true;
    },
    ...overrides,
  });
  await tick();
  await tick();
  return prevented;
}

function postedRuns() {
  return net.calls.some((call) => call.startsWith("POST /api/runs"));
}

(async () => {
  let result = {};
  if (CASE === "A") {
    // 同名工具连续两次调用：两次 tool_result 必须各归其行，先到先配。
    await load();
    await submit("hi");
    const stream = sources[sources.length - 1];
    stream.emit("tool_call", { kind: "tool_call", tool_name: "shell", tool_target: "pytest -q" });
    stream.emit("tool_call", { kind: "tool_call", tool_name: "shell", tool_target: "mypy src" });
    stream.emit("tool_result", { kind: "tool_result", tool_name: "shell", tool_output: "first result", tool_error: false });
    stream.emit("tool_result", { kind: "tool_result", tool_name: "shell", tool_output: "second result", tool_error: false });
    result = { pairing: lines().filter((line) => line.includes("shell")) };
  } else if (CASE === "B") {
    // 连接中断后重新同步，而服务端事实是 completed：状态文案必须与服务端一致。
    net.session = {
      ok: true,
      body: { session_id: "s", run_id: "run-1", status: "completed", messages: [{ role: "assistant", text: "答" }] },
    };
    await load();
    await submit("hi");
    sources[sources.length - 1].emit("error", {});
    await tick();
    await tick();
    result = { state: els["run-status"].dataset.state, text: els["run-status"].textContent };
  } else if (CASE === "C") {
    // 载入时服务端仍有在途运行：页面必须接手该运行的事件流，而不是显示「空闲」。
    net.session = { ok: true, body: { session_id: "s", run_id: "run-9", status: "running", messages: [] } };
    await load();
    result = {
      state: els["run-status"].dataset.state,
      text: els["run-status"].textContent,
      sendDisabled: els["send-button"].disabled,
      stopDisabled: els["stop-button"].disabled,
      subscribed: sources.length ? sources[sources.length - 1].url : null,
    };
  } else if (CASE === "D") {
    // 已有在途运行时的再次提交：不得静默吞掉（要有可读原因、且不真的发请求）。
    await load();
    await submit("first");
    net.calls.length = 0;
    const before = els["chat-log"].children.length;
    await submit("second");
    result = {
      newEntries: els["chat-log"].children.length - before,
      posted: net.calls.some((call) => call.startsWith("POST /api/runs")),
      lastLine: lines()[lines().length - 1],
    };
  } else if (CASE === "E") {
    // 键盘语义：Enter 发送 / Shift+Enter 换行（不吞默认行为）/ 组合输入（IME）不发送。
    await load();
    els["prompt-input"].value = "靠回车发送";
    const enterPrevented = await pressEnter();
    const enterPosted = postedRuns();
    const enterCleared = els["prompt-input"].value === "";

    net.calls.length = 0;
    await load();
    els["prompt-input"].value = "想在这里换行";
    const shiftPrevented = await pressEnter({ shiftKey: true });
    const shiftPosted = postedRuns();
    const shiftValue = els["prompt-input"].value;

    net.calls.length = 0;
    await load();
    els["prompt-input"].value = "选词中的回车";
    const composingPrevented = await pressEnter({ isComposing: true });
    const composingPosted = postedRuns();

    result = {
      enterPrevented,
      enterPosted,
      enterCleared,
      shiftPrevented,
      shiftPosted,
      shiftValue,
      composingPrevented,
      composingPosted,
    };
  }
  console.log(`PROBE_RESULT ${JSON.stringify(result)}`);
})().catch((error) => {
  console.log(`PROBE_ERROR ${error && error.stack ? error.stack : String(error)}`);
  process.exitCode = 1;
});
