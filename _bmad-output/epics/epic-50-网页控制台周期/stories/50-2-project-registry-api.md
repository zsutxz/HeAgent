---
id: 50-2
title: 项目注册表与项目 API
status: ready-for-dev
parent_epic: E50
priority: P0
phase: B（项目与会话闭环）
depends_on: [50-1]
blocks: [50-3, 50-4, 50-5, 50-6, 50-7]
created: '2026-09-23'
---

# Story 50-2：项目注册表与项目 API

## 用户故事

作为控制台用户，我希望在网页里登记并切换本机的已有目录（项目），以便一个服务进程服务我的多个项目，
且移除登记时磁盘数据分毫不动。

## 侦察实证与规格冲突（2026-09-23）

| 项 | 事实 / 处置 |
|---|---|
| 原子写 + 跨进程锁原语已具备 | `persist.atomic_update_text(path, update, *, lock_timeout=5.0)`（`persist.py:368`）、`atomic_write_text`（`:313`）⇒ 注册表读改写不需新机制 |
| 网络层不得不认识项目 | 脊柱 I1：注册表能力经 `network/http_console_protocol.py` 的 **Protocol + Pydantic 模型**注入；`network/` 不 import `projects` |
| 新增路由的注册门 | 脊柱 §2：`build_http_app(..., console=None)`；`console is None` 时**不注册**任何控制台路由（I13 向后兼容） |
| 注册表写入位置**规格冲突（本次校正）** | `epics.md` 的 Additional Requirements 写「`HTTP_CONSOLE_PROJECTS_FILE` 默认 `~/.heagent/projects.json`」；脊柱 §4 写「落点 = `<服务启动工作区>/.heagent/console/projects.json`，默认**不写**用户 home」。**取脊柱**（默认项目本地；需要机器级共享时由用户显式配成 `~/.heagent/projects.json`），并把 epics.md 的措辞修正 |
| 审计目录与注册表同域 | `.heagent/console/` 已在 50-1 的 deny 集合内（I14）⇒ 注册表与审计不可被工具读入上下文 |
| 路径身份比较的平台差异 | 测试必须覆盖大小写 / 尾分隔符 / 相对路径 / 符号链接四种写法归一到同一条目；比较用 `os.path.normcase`，**不要**只依赖 `Path.resolve()` 的字面量 |

## 范围

- 新增顶层模块 `src/heagent/projects.py`：`ProjectEntry` / `ProjectRegistry`（Pydantic + 原子持久化 + 上限 + fail-soft）。
- 新增网络层协议模块 `src/heagent/network/http_console_protocol.py`：请求/响应模型 + `ConsoleHandler` Protocol。
- `network/http_server.py` 新增 4 条项目路由（列表 / 登记 / 重命名 / 移除）与 `console=` 注入点。
- `HttpErrorCode` 新增本项目相关的稳定码（闭集扩展）。
- 默认项目：服务启动工作区，**隐式存在、不持久化、不可移除**（既有端点 `POST /api/runs` 等的兼容锚点）。

## 边界与约束

**Always**

- 只登记**已存在**的目录；不存在 / 非目录 → `invalid_project_path`，**不创建**任何目录（brief §7 D3）。
- 路径规范化链路固定：`expanduser()` → `resolve()` → 去尾分隔符；身份比较 `os.path.normcase`。
- 移除登记 = 只删注册表条目；项目目录与其 `.heagent/` 数据**逐字节保留**。
- 注册表损坏（非法 JSON / 结构不符）→ 一条 WARNING + 空注册表继续服务（fail-soft，与 Z-D12 同立场）。
- 条目数有上限；超限拒绝并给稳定错误。
- 响应体有界：不返回目录内容、不返回绝对路径以外的宿主信息、不返回凭证。

**Never**

- 不创建、不删除、不移动任何项目目录。
- 不把注册表路径交给请求参数指定（只认 `HTTP_CONSOLE_PROJECTS_FILE` 或默认落点）。
- 不在 `network/` 里 import `projects` / `config` / `engine` / `agent` / `tools`（I1）。
- 不自动移除「目录失效」的条目（列表标 `available=false`，不静默消失）。
- 不让 `DELETE` 在项目有在途运行时生效（`project_busy`）。
- 不从网页开启任何全局开关；项目登记本身不读取 `.env` 内容。

## 任务（细分）

- [ ] **T1** `projects.py`：`ProjectEntry`（`id` / `name` / `path` / `available` / `last_opened_at` / `is_default`）
      与 `ProjectRegistry`（`load` / `list` / `register` / `rename` / `remove` / `touch`），全部经
      `persist.atomic_update_text` 落盘（跨进程锁贯穿读改写）。
- [ ] **T2** 路径身份：`normalize_project_path()`（`expanduser` → `resolve` → 去尾分隔符）+
      `project_id_for(path)`（`"p" + sha256(normcase(path))[:8]`）；**重复登记必须返回既有条目**（不是新建）。
- [ ] **T3** 默认项目：`id="default"`、不落盘、`remove` 抛 `project_not_removable`；作为既有端点的语义锚点。
- [ ] **T4** 上限与失效：条目上限常数（**D5：32**，写进常量与测试）；`available` 在**列表时**由
      `is_dir()` 实时判定（不在落盘数据里缓存，避免陈旧）；`available=false` 的条目在列表里保留。
      **另有界（评审 F10，NFR-11）**：显示名长度上限（如 64 字符）与路径长度上限（如 4096 字符）须显式校验并
      给出稳定错误——否则注册表可被超长输入撑大，且超长名称会原样进 UI。
      **与并发的关系（D9）**：项目数上限 **32** 同时是在途运行上限的乘数（32 × `HTTP_MAX_INFLIGHT_RUNS`）
      ⇒ 该常数不是纯 UI 限制，改动它等于改整体资源上限，必须同时更新脊柱 §6 与文档。
- [ ] **T5** `network/http_console_protocol.py`：`ConsoleHandler` Protocol（`list_projects` / `register_project` /
      `rename_project` / `remove_project`）+ 请求/响应 Pydantic 模型（`extra="forbid"`）+ 有界字段长度。
- [ ] **T6** `http_server.py`：`build_http_app(..., console=None)` 与 4 条路由；错误信封与安全头复用 49-5 的中间件；
      非回环来源的项目**登记/移除**按脊柱 §9 要求回环（与 50-5 共用同一个来源判定）。
- [ ] **T7** `HttpErrorCode` 新增：`unknown_project` / `invalid_project_path` / `project_unavailable` /
      `project_not_removable` / `project_busy` / `project_limit_reached`（闭集扩展；同步 `__all__` 与文档）。
- [ ] **T8** 在途运行保护：`DELETE /api/projects/{id}` 在项目有在途 run 时 → `project_busy`
      （依赖 50-3 的全局 run 索引；本 story 先接**注入的**查询协议，索引由 50-3 提供）。
- [ ] **T9** 测试：登记 / 重复登记（四种写法归一）/ 非目录 / 不存在 / 失效目录 / 重命名 / 移除保留数据 /
      损坏注册表 fail-soft / 上限 / 默认项目不可移除 / `console=None` 时不注册路由 / network 层依赖面。
- [ ] **T10** 负向验证：去掉 `normcase` 比较、去掉「只登记已存在目录」校验、把「移除」实现成删目录、
      去掉上限——对应测试逐条变红后复原。

## 验收标准

- **AC1** Given 控制台已启动，When 客户端 `GET /api/projects`，Then 返回项目列表
  （`id`/`name`/`path`/`available`/`last_opened_at`/`is_default`），按最近打开降序，且不含任何凭证或非项目目录内容。
- **AC2** Given 一个存在的目录路径，When 客户端 `POST /api/projects`，Then 登记成功并返回项目 id；
  路径经规范化（`resolve`、去尾分隔符、`expanduser`）。
- **AC3** Given 同一路径以不同写法（大小写 / 尾分隔符 / 相对路径 / 符号链接）再次登记，When 执行登记，
  Then 服务识别为**已存在**并返回既有项目而非新建。
- **AC4** Given 一个不存在或不是目录的路径，When 执行登记，Then 返回稳定的 `invalid_project_path`，
  **不创建目录**、不写任何文件。
- **AC5** Given 已登记项目，When 客户端 `PATCH` 重命名显示名，Then 只改注册表里的名称，磁盘目录不变。
- **AC6** Given 已登记项目，When 客户端 `DELETE /api/projects/{id}?confirm=true`，Then 仅移除登记；项目目录与其
  `.heagent/` 数据**逐字节保留**；缺 `confirm=true` → `confirm_required`；有运行在途时返回 `project_busy`；
  `default` 返回 `project_not_removable`（评审 F11：与会话删除对齐，危险操作的确认放**服务端**而非只靠 UI）。
- **AC7** Given 已登记项目的目录被外部删除，When 客户端列出项目，Then 该项标记 `available=false`
  而不是从列表消失，对其发起运行得到 `project_unavailable`。
- **AC8** Given 注册表文件损坏（非法 JSON），When 服务启动，Then 记录 WARNING 并以空注册表继续（fail-soft），
  不阻断 HTTP 服务。
- **AC9** Given 条目数已达上限，When 再登记一个新目录，Then 返回 `project_limit_reached`，注册表不变。
- **AC10** Given 未注入控制台（`console=None`），When 请求任一 `/api/projects*`，Then 404 `not_found`，
  且既有端点行为不变（I13）。

## Definition of Done

**交付物**：`src/heagent/projects.py`、`src/heagent/network/http_console_protocol.py`（均新增）、
`src/heagent/network/http_protocol.py`、`src/heagent/network/http_server.py`、
`tests/network/test_http_console_projects.py`（新增）、`tests/test_projects.py`（新增）。

**验证命令**（实测存在性已核对）：

```bash
pytest tests/test_projects.py tests/network -q
pytest tests/test_architecture_contracts.py tests/test_http_security.py -q
pytest -q
ruff check src tests && mypy src && mypy src --platform linux
```

**负向验证**：T10 的 4 项回退各自精确变红。

**质量门**：`pytest`、`ruff check`、`ruff format --check src tests`、`mypy src`、`mypy src --platform linux` 全绿；
覆盖率门槛 87%。

## 代码地图

| 路径 | 角色 | 改动 |
|---|---|---|
| `src/heagent/projects.py` | **新增** 注册表模型 + CRUD + 落盘 | 依赖 `persist`（+ `workspace` 仅取默认落点） |
| `src/heagent/network/http_console_protocol.py` | **新增** 网络层协议（模型 + Protocol） | 只依赖 stdlib + pydantic |
| `src/heagent/network/http_protocol.py` | 稳定错误码闭集 | 新增 6 个成员 |
| `src/heagent/network/http_server.py` | 路由骨架 + 注入点 | 4 条项目路由；`console=None` 不注册 |
| `tests/test_projects.py` | **新增** 注册表单元测试 | 规范化矩阵 / 上限 / fail-soft |
| `tests/network/test_http_console_projects.py` | **新增** API 测试 | 注入假控制台 |

## 风险与未决

- **R1**：`last_opened_at` 的写频率——每次「读取项目」都 `touch` 会让注册表在高频轮询下频繁落盘；
  实现取「切换/发起运行时更新」而非「列表时更新」，并把该口径写进 docstring 与测试。
- **R2**：`project_busy` 依赖 50-3 的全局 run 索引；本 story 只接注入协议，**50-3 未完成前该分支不可测**，
  测试用假索引先行覆盖，端到端断言归 50-3/50-7。
- **R3**：上限值（32）为建议值，实现时定一个常数并同时在文档与测试中固定；若后续要可配，需另开 story
  （本周期不加配置键，避免扩大 `Settings` 面）。

## Requirement Traceability

FR-2；NFR-1, NFR-5, NFR-8, NFR-11；UX-DR3, UX-DR5；脊柱 I1, I2, I13, I14；brief §4 FR-2、§6.4、§7 D3。
