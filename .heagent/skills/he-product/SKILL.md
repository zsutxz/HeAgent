---
name: he-product
description: 产品探索类目标走 /goal 的三步声明式工作流（需求澄清→范围与非目标→验收口径）
---

# he-product（产品探索工作流）

## 边界

- 本包只承载 `/goal` 的声明式契约：`workflow.md` 声明步骤顺序、输入输出与门禁，
  `templates/` 携带步骤提示词与门禁文案；代码零流程知识，`src/` 不出现本包名。
- 单点改动、一次性问答不要启动工作流；判据同 `/goal` 默认引导。

## Pattern

产品探索类目标（把一个模糊想法收敛成可验证的需求与验收口径）用
`/goal new <描述> --workflow he-product`（或别名 `product`）启动。共 3 步：
需求澄清 → 范围与非目标 → 验收口径。命令族与推进语义同 `/goal` 默认工作流；
workflow 包与 revision 在创建时冻结，运行中改配置不换流程（漂移显性报错）。

## Steps

1. 用 `/goal new <描述> --workflow he-product` 创建 goal；步骤语义以包内 `workflow.md` 为唯一权威。
2. 推进与恢复用 `/goal next` / `/goal resume`；进度用 `/goal status`；预检用 `/goal doctor`。
3. 不要手改需求文档的「原始需求」段，也不要改写已冻结的验收口径去迁就实现。
