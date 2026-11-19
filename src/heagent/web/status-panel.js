/* 服务器状态面板（Epic 71，Story 71.6）：消费 GET /api/status。
 *
 * 渲染纪律与其它面板一致：一律 textContent / createElement（listener 地址、provider 名、作业 id
 * 都是不可信输入），请求经 `window.HePanels.request`（同源；HTTP 错误是结果，只有网络失败才抛）。
 *
 * 轮询不变量：状态只在**面板展开**时按固定间隔取——收起即停、标签页隐藏即停，恢复可见且仍展开时
 * 立刻补一次。顶栏徽标只在页面加载时取一次、随后续轮询更新：它刻意不进 app.js 的 5 秒 health
 * 循环（那里只问服务是否活着）。
 *
 * 排版：五个分组做成横向 tab 条（`role="tablist"`），一次只渲染选中的那组——侧栏只有 280px，
 * 纵向堆 40+ 行会把对话区推出屏幕。切 tab 用最近一次快照重渲染，**不额外请求**（轮询节奏只由
 * 收起/隐藏驱动，切换页签不是取数理由）。
 *
 * 作用域纪律：`active_runs` 是**服务级**合计、`max_inflight_runs` 是**每项目**上限，两者不得按
 * 比率渲染（两个项目各跑一个 run 时是 2 / 1，看起来像超卖）；徽标只报在途数，上限单独一行。
 *
 * 不可得即缺席：资源的 null 字段显示「不可用」而不是 0，`resource_source` 单独一行说明采样通路。
 */
(() => {
  "use strict";

  const STATUS_PATH = "/api/status";
  const POLL_MS = 5000;
  const UNAVAILABLE = "不可用";

  const el = {
    badge: document.getElementById("server-status"),
    details: document.getElementById("server-details"),
    groups: document.getElementById("server-groups"),
    status: document.getElementById("server-panel-status"),
  };

  // 本脚本只服务控制台页：元素不全就什么都不做（不抛，其它面板脚本各自独立）。
  if (!el.badge || !el.details || !el.groups || !el.status) return;

  const panels = window.HePanels;
  if (!panels) {
    el.status.dataset.state = "failed";
    el.status.textContent = "面板公共桥未加载";
    return;
  }

  /** 轮询句柄：非 null 即已排好下一次取数；停表后必须归位（否则会重复排程）。 */
  let timer = null;
  /** 一次只在途一个请求：toggle 与可见性切换可能与排程重叠，重叠请求只是白跑一趟。 */
  let loading = false;

  function num(value) {
    return Number.isFinite(value) ? String(value) : "-";
  }

  function text(value) {
    if (value === null || value === undefined || value === "") return "-";
    return String(value);
  }

  /** 秒 → `2d3h` / `1h23m` / `4m5s` / `7s`（粗粒度：量级一眼可读，不堆小数）。 */
  function duration(seconds) {
    if (!Number.isFinite(seconds)) return "-";
    const total = Math.max(0, Math.floor(seconds));
    if (total >= 86400) return Math.floor(total / 86400) + "d" + Math.floor((total % 86400) / 3600) + "h";
    if (total >= 3600) return Math.floor(total / 3600) + "h" + Math.floor((total % 3600) / 60) + "m";
    if (total >= 60) return Math.floor(total / 60) + "m" + (total % 60) + "s";
    return total + "s";
  }

  /** 字节 → MiB；null（采样通路不可用）如实标注，绝不填 0。 */
  function mib(value) {
    if (!Number.isFinite(value)) return UNAVAILABLE;
    return (value / 1048576).toFixed(1) + " MiB";
  }

  function cpuSeconds(value) {
    if (!Number.isFinite(value)) return UNAVAILABLE;
    return value.toFixed(1) + " s";
  }

  function milliseconds(value) {
    if (!Number.isFinite(value)) return "-";
    return Math.round(value) + " ms";
  }

  function modeOf(listeners) {
    if (!Array.isArray(listeners) || listeners.length === 0) return "未暴露";
    return listeners.some((item) => item && item.mode === "external") ? "对外" : "本地";
  }

  function totalConnections(ws) {
    if (!ws || typeof ws !== "object") return 0;
    return [ws.runs, ws.cli, ws.notifications].reduce(
      (sum, value) => sum + (Number.isFinite(value) ? value : 0),
      0,
    );
  }

  function runRows(status) {
    const counts = status.run_status && typeof status.run_status === "object" ? status.run_status : {};
    const ws = status.ws_connections && typeof status.ws_connections === "object" ? status.ws_connections : {};
    return [
      ["在途 run（服务级）", num(status.active_runs)],
      ["单项目并发上限", num(status.max_inflight_runs)],
      ["run 记录数", num(status.run_records)],
      ["运行中", num(counts.running)],
      ["已完成", num(counts.completed)],
      ["失败", num(counts.failed)],
      ["已取消", num(counts.cancelled)],
      ["已超时", num(counts.timed_out)],
      ["WS 连接（run / cli / 通知）", num(ws.runs) + " / " + num(ws.cli) + " / " + num(ws.notifications)],
      ["后台任务", num(status.background_tasks)],
    ];
  }

  function deploymentRows(status) {
    const rows = [];
    const listeners = Array.isArray(status.listeners) ? status.listeners : [];
    for (const item of listeners) {
      if (!item || typeof item !== "object") continue;
      const parts = [text(item.kind) + " " + text(item.host) + ":" + num(item.port), text(item.mode)];
      if (item.tls) parts.push("TLS");
      rows.push([text(item.label), parts.join(" · ")]);
    }
    rows.push(["沙箱后端", text(status.sandbox_backend)]);
    rows.push(["配置写入", status.config_write_enabled ? "允许" : "只读"]);
    rows.push(["当前 provider", text(status.active_provider)]);
    const pools = Array.isArray(status.routing_pools) ? status.routing_pools : [];
    for (const pool of pools) {
      if (!pool || typeof pool !== "object") continue;
      const tiers = Array.isArray(pool.tiers) ? pool.tiers.map((tier) => text(tier)) : [];
      rows.push(["路由池 " + text(pool.pool), tiers.length ? tiers.join(" / ") : "无档位"]);
    }
    return rows;
  }

  function dependencyRows(status) {
    const jobs = Array.isArray(status.cron_jobs) ? status.cron_jobs : [];
    const rows = [
      ["启动时刻", panels.formatTime(status.started_at)],
      ["uptime", duration(status.uptime_seconds)],
      ["cron 作业", num(jobs.length) + " 条"],
      ["技能数", num(status.skill_count)],
      ["记忆条目", num(status.memory_facts)],
    ];
    for (const job of jobs) {
      if (!job || typeof job !== "object") continue;
      const parts = [text(job.cron), text(job.last_status), panels.formatTime(job.last_run)];
      rows.push(["作业 " + text(job.job_id), parts.join(" · ")]);
    }
    return rows;
  }

  function resourceRows(status) {
    return [
      ["RSS", mib(status.rss_bytes)],
      ["线程数", Number.isFinite(status.threads) ? num(status.threads) : UNAVAILABLE],
      ["CPU 时间", cpuSeconds(status.cpu_seconds)],
      ["采样通路", text(status.resource_source)],
    ];
  }

  function requestRows(status) {
    const requests = status.requests && typeof status.requests === "object" ? status.requests : {};
    const codes = Array.isArray(requests.error_codes) ? requests.error_codes : [];
    const codeText = codes
      .map((item) => text(item && item.code) + "×" + num(item && item.count))
      .join(" · ");
    return [
      ["请求总数", num(requests.total)],
      ["2xx / 3xx", num(requests.status_2xx) + " / " + num(requests.status_3xx)],
      ["4xx / 5xx", num(requests.status_4xx) + " / " + num(requests.status_5xx)],
      ["延迟 p50 / max", milliseconds(requests.latency_p50_ms) + " / " + milliseconds(requests.latency_max_ms)],
      ["错误码", codes.length ? codeText : "无"],
    ];
  }

  /** 组序即阅读序：先「现在怎么样」，再「跑在哪」，最后是依赖与观测；同时决定 tab 的左→右顺序。 */
  const GROUPS = [
    ["运行态", runRows],
    ["部署面", deploymentRows],
    ["依赖态", dependencyRows],
    ["资源", resourceRows],
    ["请求计数", requestRows],
  ];

  const TAB_PANEL_ID = "server-tabpanel";

  /** 选中的分组序号；tab 栏与面板容器懒建一次（收起时不进 DOM）。 */
  let activeGroup = 0;
  /** 最近一次成功的快照：切 tab 据此重渲染，不为换页签再打一次 /api/status。 */
  let lastStatus = null;
  let tablist = null;
  let tabpanel = null;

  function renderBadge(status) {
    const parts = [
      modeOf(status.listeners),
      "up " + duration(status.uptime_seconds),
      "run " + num(status.active_runs),
      "WS " + num(totalConnections(status.ws_connections)),
    ];
    el.badge.textContent = parts.join(" · ");
    el.badge.dataset.state = "ready";
    el.badge.title = "服务器状态快照（" + panels.formatTime(new Date().toISOString()) + "）";
    el.badge.hidden = false;
  }

  /** 建 tab 栏与面板容器（只建一次；`renderGroups` 先调它，故收起→展开不会重复建）。 */
  function buildTabs() {
    if (tablist !== null) return;
    tablist = document.createElement("div");
    tablist.className = "status-tabs";
    tablist.setAttribute("role", "tablist");
    tablist.setAttribute("aria-label", "服务器状态分组");
    GROUPS.forEach(([title], index) => {
      const tab = document.createElement("button");
      tab.type = "button";
      tab.className = "status-tab";
      tab.id = "server-tab-" + index;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", TAB_PANEL_ID);
      tab.setAttribute("aria-selected", "false");
      tab.tabIndex = -1;
      tab.textContent = title;
      tab.addEventListener("click", () => selectGroup(index));
      tablist.appendChild(tab);
    });
    // 事件委托在 tab 条上：箭头键要跨按钮移动，逐个绑 keydown 会重复同一段逻辑。
    tablist.addEventListener("keydown", onTabKeydown);
    tabpanel = document.createElement("div");
    tabpanel.id = TAB_PANEL_ID;
    tabpanel.className = "status-tabpanel";
    tabpanel.setAttribute("role", "tabpanel");
    tabpanel.tabIndex = 0;
    el.groups.replaceChildren(tablist, tabpanel);
    syncTabs();
  }

  /** 选中态只由 `activeGroup` 推导：`aria-selected`、漫游 tabindex 与面板标签一次性对齐。 */
  function syncTabs() {
    if (tablist === null) return;
    const tabs = tablist.children;
    for (let index = 0; index < tabs.length; index += 1) {
      const selected = index === activeGroup;
      tabs[index].setAttribute("aria-selected", selected ? "true" : "false");
      tabs[index].tabIndex = selected ? 0 : -1;
      if (selected && tabpanel !== null) tabpanel.setAttribute("aria-labelledby", tabs[index].id);
    }
  }

  /** 方向键循环、Home/End 到两端（自动激活：焦点到哪就显示哪组的行）。 */
  function onTabKeydown(event) {
    const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
    if (!keys.includes(event.key)) return;
    let next = activeGroup;
    if (event.key === "Home") {
      next = 0;
    } else if (event.key === "End") {
      next = GROUPS.length - 1;
    } else if (event.key === "ArrowLeft") {
      next = (activeGroup - 1 + GROUPS.length) % GROUPS.length;
    } else {
      next = (activeGroup + 1) % GROUPS.length;
    }
    event.preventDefault();
    selectGroup(next);
    const tab = tablist.children[next];
    if (tab) tab.focus();
  }

  function selectGroup(index) {
    activeGroup = index;
    syncTabs();
    renderActiveGroup();
  }

  /** 只渲染选中组：面板里永远只有一张行表，切 tab 即换掉它。 */
  function renderActiveGroup() {
    if (tabpanel === null) return;
    const rows = GROUPS[activeGroup][1](lastStatus || {});
    const list = document.createElement("dl");
    list.className = "status-rows";
    for (const [label, value] of rows) {
      const term = document.createElement("dt");
      term.textContent = label;
      const detail = document.createElement("dd");
      detail.textContent = value;
      list.appendChild(term);
      list.appendChild(detail);
    }
    tabpanel.replaceChildren(list);
  }

  function renderGroups(status) {
    lastStatus = status;
    buildTabs();
    renderActiveGroup();
  }

  /** 失败即「保留上次值 + 标离线」：已渲染的行不清空，原因只进状态行与徽标 title。 */
  function markOffline(reason) {
    el.badge.dataset.state = "offline";
    if (!el.badge.textContent) el.badge.textContent = "状态不可用";
    el.badge.hidden = false;
    el.badge.title = reason;
    el.status.dataset.state = "failed";
    el.status.textContent = reason;
  }

  function shouldPoll() {
    return el.details.open && !document.hidden;
  }

  function stopPolling() {
    if (timer === null) return;
    window.clearTimeout(timer);
    timer = null;
  }

  /** 排下一次取数；面板收起或标签页不可见时不排程（重新展开 / 恢复可见时立刻补一次）。 */
  function schedulePoll() {
    stopPolling();
    if (!shouldPoll()) return;
    timer = window.setTimeout(() => {
      timer = null;
      void loadStatus();
    }, POLL_MS);
  }

  async function loadStatus() {
    if (loading) return;
    loading = true;
    let result;
    try {
      result = await panels.request("GET", STATUS_PATH);
    } catch (error) {
      loading = false;
      markOffline("无法连接到服务");
      schedulePoll();
      return;
    }
    loading = false;
    if (!result.ok) {
      markOffline(panels.describeFailure(result));
      schedulePoll();
      return;
    }
    const status = result.payload && typeof result.payload === "object" ? result.payload : {};
    renderBadge(status);
    // 懒加载：收起时不渲染明细（徽标仍然更新），展开时才建行。
    if (el.details.open) renderGroups(status);
    el.status.dataset.state = "idle";
    el.status.textContent = "更新于 " + panels.formatTime(new Date().toISOString());
    schedulePoll();
  }

  el.details.addEventListener("toggle", () => {
    if (!el.details.open) {
      stopPolling();
      return;
    }
    void loadStatus();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopPolling();
      return;
    }
    if (el.details.open) void loadStatus();
  });

  void loadStatus();
})();
