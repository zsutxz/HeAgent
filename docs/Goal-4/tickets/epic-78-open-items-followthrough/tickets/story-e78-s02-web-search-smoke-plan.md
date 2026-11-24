---
ticket: 2
ref: 78.2
code: E78-S02
epic: epic-78-open-items-followthrough
risk: low
hitl: false
covers: ["R2"]
status: done
---

# E78-S02 · `scripts/web_search_smoke.py`：A55 的真实全链冒烟前置

## Intent

<frozen-after-approval>

A55（Epic 61 的 web_search 真实 Tavily 冒烟）卡在「用户给 key 后要现写脚本」。本 entry 把脚本先写完：
四段判据逐段打印，无 key 显性退出（exit 2 + 怎么配），有 key 一条命令出结论。**key 永不打印**。

四段 = ① config 解析（引擎名 + key 是否配置 + 长度）② 引擎直调（`create_engine` → `search`，
条目数与耗时）③ 工具面截断（条数钳位 `[1,10]`、字段预算 title 200 / url 500 / snippet 600、汇总 20000）
④ 注入围栏（`guard_content` 对合成注入文本的标注）。

`--self-check` = 离线段（预算常量自检 + 合成注入文本），无 key 也能验证脚本本身没坏。

</frozen-after-approval>

## Boundaries & Constraints

**Always**

- key 只从 `get_settings().web_search_api_key` 取，只报「已配置（长度 N）/未配置」，**任何分支都不打印值**。
- 无 key 且无 `--self-check` ⇒ exit 2，提示含 `WEB_SEARCH_API_KEY` 与 `.env` 落点。
- 临时 workspace 语义：脚本不写 `.heagent/`、不写记忆、不落任何产物（只打印）。
- 有 key 时真打外部 API（Tavily），超时可配（`--timeout`，默认 30s）。

**Never**

- 不进 `heagent` CLI 命令面（`scripts/` 一次性工具，与 `ws_manual_probe.py` 同档）。
- 不改 web_search 工具 / 引擎行为（预算、钳位、围栏一律不动）。
- 不自动重试、不吞异常：引擎错误照原样打印（含 error category 与 status_code）。

## Code Map

- 新增 `scripts/web_search_smoke.py`（纯 stdlib + heagent 导入；`main(argv)` 返回退出码）。
- 新增 `tests/test_web_search_smoke_script.py`：`--self-check` exit 0；隔离 cwd 无 key exit 2 且提示；
  `--help` exit 0；源码不含 `print` key 的路径（静态断言 key 只经 settings 取）。
- `_bmad-output/open-items.md` A55 正文补「脚本用法 + 通过判据」。

## Tasks & Acceptance

- [x] 脚本四段 + `--self-check` 离线分支 + 退出码契约（0 通过 / 1 判据失败 / 2 前提缺失）。
- [x] 三条判据用例（离线、无 key、help）。
- [x] 台账 A55 正文指向脚本。

## Verification

| 命令 | 期望 |
|---|---|
| `python scripts/web_search_smoke.py --self-check` | exit 0，四段中离线可验的段全 `[OK]` |
| `python scripts/web_search_smoke.py`（隔离 cwd、无 key） | exit 2，stderr 含 `WEB_SEARCH_API_KEY` |
| `pytest tests/test_web_search_smoke_script.py -q` | 全绿 |

## 实测结果（2026-11-24）

本环境无 `WEB_SEARCH_API_KEY` ⇒ 真打外部 API 的那一段**未验证**（A55 仍未闭合，脚本即闭合工具）。
