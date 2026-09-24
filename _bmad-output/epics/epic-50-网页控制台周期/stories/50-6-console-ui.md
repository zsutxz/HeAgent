---
id: 50-6
title: 网页控制台 UI
status: review
baseline_commit: a1012d8a9333ad4b7c93519bad115d272cb731bd
parent_epic: E50
priority: P0
phase: E（整体验收）
depends_on: [50-2, 50-3, 50-4, 50-5]
blocks: [50-7]
created: '2026-09-23'
---

# Story 50-6：网页控制台 UI

## 用户故事

作为控制台用户，我希望界面像 ChatGPT 一样直观：左栏是项目与会话、右栏是对话、设置独立成面板，
并且危险操作、只读原因和「什么时候生效」都一眼可辨。

## 侦察实证（2026-09-23）

| 事实 | 证据 | 含义 |
|---|---|---|
| 静态资源与加载口径已定型 | `src/heagent/web/` = `index.html` / `app.js` / `styles.css` / `__init__.py`；`read_web_asset(name)`（`http_server.py:183`）以 `_WEB_ASSETS` 白名单 + `importlib.resources.files("heagent.web")` 为**唯一**查找方式（AD-11，源码运行与 wheel 安装都成立） | 本 story 只增改这三份资源，不改加载机制 |
| 安全响应头已落地 | `http_server.py:86-93`（严格 CSP + 禁嗅探 + 禁 framing + 不泄露 referrer）；SSE 路径 `cache-control: no-store`（`:992`） | UI 不得引入第三方脚本 / 内联脚本，否则 CSP 直接打断 |
| 既有 UI 测试落点 | `tests/test_http_web_ui.py`、`tests/network/test_http_server.py`、`tests/test_http_security.py` | 新 UI 状态在这些用例的基础上扩展 |
| Epic 49 的交互契约必须延续 | 49-3/49-4/49-5 交付：流式文本、工具活动、停止、断线重连、「连接已断开」不假装完成、错误脱敏文案 | 本 story 是**新增布局**，不是重写交互（I13 / UX-DR7） |
| 仓库没有 JS 测试运行器 | `pyproject.toml` 无 node/jsdom 测试链；49-6 的证据路径是**手工验收清单** | 本 story 沿用：清单写入产物 + 记录实测结果（不得只写「已测」） |

## 范围

- 三份静态资源改造：两栏布局（项目/会话侧栏 + 对话区）+ 独立设置面板。
- 项目侧栏：列表 / 登记 / 切换 / 重命名 / 移除登记（二次确认）。
- 会话侧栏：列表 / 新建 / 切换 / 重命名 / 删除（二次确认）。
- 设置面板：有效值 + 来源徽标 + 可写性 + 只读原因 + 凭证掩码 + 保存结果与「下一次运行生效」。
- 常驻安全声明、「无认证 / 无 TLS / 非安全边界」。
- 新增 UI 状态的可见反馈：项目切换中、会话冲突、配置写入结果、只读原因、目录失效。

## 边界与约束

**Always**

- 文本按**纯文本**渲染（`textContent`），不渲染不可信 HTML；不加载任何第三方脚本 / 字体 / CDN。
- 危险操作（删除会话 / 移除项目登记 / 写入被标记为高影响的键）必须有二次确认，且文案说明影响范围
  （删除会话 = 删文件；移除登记 = 保留目录数据）。
- 只读项显示**原因**（被环境变量覆盖 / 被白名单排除 / 开关未开启 / 服务启动控制项），不静默禁用。
- 凭证只显示「已配置 / 未配置 + 定长掩码」，不提供密钥输入框。
- 保存成功后**必须**显示「下一次运行生效」，并刷新该项的来源徽标。
- 闸门关闭时所有可写项显示为不可编辑 + 原因，**不提供**任何开启入口。
- 既有体验无回归：流式文本、工具活动、停止、断线重连、错误文案维持 Epic 49 行为。

**Never**

- 不前端的配置面板「假装」是安全控制台；常驻声明不可折叠掉。
- 不在前端做校验的**唯一**防线（后端仍必须 fail-closed；前端校验只是体验）。
- 不用 `innerHTML` 渲染任何来自服务端或模型的内容。
- 不在切换项目时改动任何进程级状态，也不中断既有运行。
- 不新增第三方依赖到前端（保持零构建链）。

## 任务（细分）

- [x] **T1** `index.html`：两栏骨架 + 设置面板入口 + 常驻安全声明条；`lang="zh-CN"`；不引入外部资源。
      声明条**没有**折叠/关闭控件（`#security-notice` 常驻），仍只引用 `/styles.css` 与 `/app.js` 两个同源资源。
- [x] **T2** `styles.css`：侧栏/对话/面板布局（含窄屏降级）、来源徽标样式、只读态与禁用态、二次确认对话框。
      加 `.config-item[data-editable="false"]` 只读态、`.badge-source[data-source=…]` 四层来源色、
      `@media (max-width: 1000px)` 单列堆叠 + `.console[data-sidebar-collapsed="true"] .sidebar{display:none}`。
- [x] **T3** `app.js` 项目层：`GET/POST/PATCH/DELETE /api/projects*` 接线；项目切换作用于本地状态（**不动进程状态**）；
      目录失效项显示 `available=false` 的可见标记。切换走「切换中」态（禁用交互 + 可见进度），
      离开有在途运行的项目时只断本页事件流并留提示（不取消运行）。
- [x] **T4** `app.js` 会话层：列表/新建/切换/重命名/删除；删除走确认；`session_conflict` / `session_busy` /
      `confirm_required` / **`session_unreadable`** 映射为可理解文案。`session_unreadable` 单列一条分支：
      清空对话区 + 可操作说明 + **禁用提交**，绝不显示成空会话（与「冲突」文案互不混用）。
- [x] **T5** `app.js` 设置面板：分组渲染（后端给的分组 + 来源 + `writable` + `read_only_reason`）；
      凭证只渲染 `configured` + 掩码；只读项显示原因（文案取自后端 `labels`）；未知键单列且标明「不生效」。
      另渲染 `env_file` 诊断（路径/存在/可读/行数/指纹/BOM/重复键/空值键）与响应级 `notes`、`ROUTING_POOLS` 有效池摘要。
- [x] **T6** 保存流程：提交 `{changes, fingerprint}`；成功后展示结果 + 「下一次运行生效」并在**同一页**刷新该项来源徽标；
      失败（`invalid_value` / `config_conflict` / `field_not_writable` / `write_disabled` / `loopback_required`）逐类给文案。
      退回旧值 = 撒谎，因此写响应里的写后条目会**就地**更新对应行（面板随后刷新失败时仍显示写后事实）。
- [x] **T7** 状态反馈：项目切换中、会话冲突、写入结果、只读原因四类状态都有可见反馈（无 `console.log` 兜底）。
- [x] **T8** 无回归检查：流式/工具活动/停止/重连按 49 的行为逐条复核。前端侧由 node 探针用例 A–E 断言
      （同名工具配对、终态文案、接手在途运行、忙时提交不静默、键盘语义），服务端侧由 49 的既有用例覆盖。
- [x] **T9** 静态资源测试：`tests/test_http_web_ui.py` 扩展——白名单命中、CSP 生效（无内联脚本/样式/事件属性）、
      无第三方 URL（三份资源都做 `http://` / `https://` / `//cdn` / CDN 主机名排除性断言）、
      源码运行与 wheel 安装两条路径都能取到资源（`read_web_asset` + `TestPackagedAssets`）。
- [x] **T10** 手工验收清单：`reviews/acceptance-50-6-console-ui.md`（17 行，四列含**实测结果**），
      由 `tests/js/console_acceptance.mjs`（真实 http-server + headless Chrome + CDP 驱动真实点击）产出。

## 验收标准

- **AC1** Given 用户打开控制台首页，When 页面加载，Then 显示两栏布局（项目/会话侧栏 + 对话区）、设置入口，
  以及常驻的「无认证 / 无 TLS / 非安全边界」声明。
- **AC2** Given 项目列表已加载，When 用户切换项目，Then 侧栏刷新为该项目会话，对话区切到该项目的当前会话，
  且**不修改**任何进程级状态；切换期间既有运行保持原项目绑定。
- **AC3** Given 用户提交提示词，When SSE 推送文本与工具事件，Then 对话区按序更新，工具显示名称/目标/结果，
  终态显示成功/失败/取消，行为与 Epic 49 一致（无回归）。
- **AC4** Given 用户打开项目设置，When 面板加载，Then 每项显示有效值、来源徽标、可写性；只读项显示**原因**；
  凭证项只显示「已配置/未配置 + 掩码」。
- **AC5** Given 写入闸门关闭，When 用户查看设置面板，Then 所有可写项显示为不可编辑并说明「服务启动时未开启配置写入」，
  **不提供**任何开启入口。
- **AC6** Given 用户保存一项配置，When 保存成功，Then 面板显示保存结果与「下一次运行生效」，并刷新该项的来源徽标。
- **AC7** Given 用户删除会话或移除项目登记，When 点击操作，Then 出现二次确认，文案说明影响范围
  （删除会话 = 删文件；移除登记 = 保留目录数据）。
- **AC8** Given 请求失败（非法值 / 冲突 / 只读 / 目录失效 / 冲突运行），When 错误返回，Then UI 显示可理解的稳定文案，
  不渲染不可信 HTML，不加载第三方脚本。
- **AC9** Given 一台窄屏设备，When 打开控制台，Then 布局降级可用（侧栏可收起或堆叠），核心操作仍可达。

## Definition of Done

**交付物**：`src/heagent/web/index.html`、`src/heagent/web/app.js`、`src/heagent/web/styles.css`、
`tests/test_http_web_ui.py`（扩展）、手工验收清单（含实测结果）。

**验证命令**：

```bash
pytest tests/test_http_web_ui.py tests/network tests/test_http_security.py -q
pytest -q
ruff check src tests && mypy src && mypy src --platform linux
python -m pip install -e . && python -c "from heagent.network.http_server import read_web_asset; print(len(read_web_asset('app.js')))"
```

**手工验收**：清单逐条执行并把**实测结果**写入产物（不得只写「已验证」）；记录浏览器与控制台 URL。

**负向验证**：①在 `index.html` 注入一个 `https://` 外链 → 「无第三方 URL」排除性断言变红；
②去掉/放宽 CSP 头 → CSP 断言变红；③从 `_WEB_ASSETS` 白名单里删掉一个资源名 → 该资源的加载测试变红。
三项各自确认后复原，全绿。

**质量门**：`pytest`、`ruff check`、`ruff format --check src tests`、`mypy src`、`mypy src --platform linux` 全绿。

## 代码地图

| 路径 | 角色 | 改动 |
|---|---|---|
| `src/heagent/web/index.html` | 页面骨架 | 两栏 + 设置面板 + 安全声明 |
| `src/heagent/web/app.js` | 交互 | 项目/会话/设置三层接线 + 状态反馈 |
| `src/heagent/web/styles.css` | 样式 | 布局 / 徽标 / 只读态 / 确认框 |
| `src/heagent/network/http_server.py` | 资源服务（既有） | 无需改动（除非新增资源名要进 `_WEB_ASSETS`） |
| `tests/test_http_web_ui.py` | UI 资源测试 | 白名单 / CSP / 无第三方 URL / wheel 路径 |

## 风险与未决

- **R1**：若新增静态资源文件名（例如拆分 `app.js`），**必须**同步 `_WEB_ASSETS` 白名单，否则 `read_web_asset`
  抛 `KeyError` → 404。建议不拆文件（少一个漂移点）。
- **R2**：手工验收无法被 CI 覆盖，属于**已知缺口**的延续（GUI 同样无自动化测试）。本 story 至少把清单固化，
  并在 50-7 的文档里如实记录「UI 无自动化回归」。
- **R3**：`cache-control: no-store` 目前只加在 SSE 路径（实测 `http_server.py:992`）；静态资源是否需要
  `no-store` 由实现时按「避免旧 JS 与新 API 错配」判断，若加需在 50-7 的观测/文档里记录。

## Requirement Traceability

FR-6；NFR-9, NFR-10；UX-DR1–UX-DR7；脊柱 I9, I12, I13；brief §4 FR-6、§2 场景表。

## Dev Agent Record

### Implementation Plan

1. **后端最小补充**（先说清为什么必须动协议）：面板需要知道「写入闸门」状态，否则 AC5 无法诚实渲染
   —— `ProjectConfigResponse` 加 `write_enabled`（入口层填写，无默认值 ⇒ 漏传即构造失败），
   `config_catalog.LABELS` 加 `write_channel_disabled` 文案。
2. **三份静态资源**：`index.html`（两栏 + 设置面板 + 常驻声明 + 确认层）、`styles.css`（布局 / 徽标 /
   只读态 / 窄屏降级）、`app.js`（项目层 / 会话层 / 设置层 / 状态反馈；49 的对话区行为原样保留）。
3. **测试**：扩展 `tests/js/app_probe.js`（真实 app.js + 最小 DOM 替身，用例 A–N）与
   `tests/test_http_web_ui.py`（静态契约 + 行为断言）。
4. **真实浏览器验收驱动**：新增 `tests/js/console_acceptance.mjs`（自起 http-server + headless Chrome +
   CDP 真实点击）产出 T10 的四列清单。
5. **负向验证**：`.heagent/tmp/mutate_50_6.py` 十条变异体（含 DoD 要求的三条），逐条确认精确变红。

### Completion Notes

**与 story 文本 / 代码地图的偏离（3 处，均有理由）**

1. **`ProjectConfigResponse.write_enabled`（新增协议字段，超出「只改三份资源」的代码地图）**：
   AC5 要求「闸门关闭 ⇒ 所有可写项显示为不可编辑 + 说明原因」，而条目上的 `writable` 只表达
   「在显式白名单内且未被系统环境变量提供」（实测：闸门关着时 `MAX_ITERATIONS.writable` 仍为 `True`）
   ——只凭它渲染必然出现「面板说可编辑、保存必被拒」。该字段由**持有闸门的入口层**填写（与 PUT 的裁决
   同一事实源，不是第二份副本），**无默认值**（漏传即构造期失败，逼调用方正面回答）。
2. **「写入被标记为高影响的键」在协议里没有标记** ⇒ 口径裁定为**所有写入都二次确认**（确认框列出将改的
   键、写入路径、备份语义与「只对下一次运行生效」）。方向是宁多确认；若日后要分级，只能新增后端字段，
   不得在前端硬编码键名清单（已登记活动台账）。
3. **两条 49 契约断言随交互面变更而更新**（`tests/test_http_web_ui.py`）：提交端点从 `POST /api/runs`
   改为项目内运行入口 `POST /api/projects/{id}/runs`；刷新恢复从 `GET /api/session` 改为
   「项目列表 + 该项目会话详情」。**行为不变**（刷新继续对话、接手在途运行、忙时不静默、键盘语义、
   同名工具配对、终态文案全部由探针逐条钉住），变的是「会话由项目承载」（D2 每请求带项目参数）。
   另 `tests/network/test_http_server.py` 的 `<title>` 断言同步为 `HeAgent 控制台`。

**关键设计点（供评审复核）**

- **切换项目只改本页状态**：唯一的持久偏好是 `localStorage` 里的一个项目 id；不改进程 cwd / 环境变量，
  也不取消在途运行。离开「正在运行的项目」时**只断本页 SSE**（服务端断线不取消运行）并留一条常驻提示
  （「仍在继续…切回即接手」），切回该项目时由会话详情的 `status=running` 重新接手事件流。
- **面板文案一律由后端派生**：只读原因 / 诊断 / 来源 / 守卫提示都来自 `labels`、`guards`、`source`
  与 `env_file`（`guardHint` 由 `guards` 生成枚举或上下界提示）；前端不硬编码键名、原因或边界
  ⇒ 后端补 `VALUE_GUARDS` 上界时 UI 自动跟随。
- **闸门关闭时零开启入口**：可写项渲染为**禁用输入框 + 原因**，开关自身也不可编辑（验收 B1 断言
  `#settings-groups` 内可编辑控件数为 0）。
- **写响应里的写后条目就地更新对应行**：面板随后的全量刷新失败时，写过的行仍显示服务端返回的写后值与
  来源（退回旧值 = 对用户撒谎），状态行同时说明「面板刷新失败、其余项可能过时」。
- **凭证零明文**：只渲染 `configured` + 定长掩码，不提供输入框；真实浏览器验收（A12）用一个假密钥标记
  同时在页面文本、`documentElement.outerHTML` 与凭证行里做排除性断言。
- **纯文本渲染**：项目名 / 会话标题 / 配置值 / 错误文案全部经 `createTextNode`；确认框文案（含项目路径）
  同样走 `textContent`，无 `innerHTML` / 内联事件属性（静态契约断言钉住）。

### 验证（实测命令 + 输出）

```bash
$ python -m pytest tests/test_http_web_ui.py -q
96 passed in 1.58s            # 静态契约 + 14 个前端行为用例（node 探针）

$ python -m pytest -q
3012 passed, 11 skipped, 18 deselected, 8 warnings in 142.99s (0:02:22)

$ python -m pytest -q --cov --cov-report=term | findstr /c:"TOTAL"
TOTAL                                          12857    869   3500    392    92%
3012 passed, 11 skipped, 18 deselected, 8 warnings in 162.59s (0:02:42)

$ ruff check src tests && ruff format --check src tests
All checks passed! / 276 files already formatted

$ mypy src && mypy src --platform linux
Success: no issues found in 146 source files        # 两次均干净

$ node tests/js/console_acceptance.mjs             # T10：真实浏览器验收（17 行）
# Chrome 153.0.8010.48；heagent-http 0.6.2
✓ A1 首页骨架 + 常驻安全声明 — 两栏 + 设置入口 + 声明常驻可见
✓ A2 无第三方请求 — 7 个请求全部同源
✓ A3 无 console 错误 / CSP 违规 — 0 条 error（favicon 404 按无害过滤）
✓ A4 项目列表渲染 — default=heagent-console-AtEPbP（服务工作区），共 1 个
✓ A5 登记项目（真实 POST） — 侧栏与 /api/projects 都有「验收项目 B」（id=p817fb93b，共 2 个）
✓ A6 目录失效可见标记 — available=false + 「目录已失效」徽标
✓ A7 切换项目刷新会话（隔离） — B 的会话 1 个、服务工作区 0 个，无交集
✓ A8 会话持久化 — 刷新前后都回到「验收项目 B」且会话为 cd6b9068…
✓ A9 重命名会话 — cd6b9068….json 的 title = 验收重命名
✓ A10 删除会话（先取消后确认） — 取消保留、确认后文件消失（2 → 1）
✓ A11 设置面板 — 20 组 / 113 条（= 后端 113 字段）/ default+global_env+project_env / 67 个只读项全部给了原因
✓ A12 凭证零明文 — 页面/DOM/行内都没有标记；凭证行只有「已配置 ********」
✓ A13 保存配置 — 25 → 321（磁盘 + 面板），来源 project_env，备份 1 个
✓ A14 非法值被拒且文件不变 — 「值不合法…MAX_ITERATIONS: must be a number」，文件未变（115 字节）
✓ A15 窄屏降级 + 侧栏可收起 — sidebar display:none，声明仍可见
✓ A16 截图留档 — …\heagent-console-AtEPbP\console.png（49 KB）
✓ B1 闸门关闭：全只读 + 原因 + 无开启入口 — 0 个可编辑控件、开关自身只读（无输入框）
ACCEPTANCE {"rows":17,"failed":0,"workspace":"C:\\Users\\skype\\AppData\\Local\\Temp\\heagent-console-AtEPbP","chrome":"Chrome/153.0.8010.48"}
# 全程结论见 reviews/acceptance-50-6-console-ui.md

$ python .heagent/tmp/mutate_50_6.py                # 负向验证（10 个变异体）
[OK] M1 index.html 注入第三方外链（DoD 负向验证①）  -> FAILED test_page_is_self_contained / test_no_third_party_resources_in_any_asset
[OK] M2 CSP 放宽（script-src 加 'unsafe-inline'）（②） -> 3 failed（TestSecurityHeaders 三个参数）
[OK] M3 从 _WEB_ASSETS 删除 styles.css（③）        -> ERROR（KeyError: 'styles.css'）
[OK] M4 UI 无视写闸门                              -> FAILED test_closed_gate_makes_every_writable_field_read_only_with_a_reason
[OK] M5 错误映射退化（退回英文文案）                -> FAILED test_each_stable_code_gets_its_own_text
[OK] M6 删除会话跳过二次确认                        -> FAILED test_delete_requires_confirmation_and_sends_confirm
[OK] M7 损坏会话被当空会话                          -> FAILED test_unreadable_session_is_not_shown_as_an_empty_conversation
[OK] M8 切项目时静默丢弃在途运行                    -> FAILED test_leaving_a_running_project_detaches_the_stream_without_cancelling
[OK] M9 入口层谎报闸门状态                          -> FAILED test_panel_reports_the_write_gate_so_the_ui_can_disable_editing
[OK] M10 保存后不就地刷新来源徽标                   -> FAILED test_write_result_keeps_the_row_truthful_when_the_panel_refresh_fails
合计 10 条变异，异常 0 条   # 每条回退后 sha256 与变异前一致（脚本内断言）

$ python .heagent/tmp/check_eol.py <全部改动文件>
# 全部 LF / 无 BOM / 末行换行（含 3 份资源、探针、验收驱动、story 之外的 11 个文件）
```

**M10 是本次负向验证的真实收获**：第一轮它**没有变红** —— 说明「用写响应就地刷新徽标」这条路径当时
没有任何用例钉住（全量刷新会掩盖它）。补了用例 N（写成功但面板刷新失败）后才变红，并顺带修出一处
UX 缺陷：刷新失败时状态行原本会被「已保存」覆盖（现在会明确说「面板刷新失败，其余项可能过时」）。

### File List

**新增**

| 路径 | 行数 | 说明 |
|---|---|---|
| `tests/js/console_acceptance.mjs` | 683 | 真实浏览器验收驱动（自起 http-server + headless Chrome + CDP，**18 行**清单 —— A1b 为收口后补入，见文末「收口后修复」，退出码即结论） |
| `_bmad-output/epics/epic-50-网页控制台周期/reviews/acceptance-50-6-console-ui.md` | 66 | T10 的四列清单（含实测结果、复跑命令、已知缺口） |

**修改**（`git diff --stat`：见 Change Log）

| 路径 | 说明 |
|---|---|
| `src/heagent/web/index.html` | 两栏 + 设置面板 + 常驻安全声明 + 二次确认层；仍只引用两个同源资源 |
| `src/heagent/web/app.js` | 项目 / 会话 / 设置三层接线 + 状态反馈 + 错误码文案表 + 来源词表；49 的对话区行为原样保留 |
| `src/heagent/web/styles.css` | 三栏网格 / 窄屏单列 / 来源徽标 / 只读态 / 确认框 |
| `src/heagent/network/http_console_protocol.py` | +`ProjectConfigResponse.write_enabled`（入口层填写，无默认值） |
| `src/heagent/cli_http.py` | `_config_response(..., write_enabled=...)` 显式透传闸门状态 |
| `src/heagent/config_catalog.py` | `LABELS` +`write_channel_disabled`（闸门关闭的原因文案由后端给） |
| `tests/js/app_probe.js` | 重写：DOM 替身自 index.html 派生 id、按路由的 fetch 替身、用例 F–N（控制台各层） |
| `tests/test_http_web_ui.py` | +静态契约（布局/CSP/事件属性/第三方 URL 排除）+ 14 个行为用例；49 的两条端点断言随交互面更新 |
| `tests/network/test_http_console_config.py` | `_sample_response` 补 `write_enabled` + 新增闸门一致性用例 |
| `tests/network/test_http_server.py` | `<title>` 断言 → `HeAgent 控制台` |

**探测 / 验证脚本**（未跟踪，`.heagent/tmp/`）：`mutate_50_6.py`（10 个变异体）、
`src_probe.py` / `src_probe2.py` / `src_probe3.py`（面板来源分布与闸门字段的诊断探针）、
`patch_ledger_50_6.py`（台账 CRLF 字节级补丁）。

### Change Log

| 日期 | 变更 |
|---|---|
| 2026-09-24 | 实现 Story 50-6：两栏控制台 UI（项目 / 会话 / 设置三层）+ 真实浏览器验收驱动（17/17 PASS）+ 10 个变异体负向验证全红；协议加 1 个字段（`write_enabled`）；全量 3012 passed / 覆盖率 92%；缺口 2 条登记活动台账（浏览器验收不进 CI、高影响键确认缺后端标记）。 |
| 2026-09-24 | **收口后修复（用户实测发现）**：首页加载即弹出关不掉的确认遮罩 —— `[hidden]` 全局守卫 + `settleConfirm` 先隐藏再结算 + 2 条 CI 不变量断言 + 探针用例 O + 浏览器验收 A1b（清单 17 → 18 行，18/18 PASS）。台账 Z-D15。 |

### 收口后修复（2026-09-24）

**用户实测缺陷（非评审发现）**：打开控制台首页即弹出「请确认」对话框，且点「取消 / 确认」都关不掉、整页真实鼠标点击被吞。

**根因**：50-6 的 UI 改造给 `styles.css` 引入的 `.overlay { display: flex }` 是**作者级**声明，压过 UA 样式表的
`[hidden] { display: none }` ⇒ `#confirm-overlay` 带着 `hidden` 属性照常渲染（`position: fixed` + `inset: 0` +
`z-index: 20`）；而 `settleConfirm` 当时在隐藏遮罩**之前** `if (!pending) return;`，加载时又没有 pending ⇒ 关不掉。

**为什么本故事的 17/17 验收没抓住**（三条判据问题，逐条已补）：① 清单只断言 `element.hidden`（属性），不看
计算样式；② `click()` 用 `node.click()`（DOM API）**绕过命中测试**，全屏遮罩吞点击在它眼里不存在；③ node 探针
是 DOM 替身、**没有 CSS 级联**。（真浏览器实测修复前：属性 `hidden=true` 而计算样式 `display=flex`、有盒子，
`elementFromPoint`（发送按钮处 / 侧栏处）= `confirm-overlay`。）

**处置**（三件，均已实跑验证）：

1. `styles.css`：加全局守卫 `[hidden] { display: none !important; }`（作者级 `!important` 压过其余作者规则 ⇒
   新增遮罩/面板不必各自再配 `[hidden]` 分支）。
2. `app.js`：`settleConfirm` 改为**先隐藏遮罩、再处理 pending**（失败模式从「关不掉」降级为「点一下关掉」）。
3. 判据补强：CI 侧 `tests/test_http_web_ui.py::TestHiddenAttributeSemantics`（2 例：守卫存在且 `!important`；
   交叉扫描 `index.html` 的 10 个 `hidden` 元素 ↔ `styles.css` 的 display 规则）+ 探针用例 O（无 pending 时
   取消/确认必须关掉遮罩）+ 浏览器侧新增 **A1b**（计算样式 `display === "none"`、0 个盒子、`elementFromPoint`
   与 CDP `Input.dispatchMouseEvent` 真实点击都不落在遮罩上）。

**验证（实测）**：负向 —— `git checkout HEAD -- styles.css` → 恰好 2 条断言变红（报 `#confirm-overlay <- .overlay`）；
回退 `settleConfirm` 顺序 → 探针用例 O 变红；无守卫时真实浏览器验收**只有 A1b 变红**（其余 17 行照旧全绿 ——
正是这一行的价值）。正向 —— `ACCEPTANCE {"rows":18,"failed":0}`；`pytest tests/test_http_web_ui.py tests/network -q`
→ 421 passed；`ruff check` / `ruff format --check` 全绿。

**登记**：台账 `deferred-work-archive.md` Z-D15（含残余：真实命中测试目前只有 A1b 一行，`click()` 仍用 DOM API）。

