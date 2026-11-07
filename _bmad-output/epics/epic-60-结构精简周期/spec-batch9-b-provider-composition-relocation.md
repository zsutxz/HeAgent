---
title: '批次 9 卡 B：provider 装配家族迁 providers/composition.py'
type: 'refactor'
created: '2026-11-07'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval route="oneshot — 调查已闭合全部事实，无 Open Questions" reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** provider 装配规则（`cli/wiring.py:64-319`，~270 行：4 URL 常量 + `_ENTRY_CREDENTIAL_HINTS` + 7 builder 函数）住在入口层——「DAG 允许入口层调用一切」不等于业务规则该住入口层；且 wiring 同时持 cron/loop 装配留守件，装配规则与运行时装配两种变化原因混居一文件。

**Approach:** 行为零变化搬移 + 呈现分离：家族迁新 `providers/composition.py`（规则真身，致命配置错误抛 `ProviderConfigError(ValueError)`）；wiring 留**呈现薄壳** `_build_provider`：catch → `click.echo(err=True)` + `SystemExit(1)`，消息字节不变；三消费方 import 原行不动（全部 patch 在消费方命名空间，零改动）；`logger.warning` 三处随迁（logger 名随新家）；frame.md 同步；契约测试零改动。named 插入序契约 docstring 显式化（既有测试已钉）。

</frozen-after-approval>

## Implementation Notes

**调查结论（2026-11-07，HEAD 1370fd5）：**

- 家族边界：`wiring.py:64-319` 连续块 = 4 URL 常量(:65-68) + `_ENTRY_CREDENTIAL_HINTS`(:71-78) + 7 函数（`_openai_builder` 81-92 ← `_build_provider` 调 4 次(190/214/219/231)；`_responses_builder` 95-106 ← :200；`_build_entry` 109-144 ← 内嵌 `_entry`(165-186) 调 :178；`_build_provider` 147-263 家族根；`_build_key_rotated` 266-281 ← `_key_rotated_builder` :298；`_key_rotated_builder` 284-304 ← `_anthropic_pool_builder` 307-319 ← :194）。`_first_line`:58-61 不属家族（消费在 build_cron_job_runner:417）。
- 留守面（不动）：docstring 1-10（重写）、imports 12-55（家族-only 清理）、`_first_line`、`ensure_runtime_config` :331-340、`build_cron_job_runner` :343-421、`AgentLoop` import :19（test_cron_notify.py:68 patch 它）+ `:384` cron 告警；留守 TYPE_CHECKING 别名仅 `CronJobRunner`:49 / `CronNotifier`:53。
- 呈现点分类（迁移转制）：致命三点 → `ProviderConfigError`：:224-229（OLLAMA_ENABLED 缺 OLLAMA_MODEL）、:243-250（无任何 API key）、:301（`_key_rotated_builder` 无凭据 `SystemExit(str)`）。wiring 薄壳 catch → `click.echo(err=True)` + `SystemExit(1)`；`SystemExit(str)` 与 `click.echo(err=True)` 的 stderr 字节与退出码等价（python 对 str 参数 SystemExit 打 stderr、退出码 1）。告警三点 `logger.warning`（:128/:236/:257）随迁，logger 名 `heagent.cli.wiring` → `heagent.providers.composition`；test_cli_provider_build.py:228 经 `record.message` 断言（非 logger 名过滤）不受影响；实施期 grep 测试面 caplog 复核零漏。
- 消费方与缝：console.py:20 / http.py:37 模块级 from-import（绑定副本），gui/__init__.py:36 函数体内惰性 import——三处**原行不动**（仍 import wiring 的 `_build_provider`＝薄壳），8 处测试 patch（events_rollout:57 / http:59,345,396 / http_lifecycle:153,336 / web_overrides:150,230 / provider_build:15 直调）全打在消费方命名空间，零改动继续有效。scripts 零引用家族符号。
- providers 包：无模块 import config——家族将首次引入 `Settings`（**TYPE_CHECKING 形态**，运行期零依赖）；无 layout pin（`test_shared_layer_layout_is_pinned` 只钉 pub/config 清单）；不进 `__init__` re-export（无 KeyRotatingProvider/OpenAIResponsesProvider 先例）；`FORBIDDEN_RUNTIME_IMPORTS["providers"]` = ("heagent.agent", *_ENTRY_LAYER_MODULES)（contracts:65）——composition 不 import 入口层，`test_no_reverse_dependency_on_agent`(:218-234) 扫全目录安全。
- named 插入序契约：named dict 代码序 deepseek→claude→openai→kimi→glm→ollama；默认序推导 :253/:255/:260-262；既有测试钉住（provider_build:78 先插者赢、:331 ACTIVE_PROVIDER 覆盖）；composition 模块 docstring 显式化。
- 契约测试核对：`test_cli_package_layout_is_pinned`(:704-722, wiring 在 :721) wiring 不删零改动；`test_entrypoints_do_not_duplicate_runtime_store_paths`(:614-627) 清单不含 wiring、家族无 `.heagent` 字面量——无影响；`test_getcwd_configuration_is_limited_to_entrypoints`(:243) 按 cli/ 首段判入口层——composition 无 getcwd，安全。
- frame.md 同步四处：:136（network 段列举——wiring 仍入口层，实施期读上下文定改不改）、:160 模块表行、:1528 目录树行、:1784 调用链图行（`cli/wiring._build_provider()` 注明规则真身 providers/composition、wiring 为呈现薄壳）。wiring docstring(1-10) 重写：定位「cron/loop 装配 + provider 呈现薄壳」。
- 命名消歧：`cli/composition.py` 已存在（入口层 loop 装配）；`providers/composition.py` 同名不同包，行文用全路径。

**执行面（动面清单）：**
1. 新建 `providers/composition.py`：家族 64-319 迁入（4 常量 + hints + 7 函数 + 内嵌 `_entry`）；致命三点转 `ProviderConfigError(ValueError)`（消息文本入异常，字节不变）；`logger` 随新家命名；TYPE_CHECKING import Settings/类型别名随迁；named 契约 docstring 显式化；模块 docstring 写明「装配规则真身、致命呈现留 cli 侧薄壳」。
2. `wiring.py`：家族块删除；薄壳 `_build_provider(settings, model)` catch → `click.echo(err=True)` + `SystemExit(1)`；家族-only imports 清理（6 个 providers 运行期 import 删；click/logging/AgentLoop 留守复核保留）；docstring 重写。
3. frame.md 四处按实读上下文同步（含 docstring 重写并入 2）。
4. 门禁：pytest 全量（不带 --cov，已知环境红 `test_build_ws_server_config_*` 在案）+ `ruff check src tests scripts` + `ruff format --check` + `mypy src`。
5. 呈报制提交；台账 deferred-work-archive.md 一行（无新增挂账则勘验索引 v2 行补 commit hash）；memory 更新。

## Review Triage Log

| # | 发现 | 裁定 | 依据 |
|---|---|---|---|
| 1 | 工作树混入非本卡改动（agent/stream_runtime.py、providers/openai.py、tests/providers/test_openai.py、tests/test_streaming.py——流式模型归因修复） | high→patch（提交分域） | 实证：四文件 `M`、HEAD 未动、非卡 B 动面；本次提交严格限定卡 B 五文件，外来改动原样保留在worktree 并呈报用户裁定归属（疑似并行会话现场） |
| 2 | frame.md「互不依赖」主张失效（:128 + 目录树 :1561） | 拆半：:128 **false**；目录树 **low→已修** | :128 说的是 providers↔tools **两包间**互不依赖——composition 只引同包实现，主张仍真；目录树注释是**包内**主张，composition 成枢纽后失真，已改「实现互不依赖；composition.py 为装配规则真身」 |
| 3 | frame.md :164 裸 `composition` 与 cli/providers 两个同名模块歧义 | low→已修 | 改全路径 `cli/composition`，遵本 spec 消歧规则 |
| 4 | ProviderConfigError 双侧契约无直接测试锚：规则侧异常类型未钉、薄壳 exit code 半契约未钉 | medium→已修 | 补 `TestProviderConfigErrorContract` 两例：零凭据 Settings → composition 抛 ProviderConfigError 且 isinstance ValueError；薄壳 SystemExit code==1 + stderr 含 "No API key configured" |
| 5 | 单档路由池 `_metadata_model` 逗号启发式会把 `fast:model` 伪名当真模型 | plausible（**非本卡代码**） | `_metadata_model` 在外来 stream_runtime 改动内，卡 B 未触；随 #1 一并呈报归属方裁定，不注册本卡台账 |
| 6 | responses.py 流末 chunk 缺 `or self._model` 回退（与 openai.py 外来修复不对称） | plausible（**非本卡代码**） | responses.py 属外来改动面，同 #5 处置 |
| 7 | 外来 `_metadata_model` 以 `object`+type: ignore 对抗既有 BaseProvider Protocol | plausible（**非本卡代码**） | stream_runtime 属外来改动面，同 #5 处置 |
| 8 | spec 实施记录行数与实况漂移（166 vs 实际；~270 vs 家族 256） | low→已修 | 实施记录补精确数：wiring 机械搬移 166 行、docstring 中文化后 172 行；composition.py 299 行=家族净体 252+头部 47；frozen Intent 的「~270」按冻结规则不动，记录面已纠 |
| 9 | 缝为跨模块导入的私有名（无公开别名/`__all__`，未来 lint 收紧或改名会静默断） | false→驳回 | 缝名刻意保持私有稳定（消费方绑定名零变化系卡 B 红线）；两侧 docstring 已成文呈现契约（改缝名会先撞 docstring 与本 spec）；新增公开别名反而扩 API 面，违背行为等价极简 |

**实施记录（2026-11-07）：** 直接 Write 大文件连续两次产出草稿残渣（`import ordering...` 等），当即弃用并改走**确定性行级手术脚本**（Bash heredoc，每步锚点计数守卫、消息文本自源文件逐字提取）——家族 64-319 逐字迁入 composition.py（守卫断言 `click`/`SystemExit` 零残留、`ProviderConfigError` 恰 3 处），wiring 重建 166 行（头清理 + 薄壳 + 322-421 逐字尾块；docstring 中文化后 172 行），composition.py 299 行（家族净体 252 + 头部 47）。守卫教训一处：`build_cron_job_runner` 计数守卫初值 ≥2 过严（定义处仅 1 次）误报中止，放宽 ≥1 后全过。ruff format 落 1 文件、check/mypy 全绿；目标测试 56 passed；frame.md 同步 **5 处**（§4.3 新增 composition 小节、目录树补行、:160 模块表、:1528 cli 树行、:1784 调用链行；:136 network 列举读实后**裁定不改**——wiring 仍入口层）；陈旧引用 grep 归零；全量 4319 passed，唯一红 = 在案环境红 `test_build_ws_server_config_*`（9001 占用）。
