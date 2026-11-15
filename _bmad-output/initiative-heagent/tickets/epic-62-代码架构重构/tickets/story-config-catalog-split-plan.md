---
ticket: 4
id: 4
type: refactor
status: done
title: "拆分 config/catalog.py"
---

# Plan — Story 1.4 拆分 config/catalog.py（迁移最小 plan）

status = done。**build record 缺失**：sprint-status.yaml 无改进计划键（grep=0），
证据为归档 epics.md 勘误（2026-11-13，用户授权核验）：「FR1.4 已交付：拆为
config/catalog/ 9 文件，最大单文件 307 行，__all__ 34 项零变化」。
baseline_revision 未推断、不记载（迁移规则禁止以今日 HEAD 充当基线）。

## Acceptance criteria

- catalog/schema.py 含配置 schema 定义，catalog/validator.py 含配置验证逻辑
- 每个文件行数 < 1000 行，配置加载与验证功能不变

## Implementation history

- v6 期交付（2026-11 批次，同批还有 config/catalog.py 之外的多项拆分）。
- 原 v6 build record 不存在；本 plan 由 migration-1 于 2026-11-15 依勘误写入。
