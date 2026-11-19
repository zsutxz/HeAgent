---
title: 'Story 71.4 进程资源采样（stdlib only）'
type: feature
ticket: 4
created: '2026-11-19'
status: built
baseline_revision: 'e06be7b'
route: full
route_source: auto
risk: medium
review: thorough
review_source: auto
lenses_ran: ['edge-case-hunter(inline)', 'verification-gap(inline)']
review_loop_iteration: 0
followup_review_recommended: false
context:
  - 'src/heagent/cli/http_status.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** 网页端看不到「这个进程吃多少内存 / 开了几个线程 / 累计多少 CPU」——依赖树里没有 `psutil`，仓库里也没有任何 `/proc` 或 ctypes 采样。

**Approach:** 新增 stdlib-only 的 `network/proc_stats.py`：Linux 读 `/proc/self/*`、Windows 走 `ctypes`；不支持的平台一律 `source="unavailable"` 且三项为 `None`（绝不填 0 冒充）。采样结果并入 `/api/status`。

## Boundaries & Constraints

**Always:**
- 零新增运行时依赖（Epic 67 的依赖精简立场）；`pyproject.toml` 依赖段零 diff。
- 不可得 → `None` + `resource_source="unavailable"`，端点照常 200。
- 采样同步、无副作用、单次只做一次文件读取或一次 Win32 调用。

**Never:**
- 不做主机级指标（磁盘 / 网络 / 其他进程）；不持久化历史；不引入 `psutil`。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| PROC_OK | Linux | `rss_bytes` 为正、`cpu_seconds >= 0`、`source="procfs"` | 无 |
| UNSUPPORTED | 平台名不认识 | 三项 `None`、`source="unavailable"` | 不抛错 |
| SAMPLING_FAILS | `/proc` 读取抛 `OSError` | 降级 `unavailable` | 不抛错 |
| CHEAP | 1000 次采样 | 总耗时 < 500ms | 无 |
| MAPPED | 采样可用 | 状态面字段与采样值一致（填 0 即失败） | 无 |

</intent-contract>

## Code Map

- `src/heagent/network/proc_stats.py`（新）-- `ProcessStats` dataclass + `read_process_stats()`；平台分支与常量 `PROCFS_SOURCE` / `CTYPES_SOURCE` / `UNAVAILABLE_SOURCE`。
- `src/heagent/cli/http_status.py` -- `_resources()` 把采样并入 `StatusResponse`。
- `src/heagent/network/http_protocol.py` -- `rss_bytes` / `threads` / `cpu_seconds` / `resource_source`（有界、可空）。
- `tests/test_http_status_api.py::TestProcessResources` -- 覆盖 I/O Matrix。
- `docs/frame.md` -- network 目录树加 `proc_stats.py` + 状态 API 行补资源口径。

## Tasks & Acceptance

**Execution:**
- [x] `proc_stats.py` -- 两条平台通路 + 不可用降级 -- 只读一次，不引依赖。
- [x] `http_protocol.py` / `http_status.py` -- 字段与映射 -- 不可得即 null。
- [x] 测试 -- 真值 / 降级 / 耗时 / 映射 -- 四项判据。
- [x] `docs/frame.md` -- 目录树与状态行 -- 文档不落后。

**Acceptance Criteria:**
- Given Linux, when 采样, then `rss_bytes > 0` 且 `source="procfs"`。
- Given 未知平台, when 采样, then 三项 `None` 且 `source="unavailable"`（不抛错）。
- Given 采样可用, when 读 status, then `rss_bytes` 与采样值一致（映射处填 0 即失败）。
- Given 1000 次采样, then 总耗时 < 500ms。

## Implementation Notes

- Linux 走 `/proc/self/status`（VmRSS / Threads）+ `/proc/self/stat`（utime+stime ÷ `SC_CLK_TCK`）；`stat` 的进程名字段可能含空格，解析从最后一个 `)` 之后切。
- Windows 走 `GetProcessMemoryInfo` + `GetProcessTimes`；线程数不采（`Toolhelp32Snapshot` 每次要枚举全进程线程，代价不成比例），留 `None`。
- `WinDLL` 在 Linux 上不存在 ⇒ 按平台 `# type: ignore[attr-defined]`，不引 `getattr` 规避（ruff B009）。

## Plan Change Log

## Review Triage Log

### 2026-11-19 — Review pass（内联自查，未起独立镜头）
- verdicts: 2 findings — high 0, medium 0, low 2, false 0, maybe-false 0
- findings:
  - `[low]` `[patch]` 状态面只断言「字段存在」，映射处填 0 也能过（首轮变异验证暴露：`or 0` 变异 GREEN）— 改为「采样可用时 `rss_bytes > 0` 且与采样通路一致」，重跑变异 `rss_bytes: 0` ⇒ RED。
  - `[low]` `[patch]` Windows 通路在本机不可执行 — 保持 `# pragma: no cover`，并把「不可用即 null」的判据放在可执行分支上（未知平台用例）。
- 说明：本故事的镜头检查由编排者内联完成（无独立子代理），因此 `lenses_ran` 标 `(inline)`；面向用户的报告里已注明。

## Auto Run Result

- **实现**：`network/proc_stats.py` + `StatusResponse` 四个资源字段 + 来源映射。
- **文件**：`src/heagent/network/proc_stats.py`（新）、`src/heagent/network/http_protocol.py`、`src/heagent/cli/http_status.py`、`tests/test_http_status_api.py`、`tests/fixtures/contract_baselines/{public_exports,exception_types}.json`、`docs/frame.md`。
- **评审处置**：patch 2 条（low），无 defer / reject。
- **后续评审建议**：`false` —— 本轮无 medium/high，且新增用例已变异验证。
- **验证**：`pytest`（`tests/network` + 相关套件 **763 passed**）；四份契约快照 `[OK]`；`ruff` / `format` / `mypy` 全绿；变异 2/2 RED（`rss_bytes: 0`、平台写死）。
- **残差**：Windows 通路未在本机执行（`# pragma: no cover`）；线程数在 Windows 上恒 `None`；macOS/BSD 走 `unavailable`。
