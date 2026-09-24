---
id: 50-5
title: 配置写入通道（白名单 / 保真写 / 备份 / 冲突 / 审计）
status: ready-for-dev
parent_epic: E50
priority: P0
phase: D（配置可编辑）
depends_on: [50-1, 50-2, 50-3, 50-4]
blocks: [50-6, 50-7]
created: '2026-09-23'
---

# Story 50-5：配置写入通道（白名单 / 保真写 / 备份 / 冲突 / 审计）

## 用户故事

作为控制台用户，我希望在显式开启的闸门之下保存**项目级非凭证**配置，失败时能恢复，
并且任何时候都清楚「这次保存什么时候生效」。

本 story 是整个 Epic 里风险最高的一环：它是唯一会**写用户既有文件**的能力，且写坏 `.env` 的代价是
「进程起不来」。因此流水线的每一步都必须是 fail-closed（不改文件即拒绝）。

## 侦察实证（2026-09-23）

| 事实 | 证据 | 含义 |
|---|---|---|
| 原子读改写 + 跨进程锁原语已具备 | `persist.atomic_update_text(path, update, *, lock_timeout=5.0)`（`persist.py:368`）；`atomic_write_text`（`:313`） | 10 步流水线不需要发明写原语 |
| **保真写的样本环境**（实测字节级） | 项目 `.env`：**4442 字节 / 77 行全 CRLF / bare LF = 0 / 无 BOM / 末行有换行 / 40 条 KV / 39 唯一键 / 1 个重复键（`SKILL_MAX_AUTO_INVOKE_TOKENS` ×2）/ 10 行内注释** | 保真断言的全部维度都来自这份真实样本 |
| 候选配置校验**可行** | 实测 `Settings(_env_file=<Path>)` 与 `Settings(_env_file=[a, b])` 均work；指向只含 `MAX_ITERATIONS=42` / `LOG_LEVEL=DEBUG` 的临时文件 → 两个字段分别取到 42 / `DEBUG` | I6 的「先构造再落盘」可落地 |
| **回环判定已可直接复用，且边界已验证** | `network.exposure.is_loopback_host()`；实测 11 种输入：`127.0.0.1` / `127.0.0.2` / `::1` / `[::1]` / `localhost` / **`::ffff:127.0.0.1`（IPv4 映射形式）** / `[::ffff:127.0.0.1]` 全为 `True`；`0.0.0.0`、`192.168.1.10`、`::ffff:192.168.1.10`、空串全为 `False` | 本机 Python 3.13.5。**注**：曾假设「IPv4 映射形式会被误判为非回环」——**实测证伪**（`ipaddress` 已处理 `ipv4_mapped`），故不需新增适配分支；此结论必须写进测试以防未来回归 |
| 白名单成立但有 1 处模式冲突、12 个未分类键 | 原 v1 **38 键**全部存在于 `Settings`；`SANDBOX_DIR_RETENTION_DAYS` 同时命中 `SANDBOX_*`；12 键既不在白名单也无排除原因（清单见 50-4）。**D2/D3 裁定后：白名单 46 键、残留 0**（已实测） | 写入白名单必须**显式枚举 + 优先级明确**（D2），且与 50-4 用**同一份常量**；弱校验键须补字段级守卫（D3） |
| 字段名 vs env 名 | `Settings.model_fields` 是**小写**字段名、**零 alias**；env 键为大写 | 白名单以大写 env 键表达，映射用 `.upper()`（**不要** `model_fields["UPPER"]`） |
| 备份/审计落点已在 `WorkspacePaths` | 脊柱 §3.1：`config_backups = .heagent/backups/env`、`console_dir = .heagent/console`（`audit.jsonl`）；两者已进 50-1 的 deny 集合（I14） | 备份与审计天然不可被工具读入上下文 |
| `.env.example` 的键多以注释行存在（110 键中仅 11 行是活键） | 字节级实测 | 50-7 的文档同步必须跟随注释风格 |

## 范围

- 新增顶层模块 `src/heagent/envfile.py`：`.env` **行级保真**读写（定位键、替换/追加、EOL/BOM/注释保真、指纹、备份）。
- 配置写入的 10 步流水线（脊柱 §8 顺序固定）。
- 备份与审计的落点、上限、保留期；写通道额外要求本机回环来源。
- 生效语义 = 下一次 run（在途 run 继续用旧快照）。
- `HTTP_CONSOLE_WRITE_ENABLED`（默认 `False`）与 `HTTP_CONSOLE_PROJECTS_FILE` 两个新设置键。

## 边界与约束

**Always**

- 顺序固定、任一步失败即拒绝：闸门 → 来源 → 键白名单 → 值校验 → 指纹冲突 → 候选构造 → 备份 → 原子写 → 回读 → 审计。
- 保真：只替换目标行；其余行、EOL（CRLF/LF）、BOM 状态、注释、空行、**未修改行的字节**逐一不变。
- 键在文件中不存在 → 以**既有文件**的 EOL 风格追加；不改动任何既有行。
- 写入前备份到 `paths.config_backups`（时间戳 + 指纹前缀，条目数与保留期有上限）；备份**不提供**任何网页下载端点。
- 审计一行 JSONL 到 `paths.console_dir/audit.jsonl`：时间 / 来源 / 键名 / 旧新值**哈希与长度** / 结果，**不含值**。
- 候选必须能被 `Settings(_env_file=<候选临时文件>)` 成功构造，否则 `invalid_value`（把「写坏 = 起不来」前移）。
- 只改**项目 `.env`**；全局 `~/.heagent/.env` 永久只读（I4）。

**Never**

- 不接受任意文件路径（只认项目 `.env`）。
- 不在响应 / 错误 / 日志 / 审计里出现值本身或任何凭证明文（I9）。
- 不写入凭证、监听面（`HTTP_*`/`TCP_*`）、**沙箱执行姿态**（`SANDBOX_*` 中除 `SANDBOX_DIR_RETENTION_DAYS` 外）、
  进程拉起开关、路径类、控制台自身开关、未知键。
- 不声称「立即生效」；不改动在途 run 已冻结的快照（I10）。
- 不让网页用任何请求打开 `HTTP_CONSOLE_WRITE_ENABLED`（I12）——它只能由服务启动配置决定。
- 不在回读校验失败时留下半写状态：必须恢复备份并显式报错。

## 任务（细分）

- [ ] **T1** `envfile.py`：`parse_index(text)`（逐行定位键、记录重复键的**最后一行**、识别注释/空行、记录 EOL 与 BOM 状态）；
      `fingerprint(bytes) -> str`（sha256）；`replace_or_append(text, key, value) -> str`（**保真**：只重写目标行，
      EOL 跟随文件，BOM 保留，追加时附带文件既有 EOL 风格）；纯函数 + `bytes` 出入，便于逐字节单测。
      ⚠️ **评审 F6**：`parse_index` 必须剥离**首行 BOM** 再取键名——否则首个键定位不到（键名变成
      `\ufeffMAX_ITERATIONS`）⇒ 会「追加一条重复行」而不是替换既有行，盘上留下一条永不生效的死行。
- [ ] **T2** 备份：`backup(path, backups_dir, fingerprint)` → 文件名含时间戳与指纹前缀；清理走既有 `prune_entries_by_mtime`
      内核（`persist`），上限与保留期写成常量并落 `WorkspacePaths`。
- [ ] **T3** 审计：`append_audit(console_dir, record)`（JSONL，原子追加，失败只 WARNING 不阻断已成功的写——
      与 ledger 回写失败的立场一致，但**失败必须在响应里体现为「审计未记录」**，不得静默）。
- [ ] **T4** 流水线 10 步实现（`config_write.py` 或 `config_catalog.py` 的写侧；由入口层注入到协议 handler）：
      闸门（`HTTP_CONSOLE_WRITE_ENABLED`）→ 回环（`is_loopback_host(request.client.host)`）→ 白名单
      （与 50-4 同一常量）→ 值校验（pydantic + `ROUTING_POOLS` 池解析）→ 指纹 → 候选构造（`Settings(_env_file=候选)`）
      → 备份 → `atomic_update_text` → 回读（重读 + 解析 + 指纹）→ 审计。
- [ ] **T5** 设置新增：`http_console_write_enabled: bool = False`、`http_console_projects_file: str | None = None`；
      两者进 `ResolvedRuntimeConfig`；`.env.example` 同步（50-7 收口，本 story 先加键）；
      **并**纳入 50-4 的「控制台自身」排除组（只读、给原因）。
- [ ] **T6** 写入白名单常量：显式枚举 **46 键**（与 50-4 共用同一常量），并定义**优先级**（**D2**：显式白名单 > 模式排除）。
- [ ] **T6b** **弱校验键的字段级守卫（D3 强制前提）**：`LOG_LEVEL` / `LOG_FILE_LEVEL` 限定枚举
      `{DEBUG,INFO,WARNING,ERROR,CRITICAL}`（空 = 回退）；`RETRY_MAX_ATTEMPTS ≤ 10`、`RETRY_BASE_DELAY ≤ 60`、
      `RETRY_MAX_DELAY ≤ 600`。**理由**：实测 `Settings(_env_file=候选)` 对弱校验字段是**空门**
      （`retry_*` 仅 `Ge` 下界、`LOG_LEVEL` 无 metadata）⇒ 只靠 I6 会让写通道变成「挂死 / 无限重试」旋钮。
      守卫失败一律 `invalid_value` + 字段级原因，文件不变。
- [ ] **T7** `PUT /api/projects/{id}/config`：`{changes:[{key,value}], fingerprint}`；错误码
      `write_disabled` / `loopback_required` / `field_not_writable` / `invalid_value` / `config_conflict` /
      `config_write_failed`；成功响应含新指纹与新值来源（供 UI 刷新徽标）。
- [ ] **T8** 生效语义：写成功后把该项目运行时的**配置代（generation）**标记过期；下一次 run 重新解析快照，
      在途 run 继续用旧快照（I10）。配一条端到端测试钉住「当前 run 用旧值 / 下一次用新值」。
- [ ] **T9** 测试（覆盖 9 类拒绝 + 弱校验守卫 + 保真 + 恢复）：闸门关闭 / 白名单成功 / 新增键追加 / 凭证键 /
      监听面键 / **沙箱执行姿态键**（`SANDBOX_BACKEND`、`SANDBOX_MODE`、`SANDBOX_FIREJAIL_PATH`…；注意
      `SANDBOX_DIR_RETENTION_DAYS` 按 **D2** 属**可写**，测试须断言其成功）/ 进程拉起开关 / 路径类 /
      控制台自身开关 / 未知键 / 非法值（类型、越界、**弱校验键的枚举与上界**：`LOG_LEVEL=BANANA`、
      `RETRY_BASE_DELAY=1e9`、`RETRY_MAX_ATTEMPTS=1000000`）/ list 字段 / 非法 JSON 的 `ROUTING_POOLS` /
      指纹冲突 / 备份与审计内容（无值）/ 回读失败恢复 / 非回环来源拒绝 / 生效语义端到端 /
      **系统 env 覆盖键被拒**（评审 F1：与面板 `writable=false` 同源）/ **BOM 首行替换而非追加**（评审 F6）。
- [ ] **T10** 保真逐字节断言：以真实样本形态构造（CRLF + 无末行换行 + 行内注释 + 重复键 + BOM 四个变体），
      断言「未修改行字节不变」；BOM 变体断言 **BOM 保留**。
- [ ] **T11** 负向验证：去掉白名单过滤、去掉指纹校验、去掉备份、把备份目录移出 deny 集合、把回读校验短路——
      对应测试**逐条必须变红**后复原。

## 验收标准

- **AC1** Given `HTTP_CONSOLE_WRITE_ENABLED` 未开启（默认），When 客户端提交任何配置写入，Then 返回 `write_disabled`，
  文件不变，且**网页无法通过任何请求开启该开关**。
- **AC2** Given 开关已由服务启动配置开启，When 客户端提交白名单内的键与新值，Then 值经 pydantic 校验后
  **保真原子写**入项目 `.env`：只有目标行被替换，其余行、行尾（CRLF/LF）、BOM 状态、注释与空行逐字节不变。
- **AC3** Given 待写入的键在项目 `.env` 中不存在，When 保存成功，Then 该键以既有文件的 EOL 风格追加，
  不改动任何既有行。
- **AC4** Given 请求包含凭证键、监听面键（`HTTP_*`/`TCP_*`）、**沙箱执行姿态键**（`SANDBOX_BACKEND` / `SANDBOX_MODE` /
  `SANDBOX_NETWORK` / `SANDBOX_ENFORCE` / `SANDBOX_FIREJAIL_PATH` 等；`SANDBOX_DIR_RETENTION_DAYS` 按 **D2** 可写，不在此列）、
  进程拉起开关、路径类键、`HTTP_CONSOLE_*` 自身开关或任何未知键，When 提交，Then 返回 `field_not_writable` 并指明原因，文件不变。
- **AC5** Given 值非法（类型不符、越界、非 JSON 的 list 字段、非法 JSON 的 `ROUTING_POOLS`），When 提交，
  Then 返回 `invalid_value` 与字段级原因，文件不变；校验通过 `Settings(_env_file=<候选临时文件>)` 复验。
  **重要（D3）**：候选构造只是**必要条件**——它对弱校验字段是**空门**，因此 `LOG_LEVEL` / `LOG_FILE_LEVEL` /
  `RETRY_*` 还必须过 T6b 的字段级守卫；AC 覆盖 `LOG_LEVEL=BANANA`、`RETRY_BASE_DELAY=1e9`、
  `RETRY_MAX_ATTEMPTS=1000000` 三个「能通过构造校验但必须被拒」的反例。
- **AC6** Given 客户端持有的文件指纹与服务端当前文件不一致（外部编辑器改了 `.env`），When 提交，
  Then 返回 `config_conflict`，**不覆盖**对方的修改，并提示重新加载。
- **AC7** Given 一次成功写入，When 检查磁盘，Then 存在写前备份（落在项目状态根内、按敏感配置处理、
  不提供网页下载、有条数与保留期上限）与一条审计记录（含时间、来源、键名、旧/新值哈希与长度，**不含**值本身与任何凭证）。
- **AC8** Given 写入过程中磁盘失败或回读校验不匹配，When 错误发生，Then **自动恢复原文件内容**并向客户端显式报告失败。
- **AC9** Given 一次成功保存，When 当前正在运行的任务继续执行，Then 它仍使用旧快照；下一次运行解析到新值，
  UI 明确显示「下一次运行生效」。
- **AC10** Given 写通道被非回环来源访问，When 提交配置写入，Then 返回 `loopback_required` 且不产生任何副作用
  （文件、备份、审计三者都不变）。
- **AC11** Given 项目 `.env` 带 UTF-8 BOM 且待写键位于**首行**，When 保存成功，Then 该行被**替换**（不是追加），
  BOM 仍保留在文件头，且全文未修改行逐字节不变（评审 F6）。
- **AC12** Given 某个**在白名单内**的键当前由**系统环境变量**提供（面板显示 `writable=false`），
  When 客户端仍提交写入该键，Then 服务端返回 `field_not_writable`（与面板同一判定、同一常量）且文件不变，
  **不得**只靠 UI 禁用（评审 F1：实测系统 env 存在时候选文件里的同名值**根本不会被解析**，
  候选构造校验拦不住它 ⇒ 若放行，写进去的是「当下无效、日后生效」的坏值）。

## Definition of Done

**交付物**：`src/heagent/envfile.py`（新增）、写入流水线模块（新增或并入 `config_catalog.py` 写侧）、
`src/heagent/config.py`（2 个新键）、`src/heagent/network/http_server.py`、
`tests/test_envfile.py`（新增）、`tests/test_config_write.py`（新增）、`tests/network/test_http_console_config.py`。

**验证命令**（实测存在性已核对）：

```bash
pytest tests/test_envfile.py tests/test_config_write.py tests/test_config.py tests/network -q
pytest -q
ruff check src tests && mypy src && mypy src --platform linux
```

**负向验证**：T11 的 5 项回退各自精确变红；**另需**对真实开发机 `.env` 的**副本**跑一次保真写演练
（CRLF / 重复键 / 内联注释三处最容易出错），断言未修改行字节一致。

**质量门**：`pytest`、`ruff check`、`ruff format --check src tests`、`mypy src`、`mypy src --platform linux` 全绿。

## 代码地图

| 路径 | 角色 | 改动 |
|---|---|---|
| `src/heagent/envfile.py` | **新增** 行级保真读写 + 指纹 + 备份 | 依赖 `persist`；**不**依赖 `config`/engine/agent/入口层 |
| `src/heagent/config_catalog.py` | 白名单常量（与 50-4 共用） | 写侧判定复用只读侧同一常量 |
| `src/heagent/config.py` | 设置 | 新增 2 键（默认关） |
| `src/heagent/network/http_server.py` | 路由 | `PUT .../config` + 回环门 |
| `src/heagent/network/http_console_protocol.py` | 协议 | 写入请求/响应模型 |
| `tests/test_envfile.py` | **新增** | 逐字节保真（CRLF/BOM/注释/重复键/无末行换行） |
| `tests/test_config_write.py` | **新增** | 10 步流水线 9 类拒绝 + 恢复 + 生效语义 |

## 风险与未决

- **D2（已裁定 2026-09-24，见脊柱 §15）**：**显式白名单优先于模式排除**（`SANDBOX_DIR_RETENTION_DAYS`
  因此可写，而 `SANDBOX_BACKEND` / `SANDBOX_MODE` / `SANDBOX_FIREJAIL_PATH` 等**执行姿态键**仍只读）。
- **D4（已裁定 2026-09-24，见脊柱 §15）**：写闸门**允许任何启动配置渠道**开启（系统环境变量 / 项目 `.env` /
  全局 `.env`）+ 可选 CLI 开关；**启动时**打一条「写通道已开启，任何能连上该端口的人都能改项目 `.env`」
  的高亮告警（stderr + 日志）。**硬约束不变**：网页任何请求都开不了它（它已在排除组，写通道改不到自己）。
- **R1**：审计追加失败的处理已定（T3）：不阻断已成功的写，但**响应必须体现**，否则会给人「已审计」的错觉。
- **R2**：`.env` 的**权限位**（Windows ACL / POSIX mode）在备份与被替换文件上的继承行为未逐项验证；
  实现时至少核实「写入后文件权限不变」，并把结论写进实现记录（若平台差异明显则记为已知缺口）。
- **R3**：多进程并发（CLI 同时改同一 `.env`）依赖 `atomic_update_text` 的跨进程锁 + 指纹校验双保险；
  需一条「两进程同时写、只有一个成功」的测试（可用两个线程 + 文件锁超时模拟，避免引入 flaky 的进程测试）。

## Requirement Traceability

FR-5；NFR-4–NFR-9, NFR-11；UX-DR3, UX-DR4；脊柱 I4, I5, I6, I7, I8, I9, I10, I12；brief §4 FR-5、§6.1–6.3、§6.6、§7 D1/D4。
