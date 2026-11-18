---
title: 'Story 63.4 增加沙箱容器启动失败恢复测试'
type: test
ticket: 4
created: '2026-11-18'
status: dropped
baseline_revision: '0d13b6c'
route: none
route_source: manual
risk: low
review: none
review_source: pinned
lenses_ran: []
context:
  - 'src/heagent/tools/sandbox/docker.py'
  - 'tests/test_sandbox_docker.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Ruling（2026-11-18 用户裁定：dropped）

**票面 verify 已被既有测试面完整满足，无需新增测试（零代码变更）。**

勘测（baseline 0d13b6c）：`tests/test_sandbox_docker.py` 已有 **49 个判据测试**，
verify 三条款逐条有钉：

| verify 条款 | 既有钉 |
| --- | --- |
| 检测失败 | 判据 2（CLI 缺席 → `available=False`）、判据 3（daemon 不可达 → `available=False`）、判据 3b（探测成功） |
| 降级非沙箱模式 + 清晰 WARNING + 降级后的工具执行 | 判据 4（`test_unavailable_falls_back_with_warning`：Passthrough 实跑命令、结果如实回传、`"falling back"` WARNING 日志断言） |
| 覆盖降级后的工具执行（恢复面） | 判据 17/17b/18（熔断窗口开启/过期恢复/探针失败即熔断）、判据 21/21b（半开探针恢复/失败续窗）、判据 22b（硬失败满窗冷却） |
| （对照面）不误降级 | 判据 9（运行期 docker 错误显性失败不降级）、判据 12（resolver 可用性闸） |

## Design（不适用）

dropped：无设计。

</frozen-after-approval>

## Outcome

零代码变更。Epic 63 剩 63.5（CI 基准强制门禁，已批执行）/ 63.6 / 63.7 / 63.8。
