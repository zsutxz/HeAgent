# HeAgent Epic 总览

> **生成与维护**：2026-08-18 建立（原 `consolidated-overview.md`），按代码与 `initiative-heagent/archive-v6/sprint-status.yaml`（已归档）持续校正；**2026-11-15 重组拆分**——周期详解与台账归档迁 [`retrospective-all-cycles.md`](retrospective-all-cycles.md)（§二–§五），活动台账独立为 [`open-items.md`](open-items.md)。本文保留当前口径：状态、缺口、路线图、待完成索引与文档地图（epic 总目录）；未闭合问题清单见 [`open-items.md`](open-items.md)。

---

## 一、当前状态与下一步

### 1.1 当前状态（截至 2026-11-15）

- **规划产物**：`sprint-status.yaml` 实测 **64 个 epic 键（Epic 1-59、61 + S1-S4）：63 `done` + 1 `backlog`**（2026-11-15 实测；唯一 backlog = Epic 61 Web 检索，2026-11-13 立项未开工；**Epic 60 结构精简 5 spec 已交付但 yaml 无键**，登记缺口见 §1.4-C）；retrospective 仍 `optional` 的 epic 共 **16 个**（均未补做，清单见 §1.4-C）。产物整理：`patches/` 按归属 epic 归档（2026-09-15）、deferred 台账重组（2026-09-17）、story 产物按 Epic 分组、改进计划四件套入 `planning-artifacts/`（2026-11-11）。
- **架构优化周期（2026-09-21~22 交付）**：6 阶段全部 done——组合根收敛（`ResolvedRuntimeConfig`）/ loop façade（策略五模块 + `mark_terminal`）/ workflow 解耦（`goal/application.py`，cli_goal 991→680）/ 三域拆分（`tools/sandbox/` 包、MCP `client`+`registry_bridge`+`discovery_failures`、skills 四文件）+ 子进程监督内核统一（`cap_channel`/`reap_subprocess`）+ safe-open 单点（`open_text_under_root`）/ **事件契约 v2**（`RunEvent.duration_ms`/`error_kind`，SCHEMA_VERSION=2 黄金测试锚定 + workflow_step_* 事件）+ benchmark 基建 + 文档收口（`docs/extending.md` / `docs/troubleshooting.md` / `docs/goal-workflow.md` / frame 4.15）。档案：`implementation-artifacts/arch-optimization-cycle/`。
- **2026-10-27~11-15 交付批（125 提交）**：Epic 58 cron 结果推送（`EventStreamHub` 通用核）、Epic 59 MEMORY 语义压缩（`fact_compact`）、Epic 60 结构精简批次 9 五卡（housekeeping 迁顶层 / providers 装配 / goal 持久化 / 写审计迁 goal 包 / 执行世界 runner 构造期参数化）、**A51 发布缺口部分闭合**（`CHANGELOG.md` 载体 + 版本真源守卫 `0.8.4→0.9.0` + mkdocs `--strict` CI 门，2026-11-11）、契约快照基线两批、改进计划 PRD/分解/估算（`planning-artifacts/`，2026-11-11）、斜杠命令 `/provider`、`/model` 硬改名、`config/catalog.py` 拆 9 子模块、全库审查 P2-P4 修复、A54 网络族单源化（重放单源 + `WsRegistry` 收编，2026-11-15）、台账重组收口（本文件拆分定名）；条目改名 gpt→openai、anthropic→claude 与 `HTTP_ENABLED`/`WS_ENABLED` 独立开关为 2026-10-26 交付（`24b0bd1`/`de8311b`）。
- **测试基线**：**4214 passed / 覆盖率 93%**（六门全过，2026-11-02 实测，Epic 58/59 交付记录；gate 87）；deselect = integration + benchmark + 本机 WSL2 恒红的 3 条 `test_cli_http_lifecycle` 端口断言；`scripts/quality_gate.py` **六门**（goal smoke / 回归+覆盖率 / ruff check / ruff format / mypy / **bandit `-ll`**，与 CI lint job 同参数）；代码量 `src/` 47,525 行（190 个 `.py`）+ `tests/` 65,014 行（192 个 `.py`）（2026-11-15 实测）。

### 1.2 已知缺口（详见 frame.md 第五章）

- `SafetyGuard` / `path_safety` / engine sandbox 均非真正安全边界——须 OS 级沙箱兜底。
- `ToolExecutor.execute_in_sandbox()` 默认 Passthrough 透传；`FirejailBackend`（Linux，仅 shell 子进程）/ `WinJobBackend`（Windows，Job Objects）可注入但均非完美边界；file/memory 等宿主进程内 I/O 工具不受覆盖。
- MCP annotations 不可信（server 自声明）——`PolicyEngine` 注解闸门仅 defense-in-depth。
- 用户可配置 MCP 注入签名入口（`spec-mcp-user-injection-signatures.md`）**项目级已交付**：`.heagent/injection_signatures.json` 受 workspace 围栏并进程内懒加载；全局/home 级 2026-09-15 **决策关闭（won't do）**。
- Dreaming 的 web_fetch 注入围栏端到端接入**已交付**（2026-08-19，Epic 35；标记透传，非真正边界）。
- 凭证 deny 的**项目级配置入口已交付**（`.heagent/path_deny.json`，2026-09-17）：仅支持收紧或精确豁免、无整体关闭入口、fail-safe 默认仍拒；`shell` 仍可 `cat .env`——非真正边界。
- **MCP stdio server 子进程未接入沙箱**（**2026-09-27 裁定 (c) 不实施**，登记为已知暴露面）：SDK 自行 `anyio.open_process` spawn，不经 `ToolExecutor.execute_in_sandbox`，Firejail / WinJob 对它零覆盖（见 §1.4-A2 → 归档 **Z-D24**）；**env 面已排除**（SDK 只继承 `DEFAULT_INHERITED_ENV_VARS`：win32 12 项 / POSIX 6 项，不继承 `*_API_KEY`）。
- sandbox 无开箱即用安全 profile 库、无人验证 profile 参数合法性、`S4-1` emit 事件仍 `skipped`（沙箱执行轨迹不可追溯）——逐条见 §1.4-C / §1.4-D。
- ~~沙箱**无进程数限额**~~ → **2026-09-18 已闭合**：新增 `SANDBOX_NPROC_LIMIT`（0=关闭），firejail 映射 `--rlimit-nproc`、WinJob 映射 `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` + `ActiveProcessLimit`；同时修正 WinJob 常量表（`JOB_OBJECT_LIMIT_PROCESS_TIME` 原误写 `0x8`=ACTIVE_PROCESS 位，正确 `0x2`）。⚠ 两后端语义不对称（firejail 按真实 UID 计数，非 per-sandbox）。

### 1.3 下一步（路线图）

> 完整清单（活动台账项——当前 16 条）见 [`open-items.md`](open-items.md)；需要排期的路线级事项见 **1.4**；本节只列需要排期的路线级事项，正文一律不重复。

- ✅ **Epic 72 WS 内网明文接入（第一步，2026-11-19 交付）**：5/5 `done`——72.1 `lan` 监听身份（非回环 + 显式 `WS_LAN_NO_AUTH` 免 token，三条准入 fail-loud、Host/Origin 防线保留、每次启动一条 WARNING）、72.2 第二 listener 退役（`WS_EXTERNAL_*` 五键 + `--ws-external-*` 三选项 + `9301` + `setup_ws_external.py` 全删，残留键由 `doctor.retired_key` 提示）、72.3 自检与排障面（doctor 三条 `ws_lan_*` findings + 启动公告三档 + faq/errors 改写）、72.4 安全口径同步（§4.19 要素 3/4/5 双档化，AGENTS/CLAUDE/deploy/.env.example/CHANGELOG 同批，守卫短语集加 `WS_LAN_NO_AUTH`）、72.5 `.env` 落地（`WS_HOST=192.168.2.226` + 免认证、TLS 停用）与容器内端到端取证。门禁：全量 `pytest` 5470 passed / 0 failed、ruff/format/mypy/bandit/mkdocs strict 全绿。未覆盖：客户端（`aihome-client`）6 处改动与第二步（`wss://` + token）不在本 epic；需求真源 `docs/tls-connect-guide.md` 在会话中途从工作树消失，宿主真机 `netstat` 对账待用户执行。
- 🔜 **生产化**：PyPI 发布、Docker Hub 镜像、CI release 路径（版本 `0.9.0`；A51 部分闭合——`CHANGELOG.md` + 版本真源守卫 + mkdocs strict 已落，2026-11-11；`.github/workflows` 仅 `ci.yml` + `codeql.yml`，release 是 `ci.yml` 内的 job 而非独立 workflow —— **2026-11-18 Epic 65 勘差确认该 job 已具备 build / twine check / OIDC 发布 / 多架构推送 / 审批门 + 失败摘要**，本条收敛为「首次真实 tag 发布待触发」）。
- ✅ **Epic 61 Web 检索工具周期（已闭合）**：2026-11-13 立项，2026-11-16 全链交付闭合——61.1 引擎层 `66a5b9f`、61.2 工具面 `1877250`、61.3 文档收口随本批收口提交入库；真实密钥冒烟经用户裁定跳过，挂账 A55（等 WEB_SEARCH_API_KEY）。
- ✅ **Epic 63 测试体系增强（已收口）**：2026-11-18 收口——63.1–63.8 全 finished（7 `done` + 63.4 `dropped`），`src/` 零改动；覆盖率实测 93.04%、CI 基准回归强制门禁（`cab4552`）、`tests/fixtures/` 唯一数据宿 + 参数化 78%（`b75075a`/`abf96d9`）。retro `accepted`（`initiative-heagent/tickets/epic-63-测试体系增强/epic-63-测试体系增强-retrospective.md`），三条 ADR 落 `initiative-heagent/decisions/`。
- ✅ **Epic 64 用户体验优化（已收口，2026-11-18）**：14/14 `done`（64.1–64.6 文档与错误形态、64.7 启动校验、64.8/64.9 进度、64.10 cron status、64.11 任务进度 API、64.12 /help 详情、64.13 错误建议命令、64.14 配置向导）；retro `accepted` 落 `initiative-heagent/tickets/epic-64-用户体验优化/epic-64-用户体验优化-retrospective.md`。收口残差两项登记 **A56**（进度跨进程不可见 / `examples/` 不在门禁范围）。
- ✅ **Epic 65 工程自动化（已收口，2026-11-18）**：9/9 `done`，按 v6 勘误「勘差 + ratchet」执行——5 条勘差收口（65.1 CI↔本地门禁映射契约 `tests/test_ci_gate_parity.py`、65.2 PR 触发面守卫、65.3 版本真源/65.4 CHANGELOG 现状已达成、65.5 补 `release` 失败摘要 step），4 条新建（65.6 `.devcontainer/` + 4 例契约、65.7 `LOG_FORMAT` 结构化日志 + `pub/log_config.py`、65.8 `DEBUG_MODE` 调试模式、65.9 `scripts/profile_run.py` 剖面脚本）。retro `accepted` 落 `initiative-heagent/tickets/epic-65-工程自动化/epic-65-工程自动化-retrospective.md`；全量 `pytest` 4867 passed / 覆盖率 93.43% / 六门绿；提交 `c8b0b24`（feat）/ `b93094a`（docs）。收口残差 **A58** 同日闭合：`runtime_stats` 采集器加 JSON 分支（`.heagent/skills/runtime_stats/collect.py`，本地技能不进版本库），text 日志输出与改前逐字节一致。
- ✅ **Epic 66 性能优化（已收口，2026-11-18）**：5/5 `done`——66.1 聚合层 `get_metadata` LRU（`f826aaf`；收口补 `RoutingProvider` / `KeyRotatingProvider` 接线）、66.2/66.3 技能匹配索引预计算 + 结果缓存（`6752b96`）、66.4 技能包索引期只读一次 entry（`d542a22`）、66.5 provider SDK 延迟导入（`0b1b156`：`import heagent` 后 `openai`/`anthropic` 均不在 `sys.modules`）。retro `accepted` 落 `initiative-heagent/tickets/epic-66-性能优化/epic-66-性能优化-retrospective.md`；收口同时把「冷启动省 >20%」做成比值判据（`tests/test_deferred_imports.py` 的 `-m benchmark` 用例）并去掉 CI 的 `--benchmark-only`（它原先把不用 fixture 的比值型判据整片跳过）。收口残差登记 **A59**（缓存容量配置键 + 命中率出口）。
- ✅ **Epic 67 安全增强（已收口，2026-11-18）**：10/10 `done`——67.1-67.3 输入验证框架 / 工具执行审计 JSONL / 敏感操作哈希链（`218dd9b`）、67.4/67.5 密钥轮换提醒与 keyring（`68c1ee2`）、67.6/67.9/67.10 漏洞扫描报告导出 / `mcp` 移出核心依赖（7→6）/ `requirements.lock`（`c50ce28`）、67.7/67.8 端点安全覆盖表 + 沙箱逃逸 7 向量（`b4d0e79`）。retro `accepted` 落 `initiative-heagent/tickets/epic-67-安全增强/epic-67-安全增强-retrospective.md`；收口残差登记 **A60**（keyring extra）/ **A61**（审计 retention）/ **A62**（CLI 写盘留痕）/ **A63**（缺 mcp 诊断判据）/ **A66**（依赖锁与审计白名单口径）。
- ✅ **Epic 68 文档与 API（已交付，2026-11-18）**：3/3 `done`——68.1/68.3 `scripts/build_docs.py` + `.github/workflows/docs.yml` Pages 部署（`31dfb55`；收口补 `site_url` 与触发分支 `master` —— 原 `if` 只认 `master`/`main`，而本仓默认分支是 `feat/module-integration`，部署会静默不触发）、68.2 公开 API docstring 覆盖判据（99 处补到 0，`0302daa`）。retro `accepted-with-open-items` 落 `initiative-heagent/tickets/epic-68-文档与API/epic-68-文档与API-retrospective.md`；残差 **A64 已于同日闭合**（用户裁定「开启」：`docs/api/` 13 页由 `mkdocstrings` 从 docstring 生成，判据 `tests/test_api_docs_pages.py`，闭合正文见 `retrospective-all-cycles.md` §三）/ **A65**（`frozen`：用户裁定暂停 Pages 发布，站点构建门仍在 CI docs step 里照跑）。
- ✅ **Epic 69 异常体系完善（已收口，2026-11-18）**：3/3 `done`——异常三层层次（`HeAgentException` 为别名）、4 类共 14 个专用异常、错误码与 `error_catalog()`（`a21c20e`）。retro `accepted` 落 `initiative-heagent/tickets/epic-69-异常体系完善/epic-69-异常体系完善-retrospective.md`；收口把 3 个层次外异常（`InputValidationError` / `McpSdkMissingError` / `FactCompactConflictError`）收编进 `pub/exceptions.py`（26 → **29** 类，码表与 `docs/errors.md` 同步）。
- ✅ **Epic 71 Web 端服务器状态面板（已收口，2026-11-19）**：6/6 `done`（`epic-71-web-server-status`）——71.1 状态协议与聚合端点（新只读 `GET /api/status`，`StatusSource` Protocol + 入口层注入，照 `TaskProgressSource` 范式）、71.2 部署面视图（绑定/端口/listener 模式/TLS/沙箱后端/写入闸门/provider 池档位名）、71.3 uptime 与依赖态（`started_at` 新记录；cron 作业与 `last_run` 取自每项目 `jobs.json`，**不报下次触发**——网页进程不启动调度器）、71.4 进程资源采样（stdlib only：Linux `/proc`、Windows `ctypes`，**不引 psutil**，不可采样即 `null`）、71.5 请求计数与延迟（`_AccessLogMiddleware` 就地整数自增 + 有界延迟 ring buffer）、71.6 网页端徽标与懒加载面板（`web/status-panel.js`：徽标只报 `run N` 不按比率、面板展开才轮询、字段覆盖守卫钉住「后端加字段面板必须跟进」）。收口 review（`edge-case-hunter` + `verification-gap` 两镜头 × 6 story）当场修 14 处（含 2 条 design 裁定按「按推荐」落地）、33 条 rejected，残差 11 条折 **A74**（前端执行级探针 / 真实来源计数映射 / 装配接线与上限 / `_proc` 失败路径等）；两项裁定已落地（沙箱改报 `effective_backend`、SSE 不进延迟窗口）；retro `accepted-with-open-items` 落 `initiative-heagent/tickets/epic-71-web-server-status/epic-71-web-server-status-retrospective.md`。立项依据：2026-11-19 实测 `/api/health` 只有 4 个封闭字段，在途 run / WS 连接数 / 端口与模式 / 沙箱 / cron / 资源 / 请求计数全部只有日志或进程内属性（缺口语义见 epic 信封「能力缺口」表）。
- 🆕 **Epic 70 Web 控制台 API 面板（2026-11-19 立项 → 同日 4 story 实现，待 review）**：4 story 全 `built`（`epic-70-web-console-api-panels`）——70.1 任务进度面板（`web/tasks.js`，轮询随终态启停）、70.2 服务身份徽标与进程会话快照（`web/app.js`：`/api/health` 的 service/version/schema_version + `/api/session`）、70.3 同源 API 探索器（`web/api-console.js`，20 条预置端点、写方法二次确认）、70.4 前端消费覆盖守卫（`tests/test_web_endpoint_coverage.py`，路由 ↔ 前端双向断言 + 两条真实文件变异验证）。立项依据：2026-11-19 实测网页端对 18 条 HTTP 路由的消费缺口（`/api/tasks`、`/api/tasks/{task_id}`、`/api/session` 零消费，且无任意端点操作入口；`file://` 独立页面因 `Origin: null` 被同源防线 403、服务端零 CORS，不可行）。
- ✅ **Epic 62 代码架构重构（已收口，2026-11-18）**：62.1 / 62.2 / 62.3 / 62.6 / 62.7 / 62.8 经 `tickets.py mark` 置 `done`（62.4 早 done、62.5 dropped），retro `accepted` 落 `initiative-heagent/tickets/epic-62-代码架构重构/epic-62-代码架构重构-retrospective.md`——欠账由 Epic 63 retro 的 Open questions 起、Epic 64 收口时一并清。
- ✅ **Epic 57（已收口）**：retro 遗留清理 2026-10-26 四 story 全 done；retro action item-12（push 待推远端）仍 open，owner=tan。
- ✅ **安全纵深（已裁定不做）**：MCP stdio server 子进程接入沙箱 —— 2026-09-27 用户裁定 (c) **不实施**（长命双向管道与既有 `CommandRunner` 形状冲突 + 隔离档属产品取舍 + 仍非边界），登记为已知暴露面（§1.4-A2 → Z-D24）。
- ⏳ **技能资源 TOCTOU 后续**：descriptor-relative open / 目录句柄、可信导入 snapshot、OS sandbox（§1.4-A1）。
- ⏳ **技术债**：benchmark 数据入库（历史趋势）、sandbox 开箱即用 profile 预设、Prompts/slash 结构化注册表（`engine/workflow.py` legacy 相位机归档已于 2026-09-17 `d835bd8` 完成）。

### 1.4 待完成工作（2026-09-24 整理）

> **权威层级**：活动（未闭合）条目正文见 [`open-items.md`](open-items.md)（唯一活动台账，2026-11-15 定名）；Epic/Story 状态以 `initiative-heagent/archive-v6/sprint-status.yaml`（v6 全周期，已归档）为准；安全缺口以 `docs/frame.md` 五为准。本节同时登记**已闭环却仍被其他文档列为待办**的条目（B 组），避免下一轮重复勘察。

#### A. 活动台账未闭合条目（16 条——A34/A41/A54/A55/A56/A59/A62/A65–A73，**索引**）

> **2026-11-15 起**：活动项正文见 [`open-items.md`](open-items.md)（唯一活动台账）。
> 已闭合编号索引（26 行表）、B 组修正表与 E 组决策关闭记录已迁 [`retrospective-all-cycles.md`](retrospective-all-cycles.md)（§三/§四）。

#### C. 纪律类产物滞后（非代码）

> 2026-11-19 处置批：四条里两条**已修**、两条**裁定不再回洗**（v6 的 `sprint-status.yaml` 已归档只读，
> 追溯性补写只会产出无现场证据的低可信度文本）。裁定可以推翻——若要恢复，按各条「回退口」执行。

- ~~**6 个 story 的 frontmatter 仍为 `status: backlog`**~~ → **2026-11-19 已修**：`36-1`、`36-2`、`36-3`、
  `37-1`、`38-1`、`39-1` 的 `status:` 已改为 `done`（与同 epic 的 `36-4` 一致）；`pytest
  tests/test_deferred_ledger.py tests/test_deferred_id_registry.py` 仍全绿（15 passed）。
- **`45-1` / `45-2` 无 story 文件**（该 epic 目录下只有 `45-3`）；`spec-45-3` / `spec-46-1` 已在归档提交中删除或改名（仅存 git 历史）。
  **裁定（2026-11-19）：不回补**——缺件本身是历史事实，据 yaml/retro 倒填一份当时不存在的 story 文件
  才是伪造产物；证据链保留在归档 yaml、`retrospective-all-cycles.md` 与 git 历史。回退口 = 用户明确要求
  补齐归档产物形态时再写「补写说明」式文件（标明为事后重构）。
- **16 个 epic 的 retrospective 键值仍为 `optional`**：25-28、38-39、43-46、49、51、55、57-58、61（2026-11-15 实测自 `sprint-status.yaml`）。
  已补做：36/37/40/41/42（09-18，键值已归一 `done`）、Epic 48（09-23）、Epic 50（09-27）、Epic 59（10-29，accepted-with-open-items）。Epic 54 / 56 retro 产物在各周期目录。
  **裁定（2026-11-19）：不再补做**——retro 的唯一产出是行动项，这些周期的行动项已进
  `open-items.md` / `retrospective-all-cycles.md`；键值住已归档只读的 v6 yaml，不再驱动任何流程；
  且触发时的现场证据（会话、评审记录）多数已不可复现。回退口 = 用户指定某一 epic 要正式 retro 时按
  v7 形态补到 `initiative-heagent/tickets/<epic>/`。
- **Epic 60 结构精简未登记 yaml**（2026-11-15 发现）：批次 9 五卡已于 2026-11-06~07 全部交付
  （`epics/epic-60-结构精简周期/` 5 份 spec frontmatter 均 `done`）。**裁定（2026-11-19）`retired`**：
  v6 yaml 已归档只读，补键没有消费方；交付事实由周期目录 spec frontmatter 与本文件 §1.3 承载。
- **`S4-1` 仍 `skipped`**（executor emit `sandbox_backend` + `sandbox_pid`）——沙箱执行轨迹不可追溯。
- `_bmad-output/README.md` 的导航已统一到当前归档规则：活动项只指向 [`open-items.md`](open-items.md)（2026-11-15 起），已闭合项按归属 Epic 进入各周期 `deferred-work.md`。

#### D. 技术债与改进候选（低优先，2026-09-18 逐条核实仍在）

> **2026-09-28 证据路径刷新**：下列条目写于 2026-09-26 包化重构之前，旧路径 `cli.py` / `config.py` / `mapping.py` **已不存在**（`cli.py` → `cli/console.py` + `cli/interactive.py`；`config.py` → `config/__init__.py`；`mapping.py` → `tools/mcp/mapping.py`）。**2026-11-15 行号再刷**：10-27 以来 125 提交致行号漂移，已复测仍成立条目的现址（`model_pricing_map`→`config/__init__.py:527`、`guard_content`→`tools/mcp/mapping.py:258`、hooks 4 事件→`engine/hooks.py:46-49`、slash 入口 `startswith("/")`→`cli/interactive.py:417,689`）。债务本身逐条复核**仍成立**。

| 项 | 现状证据 |
|----|----------|
| 生产化：PyPI 发布 / CI release workflow / Docker Hub（路线级已列 §1.3） | `.github/workflows` 仅 `ci.yml`、`codeql.yml`；版本 `0.9.0`（2026-11-11 minor bump；A51 部分闭合：CHANGELOG 载体 + 版本真源守卫 + mkdocs strict 已落） |
| ~~`engine/workflow.py` legacy 相位机归档~~ | **已完成**（2026-09-17 `d835bd8` 删除，仅存 state/checkpoint-store） |
| benchmark 数据入库（历史趋势） | 仅本地 autosave `./benchmark-data/`（gitignore）；**阈值入口已建**（Phase 5：`--benchmark-compare-fail=min:50%`，见 `docs/troubleshooting.md`） |
| `model_pricing` 抽独立数据模型 + 校验 | 仍是 JSON 字符串 + `model_pricing_map`（`config/__init__.py:519`） |
| `guard_content` 加 `source` 参数（web 语境文案不精确） | 签名仍是 `guard_content(text)`（`tools/mcp/mapping.py:217`） |
| Hook 事件集不全 | `engine/hooks.py:44-47` 仅 `PreToolUse`/`PostToolUse`/`SessionStart`/`SessionEnd` |
| firejail / WinJob 不可用仅 `logger.warning`，无 CLI banner | `tools/sandbox/winjob.py`（run 内降级 warning）/ `firejail.py`（构造期 warning） |
| readline 在 Windows 静默失效 | `cli/interactive.py:163` 仍为 try-import（无降级方案） |
| sandbox 开箱即用 profile 预设 / cron 常见模板 | 仅有 `SANDBOX_PROFILES` 声明通道，无预设库 |
| Prompts / slash 结构化注册表 | `slash.py` 已是注册表；CLI 入口仍 `startswith("/")`（`cli/interactive.py:276,446`） |
| sandbox profile 参数合法性校验 | 无校验入口（`SANDBOX_PROFILES` 直接透传 firejail 参数） |
| `skill_update` 遇富正文技能拒绝改写 | `SkillStore.update()` 对含自定章节的技能抛 `SkillRewriteError`（元数据可改，`pattern`/`steps` 须手工编辑，改前先备份） |
---

## 附：文档地图速查

| 路径 | 用途 |
|------|------|
| `docs/frame.md` | **架构权威**（活文档，随代码更新） |
| `docs/design.md` | 产品愿景与理念 |
| `docs/iteration.md` | 迭代历程与流程（2026-11-19 自 `docs/logs/` 迁回顶层，避免与运行时 `logs/` 撞名） |
| `_bmad-output/epics/epic-25-28-GUI界面周期/gui-plan.md` | GUI 实现计划 |
| `docs/README.md` | 文档索引 + 当前敏捷工作流维护说明（「Goal 工作流」章节，2026-09-20 自 workflow_intro.md 并入） |
| `_bmad-output/README.md` | 产物地图（按周期） |
| `_bmad-output/epic-overview.md` | **本文——当前状态与导航 + epic 总目录**（2026-11-15 自 consolidated-overview.md 重组定名；周期详解与台账归档已迁 retrospective-all-cycles.md） |
| `_bmad-output/open-items.md` | **唯一活动台账**（未闭合问题清单，2026-11-15 定名） |
| `_bmad-output/retrospective-all-cycles.md` | **历史记录唯一载体**（2026-11-15 四并二：周期回顾/详解 + deferred 闭合台账 §三 + review 闭合索引 §五） |
| `_bmad-output/initiative-heagent/archive-v6/sprint-status.yaml` | **sprint 状态单一权威**（全 15 周期；2026-11-15 归档） |
| `_bmad-output/epics/epic-01-10-主线规划周期/` | 主线周期原始产物（Epic 1-10） |
| `_bmad-output/epics/epic-11-18-MCP集成周期/` | MCP Client 集成周期（三阶段统一，2026-08-18 合并；含 Epic 11-18） |
| `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/` | Sandbox 硬化（Epic S1-S4） |
| `_bmad-output/epics/epic-19-20-健壮性硬化周期/` | 健壮性硬化（Epic 19-20） |
| `_bmad-output/epics/epic-21-24-质量工程周期/` | 质量工程深化（Epic 21-24） |
| `_bmad-output/epics/epic-25-28-GUI界面周期/` | GUI 周期（Epic 25-28） |
| `_bmad-output/epics/epic-29-35-交互扩展周期/` | 交互与可扩展层周期（Epic 29-35，2026-08-19） |
| `_bmad-output/epics/epic-36-39-文件安全防护周期/` | 文件安全与凭证防护（Epic 36-39，2026-08-24） |
| `_bmad-output/epics/epic-40-沙箱会话化周期/` | 沙箱会话化执行（Epic 40，2026-08-26） |
| `_bmad-output/epics/epic-41-目标驱动开发周期/` | 目标驱动开发 / `/goal`（Epic 41，2026-08-29） |
| `_bmad-output/epics/epic-42-BMad技能包运行时周期/` | BMad 技能包运行时（Epic 42，2026-09-01） |
| `_bmad-output/epics/epic-43-46-目标级工作流周期/` | 目标级工作流（Epic 43-46，2026-09-01） |
| `_bmad-output/epics/epic-47-声明式BMad敏捷工作流周期/` | 声明式 BMad 敏捷工作流（Epic 47，2026-09-01 → 09-15） |
| `_bmad-output/epics/epic-48-TCP网络接口周期/` | TCP 网络接口（Epic 48，2026-09-22） |
| `_bmad-output/epics/epic-49-HTTP网页访问周期/` | HTTP 网页入口（Epic 49，2026-09-23） |
| `_bmad-output/epics/epic-50-网页控制台周期/` | 网页控制台（Epic 50，2026-09-23 建立 → 09-24 实现 → 09-27 收口） |
| `_bmad-output/epics/epic-51-goal-workflow优化周期/` | `/goal` 与 workflow 可信交付优化（Epic 51，2026-09-29 建立 → 2026-10-23 收口） |
| `_bmad-output/epics/epic-52-安全并行story执行周期/` | goal 工作流安全并行 Story 执行器（Epic 52，2026-10-09 建立并交付） |
| `_bmad-output/epics/epic-53-容器沙箱档周期/` | 容器沙箱档（Epic 53，2026-10-20 立项，3 story 在 review；期二挂 deferred-work） |
| `_bmad-output/epics/epic-58-cron结果推送周期/` | cron 结果推送（Epic 58，2026-10-28 立项 → 11-02 收口；`EventStreamHub` 通用核） |
| `_bmad-output/epics/epic-59-MEMORY语义压缩周期/` | MEMORY 语义压缩（Epic 59，2026-10-29 立项 → 11-03 收口；`fact_compact` + dream 接线） |
| `_bmad-output/epics/epic-60-结构精简周期/` | 结构精简批次 9（2026-11-06~07 五卡交付；**yaml 未登记键**，见 §1.4-C） |
| `_bmad-output/epics/epic-61-Web检索周期/` | Web 检索工具（Epic 61，2026-11-13 立项，2026-11-16 交付闭合；SPEC.md + 票树 3 story 全 done，冒烟残差挂账 A55） |
| `_bmad-output/initiative-heagent/` | 项目改进计划 initiative（规划四件套 + v7 票树 + archive-v6；2026-11-11 立项，2026-11-15 迁移） |
| `_bmad-output/epics/<周期>/[epic-NN-主题/]stories/` | 按 epic 归档的 story 文件（2026-09-26 全深度实测：**102 个**，**28 个** `stories/` 目录） |
| `_bmad-output/epics/<周期>/<epic-NN-主题>/` | 补丁 spec 与 story 同目录（原 `patches/<领域>/` 2026-09-15 解散） |
| `_bmad-output/implementation-artifacts/arch-optimization-cycle/` | **架构优化周期档案**（总方案 + phase0..5 spec，各含执行记录；2026-09-22 归档，原 `docs/test.md` 已删并） |
| `CHANGELOG.md`（仓库根） | 发版契约载体（保有 `## [Unreleased]` 节，`tests/test_release_workflow_contract.py` 钉死；2026-11-11 随 A51 建立） |
| `_bmad-output/implementation-artifacts/spec-business-data-integration.md`（**2026-09-15 已删除**） | 业务数据整合**母规划 spec**——未启动、未衍生实现 spec 或 epic，正文仅存 git 历史（见 `_bmad-output/README.md`「已失效删除」） |
| `_bmad-output/epics/<周期>/deferred-work.md` | 已闭合遗留项按归属 epic 归档（2026-11-15 实测存在 **11 份**：01-10 / 11-18 / S1-S4 / 36-39 / 40 / 41 / 47 / 48 / 50 / **51** / **53**） |
| `_bmad-output/specs/` | quick-dev 本地工作件（gitignored；Epic 41 goal 契约已归档至 `_bmad-output/epics/epic-41-目标驱动开发周期/spec-goal-command/`） |
