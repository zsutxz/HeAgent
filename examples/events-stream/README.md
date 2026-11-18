# 示例：订阅事件流

演示如何拿到一轮 run 的**结构化轨迹**：订阅 `EngineContainer.events`（`EventBus`），
在观察者里收集事件。

## 运行

```bash
python examples/events-stream/main.py
```

不需要网络。

## 期望输出

```text
答案: 2 + 3 = 5
收到 12 条事件：
  - run_started iter=0 tool=-
  - iteration_started iter=1 tool=-
  - provider_call_started iter=1 tool=-
  - provider_call_completed iter=1 tool=- duration_ms=<ms>
  - tool_batch_started iter=1 tool=-
  - tool_call_started iter=1 tool=add
  - tool_call_completed iter=1 tool=add duration_ms=0
  - tool_batch_completed iter=1 tool=-
  - iteration_started iter=2 tool=-
  - provider_call_started iter=2 tool=-
  - provider_call_completed iter=2 tool=- duration_ms=0
  - run_completed iter=2 tool=- duration_ms=<ms>
```

两个 `<ms>` 是运行时实测值（每次不同）：stub Provider 不做网络 I/O，所以前两个通常是个位数毫秒；
`run_completed` 的 `duration_ms` 是整轮 run 的墙钟耗时。事件条数（12）与顺序稳定，不必逐字比对耗时。

## 事件形状

```python
EngineEvent(
    event_type="tool_call_completed",          # 事件名，稳定判据
    timestamp="2026-01-01T00:00:00+00:00",     # ISO 时间（示例值）
    run_id="3f2a1c",                           # 关联 run（示例值）
    iteration=1,                               # 第几轮迭代
    tool_name="add",                           # 只有工具事件才非空
    target="/tmp/demo.txt",                    # 作用对象：文件 / 命令 / 子 Agent 角色
    details={"duration_ms": 7, "mode": "direct"},  # 自由扩展字段
)
```

常用事件：

| 事件 | 关键 `details` |
| --- | --- |
| `run_started` / `run_completed` | `duration_ms`（仅 completed） |
| `iteration_started` | — |
| `provider_call_completed` | `model` / `duration_ms` / `prompt_tokens` / `completion_tokens` / `actual_tokens` |
| `tool_call_completed` / `tool_call_failed` | `duration_ms` / `mode` |
| `tool_call_blocked` | `reason` / `mode`（`safety_blocked` 表示被 `SafetyGuard` 拦下） |
| `context_compressed` | `before` / `after` |

## 三条纪律

1. **观察者必须轻**：`handle` 在调用方协程里同步派发，阻塞会直接拖慢主循环。
   要写文件/发网络请求就投递到队列，另起消费者。
2. **异常不外溢**：观察者抛异常会被 `EventBus` 捕获并记日志，不影响其它观察者，也不中断 run
   ——所以别把「观察者没跑」当成 run 的失败原因，去日志里找 `Event observer failed`。
3. **有界缓冲**：`EventBus` 只保留最近 `retain`（默认 200）条；要长期留证据就开
   `EVENTS_ROLLOUT_ENABLED=true` 落盘到 `.heagent/runs/<run_id>/rollout.jsonl`，
   再用 `heagent replay --json <file>` 回放。
