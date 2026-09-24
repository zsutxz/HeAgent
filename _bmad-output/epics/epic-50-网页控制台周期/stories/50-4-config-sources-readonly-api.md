---
id: 50-4
title: 配置来源求解与只读配置 API
status: review
baseline_commit: 4f673973be4a97acab3be1f058eabdbd4e673e49
parent_epic: E50
priority: P0
phase: C（配置可见）
depends_on: [50-1, 50-2, 50-3]
blocks: [50-5, 50-6, 50-7]
created: '2026-09-23'
---

# Story 50-4：配置来源求解与只读配置 API

## 用户故事

作为控制台用户，我希望看见每一项配置的**有效值 + 来源 + 可写性 + 只读原因**，
以便理解「现在实际生效的配置到底是从哪来的」，而不是对着一份不知道哪层覆盖了哪层的 `.env` 猜。

## 侦察实证（2026-09-23，全部为实测，探针见 `.heagent/tmp/epic50_probe*.py`）

### 四层求解可行（本 story 的技术前提已证实）

| 项 | 实测结果 |
|---|---|
| pydantic-settings 版本 | `2.14.2` |
| `DotEnvSettingsSource(Settings, env_file=<path>)` **是否尊重显式路径** | 是：指向不存在文件 → **0 键**；指向只含 2 键的临时文件 → **恰好这 2 键** |
| `Settings(_env_file=<path>)` / `_env_file=[a, b]` | 均可；列表后者覆盖前者（与运行期 `env_file=[GLOBAL, ".env"]` 同序） |
| 本机四层键数 | `global_env=39`、`project_env=39`、`system_env=0` ⇒ 有效来源 **39 键全部落 `project_env`** |
| `GLOBAL_CONFIG_FILE` | 存在；`Settings.model_config["env_file"] == [<global>, ".env"]`，即运行期口径 |
| **相对 `.env` 的解析基准是进程 CWD** | 实测：`os.chdir(tmp)` 后 `Settings()` 读到 tmp 的 `.env`（`max_iterations` 变 42）⇒ 多项目下**必须**显式传绝对 `_env_file`，否则「项目的配置」会退化成主进程 cwd 的配置（脊柱 §7 的警示已证实） |

### 六个坑 + **新查出第 7 个**（逐条实测）

| # | 坑 | 实测证据 | 处置 |
|---|---|---|---|
| 1 | 来源层返回**原始字符串** | 层给 `'123'`（str），`Settings` 给 `123`（int）；`ROUTING_POOLS` 层给 str、`Settings` 给已解析结构 | 来源判定**只看键是否出现**；展示值一律取自 `Settings` 实例 |
| 2 | 未知键**可见**且被**转小写** | `TOTALLY_UNKNOWN_KEY=hello` → 层里出现 `totally_unknown_key`；且 `Settings(extra="ignore")` 构造**不报错**（静默忽略） | 未知/拼错键**单列**标「不生效」，不并入有效值 |
| 3 | 文件缺失被静默跳过 | 指向不存在文件 → 0 键（无异常） | 先 `is_file()` 探测，区分「来源=默认」与「文件不存在」 |
| 4 | 相对路径按**进程 CWD** 解析 | 见上表 | 项目 `.env` 路径一律由 `WorkspacePaths` 显式给出 |
| 5 | 同文件**重复键后者胜** | `MAX_CONTEXT_TOKENS=111` 后接 `=222` → 层给 `'222'`；项目 `.env` 实测**恰有 1 个重复键**（`SKILL_MAX_AUTO_INVOKE_TOKENS` ×2） | 展示取后者；写入定位**最后一个**匹配行并在响应中提示重复 |
| 6 | 行内注释被剥离 | `MAX_ITERATIONS=123   # 行内注释` → 层给 `'123'`；项目 `.env` 实测 **10 处**行内注释 | 展示剥注释后的值；写回不得吞注释、不得把注释当值 |
| **7** | **空值行整条消失（脊柱未列）** | `EMPTY_VALUE=` → 层里**没有**该键（不是空串） | 必须区分「文件里有这个键但为空」与「文件里没这个键」，否则面板会把「显式置空」谎报成「来源=默认」。见 AC6 与 T4 |

### 配置面结构（实测）

| 项 | 实测 | 含义 |
|---|---|---|
| `Settings.model_fields` | **111** 个字段，**零 alias**（实测；story 起草时为 110，此后 `4f67397` 新增 `HTTP_IDLE_TIMEOUT`） | env 键 = 字段名 `.upper()`，纯机械映射；111 ↔ 111 双射无碰撞 |
| 字段名大小写 | **小写**（`max_iterations`） | **陷阱**：白名单必须写成 env 形式（`MAX_ITERATIONS`）再用 `.upper()` 映射，**不能** `Settings.model_fields["MAX_ITERATIONS"]`（会 miss） |
| 白名单（脊柱 §8） | 原 v1 **38 键** 38/38 全部存在；**D3 裁定后 46 键，46/46 仍全部存在**（已实测） | 白名单成立 |
| 白名单 ∩ 排除模式 | **1 处冲突**：`SANDBOX_DIR_RETENTION_DAYS` 同时命中 `SANDBOX_*` 排除模式 | 优先级由 **D2** 裁定：显式白名单 > 模式排除 |
| 既不在白名单、也不匹配任何排除模式的键 | **12 个**（实测）：`ANTHROPIC_PROMPT_CACHING`、`DREAM_{CRON,IDLE_MINUTES,MAX_ITERATIONS,SESSION_LOOKBACK}`、`EVENTS_ROLLOUT_ENABLED`、`LOG_LEVEL`、`LOG_FILE_LEVEL`、`OLLAMA_ENABLED`、`RETRY_{MAX_ATTEMPTS,BASE_DELAY,MAX_DELAY}` | 原「9 类排除表」是**不完整划分**（只读但给不出原因 → 违反 UX-DR5）；由 **D3** 裁定归位后残留 **0** |
| `.env.example` | 347 行、全 LF、无 BOM、覆盖**全部 111** 个 env 键（0 缺失） | 既有断言 `tests/test_config.py:574-587`（「字段 ⊆ .env.example」）已钉住 |
| `.env.example` 的写法 | 111 键中仅 **11 行**是活键，其余以 `# KEY=...` 注释形式文档化 | 同步新键时必须跟随注释风格（否则 50-7 的断言与观感都会走样） |
| 项目 `.env`（开发机） | 4442 字节、77 行**全 CRLF**、无 BOM、末行有换行、40 条 KV / 39 唯一键 / 1 重复 / 10 行内注释 | 50-5 保真写的样本来源 |

## 范围

- 新增顶层模块 `src/heagent/config_catalog.py`：分组、可写白名单、只读原因、凭证识别、**四层来源求解**。
- 新增只读 API：`GET /api/projects/{id}/config`。
- 分组与可写性由**声明式常量**驱动，与 50-5 的写白名单**同一处定义**（单一来源）。
- 凭证项只回 `configured` 布尔 + **定长掩码**（不含任何原文字符）。

## 边界与约束

**Always**

- 展示值与来源口径**同源**：值取自 `Settings` 实例，来源取自分层求解器（NFR-3，禁止第二套解析）。
- 项目 `.env` 路径由 `WorkspacePaths` 显式给出；解析用 `Settings(_env_file=[GLOBAL_CONFIG_FILE, <项目>/.env])`。
- 每一项都有 **`writable` 与 `read_only_reason`**（UX-DR5：只读必须给原因，不能静默禁用）。
- 响应体有界：项目数 × 111 字段，且字段集合固定（不随 `.env` 内容膨胀）。
- 未知键单列；`.env` 缺失 / 不可读 → 全字段回退 `global_env` / `default` 并标注文件状态，**不报 500**。

**Never**

- 不返回任何凭证明文，也不返回能反推长度的掩码（定长，不含原文字符）。
- 不把来源层的**原始字符串**当作有效值展示。
- 不新增第二套 `.env` 解析器（复用 `pydantic_settings` 的 source 类；行级改写归 50-5 的 `envfile.py`）。
- 不在 `config_catalog.py` 里 import `engine` / `agent` / 入口层（脊柱 §2 依赖表）。
- 不改动进程环境变量、不 chdir（I3）。

## 任务（细分）

- [x] **T1** `config_catalog.py`：`ConfigCatalog` 以 `Settings.model_fields` 为字段宇宙，产出
      `ConfigItem{key, group, value, source, writable, read_only_reason, is_secret, configured, masked, guards, notes}`（Pydantic；
      `notes` 为 T4 的诊断码载体——空值行 / 重复键 / BOM 前缀 / 行内注释）。
      **`guards`（评审 V1，支撑 AC11）**：承载该键的合法约束（枚举集合或上下界），供 UI 提示与写通道复用；
      弱校验键（`LOG_LEVEL` 等）必须有值——否则 AC11 无法实现。
- [x] **T2** 四层求解器：`default`（字段默认）→ `global_env` → `project_env` → `system_env`，逐层只记录
      「键是否出现」，最后落「最后出现的层」为来源；四层都未见 → `default`。
- [x] **T3** 键名映射层：内部一律用 **env 键（大写）** 表达，`Settings.model_fields` 访问时 `.upper()` 映射；
      附一条测试钉住「111 个 env 键 ⟷ 111 个字段」的双射（防未来新增 alias 时静默漂移）。
- [x] **T4** 七个坑逐条实现（含新查出的第 7 个）：原始串 vs 强转（T2 已覆盖）、未知键单列、文件缺失探测、
      显式路径、重复键后者胜（并在响应 `notes` 里提示重复）、行内注释剥离、**空值行单独标注**。
- [x] **T5** 凭证识别与掩码：`*_API_KEY` / `*_API_KEYS` 全部命中；只回 `configured` + 定长掩码；
      测试覆盖**短密钥**（长度 ≤ 掩码位数）与**多密钥**（逗号/JSON 列表）两条负向。
- [x] **T6** 分组与可写性声明式常量：把白名单（**D3 裁定后 46 键**）与排除组（含 4 个 dream 参数键的显式归位）表达为
      `WHITELIST: frozenset[str]` + `EXCLUSIONS: tuple[ExclusionRule, ...]`；**同一份常量被 50-5 复用**。
      并编码**排除规则优先级**（脊柱 §8 R-c：显式行 > 模式行；同型按表内顺序取首条）⇒ `HTTP_CONSOLE_*` 的
      `read_only_reason` 显示「控制台自身（写入面不得给自己解锁）」而非「监听面」。
- [x] **T7** 只读 API：`GET /api/projects/{id}/config` → 分组后的条目 + `.env` 文件状态（路径 / 存在与否 / 指纹）；
      项目不可用 → `project_unavailable`；未知项目 → `unknown_project`。
- [x] **T8** `ROUTING_POOLS` 特殊展示：展示**有效**路由结果（池名 / 档位映射 / 是否因非法 JSON 被整条忽略）；
      非法 JSON 时标注原因而不是只回原始串（既有行为：整条池被忽略 + 一条 WARNING + 回落 `<条目>_MODEL`）。
- [x] **T9** 测试：四层来源各一例、系统环境变量只读（`monkeypatch.setenv`）、未知键、缺失文件、
      空值行、重复键、行内注释、凭证掩码（短密钥 + 多密钥负向）、110 键双射、分组完备性
      （白名单 ∪ 排除 = 全 111，无未分类残留）、**排除原因口径**（`HTTP_CONSOLE_*` 走「控制台自身」而非
      「监听面」；`SANDBOX_DIR_RETENTION_DAYS` 按 D2 为可写且无原因）。
- [x] **T9b** **BOM 边界（评审 F6，必做）**：带 UTF-8 BOM 的 `.env` 会让**首个键静默失效**——
      实测 `DotEnvSettingsSource` 返回的键是 `'\ufeffmax_iterations'`（BOM 进了键名），
      生效值退化为字段默认（本例 `max_iterations`：文件写 123，实际取 50），**且无任何告警**。
      这与此前刚修过的 frontmatter / MEMORY.md BOM 缺陷族同源。要求：
      ①来源求解前剥离**文件头部 BOM** 再分层（读路径不写盘，盘上 BOM 保留）；
      ②若仍出现 BOM 前缀键，必须标注为「BOM 前缀导致不生效」而不是静默落 `default`；
      ③配测试：BOM + 非 BOM 两份 `.env` 的**同键来源与取值必须一致**。
- [x] **T10** 负向验证：把来源判定改成「读层里的值」、去掉未知键单列、去掉空值行标注、换成变长掩码、
      去掉 BOM 剥离——对应测试逐条变红后复原。

## 验收标准

- **AC1** Given 项目 `P` 存在系统环境变量覆盖、项目 `.env` 覆盖与全局 `~/.heagent/.env` 覆盖各若干项，
  When 客户端 `GET /api/projects/{id}/config`，Then 每项返回 `key`、`value`、`source`
  （`system_env` / `project_env` / `global_env` / `default`）、`writable`、`read_only_reason`。
- **AC2** Given 某键被系统环境变量提供，When 查询该项，Then `source=system_env` 且 `writable=false`、
  原因标明「被系统环境变量覆盖」。
- **AC3** Given 某键只在项目 `.env` 出现，When 移除该行后再次查询，Then 该项回落到 `global_env` 或 `default`
  并如实标注新来源。
- **AC4** Given 任一凭证键（`DEEPSEEK_API_KEY`、`OPENAI_API_KEYS` 等全部 `*_API_KEY` / `*_API_KEYS`），
  When 查询配置，Then 只返回 `configured: true/false` 与**定长掩码**（不反映真实长度），**永不**返回明文；
  短密钥（长度 ≤ 掩码位数）也不得因展示而暴露全文。
- **AC5** Given 项目 `.env` 中存在未知键或拼错的键，When 查询配置，Then 该键被标记为「未知键（不生效）」，
  **不并入**有效值列表。
- **AC6** Given 项目 `.env` 中存在 `SOME_KEY=`（显式空值），When 查询配置，Then 该项**不**被谎报为「来源=默认」，
  而是标注「在项目 `.env` 中为空值」并给出实际生效来源。
- **AC7** Given 项目 `.env` 不存在或不可读，When 查询配置，Then 返回全部字段的 `default` / `global_env` 来源，
  并明确标注项目配置文件路径与「不存在」状态，不报 500。
- **AC8** Given 配置项的值来源于 `Settings` 快照与来源求解器，When 客户端同时查询面板与观察运行行为，
  Then 两者对同一键的口径一致（同一求解器，非第二套解析）。
- **AC9** Given 全部 111 个字段，When 查询配置，Then 每一项都落在「可写」或「有明确 `read_only_reason`」之一，
  **不存在**既不可写又无原因的字段（**D3 裁定**后划分 = 46 白名单 + 65 排除、残留 0，由测试断言完备性）。
- **AC10** Given `SANDBOX_DIR_RETENTION_DAYS`（**D2 裁定**：显式白名单 > 模式排除），When 查询该项，
  Then `writable=true` 且原因字段为空；而 `SANDBOX_BACKEND` / `SANDBOX_MODE` 等**执行姿态键**仍为只读并给原因。
- **AC11** Given 5 个弱校验键（`LOG_LEVEL`、`LOG_FILE_LEVEL`、`RETRY_MAX_ATTEMPTS`、`RETRY_BASE_DELAY`、`RETRY_MAX_DELAY`）
  在 **D3** 下被开放为可写，When 查询该项，Then 返回其**守卫约束**（枚举集合或上界），供 UI 提示合法范围。
- **AC12** Given 项目 `.env` 带 UTF-8 BOM，When 查询配置，Then 每一项的来源与取值与「同一内容但无 BOM」的
  `.env` **完全一致**；若实现未能剥离，则该键必须被标注为「BOM 前缀导致不生效」，而不是静默显示为 `default`
  （评审 F6：BOM 缺陷族——实测首键会退化为默认值且无任何告警）。

## Definition of Done

**交付物**：`src/heagent/config_catalog.py`（新增）、`src/heagent/network/http_console_protocol.py`、
`src/heagent/network/http_server.py`、`tests/test_config_catalog.py`（新增）、`tests/test_config.py`（扩充）、
`tests/network/test_http_console_config.py`（新增）。

**验证命令**（实测存在性已核对）：

```bash
pytest tests/test_config_catalog.py tests/test_config.py tests/network -q
pytest -q
ruff check src tests && mypy src && mypy src --platform linux
```

**负向验证**：T10 的 4 项回退各自精确变红；另跑一次「面板 ↔ 运行期口径一致」的对照实验（AC8）。

**质量门**：`pytest`、`ruff check`、`ruff format --check src tests`、`mypy src`、`mypy src --platform linux` 全绿。

## 代码地图

| 路径 | 角色 | 改动 |
|---|---|---|
| `src/heagent/config_catalog.py` | **新增** 配置目录 + 四层来源求解 + 凭证掩码 | 依赖 `config`（+ pydantic）；**不**依赖 engine/agent |
| `src/heagent/network/http_console_protocol.py` | 协议模型 | 配置条目 / 分组 / 文件状态模型 |
| `src/heagent/network/http_server.py` | 路由 | `GET .../config` |
| `tests/test_config_catalog.py` | **新增** | 四层 / 七坑 / 掩码 / 双射 / 完备性 |
| `tests/test_config.py` | 既有断言 | `.env.example` 覆盖断言保持通过 |

## 风险与未决

- **D2（已裁定 2026-09-24，见脊柱 §15）**：**显式白名单优先于模式排除**；`SANDBOX_*` 的模式语义收窄为
  「执行姿态键」而非宽 glob。⇒ `SANDBOX_DIR_RETENTION_DAYS` 可写（保留天数是运维可调项，不是隔离姿态）。
  落地：`config_catalog.py` 常量里写明优先级 + 一条测试断言它 `writable=true`。
- **D3（已裁定 2026-09-24，见脊柱 §15）**：原 12 个未分类键 **8 开放 / 4 只读**——
  - 开放（3 个纯 bool，零门槛）：`ANTHROPIC_PROMPT_CACHING`、`EVENTS_ROLLOUT_ENABLED`、`OLLAMA_ENABLED`；
  - 开放（5 个需先补字段级守卫）：`LOG_LEVEL`、`LOG_FILE_LEVEL` → 枚举 `{DEBUG,INFO,WARNING,ERROR,CRITICAL}`；
    `RETRY_MAX_ATTEMPTS ≤ 10`、`RETRY_BASE_DELAY ≤ 60`、`RETRY_MAX_DELAY ≤ 600` → 上界；
  - 只读（4 键）：`DREAM_CRON`、`DREAM_IDLE_MINUTES`、`DREAM_MAX_ITERATIONS`、`DREAM_SESSION_LOOKBACK`
    （仅在已只读的 `DREAM_ENABLED` 为真时生效，v1 开放零收益）。
  ⇒ 白名单 **38 → 46 键**；划分完整性 = **111 = 46 白名单 + 65 排除，残留 0**（开发期复测）。
  ⚠️ **弱校验键的强制前提**：`Settings(_env_file=候选)` 构造成功对它们是**空门**（`retry_*` 只有 `Ge` 下界、
  `LOG_LEVEL` 连 metadata 都没有）⇒ 上述 5 键**必须**额外走字段级校验，否则写通道变成「挂死 / 无限重试」旋钮。
- **R1**：`system_env` 层在当前 shell 实测为 0 键；测试必须用 `monkeypatch.setenv` 构造，**不能**依赖开发机环境。
- **R2**：来源求解会构造 3 个 source 实例（含 2 次文件读）；面板每次请求的解析成本应实测并记录
  （若超过阈值，加进程内缓存 + 以 `.env` 指纹作键，缓存失效口径与 50-5 的指纹一致）。

## Requirement Traceability

FR-4；NFR-3, NFR-4, NFR-5, NFR-11；UX-DR2, UX-DR5；脊柱 I2, I9；brief §4 FR-4、§6.2、§6.9。

## Dev Agent Record

### Implementation Plan

- T1–T6 全部落在**新增顶层模块** `src/heagent/config_catalog.py`：域模型（`ConfigItem` / `ConfigGuard` /
  `RoutingPoolsReport` / `EnvFileReport`）+ 声明式常量（`WHITELIST_GROUPS` / `EXCLUSION_GROUPS` / `VALUE_GUARDS` /
  `LABELS`）+ 四层求解器 + 行级**诊断**扫描。依赖面只有 stdlib / Pydantic / `heagent.config`。
- T7 分三层落地：协议模型与 `ConsoleHandler.get_project_config` 进 `network/http_console_protocol.py`
  （网络层仍不认识配置，脊柱 I1）；路由进 `network/http_server.py`；域模型 → 协议模型的映射、项目 id →
  项目 `.env` 路径的解析进入口层 `cli_http.py`。
- T8/T9b 与 T1–T6 同批交付：路由池有效视图复用既有 `Settings.routing_pool_map`；BOM 容差经
  `settings_customise_sources` 换掉 dotenv 源（值语义完全交给父类）。

### Completion Notes

- **T1/T2/T3**：入口 `build_config_report(project_env_file, *, global_env_file=GLOBAL_CONFIG_FILE)`；来源判定只看
  「键是否出现在层里」，有效值一律取自 `Settings(_env_file=[全局, 项目])`。键名口径统一为**大写 env 键**，
  映射时 `.upper()` / `.lower()`；双射断言落在 `tests/test_config.py::test_env_keys_are_bijective_with_model_fields`。
- **T4（七个坑）**：①原始串不作值；②未知键单列（`unknown_keys`，保留原写法，上界 64 + 截断标注）；
  ③文件缺失 / 不可读先探测（`project_env_missing` / `project_env_unreadable`，不报 500）；④显式绝对路径
  （`test_explicit_path_beats_process_cwd` 用 `monkeypatch.chdir` 反证「不读进程 cwd 的 .env」）；
  ⑤重复键后者胜 + 条目级 `duplicate_in_project_env` + `env_file.duplicate_keys`；⑥行内注释剥离 +
  `inline_comment_in_project_env`；⑦空值行（见下）。
- **T5**：`is_secret_key` 命中 9 个 `*_API_KEY(S)`；凭证项 `value` 恒为 `None`，只回 `configured` + **常量**掩码
  `MASK="********"`（零信息量、不反映长度）。测试覆盖短密钥（4 字符）与多密钥列表两条负向，并整份响应断言
  「明文不出现」。
- **T6**：`WHITELIST_GROUPS`（10 组 46 键）+ `EXCLUSION_GROUPS`（显式键行 7 条 + 模式行 5 条）+ `UNKNOWN_GROUP`
  兜底；`classify()` 实现「白名单 > 显式行 > 模式行」（D2 / R-c），完备性 = 0 残留；同 `id` 的多条 spec
  在响应里**合并成一组**。
- **T6/T7 边界（如实说明）**：`HTTP_CONSOLE_WRITE_ENABLED` / `HTTP_CONSOLE_PROJECTS_FILE` 目前**还不是**
  `Settings` 字段（由 Story 50-5 新增）⇒「控制台自身」这条排除规则的优先级在**规则层**已被测试钉住
  （`classify("HTTP_CONSOLE_WRITE_ENABLED")`），但要等 50-5 落地后才会真正出现在响应里。常量先就位是有意的：
  50-5 **不应**再改分类逻辑。
- **T8**：`routing_report()` 复用 `Settings.routing_pool_map`（既有解析器）产出「有效池」视图
  （`declared_entries` / `effective[].tiers|roles|default|keywords` / `ignored_entries` / `invalid_json`），
  由条目诊断码 `routing_pools_invalid`（整份被忽略 ⇒ 回落 `<条目>_MODEL`）与 `routing_pools_entries_ignored`
  提示原因，而不是只回一串 JSON。
- **T9b（BOM）**：`_BomTolerantDotEnvSource._read_env_file` 只剥**映射里第一个键**的 BOM（= 文件头 BOM），
  `Settings` 侧用 `settings_customise_sources` 换成同一来源 ⇒ 来源与取值两侧同时容差（AC12：BOM 与非 BOM
  逐键一致）。文件**中部**的 BOM 刻意保留，由公开绊线 `bom_prefixed_keys()` + 条目级
  `bom_prefixed_in_project_env` 点名，绝不静默落 `default`（T9b②）。
- **T9 测试**：新增 `tests/test_config_catalog.py`（50 例）与 `tests/network/test_http_console_config.py`（13 例），
  `tests/test_config.py` 增双射断言。`config_catalog.py` 覆盖率 **97%**（394 stmts / 9 miss）。
- **T10 负向验证**：探针 `.heagent/tmp/mutate_50_4.py` 逐个拆掉本次行为，**6/6 精确变红**后自动复位：
  ①值改成读来源层原始串（第二套解析）；②去掉未知键单列；③去掉空值行标注；④掩码改成变长（前 2 字符明文）；
  ⑤去掉文件头 BOM 剥离；⑥排除规则改成「模式行优先」（`HTTP_CONSOLE_*` 显示成监听面）。

### 实现期发现并修掉的真实缺陷（均由实测 / 新测试暴露，不是测试迁就实现）

1. **story 的侦察数字过期**：`Settings` 字段实测 **111**（起草时 110——`4f67397` 新增 `HTTP_IDLE_TIMEOUT`），
   划分随之 **111 = 46 白名单 + 65 排除**（残留 0）；`.env.example` 实测 347 行 / 11 活键 / 覆盖全部 111 键。
   已就地校正 story 正文并在本记录留痕。
2. **坑 7 只被覆盖了一半（重要）**：`KEY=` 对**未知键**是「整条消失」，但对**已声明字段**会以 `''` **进层**——
   `MEMORY_NUDGE_ENABLED=` 会让 `Settings(...)` 直接 `ValidationError`（bool/int 字段），即「一个空值键把整层
   配置炸掉」。按原设计（候选失败 ⇒ 摘掉整层）实测会出现：**全部 111 项**都挂上 `ineffective_in_project_env`
   且来源集体退化成全局层。已改为**四级候选**——忠实口径 → **容错口径**（`env_ignore_empty=True`，空值 = 未提供）
   → 只留全局 → 不读任何 `.env`；且**层与取值同步降级**（否则「来源说 project_env、值却来自全局」自相矛盾，
   AC8）。空值只降级它自己并挂 `empty_in_project_env` + 响应级 `project_env_blank_values`（文案点明「bool/int
   字段会因此拒绝加载」）。
3. **`str | None` 字段的空值口径不同**：`LOG_FILE_LEVEL=` 在忠实口径下**不**降级（空串合法），生效值如实为空串、
   来源仍是项目层；两条口径差异各有测试钉住（`test_empty_value_of_str_field_is_kept_verbatim`）。
4. **排除组 id 复用导致响应里出现重复分组**：`outbound` / `run_semantics` 各有显式键行与模式行两条 spec，
   按 spec 逐个出组实测得到 **21 组**（含重复 id）；改为按 `id` 合并后 **19 组**。
5. **非 UTF-8 的 `.env`** 与「值非法」共用降级路径并统一标注 `project_env_invalid`（fail-soft，与 Z-D12 同立场，
   不抛不 500）。

### 测试环境注意（写给后续 story）

- `tests/conftest.py` 用 `os.environ.setdefault` 关掉 7 个保留期键（含 `SANDBOX_DIR_RETENTION_DAYS`）——那是**真实**的
  system_env 层 ⇒ 断言白名单可写性必须先 `monkeypatch.delenv`。这一交互本身也补了用例：
  `test_system_env_overrides_the_whitelist`（白名单键被系统变量提供时仍 `writable=false`）。
- 所有 catalog 用例都把 `global_env_file` 指向受控路径——读开发机 `~/.heagent/.env` 会让 `source` 断言不可复现。

### 成本（R2 实测）

`build_config_report` 中位 **14.0 ms/次**（n=7，探针 `epic50_probe14`）：`Settings` 构造 4.46 ms、行级扫描
0.13 ms、`model_dump(mode="json")` 0.16 ms，其余为三个来源实例；响应约 **38 KB**。结论：**不引入缓存**——
以指纹为键的缓存自身也要读文件，而陈旧快照与「生效语义 = 下一次 run」（I10）冲突。

### 交接

- `envfile.py`（行级**改写**）按脊柱归 Story 50-5。本 story 的 `scan_env_file` 只产出**诊断**（重复 / 空值 /
  行内注释 / 键的原写法）；50-5 定位「最后一个匹配行」时可复用其结果，但**不得**把值语义搬进扫描
  （否则就是本 story「Never」点名禁止的第二套解析器）。
- `HTTP_CONSOLE_*` 两个键与 `write_disabled` / `field_not_writable` 等错误码归 Story 50-5；分类常量与 `guards`
  已就位，50-5 直接复用同一份常量（单一来源）。
- 端点级用户文档与「面板 ↔ 运行期口径一致」的验收归 Story 50-6 / 50-7。

### 验证（实测命令与输出）

- `pytest tests/test_config_catalog.py tests/test_config.py tests/network -q` → **442 passed**
- `pytest -q` → **2735 passed, 10 skipped, 18 deselected**
- `ruff check src tests` → All checks passed；`ruff format --check src tests` → 272 files already formatted
- `mypy src` 与 `mypy src --platform linux` → 均 `Success: no issues found in 144 source files`
- `pytest -q --cov` → TOTAL **91.33%**（门限 87%）；新增模块 `src/heagent/config_catalog.py` **97%**
- `.heagent/tmp/mutate_50_4.py` → 6/6 变异体精确变红后自动复位

### File List

- src/heagent/config_catalog.py（新增）
- src/heagent/network/http_console_protocol.py
- src/heagent/network/http_server.py
- src/heagent/cli_http.py
- tests/test_config_catalog.py（新增）
- tests/network/test_http_console_config.py（新增）
- tests/test_config.py

### Change Log

- 2026-09-24：T1–T10 全部完成；story 状态 → `review`（baseline `4f67397`）；校正侦察数字（110 → 111 字段、
  64 → 65 排除）；新增 `notes` / `routing` 两个域模型字段（T4 / T8 的载体）。
