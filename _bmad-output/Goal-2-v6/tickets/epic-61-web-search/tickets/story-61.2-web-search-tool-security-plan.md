---
title: "Story 61.2 web_search 工具注册与安全面对齐"
type: feature
ticket: 2
created: "2026-11-16"
status: done
baseline_revision: "66a5b9f"
risk: low
context:
  - "_bmad-output/epics/epic-61-Web检索周期/SPEC.md"
  - "src/heagent/tools/builtins/web.py"
  - "src/heagent/pub/roles.py"
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 引擎层（61.1）已就绪但无工具面：模型与用户尚不能发起检索。

**Approach:** `web.py` 新增 `web_search` @tool（read_only，与 web_fetch 同实现位同安全姿态）：经 `get_settings()` 解析引擎（`create_engine(名字, api_key)`），结果确定性截断（每条摘要 ≤600 字符、汇总 ≤20000 字符并标注，零概率模型参与），输出过 guard_content 注入围栏（与 web_fetch 同款）；`pub/roles.py` dreamer 白名单与系统提示词补 web_search（与 web_fetch 同面，2026-11-16 裁定）。

**Never:** 不改 web_fetch 既有行为与测试形态；不新增网络层模块；不在工具面重试（重试立场归调用方）。

</frozen-after-approval>

## Tasks & Acceptance

- [x] web_search @tool 注册（read_only annotations）+ 引擎解析 + 确定性截断（双层预算 2026-11-16 由 82388f2 补全为四层）+ guard_content 围栏 + 空结果显性文案（1877250）
- [x] dreamer 白名单 + 系统提示词工具清单 + 查证任务措辞 + 安全立场注释块同步（1877250）
- [x] 测试：注册形态 / 替身引擎全链 / 截断预算 / max_results 钳位 / 无密钥显性报错 / guard 围栏透传 / dreamer 白名单（1877250；82388f2 增补钳位与汇总闸守卫）
- [x] 门禁：相关面 pytest + ruff + format + mypy 全绿；独立 review 处置（retro 五镜头 2026-11-16，修复批 82388f2）
