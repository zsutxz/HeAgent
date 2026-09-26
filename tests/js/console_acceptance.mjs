#!/usr/bin/env node
/* 内置网页控制台的**真实浏览器**验收驱动（Epic 50 Story 50-6 的 T8/T10）。
 *
 * 与 `app_probe.js` 的分工：探针用最小 DOM 替身在 node 里跑真实 app.js（快、确定性、进 CI）；
 * 本脚本起**真实 http-server** + **真实 headless Chrome**（CDP 驱动真实点击），因此能验证只有真浏览器
 * 才能证明的东西：CSP 是否真的生效、有没有第三方请求、console 有没有报错、窄屏计算样式、以及
 * 「点击 → 请求 → 磁盘文件真的变了」这条端到端链路。
 *
 * 用法：
 *   node tests/js/console_acceptance.mjs [--port 8917] [--python python] [--chrome <路径>] [--keep]
 *
 * 输出：一张 markdown 表格（页面 → 步骤 → 期望 → 实测）与一行 `ACCEPTANCE {json}` 汇总；
 * 任何一行失败即退出码 1。截图落在临时工作区里（路径打印在输出里）。
 *
 * **不做**的事：不跑真实 LLM 运行（本机没有可用 provider），因此「流式回答」的浏览器观感不在本清单里
 * ——那部分由 node 探针（SSE 文本/工具配对/停止/重连）与 49 的服务端用例覆盖，缺口如实记录在 story 里。
 */
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// ── 参数与外部依赖发现 ──

function parseArgs(argv) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    const key = token.slice(2);
    const next = argv[index + 1];
    if (next === undefined || next.startsWith("--")) parsed[key] = true;
    else {
      parsed[key] = next;
      index += 1;
    }
  }
  return parsed;
}

const args = parseArgs(process.argv.slice(2));
const PORT = Number(args.port || 8917);
const CHROME_CANDIDATES = [
  process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].filter(Boolean);
const CHROME = typeof args.chrome === "string" ? args.chrome : CHROME_CANDIDATES.find((path) => existsSync(path));
const PYTHON = typeof args.python === "string" ? args.python : process.env.HEAGENT_PYTHON || "python";

if (!CHROME) {
  console.error("找不到 Chrome/Edge：用 --chrome <路径> 或设置 CHROME_PATH");
  process.exit(2);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ── 极简 CDP 客户端（node 22+ 自带 WebSocket） ──

function connect(wsUrl) {
  const socket = new WebSocket(wsUrl);
  let nextId = 0;
  const pending = new Map();
  const listeners = new Map();
  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.id && pending.has(payload.id)) {
      const { resolve, reject } = pending.get(payload.id);
      pending.delete(payload.id);
      if (payload.error) reject(new Error(JSON.stringify(payload.error)));
      else resolve(payload.result);
      return;
    }
    const handlers = listeners.get(payload.method) || [];
    for (const handler of handlers) handler(payload.params);
  });
  const ready = new Promise((resolve) => socket.addEventListener("open", resolve));
  return {
    ready,
    send(method, params = {}) {
      nextId += 1;
      const id = nextId;
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        socket.send(JSON.stringify({ id, method, params }));
      });
    },
    on(method, handler) {
      listeners.set(method, [...(listeners.get(method) || []), handler]);
    },
    close: () => socket.close(),
  };
}

// ── 工作区与服务器 ──

const workspace = mkdtempSync(join(tmpdir(), "heagent-console-"));
const closedWorkspace = join(workspace, "gate-closed");
const projectB = join(workspace, "project-b");
mkdirSync(projectB, { recursive: true });
mkdirSync(closedWorkspace, { recursive: true });

const MARKER = "sk-live-MARKER-must-never-render";
writeFileSync(
  join(workspace, ".env"),
  [
    "HTTP_CONSOLE_WRITE_ENABLED=true",
    "MAX_ITERATIONS=25",
    `KIMI_API_KEY=${MARKER}`,
    "TOTALLY_UNKNOWN=1",
    "",
  ].join("\n"),
  "utf8",
);
writeFileSync(join(closedWorkspace, ".env"), "HTTP_CONSOLE_WRITE_ENABLED=false\n", "utf8");

const servers = [];

function startServer(root, port, extraArgs = []) {
  const proc = spawn(PYTHON, ["-m", "heagent", "http-server", "--port", String(port), ...extraArgs], {
    cwd: root,
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let output = "";
  proc.stdout.on("data", (chunk) => {
    output += String(chunk);
  });
  proc.stderr.on("data", (chunk) => {
    output += String(chunk);
  });
  const entry = { proc, port, output: () => output };
  servers.push(entry);
  return entry;
}

let chrome;
const logs = [];
const requests = [];

async function waitForHealth(port, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/health`);
      if (response.ok) return await response.json();
    } catch (error) {
      /* 还没起来 */
    }
    await sleep(300);
  }
  throw new Error(`服务器 ${port} 未在 ${timeoutMs}ms 内就绪`);
}

function startChrome(port) {
  const profile = mkdtempSync(join(tmpdir(), "heagent-console-profile-"));
  const proc = spawn(
    CHROME,
    [
      "--headless=new",
      "--disable-gpu",
      "--no-first-run",
      "--no-default-browser-check",
      "--no-sandbox",
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      "about:blank",
    ],
    { stdio: "ignore" },
  );
  return proc;
}

async function waitForDevtools(port, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/version`);
      if (response.ok) return await response.json();
    } catch (error) {
      /* 还没起来 */
    }
    await sleep(200);
  }
  throw new Error("Chrome 调试端口未就绪");
}

// ── 页面驱动 ──

let cdp = null;
let origin = "";

async function evaluate(expression, { awaitPromise = true } = {}) {
  const result = await cdp.send("Runtime.evaluate", { expression, awaitPromise, returnByValue: true });
  if (result.exceptionDetails) {
    const detail = result.exceptionDetails.exception ? result.exceptionDetails.exception.description : "";
    throw new Error(`页面求值失败：${detail || JSON.stringify(result.exceptionDetails)}`);
  }
  return result.result.value;
}

async function waitFor(expression, { timeoutMs = 15000, label = expression } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      if (await evaluate(expression)) return true;
    } catch (error) {
      /* 页面可能正在导航 */
    }
    await sleep(150);
  }
  throw new Error(`等待超时：${label}`);
}

async function open(url) {
  origin = new URL(url).origin;
  await cdp.send("Page.navigate", { url });
  await waitFor(`document.readyState === "complete"`, { label: "页面加载完成" });
  await waitFor(`document.querySelectorAll("#project-list > li").length > 0`, { label: "项目列表已渲染" });
  await sleep(300);
}

async function reload() {
  await cdp.send("Page.reload", { ignoreCache: true });
  await waitFor(`document.readyState === "complete"`, { label: "刷新完成" });
  await waitFor(`document.querySelectorAll("#project-list > li").length > 0`, { label: "项目列表已渲染" });
  await sleep(300);
}

async function click(selector) {
  const ok = await evaluate(`(() => { const node = document.querySelector(${JSON.stringify(selector)}); if (!node) return false; node.click(); return true; })()`);
  if (!ok) throw new Error(`找不到可点击元素：${selector}`);
}

async function setValue(selector, value) {
  const ok = await evaluate(
    `(() => { const node = document.querySelector(${JSON.stringify(selector)}); if (!node) return false;` +
      ` node.value = ${JSON.stringify(value)}; node.dispatchEvent(new Event("input", { bubbles: true }));` +
      ` node.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`,
  );
  if (!ok) throw new Error(`找不到输入元素：${selector}`);
}

function readEnvFile(path) {
  return existsSync(path) ? readFileSync(path, "utf8") : "";
}

/** 按项目 id 切换（项目名可能是目录 basename，用 id 才稳）。 */
async function selectProjectById(projectId) {
  const found = await evaluate(
    `(() => { const li = document.querySelector('#project-list > li[data-project-id=${JSON.stringify(projectId)}]');` +
      ` if (!li) return false; li.querySelector(".list-button").click(); return true; })()`,
  );
  if (!found) throw new Error(`项目列表里没有 ${projectId}`);
  await waitFor(
    `(() => { const li = document.querySelector('#project-list > li[data-project-id=${JSON.stringify(projectId)}]'); return Boolean(li) && li.dataset.active === "true"; })()`,
    { label: `切到项目 ${projectId}` },
  );
  await sleep(250);
}

let projectBId = null;

// ── 清单 ──

const rows = [];

function row(id, title, expectation, run) {
  rows.push({ id, title, expectation, run });
}

// A 段：闸门开启的工作区（可写）

row("A1", "首页骨架 + 常驻安全声明", "两栏骨架、设置入口、安全声明三条事实同时可见", async () => {
  const state = await evaluate(`({
    sidebar: Boolean(document.getElementById("sidebar")),
    chat: Boolean(document.getElementById("chat-log")),
    settings: Boolean(document.getElementById("settings-button")),
    createSession: Boolean(document.getElementById("session-create")),
    notice: document.getElementById("security-notice").textContent,
    noticeVisible: document.getElementById("security-notice").getClientRects().length > 0,
  })`);
  const facts = ["无认证", "无 TLS", "非安全边界"].every((text) => state.notice.includes(text));
  if (!(state.sidebar && state.chat && state.settings && state.createSession && facts && state.noticeVisible)) {
    throw new Error(`骨架/声明不完整：${JSON.stringify(state)}`);
  }
  return "两栏 + 设置入口 + 声明常驻可见";
});

row("A1b", "首页无阻塞遮罩（计算样式 + 真实鼠标命中）", "确认遮罩计算样式为 none，且真实鼠标点击落到页面元素而不是遮罩", async () => {
  // 判据必须是**计算样式 + 命中测试**，不能只看 element.hidden：作者级 display 会压过 UA 的
  // `[hidden]{display:none}`（2026-09-24 实测：`.overlay{display:flex}` 让首页加载即弹出关不掉的全屏
  // 遮罩，而当时全部用例只断言属性、且用 node.click() 绕过命中测试，17/17 照样 PASS）。
  const state = await evaluate(`(() => {
    const overlay = document.getElementById("confirm-overlay");
    const center = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
    const at = (x, y) => { const node = document.elementFromPoint(x, y); return node ? (node.id || node.tagName) : null; };
    // 发送按钮常常落在首屏之下（elementFromPoint 对视口外的点返回 null）——只有它真的在视口内才纳入判据。
    const send = document.getElementById("send-button").getBoundingClientRect();
    const sendVisible = send.width > 0 && send.top >= 0 && send.bottom <= window.innerHeight;
    return {
      hiddenAttribute: overlay.hidden,
      computedDisplay: getComputedStyle(overlay).display,
      renderedBoxes: overlay.getClientRects().length,
      topmostAtCenter: at(center.x, center.y),
      topmostAtSend: sendVisible ? at(send.left + send.width / 2, send.top + send.height / 2) : "",
      sendVisible,
      center,
    };
  })()`);
  if (state.computedDisplay !== "none" || state.renderedBoxes !== 0) {
    throw new Error(
      `确认遮罩在首页就渲染出来了（hidden=${state.hiddenAttribute}，display=${state.computedDisplay}，盒子=${state.renderedBoxes}）`,
    );
  }
  if (state.topmostAtCenter === "confirm-overlay" || state.topmostAtSend === "confirm-overlay") {
    throw new Error(`遮罩吞掉了鼠标命中：视口中心=${state.topmostAtCenter}，发送按钮=${state.topmostAtSend || "(不在视口内)"}`);
  }
  // 再用 CDP 派发一次真实鼠标点击（走完整命中测试；DOM 的 node.click() 不做命中测试）。
  // 捕捉层只记录落点并 preventDefault，避免误提交一次运行。
  await evaluate(`(() => {
    window.__hitProbe = (event) => { window.__hitTarget = event.target.id || event.target.tagName; event.preventDefault(); };
    document.addEventListener("click", window.__hitProbe, true);
  })()`);
  await cdp.send("Input.dispatchMouseEvent", { type: "mousePressed", x: state.center.x, y: state.center.y, button: "left", clickCount: 1 });
  await cdp.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: state.center.x, y: state.center.y, button: "left", clickCount: 1 });
  await sleep(150);
  const hit = await evaluate(`(() => {
    document.removeEventListener("click", window.__hitProbe, true);
    const target = window.__hitTarget;
    delete window.__hitProbe;
    delete window.__hitTarget;
    return target || "";
  })()`);
  if (!hit) throw new Error("真实鼠标点击没有落到任何元素（命中测试异常）");
  if (hit === "confirm-overlay") throw new Error("真实鼠标点击被确认遮罩吞掉");
  const sendNote = state.sendVisible ? `发送按钮处最上层=${state.topmostAtSend}` : "发送按钮在首屏之下（未纳入判据）";
  return `display=none、0 个盒子、视口中心最上层=${state.topmostAtCenter}、真实点击落点=${hit}、${sendNote}`;
});

row("A2", "无第三方请求", "浏览器发出的全部请求都同源（CSP + 页面无外链）", async () => {
  const foreign = requests.filter((url) => !url.startsWith(origin) && !url.startsWith("data:"));
  if (foreign.length) throw new Error(`出现跨源请求：${foreign.join(", ")}`);
  return `${requests.length} 个请求全部同源`;
});

row("A3", "无 console 错误 / CSP 违规", "页面没有 error 级 console 消息或 CSP 拦截", async () => {
  const errors = logs.filter((entry) => entry.level === "error" && !entry.text.includes("/favicon.ico"));
  if (errors.length) throw new Error(errors.map((entry) => entry.text).join(" | "));
  return "0 条 error（favicon 404 已按无害过滤）";
});

row("A4", "项目列表渲染", "侧栏列出服务工作区项目且标记为可用", async () => {
  const projects = await evaluate(
    `Array.from(document.querySelectorAll("#project-list > li")).map((li) => ({ id: li.dataset.projectId, name: li.querySelector(".list-button").textContent, available: li.dataset.available, flags: Array.from(li.querySelectorAll(".badge")).map((b) => b.textContent) }))`,
  );
  const fallback = projects.find((item) => item.id === "default");
  if (!fallback || fallback.available !== "true") throw new Error(`项目列表异常：${JSON.stringify(projects)}`);
  return `default=${fallback.name}（${fallback.flags.join("/") || "无标记"}），共 ${projects.length} 个`;
});

row("A5", "登记项目（真实 POST）", "提交目录后侧栏出现该项目，且服务端注册表也有", async () => {
  await setValue("#project-path", projectB);
  await setValue("#project-name", "验收项目 B");
  await click("#project-register");
  await waitFor(`document.getElementById("active-project").textContent === "验收项目 B"`, {
    label: "切换到新登记的项目",
  });
  const server = await (await fetch(`${origin}/api/projects`)).json();
  const entry = server.projects.find((item) => item.name === "验收项目 B");
  if (!entry) throw new Error(`服务端未登记：${server.projects.map((item) => item.name).join(", ")}`);
  projectBId = entry.id;
  return `侧栏与 /api/projects 都有「验收项目 B」（id=${entry.id}，共 ${server.projects.length} 个）`;
});

row("A5b", "「选择文件夹…」入口（R2）", "登记表单里有服务端原生选择按钮，且与手工输入共存（不自动登记）", async () => {
  const shape = await evaluate(`(() => {
    const button = document.getElementById("project-pick");
    const register = document.getElementById("project-register");
    return {
      exists: Boolean(button),
      label: button ? button.textContent : null,
      disabled: button ? button.disabled : null,
      type: button ? button.type : null,
      title: button ? button.title : null,
      sameForm: Boolean(button && register && button.parentNode === register.parentNode),
      pathInputStillEditable: !document.getElementById("project-path").disabled,
    };
  })()`);
  if (!shape.exists || shape.type !== "button") throw new Error(`选择按钮缺失或类型不对：${JSON.stringify(shape)}`);
  if (!shape.label.includes("选择文件夹")) throw new Error(`按钮文案不对：${shape.label}`);
  if (shape.disabled) throw new Error("按钮不该初始禁用");
  if (!shape.title.includes("服务端")) throw new Error(`缺少「在服务端机器上打开」的说明：${shape.title}`);
  if (!shape.sameForm || !shape.pathInputStillEditable) throw new Error("手工输入必须与按钮共存");
  return `「${shape.label}」与「登记项目」同表单、手工输入仍可编辑；真实点击见 B2（用 --dialog-backend none 走确定性不可用路径）`;
});

row("A6", "目录失效可见标记", "目录被删后项目标记为 available=false 且显示「目录已失效」", async () => {
  rmSync(projectB, { recursive: true, force: true });
  await reload();
  const item = await evaluate(
    `(() => { const li = Array.from(document.querySelectorAll("#project-list > li")).find((node) => node.querySelector(".list-button").textContent === "验收项目 B"); if (!li) return null; return { available: li.dataset.available, flags: Array.from(li.querySelectorAll(".badge")).map((b) => b.textContent) }; })()`,
  );
  if (!item || item.available !== "false" || !item.flags.includes("目录已失效")) {
    throw new Error(`失效标记缺失：${JSON.stringify(item)}`);
  }
  return "available=false + 「目录已失效」徽标";
});

row("A7", "切换项目刷新会话（隔离）", "切到项目 B 后侧栏是它自己的会话，切回服务工作区看不到它", async () => {
  mkdirSync(projectB, { recursive: true });
  await reload();
  await selectProjectById(projectBId);
  await click("#session-create");
  await waitFor(`document.querySelectorAll("#session-list > li").length === 1`, { label: "项目 B 出现一个会话" });
  const inB = await evaluate(`Array.from(document.querySelectorAll("#session-list > li")).map((li) => li.dataset.sessionId)`);
  await selectProjectById("default");
  const inDefault = await evaluate(
    `Array.from(document.querySelectorAll("#session-list > li")).map((li) => li.dataset.sessionId)`,
  );
  const overlap = inB.filter((id) => inDefault.includes(id));
  if (overlap.length) throw new Error(`跨项目串味：${overlap.join(", ")}`);
  return `B 的会话 ${inB.length} 个、服务工作区 ${inDefault.length} 个，无交集`;
});

row("A8", "会话持久化（刷新 + 重启无关）", "刷新页面后项目 B 的会话仍在列表里", async () => {
  await selectProjectById(projectBId);
  await waitFor(`document.querySelectorAll("#session-list > li").length === 1`);
  const before = await evaluate(`Array.from(document.querySelectorAll("#session-list > li")).map((li) => li.dataset.sessionId)`);
  await reload();
  await waitFor(`document.querySelectorAll("#session-list > li").length === 1`, { label: "刷新后会话仍在" });
  const active = await evaluate(`document.getElementById("active-project").textContent`);
  if (active !== "验收项目 B") throw new Error(`刷新后没回到上次的项目：${active}`);
  const after = await evaluate(`Array.from(document.querySelectorAll("#session-list > li")).map((li) => li.dataset.sessionId)`);
  if (JSON.stringify(before) !== JSON.stringify(after)) throw new Error(`${before} != ${after}`);
  return `刷新前后都回到「${active}」且会话为 ${after.join(", ")}（落盘在 <项目根>/.heagent/sessions/）`;
});

row("A9", "重命名会话（确认框 + PATCH）", "标题更新，且磁盘会话文件里的 title 同步变化", async () => {
  await evaluate(`document.querySelectorAll("#session-list > li")[0].querySelectorAll(".item-actions button")[0].click()`);
  await waitFor(`document.getElementById("confirm-overlay").hidden === false`, { label: "确认框出现" });
  await setValue("#confirm-input", "验收重命名");
  await click("#confirm-ok");
  await waitFor(
    `document.querySelectorAll("#session-list > li")[0].querySelector(".list-button").textContent === "验收重命名"`,
    { label: "标题已更新" },
  );
  const sessionId = await evaluate(`document.querySelectorAll("#session-list > li")[0].dataset.sessionId`);
  const files = readdirSync(join(projectB, ".heagent", "sessions"));
  const target = files.find((name) => name.endsWith(".json") && name.includes(sessionId));
  const raw = target ? readFileSync(join(projectB, ".heagent", "sessions", target), "utf8") : "";
  if (!raw.includes("验收重命名")) throw new Error(`磁盘会话文件未同步：${target}`);
  return `${target} 的 title = 验收重命名`;
});

row("A10", "删除会话（先取消后确认）", "取消时不删文件；确认后文件从磁盘消失", async () => {
  const sessionId = await evaluate(`document.querySelectorAll("#session-list > li")[0].dataset.sessionId`);
  const sessionsDir = join(projectB, ".heagent", "sessions");
  const before = readdirSync(sessionsDir).length;
  await evaluate(`document.querySelectorAll("#session-list > li")[0].querySelectorAll(".item-actions button")[1].click()`);
  await waitFor(`document.getElementById("confirm-overlay").hidden === false`);
  const confirmText = await evaluate(`document.getElementById("confirm-text").textContent`);
  await click("#confirm-cancel");
  await sleep(200);
  const afterCancel = readdirSync(sessionsDir).length;
  if (afterCancel !== before) throw new Error("取消后文件被删了");
  await evaluate(`document.querySelectorAll("#session-list > li")[0].querySelectorAll(".item-actions button")[1].click()`);
  await waitFor(`document.getElementById("confirm-overlay").hidden === false`);
  await click("#confirm-ok");
  await waitFor(`document.querySelectorAll("#session-list > li").length === 0`, { label: "会话从列表消失" });
  const afterDelete = readdirSync(sessionsDir).length;
  if (afterDelete !== before - 1) throw new Error(`删除后文件数 ${afterDelete}（期望 ${before - 1}）`);
  if (!confirmText.includes("不可恢复")) throw new Error(`确认文案未说明影响范围：${confirmText}`);
  return `取消保留、确认后 ${sessionId} 文件消失（${before} → ${afterDelete}）`;
});

row("A11", "设置面板（分组 / 来源 / 只读原因）", "按后端分组渲染，条目带来源徽标，只读项显示原因", async () => {
  // 面板是**按当前项目**求解的：先回到服务工作区（它的 .env 提供项目层来源）。
  await selectProjectById("default");
  await click("#settings-button");
  await waitFor(`document.querySelectorAll("#settings-groups .config-item").length > 0`, { label: "配置面板已渲染" });
  const summary = await evaluate(`({
    groups: Array.from(document.querySelectorAll("#settings-groups .group")).map((node) => node.dataset.group),
    items: document.querySelectorAll("#settings-groups .config-item").length,
    sources: Array.from(new Set(Array.from(document.querySelectorAll("#settings-groups .config-item")).map((node) => node.dataset.source))).sort(),
    readOnlyWithReason: Array.from(document.querySelectorAll('#settings-groups .config-item[data-writable="false"]')).filter((node) => node.dataset.readOnlyReason && node.querySelector(".config-reason") && node.querySelector(".config-reason").textContent.length > 0).length,
    readOnly: document.querySelectorAll('#settings-groups .config-item[data-writable="false"]').length,
    secrets: Array.from(document.querySelectorAll("#settings-groups .config-item")).filter((node) => node.querySelector(".badge") && node.textContent.includes("凭证")).length,
    unknownKeys: Array.from(document.querySelectorAll("#unknown-keys > li")).map((node) => node.dataset.unknownKey),
    status: document.getElementById("settings-status").textContent,
    inlineValue: (() => {
      // R10：值必须与键名**同一行**，判据是几何（两个 rect 纵向重叠且值在键右侧），不是 DOM 顺序。
      const row = document.querySelector('#settings-groups .config-item[data-key="MAX_ITERATIONS"]');
      if (!row) return null;
      const key = row.querySelector(".config-key").getBoundingClientRect();
      const value = row.querySelector(".config-value").getBoundingClientRect();
      return {
        sameLine: key.top < value.bottom && value.top < key.bottom,
        rightOfKey: value.left >= key.right - 1,
        keyY: Math.round(key.top),
        valueY: Math.round(value.top),
      };
    })(),
  })`);
  const declared = Number((summary.status.match(/(\d+) 个字段/) || [])[1] || 0);
  if (summary.groups.length < 5 || summary.items < 46) throw new Error(`分组/条目过少：${JSON.stringify(summary)}`);
  if (summary.readOnlyWithReason !== summary.readOnly || summary.readOnly === 0) {
    throw new Error(`有只读项没给原因：${JSON.stringify(summary)}`);
  }
  if (summary.sources.length !== 3 || !summary.sources.includes("project_env") || !summary.sources.includes("default")) {
    throw new Error(`来源徽标未覆盖全部四层中的三层：${JSON.stringify(summary.sources)}`);
  }
  if (declared !== summary.items) throw new Error(`状态行说 ${declared} 个字段，面板渲染了 ${summary.items} 条`);
  if (summary.secrets < 1) throw new Error("凭证行没有被标出来");
  if (!summary.unknownKeys.includes("TOTALLY_UNKNOWN")) throw new Error(`未知键未单列：${summary.unknownKeys}`);
  if (!summary.inlineValue || !summary.inlineValue.sameLine || !summary.inlineValue.rightOfKey) {
    throw new Error(`值必须跟在键名后面、同一行（R10）：${JSON.stringify(summary.inlineValue)}`);
  }
  return `${summary.groups.length} 组 / ${summary.items} 条（= 后端 ${declared} 字段）/ ${summary.sources.join("+")} / ${summary.readOnly} 个只读项全部给了原因 / 未知键 ${summary.unknownKeys.join(",")} / 值内联（键 y=${summary.inlineValue.keyY}、值 y=${summary.inlineValue.valueY}）`;
});

row("A11b", "会话列表只显示最近 10 条（R1）", "同一项目有 195 个会话（AC13 点名的最长提示档）时：侧栏只渲染 10 条、显示总数、展开后全部可见", async () => {
  await selectProjectById(projectBId);
  await waitFor(`document.getElementById("active-project").textContent === "验收项目 B"`, { label: "切回项目 B" });
  // 用**真实 API** 造会话（不直接编文件）：这样断言的是真实落盘格式与真实列表端点。
  // 造到 **195** 条（R9 / AC13 点名的那一档，此前只有一次性探针验过、清单里只造到 21）：
  // 「共 195 个会话 · 只显示最近 10 条」与「显示全部（195）」是最长的那一档。
  await evaluate(`(async () => {
    let count = (await (await fetch("/api/projects/${projectBId}/sessions")).json()).sessions.length;
    while (count < 195) {
      await fetch("/api/projects/${projectBId}/sessions", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: "列表会话 " + count }),
      });
      count += 1;
    }
    return count;
  })()`);
  const total = await evaluate(
    `fetch("/api/projects/${projectBId}/sessions").then((r) => r.json()).then((p) => p.sessions.length)`,
  );
  await reload();
  await waitFor(`document.getElementById("active-project").textContent === "验收项目 B"`, { label: "刷新后仍在项目 B" });
  const truncated = await evaluate(`({
    rendered: document.querySelectorAll("#session-list > li").length,
    countText: document.getElementById("session-count").textContent,
    moreHidden: document.getElementById("session-more").hidden,
  })`);
  // R9：真实几何（字符串断言看不出「按钮被挤成三行 / 越出侧栏」这类版面缺陷，只有真浏览器能量）。
  const geometry = await evaluate(`(() => {
    const panel = document.getElementById("sidebar").querySelector("section:nth-of-type(2)").getBoundingClientRect();
    const moreNode = document.getElementById("session-more");
    const more = moreNode.getBoundingClientRect();
    const count = document.getElementById("session-count").getBoundingClientRect();
    const style = getComputedStyle(moreNode);
    const lineHeight = parseFloat(style.lineHeight) || 1;
    // 内容盒高度 ÷ 行高 = 文字占了几行（盒子高度含 padding/border，直接除会假报折行）。
    const contentHeight =
      more.height -
      parseFloat(style.paddingTop) -
      parseFloat(style.paddingBottom) -
      parseFloat(style.borderTopWidth) -
      parseFloat(style.borderBottomWidth);
    return {
      moreHeight: Math.round(more.height),
      moreLines: Math.round((contentHeight / lineHeight) * 10) / 10,
      moreRight: Math.round(more.right),
      panelRight: Math.round(panel.right),
      stacked: count.top >= more.bottom - 1,
      gap: Math.round(count.top - more.bottom),
    };
  })()`);
  if (total <= 10) throw new Error(`前置条件不成立：项目 B 只有 ${total} 个会话`);
  if (truncated.rendered !== 10) throw new Error(`默认应只渲染 10 条，实际 ${truncated.rendered}`);
  if (!truncated.countText.includes(`共 ${total} 个会话`)) throw new Error(`未显示总数：${truncated.countText}`);
  if (!truncated.countText.includes("只显示最近 10 条")) throw new Error(`未显示截断口径：${truncated.countText}`);
  if (truncated.moreHidden) throw new Error("超出部分必须可展开（不能静默藏起来）");
  if (geometry.moreLines > 1.5) {
    throw new Error(`展开按钮被挤压折行（${geometry.moreLines} 行 / ${geometry.moreHeight}px，R9 已撤销该形态）`);
  }
  if (geometry.moreRight > geometry.panelRight) {
    throw new Error(`展开按钮越出会话面板：${geometry.moreRight} > ${geometry.panelRight}`);
  }
  if (!geometry.stacked) throw new Error(`规模提示必须在展开按钮**下面**（R9）：${JSON.stringify(geometry)}`);
  await click("#session-more");
  await waitFor(`document.querySelectorAll("#session-list > li").length === ${total}`, { label: "展开后全部可见" });
  const expandedLabel = await evaluate(`document.getElementById("session-more").textContent`);
  if (!expandedLabel.includes("只看最近 10 条")) throw new Error(`展开后按钮文案未变：${expandedLabel}`);
  return `共 ${total} 个会话：默认渲染 10 条（「${truncated.countText}」），展开后 ${total} 条全部可见；按钮 ${geometry.moreHeight}px/单行、提示在其下 ${geometry.gap}px`;
});

row("A11c", "设置面板瘦身（R4）", "无整句长解释；诊断/未知键默认收起且标题带条数；只读原因是短标签", async () => {
  await selectProjectById("default");
  await click("#settings-button");
  await waitFor(`document.querySelectorAll("#settings-groups .config-item").length > 0`, { label: "配置面板已渲染" });
  const state = await evaluate(`({
    panelText: document.getElementById("settings-panel").textContent,
    diagnosticsOpen: document.getElementById("settings-diagnostics-wrap").open,
    diagnosticsSummary: document.getElementById("settings-diagnostics-summary").textContent,
    unknownOpen: document.getElementById("settings-unknown-wrap").open,
    unknownSummary: document.getElementById("settings-unknown-summary").textContent,
    reasons: Array.from(document.querySelectorAll("#settings-groups .config-item .config-reason")).map((node) => node.textContent),
    noteParagraphs: document.querySelectorAll("#settings-groups .config-notes").length,
  })`);
  // 只盯**横幅专属**的两句（「改动需要重启服务」是监听面键的合法短原因，不能误判）。
  const offenders = ["网页无法自行开启", "需在启动配置"].filter((phrase) => state.panelText.includes(phrase));
  if (offenders.length) {
    const index = state.panelText.indexOf(offenders[0]);
    const context = state.panelText.slice(Math.max(0, index - 80), index + 80);
    throw new Error(`长句解释仍然出现在面板文本里（${offenders.join(" / ")}）：…${context}…`);
  }
  if (state.diagnosticsOpen || state.unknownOpen) throw new Error("诊断/未知键必须默认收起");
  if (!state.diagnosticsSummary.includes("诊断")) throw new Error(`诊断标题缺失：${state.diagnosticsSummary}`);
  if (!state.unknownSummary.includes("未知键")) throw new Error(`未知键标题缺失：${state.unknownSummary}`);
  if (!state.reasons.length) throw new Error("只读原因必须仍然可见（UX-DR5）");
  const longForm = state.reasons.filter((text) => !text.startsWith("只读："));
  if (longForm.length) throw new Error(`只读原因不是短标签：${longForm.slice(0, 3).join(" | ")}`);
  if (state.noteParagraphs !== 0) throw new Error("逐项说明不该再铺成长段文案");
  return `诊断「${state.diagnosticsSummary}」与未知键「${state.unknownSummary}」默认收起；${state.reasons.length} 条只读原因均为「只读：…」短标签；无长句解释`;
});

row("A12", "凭证零明文", "项目 .env 里的密钥标记不出现在页面文本、DOM 与前端响应里", async () => {
  const text = await evaluate(
    `({ body: document.body.textContent, html: document.documentElement.outerHTML, panel: document.getElementById("settings-panel").textContent })`,
  );
  const leaked = Object.entries(text).filter(([, value]) => value.includes(MARKER));
  if (leaked.length) throw new Error(`密钥泄漏在：${leaked.map(([key]) => key).join(", ")}`);
  const rowText = await evaluate(
    `(() => { const row = Array.from(document.querySelectorAll("#settings-groups .config-item")).find((node) => node.dataset.key === "KIMI_API_KEY"); return row ? { text: row.textContent, inputs: row.querySelectorAll("input").length, html: row.outerHTML } : null; })()`,
  );
  if (!rowText || rowText.inputs !== 0) throw new Error(`凭证行不该有输入框：${JSON.stringify(rowText)}`);
  if (!rowText.text.includes("已配置") || !rowText.text.includes("*")) throw new Error(`凭证行未显示掩码：${rowText.text}`);
  return `页面/DOM/行内都没有标记；凭证行只有「${rowText.text.replace(/凭证|来源：项目 .env/g, "").trim()}」`;
});

row("A13", "保存配置（确认 → 写入 → 生效时机）", "确认后磁盘 .env 出现新值、页面显示「下一次运行生效」、来源徽标刷新、写前有备份", async () => {
  await setValue('#settings-groups .config-item[data-key="MAX_ITERATIONS"] input', "321");
  await waitFor(`document.getElementById("settings-save").disabled === false`, { label: "保存按钮可用" });
  const pending = await evaluate(`document.getElementById("settings-pending").textContent`);
  await click("#settings-save");
  await waitFor(`document.getElementById("confirm-overlay").hidden === false`, { label: "写入确认框出现" });
  const confirmText = await evaluate(`document.getElementById("confirm-text").textContent`);
  const beforeDisk = readEnvFile(join(workspace, ".env"));
  await click("#confirm-ok");
  await waitFor(`!document.getElementById("settings-result").hidden`, { label: "写入结果出现" });
  await sleep(500);
  const result = await evaluate(`({ state: document.getElementById("settings-result").dataset.state, text: document.getElementById("settings-result").textContent, status: document.getElementById("settings-status").textContent })`);
  const disk = readEnvFile(join(workspace, ".env"));
  const badge = await evaluate(
    `(() => { const row = document.querySelector('#settings-groups .config-item[data-key="MAX_ITERATIONS"]'); return { source: row.dataset.source, badge: row.querySelector(".badge-source").textContent, value: row.querySelector(".config-value").textContent, input: row.querySelector("input").value }; })()`,
  );
  const backups = existsSync(join(workspace, ".heagent", "backups")) ? readdirSync(join(workspace, ".heagent", "backups")) : [];
  if (!beforeDisk.includes("MAX_ITERATIONS=25")) throw new Error("前置状态不是 25，用例前提被破坏");
  if (!confirmText.includes("下一次运行生效")) throw new Error(`确认文案未表述生效时机：${confirmText}`);
  if (pending !== "有 1 项未保存") throw new Error(`待保存提示异常：${pending}`);
  if (result.state !== "ok") throw new Error(`写入未成功：${result.text}`);
  if (!disk.includes("MAX_ITERATIONS=321")) throw new Error(`磁盘未写入：${disk.split("\n")[1]}`);
  if (!result.text.includes("下一次运行生效")) throw new Error(`结果未表述生效时机：${result.text}`);
  if (badge.source !== "project_env" || !badge.badge.includes("项目 .env")) throw new Error(`来源徽标未刷新：${JSON.stringify(badge)}`);
  if (badge.value !== "321" || badge.input !== "321") throw new Error(`面板未刷新到写后值：${JSON.stringify(badge)}`);
  if (!backups.some((name) => name.endsWith(".bak"))) throw new Error(`没有写前备份：${backups.join(", ")}`);
  return `25 → 321（磁盘 + 面板），来源 ${badge.source}，备份 ${backups.length} 个，状态行「${result.status}」`;
});

row("A14", "非法值被拒且文件不变", "提交非法值后页面给出可理解文案，磁盘文件逐字节不变", async () => {
  const before = readEnvFile(join(workspace, ".env"));
  await setValue('#settings-groups .config-item[data-key="MAX_ITERATIONS"] input', "abc");
  await click("#settings-save");
  await waitFor(`document.getElementById("confirm-overlay").hidden === false`);
  await click("#confirm-ok");
  await waitFor(`document.getElementById("settings-result").dataset.state === "failed"`, { label: "失败结果出现" });
  await sleep(300);
  const text = await evaluate(`document.getElementById("settings-result").textContent`);
  const after = readEnvFile(join(workspace, ".env"));
  if (after !== before) throw new Error("被拒的写入改了文件");
  if (!text.includes("值不合法")) throw new Error(`文案不可理解：${text}`);
  return `「${text.split("\n").pop().trim()}」，文件未变（${before.length} 字节）`;
});

row("A15", "窄屏降级 + 侧栏可收起", "420px 宽下侧栏可收起（计算样式 display:none），安全声明仍可见", async () => {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 420,
    height: 900,
    deviceScaleFactor: 1,
    mobile: true,
  });
  await sleep(200);
  await click("#sidebar-toggle");
  await sleep(200);
  const state = await evaluate(`({
    collapsed: document.getElementById("console").dataset.sidebarCollapsed,
    display: getComputedStyle(document.getElementById("sidebar")).display,
    noticeVisible: document.getElementById("security-notice").getClientRects().length > 0,
    aria: document.getElementById("sidebar-toggle").getAttribute("aria-expanded"),
  })`);
  await cdp.send("Emulation.clearDeviceMetricsOverride");
  if (state.collapsed !== "true" || state.display !== "none" || state.aria !== "false") {
    throw new Error(`侧栏收起无效：${JSON.stringify(state)}`);
  }
  if (!state.noticeVisible) throw new Error("窄屏下安全声明不可见");
  await click("#sidebar-toggle");
  return "sidebar display:none，声明仍可见";
});

row("A16", "截图留档", "控制台整页截图写入临时工作区", async () => {
  const shot = await cdp.send("Page.captureScreenshot", { format: "png" });
  const path = join(workspace, "console.png");
  writeFileSync(path, Buffer.from(shot.data, "base64"));
  return `${path}（${Math.round(readFileSync(path).length / 1024)} KB）`;
});

// B 段：写入闸门关闭的服务（另一个工作区 + 另一个端口）

row("B1", "闸门关闭：全只读 + 原因 + 无开启入口", "闸门徽标挂在项目名后面（同一行）说明闸门关闭，所有可写项不可编辑，且没有任何开启入口", async () => {
  const closedPort = PORT + 1;
  startServer(closedWorkspace, closedPort);
  await waitForHealth(closedPort);
  await open(`http://127.0.0.1:${closedPort}/`);
  await click("#settings-button");
  await waitFor(`document.querySelectorAll("#settings-groups .config-item").length > 0`);
  const state = await evaluate(`(() => {
    const gate = document.getElementById("settings-gate");
    const project = document.getElementById("settings-project").getBoundingClientRect();
    const gateBox = gate.getBoundingClientRect();
    const writableRows = Array.from(document.querySelectorAll('#settings-groups .config-item[data-writable="true"]'));
    return {
      gateText: gate.hidden ? "" : gate.textContent,
      gateTitle: gate.title,
      gateSameLineAsProject: gateBox.top < project.bottom && gateBox.bottom > project.top,
      gateRightOfProject: gateBox.left >= project.right,
      writableReasons: writableRows.reduce((sum, row) => sum + row.querySelectorAll(".config-reason").length, 0),
      writableRows: writableRows.length,
      panelText: document.getElementById("settings-panel").textContent,
      saveDisabled: document.getElementById("settings-save").disabled,
      enabledInputs: Array.from(document.querySelectorAll("#settings-groups .config-input")).filter((node) => !node.disabled).length,
      editableRows: document.querySelectorAll('#settings-groups .config-item[data-editable="true"]').length,
      gateKey: (() => { const row = Array.from(document.querySelectorAll("#settings-groups .config-item")).find((node) => node.dataset.key === "HTTP_CONSOLE_WRITE_ENABLED"); return row ? { editable: row.dataset.editable, inputs: row.querySelectorAll("input").length } : null; })(),
    };
  })()`);
  if (state.gateText !== "只读") throw new Error(`闸门徽标文案异常：${JSON.stringify(state.gateText)}`);
  if (!state.gateTitle.includes("未开启配置写入") || !state.gateTitle.includes("HTTP_CONSOLE_WRITE_ENABLED")) {
    throw new Error(`「为什么只读」必须仍然可达（title）：${state.gateTitle}`);
  }
  if (!state.gateSameLineAsProject || !state.gateRightOfProject) {
    throw new Error(`闸门徽标必须跟在项目名之后、同一行（R9）：${JSON.stringify(state)}`);
  }
  if (state.panelText.includes("网页无法自行开启") || state.panelText.includes("需在启动配置")) {
    throw new Error("闸门关闭时也只允许一行短状态（R4：长解释不该回来）");
  }
  if (!state.saveDisabled) throw new Error("保存按钮应当禁用");
  if (state.enabledInputs !== 0 || state.editableRows !== 0) throw new Error(`仍有可编辑项：${JSON.stringify(state)}`);
  if (state.writableReasons !== 0) {
    throw new Error(`可写项不该再逐项铺同一句只读原因（R9）：${state.writableReasons} 条`);
  }
  if (!state.gateKey || state.gateKey.editable !== "false" || state.gateKey.inputs !== 0) {
    throw new Error(`开关自身应当是只读且无输入框：${JSON.stringify(state.gateKey)}`);
  }
  return `项目名后「${state.gateText}」徽标（title 含完整原因）、0 个可编辑控件、${state.writableRows} 个可写项无逐项重复、开关自身只读（无输入框）`;
});

row("A11d", "布局：一列侧栏 + 对话区占满所在列（R6/R7/R8）", "项目与会话同栏堆叠；对话正文与输入条铺满该列（不再限宽居中）；设置面板打开时对话列仍最宽；会话控件在列表之上", async () => {
  // B1 之后页面停在「闸门关闭」的服务上 ⇒ 显式回到主控制台，并切到有 195 个会话的项目 B。
  await open(`http://127.0.0.1:${PORT}/`);
  await selectProjectById(projectBId);
  await click("#settings-close"); // 量的是**默认两栏**布局：先把设置面板收起来
  // 必须先把视口放宽：容器不够宽时「占满 vs 限宽」测不出差别（旧口径下只会得到恒定的 768px）。
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 900, deviceScaleFactor: 1, mobile: false });
  await sleep(200);
  await waitFor(`document.getElementById("sidebar").offsetParent !== null`, { label: "侧栏可见" });
  // ① R8：会话规模/展开控件必须在**会话列表之上**（几何判据 = 位置，不是 DOM 顺序）。
  const controls = await evaluate(`(() => {
    const more = document.getElementById("session-more");
    const moreRect = more.getBoundingClientRect();
    const listRect = document.getElementById("session-list").getBoundingClientRect();
    return { hidden: more.hidden, moreBottom: Math.round(moreRect.bottom), listTop: Math.round(listRect.top) };
  })()`);
  if (controls.hidden) throw new Error("项目 B 应有 >10 个会话，「显示全部」必须可见（前置条件被破坏）");
  if (!(controls.moreBottom <= controls.listTop + 1)) {
    throw new Error(`会话控件不在会话列表之上（R8）：${JSON.stringify(controls)}`);
  }
  // ② R7：设置面板打开时三列里**对话列仍是最宽的**（旧口径下设置面板比对话列宽）。
  await click("#settings-button");
  await waitFor(`document.querySelectorAll("#settings-groups .config-item").length > 0`, { label: "配置面板已渲染" });
  const threeColumn = await evaluate(`({
    chat: Math.round(document.querySelector(".chat").getBoundingClientRect().width),
    settings: Math.round(document.getElementById("settings-panel").getBoundingClientRect().width),
  })`);
  if (!(threeColumn.chat > threeColumn.settings)) {
    throw new Error(`设置面板打开时对话列不再是最宽的一列：${JSON.stringify(threeColumn)}`);
  }
  // 布局是**给人看**的：把两种状态各留一张图（`--keep` 时随工作区保留，便于人眼复核）。
  const threeShot = await cdp.send("Page.captureScreenshot", { format: "png" });
  const threePath = join(workspace, "console-a11d-3col-settings-open.png");
  writeFileSync(threePath, Buffer.from(threeShot.data, "base64"));
  await click("#settings-close");
  await waitFor(`document.getElementById("settings-panel").hidden`, { label: "设置面板已收起" });
  await sleep(200);
  const layout = await evaluate(`(() => {
    const sidebar = document.getElementById("sidebar");
    const sidebarStyle = getComputedStyle(sidebar);
    const projects = document.getElementById("project-list").parentNode;
    const sessions = document.getElementById("session-list").parentNode;
    const log = document.getElementById("chat-log");
    // 对话区此刻可能没有消息（本清单不跑真实 LLM 运行）⇒ 用一个探针元素量**真实 CSS 规则**
    // （.chat-log > * 的宽度），量完立刻移除，不留痕迹。
    const probe = document.createElement("li");
    probe.className = "entry";
    log.appendChild(probe);
    const probeRect = probe.getBoundingClientRect();
    const logRect = log.getBoundingClientRect();
    const logStyle = getComputedStyle(log);
    log.removeChild(probe);
    const composerRect = document.getElementById("prompt-input").getBoundingClientRect();
    return {
      sidebarDisplay: sidebarStyle.display,
      sidebarDirection: sidebarStyle.flexDirection,
      containsBoth: sidebar.contains(projects) && sidebar.contains(sessions),
      stacked: projects.getBoundingClientRect().bottom <= sessions.getBoundingClientRect().top + 1,
      probeWidth: Math.round(probeRect.width),
      logWidth: Math.round(logRect.width),
      paddingLeft: Math.round(parseFloat(logStyle.paddingLeft)),
      paddingRight: Math.round(parseFloat(logStyle.paddingRight)),
      leftGap: Math.round(probeRect.left - logRect.left),
      rightGap: Math.round(logRect.right - probeRect.right),
      composerWidth: Math.round(composerRect.width),
    };
  })()`);
  if (layout.sidebarDisplay !== "flex" || layout.sidebarDirection !== "column") {
    throw new Error(`侧栏不是一列：${JSON.stringify(layout)}`);
  }
  if (!layout.containsBoth || !layout.stacked) throw new Error(`项目与会话必须同栏纵向堆叠：${JSON.stringify(layout)}`);
  // 「占满」的**判别性**判据：1600px 视口下 280px 侧栏 ⇒ 对话列 1320px，去掉该列 1rem 内边距后正文应 ≈1288px。
  // 旧口径（48rem 限宽居中）只会得到恒定 768px，两侧各留一大块空白 ⇒ 这几条会精确变红。
  const contentWidth = layout.logWidth - layout.paddingLeft - layout.paddingRight;
  if (layout.probeWidth <= 768) throw new Error(`对话正文没占满该列（还被限宽？）：${JSON.stringify(layout)}`);
  if (Math.abs(layout.probeWidth - contentWidth) > 1) throw new Error(`对话正文未铺满该列：${JSON.stringify(layout)}`);
  if (Math.abs(layout.leftGap - layout.paddingLeft) > 1 || Math.abs(layout.rightGap - layout.paddingRight) > 1) {
    throw new Error(`对话正文两侧余量应等于该列内边距（不是居中余量）：${JSON.stringify(layout)}`);
  }
  if (Math.abs(layout.composerWidth - layout.probeWidth) > 2) {
    throw new Error(`输入条与正文不同宽：${JSON.stringify(layout)}`);
  }
  const twoShot = await cdp.send("Page.captureScreenshot", { format: "png" });
  const twoPath = join(workspace, "console-a11d-2col-chat-fullwidth.png");
  writeFileSync(twoPath, Buffer.from(twoShot.data, "base64"));
  await cdp.send("Emulation.clearDeviceMetricsOverride");
  return `${controls.moreBottom} ≤ ${controls.listTop}（控件在列表之上）；设置面板打开时对话 ${threeColumn.chat}px > 设置 ${threeColumn.settings}px；1600px 视口下侧栏 ${layout.sidebarDisplay}/${layout.sidebarDirection} 且项目与会话同栏堆叠、对话正文 ${layout.probeWidth}px（= 该列 ${layout.logWidth} - 内边距 ${layout.paddingLeft}/${layout.paddingRight}）、输入条 ${layout.composerWidth}px；截图 console-a11d-2col-chat-fullwidth.png / console-a11d-3col-settings-open.png`;
});

row("B2", "选择文件夹：不可用路径（R2）", "``--dialog-backend none`` 的服务上点击按钮：给出原因、不回填、不登记", async () => {
  const port = PORT + 2;
  startServer(closedWorkspace, port, ["--dialog-backend", "none"]);
  await waitForHealth(port);
  await open(`http://127.0.0.1:${port}/`);
  await click("#project-pick");
  await waitFor(`document.getElementById("project-status").dataset.state === "failed"`, { label: "给出失败原因" });
  const state = await evaluate(`({
    text: document.getElementById("project-status").textContent,
    path: document.getElementById("project-path").value,
    disabled: document.getElementById("project-pick").disabled,
  })`);
  if (!state.text.includes("目录选择器")) throw new Error(`文案不可理解：${state.text}`);
  if (!state.text.includes("服务端说明")) throw new Error(`未回传服务端原因：${state.text}`);
  if (state.path !== "") throw new Error("不可用时不该回填任何路径");
  if (state.disabled) throw new Error("请求结束后按钮必须恢复可用");
  return `「${state.text}」且输入框未被改动`;
});

// ── 执行 ──

const table = [];
let failed = 0;

try {
  const server = startServer(workspace, PORT);
  const health = await waitForHealth(PORT).catch((error) => {
    throw new Error(`${error.message}\n--- 服务端输出 ---\n${server.output()}`);
  });
  chrome = startChrome(PORT + 100);
  const version = await waitForDevtools(PORT + 100);
  const target = await (
    await fetch(`http://127.0.0.1:${PORT + 100}/json/new?about:blank`, { method: "PUT" })
  ).json();
  cdp = connect(target.webSocketDebuggerUrl);
  await cdp.ready;
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Network.enable");
  cdp.on("Network.requestWillBeSent", (params) => requests.push(params.request.url));
  cdp.on("Log.entryAdded", (params) =>
    logs.push({ level: params.entry.level, text: `${params.entry.text} ${params.entry.url || ""}`.trim() }),
  );
  cdp.on("Runtime.consoleAPICalled", (params) => {
    const text = (params.args || []).map((arg) => arg.value ?? arg.description ?? "").join(" ");
    logs.push({ level: params.type === "error" ? "error" : params.type, text });
  });

  await open(`http://127.0.0.1:${PORT}/`);
  console.log(`# HeAgent 控制台验收（真实浏览器）\n`);
  console.log(`- Chrome: ${version.Browser}`);
  console.log(`- 服务: ${health.service} ${health.version} @ http://127.0.0.1:${PORT}/`);
  console.log(`- 工作区: ${workspace}\n`);

  for (const item of rows) {
    try {
      const observed = await item.run();
      table.push({ ...item, observed, status: "PASS" });
      console.log(`✓ ${item.id} ${item.title} — ${observed}`);
    } catch (error) {
      failed += 1;
      table.push({ ...item, observed: String(error.message || error), status: "FAIL" });
      console.log(`✗ ${item.id} ${item.title} — ${error.message || error}`);
    }
  }

  console.log("\n| # | 步骤（页面） | 期望 | 实测 | 结论 |");
  console.log("|---|---|---|---|---|");
  for (const item of table) {
    console.log(`| ${item.id} | ${item.title} | ${item.expectation} | ${item.observed.replace(/\|/g, "/")} | ${item.status} |`);
  }
  console.log(`\nACCEPTANCE ${JSON.stringify({ rows: table.length, failed, workspace, chrome: version.Browser })}`);
} catch (error) {
  console.error(`验收驱动异常：${error && error.stack ? error.stack : error}`);
  failed += 1;
} finally {
  try {
    if (cdp) cdp.close();
  } catch (error) {
    /* 忽略 */
  }
  if (chrome) chrome.kill();
  for (const entry of servers) entry.proc.kill();
  await sleep(500);
  if (!args.keep) {
    try {
      rmSync(workspace, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    } catch (error) {
      console.error(`临时工作区未能删除（不影响结论）：${workspace}`);
    }
  }
}

process.exit(failed === 0 ? 0 : 1);
