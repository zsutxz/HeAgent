# Story 50-6 验收：网页控制台 UI（真实浏览器）

- 日期：2026-09-24
- 驱动：`tests/js/console_acceptance.mjs`（自起**真实** `heagent http-server` + headless Chrome，CDP 驱动真实点击）
- 环境：Chrome **153.0.8010.48**；`heagent-http` 0.6.2；Windows；工作区 = 临时目录（脚本自动创建/删除，`--keep` 保留）
- 结论：**17 / 17 PASS**（`ACCEPTANCE {"rows":17,"failed":0}`）—— 首次交付（2026-09-24）
- **收口后补记（2026-09-24）**：新增 **A1b**（首页无阻塞遮罩）后为 **18 / 18 PASS**（`ACCEPTANCE {"rows":18,"failed":0}`）。
  补入原因：原 17 行**没有一行**能发现「打开首页即弹出关不掉的确认遮罩」（`hidden` 属性为真却照样渲染，且吞掉
  整页真实鼠标点击）—— 判据问题逐条分析见文末「收口后新增的判据」。

## 怎么复跑

```bash
node tests/js/console_acceptance.mjs            # 起服务 + 起浏览器 → 打印清单表 + ACCEPTANCE 汇总
node tests/js/console_acceptance.mjs --keep     # 保留临时工作区（含 console.png 截图）便于人工比对
```

前提：本机有 Chrome 或 Edge（自动探测；也可 `--chrome <路径>` / `CHROME_PATH`）、已装 `heagent[http]`
（starlette/uvicorn）、`python` 指向装有本仓库的环境（可 `--python <路径>`）。退出码 1 = 有行失败。

脚本**不做**的事（如实声明）：不跑真实 LLM 运行——本机当前无可用 provider（Ollama 未运行），因此
「流式回答」在真浏览器里的观感不在本清单里；该链的前端侧由 node 探针（`tests/js/app_probe.js` 的
A/B/C/D/E/N 用例，注入 SSE 事件断言渲染结果）与 Epic 49 的服务端用例覆盖。

## 清单与实测结果

| # | 步骤（页面） | 期望 | 实测 | 结论 |
|---|---|---|---|---|
| A1 | 首页加载 | 两栏骨架、设置入口、安全声明三条事实同时可见 | 两栏 + 设置入口 + 声明常驻可见 | PASS |
| A1b | 首页加载后立刻查遮罩（计算样式 + 真实命中测试） | 确认遮罩 `display:none`、0 个盒子，真实鼠标点击落到页面元素 | display=none、0 个盒子、视口中心最上层=DIV、真实点击落点=DIV、发送按钮在首屏之下（未纳入判据） | PASS |
| A2 | 观察浏览器网络请求 | 全部请求都同源（CSP + 页面无外链） | 7 个请求全部同源 | PASS |
| A3 | 观察 console / CSP 违规 | 没有 error 级 console 消息或 CSP 拦截 | 0 条 error（favicon 404 按无害过滤） | PASS |
| A4 | 项目列表 | 侧栏列出服务工作区项目且标记为可用 | `default=heagent-console-AtEPbP`（服务工作区徽标），共 1 个 | PASS |
| A5 | 填写目录 → 登记项目 | 侧栏出现该项目，且服务端注册表也有 | 侧栏与 `/api/projects` 都有「验收项目 B」（id=p817fb93b，共 2 个） | PASS |
| A6 | 删除该目录 → 刷新 | 标为 `available=false` 并显示「目录已失效」 | available=false + 「目录已失效」徽标 | PASS |
| A7 | 切到项目 B → 新建会话 → 切回 | 两侧会话列表互不可见（不串味） | B 的会话 1 个、服务工作区 0 个，无交集 | PASS |
| A8 | 刷新页面 | 回到上次的项目，会话仍在（落盘） | 刷新前后都回到「验收项目 B」且会话为 `cd6b9068…` | PASS |
| A9 | 重命名会话（确认框） | 标题更新且磁盘会话文件同步 | `cd6b9068….json` 的 `title` = 验收重命名 | PASS |
| A10 | 删除会话（先取消、再确认） | 取消不删文件；确认后文件消失 | 取消保留、确认后文件消失（2 → 1） | PASS |
| A11 | 打开设置面板 | 按后端分组渲染 + 来源徽标 + 只读项给原因 + 未知键单列 | 20 组 / 113 条（= 后端 113 字段）/ default+global_env+project_env / 67 个只读项全部给了原因 / 未知键 TOTALLY_UNKNOWN | PASS |
| A12 | 项目 `.env` 内预设假密钥后浏览面板 | 明文密钥不出现在页面文本、DOM 与凭证行 | 页面/DOM/行内都没有标记；凭证行只有「已配置 ********」+ 只读原因 | PASS |
| A13 | 改 `MAX_ITERATIONS` → 保存 → 确认 | 磁盘 `.env` 出现新值、显示「下一次运行生效」、来源徽标刷新、写前有备份 | 25 → 321（磁盘 + 面板），来源 project_env，备份 1 个，状态行「已保存：下一次运行生效」 | PASS |
| A14 | 提交非法值（`abc`） | 可理解文案；文件逐字节不变 | 「值不合法：本次没有改动任何文件。 服务端说明：MAX_ITERATIONS: must be a number」，文件未变（115 字节） | PASS |
| A15 | 窗口收窄到 420px + 收起侧栏 | 侧栏可收起（计算样式 `display:none`），安全声明仍可见 | sidebar display:none，声明仍可见 | PASS |
| A16 | 截图留档 | 整页截图写入临时工作区 | `…\heagent-console-AtEPbP\console.png`（49 KB） | PASS |
| B1 | 以 `HTTP_CONSOLE_WRITE_ENABLED=false` 另起一份服务 | 面板说明闸门关闭、全部可写项不可编辑、无任何开启入口 | 闸门说明可见、0 个可编辑控件、可写项原因一致、开关自身只读（无输入框） | PASS |

> A16 的截图路径随临时目录在脚本退出时删除（`--keep` 才保留）；本报告只保留可复跑的**实测结论**。

## 覆盖到哪些验收标准

| AC | 对应行 |
|---|---|
| AC1 两栏 + 设置入口 + 常驻声明 | A1、A11 |
| AC2 切换项目只改本页状态、会话随项目走 | A5、A6、A7、A8 |
| AC3 SSE 行为无回归（流式 / 工具活动 / 停止 / 重连） | 见上文「脚本不做的事」——由 node 探针 A/B/C/D/E 与 49 的服务端用例覆盖，**本清单未含真浏览器 LLM 运行** |
| AC4 有效值 + 来源徽标 + 可写性 + 只读原因 + 凭证掩码 | A11、A12 |
| AC5 闸门关闭 ⇒ 全只读 + 原因 + 无开启入口 | B1 |
| AC6 保存成功 ⇒ 结果 + 「下一次运行生效」+ 刷新来源徽标 | A13 |
| AC7 危险操作二次确认 + 文案说明影响范围 | A9（重命名确认框）、A10（删除会话）、A13（写入确认框） |
| AC8 失败给可理解文案、不渲染不可信 HTML、不加载第三方脚本 | A2、A3、A14 |
| AC9 窄屏降级可用 | A15 |

## 已知缺口（同时登记在活动台账）

1. **浏览器验收不进 CI**：CI 只装 `.[dev]`（无 `heagent[http]`），也没有浏览器 ⇒ 本脚本只能按需手动跑。
   CI 里跑得动的是 node 探针（`tests/test_http_web_ui.py::TestWebUiBehaviour` 等，DOM 替身，不需要浏览器）。
2. **无真实 LLM 的浏览器运行验收**：本机无可用 provider，AC3 的「真浏览器里看着流式回答出现」未做；
   建议在有 provider 的环境用同一脚本补一行（提交提示词 → 断言对话区出现文本且终态为已完成）。
3. 窄屏断言的粒度：A15 只验证「侧栏可收起 + 声明可见」，未逐项验证每个控件的可点性（截图人工比对补充）。
4. **`click()` 用 DOM API，绕过命中测试**：清单里除 A1b 外都用 `node.click()`，因此「全屏元素遮挡点击」这类缺陷
   只有 A1b 能发现（2026-09-24 那条遮罩缺陷 17/17 照旧全绿正是此因）。保留 DOM 点击是**有意**的（真鼠标点击对
   布局变化更脆），代价是遮挡类问题只靠 A1b 一行覆盖。

## 收口后新增的判据（2026-09-24）

**A1b：首页无阻塞遮罩（计算样式 + 真实鼠标命中）** —— 触发背景：用户实测发现打开首页即弹出「请确认」且关不掉。
根因是 `styles.css` 的 `.overlay { display: flex }`（作者级声明）压过 UA 样式表的 `[hidden] { display: none }`，
`#confirm-overlay` 带着 `hidden` 属性照常渲染（`position: fixed` + `inset: 0` + `z-index: 20`）并吞掉整页真实鼠标
点击；`settleConfirm` 又在隐藏遮罩**之前** `if (!pending) return;`，加载时没有 pending ⇒ 关不掉。详见 Story 50-6
「收口后修复」与台账 Z-D15。

判据（三者同时成立才 PASS）：① `getComputedStyle(overlay).display === "none"`；② `overlay.getClientRects().length === 0`；
③ `elementFromPoint`（视口中心，及在视口内时的发送按钮处）与 CDP `Input.dispatchMouseEvent` 派发的**真实点击**落点
都不是 `confirm-overlay`（真实点击用捕捉层记录落点并 `preventDefault`，避免误提交一次运行）。

负向验证：把 `styles.css` 退回无守卫版本重跑整份清单 → **只有 A1b 变红**（exit 1），其余 17 行照旧 PASS。
