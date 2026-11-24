# 配置管理（`config/` 包）

> 状态：实现细节参考，自 [`framework.md`](../framework.md) **4.10** 迁出（2026-11-24 整理；编号不变，
> 其它文档里「4.10」的引用即指本页）。架构视角（项目定位 / 数据流 / 模块 DAG / 各模块职责与边界）见
> [`framework.md`](../framework.md)，安全立场（canonical）见 [§4.18](../framework.md#418-安全口径canonical)，
> 扩展页总索引见 [`frame/README.md`](README.md)。

## 4.10 配置管理 (`config/` 包)

> `config/catalog/` 自 2026-11-11 起是**子包**（原 1350 行单文件，E3 绞杀者）：
> `models`（Pydantic 模型）/ `groups`（分组数据表）/ `masking`（凭证掩码）/ `guards`（取值守卫与影响面）/
> `envscan`（行级扫描）/ `sources`（四层来源求解）/ `classify`（键名分类）/ `report`（报表装配）；
> `__init__.py` 只做 `X as X` 形式的显式 re-export，公共名 `heagent.config.catalog` 与 `__all__`（34 项）零变化。
> **子模块是内部实现细节**：外部（含 `tests/`）只经 `heagent.config.catalog` 导入，直连
> `catalog.models` 等子模块会绕过包壳契约、且不进 `public_exports.json`。
> 依赖方向：models → groups/masking/guards/envscan/sources → classify → report（无环）。

- `pydantic-settings` 的 `Settings` 类，从 `.env` + 环境变量加载
- **加载优先级**：系统环境变量 > 项目 `.env` > 用户 `~/.heagent/setting.md`（YAML frontmatter，`config/user_settings.py`）> 字段默认值；同 key 冲突时高优先级来源胜出。顺序由 `Settings.settings_customise_sources` 的源元组决定（md 源插在 dotenv 源之后）；`.env` 是项目级专用格式，用户级是 markdown。
- `get_settings()` 单例访问，`reset_settings()` 用于测试重置
- **运行配置快照（Phase 1，2026-09-21）**：`ResolvedRuntimeConfig`（冻结 `Settings` 子类，集合深拷贝、凭证 `exclude` 不入 repr/JSON）+ `resolve_runtime_config(settings=None, **overrides)`——显式非 `None` 覆盖才生效（保留「显式 `False` 反向压过 env `True`」三态语义），每个字段经 `RuntimeConfigSource` 记录来源（`settings`/`override`）。入口层（`cli.composition._build_loop`/`gui_main`）组装期解析一次，engine（`EngineContainer.runtime_config`，并把实际生效后端记入 `SandboxDecision` 写入 run metadata）与两类 loop（主/cron）共用同一份；`AgentLoop`/`SubAgent` 业务执行（压缩/窗口重置/委派深度/提示词块/技能预算）只读快照，运行中全局 Settings 漂移不影响已创建的运行。`PolicyVerdict.source` 标记裁决来源。业务方法禁止隐式 `get_settings()`；构造期回退与无 run 绑定的工具路径（housekeeping/dream/skills 未绑定回退）除外，详见下表口径。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `deepseek_api_key` | None | DeepSeek API Key（优先） |
| `active_provider` | None | 默认激活的 provider 条目名（多条目时作为启动选择与 `SwitchableProvider` 的默认项）；未设或该条目不可用 → 回退到第一个可用条目（构建顺序 `deepseek` → `claude` → `openai` → `kimi` → `glm` → `ollama`） |
| `anthropic_api_key` | None | Anthropic API Key |
| `kimi_api_key` / `glm_api_key` | None | Kimi、GLM Provider API Key |
| `openai_responses_api_key` | None | OpenAI Responses API / 中转站 API Key |
| `openai_responses_base_url` | None | Responses API 中转站地址（`wire_api="responses"`，如 `https://www.komapi.top/v1`） |
| `ollama_enabled` | False | 本地 Ollama 条目开关（OpenAI 兼容 `/v1`，显式 opt-in，无需 API Key） |
| `ollama_base_url` | `http://127.0.0.1:11434/v1` | Ollama OpenAI 兼容端点 |
| `ollama_model` | None | Ollama 模型名（启用时必填，否则 fail-fast） |
| `ollama_api_key` | None | Ollama 占位 key（缺省用 `"ollama"`；Ollama 不校验 key） |
| `deepseek_base_url` | None | DeepSeek API 基础 URL |
| `anthropic_base_url` | None | Anthropic 代理地址 |
| `kimi_base_url` / `glm_base_url` | None | Kimi、GLM API 基础 URL（缺省用内置端点 `api.moonshot.cn/v1` / `open.bigmodel.cn/api/paas/v4`） |
| `anthropic_prompt_caching` | True | Anthropic 提示词缓存（注入 cache_control 断点，FR-3；不兼容代理时关闭） |
| `routing_pools` | "" | 声明式路由池 JSON（任意 provider 条目多档池；改档位/角色/关键词无需改代码） |
| `routing_reasoning_continuity` | False | 推理链续接（**所有池的默认值**，单池可用 spec 的 `reasoning_continuity` 覆盖）：true 时「上一轮走了 pro 且思考痕迹仍在历史中」继续走 pro，否则只按当前请求命中关键词判定 |
| `anthropic_api_keys` | "" | Anthropic 多密钥池（逗号分隔） |
| `default_model` | `gpt-4o` | claude 条目的兜底模型 |
| `deepseek_model` / `kimi_model` / `glm_model` | `deepseek-v4-pro` / `kimi-k3` / `glm-5.3` | 各 Provider 默认模型（**仅该条目未出现在 `routing_pools` 时生效**；有池时模型由池的 `tiers` 决定，`--model` 亦被忽略并告警） |
| `openai_model` | `gpt-5.6-terra` | openai（Responses API）条目默认模型（声明 openai 池时由 `tiers` 决定） |
| `max_iterations` | 50 | Agent 循环最大迭代次数 |
| `max_context_tokens` | 512000 | 模型上下文窗口大小 |
| `max_output_tokens` | None | 单次输出 token 上限（None=不设；本地思考模型建议设） |
| `compression_threshold` | 0.8 | 上下文压缩触发阈值 |
| `context_strategy` | `compressor` | 上下文管理策略：`compressor`=原地摘要压缩（默认）/ `reset`=窗口重置（清窗后 resume 续跑；与 compressor 互斥） |
| `window_reset_threshold` | 0.6 | 窗口重置触发阈值（`context_strategy=reset` 时生效） |
| `retry_max_attempts` | 3 | 最大重试次数 |
| `retry_base_delay` | 1.0 | 重试基础延迟（秒） |
| `retry_max_delay` | 30.0 | 重试最大延迟（秒） |
| `skill_match_threshold` | 0.3 | 技能关键词匹配阈值（0.0–1.0） |
| `skill_max_auto_invoke` | 3 | 最多自动注入技能数 |
| `skill_max_auto_invoke_tokens` | None | 自动注入技能正文的总估算 token 预算（None 保持旧行为；超预算完整 Skill 跳过而不截断） |
| `skill_max_manual_load_tokens` | 8192 | `skill_load` 单个完整 Skill 的估算 token 上限（超限显式拒绝） |
| `context_files_enabled` | True | 是否自动加载项目上下文文件（分层扫描） |
| `context_files_max_bytes` | 32768 | 上下文文件字节预算；超预算时近端优先保留，被丢弃/截断者显式标注 |
| `context_files_user_level` | False | 是否纳入用户级 `~/.heagent/AGENTS.md`（默认关闭，避免全局文件静默影响每个项目） |
| `events_rollout_enabled` | False | 是否把每次 run 的事件落盘为 `.heagent/runs/<run_id>/rollout.jsonl`（默认关闭；内容含工具原始输出） |
| `memory_nudge_enabled` | True | 是否注入记忆保存提醒 |
| `memory_inject_max_bytes` | 98304 | 注入 `<memory>` 的字节预算（0=不限制）；超预算**从尾部倒装保留最新后缀**（2026-10-30 59-3 读序翻转，省略最旧前缀）并在块尾显式标注省略条数 + warning，文件本体不改动（`MEMORY.md` 是 append-only 且整份注入，无预算会无界增长） |
| `memory_archive_trigger_bytes` | 49152 | MEMORY.md 的 fact 总字节超此值时自动归档**最旧前缀**到 `archive/MEMORY-archive.md`（保留能装进此预算的最新后缀；0=禁用自动归档；2026-10-30 59-3 读序翻转后无头部钉住） |
| `memory_archive_min_interval_seconds` | 86400 | 自动归档的跨进程节流间隔（秒；0=每次都扫） |
| `skill_curator_stale_days` | 30 | `skill_curate` 未显式传 `days` 时的过期天数默认值 |
| `cron_enabled` | True | 是否启用 cron 调度 |
| `cron_tick_seconds` | 60 | 调度器检查间隔（秒） |
| `cron_push_enabled` | False | 是否把 cron 每轮终局推送到 `WS /api/notifications/ws`（Epic 58；默认关 ⇒ 中枢不建、端点不注册）。与 `cron_echo_to_terminal` **互相独立** |
| `cron_echo_to_terminal` | False | 是否在终端 stderr 回显一行 `[cron <job_id>] …`（Epic 58；单行、`\n` 折成 `⏎`、500 字符截断；不碰 stdout 的 JSONL 契约） |
| `dream_enabled` | False | 是否启用 dreaming（离线记忆巩固，opt-in；无人监督后台跑+联网+改持久记忆） |
| `dream_cron` | `0 3 * * *` | dream cron 触发表达式（构造期 fail-fast 校验，须 5 字段） |
| `dream_idle_minutes` | 30 | dream idle 触发阈值（分钟，距上次 run 结束；0=禁用 idle 触发） |
| `dream_max_iterations` | 20 | dreamer SubAgent 独立迭代预算（不复用全局 `max_iterations`） |
| `goal_max_iterations` | 20 | `/goal` 单步 SubAgent 最大迭代轮数（步骤可用 `max_iterations:` 覆盖） |
| `subagent_max_depth` | 3 | 子 Agent 委派嵌套深度上限（0=禁止委派；超限工具返回 `status=error`） |
| `subagent_max_iterations` | 20 | 嵌套子代理兜底迭代预算（角色未声明 `max_iterations` 时生效：显式参数 > 角色声明 > 本项） |
| `goal_checkpoint_mode` | `prompt` | `/goal` 检查点策略：自动继续或等待用户 |
| `goal_open_question_mode` | `block` | `/goal` 未决问题策略：阻塞或采用默认值 |
| `goal_workflow_skill` | `he-goal` | `/goal` 工作流包 id（包在自己 `meta.yaml` 里声明 `canonical_id`，按 id/别名解析） |
| `announce_progress` | True | 是否把「▶ 启动 / ✔ 完成 + 状态行」进度公告写到 stderr（false=静音） |
| `dream_session_lookback` | 5 | 预加载近期 session 个数（按 timestamp 降序） |
| `mcp_enabled` | True | 是否启用 MCP server 连接（门控，False 则跳过加载） |
| `mcp_config_path` | `.mcp.json` | MCP server 声明式配置文件路径 |
| `safety_blocked_tools` | `[]` | 工具名黑名单（**JSON 数组**，元素为正则片段、大小写不敏感）：命中即由 `SafetyGuard` 在执行前拦截，对内置 / shell / MCP 工具同等生效（默认空=不拦） |
| `sandbox_backend` | `auto` | Shell 沙箱后端：`auto`（探测 firejail，缺则回退 passthrough）/ `passthrough` / `firejail` / `winjob`（Windows 需显式指定）/ `docker`（container 档，Epic 53，需 Docker daemon） |
| `sandbox_firejail_path` | `firejail` | firejail 可执行文件路径（PATH 查找或绝对路径） |
| `sandbox_docker_image` | `heagent-sandbox:3.11` | 容器档镜像（Epic 53 期一）；换镜像=换容器内工具链，构建文件 `docker/sandbox/Dockerfile` |
| `sandbox_docker_digest` | `""` | 运行期 digest pin（Epic 53 审查修复批）：非空时首 run 前 inspect 校验本地 tag 的 repo digest，不符显性拒绝；构建后 `docker image inspect` 取值填入 |
| `sandbox_mode` | `workspace-write` | 权限档位：`read-only`（只放行只读工具，未知工具 fail-closed）/ `workspace-write` / `danger-full-access`（跳过围栏与凭证 deny 预检）；非法值回退并告警 |
| `sandbox_network` | False | 是否允许子进程出站；False 时 firejail 追加 `--net=none`、docker 追加 `--network=none`（即容器档默认隔离态，D2），True 时 docker 走 bridge（显式开启），其余后端记「网络隔离未生效」 |
| `run_retention_days` | 7 | `.heagent/runs/` 运行快照（`<run_id>.json` + 配套 `.lock` + `<run_id>/` 产物目录）保留天数；全新 run 启动时清理一次（0=禁用）。`pub/persist.py` 刻意保留 `.lock`（规避 unlink 竞态），本项是 runs 侧唯一回收时机 |
| `ledger_retention_days` | 7 | `.heagent/ledger/` 幂等记录保留天数；全新 run 启动时清理一次（0=禁用） |
| `prune_min_interval_seconds` | 900 | 过期清理的**跨进程节流**：距上次清理不足此间隔就跳过扫描（0=每次都扫）。短命 CLI 进程靠它省掉「每次启动重扫万级目录」 |
| `log_retention_days` | 14 | `logs/` 日志文件保留天数（CLI/GUI 启动时回收；0=禁用） |
| `session_retention_days` | 30 | `.heagent/sessions/` 会话文件保留天数（启动时按 mtime 回收；0=禁用） |
| `edit_snapshot_retention_days` | 7 | `.heagent/tmp/edit-snapshots/` 编辑快照保留天数（启动时回收 run 目录；0=禁用） |
| `sandbox_dir_retention_days` | 7 | `.heagent/sandboxes/<run_id>/` 沙箱会话目录保留天数（E40-D1：崩溃/SIGKILL 的 run 不会 teardown，由启动时回收**孤儿**目录；0=禁用。判活取「目录 + 直接子项」最新 mtime，故正在写的 run 不会被删；单趟有上限、失败记 warning） |
| `sandbox_enforce` | True | 探测到**真实**后端时自动把 `shell` 纳入沙箱工具集并授权当次 run（passthrough 下零行为变更） |
| `tokenizer` | `auto` | Token 计量后端：`auto`（有 tiktoken 用真实 encoding，否则启发式 + 在线校准）/ `estimate` / `tiktoken` |
| `sandbox_session_workspace` | False | 是否为每个 run 建立会话工作目录；CLI/GUI `--sandbox-session-workspace` / `--no-...` 可**双向**覆盖（E40-D4，三态：未传则跟随本项） |
| `sandbox_session_keep` | False | run 结束后是否保留会话目录；同上，CLI/GUI `--sandbox-session-keep` / `--no-...` 可覆盖 |
| `sandbox_env_allowlist` | `""` | 逗号分隔的 env 豁免变量名（如 `GITHUB_TOKEN`）：命中者不参与 `scrub_sensitive_env` 的敏感剥离；空=全剥离 |
| `sandbox_profiles` | `""` | JSON：profile 名 → firejail 参数表（如 `{"default": ["--seccomp", "--caps.drop=all"]}`），高级隔离参数由此声明、默认关闭；坏 JSON/坏条目告警丢弃 |
| `sandbox_tool_profiles` | `""` | JSON：工具名 → profile 名（per-tool 参数粒度），叠加进 `PolicyEngine.sandbox_profiles`；空=现状（缺省落 `default`） |
| `sandbox_memory_limit_mb` | 0 | 沙箱 shell 内存限额（MB；firejail `--rlimit-as` / winjob Job Memory / docker `--memory`）；0=关闭。触发=子进程被终止 → 非零退出码（显性失败） |
| `sandbox_cpu_seconds` | 0 | 沙箱 shell CPU 时间限额（秒；firejail `--rlimit-cpu` / winjob Process Time）；触发行为同上。⚠ docker 后端**无诚实映射**（`--cpus` 是速率上限非时间上限）——配置了只打提示、不生效 |
| `sandbox_nproc_limit` | 0 | 沙箱 shell 进程数限额（firejail `--rlimit-nproc` / winjob Active Process / docker `--pids-limit`）；触发行为同上。⚠ 语义不对称：firejail 侧按**真实 UID** 计数（非 per-sandbox），winjob 侧为 job 作用域 |
| `http_enabled` | `True` | 是否装配 HTTP listener（9101）；`False` = 不启动（仅 WS 或全关；全关时 `http-server` 命令拒绝启动，交互模式无网页入口） |
| `http_host` | `127.0.0.1` | HTTP 网页入口绑定地址；非回环值启动时日志记一条 `event=exposed` 且 stderr 打印一行告警（判定单点复用 `network/exposure.py`） |
| `http_port` | 9101 | HTTP 网页入口端口（1..65535；默认 9101） |
| `http_port_auto_find_attempts` | 10 | 端口被占用时自动**顺延**的尝试次数（`port+1…`）；**默认 10 = 开启**（2026-10-15 契约修订：多开实例不冲突；原默认 0 = fail-loud，源自 Epic 49 Story 49-2——hang 根因「显式端口被改写」已修，显式 `--port` 契约保留）。Windows 下探测 socket 不设 `SO_REUSEADDR`，与真实监听语义一致，避免占用探测失真。2026-09-27 加入 |
| `http_max_connections` | 16 | 同时打开的 HTTP 客户端连接上限（交给 Uvicorn `limit_concurrency`，超限连接被直接拒绝而非排队） |
| `http_max_subscribers` | 16 | **每 run** 的 SSE 订阅者上限（同一 run 的并发事件流；超限回 429 `rate_limited`）。与 WS 连接额度独立。 |
| `ws_enabled` | `True` | 是否装配 WS listener（单 listener，默认 9201）；`False` = 不启动 |
| `ws_host` | `127.0.0.1` | WS listener 绑定地址（Epic 56 D1：与 HTTP 完全分离的独立 server）。**按绑定地址 + `WS_LAN_NO_AUTH` 切三档**（D5 + Epic 72）：回环 = `local`（免认证）；非回环 + `WS_LAN_NO_AUTH=true` = `lan`（内网免认证，只接受私有地址字面量，启动打 `event=exposed listener=lan auth=none`）；其余非回环 = `external`（强制 token，启动打 `event=exposed listener=external auth=token`）；三档的边界地位见 §4.18 |
| `ws_port` | 9201 | WS 入口端口（1..65535）。四条端点（提交 `/api/runs/ws`、订阅 `/api/runs/{run_id}/ws`、旁路 `/api/cli/ws`、通知流 `/api/notifications/ws`）路径不变、端口 8766 → 9001 是 Epic 56 的**唯一 breaking change**（通知流是 Epic 58 新增，非迁移）；**默认值 2026-10-29 起由 9001 改为 9901**（9001 段常被本机其他程序占用，避免启动即顺延）；**2026-11-04 起由 9901 改为 9201**（本仓部署段，避开高频占用区） |
| `ws_max_connections` | 16 | **每 run** 的 WebSocket 订阅上限 + CLI 旁路 hub 的连接总额 + **提交端点的连接席位**（迁移自 `http_ws_max_connections`）；三处各自计数、同值同源。独立于 SSE 订阅池，超额在 accept 后收到 `rate_limited` 错误帧（检查+登记同一步） |
| `ws_shutdown_timeout` | 5 | WS server 关闭排空的等待上限（秒）：关既有订阅连接 → 停 listener |
| `ws_tls_cert_file` | None | 对外模式 TLS 的 PEM 证书路径（D4）。与 `ws_tls_key_file` **要么都给要么都不给**（半配即 `WsConfigError` / 命令级 exit 1）；配齐即 listener 走 `wss`。不配 = 明文，对外模式启动打 `event=plaintext_external` 告警 |
| `ws_tls_key_file` | None | 对外模式 TLS 的 PEM 私钥路径（同上） |
| `ws_cli_bypass_enabled` | False | **CLI 旁路订阅开关**（Epic 55，Epic 56 D7 起宿主 = WS server）：开启时 WS listener 注册 `WS /api/cli/ws`，把**终端里那一轮** run 的事件（文本增量 / 工具调用 / 终态）实时推给旁路订阅者。只读、跨轮次、不占运行名额、不写会话历史、没有 `cancel` 通道（终端独占 Ctrl+C / 双击 Esc）。**默认关**——开了等于让能连上该端口的进程看到终端 agent 的工具输出（可能含文件内容），边界地位见 §4.18。 |
| `ws_local_auth_enabled` | False | **本地强制认证开关**（2026-11-04 D5 修订）：True 时回环主 listener **也**强制 `Authorization: Bearer <token>`（含旁路端点 `/api/cli/ws`——旁路不再免认证）。开启前必须在 `~/.heagent/setting.md` 配 `WS_AUTH_TOKEN`，否则配置构造期拒绝启动（fail-closed，与对外模式同口径）。开启时该 listener 的前门由 Origin/Host 换成 token；本机消费者（console 的 run 订阅、观察脚本）都要带 token。非回环绑定时开关冗余（对外模式本就强制认证）。 |
| `http_max_inflight_runs` | 1 | **每项目**同时在途的网页 Agent 运行上限（MVP 单会话单运行；超限提交收 `run_conflict`） |
| `http_max_total_inflight` | 0 | **服务级**在途运行总额（跨项目共享）；0 = 不限 ⇒ 不设时全局上限 = 项目数 × `http_max_inflight_runs`；超限提交收 `total_inflight_limit`（2026-09-27 新增） |
| `http_max_request_bytes` | 394240 | 单个 JSON 请求体的字节上限（超限收 `request_too_large`）。默认 = `12 × MAX_PROMPT_CHARS(32768) + 1 KiB` 信封，**保证协议允许的最大 prompt 在任何客户端编码下都发得进来**（旧默认 65536 使中文约 2.18 万字就撞 413——2026-09-23 修复；三处默认值的关系由 `tests/network/test_http_protocol.py` 钉住） |
| `http_event_buffer_size` | 512 | 每个 run 的 SSE 事件环形缓冲条数（越过窗口的重连收 `resync_required`） |
| `http_run_history_size` | 64 | 已终结 run 记录的保留条数（淘汰后按其 id 订阅收 `unknown_run`） |
| `http_request_timeout` | 0 | 单次网页 Agent 运行的**总时长**硬上限（秒）；0 = 不限制（运维显式兜底闸门，2026-09-24） |
| `http_idle_timeout` | 300 | 单次网页 Agent 运行的**静默**上限（秒）：无事件且无在途工具才算卡死，按 `timed_out` 终结并释放名额；0 = 关闭 |
| `http_tool_inflight_timeout` | 3600 | 单个**在途工具**的最长在途时间（秒）：超过即按「工具卡死」终结该 run，文案 `run stalled: a tool has been in flight for over Ns`；0 = 关闭。**刻意不复用** `http_idle_timeout`——长 shell / 子代理期间同样没有事件，用静默阈值会误杀正常长调用（2026-09-27） |
| `http_shutdown_timeout` | 5 | 关闭时「停止接收 → 终结在途 run → 关订阅 → 关 listener」全过程的等待上限 |
| `http_console_write_enabled` | False | 网页控制台的**配置写入通道**开关（Story 50-5）。关闭时配置面全只读，且网页**无法通过任何请求**打开它自己；开启渠道只有启动配置（系统环境变量 / 项目 `.env` / 全局 `.env`），开启时入口层 stderr + 日志双通道高亮告警。**开启即等于任何能连上该端口的人都能改项目 `.env`**（边界地位见 §4.18；机制与默认值见 [network.md](network.md) 4.17） |
| `http_console_projects_file` | None | 项目注册表落点覆盖（缺省 `<服务启动工作区>/.heagent/console/projects.json`）。需要机器级共享时显式指向 `~/.heagent/projects.json`；缺省**不写用户 home** |
| `approval_tools` | `""` | 需要交互审批的工具名列表 |
| `hooks_enabled` | False | 是否启用 `.heagent/hooks.json` |
| `plan_mode` | False | 是否启用只读计划模式 |
| `model_pricing` | `""` | 模型价格表 JSON `{"<model>": {"input": 单价, "output": 单价}}`（$/M token）；空=不显示成本 |
| `log_dir` | `logs` | 日志文件目录（相对 cwd），每次启动新建 `heagent-<时间戳>.log` |
| `log_level` | `INFO` | stderr 控制台日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `log_file_level` | None | 文件日志级别；未设（None）时回退到 `log_level` |
| `log_format` | `text` | 日志行格式：`text`（人读，与历史输出逐字一致）/ `json`（单行 JSON：`timestamp` 带时区偏移、`extra=` 注入落 `context`、异常落 `exc_info`）。实现单点 `pub/log_config.py`，CLI / GUI / HTTP 三个装配点共用（Epic 65） |
| `debug_mode` | False | 调试模式（`DEBUG_MODE`，Epic 65）：日志级别强制 `DEBUG`（暴露既有的入参/中间量插桩，压过 `LOG_LEVEL`）+ CLI 错误出口在既有三段之后追加 `Traceback (DEBUG_MODE=true):` 段；默认关，**不改任何安全面**（审批 / 沙箱 / plan mode 各自独立） |
