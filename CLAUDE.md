# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 本文件独立于 AGENTS.md（并行维护、不互为真源、不合并）——2026-11-12 裁定，再覆盖/合并即违规。
>
> 本文件只放两件事：**去哪读**（§1，项目事实一律外链、此处不复述）与**协作纪律**（§2–§3）。
> 要补项目事实，先补进 `README.md` 或 `docs/framework.md`，这里只留指针——否则同一事实会有第二份真相。

## 1. 先读哪个文档

| 想知道什么 | 权威落点 |
| --- | --- |
| 安装、Provider 配置、CLI / HTTP / WS 用法、常用命令、开发与门禁命令、发版 | [`README.md`](README.md) |
| 架构权威：数据流、模块 DAG 与依赖规则、模块详解、完整调用链、技术规范（单文件 1000 行上限、包边界契约、注释与 Windows 规范） | [`docs/framework.md`](docs/framework.md) |
| 安全口径（canonical）：三层非边界 / OS 沙箱兜底 / `local` · `lan` · `external` 三档 / 端点可见性 / 已知缺口 | [`docs/framework.md` §4.18](docs/framework.md#418-安全口径canonical) |
| 缺口台账与规划产物布局（goal 树、`_bmad-output/` 三代归档、台账守卫测试） | [`docs/framework.md` §8.5](docs/framework.md#85-台账与规划产物布局) |
| 门禁红了怎么分诊（`verify_baseline` 的 VERDICT 判读、耗时基线、marker 口径） | [`docs/testing.md`](docs/testing.md) |
| 沙箱后端、四档分级与会话目录 | [`docs/sandbox.md`](docs/sandbox.md) |
| 文档职责、权威顺序与阅读路径 | [`docs/README.md`](docs/README.md) |
| 扩展点（新增 provider / tool / 技能包）与测试约束 | [`AGENTS.md`](AGENTS.md) |
| 当前 goal 与票树 | 指针 `docs/current` → `docs/<goal-id>/tickets/`：`tickets.py --project-root docs/<goal-id>/tickets …`，`mark` 是状态唯一合法写路径 |

## 2. 协作纪律（本文件负责的部分）

- **提交前必须呈报**：每次 `git commit` 前呈报提交信息与文件清单，获得明确同意后才执行。
- 提交信息用**中文** Conventional Commit（`feat(provider): 增加模型回退`）；只写修改点（改了什么 / 为什么），不写开发过程叙事（评审轮次、triage 统计、plan 闭合状态）——过程记录归 plan 与台账。
- 提交前跑相关测试 + `ruff check` + `mypy`。
- **monkeypatch 缝是搬移红线**：搬代码前先 `grep` patch 用的字符串路径（如 `heagent.cli.console._run_prompt`）。
- 信任「读到的」而不是「记得的」：动包边界、新增 `cli/*.py` 子模块、改台账之前，先读对应契约测试（`tests/test_architecture_contracts.py`、`tests/test_deferred_*.py`）的头部注释与 §1 表里的落点。

## 3. 本机环境注意（非项目事实）

- 本地 Python 3.13 的 `pytest --cov` 有 pydantic-settings × coverage 兼容问题 ⇒ 本地验证用不带 `--cov` 的 `pytest`，覆盖率门交给 CI 与 `scripts/quality_gate.py`。
- 必须在仓库根启动：`workspace_root` = 进程 cwd（从盘根启动会把整盘挂进容器沙箱）；Windows 用 `powershell scripts/start_heagent.ps1`，它把 cwd 钉在仓库根。
