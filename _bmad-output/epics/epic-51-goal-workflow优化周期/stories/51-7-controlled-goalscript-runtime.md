---
id: 51-7
title: 受控 GoalScript 与 ScriptRuntime
status: ready-for-dev
parent_epic: E51
priority: P2
depends_on: [51-6]
blocks: [51-8]
created: '2026-09-29'
---

# Story 51-7：受控 GoalScript 与 ScriptRuntime

## 用户故事

作为可信 workflow 作者，我希望表达条件、循环和动态输入，同时不能接管状态、checkpoint 或工具治理。

## 产品裁决

- 脚本模式默认关闭。
- 第一阶段只允许可信本地 workflow 包启用。
- GoalScript 不是安全边界；第三方脚本需要后续隔离 worker。

## 验收标准

- 支持 `executor_mode: script` 和包内受完整性校验的脚本资源。
- `GoalScript` 只暴露受控 step/parallel/checkpoint/input/artifact/decision/validate API。
- 所有状态变化仍经 `WorkflowRunner`；所有 Agent/tool 调用仍经既有治理链。
- 脚本不能直接写 checkpoint、workflow/current，不能裸起子进程、裸联网、自动 commit。
- 条件分支结果基于持久化输入/产物，进程重启后可确定恢复。
- 强制步骤数、深度、超时和取消语义；超限有界失败。
- 资源 hash 漂移显性失败。

## 任务

- [ ] 新增 `script_api.py`、`script_loader.py`、`script_runtime.py`。
- [ ] 定义 Pydantic 操作请求/响应模型。
- [ ] 实现声明式步骤适配与幂等跳过。
- [ ] 增加越权 API 缺失、超限、恢复、漂移和治理链测试。
- [ ] 文档显著声明宿主解释器模式仅限可信包且非安全边界。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_goal_script_api.py tests/test_goal_script_runtime.py tests/test_goal_script_security.py -q
pytest tests/test_skill_packages.py tests/test_architecture_contracts.py -q
ruff check src tests
mypy src
mypy src --platform linux
```
