---
id: 50-4
title: 配置来源求解与只读配置 API
status: ready-for-dev
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
| `Settings.model_fields` | **110** 个字段，**零 alias** | env 键 = 字段名 `.upper()`，纯机械映射；110 ↔ 110 双射无碰撞 |
| 字段名大小写 | **小写**（`max_iterations`） | **陷阱**：白名单必须写成 env 形式（`MAX_ITERATIONS`）再用 `.upper()` 映射，**不能** `Settings.model_fields["MAX_ITERATIONS"]`（会 miss） |
| 白名单（脊柱 §8） | 原 v1 **38 键** 38/38 全部存在；**D3 裁定后 46 键，46/46 仍全部存在**（已实测） | 白名单成立 |
| 白名单 ∩ 排除模式 | **1 处冲突**：`SANDBOX_DIR_RETENTION_DAYS` 同时命中 `SANDBOX_*` 排除模式 | 优先级由 **D2** 裁定：显式白名单 > 模式排除 |
| 既不在白名单、也不匹配任何排除模式的键 | **12 个**（实测）：`ANTHROPIC_PROMPT_CACHING`、`DREAM_{CRON,IDLE_MINUTES,MAX_ITERATIONS,SESSION_LOOKBACK}`、`EVENTS_ROLLOUT_ENABLED`、`LOG_LEVEL`、`LOG_FILE_LEVEL`、`OLLAMA_ENABLED`、`RETRY_{MAX_ATTEMPTS,BASE_DELAY,MAX_DELAY}` | 原「9 类排除表」是**不完整划分**（只读但给不出原因 → 违反 UX-DR5）；由 **D3** 裁定归位后残留 **0** |
| `.env.example` | 345 行、全 LF、无 BOM、覆盖**全部 110** 个 env 键（0 缺失） | 既有断言 `tests/test_config.py:574-587`（「字段 ⊆ .env.example」）已钉住 |
| `.env.example` 的写法 | 110 键中仅 **11 行**是活键，其余以 `# KEY=...` 注释形式文档化 | 同步新键时必须跟随注释风格（否则 50-7 的断言与观感都会走样） |
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
- 响应体有界：项目数 × 110 字段，且字段集合固定（不随 `.env` 内容膨胀）。
- 未知键单列；`.env` 缺失 / 不可读 → 全字段回退 `global_env` / `default` 并标注文件状态，**不报 500**。

**Never**

- 不返回任何凭证明文，也不返回能反推长度的掩码（定长，不含原文字符）。
- 不把来源层的**原始字符串**当作有效值展示。
- 不新增第二套 `.env` 解析器（复用 `pydantic_settings` 的 source 类；行级改写归 50-5 的 `envfile.py`）。
- 不在 `config_catalog.py` 里 import `engine` / `agent` / 入口层（脊柱 §2 依赖表）。
- 不改动进程环境变量、不 chdir（I3）。

## 任务（细分）

- [ ] **T1** `config_catalog.py`：`ConfigCatalog` 以 `Settings.model_fields` 为字段宇宙，产出
      `ConfigItem{key, group, value, source, writable, read_only_reason, is_secret, configured, masked, guards}`（Pydantic）。
      **`guards`（评审 V1，支撑 AC11）**：承载该键的合法约束（枚举集合或上下界），供 UI 提示与写通道复用；
      弱校验键（`LOG_LEVEL` 等）必须有值——否则 AC11 无法实现。
- [ ] **T2** 四层求解器：`default`（字段默认）→ `global_env` → `project_env` → `system_env`，逐层只记录
      「键是否出现」，最后落「最后出现的层」为来源；四层都未见 → `default`。
- [ ] **T3** 键名映射层：内部一律用 **env 键（大写）** 表达，`Settings.model_fields` 访问时 `.upper()` 映射；
      附一条测试钉住「110 个 env 键 ⟷ 110 个字段」的双射（防未来新增 alias 时静默漂移）。
- [ ] **T4** 七个坑逐条实现（含新查出的第 7 个）：原始串 vs 强转（T2 已覆盖）、未知键单列、文件缺失探测、
      显式路径、重复键后者胜（并在响应 `notes` 里提示重复）、行内注释剥离、**空值行单独标注**。
- [ ] **T5** 凭证识别与掩码：`*_API_KEY` / `*_API_KEYS` 全部命中；只回 `configured` + 定长掩码；
      测试覆盖**短密钥**（长度 ≤ 掩码位数）与**多密钥**（逗号/JSON 列表）两条负向。
- [ ] **T6** 分组与可写性声明式常量：把白名单（**D3 裁定后 46 键**）与排除组（含 4 个 dream 参数键的显式归位）表达为
      `WHITELIST: frozenset[str]` + `EXCLUSIONS: tuple[ExclusionRule, ...]`；**同一份常量被 50-5 复用**。
      并编码**排除规则优先级**（脊柱 §8 R-c：显式行 > 模式行；同型按表内顺序取首条）⇒ `HTTP_CONSOLE_*` 的
      `read_only_reason` 显示「控制台自身（写入面不得给自己解锁）」而非「监听面」。
- [ ] **T7** 只读 API：`GET /api/projects/{id}/config` → 分组后的条目 + `.env` 文件状态（路径 / 存在与否 / 指纹）；
      项目不可用 → `project_unavailable`；未知项目 → `unknown_project`。
- [ ] **T8** `ROUTING_POOLS` 特殊展示：展示**有效**路由结果（池名 / 档位映射 / 是否因非法 JSON 被整条忽略）；
      非法 JSON 时标注原因而不是只回原始串（既有行为：整条池被忽略 + 一条 WARNING + 回落 `<条目>_MODEL`）。
- [ ] **T9** 测试：四层来源各一例、系统环境变量只读（`monkeypatch.setenv`）、未知键、缺失文件、
      空值行、重复键、行内注释、凭证掩码（短密钥 + 多密钥负向）、110 键双射、分组完备性
      （白名单 ∪ 排除 = 全 110，无未分类残留）、**排除原因口径**（`HTTP_CONSOLE_*` 走「控制台自身」而非
      「监听面」；`SANDBOX_DIR_RETENTION_DAYS` 按 D2 为可写且无原因）。
- [ ] **T9b** **BOM 边界（评审 F6，必做）**：带 UTF-8 BOM 的 `.env` 会让**首个键静默失效**——
      实测 `DotEnvSettingsSource` 返回的键是 `'\ufeffmax_iterations'`（BOM 进了键名），
      生效值退化为字段默认（本例 `max_iterations`：文件写 123，实际取 50），**且无任何告警**。
      这与此前刚修过的 frontmatter / MEMORY.md BOM 缺陷族同源。要求：
      ①来源求解前剥离**文件头部 BOM** 再分层（读路径不写盘，盘上 BOM 保留）；
      ②若仍出现 BOM 前缀键，必须标注为「BOM 前缀导致不生效」而不是静默落 `default`；
      ③配测试：BOM + 非 BOM 两份 `.env` 的**同键来源与取值必须一致**。
- [ ] **T10** 负向验证：把来源判定改成「读层里的值」、去掉未知键单列、去掉空值行标注、换成变长掩码、
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
- **AC9** Given 全部 110 个字段，When 查询配置，Then 每一项都落在「可写」或「有明确 `read_only_reason`」之一，
  **不存在**既不可写又无原因的字段（**D3 裁定**后划分 = 46 白名单 + 64 排除、残留 0，由测试断言完备性）。
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
  ⇒ 白名单 **38 → 46 键**；划分完整性 = **110 = 46 白名单 + 64 排除，残留 0**（已实测）。
  ⚠️ **弱校验键的强制前提**：`Settings(_env_file=候选)` 构造成功对它们是**空门**（`retry_*` 只有 `Ge` 下界、
  `LOG_LEVEL` 连 metadata 都没有）⇒ 上述 5 键**必须**额外走字段级校验，否则写通道变成「挂死 / 无限重试」旋钮。
- **R1**：`system_env` 层在当前 shell 实测为 0 键；测试必须用 `monkeypatch.setenv` 构造，**不能**依赖开发机环境。
- **R2**：来源求解会构造 3 个 source 实例（含 2 次文件读）；面板每次请求的解析成本应实测并记录
  （若超过阈值，加进程内缓存 + 以 `.env` 指纹作键，缓存失效口径与 50-5 的指纹一致）。

## Requirement Traceability

FR-4；NFR-3, NFR-4, NFR-5, NFR-11；UX-DR2, UX-DR5；脊柱 I2, I9；brief §4 FR-4、§6.2、§6.9。
