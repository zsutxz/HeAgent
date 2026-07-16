# HeAgent 代码审查结论

> 审查时间：2026-06-23 | 范围：`src/heagent/` 全部源文件 (60+) + `tests/` 核心测试

## 总体评价：高质量，可投入生产

**架构、代码质量、测试覆盖、安全声明诚实度均属上乘。**

---

## 必须修复（3项）

| # | 位置 | 问题 |
|---|------|------|
| 1 | `loop.py` `_runtime_scope()` | `ExitStack` 内 `bind_*` 若抛异常，剩余 bind 不执行 → 部分工具运行时未绑定但 run 继续 |
| 2 | `sandbox.py` `_kill_and_reap()` | `proc.kill()` 权限失败(`PermissionError`) 不阻断后续 `wait()` 但子进程可能泄漏 |
| 3 | `mapping.py` `_INJECTION_PATTERNS` | 注入启发式模式描述刻意不含原始字节 → 调试困难（DP-4 第二半安全标注要求） |

## 建议修复（5项）

| # | 位置 | 建议 |
|---|------|------|
| 4 | `roles.py` 中文提示词 | 与 `window_reset.py` 英文 `RESUME_HINT` 语言不一致，统一为中文 |
| 5 | `memory/skills.py` frontmatter 解析 | 手动解析 `---` → 引入 `yaml` 依赖替换（含 `:` 的值当前会解析错） |
| 6 | `executor.py` 多处 `except Exception` | 加上 `logger.exception` 避免掩盖真 bug（如 handler 的 `ImportError`） |
| 7 | `loop.py` `_emit()` | 外层 try/except 与 `EventBus.emit` 内已 catch 重复 → 删外层 |
| 8 | `config.py` 文档 | 补充 `.env` 覆盖环境变量的优先级说明 |

## 架构亮点（保持）

- ✅ **DAG 清晰**：`agent` 不反依赖 `tools`/`providers`/`engine`；`mcp/` 禁从 `agent` 导入
- ✅ **DI 注入**：`AgentLoop` 组件全注入、无全局状态毒化；`sub.py` 用 `dataclasses.replace` 只换 policy
- ✅ **纵深防御**：PolicyEngine(准入/围栏) → ToolExecutor(分发) → SafetyGuard(黑名单) → handler 四层串行
- ✅ **幂等账本**：`ExecutionLedger` 以 `sha1(key)` 防重复执行（window_reset 后重复 tool_call / cron tick）
- ✅ **安全声明诚实**：项目明确标注所有安全组件「非真正边界，须 OS 级沙箱兜底」—— 罕见且值得肯定

## 主要指标

| 维度 | 结果 |
|------|------|
| 模块边界 | ⭐⭐⭐⭐⭐ 依赖 DAG 清晰，无循环导入 |
| 测试覆盖 | ⭐⭐⭐⭐⭐ 正常/异常/损坏容错/异步回归全覆盖 |
| 错误体系 | ⭐⭐⭐⭐ 统一 `HeAgentError` 体系，部分 catch-all 可收窄 |
| 文档质量 | ⭐⭐⭐⭐ `docs/frame.md` 架构权威，源码注释完整 |
| 长期风险 | **唯一大文件** `loop.py` ~750 行；`Settings` 单例跨测试可能污染 |
