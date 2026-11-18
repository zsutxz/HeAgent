---
title: 'Story 62.8 拆分 goal/application.py 与 cli/http.py'
type: refactor
ticket: 8
created: '2026-11-17'
status: done
baseline_revision: 'f32acc7'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'docs/frame.md'
  - '_bmad-output/initiative-heagent/tickets/epic-62-代码架构重构/epic-62-代码架构重构.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** epic-62 的 Outcome 要求「单文件均低于 1000 行」。62.6 收口后实测两处仍超标：
`goal/application.py` 1067 行（62.6 的辅助函数拆解把它从 972 推到 1067，而该票 frozen intent 明禁新模块）、
`cli/http.py` 1014 行（62.5 勘测期已登记的票外线索）。这是 epic 收口的硬缺口。

**Ruling（2026-11-17 用户「按你建议」= 先立本票补硬缺口，再收 62.7 魔法数字口径）：**
按「内聚职责」各拆一个同级模块，不做包化（包化会移动 4 处 `restore_runner` 与 3 处
`build_http_service`/`_serve_web` monkeypatch 缝的实现模块）：

- `goal/application.py` 的**声明面**（包加载/校验、绑定冻结、门禁与 open-question 策略、
  输入去重、角色包解析、prompt/story 装配）→ 新建 `goal/workflow_support.py`；application
  保留 use-case（advance / pause_resume / record_decision）与 Runner/checkpoint 面。
- `cli/http.py` 的**配置派生面**（`Settings` + CLI 覆盖 → `HttpServerConfig` / `WsServerConfig`
  的纯推导，含 `build_ws_servers` 的中枢装配决策）→ 新建 `cli/http_config.py`；http.py 保留
  服务单元（`EmbeddedHttpService`）、命令层（`http_server_cmd`）与运行期装配（`build_http_service`）。

约束：① 导入面零变化（`heagent.goal.application` / `heagent.cli.http` 仍是既有符号的可用路径，
经 PEP 484 显式别名 `import X as X` 再导出）；② monkeypatch 缝零移动（`restore_runner` 仍在
application、`build_http_service` / `_serve_web` / `_build_provider` 仍在 http）；③ 行为零变化
（纯搬移，仅 `__all__` / 导入行变化）。

</frozen-after-approval>

## Tasks & Acceptance

**Execution:**

- [x] `src/heagent/goal/workflow_support.py` — 新建：声明面 16 个公开符号（`render_template` /
      `load_validated_workflow` / `validate_goal_workflow` / `checkpoint_mode` / `open_question_mode` /
      `resolve_skill_package` / `WorkflowBinding` / `read_workflow_binding` / `resolve_bound_workflow` /
      `gate_requirements` / `open_question_policy` / `_is_input_body` / `dedupe_inputs` /
      `role_instructions` / `declarative_prompt` / `load_stories`）+ 相关模块级常量
- [x] `src/heagent/goal/application.py` — 删搬移块，改为 16 行 `import X as X` 再导出；768 行
- [x] `src/heagent/cli/http_config.py` — 新建：配置派生面 10 个符号（`_reject_non_finite` /
      `_resolve_listener_port` / `build_server_config` / `_ws_config` / `build_ws_server_config` /
      `_clean_path` / `_external_tls_files` / `build_external_ws_server_config` / `build_ws_servers` /
      `_first_validation_message`）
- [x] `src/heagent/cli/http.py` — 删搬移块，改为 import + `__all__` 再导出；706 行
- [x] `tests/test_architecture_contracts.py` — ① use-case click-free 判据扩到 `workflow_support.py`；
      ② `cli` 布局钉死表加 `http_config`；③ 存储路径判据加 `cli/http_config.py`
- [x] `docs/frame.md` — cli 子模块表 + 模块总表 + 目录树两处 + `build_ws_servers` 归属两处 +
      `validate_goal_workflow` 归属
- [x] `pyproject.toml` — 覆盖率注释的「不 omit」清单加 `cli/http_config.py`
- [x] `ruff.toml` — `goal/application.py` 加 `PLC0414` per-file 豁免（PEP 484 再导出别名被误判）

**Verification:**

- [x] `wc -l`：application 768 / workflow_support 340 / http 706 / http_config 336，全部 <1000
- [x] 全量 pytest + `pytest --cov`（门限 87%）
- [x] `ruff check` / `ruff format --check` / `mypy src` 全绿
- [x] 契约基线 `scripts/contract_snapshot.py --check` 四份一致（无漂移）
- [x] 缝实证：`tests/test_goal_declarative_workflow.py` 3 处 + `tests/test_goal_decisions.py` 1 处
      `application.restore_runner` patch 全绿；`tests/test_cli_http*.py` 的
      `cli.http.build_http_service` / `_serve_web` / `_build_provider` patch 全绿

**Implementation Notes（执行期账）:**

- 行数收口：`goal/application.py` 1067→**768**、`goal/workflow_support.py` **340**、
  `cli/http.py` 1014→**706**、`cli/http_config.py` **336**（全仓已无 >1000 行文件）
- 再导出形态：application 用 16 行 `from ... import X as X`（PEP 484 显式别名，isort 默认
  `combine-as-imports=false` 因此逐行）；http 侧沿用既有 `__all__`（该文件本就有）
- **踩坑记录（口径副作用）**：先试 application 加 `__all__`，`scripts/contract_snapshot.py` 的
  `collect_exceptions` 会把「模块 `__all__` 里的类」一并计入异常快照 ⇒ DecisionOutcome /
  GoalAdvanceStatus 等 7 个非异常类被塞进 `exception_types.json`（+44 行）。
  改用 PEP 484 别名后快照零漂移、`--check` 四份全 OK —— 再导出优先用别名，不要给
  「会被异常快照扫描的模块」新增 `__all__`
- `PLC0414`（import alias 不改名）会对 `import X as X` 逐行报警 ⇒ ruff.toml 给
  `goal/application.py` 单独豁免（与既有 per-file 豁免同风格），不放宽全局
- 缝实证：`restore_runner` 4 处 patch（application 内解析）、`build_http_service` / `_serve_web` /
  `_build_provider` 3 类 patch（http 内解析）全部随实现留在原模块 ⇒ 测试零改动即通过
- 实测：全量 `pytest` → **4387 passed / 5 failed**（5 红全为 `test_setup_ws_external.py`，
  `verify_baseline.py` 判 `VERDICT: environmental`）；`pytest --cov` → **92.98%**（门限 87%；
  新模块 http_config 95% / workflow_support 89%）；`ruff check` / `format --check` / `mypy src`
  （209 文件）全绿；`contract_snapshot.py --check` 四份一致
- 文档同步：frame.md 改了 8 处（cli 子模块表、模块总表、确定性内核段、目录树两行、
  `build_ws_servers` 归属两处、`validate_goal_workflow` 归属）；`docs/frame.md` 的目录 TOC
  标题未含 goal/cli 文件名变化，无需改锚点
