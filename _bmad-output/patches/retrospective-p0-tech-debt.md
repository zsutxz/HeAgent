# Retrospective — P0 Provider 技术债收尾

> **事后补做**（2026-06-29）。P0 技术债收尾是补丁周期的一组工作（非 sprint-status 标准 epic），按同一 retro 模板生成。
> 证据来源：`_bmad-output/patches/deferred-work.md`（三条均已关闭）+ `git log`（2026-06-19 异常统一包装、2026-06-20 P0 债收尾）。
> 适配 CLI/库项目——省略 sprint velocity / incidents / deployment / stakeholder（不适用，不编造）。

## 概览

| 项 | 内容 |
|----|------|
| 范围 | P0 provider 技术债收尾（补丁周期） |
| 来源 spec | `p0-provider-hardening`（provider 源头把 SDK 异常统一包装为 `ProviderError`） |
| 三项发现 | ① SubAgent 共享 SkillStore 写竞态 ② ProviderChain 双层重包 ③ 流式 backstop 丢失 last_error |
| 结果 | 全部关闭——① 经核实不成立关闭；②③ 已修复 |

## 成果（What went well）

1. **三项全部关闭，零挂账**：含一项「经核实不成立」而关闭（竞态），不是全靠修代码才算收尾。
2. **把「不成立」的结论锁成可验证不变量**：为竞态误判加了回归测试 `test_parallel_shared_skillstore_no_lost_usage_update`——未来若 `SkillStore` async 化引入真实 await 交错，测试会变红提醒重新评估。
3. **send/stream 路径对称化收尾**：双层重包（`_raise_provider_error` 守卫）与流式 backstop（跟踪 `last_error`）修复后，两条路径行为对称、`__cause__` 链正确。

## 挑战（Challenges）

1. **edge case hunter 误判并发竞态**：把「多协程访问共享 SkillStore」判为竞态，忽略了 `record_usage` 是无 `await` 的同步原子段——审查发现需人工核实「是否真有 await 交错」。
2. **spec 边界外的连锁**：P0-2 的边界是「provider 源头包装」，未覆盖下游 chain 对已包装异常的二次包装——一个 spec 的窄边界引发了相邻路径的 deferred 项。

## 教训（Key lessons）

1. **审查发现的并发竞态要先核实 await 交错**：单线程 asyncio 下，无 `await` 的同步方法必然串行（A 完整写完才轮到 B），不构成竞态。**不要引入 `asyncio.Lock`**——`Lock.acquire` 是 awaitable，同步方法内用不了；`threading.Lock` 在单线程无意义。用回归测试锁定不变量即可。
2. **异常包装入口加 `isinstance` 守卫**：`_wrap_error` 类入口 `if isinstance(e, ProviderError): raise`，避免对体系内异常二次包装；用「抛出异常的 `__cause__` 不再是另一个 `ProviderError`」写回归测试。
3. **成对路径要对称实现 + 对称测试**：`send()` 跟踪 `last_error`，`stream()` 一度漏了——成对的 send/stream 实现要互相对照补齐。
4. **deferral 机制有效**：spec 边界外的连锁问题（双层重包、流式 backstop）走 `deferred-work.md` 而非就地扩展原 spec——冻结边界 + 单独收尾，避免单个 spec 膨胀。

## 技术债 / 遗留（Deferred）

| 项 | 状态 |
|----|------|
| ① SubAgent 共享 SkillStore 写竞态 | **关闭**——核实不成立（同步方法串行），加回归测试锁定 |
| ② ProviderChain 双层重包 | **关闭**——`_raise_provider_error` 守卫，已修复 |
| ③ 流式 backstop 丢失 last_error | **关闭**——stream 跟踪 last_error，已修复 |

> 唯一的前瞻项：若 `SkillStore` 方法 async 化（CLAUDE.md 规定库代码无同步 I/O，届时 `read_text`/`write_text` 须 async 化），回归测试①会变红，需重新评估并发安全。

## 行动项（Action items）

| # | 行动 | Owner | 触发 / 时机 |
|---|------|-------|-------------|
| A1 | `SkillStore` async 化时重新评估并发安全（回归测试①会提醒） | tan | SkillStore `read_text`/`write_text` async 化 |
| A2 | 审查发现的竞态类问题，先核实 await 交错再定级（纳入审查 checklist） | tan | 下次 code-review |

## 下一步

P0 provider 技术债已清零。前瞻项（SkillStore async 化的并发重评）依赖未来的「库代码无同步 I/O」推进，已由回归测试守卫，无需主动排期。

## 不适用字段（CLI/库项目）

sprint velocity / 实际-vs-计划 story points / production incidents / deployment / stakeholder acceptance —— 省略，不编造。
