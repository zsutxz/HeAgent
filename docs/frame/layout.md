# 目录结构（`src/heagent/`）

> 状态：阅读辅助快照，自 [`framework.md`](../framework.md) 原「六、目录结构」迁出（2026-11-24 整理）。
> **`src/` 是唯一真源**：本页只是「哪个文件干什么」的速查表，与代码不一致时以代码为准；
> 分层规则与依赖方向见 [`framework.md`](../framework.md#三模块依赖关系-dag) §三，布局契约见
> `tests/test_architecture_contracts.py`，安全立场见 [§4.18](../framework.md#418-安全口径canonical)。

## 目录结构

```
src/heagent/
├── __init__.py
├── __main__.py              # python -m heagent 入口
├── housekeeping.py          # 启动期运行时产物保留期回收（2026-11-06 自 cli/ 迁回顶层；维护面模块，下层不得反向导入）
├── cli/                     # 入口层命名空间（2026-09-26 收编原七个平铺 cli*.py；`__init__.py` 零 import）
│   ├── console.py           # Click 命令组 + 参数解析 + 启动编排（入口脚本 `heagent.cli.console:main`；原 cli.py）
│   ├── composition.py       # 装配：provider→engine→loop / soul / 上下文策略 / plan mode / dream / 事件 sink（2026-09-26 自 cli.py 拆出）
│   ├── interactive.py       # 单次/交互执行：REPL + 斜杠命令族 + 内嵌 HTTP 挂载点（2026-09-26 自 cli.py 拆出）
│   ├── help_view.py         # /help 渲染面：列表版 + 详情版 + 未知命令建议（纯展示；2026-11-18 自 interactive.py 拆出）
│   ├── init.py              # heagent init 子命令（全局配置/项目上下文模板生成，2026-09-17 自 cli.py 拆出）
│   ├── goal/                # /goal 命令族子包（声明式工作流分发 + cron 自动推进；2026-11-17 Story 62.2 自 cli/goal.py 拆出，__init__ 全量再导出）
│   │   ├── commands.py      # 命令面：命令处理器、参数解析/分发、cron 自动推进与 runner 入口
│   │   ├── execution.py     # 步骤执行面：声明式解析辅助、步骤执行、script 两阶段与 SubAgent 会话缝
│   │   ├── messages.py      # 用户可见输出漏斗（sink ContextVar + _echo 单点出口）
│   │   └── verify.py        # 验证面：质量门 / 证据求值 / 受治理重跑 / workflow 事件发射
│   ├── http.py              # http-server 子命令 + HTTP 服务装配（入口层组合根；Epic 49）
│   ├── http_config.py       # HTTP/WS listener 配置装配（Settings + CLI 覆盖 → *Config；2026-11-17 Story 62.8 自 http.py 拆出）
│   ├── http_console.py      # 网页控制台的项目/会话/配置面（Epic 50；2026-09-26 自 cli_http.py 拆出）
│   ├── http_status.py       # GET /api/status 的来源适配（运行态 / WS 计数 / 后台任务 -> StatusResponse；Story 71.1）
│   ├── dialogs.py           # 服务端原生「选择目录」对话框（Story 50-8）
│   ├── port_finder.py       # 监听端口顺延查找（preferred…preferred+9 内取空口；2026-09-27）
│   ├── display.py           # 终端渲染辅助（CLI 与 GUI 共用；原 cli_display.py）
│   ├── errors.py            # CLI 错误的统一出口（描述 + Try 选项 + Docs 锚点；Story 64.5）
│   ├── doctor.py            # heagent doctor 配置诊断（只读，11 组检查 / 30 个诊断码；Story 64.6 / 73.3）
│   ├── cron_cmd.py          # heagent cron status：定时任务状态查询（只读 jobs.json；Story 64.10）
│   ├── audit_cmd.py         # heagent audit list|export|verify：审计 JSONL 查询 / 导出 / 跨段哈希链校验（Story 67.2 / 67.3；段轮转 A61）
│   ├── progress.py          # 工具执行耗时行 + 大文件读写进度（Story 64.8 / 64.9）
│   ├── run_history.py       # 重启后的读侧事件回放：rollout.jsonl → SSE 负载（A35，2026-11-18）
│   ├── settings_audit.py    # CLI 侧用户级配置写入的统一审计留痕（A62，2026-11-21）
│   ├── suggestions.py       # 错误场景 → ≥2 条可执行命令建议（Story 64.13）
│   ├── wizard.py            # heagent init --interactive 配置向导（Story 64.14）
│   ├── skill_merge.py       # /skill-merge 跨根同名技能交互收口（skills 双根，2026-10-10）
│   ├── slash.py             # 交互模式斜杠命令注册与路由（2026-09-26 自顶层迁入）
│   ├── terminal.py          # 终端键盘监听（Esc 暂停 / Enter 恢复 / 双击 Esc 打断；2026-09-26 自顶层迁入）
│   ├── tls_cmd.py           # heagent tls init|issue|rotate-key|fingerprint|verify：WS TLS 身份材料的唯一入口（Story 73.2）
│   ├── wiring.py            # provider 呈现薄壳（规则在 providers/composition.py，2026-11-07 迁出）+ ensure_runtime_config / build_cron_job_runner（CLI/GUI 共用；2026-09-26 自顶层迁入）
│   ├── ws_project_adapter.py # WS 项目通道适配器：控制台项目面 → 项目帧（只翻译不含判据，不碰盘与注册表；Epic 75）
│   └── ws_submission_cache.py # WS 提交幂等窗口：在途合流 / 成功重放 / 失败移出（60s TTL、256 条上限、纯内存；Epic 77）
├── web/                     # 内置网页资源包（HTML/CSS/JS，随 wheel 分发；经 importlib.resources 读取）
├── pub/                     # 公共层：零 heagent 运行栈依赖（任何层可依赖；`__init__.py` 零 import，2026-09-26）
│   ├── exceptions.py        # 异常层级
│   ├── types.py             # 共享 Pydantic 模型
│   ├── persist.py           # 原子写 + 容错读 + 跨进程文件锁 + prune 批量内核
│   ├── roles.py             # RoleSpec + 内置角色注册表（agent/tools/engine 共用）
│   ├── frontmatter.py       # 共享 frontmatter 解析（零 heagent 依赖；六处手写解析器收敛，2026-09-17）
│   ├── safe_logging.py      # 日志卫生（safe_log 容错 + 故障守卫 + 启发式脱敏；零 heagent 依赖，2026-09-23）
│   ├── log_config.py        # 日志行格式单一实现：text（人读，与历史输出逐字一致）/ json（timestamp 带时区偏移；Epic 65）
│   ├── audit.py             # 追加式审计面（工具执行 + 敏感操作 JSONL，prev/digest 哈希链；段轮转与段头续接 A61）
│   ├── validation.py        # 统一输入验证框架（Rule 链 + 结构化 issue + InputValidationError；Story 67.1）
│   ├── workspace.py         # 状态根派生的规范路径（WorkspacePaths）
│   ├── task_shutdown.py     # 后台调度 task 关停内核（cron/dream 共用）
│   ├── projects.py          # 网页控制台项目注册表（零运行栈依赖；2026-09-26 自顶层迁入）
│   └── event_lines.py       # 引擎事件的展示层纯函数（EventCursor 差分 + 单行格式化；GUI 薄壳调用，2026-09-28 台账 A24）
├── config/                  # 配置面（依赖 pub/，2026-09-26 自顶层平铺收敛）
│   ├── __init__.py          # pydantic-settings 配置（Settings / get_settings / resolve_runtime_config；原 config.py）
│   ├── catalog/             # 配置四层来源求解（2026-11-11 E3 绞杀者拆为子包，行为零改动，包壳统一 re-export）
│   │   ├── models.py        # 配置面 Pydantic 报表模型（ConfigReport / ConfigItem / ConfigGroupSpec 等）
│   │   ├── groups.py        # 分组数据表：组规格、可写白名单来源、只读原因与展示标签
│   │   ├── masking.py       # 凭证掩码口径：定长掩码、秘密键后缀判定与「空值」识别
│   │   ├── guards.py        # 取值守卫与影响面：字段上界、值域守卫、impact 分级
│   │   ├── envscan.py       # .env / setting.md 行级扫描（只产诊断，永不参与取值）
│   │   ├── sources.py       # 四层来源求解器：pydantic-settings 单一来源 + 逐层失败降级
│   │   ├── classify.py      # 键名分类：可写白名单、分类结果与系统环境键枚举
│   │   └── report.py        # 报表装配：配置项、分组、未知键与路由池视图
│   ├── write.py             # 受闸门的项目 .env 写流水线（原 config_write.py；Story 50-5）
│   ├── envfile.py           # .env 行级保真读写（原 envfile.py；Story 50-5）
│   ├── keyring_store.py     # 密钥唯一收敛点：KEYRING_ENABLED 时先查系统 keyring 再回退字段值（Story 67.5）
│   ├── rotation.py          # 密钥轮换提醒：首次观测日期落 <状态根>/key_rotation.json，超期启动期 WARNING（Story 67.4）
│   ├── validation.py        # 启动期必需配置校验（只判「不满足必然起不来」，<100ms；Story 64.7）
│   └── user_settings.py     # 用户级 setting.md：读/渲染/一次性迁移 + 用户层 pydantic-settings 源
│
├── agent/                   # 顶层编排
│   ├── loop.py              # AgentLoop façade（依赖注入装配 + 公共入口委托，Phase 2）
│   ├── run_lifecycle.py     # run 生命周期策略（状态类 + 初始化/非流式循环体/终结/检查点）
│   ├── stream_runtime.py    # 流式循环体策略（run_stream）
│   ├── resume_runtime.py    # resume 快照重建策略
│   ├── context_runtime.py   # 迭代控制/消息追加/压缩/窗口重置策略
│   ├── message_ports.py     # steering/follow-up 端口 + 协作式暂停
│   ├── system_prompt.py     # _build_system 拼装（人格/上下文/技能/记忆/画像）
│   ├── tool_execution.py    # _execute_one 工具执行链（ledger → policy → executor）
│   ├── middleware.py        # 中间件组合 + make_retry_middleware
│   ├── delegation.py        # 子 Agent 委派回调（tools ↔ agent 依赖倒置）
│   └── sub.py               # 子 Agent（并行任务 + 角色化）
│
├── providers/               # LLM Provider（实现互不依赖；composition.py 为装配规则真身，依赖各实现）
│   ├── base.py              # BaseProvider Protocol
│   ├── composition.py       # provider 装配规则真身（2026-11-07 批次9卡B 迁入；致命呈现由 cli/wiring 薄壳完成）
│   ├── openai.py            # OpenAI 兼容（含 DeepSeek）
│   ├── fallback_base.py     # 回退层共享基础设施：错误包装 / 回退决策 / 回退循环模板（2026-09-27）
│   ├── anthropic.py         # Anthropic（含提示词缓存 FR-3）
│   ├── chain.py             # ProviderChain 回退链（外层，FR-4 回退精度）
│   ├── metadata_cache.py    # 聚合层 get_metadata 的进程内 LRU（显式失效 + hits/misses 观测面；Story 66.1）
│   ├── key_rotation.py      # KeyRotatingProvider 密钥池轮换（中层）
│   ├── retry.py             # 错误分类 + make_retry_middleware（内层）
│   ├── responses.py         # OpenAI Responses API 兼容 Provider
│   ├── router.py            # RoutingProvider 智能路由（按任务特征选模型，主动选择层）
│   └── switchable.py        # SwitchableProvider 运行时多 vendor 切换（外层选择层）
│
├── tools/                   # 工具系统
│   ├── decorator.py         # @tool 装饰器
│   ├── registry.py          # ToolRegistry 单例
│   ├── safety.py            # SafetyGuard（shell 命令安全）
│   ├── path_safety.py       # 工作区路径校验（文件工具）
│   ├── edits.py             # 编辑原语：行尾/BOM 保真读写、diff 回执、落盘前快照
│   ├── sandbox/             # 沙箱包（Phase 4 C1 自单文件拆出 + Epic 53 container 档；`__init__` re-export 历史公共名）
│   │   ├── contracts.py     # 契约层：SandboxTier 强度分级 + CommandRunner Protocol + 注入 slot（零后端依赖）
│   │   ├── process.py       # 进程监督内核：spawn / 超时 / 取消 / kill-reap / 输出截断的单点实现
│   │   ├── firejail.py      # Firejail 后端（OS 级隔离，Linux-only，非完美边界）
│   │   ├── winjob.py        # Windows Job Objects 后端（进程级隔离，随句柄关闭杀全树）
│   │   ├── docker.py        # Docker 容器后端（CONTAINER 档首个实现，Epic 53 期一：短命命令一次性容器）
│   │   └── session.py       # 沙箱会话目录约定与 per-run 会话作用域（目录约定，非安全边界）
│   ├── call_summary.py      # 工具调用「作用对象」摘要（展示层共用）
│   ├── runtime.py           # 工具运行态绑定（_runtime_scope）
│   ├── mcp/                 # MCP 适配层
│   │   ├── config.py        # MCPConfig + load_mcp_config（.mcp.json + ${ENV} 插值）
│   │   ├── mapping.py       # mcp_tool_to_schema + bridge_result
│   │   ├── session_api.py   # MCP SDK 会话字段兼容访问
│   │   ├── sdk.py           # mcp SDK 导入唯一通道（可选依赖，缺包给安装诊断；Story 67.9）
│   │   ├── client.py        # TransportOpener Protocol + 默认实现（Phase 4 C2）
│   │   ├── registry_bridge.py  # 注册/注销单一入口（Phase 4 C2）
│   │   ├── manager.py       # MCPClientManager（生命周期 façade + discovery_failures）
│   │   └── stdio_sandbox.py  # MCP stdio 子进程进容器（把 SDK 子进程换成 docker CLI 拉起，Story 53-5）
│   └── builtins/            # 内置工具（29 个）
│       ├── __init__.py      # 触发注册
│       ├── shell.py         # shell 命令执行
│       ├── file.py          # 文件读写
│       ├── search.py        # 文件/内容搜索
│       ├── skills.py        # 技能管理（create/update/list/delete/curate/archive）
│       ├── memory.py        # 记忆管理（fact_add/profile_update）
│       ├── cron.py          # Cron 管理（add/list/remove）
│       ├── subagent.py      # 子 Agent 委派工具（仅持可注入回调，不导入 agent/）
│       ├── web.py           # web_fetch（HTTP 抓取，read-only）+ web_search（检索工具面，read-only）
│       ├── web_search_engine.py  # web_search 引擎面（SearchEngine 协议/Tavily/registry，非 @tool）
│       └── git.py           # Git 工具（status/diff/log/blame，read-only）
│
├── context/                 # 上下文管理
│   ├── loader.py            # 上下文文件分层扫描（仓库根 → cwd，CONTEXT.md > AGENTS.md > CLAUDE.md）
│   ├── tokens.py            # CJK 感知 Token 估算
│   ├── sidecall.py          # 旁路 provider 调用统一记账（压缩/重置/命名留日志与校准）
│   ├── compressor.py        # 消息压缩
│   ├── window_reset.py      # 窗口重置 + checkpoint-resume（P3）
│   └── session.py           # 会话持久化
│
├── memory/                  # 记忆系统
│   ├── facts.py             # 事实存储 + 去重
│   ├── profile.py           # 用户画像
│   ├── soul.py              # 人格系统（全局/项目两级）
│   ├── auto_archive.py      # 启动期 MEMORY.md 字节归档（超阈值移出最旧前缀进 archive/；2026-09-27）
│   ├── compact.py           # MEMORY.md 语义压缩（Epic 59 写侧唯一入口：合并重复/过时条目，留底先行）
│   └── dream.py             # 离线记忆巩固调度器（Dreaming 模式）
│
├── skills/                  # 技能库域包（2026-10-10 自 memory/ 迁出）
│   ├── __init__.py          # 历史公共名 re-export 门面
│   ├── skill_models.py      # 技能模型 + SKILL.md 解析 + 名称校验
│   ├── skill_rewrite.py     # 渲染 + frontmatter 就地改写（正文保真）
│   ├── skill_catalog.py     # 匹配 + 过期盘点（纯检索）
│   ├── skill_store.py       # SkillStore 门面（读经 open_text_under_root）
│   ├── skill_meta.py        # meta.yaml 契约（2026-10-10 拆分落点）
│   ├── skill_packages.py    # 声明式技能包索引与安全资源读取（工作流装配在 goal/workflow_loader.py）
│   └── skill_importer.py    # 技能包导入与目录映射
│
├── engine/                  # 运行时引擎（P0）
│   ├── container.py         # EngineContainer（DI）
│   ├── context.py           # RunContext / RunStatus
│   ├── policy.py            # PolicyEngine 准入/审批/沙箱裁决
│   ├── executor.py          # ToolExecutor 策略分发
│   ├── store.py             # RunStore 运行快照（async I/O）
│   ├── ledger.py            # ExecutionLedger 幂等/租约（async I/O）
│   ├── checkpoint.py        # WorkflowCheckpointStore + GoalWorkflowState 运行时进度（2026-09-20 自 workflow.py 改名；load_state 恢复进度，与装载声明区分）
│   ├── workflow_resource.py # 工作流资源模型 WorkflowResource/Step（2026-09-20 自 memory.skill_packages 迁入）
│   ├── state_machine.py     # 状态模型 + 唯一状态写点 _transition_fields + update 推导 + 决策内核
│   ├── story_batch.py       # story 并行批派生/收集 + 回调调用契约 + 写集词法
│   ├── workflow_runner.py   # 声明式 workflow 单步执行器
│   ├── workflow_events.py   # 工作流状态机驱动事件（WorkflowEvent 枚举）
│   ├── workflow_transition.py  # 状态机转换表 transition()（fail-loud 非法转换）
│   ├── approval.py          # 交互式审批协议与状态
│   ├── hooks.py             # 生命周期 Hook 调度
│   ├── tasks.py             # 后台任务进度注册表（四态 + 百分比单调 + TTL/条数淘汰；Story 64.11）
│   └── observability.py     # EventBus / 事件
├── events/                  # 事件传输层（JSONL 契约 / rollout 落盘 / replay）
│   ├── protocol.py          # RunEvent + EngineEvent → RunEvent 映射
│   └── sink.py              # JsonlSink（stdout/rollout）+ read_rollout / render_event
│
├── network/                 # 网络入口传输层（Epic 49–50 HTTP/SSE + Epic 54–56 WS；协议/生命周期/暴露判定，不依赖运行栈）
│   ├── http_protocol.py     # HTTP/SSE 协议模型与稳定错误码（含 HttpRunConflictError 的唯一来源）
│   ├── ws_protocol.py       # WebSocket 帧模型（event/ack/error/notification）、命令枚举（run/cancel/cancel_run/ping/projects）、三条上界与关闭码
│   ├── http_server/         # HTTP/SSE 子包（2026-11-15 Story 62.1 自单文件拆出；层序无环：config → assets/records → service → pipeline → endpoints_* → middleware → app → listener，`__init__` 全量再导出）
│   │   ├── config.py        # HttpServerConfig 与启动失败异常（层序最底层，只依赖 Pydantic + 请求上限常量）
│   │   ├── assets.py        # 包内静态资源白名单与读取
│   │   ├── records.py       # _RunRecord 单次运行状态源（有界事件缓冲 / 订阅者 / 终态转换，AD-3·AD-4）
│   │   ├── service.py       # HttpRunService：运行生命周期、单运行名额、看门狗与 SSE 事件源（AD-3 唯一所有者）
│   │   ├── metrics.py          # 请求计数与延迟窗口（Story 71.5）
│   │   ├── pipeline.py      # 请求管线 helper：有界读体 / 校验 / 错误信封 / SSE 编码 / 控制台错误码状态表
│   │   ├── endpoints_run.py  # 运行 API 端点：创建 / SSE 订阅 / 取消 / 会话快照
│   │   ├── endpoints_console.py  # 控制台端点：项目 / 会话 / 配置 / 原生目录选择（分组与来源求解留入口层）
│   │   ├── endpoints_tasks.py  # 后台任务进度查询端点（只认注入的 TaskProgressSource，Story 64.11）
│   │   ├── middleware.py    # ASGI 中间件与安全响应头：同源防线 / 请求观测 / 安全头（包装序装配在 app）
│   │   ├── app.py           # ASGI 应用装配：健康检查 + 运行/控制台路由 + 包内静态页（路由常量与注册同模块，供路由快照解析）
│   │   └── listener.py      # HTTP listener 生命周期：绑定 / 就绪探测 / 有界关闭（start·serve_forever·close 三件套）
│   ├── ws_host.py           # WsServer / WsServerConfig / build_ws_app：独立 listener、四条 WS 端点的装配（Epic 56/58）
│   ├── origin.py            # 入口 listener 同源防线（AD-6）与探测地址推导（HTTP/WS 共用的单源；Epic 56 D1）
│   ├── optional_deps.py     # 可选依赖延迟导入辅助 require_module + HttpDependencyError（http_server / ws_host 共用）
│   ├── ws_server.py         # WS 端点逻辑：提交 run、单 run 订阅+游标续传、命令处理、连接生命周期
│   ├── ws_commands.py       # 集合级端点的命令循环簇（分派 / 提交 / 取消 / 项目列表；Story 74.3 自 ws_server 拆出）
│   ├── ws_auth.py           # 对外模式认证纯逻辑：Bearer 解析 / 常量时间比较 / 按来源失败限速（Epic 56）
│   ├── event_stream_hub.py  # 只读事件流通用核：seq / 环形缓冲 / 游标重放 / 背压踢人 / 有界关停（Epic 58 D3）
│   ├── cli_event_hub.py     # CLI 终端的旁路流（EventStreamHub 薄适配：本轮 run 语义 + RunEventPayload）
│   ├── notification_hub.py  # cron 结果通知流（EventStreamHub 薄适配：一次执行一条 + NotificationPayload）
│   ├── http_console_protocol.py  # 网页控制台协议模型：项目/会话/配置面板与写通道的请求-响应契约（Epic 50）
│   ├── exposure.py          # 回环判定 + 「无认证 / 无 TLS / 非生产边界」告警文案（单点，不解析 DNS）
│   ├── proc_stats.py        # 本进程资源采样：Linux /proc、Windows ctypes（零第三方依赖，不可得即 null；Story 71.4）
│   └── tls_identity.py      # TLS 身份解析（纯 stdlib ASN.1 遍历）：SPKI 指纹 / 短指纹 / 有效期 / SAN / 证书与身份密钥配对（Story 73.1）
│
├── goal/                    # /goal 域层（入口层，供 cli/goal 使用，下层不得反向导入）
│   ├── application.py       # workflow use-case 确定性内核（story 选择/checkpoint 恢复/推进；click-free，Phase 3）
│   ├── workflow_support.py  # workflow 声明面：包加载/校验、绑定冻结、门禁与 open-question 策略、prompt 装配（2026-11-17 Story 62.8 拆出）
│   ├── document.py          # brief.md 定位/命名规则/增量更新（存量回落 require.md/GOAL.md）+ goal id 分配与三步写（reserve_goal_id / write_goal_bundle，2026-11-07 自 cli/goal.py 迁入）
│   ├── naming.py            # /goal new 项目名 LLM 生成，失败显性回退 project（2026-09-21）
│   ├── workflow_loader.py   # workflow.md 声明装配 read_workflow（frontmatter 策略/内嵌步骤/模板必需性/validation: 证据子句解析）
│   ├── doctor.py            # 声明驱动的只读预检（doctor_checks 词汇 → 结构化报告，Story 51-1）
│   ├── status_view.py       # /goal status 纯投影（status_fields 词汇，零 IO，Story 51-1）
│   ├── evidence.py          # 结构化执行证据：版本化模型 + 追加式存储 + 受治理结果证据化（Story 51-3）
│   ├── git_port.py          # 只读 Git 端口：base/head/变更集与工作区冲突状态，从不 commit（Story 51-3）
│   ├── decisions.py         # 人工决策日志：版本化模型 + 追加式存储（<goal_dir>/decisions/，Story 51-5）
│   ├── quality_gates.py     # 通用门禁求值器：validation: 结构化子句 → 证据/产物/只读 Git 比对；
│   │                        #   gate: 宿主注册表（名字→语义+求值函数分派表）也在此（Story 51-4）
│   ├── write_audit.py       # Story 写集审计判负策略（AD-18 / A40 内容指纹 / A41-A43 披露与 remediation，2026-11-07 自 cli/goal.py 迁入）
│   ├── worktree.py          # Story 物理隔离（AD-20 / A41）：worktree 确定性路径 + detached 创建 + --force 移除，产物回收 promote_story_commit（临时引用 refs/heagent/stories/<story> → cherry-pick → 删引用，冲突 abort 后显性失败；进程内串行门防 index.lock 争用）与 promote_goal_products（gitignore 的 `_he-output` 增量搬回主工作区）（2026-11-21）
│   ├── mutex.py             # goal 域互斥公共端口：进程内 asyncio.Lock + 跨进程 .heagent/goal.lock（单推进者不变量下沉，2026-10-07 / A32②）
│   ├── script_api.py        # GoalScript 受限能力门面：只登记操作请求，准入与执行交给既有 Runner/治理链（Story 51-7）
│   ├── script_loader.py     # GoalScript 资源加载与静态约束（唯一入口名 build_workflow，AST 白名单）
│   └── script_runtime.py    # GoalScript 有界宿主执行：AST 指令预算 + host 调用回本进程（Story 51-7 两阶段）
├── gui/                     # 可选 Textual GUI（需 `[gui]` extra；Epic 27 面板 + Epic 28 事件流）
│   ├── app.py               # Textual App 根壳：持有 loop / bridge / state / stores，管理页面导航
│   ├── bridge.py            # AgentLoop ↔ Textual 异步数据桥
│   ├── cli.py               # `heagent gui` 子命令入口（建 Provider/AgentLoop 后交给 App）
│   ├── observers.py         # EventBus → GuiState 观察者 + 事件环形缓冲（Epic 28）
│   ├── state.py             # 响应式全局状态（Pydantic + Textual reactive 适配）
│   ├── screens/             # 页面（每页一 Screen）
│   │   ├── chat.py          # 主聊天界面（流式对话 + 工具调用可视化）
│   │   ├── cron.py          # Cron 任务管理面板（DataTable + 添加/删除，Story 27-3）
│   │   ├── cron_add.py      # 添加 Cron 任务弹窗
│   │   ├── event_log.py     # 事件日志页面（Epic 28-1）
│   │   ├── memory.py        # 记忆/画像只读浏览面板（Story 27-3）
│   │   ├── runs.py          # 运行历史面板（运行树 + 详情/恢复，Epic 28-2/3）
│   │   └── skills.py        # 技能管理面板（详情/创建弹窗，Story 27-2）
│   └── widgets/             # 复用 widget
│       └── event_log.py     # 引擎事件实时日志 widget（RichLog + 自动滚动，Epic 28-1）
└── cron/                    # 定时调度
    ├── expr.py              # 5-field cron 表达式解析纯叶子（零 heagent 导入；memory/dream 与 cron/scheduler 共用）
    ├── jobs.py              # CronJob 模型 + JobStore 持久化
    ├── status.py            # 执行状态派生与展示（never/running/success/failed/interrupted + next fire；Story 64.10）
    └── scheduler.py         # CronScheduler 后台调度器
```
