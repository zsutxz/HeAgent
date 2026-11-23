---
type: review
code: E76-R2
epic: epic-76-remote-surface-closeout
review_loop_iteration: 0
lens: 不变量与守卫（反证式）
reviewed_at: 2026-11-23
head: 3ef5be81
---

# E76 收口三审 · R2 不变量与守卫

## 范围与方法

- 对本 epic 新增/触及的**每条守卫**做反证：注入缺陷后判据必须变红，回退后恢复绿。
- 反证 1（当轮实跑）：`_warn_external_without_sandbox` 顶部插入 `return None` ⇒ `test_external_listener_on_a_non_docker_backend_warns_exactly_once` **FAILED**；回退 ⇒ `1 passed`。
- 反证 2（当轮实跑）：`_assert_single_adapter` 新增 `assert "sandbox_backend" in calls[0]` 前，两条装配路径用例**在入口漏传时仍绿**；补断言后 17 passed。

## 守卫清单与裁定

| # | 守卫 | 判据位置 | 反证结果 | 裁定 |
|---|---|---|---|---|
| G1 | `external` + 非 docker 恰 1 条 WARNING | `tests/test_cli_http_lifecycle.py:600/619` | 注入即红 | 有效 |
| G2 | 判据取**生效**档位（不是请求值） | 同上 + `http.py` 两条装配路径 | 入口漏传时原本不红，补断言后红 | 有效（当轮补强） |
| G3 | 项目名额双层不占 `run_conflict` 名额 | `tests/network/test_ws_project_admission.py` | 三码分别断言 | 有效 |
| G4 | cursor 续流首帧 ≤ N+1 且连续 | `tests/network/test_ws_resume.py:133` | 缺口即断帧 | 有效 |
| G5 | 窗口不足必响且已清理路具名 | `test_ws_resume.py:167/217` | 帧序恰 `["error"]` | 有效 |
| G6 | 远程可见面不扩张（命令/帧封闭集） | `test_ws_protocol.py` + `tests/test_architecture_contracts.py::test_ws_endpoints_and_commands_stay_closed` | 集合相等 + 词根守卫 | 有效 |
| G7 | 契约基线不漂移 | `contract_snapshot.py --check` | 五份 `[OK]` | 有效 |

## 结构性不变量（读码确认，非本 epic 新增但被远程面放大）

1. **慢订阅者被摘除而非阻塞生产者**：`event_stream_hub._emit` 遇到 `QueueFull` → `_drop_lagging_subscriber`（清队列、投 `None` 哨兵、WARNING `subscriber_dropped reason=queue_full`）⇒ 客户端只会看到「流结束」，必须靠 R3 的 cursor 重连续传；不会让落库线程卡住。队列上界 = `record.subscriber_queue_size`（`ws_server.py:342`）。
2. **两个并发 run 的隔离靠「每 run 一份 record + 各自的订阅队列」**，没有共享可变状态；跨项目归属判定在 `RunWebSocketService` 层（E74/E75 已钉），本 epic 只加用例。
3. **陈旧 `running` 的收尾时机**：`container.py:307` 在 run **启动时**扫 `close_stale_running(max_idle_hours=6)`；远程客户端在「上一进程已死、下一次 run 尚未启动」的窗口里仍会读到 `running` 快照——这是 E76 远程可见面的**已知语义**（不是本 epic 引入，也不是缺陷），客户端 UI 需容忍该窗口。
4. **快照并发写**靠 `RunStore.save` 的保守合并（Z-D21 / A34 残余挂起），本 epic 未改动该路径。

## 结论

**通过**：G1–G7 全部可反证；G2 原本是「断言比实现弱」的软守卫，当轮已补齐。结构性不变量四条均有代码位置支撑，无 new High/Critical。
