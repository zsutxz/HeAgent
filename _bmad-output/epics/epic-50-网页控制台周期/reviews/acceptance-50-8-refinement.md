# Story 50-8 验收：控制台体验优化（真实浏览器 + 单测 + 负向验证）

- 日期：2026-09-24
- 驱动：`tests/js/console_acceptance.mjs`（自起**真实** `heagent http-server`——B 段两份额外服务，含 `--dialog-backend none`——+ headless Chrome，CDP 驱动真实点击）
- 环境：Chrome **153.0.8010.48**；`heagent-http` 0.6.2；Windows；工作区 = 临时目录（脚本自动创建，`--keep` 保留）
- 结论：**23 / 23 PASS**（`ACCEPTANCE {"rows":23,"failed":0}`）
  - 首轮追加 A5b / A11b / A11c / B2（18 → 22 行）；
  - **第二轮（用户裁决）追加 A11d**，并把 A11b 的阈值由 20 改为 **10**（22 → 23 行）。
  - **第三轮（用户裁决 R7/R8）重写 A11d 的判据**：由「限宽居中」改为「对话区**占满该列** + 控件在**会话列表之上** +
    三列里**对话列最宽**」（行数仍 23）。新判据第一版当场变红（`{"chat":0,…}`）：`#chat-log` 为空时命中
    `.chat-log:empty{display:none}` ⇒ 它的盒子恒为 0，改量 `.chat` 这一**列容器**才拿到 812px。
  - A11d 另外留下**两张人眼可复核的截图**（`--keep` 时随工作区保留）：`console-a11d-2col-chat-fullwidth.png`
    （两栏：正文铺满该列 + 「显示全部」在列表之上）与 `console-a11d-3col-settings-open.png`（三列：对话列最宽）。
- 复跑：`node tests/js/console_acceptance.mjs --python E:/AI/HeAgent/.venv/Scripts/python.exe`
  （前提：本机有 Chrome/Edge、已装 `heagent[http]`；退出码 1 = 有行失败）

## 清单与实测结果

| # | 步骤（页面） | 期望 | 实测 | 结论 |
|---|---|---|---|---|
| A1 | 首页骨架 + 常驻安全声明 | 两栏骨架、设置入口、安全声明三条事实同时可见 | 两栏 + 设置入口 + 声明常驻可见 | PASS |
| A1b | 首页无阻塞遮罩（计算样式 + 真实命中） | 遮罩 `display:none`、真实鼠标点击落到页面元素 | display=none、0 个盒子、视口中心最上层=LI、真实点击落点=LI | PASS |
| A2 | 无第三方请求 | 全部请求同源 | 7 个请求全部同源 | PASS |
| A3 | 无 console 错误 / CSP 违规 | 0 条 error | 0 条 error（favicon 404 按无害过滤） | PASS |
| A4 | 项目列表渲染 | 服务工作区在列且可用 | default=heagent-console-*（服务工作区），共 1 个 | PASS |
| A5 | 登记项目（真实 POST） | 侧栏与服务端注册表都有该项目 | 两侧都有「验收项目 B」（id=p88d5c44e，共 2 个） | PASS |
| **A5b** | **「选择文件夹…」入口（R2）** | 表单内有服务端原生选择按钮，且与手工输入共存 | 「选择文件夹…」与「登记项目」同表单、`type=button`、带「在服务端机器上打开」说明、手工输入仍可编辑 | **PASS** |
| A6 | 目录失效可见标记 | `available=false` + 「目录已失效」 | available=false + 「目录已失效」徽标 | PASS |
| A7 | 切换项目刷新会话（隔离） | 两侧会话互不可见 | B 的会话 1 个、服务工作区 0 个，无交集 | PASS |
| A8 | 会话持久化 | 刷新后仍在（落盘） | 刷新前后都回到「验收项目 B」且会话为 `15c77c13…` | PASS |
| A9 | 重命名会话 | 标题与磁盘文件同步 | `<sid>.json` 的 `title` = 验收重命名 | PASS |
| A10 | 删除会话（先取消后确认） | 取消不删、确认后文件消失 | 取消保留、确认后文件消失（2 → 1） | PASS |
| A11 | 设置面板（分组 / 来源 / 只读原因） | 分组 + 来源徽标 + 只读原因 + 未知键单列 | 20 组 / 113 条（= 后端 113 字段）/ default+global_env+project_env / 67 个只读项全部给了原因 / 未知键 TOTALLY_UNKNOWN | PASS |
| **A11b** | **会话列表只显示最近 10 条（R1）** | 10+ 会话时只渲染 10 条、显示总数、展开后全部可见 | 用**真实 API** 造到 21 个会话：默认渲染 10 条（「共 21 个会话 · 只显示最近 10 条」），点「显示全部（21）」后 21 条全部可见 | **PASS** |
| **A11c** | **设置面板瘦身（R4）** | 无整句长解释；诊断/未知键默认收起且标题带条数；只读原因是短标签 | 诊断「项目 .env 诊断」与未知键「未知键（1 条，不生效）」默认收起；67 条只读原因均为「只读：…」短标签；面板文本里无「网页无法自行开启」「需在启动配置」 | **PASS** |
| **A11d** | **布局：一列侧栏 + 对话区占满所在列（R6/R7/R8）** | 项目与会话同栏堆叠；对话正文与输入条**铺满该列**（不再限宽居中）；设置面板打开时对话列仍最宽；会话控件在列表之上 | **1600px 视口**下实测：`显示全部` 底边 **687 ≤ 740** 会话列表顶边；设置面板打开时对话 **812px > 设置 508px**；侧栏 `flex/column` 且两个面板同栏堆叠；对话正文 **1288px**（= 该列 1320 − 内边距 16/16）、输入条 **1288px** | **PASS** |
| A12 | 凭证零明文 | 密钥标记不出现在页面/DOM/行内 | 页面/DOM/行内都没有标记；凭证行只有「已配置 ********」 | PASS |
| A13 | 保存配置（确认 → 写入 → 生效时机） | 磁盘出现新值 + 「下一次运行生效」+ 徽标刷新 + 有备份 | 25 → 321（磁盘 + 面板），来源 project_env，备份 1 个 | PASS |
| A14 | 非法值被拒且文件不变 | 可理解文案 + 文件逐字节不变 | 「值不合法：本次没有改动任何文件。服务端说明：MAX_ITERATIONS: must be a number」，文件未变（115 字节） | PASS |
| A15 | 窄屏降级 + 侧栏可收起 | 420px 下侧栏收起、声明仍可见 | sidebar display=none，声明仍可见 | PASS |
| A16 | 截图留档 | 整页截图 | `<workspace>/console.png`（46 KB） | PASS |
| B1 | 闸门关闭：全只读 + 原因 + 无开启入口 | 面板说明闸门关闭、全部可写项不可编辑 | 闸门说明可见（一行短状态）、0 个可编辑控件、可写项原因一致、开关自身只读；**且面板文本无长句** | PASS |
| **B2** | **选择文件夹：不可用路径（R2）** | `--dialog-backend none` 的服务上点击按钮 ⇒ 给原因、不回填、不登记 | 「本机没有可用的图形目录选择器（或服务启动时禁用了它）：请手工填写目录的绝对路径。 服务端说明：directory dialog is disabled (--dialog-backend none)」，输入框未被改动 | **PASS** |

> A16 截图随临时目录删除（`--keep` 才保留）；本报告只留可复跑的**实测结论**。

## 覆盖到哪些 AC（本 story）

| AC | 覆盖方式 |
|---|---|
| AC1 会话列表只显示最近 10 条（可展开、当前会话永远可见） | A11b（真浏览器）+ 探针 P/Q（`tests/js/app_probe.js`，含「当前会话落在窗口外 ⇒ 自动展开且按钮隐藏」）+ `test_http_web_ui.py::TestConsoleRefinement` 两例 |
| AC2 原生目录选择填回路径、取消无副作用 | A5b（入口形态）+ B2（不可用路径端到端）+ 探针 R（成功回填且**不发** `POST /api/projects`、取消文案）+ `tests/network/test_http_console_dialogs.py`（真 console 装配：成功 / 取消 / 503 / 409 / 回环门 / 无副作用） |
| AC3 三种边界（无后端 / 在途 / 非回环） | `TestEndpoint` 6 例 + `TestRealAssembly` 4 例（含「非回环⇒不 spawn」「并发⇒409」）；真机探针见下 |
| AC4 设置面板瘦身但不丢信息 | A11c + B1（真浏览器）+ 探针 S + `test_settings_panel_is_compact_without_losing_reasons` / `test_diagnostics_and_unknown_keys_are_collapsed_by_default` |
| AC5 侧栏一列（项目与会话同栏） | A11d（真浏览器计算样式）+ `test_sidebar_keeps_projects_and_sessions_in_one_column`（含「`display: contents` 不得回来」的护栏）+ A1/A15（收起与窄屏） |
| AC6 无回归 | 全量 3139 passed；A2/A3/A7…A15 全绿 |
| AC7 新错误码有文案 | `test_every_console_error_code_has_a_readable_text`（由 `HttpErrorCode` 枚举派生，**32 → 34 条**）+ `tests/network/test_http_protocol.py` 的码集断言 |
| AC8 文档与台账 | `docs/frame.md` 4.18（+3 行 / 错误码 32→34 / 安全声明段）/ 五（+3 行）/ 七（+1 段）；活动台账 +2 条；`sprint-status.yaml` |
| AC9 网页侧读取结果收敛 | R5 两半的真实装配用例 + 安全用例（内容不进帧 / 模型仍拿到 / 日志也没有）+ 探针 T（格式不变） |
| ~~AC10 ChatGPT 式限宽居中阅读列~~（2026-09-24 第三轮**用户裁决撤销**） | 由 AC11 取代——原 A11d 的「768px 居中」判据同时作废 |
| AC11 对话区**占满该列**（R7） | A11d（**1600px 视口**实测正文 1288px = 该列 1320 − 内边距 16/16、输入条 1288px；设置面板打开时对话 812px > 设置 508px）+ `test_chat_content_fills_the_column` + `test_settings_open_keeps_the_chat_column_the_widest` |
| AC12 会话控件在**列表之上**（R8） | A11d（几何实测 `显示全部` 底边 687 ≤ 列表顶边 740）+ `test_session_scale_controls_sit_at_the_top_of_the_sessions_panel` |

## 真实弹窗：唯一不能自动化的那一步

`file_read` 之外，本 story 唯一新增的宿主面是**真实原生窗口**——「选中并确认」需要人眼与人手，浏览器清单
只能覆盖「按钮存在 / 不可用路径 / 取消或超时」。已做的**真机**验证（一次性探针，会短暂闪窗 ≈2s）：

```
$ .venv\Scripts\python.exe .heagent/tmp/probe_50_8_dialog_real.py
resolve_backend('auto') = tkinter
in_flight(during)=False result=None elapsed=2.0s in_flight(after)=False
stderr: directory dialog timed out after 2s; treated as cancelled
```

即：**后端解析 → 真实拉起 tkinter 子进程（窗口真的出现）→ 2s 超时 → kill + 归还名额 + WARNING** 全链路成立；
`result=None` 是「超时按取消」的既定语义。（`in_flight(during)` 的观测点在调用之前——探针自身顺序问题，
在途语义由 `test_busy_while_another_pick_is_in_flight` 与 `test_cancellation_kills_the_child_and_releases` 覆盖。）

## 负向验证（`.heagent/tmp/mutate_50_8.py`，17 条变异 **17/17 精确变红**）

| # | 变异 | 结果 |
|---|---|---|
| M1 | 去掉选择器端点的回环门 | 2 failed（非回环被拒 + 不 spawn） |
| M2 | 去掉单在途守卫 | 2 failed（并发 ⇒ busy） |
| M3 | 不解析标记行、直接回传 stdout | 2 failed（脏值/无标记用例） |
| M4 | 超时不终止子进程 | 3 failed（kill 断言） |
| M5 | 会话列表不再截断 | 1 failed（探针 P） |
| M6 | 当前会话在窗口外时不自动展开 | 1 failed（探针 Q） |
| M7 | 整句长解释塞回设置面板 | 1 failed（探针 S：`gateText` 必须等于短状态） |
| M8 | 读取结果无内容时不再回显作用对象 | 1 failed（探针 T） |
| M9 | 网页不再对 `file_read` 收敛 | 3 failed（R5 + 日志面） |
| M10 | 连失败消息也收敛 | 1 failed（`Error:` 前缀判据） |
| M11 | 新错误码缺状态码映射 | 2 failed（503 退化成 400） |
| **M12** | **侧栏回退成多栏（`display:contents`）** | **1 failed（一列口径护栏）** |
| **M13** | **对话区把限宽阅读列加回来（撤销 R7）** | **1 failed（`test_chat_content_fills_the_column`）** |
| **M14** | **会话截断阈值回到 20** | **2 failed（探针 P 的「10 条」与自动展开边界）** |
| **M15** | **会话规模/展开控件挪回列表下方（撤销 R8）** | **1 failed（`test_session_scale_controls_sit_at_the_top_of_the_sessions_panel`）** |
| **M16** | **三列份额翻回「设置面板比对话列宽」** | **1 failed（`test_settings_open_keeps_the_chat_column_the_widest`）** |
| **M17** | **输入条也加上限宽（与正文不同宽）** | **1 failed（`.composer > *` 不得有 `max-width`）** |

每条变异写完即用**原始 bytes** 还原并复核 sha256（脚本内置断言）。

## 质量门（实测）

```bash
$ .venv\Scripts\python.exe -m pytest -q --cov=heagent --cov-fail-under=87 --cov-report=term --no-header -p no:randomly
TOTAL                                          13041    868   3546    391    92%
Required test coverage of 87% reached. Total coverage: 91.88%
3139 passed, 11 skipped, 18 deselected, 8 warnings in 169.73s (0:02:49)

$ .venv\Scripts\python.exe -m pytest tests/test_cli_dialogs.py tests/network/test_http_console_dialogs.py -q --cov=heagent.cli_dialogs
src\heagent\cli_dialogs.py     113      6     34      2    93%   108-110, 123, 127, 165
43 passed in 0.68s

$ .venv\Scripts\python.exe -m ruff check src tests          → All checks passed!
$ .venv\Scripts\python.exe -m ruff format --check src tests  → 280 files already formatted
$ .venv\Scripts\python.exe -m mypy src                       → Success: no issues found in 147 source files
$ .venv\Scripts\python.exe -m mypy src --platform linux      → Success: no issues found in 147 source files
$ .venv\Scripts\python.exe -m heagent http-server --help | findstr dialog-backend
  --dialog-backend [auto|tkinter|powershell|none]

$ node tests/js/console_acceptance.mjs --python E:/AI/HeAgent/.venv/Scripts/python.exe
ACCEPTANCE {"rows":23,"failed":0,"workspace":"…\\heagent-console-T5HOUf","chrome":"Chrome/153.0.8010.48"}

$ .venv\Scripts\python.exe .heagent/tmp/mutate_50_8.py
合计 17 条变异，未变红 0 条：[]
```

> 上一轮（第二轮）的对应数字为 `3137 passed / 91.88%`、真浏览器 23/23、变异 14/14；本轮把 U/I 判据改向
> （R7 撤销限宽、R8 控件置顶）后复跑，数字如上。

## 已知缺口（同时登记在 `docs/frame.md` 五 与活动台账）

1. **网页请求可拉起宿主 GUI 进程**（本 story 有意引入的新暴露面）：回环门 + 单在途 + 冻结 argv + 超时都
   只是 defense-in-depth；回环 peer ≠ 可信，能连上端口的本机进程都能让服务机弹窗。
2. **不可用环境**：无图形后端 / 服务在远程机器 / `--dialog-backend none` ⇒ 一律 `dialog_unavailable` + 保留手工输入；
   不做服务端目录浏览 API（那会把宿主目录结构开放给回环客户端）。
3. **真实弹窗的那一步无法自动化**（见上）；`tkinter` 冻结脚本在 CI 里永不执行，只钉「能编译」。
4. **`Error:` 前缀判据是展示层启发式**：内置工具用返回值表达可预期失败，若将来改结构化错误，该判据应退化为只看 `is_error`。
5. 既有缺口未变：浏览器验收不进 CI、无真实 LLM 运行的浏览器验收（Z-D15 同处）、非回环运行姿态（blocked）。
