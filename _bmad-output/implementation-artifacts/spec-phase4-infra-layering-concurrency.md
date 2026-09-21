---
title: 'Phase 4 基础设施分层与并发边界'
type: 'refactor'
created: '2026-09-21'
status: 'done'
baseline_commit: '52a7cba'
review_loop_iteration: 0
context: ['{project-root}/docs/frame.md', '{project-root}/docs/test.md', '{project-root}/_bmad-output/implementation-artifacts/spec-phase3-workflow-decoupling.md']
---

<frozen-after-approval reason="待用户批准后冻结执行">

## Intent

问题：① `tools/sandbox.py` 797 行单文件混装契约（tier/Protocol/RuntimeSlot 绑定）、进程监督（supervise/kill/reap/截断）、两个平台后端与会话目录，变更回归半径大（test.md §2-P1）；② 子进程语义五种走法——超时（sandbox 返回字符串 / git 抛 RuntimeError / hooks 返回元组 / MCP `call_tool`/`list_tools` 无超时）、清理（asyncio 路径 5s bounded reap vs WinJob `proc.wait()` 无界 vs git `communicate()` 无界 vs hooks 超时路径不关管道）、截断（仅 sandbox 512KB）、env（asyncio 剥敏感项 vs WinJob 全量继承）；③ MCP 单 server 连接失败仅 logger.warning，发现错误无向上通道（cli/GUI 无感）；④ skill 文件读取三份实现——`SkillPackage._read_text`（O_NOFOLLOW 加固）、`SkillStore._read_text`（裸 read_text）、importer/mapping/path_safety 各自直读，「解析后安全打开」无单一入口。

方案：沿 test.md §3.3 目标拆分表，四个边界逐一收口——C1 sandbox 包化（行为零变化）→ C2 MCP 生命周期与发现错误通道 → C3 子进程监督内核统一（git/hooks/WinJob 接入 shared kernel，修纯 bug 级不一致）→ C4 skills 拆分 + safe-open 单点（含 os.open 单点 AST 契约）。每边界一次门禁 + 一次 commit。

## Boundaries & Constraints

始终：行为不变优先——用户可见文案、错误语义（sandbox 返回格式化字符串 / git 抛 RuntimeError / hooks 返回 `(rc, msg)` 元组 / config 抛 ToolError→SystemExit(1)）逐字冻结；monkeypatch 缝按 Code Map 缝清单处置，逐条留档；每次只动一个边界。

需要协商的预期内最小行为变化（均为 test.md 明示授权的语义统一，逐项列出）：
- **V1** WinJob `_winjob_spawn` 补 `scrub_sensitive_env`（现状继承全量环境含 API key，与 asyncio 路径方向相反，属凭证卫生缺口）；
- **V2** WinJob 超时/取消路径 `proc.wait()` 加 5s 上界（对齐 `_REAP_WAIT_TIMEOUT`，无界 wait 属 bug 级）；
- **V3** git/hooks reap 的 `communicate()` 加同款上界；hooks 超时路径补关管道（与取消路径对称）；
- **V4** MCP 单 server 发现失败经 `discovery_failures` 结构化暴露，CLI `_mcp_lifecycle` 渲染 stderr（现状仅 warning，「不隐藏发现错误」为 test.md 明文要求）。

禁止：不为 MCP stdio 接沙箱（台账冻结边界：不改连接/握手契约，该缺口独立挂账）；不给 `call_tool`/`list_tools` 加超时（LLM 长调用合法，超时只属 connect/ping lifecycle）；不引入第三方依赖（孤儿进程检查不用 psutil）；不删 `tools/sandbox.py`/`tools/mcp/manager.py`/`memory/skills.py` 路径本身（保 import 兼容）；不改 FORBIDDEN_RUNTIME_IMPORTS 既有断言（只增不改）；不动 `SkillPackage._read_text` 的 fallback 语义（不支持 O_NOFOLLOW 平台回退 + 特征测试原样保留）；中间目录 TOCTOU（descriptor-relative）仍挂台账不本阶段交付。

## I/O & Edge-Case Matrix

| 场景 | 输入 | 预期 | 错误处理 |
| --- | --- | --- | --- |
| 兼容导入 | `from heagent.tools.sandbox import WinJobBackend/PassthroughRunner/SandboxTier/configure/get_command_runner/SandboxSession/...` | 包 `__init__` re-export 全保持，`EngineContainer(command_runner=...)` 注入面零改动 | 禁止删旧符号 |
| sandbox 缝 | `patch("heagent.tools.sandbox.WinJobBackend.available")` ×2 | 类对象身份经 re-export 保持，缝自动存活，测试不改 | — |
| sandbox 平台 patch | `patch("heagent.tools.sandbox.sys.platform")` ×3、`signal.SIGKILL` ×1 | 改写为解析等价的全局路径（同一 sys/signal 单例对象），语义不变 | 改写逐条留档 Change Log |
| reap 缝 | `patch("heagent.tools.sandbox._REAP_WAIT_TIMEOUT")` ×1 | 常量随消费者迁 `sandbox/process.py`，patch 路径同步改写 | 同上 |
| WinJob 不可用 / CreateJobObject 失败 | 非 Windows / API 失败 | warning/error + 降级 Passthrough，文案逐字保留 | 行为冻结 |
| 取消传播 | asyncio 任务取消于 run 途中 | kill 后 re-raise CancelledError，三 backend + git + hooks 一致 | bounded reap |
| MCP 单 server 失败 | stdio/http server 连接超时或异常 | 其他 server 不受影响（现状保持）；失败进 `discovery_failures`；合法发现照常注入 | 不静默降级为「部分可用却无报告」 |
| MCP 配置错误 | 非法 JSON / 缺 command\|url / `${VAR}` 未设 | ToolError → CLI fail-fast 不变 | 现状冻结 |
| SkillStore 读符号链接 SKILL.md | 最终组件为 symlink（支持 O_NOFOLLOW 平台） | 拒绝读（ELOOP→显性错误）；回退平台行为不变（特征测试保留） | 显性失败 |
| 并发替换 | `record_usage` 原子替换 SKILL.md 期间 SkillPackage/SkillStore 读 | 读者见旧或新完整文件（os.replace 原子性 + fstat 尺寸），无半文 | 不加跨进程读锁（Windows 写者兼容现状，skills.py:85-92 设计不变） |
| 路径逃逸 | skill 名含 `..` / 资源路径越界 | `WorkspacePathError` 不变 | 现状冻结 |
| 契约钉死 | `os.open` 全仓出现位置 | 仅 `tools/path_safety.py`（AST 契约，沿 frontmatter 正则单点先例） | 契约测试显性失败 |

## Code Map

- **C1** `src/heagent/tools/sandbox.py`（797 行）→ 包 `src/heagent/tools/sandbox/`：
  - `contracts.py`：`SandboxTier`、`CommandRunner` Protocol、RuntimeSlot 绑定面（`configure/reset/bind_command_runner/get_command_runner` 及 profile/workspace/session slots）；
  - `process.py`：`_supervise_subprocess`、`_spawn_kwargs`、`scrub_sensitive_env`、`_kill_and_reap`、`_cap_channel`、`_validate_timeout`、`_format_result`、`_REAP_WAIT_TIMEOUT`、`PassthroughRunner`；
  - `firejail.py`：`FirejailBackend` + `_build_argv`；`winjob.py`：`WinJobBackend` + `_winjob_spawn` + ctypes 常量；`session.py`：`SandboxSession` + `_sandbox_sessions` 字典 + `get_or_create_session/pop_session`；
  - `__init__.py` re-export 公共面。`available` 形状统一为 property（WinJob staticmethod → property，消 `container.py:253` 的 `type: ignore[attr-defined]`）。
- **C2** `src/heagent/tools/mcp/`：`manager.py`（493 行）收缩为 MCPClientManager façade + lifecycle（`_connect_all/_server_loop/_watch/_await_shutdown`，Phase 2 façade 先例）；新 `client.py` 承载 `_transport_and_session` + **最小 `TransportFactory` Protocol**（stdio/http 分派收敛为注入点，默认实现 = 现 SDK 调用）；新 `registry_bridge.py` 承载注册/注销（`_discover_and_register/_register_bridge_tool/_unregister_server/_unregister_all` + 命名去重）；`discovery_failures: list[MCPServerFailure]`（Pydantic）在 `_server_loop` 异常分支填充，`cli.py:_mcp_lifecycle` 渲染 stderr。**不建 `resources.py`**（Resources 原语 V2 未做，不造空模块，test.md 表格该列留待原语交付）。
- **C3** 子进程内核统一：`git.py:_run_git` 与 `engine/hooks.py` 改用 `sandbox/process.py` 的 kill/reap（bounded）+ `_cap_channel` 输出截断内核；各自可观察语义（git 抛 RuntimeError、hooks 返回元组）冻结；hooks env 白名单、git env 全量继承均**文档化为有意差异**不改。
- **C4** `src/heagent/memory/skills.py`（687 行）→ `skill_models.py`（解析/名称校验）、`skill_catalog.py`（match/stale/list/all_skills_content 纯检索）、`skill_store.py`（SkillStore 持久化类）、`skill_rewrite.py`（record_usage/update frontmatter 改写）；`skills.py` 保留为 re-export shim；safe-open 内核 `open_text_under_root()`（os.open + O_NOFOLLOW 回退 + fstat 校验 + 尺寸读，参数化 root）落 `tools/path_safety.py`，`SkillPackage._read_text`/`SkillStore._read_text`/importer `_hash`/`_read_manifest`/`_read_lock`/mapping `_load_user_signatures` 全部收敛接入。
- 架构契约（`tests/test_architecture_contracts.py` 扩展，只增）：① `tools/sandbox/*` 禁止运行期导入 `click`/`heagent.cli*`/`heagent.gui*`/`agent*`；② `tools/mcp/*` 同；③ `os.open` 全仓单点 = `tools/path_safety.py`；④ `memory/skills*` 禁止裸 `Path.read_text` 于技能文件路径（经 safe-open 内核）。
- 缝清单（全量 grep 已核，MCP/skills 缝均为类属性/实例级——拆分免疫）：
  | 缝 | 处数 | 处置 |
  | --- | --- | --- |
  | `heagent.tools.sandbox.sys.platform` | 3 | 改写 `sys.platform`（同一单例） |
  | `heagent.tools.sandbox.signal.SIGKILL` | 1 | 改写 `signal.SIGKILL`（同上） |
  | `heagent.tools.sandbox.WinJobBackend.available` | 2 | 类身份经 re-export 存活，不改 |
  | `heagent.tools.sandbox._REAP_WAIT_TIMEOUT` | 1 | 改写 `heagent.tools.sandbox.process._REAP_WAIT_TIMEOUT` |
  | `MCPClientManager._transport_and_session` | 类属性 patch（test_mcp_manager 全部用例） | 方法随类走，缝存活，不改 |

## Tasks & Acceptance

- [x] C1 sandbox 包化：上述五文件拆分 + `__init__` re-export + `available` property 统一；行为零变化，sandbox/winjob/housekeeping/credential 系测试原样通过；7 处缝按清单处置。（`15c8f61`）
- [x] C2 MCP 分层：client.py（TransportFactory Protocol）+ registry_bridge.py + manager façade 化；`discovery_failures` 结构化 + CLI stderr 渲染；单 server 失败隔离测试扩展（失败 server 出现在 discovery_failures 且其余 server 工具可用）。（`5adde12`）
- [x] C3 子进程内核统一：git/hooks 接 process.py 内核（bounded reap + 截断）；WinJob bounded wait（V2）+ env scrub（V1）；hooks 超时路径关管道（V3）；可观察语义冻结断言补齐。（`1380f0d`）
- [x] C4 skills 拆分 + safe-open 单点：四文件拆分 + `open_text_under_root` 内核 + 全读取点接入 + os.open 单点 AST 契约；`test_skill_packages_toctou.py` 特征测试原样通过。
- [x] `docs/frame.md` 4.4/4.11/memory 模块地图与调用链同步；`docs/test.md` §12 记录执行结果；本 spec 状态 done。（执行记录实落 test.md §13，沿编号顺延）

验收：Given 既有 sandbox/winjob/MCP/skill package/path safety/housekeeping 测试，When 拆分后运行，Then 原样通过且无跳过（V1–V4 涉及断言按新语义更新并留档）；Given `os.open` 全仓扫描，Then 单点命中 path_safety；Given cli_goal 之前例，When 统计三源文件行数，Then sandbox.py/manager.py/skills.py 显著收缩且公共 import 面不变；quality_gate 全量通过（覆盖率 ≥87%）。

## Spec Change Log

- 2026-09-21：C1–C4 全部完成（`15c8f61` / `5adde12` / `1380f0d` / C4 收尾提交），quality_gate 全量绿（2045 passed，相对基线 +7 全为新契约/新语义用例，无删减无跳过）。实施偏差与决策留档：
  ① **C1**：`CommandRunner.available` 在 Protocol 中必须以 **property 形式**声明——可写属性声明（`available: bool`）与实现的只读 property 不兼容（mypy 实测三处 assignment/return-value 错），基线无此成员故未暴露。
  ② **C3**：`reap_subprocess` 的 timeout 不得写成默认参数（def 时绑定 `_REAP_WAIT_TIMEOUT` 常量会使模块属性 patch 缝失效，`test_reap_wait_is_bounded` 实测红）——改为 `None` 缺省 + 调用时读模块属性。
  ③ **C4**：`os.open` 白名单 = `tools/path_safety.py` + `persist.py`——spec 原文「全仓单点」未计入 persist 锁文件创建（`O_CREAT|O_RDWR`，非读取路径），强行并入读取内核属扭曲，契约按白名单落地。
  ④ **C4**：importer 例外面扩大：`_read_manifest`（csv.DictReader 需 raw newline 语义，内核的 universal newlines 会破坏 csv）与 `_hash`（字节流哈希，文本内核抽象错误）保留直读；`_read_lock` 已接内核。spec Code Map「全部收敛接入」据此修正。
  ⑤ **C4**：`SkillStore._render_skill_md`/`_body_survives_rerender` 以 staticmethod 别名留类上、call 点走 `self.`——测试既有**类名访问**与**实例级 patch 拦截 update 事务**两种缝共存所需（Phase 3「grep 属性访问面」教训的实例级变体）。
  ⑥ **C2**：`TransportOpener` Protocol 落为构造期注入端口 + 新增注入端口测试；manager 保留 `_transport_and_session` 方法作 class-patch 缝宿主（test_mcp_manager 全部用例依赖），连接成功日志随 wrapper 保留（`type(cfg).__name__` 与原文案逐字一致）。
  ⑦ **C4**：`SkillStore.load` 的 `FileNotFoundError→None` 语义不变；其余 OSError（如最终组件符号链接 ELOOP）由内核显性上抛——此前 read_text 会**跟随**符号链接读任意内容，属 V4 之外的加固方向变化（与 SkillPackage 既有行为对齐），留档。
- 2026-09-21：用户批准冻结并执行（「按你推荐的来」，V1–V4 与四边界方案全盘通过；入口全量门禁已在 52a7cba 验证：2038 passed / 90.78%）。
- 2026-09-21：spec 创建（draft）。勘察结论：① 三域缝面仅 sandbox 7 处字符串缝（MCP 类属性缝、skills 实例缝拆分免疫）；② `CommandRunner` Protocol 已存在，C1 只补形状统一（`available` property 化），不新增 Protocol 层级；③ MCP `resources.py` 不建（原语未交付，不造空模块）；④ skill 双体系（SkillStore 记忆型 / SkillPackage 声明式）共存且共用 `.heagent/skills` 根——`record_usage` 会改写声明式包 SKILL.md（skills.py:390-421），读写锁现状（实例 RLock + os.replace 原子性）冻结不改，理由：Windows 读者持句柄会使写者 `os.replace` 失败（skills.py:85-92 已留档）；⑤ WinJob env 全量继承判为凭证卫生缺口，纳入 V1 最小行为变化。

## Design Notes

拆分顺序 = 依赖方向：C1 先立 process.py 内核（C3 的消费者），C2/C3/C4 相互独立可独立回滚。façade 沿 Phase 2 先例——类留原模块（`MCPClientManager` 在 manager.py、`SkillStore` 在 skill_store.py），跨文件只搬纯函数与内聚方法组，避免 mixin 式拆类。safe-open 单点选 `tools/path_safety.py` 而非新模块：memory→tools.path_safety 导入已存在（skill_packages.py:208），不新造层；os.open 单点契约沿 frontmatter 正则单点先例，把「分散即漏洞」钉成可执行断言。MCP 发现阶段无事件通道可用（tools 不可依赖 engine/events），结构化返回值 + 入口渲染是分层内最小解。

## Verification

- `python -m pytest tests/test_sandbox.py tests/test_sandbox_mode.py tests/test_winjob_backend.py tests/test_coverage_sandbox.py tests/test_credential_guard.py tests/test_mcp_manager.py tests/test_mcp_cli.py tests/test_mcp_config.py tests/test_mcp_mapping.py tests/test_memory.py tests/test_skill_tools.py tests/test_skill_packages_toctou.py tests/test_housekeeping.py tests/test_engine_p0.py tests/test_architecture_contracts.py -q`
- `python scripts/quality_gate.py` 全量（每 C 边界收口 + 最终各一次）。
- `ruff check src tests scripts`、`ruff format --check src tests`、`mypy src`。
- 平台说明：本地 Windows 验证 WinJob 路径；Firejail/Linux 后端由 CI（Python 3.11 Linux）覆盖，本地仅静态可验证部分。

</frozen-after-approval>
