# 上下文管理（`context/`）

> 状态：实现细节参考，自 [`framework.md`](../framework.md) **4.5** 迁出（2026-11-24 整理；编号不变，
> 其它文档里「4.5」的引用即指本页）。架构视角（项目定位 / 数据流 / 模块 DAG / 各模块职责与边界）见
> [`framework.md`](../framework.md)，安全立场（canonical）见 [§4.18](../framework.md#418-安全口径canonical)，
> 扩展页总索引见 [`frame/README.md`](README.md)。

## 4.5 上下文管理 (`context/`)

### loader.py — 上下文文件分层扫描

| 函数 | 说明 |
|------|------|
| `load_context_files(cwd, *, max_bytes=None, user_level=None, home=None)` | 分层扫描并渲染（无命中返回 None）；其余参数为测试/调用方覆盖，默认取 Settings |
| `collect_context_files(cwd, ...)` | 同上但返回结构化 `ContextBundle`（files/omitted/bytes_used），供断言层序与预算行为 |
| `_level_dirs(start, *, max_levels=8)` | 由外到内的目录链 `[仓库根, …, cwd]`；不在仓库内时为 `[start]` |

**分层发现语义（对齐 Codex 的 `AGENTS.md` 约定）**：①**仓库边界**——自 `cwd` 向上找 `.git`/`.hg`，命中即纳入该级并停止上溯（`max_levels=8` 超限则退化为单层，不做无界上溯）；不在仓库内时只扫 `cwd` 一层，**既有行为逐字节不变**。②**层序由泛到专**——仓库根在前、`cwd` 在后，同一层内保持既有优先级 `.heagent/CONTEXT.md` > `AGENTS.md` > `CLAUDE.md`；段落标题为相对最外层目录的 POSIX 路径（`## sub/AGENTS.md`），最外层即旧标签本身。③**用户级文件** `~/.heagent/AGENTS.md` 由 `CONTEXT_FILES_USER_LEVEL` 控制，**默认关闭**（全局文件静默影响每个项目，且会让测试依赖开发机 home）；标题固定渲染为 `~/.heagent/AGENTS.md`，不泄绝对路径。④**字节预算** `CONTEXT_FILES_MAX_BYTES`（默认 32768，Codex 同量级）——超预算时**近端优先**（越靠近 cwd 越具体），单段放不下但预算 ≥1024 字节时保留头部并按**悲观标记长度**预留，末尾追加 `… (truncated — kept the first N of M bytes)`；整段丢弃者汇总为一行 `(context files omitted: N — CONTEXT_FILES_MAX_BYTES=… exhausted; raise the budget to include: …)` 并打 `logger.warning`，**绝不静默**。坏编码文件按不可读处理并告警，不打断 run。

### tokens.py — Token 计量（真实 tokenizer + 在线校准，P0-3）

| 函数 | 说明 |
|------|------|
| `count_tokens(messages, *, model=None)` | 真实 tokenizer 优先，其次**校准后**的启发式；`model` 决定 encoding 与校准系数 |
| `note_actual_usage(model, *, estimated, actual)` | 用 provider 真实 usage 回收校准系数（指数滑动平均，按模型记录） |
| `tokenizer_backend(model)` / `calibration_factor(model)` | 当前后端名 / 当前系数（诊断与状态展示） |
| `reset_calibration()` | 清空系数与 encoding 缓存 |

后端口径由 `Settings.tokenizer`（`TOKENIZER`）控制：`auto`（默认）= 装了 tiktoken 就用真实
encoding（模型名不被识别时退 `cl100k_base`），否则用 CJK 感知启发式；`estimate` = 强制启发式；
`tiktoken` = 强制真实（依赖缺失时告警一次后回退）。encoding 按模型缓存（含「不可用」这一结果，
避免反复尝试导入）。

校准入口（2026-11-05 起两类）：主循环 `AgentLoop._call_provider` 与旁路调用经
`context.sidecall.send_accounted`（context 压缩 / 窗口重置 / goal 命名——此前直调
`provider.send` 零日志零样本，统计低估）。两者都在拿到真实 `usage.prompt_tokens` 时调用
`note_actual_usage`。坏样本被丢弃
（`actual<=0`，或比值超出 0.2~5），因为坏样本会把压缩阈值带偏。启发式路径返回
`round(raw × factor)`，两条路径量纲因此可比。

⚠ 计量结果直接喂给压缩阈值与窗口重置判定：偏差会放大成「该压缩时没压缩（撞 API 400）」
或「提前压缩、白丢上下文」，故不再满足于纯估算。

### sidecall.py — 旁路调用统一记账（2026-11-05）

主循环的模型调用自带日志与校准（`AgentLoop._call_provider`）；context 压缩、窗口重置、
goal 命名三类旁路此前直调 `provider.send`，在日志与统计里完全隐形。`send_accounted(provider,
messages, *, caller)` 是统一记账入口：估算 → 调用 → 计时 → 调用日志（格式对齐
`_call_provider`，caller 标签区分来源）→ 校准；usage 缺失显性告警、失败原样上抛，处置
（占位符/显性回退）归调用方。

### compressor.py — 上下文压缩

Token 用量 ≥ `compression_threshold` 时，通过 LLM 摘要旧消息，防止上下文窗口溢出。

摘要提示词为**结构化四段**（`STRUCTURED_SUMMARY_PROMPT`，公开名）：`## Goal` /
`## Changed files` / `## Todo` / `## Constraints and failures`，并要求标识符、路径、命令与
报错**逐字保留**。旧版只要「一段话 + 保留 key facts」，实测会把「改过哪些文件、还剩什么
没做」这类**可重放状态**揉成模糊叙述，压缩后接着干时容易重做已完成的改动或丢掉未完成的
步骤。`window_reset.py` 的 `DEFAULT_SUMMARY_PROMPT` 直接复用该常量（此前两处各写一份、仅
靠注释约定一致）。

### window_reset.py — 上下文窗口重置（checkpoint-resume）

Token 用量 ≥ 阈值（默认 0.6）时**清窗重建**：把整段对话压成一条进度摘要 + 原始 task + 续跑提示，
写入 `RunContext.metadata['progress_summary']/['segment']`（跨清窗存活），配合 `AgentLoop.resume()`
同 `run_id` 跨多段 context window 续跑。与 `compressor` **互斥**（运行期二选一，`AgentLoop.__init__`
断言，D3）——compressor 原位摘要保留 recent 消息，window_reset 更激进地整窗重置；摘要提示词与
compressor 一致。reset 不重置 iteration/accumulated（防绕预算）。`run`/`run_stream` 在工具消息追加后检查触发。
CLI 经 `CONTEXT_STRATEGY`（`compressor`/`reset`）二选一接线，`WINDOW_RESET_THRESHOLD` 控制重置触发阈值（见 cli.py `_build_context_strategy`）。

### session.py — 会话持久化

`.heagent/sessions/<session_id>.json` 存储/恢复**对话历史**（消息列表）。交互模式下通过 `session_id` 自动保存/恢复。

五条判据（与文件路径 / 并发写直接相关；边界地位见 §4.18）：

- **id 判据**：`^[a-zA-Z0-9_-]{1,128}\Z`（路径遍历防线）+ **Windows 保留设备名**拒绝（`WINDOWS_RESERVED_DEVICE_NAMES` 22 项 = CON/PRN/AUX/NUL + COM1-9 + LPT1-9；`NUL` 在字符集**之内**，放行即在 Windows 上写向空设备、静默丢整段对话）。网络层持同义镜像 `SESSION_ID_RESERVED_NAMES`（不得 import 运行栈，靠测试钉逐元素相等）；CLI `--resume` 在构造 provider 前用同一个`validate_session_id()` fail-fast。
- **写入**：`pub.persist.atomic_update_text`（跨进程锁 = 同目录 `<id>.json.lock`）。**写入路径刻意不删锁文件**（删除会让「B 等旧 inode、C 拿新文件」的经典竞态失效互斥）。
- **并发写（2026-09-27 修）**：运行落盘把「本次 run 起步时**磁盘上**的消息」作为**内容基线**传给
  `SessionStore.save(base=...)`。锁内若发现别的写者追加过消息，**不再整份覆盖**——把本次新增的消息接在
  对方新增的之后（两段都保留，`_merge_concurrent_writes`）；无法**安全**判定的形态（磁盘上的共享前缀
  被改写 / 比基线短 / 调用方给的基线对不上 / 文件不可解析）一律退回 last-write-wins 并记 WARNING
  ——最坏情况与改造前逐字一致。触发场景：CLI 与网页入口共享同一 `.heagent/sessions`，网页
  `POST /api/projects/{id}/runs` 不带 `session_id` 时取**最近**会话（往往正是 CLI 在写的那个）。
  SYSTEM 消息不参与比对（每次 run 重建、`load` 时会剔除），合并结果只保留本次 writer 的 SYSTEM。
- **回收**：`prune(retention_days)` 按 mtime 回收 `*.json`，并顺带用 `pub.persist.reap_dangling_locks`回收**孤儿锁**（三判据全中才删：同名记录已不存在 + 锁 mtime 超限 + `timeout=0` 非阻塞加锁证明无人持有）；`delete()` 不回收（新锁过不了年龄门槛）。
- **列表**：`list_metadata` 对超过 `MAX_SESSION_METADATA_BYTES`（1 MiB）的会话**只读头部**（`_read_head` 有界读 + 严格解码；`_metadata_from_head` 只在 `"messages"` **之前**的元数据区取值——落盘键序保证 `session_id`/`version`/`timestamp`/`title` 都在那里），`message_count` 退化为 `None`（D6 口径）。列表侧另有进程内**元数据备忘录**（键 = 文件名 + `mtime_ns` + `size`，未变更文件不重解析）；容量上限 `_META_CACHE_MAX_ENTRIES`（1024）溢出时按 FIFO 淘汰最旧一条，**不整表清空**（2026-11-26 改：整表 `clear()` 会让下一轮把上千份会话重新解析一遍）；**首次饱和**打一条 `session event=metadata_memo_saturated entries=1024 dir=…`（WARNING，只打一次）——饱和意味着会话总数已超上限、被挤掉的尾部每轮都会重新解析，是性能拐点而不是错误。

> 注意：另有一套 `engine/store.py` 的 `RunStore`（`.heagent/runs/<run_id>.json`）保存**单次运行快照**（含上下文 / 结果 / 最终答案），见 4.12。两者用途不同——session 是跨轮对话历史，RunStore 是单次 run 的可恢复快照。
