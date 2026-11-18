# 性能调优指南

本页回答三件事：**怎么测**、**时间花在哪**、**调哪个键**。所有默认值与键名以 `.env.example` 为准，
benchmark 命令与 [文档索引的「性能基准」节](README.md#性能基准)同源——那里给命令，这里给判读与调参。

> 本页不给「绝对值多少毫秒」的承诺：同一段代码在不同机器、不同 Provider、不同网络下差一个数量级是常态。
> 可复现的只有**相对判据**（同机前后对比、同 benchmark 基线对比）。

## 一、分析方法

三层，从便宜到贵。先用第一层定位「哪一段慢」，再决定要不要往下走。

### 1. 从事件流拿分段耗时（最快，零依赖）

一次 run 的分段耗时全在事件 `details.duration_ms` 里：

| 事件 | 关键 `details` | 说明 |
| --- | --- | --- |
| `provider_call_completed` | `duration_ms` / `model` / `prompt_tokens` / `completion_tokens` / `actual_tokens` | **一次 LLM 往返**的 wall time（含中间件链） |
| `tool_call_completed` / `tool_call_failed` | `duration_ms` / `mode` | 单个工具执行的耗时；`mode` 取值 `direct` / `sandbox_required` / `approval_required` |
| `context_compressed` | `before` / `after`（token） | 压缩触发点；压缩本身是一次**旁路 LLM 调用**，只在日志的 provider 调用里可见 |
| `run_completed` | `duration_ms` | 整轮 run |

```bash
# 落盘开启时逐条看（EVENTS_ROLLOUT_ENABLED=true）；--json 才有事件名，默认渲染成人读行
heagent replay --json .heagent/runs/<run_id>/rollout.jsonl | grep -E "provider_call_completed|tool_call_completed"
```

判读要点：

- **单次 run 的总耗时 ≈ provider 调用耗时之和 + 工具耗时之和 + 剩余开销**。剩余开销通常很小；
  若它对不上，先看是不是**并发工具**（一批工具并行执行，耗时不是简单相加）。
- `duration_ms` 是 `perf_counter` 单调钟，不受系统时钟调整影响。
- 同一 prompt 连续两次的 `provider_call_completed.duration_ms` 差异主要来自上游，不是你改的代码。

### 2. 用 benchmark 建基线（回归判据）

`tests/test_benchmarks.py` 有 14 个用例，覆盖 token 估算、上下文压缩、工具注册、技能匹配、
大消息列表、单次迭代、8 个并发工具、恢复历史、rollout 写 50 事件。

```bash
# 只列用例，看有没有跑偏
python -m pytest -m benchmark -q --co

# 入库基线
python -m pytest -m benchmark -q --benchmark-autosave --benchmark-storage=./benchmark-data

# 与基线对比，劣化超过 50% 即判失败（`0001` 是示例 save id，换成你目录里的实际值）
python -m pytest -m benchmark -q --benchmark-storage=./benchmark-data \
    --benchmark-compare=0001 --benchmark-compare-fail=min:50%
```

`./benchmark-data/` 下的目录名形如 `0001_<sha>_<ts>_<changes>.json`；`--benchmark-autosave` 每入库一次
就多一个新编号，所以对比时要用**你要比的那一次的编号**，不能一直写 `0001`。

- `benchmark` 标记在 `pyproject.toml` 的 `addopts` 里被 deselect ⇒ 普通 `pytest` 不跑它们。
- `--benchmark-autosave` / `--benchmark-storage` / `--benchmark-compare` **只认命令行旗标**
  （pytest-benchmark 不从 `pyproject.toml` 读这些设置），写进配置不会生效。
- 基线目录 `./benchmark-data/` 是本地产物、已在 `.gitignore` 里。

### 3. 单点 profile（定位热点）

benchmark 告诉你「慢了」，profile 告诉你「慢在哪一行」。仓库自带 `scripts/profile_run.py`
（标准库 `cProfile`，零新依赖），报告含「按 tottime 排的热点函数」+「按 cumtime 排的调用表」：

```bash
# 剖面一个模块；`--` 之后原样转给目标
python scripts/profile_run.py --module pytest -- tests/test_agent_loop.py -q
python scripts/profile_run.py --module heagent -- "用一句话解释 asyncio"

# 剖面一个脚本，并指定报告落点 / 表格深度
python scripts/profile_run.py --script scripts/collect_stats.py --out .heagent/tmp/cli.prof.txt --top 40
```

报告默认落 `.heagent/tmp/profile-<时间戳>.txt`，stdout 同时打热点摘要（不打开文件就能看）。

异步/等待占比高时，cProfile 会把时间算在 `await` 处，此时改用采样型 profiler attach 到**运行中的进程**
（需自行安装 `py-spy`，且容器内通常要 `--cap-add SYS_PTRACE`）：

```bash
py-spy record -o .heagent/tmp/heagent.svg --pid <PID>   # 火焰图
py-spy top --pid <PID>                                  # 实时热点
```

**不要**用 profile 结果做绝对性能判断——插桩本身会放大耗时。

## 二、常见瓶颈

按「可观测的现象」列，每条给判据与对策去向。

| 现象 | 观测点 | 判据 | 对策 |
| --- | --- | --- | --- |
| 一轮 run 慢，但工具很快 | `provider_call_completed.duration_ms` 占比 | LLM 往返占 80%+ | 属正常；想快就换更快的模型或档位（[四、参数](#四参数说明与推荐值)的 `ROUTING_POOLS`） |
| 同一模型越跑越慢（每轮更久） | `provider_call_completed.prompt_tokens` 逐轮上涨 | 输入 token 线性增长 | 开压缩（`CONTEXT_STRATEGY=compressor`）或降 `MAX_CONTEXT_TOKENS`；见 `context_compressed` 事件是否触发 |
| 压缩后反而更慢 | 日志里出现额外的旁路 provider 调用 | 一次压缩 = 一次完整 LLM 调用 | 压缩是**用一次调用换后续多轮更短**；短会话里不划算，可提高 `COMPRESSION_THRESHOLD` |
| 工具调用挤在一起、没有并发 | `tool_call_completed` 时间戳重叠度 | 一批调用串行完成 | 并发由 AgentLoop 按批执行；如果是同一个长 `shell`，只能拆命令 |
| 首轮启动慢 | 进程启动到第一条 `provider_call_started` | 数秒级 | 多为导入开销与上下文文件扫描；`CONTEXT_FILES_MAX_BYTES`、技能库规模是主因 |
| 磁盘 I/O 抖动 | `EVENTS_ROLLOUT_ENABLED=true` 时每 run 写 `rollout.jsonl` | 高频写盘 | 不需要回放就保持 `false`（默认）；要留证据时再开 |
| SSE 断线后客户端频繁重同步 | `resync_required`（409） | 环形缓冲被覆盖 | 调大 `HTTP_EVENT_BUFFER_SIZE`（默认 512 条/run） |
| 长任务被误杀 | 请求以超时结束 | `HTTP_IDLE_TIMEOUT`（默认 300 秒无事件即判卡死）命中；`HTTP_REQUEST_TIMEOUT` 只在显式设过非 0 值时才生效 | 「跑得久」不等于「卡死」：保持 `HTTP_REQUEST_TIMEOUT=0`，调大 `HTTP_IDLE_TIMEOUT` |
| 重试把故障放大成延迟 | 日志里同一请求多次 `provider_call_started` | `RETRY_MAX_ATTEMPTS` × `RETRY_MAX_DELAY` | 上游不稳时降 `RETRY_MAX_ATTEMPTS`、或把池内档位换到可用模型 |

## 三、优化建议

按「先做收益最大的」排序：

1. **先量再改**：没有 `duration_ms` 与 benchmark 基线之前，任何「优化」都是猜测。
2. **把 LLM 往返降下来**：路由池按难度分档（`ROUTING_POOLS` 的 fast/mid/pro），简单任务不必走 pro。
3. **控制上下文增长**：压缩策略 + 合理的 `MAX_CONTEXT_TOKENS`；窗口开得比模型真实窗口大不会更快，
   只会让阈值永不触发、先撞上游 400。
4. **别让技能自动注入吃满预算**：`SKILL_MAX_AUTO_INVOKE` / `SKILL_MAX_AUTO_INVOKE_TOKENS`
   约束「自动注入几个、共多少 token」；预算越大，每轮输入越长。
5. **关掉不用的可观测能力**：`EVENTS_ROLLOUT_ENABLED`（默认关）、`CRON_ECHO_TO_TERMINAL`、
   `ANNOUNCE_PROGRESS`（只影响 stderr 呈现，不影响 LLM 耗时）。
6. **长任务用空闲判据而不是总时长**：`HTTP_REQUEST_TIMEOUT=0`（不限总时长）+ `HTTP_IDLE_TIMEOUT`
   （默认 300 秒无事件才判卡死）+ `HTTP_TOOL_INFLIGHT_TIMEOUT`（默认 3600 秒，单个在途工具）。
7. **并发上限按真实现场调**：`HTTP_MAX_CONNECTIONS` / `HTTP_MAX_SUBSCRIBERS` /
   `HTTP_MAX_INFLIGHT_RUNS` 调大之前，先确认宿主机与 Provider 配额撑得住——超额只会把排队变成 429。

## 四、参数说明与推荐值

「推荐」列给的是**常见场景的起点**，不是最优解；「何时改」列才是判据。

### 上下文与 token

| 键 | 默认 | 推荐起点 | 何时改 |
| --- | --- | --- | --- |
| `MAX_CONTEXT_TOKENS` | `512000` | 与所用模型的真实窗口一致 | 换小窗口模型（本地 Ollama 尤其）时必须下调，否则压缩阈值永不触发 |
| `COMPRESSION_THRESHOLD` | `0.8` | `0.8` | 短会话多、压缩开销占比高时上调；长会话精度优先时下调 |
| `CONTEXT_STRATEGY` | `compressor` | `compressor` | 需要保留原文时改 `reset`（清窗后 resume，代价是丢上下文） |
| `WINDOW_RESET_THRESHOLD` | `0.6` | `0.6` | 仅 `reset` 策略生效；与 `COMPRESSION_THRESHOLD` 不要设成同值，否则两条路径同时触发 |
| `TOKENIZER` | `auto` | `auto` | 日志行 `Provider response: … (estimated: …, delta: …)` 的 `delta` 持续偏大时改 `tiktoken`（需装依赖） |
| `MAX_OUTPUT_TOKENS` | 未设 | 按模型给（如 `4096`） | 不设时整行注释掉——留空会解析失败；本地思考模型建议显式设小 |

### 技能、记忆与上下文文件

| 键 | 默认 | 推荐起点 | 何时改 |
| --- | --- | --- | --- |
| `SKILL_MATCH_THRESHOLD` | `0.3` | `0.3` | 误触发（无关却注入）时上调；漏触发时下调 |
| `SKILL_MAX_AUTO_INVOKE` | `3` | `3` | 技能库大、每轮注入过多时下调到 1-2 |
| `SKILL_MAX_AUTO_INVOKE_TOKENS` | `8192` | `8192` | 注入预算是输入侧成本主项，长会话紧时下调 |
| `MEMORY_INJECT_MAX_BYTES` | `98304` | `98304` | 记忆条目多时下调；`0` = 不限（不推荐长期用） |
| `CONTEXT_FILES_MAX_BYTES` | `32768` | `32768` | 仓库根有多份大 `AGENTS.md` 时下调 |

### 重试与超时

| 键 | 默认 | 推荐起点 | 何时改 |
| --- | --- | --- | --- |
| `RETRY_MAX_ATTEMPTS` | `3` | `3` | 上游频繁 5xx 时下调以免放大延迟；不稳但必要场景上调 |
| `RETRY_BASE_DELAY` / `RETRY_MAX_DELAY` | `1.0` / `30.0` | 保持 | 与上游限流窗口对齐时再改 |
| `HTTP_REQUEST_TIMEOUT` | `0` | `0` | 保持 0：长任务别用墙钟杀，用下面的空闲判据 |
| `HTTP_IDLE_TIMEOUT` | `300` | `300` | 单轮工具可能长时间无事件时上调 |
| `HTTP_TOOL_INFLIGHT_TIMEOUT` | `3600` | `3600` | 有超过 1 小时的单工具（大数据导出等）时上调 |

### 迭代预算

| 键 | 默认 | 推荐起点 | 何时改 |
| --- | --- | --- | --- |
| `MAX_ITERATIONS` | `50` | `50` | 复杂任务迭代不够时上调；上调会放大失控成本 |
| `SUBAGENT_MAX_ITERATIONS` | `20` | `20` | 子 Agent 提前收尾时上调 |
| `SUBAGENT_MAX_DEPTH` | `3` | `3` | 层数越深，失败面与延迟越难预测 |

### 并发与缓冲

| 键 | 默认 | 推荐起点 | 何时改 |
| --- | --- | --- | --- |
| `HTTP_MAX_INFLIGHT_RUNS` | `1` | `1` | 多用户/多标签页共用服务时上调，同时看 `HTTP_MAX_TOTAL_INFLIGHT` |
| `HTTP_EVENT_BUFFER_SIZE` | `512` | `512` | 客户端断线频繁且事件密集时上调（内存换重连成功率） |
| `HTTP_RUN_HISTORY_SIZE` | `64` | `64` | 需要更久的 run 回看时上调 |

## 五、测试方法

一次完整的性能验证闭环：

```bash
# 1) 门禁先绿（性能改动不得引入功能回归）
python -m pytest -q

# 2) 建/续基线（同机、同 Python 版本、无其他负载）
python -m pytest -m benchmark -q --benchmark-storage=./benchmark-data --benchmark-autosave

# 3) 改完再对比，超 50% 判失败
python -m pytest -m benchmark -q --benchmark-storage=./benchmark-data \
    --benchmark-compare=0001 --benchmark-compare-fail=min:50%
```

判读规则：

- **对比的是同机同版本**：换机器、换 Python、换依赖版本后旧基线不再可比，要重新入库。
- **噪声识别**：`min:50%` 是数量级守护，不是精度守护；单个用例抖动 20% 属常见，看同一类用例
  是否整体漂移。
- **异步基准要跑在独立 event loop**：`tests/test_benchmarks.py` 用 `_sync` helper 桥接，
  自己写新基准时沿用同一形态，不要在已运行 loop 里嵌套。
- **拿 benchmark 与真实 run 对照**：benchmark 用 stub provider，量的是本仓代码；真实 run 的
  `provider_call_completed.duration_ms` 主要反映上游。两者别混为一谈。
