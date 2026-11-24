# AGENTS.md

本文件为 Claude Code / Codex 等编码代理提供统一仓库指引：只放**去哪读**与**不可外包的纪律**；
项目事实（架构、命令、代码规范、发版、台账布局）一律外链，不在此复述。

## ⚠️ 安全声明

> **派生副本，真源 = [`docs/framework.md`](docs/framework.md) 的「安全口径（canonical）」（§4.18）。** 要素条目与真源
> 一一对应、不增不删；两者不一致时以真源为准。本段不承载独立论证，不得在此扩写要素正文。

HeAgent 执行 `shell` / 读写文件 / 调外部 API，并可连接**外部 MCP server**；工具返回内容直接进入模型上下文。

1. **三层非边界**：`SafetyGuard` / `PolicyEngine` / sandbox 后端均非真正安全边界。
2. **OS 级沙箱兜底**：容器档 Docker 后端默认未启用、启用也非绝对边界；MCP stdio 子进程在 `SANDBOX_BACKEND=docker` 且 daemon 可用时经同一镜像容器拉起（Epic 53 期二 53-5，D53-1 闭合），后端不可用时显性降级为宿主执行并每次 WARNING。
3. **本地模式**（listener 绑回环，默认）：HTTP 与 WS 均无认证、无 TLS；回环绑定不等于可信；`Origin` / `Host` 校验只是入口层 defense-in-depth；WS listener 可经 `WS_LOCAL_AUTH_ENABLED=true` 也强制 Bearer token（2026-11-04 D5 修订，默认关；开启时含旁路 `/api/cli/ws`、本机消费者都要带 token）；内网免认证档（`lan`）同样无认证、无 TLS，私有地址不等于同网段可信。
4. **非回环绑定两档，生产形态是 `wss` + token**（WS listener 绑非回环）：`external`（默认，Epic 56 D5）强制 `Authorization: Bearer <token>`（token 只读用户级 `~/.heagent/setting.md`，项目 `.env` 无效），缺 token 拒绝启动（fail-closed），认证不是绝对边界，浏览器 WebSocket API 无法自定义请求头；`WS_TLS_CERT_FILE` + `WS_TLS_KEY_FILE` 配齐即 `wss`（Epic 73），「加密 + token」才是完整生产形态，客户端信任锚是服务端身份公钥的 SPKI-SHA256 pin（`heagent tls fingerprint`；重签叶证书不改 pin，`heagent tls rotate-key` 是唯一改 pin 的动作）；`lan`（须显式 `WS_LAN_NO_AUTH=true`，Epic 72）无认证、无 TLS、只接受私有地址字面量，同网段任何设备都能驱使代理，每次启动 WARNING，只能靠网络侧兜底，且与 TLS **互斥**（`wss` + `WS_LAN_NO_AUTH=true` 拒绝启动）。
5. **端点可见性**：HTTP listener 没有对外模式；终端旁路 `/api/cli/ws` 只挂回环（`local`）listener，`lan` / `external` 恒不注册；只读通知流 `/api/notifications/ws` 随 listener 注册，`lan` / `external` 上同样可见（`external` 在 token 之后、`lan` 上无认证）——但仅在 `CRON_PUSH_ENABLED=true` 建起中枢时注册，默认关 ⇒ 路由不存在（客户端拿裸 403）。
6. **已知缺口与台账**：清单落 `_bmad-output/open-items.md`（「活动（未闭合）条目」节；闭合历史见 `_bmad-output/retrospective-all-cycles.md` §三），本节不复述。

落点提示：端口 / provider / 认证 / TLS 键等机制细节见 `docs/framework.md` 4.16 与 4.16.1；非回环入口（`lan` / `external`）能提交 run 时**强烈建议**启用容器沙箱档（`--sandbox docker`）。

<!-- bmad:context -->
<!-- Verified 2026-11-03 against 31cf7cb. Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## 文档指向

**架构权威 = `docs/framework.md`**（数据流 §二 / 模块 DAG 与依赖规则 §三 / 模块详解 §四 / 调用链 §七 /
技术规范 §八 / 安全口径 §4.18 / 台账与规划产物布局 §8.5）；全目录索引见 `docs/README.md`。

| 想知道什么 | 权威落点 |
| --- | --- |
| 安装、Provider 配置、CLI / HTTP / WS 用法、配置开关 | `README.md` |
| 开发与门禁命令（pytest / ruff / mypy / bandit / `quality_gate.py` / `verify_baseline.py` / mkdocs） | `README.md`「开发」节 |
| 门禁红了怎么分诊、耗时基线、marker 口径 | `docs/testing.md` |
| 沙箱后端、四档分级与会话目录 | `docs/sandbox.md` |
| 设计理念与非目标 | `docs/design.md` |
| 迭代历程与迭代方法 | `docs/iteration.md` |
| 缺口台账 | `_bmad-output/open-items.md`「活动（未闭合）条目」节 ＋ framework §五 |

## 硬约束（违反即架构错误；判据 = `tests/test_architecture_contracts.py`）

- 依赖方向固定 `pub → config → providers/tools/context → engine → agent → cli/gui/goal`，下层不得反向导入入口层；旁支档位（memory/skills 对 engine 仅 TYPE_CHECKING、events、cron、network/、web/）见 framework §三
- 新增 provider / tool **禁止**从 `agent/` 导入
- `network/` 不得导入运行栈（agent/engine/providers/tools/memory/skills/context/cron/events）与配置（config/pub.projects/pub.workspace）；`network/ws_server.py` 不得导入 `network/http_server.py`（同层传输模块互不依赖，共享契约住 `http_protocol.py`）
- 跨模块数据用 Pydantic 模型（`pub/types.py`），**禁止**原始 dict
- 工具执行链固定为 **`PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler**
- 改包间依赖必须同步 `FORBIDDEN_RUNTIME_IMPORTS` 并跑 `pytest tests/test_architecture_contracts.py -q`；新增/删除 `cli/*.py` 要同步 `test_cli_package_layout_is_pinned` 白名单
- `heagent/cli/__init__.py` 永不放 import（`test_cli_package_shell_stays_thin`）；子模块延迟导入必须指向实模块
- 单文件 ≤ 1000 行（framework §八「文件规模」行）

## 代理必须记住的三条操作口径

- **在仓库根启动**：`workspace_root` = 进程 cwd（从盘根启动会把整盘挂进容器沙箱）；Windows 用 `powershell scripts/start_heagent.ps1`
- **门禁红了第一步**：`python scripts/verify_baseline.py <用例> -q` 判「环境产物 vs 回归」，判读见 `docs/testing.md`
- **测试约定**：`StubProvider` 模拟、不调真实 API；provider 测试放 `tests/providers/`；异步由 `pytest-asyncio` 自动驱动

## 扩展点（详解见 framework §4.3 / §4.4）

- Provider 实现 `send` / `stream` / `get_metadata`
- Tool 放 `tools/builtins/`：`@tool(read_only=...)`、路径经 `tools/path_safety` 校验、在 `builtins/__init__.py` 注册
- Skill 包必须包含带 frontmatter 的 `SKILL.md`；工作流资源用 `SkillPackage` 类型化读取
- **monkeypatch 缝是搬移红线**——搬代码前先 `grep` patch 字符串路径（如 `heagent.cli.console._run_prompt`）

## Git 提交与 Pull Request

- 提交信息用**中文** Conventional Commit，如 `feat(provider): 增加模型回退`
- **每次 `git commit` 前必须呈报提交信息与文件清单，获得明确同意后才执行**
- 提交前跑相关测试 + `ruff check` + `mypy`；PR 说明问题、方案、测试命令与兼容性影响

## 仓库卫生

- `.heagent/`、`_bmad-output/`、日志与本地状态是运行/规划产物；不提交密钥、`.env` 或生成文件

<!-- /bmad:context -->

## 块外手工区（refresh 不覆盖；纪律与运维指针放这里才能存活）

- **工程纪律四条款**（fails loud at load / 常量≠配置 / 空 catch 具名 / 不解释的对称破缺暗示漏提取）：canonical 在 [`docs/framework.md`](docs/framework.md) §8.4，本文件只留指针。
- **文档站**：`mkdocs build --strict` 是 CI 文档门（构建期工具，按需 `pip install mkdocs "mkdocstrings[python]"`）；动 `docs/` 后本地先跑。
- **发版契约**：`src/heagent/__init__.py::__version__` 与 `pyproject.toml` 一致且纯 semver，`CHANGELOG.md` 保有 `## [Unreleased]`，判据 `tests/test_release_workflow_contract.py`；发版 = 两处同步 bump + 归节。
- **Active ticket store** = 当前 goal 树自带的 `docs/<goal-id>/tickets/`（指针 `docs/current`；`tickets.py --project-root docs/<goal-id>/tickets …`，`mark` 是唯一写路径）。历史票树 `_bmad-output/Goal-3/tickets/`（Epic 70–73）与 `Goal-2-v6/tickets/`（Epic 61–69）是只读归档；`_bmad/custom/config.user.toml` 的 `active_initiative` 是 gitignored 用户配置 ⇒ 换机器 / 新 clone 需重写。布局、读取范围与守卫测试见 framework §8.5。
- **新工作唯一入口 = 票树**：对 bmad 说 build entry（如 62.1）；独立 intent 走 bmad 立项流程进票树；v6 追踪源（`epics.md` + `sprint-status.yaml`）已上移 `Goal-2-v6/` 根（只读）。
- **WS/TLS 排障工具链**：`heagent tls {init,issue,rotate-key,fingerprint,verify}`（唯一签发入口）→ `scripts/ws_manual_probe.py`（配 `tls_ws_stub.py` 自证握手）→ `scripts/cleanup_orphan_containers.ps1`；细节见各脚本头注释。

## 已知缺口

完整清单见 framework §五 与 `_bmad-output/open-items.md`「活动（未闭合）条目」节（闭合历史见
`_bmad-output/retrospective-all-cycles.md` §三）；边界立场见 framework §4.18。本段不复述条目正文。
