/* 后台任务面板（Epic 70，Story 70.1）：消费 GET /api/tasks 与 GET /api/tasks/{task_id}。
 *
 * 只读视图：渲染一律 textContent / createElement（服务端的 kind / message 都是不可信输入）；
 * 请求经 `window.HePanels.request`（同源，HTTP 错误也是结果而不是异常，只有网络失败才抛）。
 *
 * 轮询不变量：只有列表里存在 pending / running 时才值得继续取数；拿到「空列表」或「全部终态」
 * 的快照即停表（页面静止时不打服务端）。标签页不可见时同样停表，重新可见立刻补一次。
 * 取数失败不改变这条判定——失败时手上没有可信快照，列表内容保持上一次渲染的事实。
 */
(() => {
  "use strict";

  const POLL_MS = 2000;
  const LIST_PATH = "/api/tasks";
  const DETAIL_PATH = "/api/tasks/";
  /** 仍在推进的两态：只有它们值得继续轮询（completed / failed 是终态）。 */
  const ACTIVE_STATES = new Set(["pending", "running"]);
  const STATUS_TEXT = {
    pending: "等待中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
  };
  /** 详情字段与中文标签：顺序即渲染顺序，字段集合与服务端响应一致（不多造语义）。 */
  const DETAIL_FIELDS = [
    ["task_id", "任务"],
    ["kind", "类型"],
    ["status", "状态"],
    ["percent", "进度"],
    ["message", "消息"],
    ["started_at", "开始"],
    ["updated_at", "更新"],
  ];

  const el = {
    list: document.getElementById("task-list"),
    empty: document.getElementById("task-empty"),
    detail: document.getElementById("task-detail"),
    status: document.getElementById("task-status"),
  };

  // 本脚本只服务控制台页：面板不在页面上就什么都不做（不抛，其它面板脚本各自独立）。
  if (!el.list || !el.empty || !el.detail || !el.status) return;

  const panels = window.HePanels;
  if (!panels) {
    el.status.dataset.state = "failed";
    el.status.textContent = "面板公共桥未加载";
    return;
  }

  /** 轮询句柄：非 null 即已排好下一次取数；停表后必须归位为 null（否则会重复排程）。 */
  let timer = null;
  /** 列表请求一次只在途一个：可见性切换可能与排程重叠，重叠请求只是白跑一趟。 */
  let loading = false;

  function setStatus(state, text) {
    el.status.dataset.state = state;
    el.status.textContent = text;
  }

  function stopPolling() {
    if (timer === null) return;
    window.clearTimeout(timer);
    timer = null;
  }

  /** 排下一次取数；不可见的标签页不排程（恢复可见时由 visibilitychange 立即补一次）。 */
  function schedulePoll() {
    stopPolling();
    if (document.hidden) return;
    timer = window.setTimeout(() => {
      timer = null;
      void loadTasks();
    }, POLL_MS);
  }

  function hasActive(tasks) {
    return tasks.some((task) => ACTIVE_STATES.has(task.status));
  }

  function tasksOf(payload) {
    if (!payload || typeof payload !== "object") return [];
    const tasks = payload.tasks;
    if (!Array.isArray(tasks)) return [];
    return tasks.filter((task) => task && typeof task === "object");
  }

  function percentOf(task) {
    const value = Number(task.percent);
    if (!Number.isFinite(value)) return 0;
    return Math.min(100, Math.max(0, Math.round(value)));
  }

  function statusText(status) {
    return STATUS_TEXT[status] || String(status || "-");
  }

  /** 条目副行：状态 + 更新时间，有 message 才追加（不编造缺省文案）。 */
  function metaText(task) {
    const parts = [statusText(task.status), panels.formatTime(task.updated_at)];
    if (task.message) parts.push(String(task.message));
    return parts.join(" · ");
  }

  function taskRow(task) {
    const row = document.createElement("li");
    row.className = "list-item task-row";
    row.dataset.state = String(task.status || "");
    row.tabIndex = 0;
    row.setAttribute("role", "button");

    const title = document.createElement("span");
    title.className = "task-title";
    title.textContent = String(task.kind || "-") + " · " + percentOf(task) + "%";

    const meta = document.createElement("span");
    meta.className = "task-meta";
    meta.textContent = metaText(task);

    row.appendChild(title);
    row.appendChild(meta);
    row.addEventListener("click", () => void loadDetail(String(task.task_id || "")));
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      void loadDetail(String(task.task_id || ""));
    });
    return row;
  }

  function renderTasks(tasks) {
    el.list.replaceChildren();
    el.empty.hidden = tasks.length > 0;
    for (const task of tasks) el.list.appendChild(taskRow(task));
  }

  function detailValue(task, key) {
    if (key === "status") return statusText(task.status);
    if (key === "percent") return percentOf(task) + "%";
    if (key === "started_at" || key === "updated_at") return panels.formatTime(task[key]);
    const raw = task[key];
    if (raw === null || raw === undefined || raw === "") return "-";
    return String(raw);
  }

  function renderDetail(task) {
    const rows = document.createElement("dl");
    for (const [key, label] of DETAIL_FIELDS) {
      const term = document.createElement("dt");
      term.textContent = label;
      const value = document.createElement("dd");
      value.textContent = detailValue(task, key);
      rows.appendChild(term);
      rows.appendChild(value);
    }
    el.detail.dataset.state = task.status === "failed" ? "failed" : "ok";
    el.detail.replaceChildren(rows);
    el.detail.hidden = false;
  }

  /** 详情取不到时由详情区自己说清楚：列表里已渲染的事实不受牵连。 */
  function renderDetailFailure(text) {
    const line = document.createElement("p");
    line.textContent = text;
    el.detail.dataset.state = "failed";
    el.detail.replaceChildren(line);
    el.detail.hidden = false;
  }

  async function loadDetail(taskId) {
    if (!taskId) return;
    let result;
    try {
      result = await panels.request("GET", DETAIL_PATH + encodeURIComponent(taskId));
    } catch (error) {
      renderDetailFailure("无法连接到服务");
      return;
    }
    if (!result.ok) {
      renderDetailFailure(panels.describeFailure(result));
      return;
    }
    renderDetail(result.payload && typeof result.payload === "object" ? result.payload : {});
  }

  async function loadTasks() {
    if (loading) return;
    loading = true;
    let result;
    try {
      result = await panels.request("GET", LIST_PATH);
    } catch (error) {
      loading = false;
      setStatus("failed", "无法连接到服务");
      schedulePoll();
      return;
    }
    loading = false;
    if (!result.ok) {
      setStatus("failed", panels.describeFailure(result));
      schedulePoll();
      return;
    }
    const tasks = tasksOf(result.payload);
    renderTasks(tasks);
    setStatus("idle", tasks.length ? "共 " + tasks.length + " 个任务" : "");
    if (hasActive(tasks)) schedulePoll();
    else stopPolling();
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopPolling();
      return;
    }
    void loadTasks();
  });

  void loadTasks();
})();
