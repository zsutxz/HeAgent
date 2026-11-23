---
type: epic
parent: brief
title: <Epic 标题>
covers: [R1, R2]
after: []
refined: false
sources: []
companions: []
risk: low
---
# <Epic 标题>

> epic 文件模板。路径固定 `Docs/<goal-id>/tickets/<e编号>-<slug>/<e编号>-<slug>.md`，与本文件夹的
> `tickets/tickets.toml` 成对。Step 04 只写「薄」版本：`Description`、`Outcome`、`Boundaries`、
> 已知的 `Done when`、`covers`、`after`，并置 `refined: false`——**没有 `## Requirements`**。
> Step 06 细化时补 `## Requirements`（每条一个 `R<n>`，引用父级 id）并置 `refined: true`。
> story 清单**不在这里**：在本文件夹的 `tickets/tickets.toml`（表顺序即构建顺序）。旧口径的
> `## Stories` 段与 `S-N` 编号已废弃，不要写。

## Description

<这个 epic 交付什么，一句话到一段>

## Outcome

<完成时世界是什么状态；可观察>

## Requirements

由 Step 06 细化时写入（Step 04 删除本节或留空）：

- R1 (parent R3): <一条可验证的要求>

## Constraints

<必须保持的边界；引用 initiative 的 Constraints 时写 id 或短句>

## Done when

- <可判定的完成条件；整 epic 的集成验证方式>

## Boundaries

<范围内行为与明确的范围外边界；consumed/configured 的 touch point 列在这里并注明归属>

## References

- `Docs/<goal-id>/brief.md`（需求真源兼信封）
- `Docs/<goal-id>/architecture-<slug>/architecture-<slug>.md`（采纳的决策 id）

## Notes

- Decision: <日期> <切片/细化决定，含被否掉的建议>
- Source conflict: <代码与 Requirements 冲突时的实际情况与纠正建议>
