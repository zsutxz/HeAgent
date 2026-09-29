---
id: 51-4
title: 真实质量 Gate 与 goal verify
status: ready-for-dev
parent_epic: E51
priority: P0
depends_on: [51-3]
blocks: [51-6, 51-8]
created: '2026-09-29'
---

# Story 51-4：真实质量 Gate 与 `/goal verify`

## 用户故事

作为 Goal 负责人，我希望完成判定依赖真实 Evidence，以便未运行测试或运行失败的 Story 不能推进。

## 声明面（主要交付物）

- **门禁规则全部来自 51-3 的 `validation:` 子句**，本 Story 不引入新的顶层配置键：
  - `command:` → 必须有匹配的计划证据（退出码 0、cwd 正确、未过期、属于当前 Story / 步骤）；
  - `artifact:` → 必须有该产物；
  - `git:` → 必须有该路径的 Git 变更证据；
  - `section:` → 输出必须含该标题（**既有文本门禁，保留**）；
  - `gate: <名字>` → 命名质量门（宿主内置门，工作流只能**引用**不能削弱）。
- `gate:` 的可用名字由引擎注册表提供（通用词汇）；workflow 只能引用已注册名字，
  写出未注册名字 = 加载期 fail-loud。
- **老包不声明结构化子句时保持原文本门禁行为**（零行为变化）。

## 引擎面（最小通用能力）

- 通用求值器：把声明子句逐条匹配到当前步骤 / Story 的证据与产物上，产出结构化的通过 / 失败与原因。
- `/goal verify`：只检查或**受控重跑**声明里列出的验证，绝不重新执行实现步骤、绝不伪造完成状态。
- 失败 / 超时 / 取消 / 策略阻断都算「未通过」，不区分「没跑」与「跑了没过」的写法。
- **为什么声明层表达不了**：求值器需要读取证据记录、访问文件系统与只读 Git；声明只能表达**规则**。
  求值器本身通用（不认 Epic、不认步骤名）；`gate:` 注册表是通用词汇表，新增门 = 新词汇（AD-14）。

## 验收标准

- workflow 可声明必需产物、命令、Git 路径和质量门（经 `validation:` 子句）。
- 声称命令通过但没有匹配的命令证据时 Gate 失败。
- 非零退出码、错误 cwd、过期证据或证据不属于当前 Story 时进入 `BLOCKED`。
- `/goal verify` 只重跑 / 检查声明的验证，不重新执行实现步骤，不伪造完成状态。
- 旧 workflow 未声明结构化 Gate 时保持原文本 Gate 行为。
- workflow 不能降低宿主强制质量门或绕过工具治理链；引用未注册 `gate:` 名字时加载期显性失败。

## 任务

- [ ] 扩展 `WorkflowStepResource` 的 `validation` 模型（向后兼容：老字符串仍可解析）。
- [ ] 在 `goal/quality_gates.py` 实现通用求值器（AD-14 证明：见「引擎面」末条）。
- [ ] 实现 `/goal verify` 与结构化报告（输出继续走 `_echo` 漏斗）。
- [ ] 增加缺证据、失败证据、错误归属、旧语义兼容测试。
- [ ] 负向验证「只写 Markdown 就通过」「引用未注册 gate」「失败证据当通过」的变异体必须红。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_goal_quality_gates.py tests/test_goal_evidence.py tests/test_workflow_resources.py -q
pytest tests/test_workflow_runner.py tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
