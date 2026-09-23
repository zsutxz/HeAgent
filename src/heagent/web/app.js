/* HeAgent 内置网页脚本（Epic 49）。
 *
 * 约束（改这里前先读 docs/frame.md 4.17）：
 *   - 纯原生 JS：不加载、不依赖任何第三方脚本（严格 CSP 下也只允许同源 /app.js）；
 *   - 提示词、回答、工具名与工具输出**一律按纯文本渲染**（createTextNode / textContent），
 *     绝不使用 innerHTML —— Agent 输出是不可信内容，HTML 注入会变成页面内的脚本执行；
 *   - 所有请求同源（页面与 /api/* 由同一个 ASGI app 提供），不配置 CORS、不带凭据；
 *   - 状态词表集中在 SERVICE_TEXT / RUN_TEXT，UI 只映射服务端给出的事实，不自行推断
 *     「大概成功了」——终态一律等 SSE 的终态事件（或重新同步后的会话快照），不提前宣布。
 */
(() => {
  "use strict";

  const HEALTH_POLL_MS = 5000;
  const MAX_LOG_ENTRIES = 500;

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

  const el = {
    service: document.getElementById("service-status"),
    log: document.getElementById("chat-log"),
    empty: document.getElementById("empty-state"),
    form: document.getElementById("prompt-form"),
    input: document.getElementById("prompt-input"),
    send: document.getElementById("send-button"),
    stop: document.getElementById("stop-button"),
    run: document.getElementById("run-status"),
  };

  let activeRunId = null;
  let stream = null;
  let assistantEntry = null;
  const pendingToolEntries = new Map();

  /** 只把字符串交给 textContent；其它类型（数字/对象/undefined）一律折叠为可读文本。 */
  function asText(value) {
    if (typeof value === "string") return value;
    if (value === null || value === undefined) return "";
    return String(value);
  }

  function setServiceState(state) {
    el.service.dataset.state = state;
    el.service.textContent = SERVICE_TEXT[state] || SERVICE_TEXT.connecting;
  }

  function setRunState(state, text) {
    el.run.dataset.state = state;
    el.run.textContent = text || RUN_TEXT[state] || state;
    const busy = BUSY_STATES.has(state);
    el.send.disabled = busy;
    el.input.disabled = busy;
    el.stop.disabled = !(state === "running" || state === "reconnecting");
  }

  /** 往对话记录追加一条纯文本条目（种类只影响样式，从不影响内容解释方式）。 */
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
    const label = payload.tool_target
      ? `${asText(payload.tool_name)} → ${asText(payload.tool_target)}`
      : asText(payload.tool_name);
    // 同一工具名会被连续/并发调用多次（工具结果事件里没有 call id），所以按「先到先配」排队：
    // 用「一名一条队列」而不是「一名一条」，否则后一次调用会覆盖前一次的条目，
    // 结果被写到错误的行上、前一行永远停在「运行中」。
    const key = asText(payload.tool_name);
    const queue = pendingToolEntries.get(key);
    if (queue) {
      queue.push(appendEntry("tool", `▶ ${label}`));
    } else {
      pendingToolEntries.set(key, [appendEntry("tool", `▶ ${label}`)]);
    }
  }

  function showToolResult(payload) {
    const key = asText(payload.tool_name);
    const queue = pendingToolEntries.get(key);
    const entry = queue && queue.length ? queue.shift() : null;
    if (queue && queue.length === 0) pendingToolEntries.delete(key);
    const isError = Boolean(payload.tool_error);
    const output = asText(payload.tool_output);
    const line = `${isError ? "✘" : "✔"} ${key}${output ? `：${output}` : ""}`;
    const target = entry || appendEntry("tool", line);
    target.dataset.error = isError ? "true" : "false";
    if (entry) target.textContent = line;
    el.log.scrollTop = el.log.scrollHeight;
  }

  function closeStream() {
    if (stream) {
      stream.close();
      stream = null;
    }
    activeRunId = null;
    assistantEntry = null;
    pendingToolEntries.clear();
  }

  function finishRun(state, text) {
    closeStream();
    setRunState(state, text);
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
    const runId = activeRunId;
    if (!runId) return;
    let snapshot;
    try {
      const response = await fetch("/api/session", { headers: { accept: "application/json" } });
      if (!response.ok) return;
      snapshot = await response.json();
    } catch (error) {
      return; // 服务不可达：保持「重连中」，由 EventSource 继续尝试。
    }
    if (activeRunId !== runId) return; // 已经切到别的运行，别用旧快照覆盖。
    const terminal = ["completed", "failed", "cancelled", "timed_out"].includes(snapshot.status);
    if (terminal || snapshot.run_id !== runId) {
      closeStream();
      await restoreSession();
      appendEntry("error", "连接中断后已与服务端重新同步（可能有事件未送达）。");
      // 文案要与服务端事实一致：completed 就是「已完成」，不能让状态词表里的「失败」顶上去。
      const state = snapshot.status === "completed" ? "done" : "failed";
      setRunState(state, RUN_TEXT[state]);
    }
  }

  async function readError(response) {
    try {
      const payload = await response.json();
      return asText(payload && payload.error && payload.error.message);
    } catch (error) {
      return "";
    }
  }

  async function submitPrompt(prompt) {
    setRunState("starting");
    appendEntry("user", prompt);
    let response;
    try {
      response = await fetch("/api/runs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
    } catch (error) {
      appendEntry("error", "无法连接到服务");
      setRunState("failed");
      return;
    }
    if (!response.ok) {
      const message = await readError(response);
      appendEntry("error", message || `请求被拒绝（HTTP ${response.status}）`);
      setRunState("failed");
      return;
    }
    const created = await response.json();
    activeRunId = created.run_id;
    setRunState("running");
    subscribe(created.run_id);
  }

  async function cancelRun() {
    if (!activeRunId) return;
    const runId = activeRunId;
    setRunState("cancelling");
    try {
      const response = await fetch(`/api/runs/${runId}`, { method: "DELETE" });
      if (!response.ok) {
        const message = await readError(response);
        appendEntry("error", message || `取消失败（HTTP ${response.status}）`);
        setRunState("failed");
        return;
      }
      // 成功时不在这里宣布结果：终态由 SSE 的 `cancelled` 事件给出（服务端是唯一事实源）。
    } catch (error) {
      appendEntry("error", "无法连接到服务");
      setRunState("disconnected");
    }
  }

  async function restoreSession() {
    try {
      const response = await fetch("/api/session", { headers: { accept: "application/json" } });
      if (!response.ok) return;
      const snapshot = await response.json();
      const messages = Array.isArray(snapshot.messages) ? snapshot.messages : [];
      el.log.replaceChildren();
      assistantEntry = null;
      for (const message of messages) {
        appendEntry(message.role === "user" ? "user" : "assistant", message.text);
      }
      // 服务端仍有在途运行时不能显示「空闲」：接手它的事件流（终态仍由 SSE 给出），
      // 否则用户以为可以提交，实际只会收到 run_conflict。
      if (!activeRunId && snapshot.status === "running" && snapshot.run_id) {
        activeRunId = snapshot.run_id;
        setRunState("running");
        subscribe(snapshot.run_id);
      }
    } catch (error) {
      // 服务不可达时保持空态：不伪造历史。
    }
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

  el.form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (activeRunId) {
      // 运行中禁止重复提交（服务端也会回 run_conflict），但**不静默吞掉**这次点击：
      // 取消失败或连接中断时发送按钮可能已解禁，用户需要一个可读的原因。
      appendEntry("error", "已有运行进行中：请等待它结束，或点「停止」后再提交。");
      return;
    }
    const prompt = asText(el.input.value).trim();
    if (!prompt) return;
    el.input.value = "";
    submitPrompt(prompt);
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

  setServiceState("connecting");
  setRunState("idle");
  checkHealth();
  restoreSession();
  window.setInterval(checkHealth, HEALTH_POLL_MS);
})();
