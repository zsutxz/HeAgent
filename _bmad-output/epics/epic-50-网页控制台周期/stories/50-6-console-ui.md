---
id: 50-6
title: 网页控制台 UI
status: ready-for-dev
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

- [ ] **T1** `index.html`：两栏骨架 + 设置面板入口 + 常驻安全声明条；`lang="zh-CN"`；不引入外部资源。
- [ ] **T2** `styles.css`：侧栏/对话/面板布局（含窄屏降级）、来源徽标样式、只读态与禁用态、二次确认对话框。
- [ ] **T3** `app.js` 项目层：`GET/POST/PATCH/DELETE /api/projects*` 接线；项目切换作用于本地状态（**不动进程状态**）；
      目录失效项显示 `available=false` 的可见标记。
- [ ] **T4** `app.js` 会话层：列表/新建/切换/重命名/删除；删除走确认；`session_conflict` / `session_busy` /
      `confirm_required` / **`session_unreadable`（D1 新增：会话文件损坏，文案须与「冲突」区分开，引导用户
      处理或删除该文件而不是当作空会话继续）** 映射为可理解文案（复用 49 的稳定错误文案映射函数）。
- [ ] **T5** `app.js` 设置面板：分组渲染（后端给的分组 + 来源 + `writable` + `read_only_reason`）；
      凭证只渲染 `configured` + 掩码；只读项显示原因；未知键单列且标明「不生效」。
- [ ] **T6** 保存流程：提交 `{changes, fingerprint}`；成功后展示结果 + 「下一次运行生效」并在**同一页**刷新该项来源徽标；
      失败（`invalid_value` / `config_conflict` / `field_not_writable` / `write_disabled` / `loopback_required`）逐类给文案。
- [ ] **T7** 状态反馈：项目切换中（禁用交互 + 可见进度）、会话冲突（提示重新加载）、写入结果、只读原因四类状态
      都有可见反馈（不允许只在 console 里打日志）。
- [ ] **T8** 无回归检查：流式/工具活动/停止/重连路径按 49 的行为逐条手工复核（作为验收清单的一部分）。
- [ ] **T9** 静态资源测试：`tests/test_http_web_ui.py` 扩展——资源白名单命中、CSP 生效、无第三方 URL
      （对 `index.html` / `app.js` / `styles.css` 做 `http://` / `https://` / `//cdn` 的**排除性断言**）、
      源码运行与 wheel 安装两条路径都能取到资源。
- [ ] **T10** 手工验收清单（写入本 story 产物或 `reviews/`）：页面 → 步骤 → 期望 → **实测结果**四列，
      至少覆盖 brief §9 的 9 条验收标准中与 UI 相关的部分。

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
