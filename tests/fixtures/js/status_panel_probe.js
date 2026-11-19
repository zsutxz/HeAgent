/* 服务器状态面板的渲染探针（Epic 71 评审 C1：`status-panel.js` 此前没有执行级测试）。
 *
 * `status-panel.js` 是 IIFE，内部状态无法从外部注入，因此这里用**最小 DOM 替身**加载真实脚本，喂一份
 * 完整 `StatusResponse` 形状的 payload（字段见 `network/http_protocol.py`），再由探针自己检查渲染结果：
 * 徽标里的模式 / uptime / 在途 run / WS 合计、五组页签的行值、null 资源显示「不可用」、失败保留上次值。
 *
 * 用法：node status_panel_probe.js <status-panel.js 路径> <index.html 路径>
 * 输出：一行 ``PROBE_RESULT {json}``；任一检查不符则 ``PROBE_ERROR …`` 且退出码 1
 *（由 tests/test_web_server_status_panel.py::TestStatusPanelProbe 解析）。
 *
 * 执行环境：**由有 node 的机器执行**；没有 node 的环境（本仓开发机实测 `which node` 无输出）按
 * `pytest.skip("node not installed")` 跳过，静态契约用例仍然生效。
 *
 * 保真边界（与 app_probe.js 同一套替身约定，误用会得到假绿）：
 * ① 没有 DOM 树：元素是**扁平注册表**（按 index.html 的 id 建），父子关系只对脚本自己 appendChild 的
 *    节点成立 ⇒ 别在这里验「某个 id 在某个容器内」；
 * ② 不含 HTML 的静态文本（`<summary>` 那段文字在替身里是空串）⇒ 静态文案断言请直接读 index.html；
 * ③ 没有 CSS ⇒ 布局、以及 `hidden` 与样式表的相互作用只能靠真浏览器；
 * ④ `children` 里可能有文本节点（真 DOM 只含元素）——本探针只读脚本自己建的节点，故不受影响。
 *
 * 替身的收窄前提：`status-panel.js` 只用 getElementById / createElement / createTextNode / textContent /
 * setAttribute / className / id / tabIndex / focus / click / addEventListener / replaceChildren / children /
 * dataset / title / hidden / `details.open` / `document.hidden` / `window.setTimeout|clearTimeout`。
 * `window.HePanels` 是**桩**（取数通路本身由 HTTP 层用例与 app_probe.js 覆盖），`window.setTimeout` 是
 * 空实现——探针不靠轮询推进，也不该被永不触发的定时器挂住进程。
 */
"use strict";

const fs = require("fs");

const SRC_PATH = process.argv[2];
const HTML_PATH = process.argv[3];
if (!SRC_PATH || !HTML_PATH) {
  console.log("PROBE_ERROR 用法：node status_panel_probe.js <status-panel.js 路径> <index.html 路径>");
  process.exit(1);
}

const src = fs.readFileSync(SRC_PATH, "utf8");
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
    title: "",
    tabIndex: 0,
    // 真 DOM 里 `<details>` 无 open 属性即收起；替身一律给这个属性，收起分支才可驱动。
    open: false,
    focused: false,
    _tc: null,
    appendChild(child) {
      this.children.push(child);
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

// 元素清单**从 index.html 解析**：脚本 getElementById 拿不到的 id 返回 null（不凭空造假元素），
// 因此「JS 引用了页面上不存在的 id」会立刻炸成 PROBE_ERROR，而不是静默通过。
const els = {};

for (const tag of html.match(/<[a-zA-Z][^>]*>/g) || []) {
  const nameMatch = /^<([a-zA-Z][a-zA-Z0-9]*)/.exec(tag);
  const idMatch = /\bid="([^"]+)"/.exec(tag);
  if (!nameMatch || !idMatch) continue;
  els[idMatch[1]] = makeEl(nameMatch[1].toLowerCase());
}
// 兜底：属性跨行的标签若被上一条正则切碎，这里仍然登记（否则脚本会认为元素缺失并静默什么都不做）。
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

// ── 面板公共桥替身 + 取数记录 ──

const net = { calls: [], reply: { status: 200, ok: true, payload: {} } };

global.window = {
  setTimeout: () => 0,
  clearTimeout: () => {},
  HePanels: {
    request: async (method, path) => {
      net.calls.push(method + " " + path);
      return net.reply;
    },
    describeFailure: (result) => "HTTP " + String((result && result.status) || 0),
    // 真实现走 `toLocaleString("zh-CN")`：断言不该依赖系统 locale ⇒ 桩只回原文（时间格式不在判据里）。
    formatTime: (value) => (value ? String(value) : "-"),
  },
};

// ── 一份完整 StatusResponse 形状的 payload（数值刻意互不相同，便于反查字段错位） ──

function statusPayload(overrides = {}) {
  return Object.assign(
    {
      service: "heagent-http",
      version: "9.9.9",
      schema_version: "1",
      active_runs: 3,
      max_inflight_runs: 2,
      run_records: 42,
      run_status: { running: 1, completed: 30, failed: 8, cancelled: 2, timed_out: 1 },
      ws_connections: { runs: 2, cli: 2, notifications: 1 },
      background_tasks: 4,
      listeners: [
        {
          kind: "http",
          label: "HTTP",
          host: "127.0.0.1",
          port: 9101,
          mode: "local",
          tls: { enabled: false, spki_sha256: null, short_fingerprint: null, not_after: null, san: null },
        },
        {
          kind: "ws",
          label: "WS",
          host: "127.0.0.1",
          port: 9201,
          mode: "external",
          tls: {
            enabled: true,
            spki_sha256: "d5af625c13e6bc95eac24f6c41f9e29c4ad06d97e48185bdeb80d635b95eacfb",
            short_fingerprint: "2WXW-EXAT-426J",
            not_after: "2036-11-16T13:40:49Z",
            san: ["IP:127.0.0.1", "DNS:localhost"],
          },
        },
      ],
      sandbox_backend: "local",
      config_write_enabled: false,
      active_provider: "gpt",
      routing_pools: [
        { pool: "default", tiers: ["fast", "mid", "pro"] },
        { pool: "empty", tiers: [] },
      ],
      started_at: "2026-11-20T02:00:00Z",
      uptime_seconds: 3725,
      cron_jobs: [
        { job_id: "1b45af3c", cron: "0 20 * * *", last_run: "2026-11-20T12:00:00Z", last_status: "success" },
      ],
      skill_count: 12,
      memory_facts: 34,
      rss_bytes: null,
      threads: null,
      cpu_seconds: 12.5,
      resource_source: "unavailable",
      requests: {
        total: 128,
        status_2xx: 111,
        status_3xx: 4,
        status_4xx: 11,
        status_5xx: 2,
        latency_p50_ms: 7.4,
        latency_max_ms: 812.6,
        error_codes: [{ code: "not_found", count: 9 }],
      },
    },
    overrides,
  );
}

// ── 驱动与观察工具 ──

const tick = () => new Promise((resolve) => setImmediate(resolve));

async function settle(count = 8) {
  for (let index = 0; index < count; index += 1) await tick();
}

/** 一次「页面载入」：重新执行脚本，得到干净的闭包状态（旧实例的 handlers 被新实例覆盖）。 */
async function loadPage(payload) {
  net.reply = { status: 200, ok: true, elapsed: 1, payload: payload, text: "" };
  // eslint-disable-next-line no-new-func
  new Function(src)();
  await settle();
}

function tablistEl() {
  return mustEl("server-groups").children.find((node) => node && node.className === "status-tabs") || null;
}

function tabpanelEl() {
  return mustEl("server-groups").children.find((node) => node && node.id === "server-tabpanel") || null;
}

/** 当前页签的行表读成 `[label, value]` 对（脚本按 dt/dd 交替 append，配对关系是它自己的不变量）。 */
function rows() {
  const panel = tabpanelEl();
  if (!panel || panel.children.length === 0) return [];
  const list = panel.children[0];
  const pairs = [];
  for (let index = 0; index + 1 < list.children.length; index += 2) {
    pairs.push([list.children[index].textContent, list.children[index + 1].textContent]);
  }
  return pairs;
}

function rowValue(label) {
  const found = rows().find((pair) => pair[0] === label);
  return found ? found[1] : null;
}

function labels() {
  return rows().map((pair) => pair[0]);
}

function tabTitles() {
  const list = tablistEl();
  return list ? list.children.map((tab) => tab.textContent) : [];
}

function selectTab(title) {
  const list = tablistEl();
  const index = list ? list.children.findIndex((tab) => tab.textContent === title) : -1;
  if (index < 0) throw new Error("找不到页签：" + title);
  list.children[index].click();
  return index;
}

const checks = [];

function check(name, actual, expected) {
  checks.push({
    name: name,
    passed: JSON.stringify(actual) === JSON.stringify(expected),
    actual: actual,
    expected: expected,
  });
}

(async () => {
  const observed = {};

  // ── 场景 1：完整快照（回环 HTTP + 对外 WS，两个路由池）──
  mustEl("server-details").open = true;
  await loadPage(statusPayload());

  observed.badge = mustEl("server-status").textContent;
  observed.badgeState = mustEl("server-status").dataset.state;
  observed.tabs = tabTitles();
  observed.calls = net.calls.slice();

  check("徽标：模式 · uptime · 在途 run · WS 合计", observed.badge, "对外 · up 1h2m · run 3 · WS 5");
  check("徽标就绪态", observed.badgeState, "ready");
  check("五个页签的标题与顺序", observed.tabs, ["运行态", "部署面", "依赖态", "资源", "请求计数"]);
  check("取数只打 GET /api/status（一次页面载入一次）", observed.calls, ["GET /api/status"]);

  // 运行态（默认选中组）
  observed.runRows = rows();
  check("在途 run（服务级）", rowValue("在途 run（服务级）"), "3");
  check("单项目并发上限不与在途数成比率", rowValue("单项目并发上限"), "2");
  check("run 记录数", rowValue("run 记录数"), "42");
  check(
    "运行记录按状态分布",
    [rowValue("运行中"), rowValue("已完成"), rowValue("失败"), rowValue("已取消"), rowValue("已超时")],
    ["1", "30", "8", "2", "1"],
  );
  check("WS 连接三分项", rowValue("WS 连接（run / cli / 通知）"), "2 / 2 / 1");
  check("后台任务", rowValue("后台任务"), "4");

  // 部署面
  selectTab("部署面");
  observed.deploymentRows = rows();
  check("回环 HTTP listener 行", rowValue("HTTP"), "http 127.0.0.1:9101 · local");
  check("对外 WS listener 行带 TLS 标记", rowValue("WS"), "ws 127.0.0.1:9201 · external · TLS");
  check("TLS 身份行：短指纹与到期日", rowValue("TLS"), "wss · pin 2WXW-EXAT-426J · 到期 2036-11-16");
  check("明文 listener 不出身份行", labels().filter((label) => label === "TLS").length, 1);
  check("沙箱后端", rowValue("沙箱后端"), "local");
  check("配置写入关闭即「只读」", rowValue("配置写入"), "只读");
  check("当前 provider", rowValue("当前 provider"), "gpt");
  check("路由池档位", rowValue("路由池 default"), "fast / mid / pro");
  check("空档位池不留空白", rowValue("路由池 empty"), "无档位");

  // 依赖态
  selectTab("依赖态");
  observed.dependencyRows = rows();
  check("统计范围先标注", rowValue("统计范围"), "本进程工作区");
  check("uptime 粗粒度格式", rowValue("uptime"), "1h2m");
  check("cron 作业条数", rowValue("cron 作业"), "1 条");
  check("技能数与记忆条目", [rowValue("技能数"), rowValue("记忆条目")], ["12", "34"]);
  check("作业行含 cron · 末次状态 · 末次时刻", rowValue("作业 1b45af3c"), "0 20 * * * · success · 2026-11-20T12:00:00Z");

  // 资源：不可得即「不可用」，绝不填 0
  selectTab("资源");
  observed.resourceRows = rows();
  check("RSS 采样不可得", rowValue("RSS"), "不可用");
  check("线程数不可得", rowValue("线程数"), "不可用");
  check("CPU 时间", rowValue("CPU 时间"), "12.5 s");
  check("采样通路如实标注", rowValue("采样通路"), "unavailable");
  check("资源组固定四行", labels().length, 4);

  // 请求计数
  selectTab("请求计数");
  observed.requestRows = rows();
  check("请求总数", rowValue("请求总数"), "128");
  check("2xx / 3xx 用实际数字", rowValue("2xx / 3xx"), "111 / 4");
  check("4xx / 5xx 用实际数字", rowValue("4xx / 5xx"), "11 / 2");
  check("延迟 p50 / max 保留毫秒单位", rowValue("延迟 p50 / max"), "7 ms / 813 ms");
  check("错误码计数", rowValue("错误码"), "not_found×9");

  // 键盘导航：Home/End 到两端、方向键回绕，焦点与 aria-selected 跟着走
  const tablist = tablistEl();
  selectTab("资源");
  tablist.dispatchEvent({ type: "keydown", key: "End", preventDefault() {} });
  observed.afterEnd = [
    labels()[0],
    tablist.children[4].attributes["aria-selected"],
    Boolean(tablist.children[4].focused),
  ];
  check("End 键选中末组", observed.afterEnd, ["请求总数", "true", true]);

  tablist.dispatchEvent({ type: "keydown", key: "ArrowRight", preventDefault() {} });
  observed.afterWrap = [labels()[0], tablist.children[0].attributes["aria-selected"]];
  check("ArrowRight 从末组回绕到首组", observed.afterWrap, ["在途 run（服务级）", "true"]);

  // ── 场景 2：没有任何 listener ⇒ 模式「未暴露」，部署面没有 listener 行 ──
  await loadPage(statusPayload({ listeners: [] }));
  observed.unexposedBadge = mustEl("server-status").textContent;
  selectTab("部署面");
  observed.unexposedDeploymentLabels = labels();
  check("无 listener ⇒ 徽标模式为「未暴露」", observed.unexposedBadge, "未暴露 · up 1h2m · run 3 · WS 5");
  check("无 listener ⇒ 部署面首行是沙箱后端", observed.unexposedDeploymentLabels[0], "沙箱后端");

  // ── 场景 3：取数失败（HTTP 错误是结果，不抛）⇒ 保留上次值 + 标离线 ──
  net.reply = { status: 500, ok: false, elapsed: 1, payload: { error: { code: "internal", message: "boom" } } };
  if (!documentHandlers.visibilitychange) {
    throw new Error("脚本没有注册 visibilitychange 处理（可见性轮询契约缺失）");
  }
  documentHandlers.visibilitychange();
  await settle();

  check("失败：徽标标离线", mustEl("server-status").dataset.state, "offline");
  check("失败：状态行显示错误映射", mustEl("server-panel-status").textContent, "HTTP 500");
  check("失败：状态行标 failed", mustEl("server-panel-status").dataset.state, "failed");
  check("失败：徽标文案保留上次值", mustEl("server-status").textContent, "未暴露 · up 1h2m · run 3 · WS 5");
  check("失败：已渲染的行不被清空", labels()[0], "沙箱后端");

  const failed = checks.filter((item) => !item.passed);
  if (failed.length > 0) {
    console.log("PROBE_ERROR " + JSON.stringify(failed));
    process.exitCode = 1;
    return;
  }
  console.log("PROBE_RESULT " + JSON.stringify({ checks: checks.length, observed: observed }));
})().catch((error) => {
  console.log("PROBE_ERROR " + (error && error.stack ? error.stack : String(error)));
  process.exitCode = 1;
});
