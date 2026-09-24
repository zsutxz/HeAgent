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

function startServer(root, port) {
  const proc = spawn(PYTHON, ["-m", "heagent", "http-server", "--port", String(port)], {
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
  return `${summary.groups.length} 组 / ${summary.items} 条（= 后端 ${declared} 字段）/ ${summary.sources.join("+")} / ${summary.readOnly} 个只读项全部给了原因 / 未知键 ${summary.unknownKeys.join(",")}`;
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

row("B1", "闸门关闭：全只读 + 原因 + 无开启入口", "面板说明闸门关闭，所有可写项不可编辑，且没有任何开启入口", async () => {
  const closedPort = PORT + 1;
  startServer(closedWorkspace, closedPort);
  await waitForHealth(closedPort);
  await open(`http://127.0.0.1:${closedPort}/`);
  await click("#settings-button");
  await waitFor(`document.querySelectorAll("#settings-groups .config-item").length > 0`);
  const state = await evaluate(`({
    gate: document.getElementById("settings-gate").hidden ? "" : document.getElementById("settings-gate").textContent,
    saveDisabled: document.getElementById("settings-save").disabled,
    enabledInputs: Array.from(document.querySelectorAll("#settings-groups .config-input")).filter((node) => !node.disabled).length,
    editableRows: document.querySelectorAll('#settings-groups .config-item[data-editable="true"]').length,
    reasonSamples: Array.from(document.querySelectorAll("#settings-groups .config-item")).filter((node) => node.dataset.writable === "true").slice(0, 3).map((node) => { const reason = node.querySelector(".config-reason"); return reason ? reason.textContent : null; }),
    gateKey: (() => { const row = Array.from(document.querySelectorAll("#settings-groups .config-item")).find((node) => node.dataset.key === "HTTP_CONSOLE_WRITE_ENABLED"); return row ? { editable: row.dataset.editable, inputs: row.querySelectorAll("input").length, reason: row.querySelector(".config-reason") ? row.querySelector(".config-reason").textContent : null } : null; })(),
  })`);
  if (!state.gate.includes("未开启配置写入")) throw new Error(`面板未说明闸门关闭：${state.gate}`);
  if (!state.saveDisabled) throw new Error("保存按钮应当禁用");
  if (state.enabledInputs !== 0 || state.editableRows !== 0) throw new Error(`仍有可编辑项：${JSON.stringify(state)}`);
  if (!state.reasonSamples.every((text) => text && text.includes("未开启配置写入"))) {
    throw new Error(`可写项未给原因：${JSON.stringify(state.reasonSamples)}`);
  }
  if (!state.gateKey || state.gateKey.editable !== "false" || state.gateKey.inputs !== 0) {
    throw new Error(`开关自身应当是只读且无输入框：${JSON.stringify(state.gateKey)}`);
  }
  return `闸门说明可见、0 个可编辑控件、可写项原因一致、开关自身只读（无输入框）`;
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
