# Epic 50 架构脊柱：网页控制台

- 建立：2026-09-23
- 状态：**冻结（freeze）**——本文件是本周期的不变量清单。实现与 story 必须服从；要改先改本文件并说明理由。
- 输入：`brief.md`（产品）、`docs/frame.md`（架构权威）、`epics.md`（story 拆分）、以及 step-01 的代码级侦察（每条事实均带行号）。
- 上游：Epic 49（HTTP 网页访问周期）交付的 `network/http_server.py` + `cli_http.py`。

## 0. 一句话

把「一个进程 = 一个目录 = 一次性聊天页」升级为**本机多项目控制台**：工作区是一等参数，
会话持久化到项目状态根，配置有效值与来源可视化，配置写入经白名单 + 保真写 + 备份 + 冲突检测 + 审计的闸门，
且**写通道永远不是安全边界**。

## 1. 不变量（违反即架构错误）

| # | 不变量 | 依据 / 代价 |
|---|---|---|
| I1 | **网络层不认识项目**。`network/` 不得导入 `config`（既有延迟导入除外）、`agent`、`engine`、`tools`、`projects`；项目 / 会话 / 配置能力一律经**注入的 handler 协议**进入。 | Epic 49 的 NFR2 延续；测试 `tests/test_architecture_contracts.py` 钉死 |
| I2 | **状态根只有一个来源**：`WorkspacePaths`。除入口层兜底（参数缺省 → 进程 cwd）外，禁止新增 `os.getcwd()` 装配点与重复路径字符串常量。 | 侦察发现同一条「工作区」有 6+ 处独立取值（`cli.py:219/243/263/313/460`、`cli_http.py:197`、`cli_tcp.py:170`），且 `housekeeping.py:229` 与 `SessionStore` 默认值重复拼串 |
| I3 | **项目切换不修改进程状态**：不 `os.chdir()`，不改 `os.environ`，不依赖服务端「当前项目」可变变量。项目身份经每请求参数显式传递。 | brief §6.7、§7 D2 |
| I4 | **配置写入只改项目 `.env`**，全局 `~/.heagent/.env` 永久只读。 | brief §7 D1（全局误改影响所有项目） |
| I5 | **写白名单 fail-closed**：可写项是显式允许子集，不是「排除法」。凭证、监听面、沙箱/执行后端、进程拉起开关、路径类、控制台自身开关一律排除。 | brief §6.3；侦察给出的 9 类排除表 |
| I6 | **候选配置必须先能被 `Settings(_env_file=<候选临时文件>)` 成功构造**，否则拒绝写入。 | 「写坏 = 整个进程起不来」（侦察实测：list 字段用逗号分隔直接 `SettingsError`） |
| I7 | **保真写**：只替换目标行；其它行的字节、EOL（CRLF/LF）、BOM 状态、注释与空行保持不变。 | 项目 `.env` 实测 77 行全 CRLF、10 处行内注释、1 个重复键 |
| I8 | **写前备份 + 写后回读校验**；失败自动恢复原内容并显式报告。备份按敏感配置处理，网页不可下载。 | brief §6.6 |
| I9 | **凭证零回传**：响应、错误、日志、审计都不含明文；掩码固定位数，不反映真实长度。 | brief §6.2 |
| I10 | **生效语义 = 下一次 run**。当前在途运行保持旧快照；UI 不得声称立即生效。 | brief 硬结论 (b)、§6.9；`ResolvedRuntimeConfig` 冻结语义 |
| I11 | **并发写显式冲突**：同一会话文件被外部修改 → 409，不静默覆盖；在途运行期间禁止删除会话与移除项目。 | brief §6.8；`SessionStore.save` 现状是 last-write-wins |
| I12 | **默认全只读**：`HTTP_CONSOLE_WRITE_ENABLED=False`（默认）时，配置面只读且**网页无法自行开启**。 | brief §7 D4 |
| I13 | **无回归**：CLI / GUI / TCP / Epic 49 的全部 HTTP 端点行为不变；新增端点缺省不注册。 | brief §9.9、epics.md NFR-10 |
| I14 | 内部状态读拒集合**从同一 `WorkspacePaths` 派生**，并覆盖全部运行态子目录（`sessions`/`ledger`/`runs`/`memory`/`skills`/`user`/`cron`/`checkpoints`/`sandboxes`/`tmp/edit-snapshots`/`console`/`backups`）。 | 侦察新查出：`tools/path_safety.py:255` 只 deny 5 个子目录，其余裸奔 |

## 2. 模块落位与依赖

```
exceptions  types  config  persist  roles  frontmatter  safe_logging   ← 顶层底层
      ↑         ↑        ↑        ↑
      │   workspace.py   envfile.py   config_catalog.py   projects.py    ← 本周期新增（顶层）
      │         ↑            ↑              ↑                ↑
      └─ providers ─ tools ─ context ── engine ── agent ── cli_console.py（新增，入口层）
                                                    ↑
                                       cli_http.py / cli.py / gui / cli_tcp.py
```

| 新增模块 | 职责 | 允许依赖 | 禁止依赖 |
|---|---|---|---|
| `src/heagent/workspace.py` | `WorkspacePaths`（Pydantic）：给定工作区根，派生全部运行态路径 | stdlib | 任何 heagent 模块 |
| `src/heagent/envfile.py` | `.env` 行级**保真**读写：定位键、替换/追加值、EOL/BOM 保真、指纹(sha256)、备份 | `persist` | `config`、`engine`、`agent`、入口层 |
| `src/heagent/config_catalog.py` | 配置目录：分组、可写白名单、只读原因、凭证识别、**四层来源求解** | `config`、`types` | `engine`、`agent`、入口层 |
| `src/heagent/projects.py` | 项目注册表：`ProjectEntry` + CRUD + 路径规范化 + 原子持久化 | `persist`、`workspace` | `engine`、`agent`、入口层 |
| `src/heagent/cli_console.py` | 控制台编排（入口层）：注册表 + 每项目运行时池 + 全局 run 索引 + handler 工厂 | 任意入口层可用的模块 | 被 `network/` 导入 |
| `src/heagent/network/http_console_protocol.py` | 网络层看到的**控制台协议**（Pydantic 请求/响应模型 + `ConsoleHandler` Protocol） | stdlib、Pydantic | 任何运行时模块 |

`network/http_server.py` 只新增：路由骨架 + 注入点。`build_http_app(..., console=None)`；`console is None`
时**不注册**任何控制台路由（向后兼容，I13）。

## 3. 工作区模型

### 3.1 `WorkspacePaths`（单一来源）

```python
class WorkspacePaths(BaseModel):          # frozen
    root: Path                            # 工作区根（项目根）
    # 全部由 root 派生，禁止外部拼字符串：
    state_dir        = root/".heagent"
    sessions         = state_dir/"sessions"
    skills           = state_dir/"skills"
    memory_file      = state_dir/"memory"/"MEMORY.md"
    profile_file     = state_dir/"user"/"USER.md"
    cron_file        = state_dir/"cron"/"jobs.json"
    runs             = state_dir/"runs"
    ledger           = state_dir/"ledger"
    checkpoints      = state_dir/"checkpoints"
    sandboxes        = state_dir/"sandboxes"
    edit_snapshots   = state_dir/"tmp"/"edit-snapshots"
    console_dir      = state_dir/"console"          # 审计
    config_backups   = state_dir/"backups"          # 配置备份（2026-09-24 评审校正：原写 "backups"/"env"，
                                                     #   代码 workspace.py 与 path_safety 的 deny 集都按 "backups"）
    projects_file    = console_dir/"projects.json"  # 可被 HTTP_CONSOLE_PROJECTS_FILE 覆盖
```

> **作用域警告（评审 F3，2026-09-24）**：`projects_file` **只对「服务启动工作区」有意义**——项目注册表是
> **服务级**产物（脊柱 §4），而 `WorkspacePaths` 是**项目级**的。对已登记的其它项目 `P`，
> `WorkspacePaths(P.root).projects_file` 指向 `P/.heagent/console/projects.json`（一个**不存在也不该存在**的
> 第二个注册表）。⇒ 注册表路径**只能**由控制台从「启动工作区 + `HTTP_CONSOLE_PROJECTS_FILE` 覆盖」解析一次，
> 禁止从任意项目的 `WorkspacePaths` 取；实现须配一条测试钉住这一点。

**口径修正（顺带闭合侦察发现的漂移）**：`engine` 围栏基址在构造期冻结，而 `AgentLoop.context_dir`
过去每 run 重读 `os.getcwd()`（`cli_http.py:207-214` → `cli.py:263`）。改造后两者**同源取自绑定工作区**，
`os.chdir()` 不再造成分叉。

### 3.2 状态根落位现状（改造清单）

| Store | 默认（改造前） | 改造后 |
|---|---|---|
| `SessionStore` | `.heagent/sessions`（`context/session.py:83`） | `paths.sessions` |
| `SkillStore` | `.heagent/skills`（`memory/skill_store.py:47`） | `paths.skills` |
| `FactStore` | `.heagent/memory/MEMORY.md`（`memory/facts.py:41`） | `paths.memory_file` |
| `ProfileStore` | `.heagent/user/USER.md`（`memory/profile.py:21`） | `paths.profile_file` |
| `JobStore` | `.heagent/cron/jobs.json`（`cron/jobs.py:36`） | `paths.cron_file` |
| `RunStore` | `.heagent/runs`（`engine/store.py:91`） | `paths.runs` ← **校正 C1**：`default()` **已**接受 `workspace_root=`，缺的是把它接到这两个 `init` 字段（`engine/container.py:44-45` 走 `field(default_factory=…)` 无参构造） |
| `ExecutionLedger` | `.heagent/ledger`（`engine/ledger.py:122`） | `paths.ledger` ← 同上 |
| `WorkflowCheckpointStore` | `.heagent/checkpoints`（`engine/checkpoint.py:85`） | `paths.checkpoints` |
| 编辑快照 | `workspace_root()/.heagent/tmp/edit-snapshots`（`tools/edits.py:136`） | `paths.edit_snapshots` |
| 沙箱会话目录 | `engine/container.py:344-348` | `paths.sandboxes` |

所有既有 store **已接受路径形参**（`base_dir` / `path`），改造面集中在**装配点传参**；
`RunStore` / `ExecutionLedger` 是 `EngineContainer` 的 `init=True` 字段（`engine/container.py:48-49`），
只需让 `default()` 暴露并派生。

### 3.3 内部状态读拒集合（I14）

`build_internal_state_dirs()` 改为接受工作区根（缺省回退进程 cwd + home，保持既有调用方语义），
返回集合从 `WorkspacePaths` 派生 ⇒ 一次改动同时覆盖 12 个子目录。这是**行为收紧**，
必须带负向验证：回退收紧项 → 新测试精确变红。

## 4. 项目注册表

- **身份** = 规范化后的绝对路径。规范化规则：`expanduser()` → `resolve()` → 去尾分隔符；Windows 下
  大小写不敏感比较（同路径不同写法不得产生两个条目）。
- **项目 id**：稳定短 id（`p` + 8 位 hash）；默认项目固定为 `"default"`。
- **默认项目**：服务启动工作区，**隐式存在、不持久化、不可移除**（`project_not_removable`）——
  这是 Epic 49 `/api/runs` 等既有端点的兼容锚点（I13）。
- **落点**：`<服务启动工作区>/.heagent/console/projects.json`，可被 `HTTP_CONSOLE_PROJECTS_FILE` 覆盖
  （需要机器级共享时显式配置为 `~/.heagent/projects.json`）。默认不写用户 home。
- **登记语义**：只登记**已存在**的目录（brief §7 D3）；不存在 / 非目录 → `invalid_project_path`，
  **不创建**任何目录。目录失效（登记后被删）→ 列表中标 `available=false`，对该项目发起运行得到显式错误，
  **不自动移除**。
- **移除语义**：只删注册表条目，目录与该项目 `.heagent/` 数据逐字节保留（brief §9.8）。
- **上限**：条目数上限（常数），超限拒绝。
- **fail-soft**：注册表 JSON 损坏 → WARNING + 空注册表继续（不阻断 HTTP 服务，与 Z-D12 的 fail-soft 立场一致）。

## 5. HTTP API 形状（冻结）

### 5.1 既有（形状不变，语义 = 默认项目）

`GET /api/health` · `GET /` · `GET /{asset}` · `POST /api/runs` · `GET /api/runs/{run_id}/events` ·
`DELETE /api/runs/{run_id}` · `GET /api/session`

`run_id` 在**服务进程内全局唯一**（uuid4），由控制台维护全局 `run_id → project` 索引，
因此既有按 `run_id` 定位的端点在多项目下依然无歧义。

### 5.2 新增

| 方法 + 路径 | 语义 |
|---|---|
| `GET /api/projects` | 列表（`id`/`name`/`path`/`available`/`last_opened_at`/`is_default`），按最近打开降序 |
| `POST /api/projects` | 登记已有目录 `{path, name?}` |
| `PATCH /api/projects/{id}` | 重命名显示名 `{name}` |
| `DELETE /api/projects/{id}` | 移除登记（**不删目录**）；缺 `?confirm=true` → `confirm_required`；在途运行 → 拒绝；`default` → 拒绝 |
| `GET /api/projects/{id}/sessions` | 会话列表（`session_id`/`title`/`message_count`/`updated_at`） |
| `POST /api/projects/{id}/sessions` | 新建会话 `{title?}` |
| `GET /api/projects/{id}/sessions/{sid}` | 消息列表（与 `/api/session` 同构） |
| `PATCH /api/projects/{id}/sessions/{sid}` | 重命名会话 `{title, fingerprint?}` |
| `DELETE /api/projects/{id}/sessions/{sid}` | 删除会话（需 `?confirm=true`） |
| `POST /api/projects/{id}/runs` | 在项目内创建运行 `{prompt, session_id?}` |
| `GET /api/projects/{id}/config` | 有效值 + 来源 + 可写性（凭证仅掩码） |
| `PUT /api/projects/{id}/config` | 写入 `{changes:[{key,value}], fingerprint}` |

### 5.3 错误码（`HttpErrorCode` 闭集扩展）

新增稳定码：`unknown_project` · `invalid_project_path` · `project_unavailable` · `project_not_removable` ·
`project_busy` · `project_limit_reached` · `unknown_session` · `invalid_session_id` · `session_conflict` ·
`session_busy` · `confirm_required` · `write_disabled` · `field_not_writable` · `invalid_value` ·
`config_conflict` · `config_write_failed` · `loopback_required`。

错误信封形状不变（`{"error":{"code","message"}}`），文案经既有 `sanitize_message`。

**已裁定（D1，2026-09-24）**：**新增 `session_unreadable`** —— 用于区分「会话文件损坏 / 不可解析」与
「空会话」（`SessionStore.load` 现会静默把损坏当空，`context/session.py:131-133`）。理由：与「闭集里新增语义
要加成员」的原则一致，且与 `session_conflict` 语义不重叠（冲突 = 版本不符；不可读 = 无法解析）。
⇒ 本节实际新增 **18** 个成员（下表 17 + `session_unreadable`）。

## 6. 会话与运行绑定

- 每项目一个**项目运行时**（`ProjectRuntime`）：持有 `WorkspacePaths` + 该项目专属的
  `EngineContainer`（围栏与状态根都指向项目根）+ `SkillStore`/`FactStore`/`ProfileStore`/`soul` +
  `SessionStore` + provider + `HttpRunService`（会话投影 / SSE 缓冲 / 在途名额）。
  ⇒ 跨项目**零共享可变状态**（`HttpRunService` 原有语义按项目复用）。

**并发口径（D9 裁定，2026-09-24；原为评审 F4）**：`max_inflight_runs` 是 **service 级**名额
（`network/http_server.py:150,386` 用 `self.config`），而每个项目各持一个 `HttpRunService` ⇒
**同一时刻的在途运行上限 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`**。默认值下（项目上限 32、单项目 1）
⇒ **最多 32 个并发 run**。

- 这是**有意采纳**的语义：多项目并行是网页控制台的一等能力（项目 A 在跑时切到 B 也能起跑）。
- 代价按项目**线性放大**：每项目一套 `EngineContainer` / 事件缓冲（`HTTP_EVENT_BUFFER_SIZE`=512）/
  run 历史（`HTTP_RUN_HISTORY_SIZE`=64）/ SSE 订阅、以及真实 LLM 并发、沙箱进程与磁盘写入。
- **每项目内部语义不变**：单运行约束、会话在途保护、SSE 缓冲上限、run 历史上限、`.env` 写入闸门
  一律按项目各自生效；跨项目不共享在途名额、不做全局调度。
- **已知缺口（如实登记）**：**没有全局并发上限**——登记接近上限的项目数时资源占用线性上升。
  是否需要全局软上限（如 `HTTP_CONSOLE_MAX_TOTAL_INFLIGHT`）留作后续，写入 `docs/frame.md` 五 与台账。
  另注意：`HTTP_MAX_CONNECTIONS` 仍由 Uvicorn `limit_concurrency` 承担，且**不随项目数放大** ——
  多项目并行时连接层可能先于运行层成为瓶颈（属既有限制面的延续）。
- **运行绑定会话**：`POST .../runs` 携带 `session_id`（缺省 = 该项目「当前会话」，无则新建）。
  run 装配把 `session=<该项目的 SessionStore>` 与 `session_id` 传入 `AgentLoop`（此前是 `session=None`，
  这是 Epic 49 不落盘会话的根因）。
- **会话标题**：派生自主对话区首条用户消息（截断 + 折叠空白）；重命名写回会话文件的可选 `title` 字段
  （**不改** `messages`，避免污染 CLI 读取路径）。`title` 缺省时退回派生值。
- **冲突检测（增量）**：`SessionStore.save(..., expected_version: int | None = None)`；
  磁盘 `version` 与期望不符 → 抛 `SessionConflictError`。Web 侧传期望版本；CLI 侧不传 ⇒ 行为不变（I13）。
- **在途保护**：会话归属某个在途 run 时，`DELETE` 会话返回 `session_busy`；项目有在途 run 时
  `DELETE /api/projects/{id}` 返回 `project_busy`。

## 7. 配置来源求解（`config_catalog.py`）

**四层，自下而上覆盖，记录最后写入者**（已实测可行）：

```python
layers = [
    ("default",     {name: field.default for name, field in Settings.model_fields.items()}),
    ("global_env",  DotEnvSettingsSource(Settings, env_file=GLOBAL_CONFIG_FILE)()),
    ("project_env", DotEnvSettingsSource(Settings, env_file=<项目工作区>/.env)()),   # 不是进程 cwd！
    ("system_env",  EnvSettingsSource(Settings)()),
]
```

六个**必须处理**的坑（侦察实测，逐条有探针证据）：

| # | 坑 | 处理 |
|---|---|---|
| 1 | 来源层返回**原始字符串**（`'true'` ≠ `True`） | 来源判定只看「键是否出现」；展示值一律取自 `Settings` 实例 |
| 2 | 来源类能看见**未知键**并转小写 | 未知/拼错键单列，标「不生效」，不并入有效值 |
| 3 | 文件缺失被静默跳过 | 先 `is_file()` 探测，区分「来源=默认」与「文件不存在」 |
| 4 | 相对路径按**进程 CWD** 解析 | 项目 `.env` 路径一律由 `WorkspacePaths` 显式给出（这正是 I2 的动机之一） |
| 5 | 同文件**重复键后者胜** | 展示有效值按后者；写入时定位**最后一个**匹配行并在响应中提示重复 |
| 6 | 值里的行内注释被剥离（`#` 前有空白时） | 展示剥注释后的值；写回时不得把注释当值、不得吞掉注释 |
| 7 | **空值行整条消失**（`KEY=` → 该键不出现在任何层）**（校正 C5）** | 必须区分「文件里有该键但为空」与「文件里没有该键」，否则面板会把「显式置空」谎报成「来源 = 默认」 |

**键名口径（校正 C6）**：`Settings.model_fields` 的键是**小写字段名**（`max_iterations`），env 键是大写；
`Settings` 零 alias ⇒ 110 字段 ↔ 110 env 键为双射（实测无碰撞）。白名单一律以**大写 env 键**表达，
映射到字段集时用 `.upper()`；**不要**写 `Settings.model_fields["MAX_ITERATIONS"]`（会 miss）。

**注意**：项目 `.env` 的解析必须与运行期口径一致 —— 运行期 `Settings` 用 `env_file=[global, ".env"]`（进程 cwd 相对）。
多项目下项目 `.env` 不等于进程 cwd 的 `.env`，因此**项目运行时的配置解析必须显式传 `_env_file`**
（`Settings(_env_file=[global, <project>/.env])`），否则「项目的配置」会退化为主进程 cwd 的配置。
这是本周期最容易踩错的一点，必须有专门测试钉住。

## 8. 配置写入通道

**流水线（10 步执行 + 1 项生效语义；顺序固定，任一步失败即拒绝且文件不变）：**

1. 闸门：`HTTP_CONSOLE_WRITE_ENABLED`（默认 False）→ 否则 `write_disabled`。
2. 来源：仅接受本机回环来源 → 否则 `loopback_required`。
3. 键：必须在**显式白名单**内**且不得被系统环境变量提供**（后者 ⇒ `field_not_writable`；
   该判定与 50-4 的 `writable=false` **同一求解器、同一常量**，不得只在 UI 层拦）→ 否则 `field_not_writable`。
4. 值：类型/范围/枚举/JSON 由 pydantic 复验；`ROUTING_POOLS` 额外用既有池解析校验 →
   否则 `invalid_value`（含字段级原因）。
5. 冲突：客户端指纹 ≠ 当前文件 sha256 → `config_conflict`。
6. 候选：在当前内容上做**行级替换/追加** → 写临时候选文件 → `Settings(_env_file=候选)` 构造成功才算通过。
7. 备份：当前文件复制到 `paths.config_backups`（带时间戳 + 指纹前缀），条目数上限内。
8. 写入：`persist.atomic_update_text(项目 .env, ...)`（跨进程锁贯穿读改写）。
9. 回读：重新读文件 + 解析校验 + 指纹比对 → 不符则**恢复备份**并 `config_write_failed`。
10. 审计：追加一条 JSONL 到 `paths.console_dir/audit.jsonl`（键名 + 前后哈希/长度 + 结果，**无值**）。
11. 语义：标记该项目运行时**配置代（generation）已过期**；下一次 run 用新解析的快照，
    在途 run 继续用旧快照对象（I10）。

**白名单 v1（显式，fail-closed）**——分组供 UI 展示：

- 模型：`DEFAULT_MODEL`、`DEEPSEEK_MODEL`、`KIMI_MODEL`、`GLM_MODEL`、`OPENAI_MODEL`、`OLLAMA_MODEL`
- 路由：`ROUTING_POOLS`（JSON + 池条目名校验）、`ROUTING_REASONING_CONTINUITY`
- 迭代与限额：`MAX_ITERATIONS`、`GOAL_MAX_ITERATIONS`、`SUBAGENT_MAX_ITERATIONS`、`SUBAGENT_MAX_DEPTH`、
  `MAX_OUTPUT_TOKENS`、`SHELL_TIMEOUT`、`ANNOUNCE_PROGRESS`
- 上下文：`MAX_CONTEXT_TOKENS`、`COMPRESSION_THRESHOLD`、`WINDOW_RESET_THRESHOLD`、`CONTEXT_STRATEGY`
  （枚举限定 `compressor|reset`）、`TOKENIZER`、`CONTEXT_FILES_ENABLED`、`CONTEXT_FILES_MAX_BYTES`、
  `CONTEXT_FILES_USER_LEVEL`
- 记忆与技能：`MEMORY_NUDGE_ENABLED`、`MEMORY_INJECT_MAX_BYTES`、`SKILL_MATCH_THRESHOLD`、
  `SKILL_MAX_AUTO_INVOKE`、`SKILL_MAX_AUTO_INVOKE_TOKENS`、`SKILL_MAX_MANUAL_LOAD_TOKENS`、
  `SKILL_CURATOR_STALE_DAYS`
- 保留期：`LEDGER_RETENTION_DAYS`、`RUN_RETENTION_DAYS`、`LOG_RETENTION_DAYS`、`SESSION_RETENTION_DAYS`、
  `EDIT_SNAPSHOT_RETENTION_DAYS`、`SANDBOX_DIR_RETENTION_DAYS`、`PRUNE_MIN_INTERVAL_SECONDS`
- cron 频率：`CRON_TICK_SECONDS`
- **行为 / 观测 / 日志 / 传输（D3 裁定新增 8 键，2026-09-24；原为「未分类」）**：
  `ANTHROPIC_PROMPT_CACHING`、`EVENTS_ROLLOUT_ENABLED`、`OLLAMA_ENABLED`（纯 bool）；
  `LOG_LEVEL`、`LOG_FILE_LEVEL`（需枚举限定）；`RETRY_MAX_ATTEMPTS`、`RETRY_BASE_DELAY`、`RETRY_MAX_DELAY`（需补上界）

> **开放弱校验键的强制前提（校正 C5/新发现）**：I6 的「候选能被 `Settings(_env_file=候选)` 构造成功」对
> **弱校验字段是空门**——实测 `retry_*` 只有下界（`Ge(ge=1)` / `Ge(ge=0.0)`，无上界）、`LOG_LEVEL` 是
> 自由 `str`（无 metadata）。⇒ 上述 5 个非 bool 键**必须**额外走字段级校验（枚举 / 上界），
> 否则写通道会变成「挂死 / 无限重试」旋钮。
> 上界取值（写通道侧，不改 `Settings` 定义）：`RETRY_MAX_ATTEMPTS ≤ 10`、`RETRY_BASE_DELAY ≤ 60`、
> `RETRY_MAX_DELAY ≤ 600`；`LOG_LEVEL` / `LOG_FILE_LEVEL` ∈ `{DEBUG, INFO, WARNING, ERROR, CRITICAL}`（空 = 回退）。

**显式排除（只读，UI 显示原因）**：

| 组 | 键（模式） | 原因 |
|---|---|---|
| 凭证 | `*_API_KEY`、`*_API_KEYS` | 永不回传、永不写入（brief §6.2） |
| 监听面 | `HTTP_*`、`TCP_*` | 改暴露面 / 需重启服务（brief §6.9） |
| 沙箱与执行后端 | `SANDBOX_*`（**除 `SANDBOX_DIR_RETENTION_DAYS`，见 D2**） | 改 OS 级隔离姿态；`SANDBOX_FIREJAIL_PATH` 等价任意程序执行 |
| 进程拉起 | `HOOKS_ENABLED`、`MCP_ENABLED`、`MCP_CONFIG_PATH`、`CRON_ENABLED`、`DREAM_ENABLED` | 新增执行面 / 无人监督后台执行 |
| 路径类 | `LOG_DIR`、`GOAL_WORKFLOW_SKILL` | 任意宿主路径 / 加载任意工作流 |
| 安全闸门 | `SAFETY_BLOCKED_TOOLS`、`APPROVAL_TOOLS` | 降低 defense-in-depth 等于自我削权 |
| 出站重定向 | `*_BASE_URL`、`ACTIVE_PROVIDER` | 把凭证送往往意端点（准凭证外泄通道）、SSRF 面 |
| 运行语义（v1 排除） | `PLAN_MODE`、`MODEL_PRICING`、`GOAL_*_MODE` | 静默改变行为，非「配置展示」范围 |
| 控制台自身 | `HTTP_CONSOLE_WRITE_ENABLED`、`HTTP_CONSOLE_PROJECTS_FILE` | 写入面不得给自己解锁（I12） |
| 未知键 | 任何不在 `Settings.model_fields` 的键 | brief §6.3 |
| **dream 参数（D3 裁定，2026-09-24）** | `DREAM_CRON`、`DREAM_IDLE_MINUTES`、`DREAM_MAX_ITERATIONS`、`DREAM_SESSION_LOOKBACK` | 仅在 `DREAM_ENABLED`（已排除、只读）为真时生效 ⇒ v1 开放**零收益**，却把「无人监督后台执行」的强度旋钮交出去 |

**排除规则之间的优先级（R-c 收紧，2026-09-24）**：同一键命中**多条**排除规则时（实测只有 `HTTP_CONSOLE_*`：
同时命中 `HTTP_*` 与「控制台自身」），取**显式行 > 模式行**；同型时按**表内顺序取首条**。
该口径决定 UI 显示哪一条 `read_only_reason`，由 50-4 的测试钉住。

**优先级（D2 裁定，2026-09-24）**：`SANDBOX_DIR_RETENTION_DAYS` 同时出现在白名单与 `SANDBOX_*` 排除模式
（**实测冲突**）。裁定 = **显式白名单优先于模式排除**，并把 `SANDBOX_*` 的模式语义收窄为「执行姿态键」而非宽 glob；
该裁定必须体现在 `config_catalog.py` 的常量与测试里，且与 50.4 的展示口径一致。

**划分完整性（D3 裁定后实测；数字于 2026-09-24 评审校正为 111 / 65）**：**111 = 46 白名单 + 65 排除**（65 = 61 模式命中 + 4 个 dream 显式；`4f67397` 新增 `HTTP_IDLE_TIMEOUT` 后字段数 110 → 111），
**残留 0**；白名单 46 键**全部**存在于 `Settings`。完备性由 50-4 的 AC9 测试钉住（白名单 ∪ 排除 = 全字段）。

## 9. 安全立场

- 网页入口**无认证、无 TLS、非安全边界**（沿用 Epic 49）。写通道存在 ⇒ 「任何能连上该端口的人都能在
  已开启开关时改项目 `.env`」。UI 必须常驻显示该事实（UX-DR6），文档必须同样声明。
- 同源防线复用 Epic 49（Host / Origin / 拒绝 forwarded）；**写通道额外要求本机回环来源**（brief §6.5）。
- 凭证掩码：固定位数（如 `****` + 前后各 0～2 字符？——否决；**冻结为定长掩码**，不含任何原文字符），
  只回 `configured` 布尔。**短密钥不得因展示而暴露全文**。
- 备份目录、审计目录进入内部状态读拒集合（I14），且备份不提供任何网页下载端点。
- 本项目登记 = 把任意本机目录交给网页当工作区。这是**既有限制面的延伸**（CLI 也由 cwd 决定），
  必须在 UI 与文档声明「网页不是权限边界」。

## 10. 测试策略

- **网络层**：既有 `tests/network/test_http_server.py` / `test_http_run_service.py` 保持通过；
  新增控制台路由测试走**注入的假控制台**（不装 starlette 真实依赖？——starlette 属 `http` extra，
  测试已有 skip 机制，沿用既有做法）。
- **控制台编排**：以 `StubProvider` + 临时工作区目录测跨项目隔离（A 项目写入不得出现在 B）。
- **保真写**：构造 CRLF/LF/BOM/注释/重复键/无末行换行的样本文件，逐字节断言未修改行不变。
- **来源求解**：`monkeypatch.setenv` + 临时 `.env` 文件构造四层，逐项断言来源。
- **负向验证（纪律）**：去掉白名单过滤、去掉指纹校验、去掉备份、把备份目录移出 deny 集合、
  回退 `build_internal_state_dirs()` 收紧项 —— 对应测试**逐条必须变红**。
- **不伪造**：story 里的验证数字必须先跑命令再落笔。
- 覆盖率门槛 87%（`pyproject.toml` 已 omit `gui/` 与 CLI 交互层；`cli_console.py` 若属交互层需评估是否 omit，
  **默认不 omit**，靠测试覆盖）。

## 11. 兼容策略

| 面 | 策略 |
|---|---|
| 既有 HTTP 端点 | 形状不变，语义 = 默认项目（服务启动工作区）；`console is None` 时不注册新路由 |
| `HttpAgentHandler` | 演进为「单项目运行时」，新增 `workspace_root` 形参（缺省 = 进程 cwd，行为不变） |
| `SessionStore.save` | 新增**可选** `expected_version`；不传 = 现状 |
| `build_internal_state_dirs()` | 新增可选工作区参数；缺省 = 现状（cwd + home） |
| `EngineContainer.default()` | 新增可选状态根形参；缺省 = 现状 |
| CLI / GUI / TCP | 不改变装配语义（各自回退 cwd），仅改为经 `WorkspacePaths` 派生，去掉重复字符串 |
| `Settings` | 新增 2 键（`HTTP_CONSOLE_WRITE_ENABLED`、`HTTP_CONSOLE_PROJECTS_FILE`），**必须同步 `.env.example`**（既有断言覆盖全部字段） |

## 12. 不在本周期（范围边界）

多用户 / 账号 / 权限 / TLS / 反向代理 / 公网暴露；运行中热切换模型或工具策略；MCP 管理 UI；
审批 UI；删除项目目录；Git 操作与文件浏览器；创建项目目录；浏览器读写任意宿主文件；
SSE 事件全量持久化；服务重启后续跑中断任务；跨项目共享在途名额 / 全局调度策略
（**D9 裁定后改写**：多项目**并行运行**是有意采纳的语义，原「不扩大跨项目并发」表述作废）。

## 13. 本文件之外的同步义务

- `docs/frame.md`：新增 4.18「网页控制台」小节 + 配置表新增 `HTTP_CONSOLE_*` 两行（brief §10）。
- `.env.example`：新增 2 键（既有测试断言「全部字段被提及」会强制）。
- `_bmad-output/consolidated-overview.md`：Epic 50 条目（epic 收口时同步）。
- `_bmad-output/sprint-status.yaml`：epic-50 与 7 条 story 的状态行。

## 14. 侦察校正（2026-09-23，story 细分阶段实测）

写 `stories/50-*.md` 时对代码做了逐条实测复核，查出 **8 处**本文件／`epics.md` 的不准确或冲突之处。
按本文件开头的规则（「要改先改本文件并说明理由」），逐条在此登记，并已回写到对应小节。

| # | 原表述 | 实测事实 | 处置 |
|---|---|---|---|
| **C1** | 「`EngineContainer.default()` 必须**新增**状态根形参」 | `default()` **早已**接受 `workspace_root=`（`engine/container.py:173-176`），且已喂给 policy（`:303-304`）与沙箱会话目录（`:313-341`）；真正缺的是把它接到 `run_store`/`ledger`（`:44-45` 走 `field(default_factory=…)` 无参构造） | 已改 §3.2；story 50-1 的 T3 按此重写 |
| **C2** | §8 的「显式排除」表被当作完整划分 | **12 键**既不在白名单也不匹配任何排除模式（`ANTHROPIC_PROMPT_CACHING`、`DREAM_*`×4、`EVENTS_ROLLOUT_ENABLED`、`LOG_LEVEL`、`LOG_FILE_LEVEL`、`OLLAMA_ENABLED`、`RETRY_*`×3）⇒ 会「只读但无原因」，违反 UX-DR5 | 已改 §8；由 **D3** 裁定归位（8 开放 / 4 只读），划分 **46 + 64、残留 0** |
| **C3** | 白名单与排除模式可并存 | `SANDBOX_DIR_RETENTION_DAYS` **同时命中**白名单与 `SANDBOX_*`（实测冲突），优先级未定义 | 已改 §8；由 **D2** 裁定：显式白名单 > 模式排除 |
| **C4** | 错误码闭集无「会话文件不可读」语义 | `SessionStore.load()` 静默把损坏 JSON 当空列表（`context/session.py:131-133`）⇒ 网页会把损坏会话当空会话并覆盖 | 由 **D1** 裁定：**新增 `session_unreadable`**（本节曾标「待定」，已关闭） |
| **C5** | §7 列「六个必须处理的坑」 | 实测出**第 7 个**：`KEY=`（空值）整条**不出现**在任何来源层 ⇒ 会把「显式置空」谎报成「来源=默认」 | 已改 §7；50-4 的 AC6/T4 |
| **C6** | 白名单以 `Settings.model_fields` 表达 | `model_fields` 的键是**小写**字段名、零 alias ⇒ 直接用小写/大写混写会静默 miss | 已改 §7 增加「键名口径」段；50-4 的 T3 |
| **C7** | `epics.md` Story 50.1 的验证命令含 `tests/test_path_safety.py` | **该文件不存在**（实测 `MISS`）；内部状态 deny 的测试在 `tests/test_credential_guard.py`（`test_build_internal_state_dirs`，`:66`） | 已修 `epics.md` 的 DoD 命令 |
| **C8** | `epics.md` 的 Additional Requirements 写 `HTTP_CONSOLE_PROJECTS_FILE` 默认 `~/.heagent/projects.json` | 与本文件 §4「落点 = `<服务启动工作区>/.heagent/console/projects.json`，**默认不写用户 home**」冲突 | 已修 `epics.md`，以本文件 §4 为准 |
| **C9** | §8 写「划分完整性 **110 = 46 + 64**」 | `4f67397` 新增 `HTTP_IDLE_TIMEOUT` 后实测 **111 = 46 + 65**（残留 0）；同文件 §15 的 D3 行早已写 111/65（自相矛盾） | 已就地校正 §8（story 50-4 的数字同步校正）|
| **C10** | §3.1 写 `config_backups = state_dir/"backups"/"env"` | 实测代码是 `workspace.py` 的 `state_dir/"backups"`（`tools/path_safety.py` 的 I14 deny 集同）——备份写入方（Story 50-5）尚未落地，两处口径必须先定死 | 已就地校正 §3.1为代码口径；50-5 必须经 `WorkspacePaths.config_backups` 取路径（不得另拼字符串）|

**顺带确认（无需改动）**：`network.exposure.is_loopback_host()` 直接可用于**写通道来源判定**——
实测 11 种输入全对，含 IPv4 映射形式 `::ffff:127.0.0.1` 与 `[::ffff:127.0.0.1]`（本机 Python 3.13.5）；
曾假设该形式会被误判为非回环，**实测证伪**，故不新增分支（结论已入 50-5/50-7 的测试要求）。

**story 产物**（本周期 7 条，与 `sprint-status.yaml` 的 key 一一对应）：

| story | 文件 | 阶段 |
|---|---|---|
| 50-1 | `stories/50-1-workspace-first-class.md` | A |
| 50-2 | `stories/50-2-project-registry-api.md` | B |
| 50-3 | `stories/50-3-session-persistence-api.md` | B |
| 50-4 | `stories/50-4-config-sources-readonly-api.md` | C |
| 50-5 | `stories/50-5-config-write-channel.md` | D |
| 50-6 | `stories/50-6-console-ui.md` | E |
| 50-7 | `stories/50-7-security-acceptance-docs.md` | E |

**实现期校正（2026-09-24，Epic 50 实现与收口实测）**：写代码与收口时对同一批事实复核，又查出 3 处
不准确，逐条登记（并已回写到对应位置）：

| # | 原表述 | 实测事实 | 处置 |
|---|---|---|---|
| **C11** | §10 / **D7** 预判控制台逻辑会拆到独立模块 `cli_console.py` 并「默认不 omit」 | 该模块**从未存在**：控制台装配全在 `cli_http.py`（**不在**覆盖率 omit 列表里，靠测试覆盖，实测计入总量） | D7 标注**作废**；`docs/frame.md` 五 记录该口径变更与「若将来拆分口径随模块走」 |
| **C12** | §8 划分完整性 `111 = 46 + 65`（C9 校正后的口径） | Story 50-5 新增 2 个 `HTTP_CONSOLE_*` 键后实测 **113 字段 = 白名单 46 + 排除 67、残留 0** | `docs/frame.md` 4.18 采用实测值；本表同步 |
| **C13** | §5.3 与 `docs/frame.md` 4.17 的 `HttpErrorCode` 计数 **27** | Story 50-5 的写通道再加 5 ⇒ 实测 **32**（= 49 的 14 + Epic 50 的 18：项目注册表 6 / 会话 5 / 写通道 5 / 运行与边界 2） | 已就地校正 `docs/frame.md` 4.17（口径与分组见 4.18） |

**随实现落定的未决项**：**D8**（静态资源是否加 `no-store`）—— 实测静态资源已带
`cache-control: no-cache`（Epic 49 既有），它已强制再验证 ⇒ **结论：不新增**，不作变更（记录在此，
不再另立条目）。**D5**（条目上限 32）与 **D6**（会话列表只读轻量元数据）按裁定落地，无偏差。
**D1/D2/D3/D4/D9** 亦均按裁定落地（D4 的告警为 stderr + 日志双通道）。

## 15. 决策登记表（D1–D8，2026-09-24 裁定）

本表是 Epic 50 决策编号的**唯一**来源；`stories/50-*.md` 里的决策引用一律指向本表
（早期产物中用过的局部编号 `D-1`/`D-2`/`D-3`/`D-4` 已按本表统一，其中两个「D-1」指的是不同的事）。

| # | 决策 | 裁定 | 依据 | 生效位置 |
|---|---|---|---|---|
| **D1** | 损坏会话文件用哪个错误码 | **新增 `session_unreadable`** | 闭集新增语义须加成员；与 `session_conflict` 不重叠 | 脊柱 §5.3；50-3 T5/AC9 |
| **D2** | 白名单 vs 模式排除的优先级 | **显式白名单 > 模式排除**，并把 `SANDBOX_*` 语义收窄为「执行姿态键」 | `SANDBOX_DIR_RETENTION_DAYS` 实测同时命中两者 | 脊柱 §8；50-4 T6；50-5 T6 |
| **D3** | 原「12 个未分类键」的归位 | **8 键开放 / 4 键只读**：开放 = 3 个 bool（`ANTHROPIC_PROMPT_CACHING`、`EVENTS_ROLLOUT_ENABLED`、`OLLAMA_ENABLED`）+ 5 个需补守卫（`LOG_LEVEL`、`LOG_FILE_LEVEL` 枚举；`RETRY_*` 上界 10/60/600）；只读 = `DREAM_CRON`、`DREAM_IDLE_MINUTES`、`DREAM_MAX_ITERATIONS`、`DREAM_SESSION_LOOKBACK` | 弱校验键开放的前置条件是字段级校验（I6 对它们是空门）；dream 参数在 `DREAM_ENABLED` 只读时开放零收益 | 脊柱 §8；50-4 T6/AC9；50-5 AC5 |
| **D4** | 写闸门的开启渠道与告警 | **允许任何启动配置渠道**（系统环境变量 / 项目 `.env` / 全局 `.env`）+ 可选 CLI 开关；**启动时**打一条「写通道已开启，任何能连上该端口的人都能改项目 `.env`」高亮告警；**网页任何请求都开不了它** | 它本身就是启动配置；I12 禁的是**网页**自行开启 | 脊柱 §8/§9；50-5 T5；50-6 常驻声明 |
| **D5** | 项目条目数上限 | 常数 **32**，不新增配置键 | 避免扩大 `Settings` 面 | 50-2 T4 |
| **D6** | 会话列表 `message_count` 取法 | 列表只读轻量元数据；会话过大时退化为「详情才返回」 | 大会话逐文件解析有成本 | 50-3 R1 |
| **D7** | `cli_console.py` 覆盖率口径 | ~~**不 omit**（靠测试覆盖）~~ **作废：该模块从未落地**（实现期校正 §14 C11） | 脊柱 §10 | 50-7 R1 |
| **D8** | 静态资源是否加 `no-store` | 实现期按「旧 JS × 新 API 错配」判断，加了即记录 | 现仅 SSE 路径有该头 | 50-6 R3 |
| **D9** | 跨项目并发语义（原评审 F4） | **采纳「并发随项目数线性增长」**：在途上限 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`（默认 **最多 32**）；每项目内部的单运行/会话保护/缓冲上限不变；**无全局上限**，登记为已知缺口（后续可加 `HTTP_CONSOLE_MAX_TOTAL_INFLIGHT`），连接层仍受 `HTTP_MAX_CONNECTIONS` 约束 | 多项目并行是网页控制台的一等能力；代价线性放大而每项目仍单运行 | 脊柱 §6/§12；`brief` §5；50-2 T4；50-3 T9；50-7 T10⑨ |

**不随本表裁定（实施期事项，不阻塞开工）**：见各 story 的「风险与未决」——50-1 R3/R4、50-2 R1、
50-3 R1/R2/R3、50-4 R2、50-5 R2/R3、50-6 R1/R2、50-7 R2/R3。

**审阅期收紧（2026-09-24，裁定落笔后的自查发现，按建议修正）**：

| # | 问题 | 处置 |
|---|---|---|
| R-a | 排除表「沙箱与执行后端 \| `SANDBOX_*`」未写 D2 例外，读者会以为该键被封死 | 补「（**除 `SANDBOX_DIR_RETENTION_DAYS`，见 D2**）」 |
| R-b | 弱校验键注释仍举 `DREAM_CRON` 作「需 cron 表达式校验」的例子，而 D3 已将其留只读 ⇒ 死文本 | 删去该例，守卫要求收窄为「枚举 / 上界」 |
| R-c | `HTTP_CONSOLE_*` 同时命中 `HTTP_*` 与「控制台自身」两条排除规则，**只读原因显示哪条未定义** | 新增规则：排除之间**显式行 > 模式行**，同型按表内顺序取首条；由 50-4 T6/T9 钉住 |
| R-d | §8 流水线列 11 项，而 50-5 全篇写「10 步流水线」，口径不一致 | §8 统一为「**10 步执行 + 1 项生效语义**」 |

**已裁定（D9，2026-09-24 —— 原评审 F4 的 `blocked` 项已关闭）**：**采纳「跨项目并发随项目数线性增长」**。

- 语义：在途运行上限 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`（默认项目上限 32 ⇒ **最多 32 个并发 run**）；
  跨项目不共享在途名额、不做全局调度；**每项目内部**的单运行约束、会话在途保护、缓冲/历史上限、
  配置写入闸门一律不变。详见 §6「并发口径」。
- 文档义务：`brief` §5 的「多项目切换不等于并行运行」已作废（见该文件同处标注）；§12 的
  「扩大跨项目并发运行能力（不做）」已改写为「不做**跨项目共享名额 / 全局调度**」。
- **已知缺口如实登记**：无全局并发上限 ⇒ 接近项目数上限时资源占用线性上升；
  是否新增 `HTTP_CONSOLE_MAX_TOTAL_INFLIGHT` 留作后续（写入 `docs/frame.md` 五 与 deferred 台账）。
  `HTTP_MAX_CONNECTIONS` 不随项目数放大 ⇒ 多项目并行时连接层可能先成为瓶颈（既有限制面的延续）。
