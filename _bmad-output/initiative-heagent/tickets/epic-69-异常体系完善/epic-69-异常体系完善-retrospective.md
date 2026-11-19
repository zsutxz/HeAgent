---
epic: epic-69-异常体系完善
date: 2026-11-18
verdict: accepted
criteria: declared
headless: false
---

# Epic 69 Retrospective

> 路径约定：`tickets/story-69.*` 均相对 `_bmad-output/initiative-heagent/tickets/epic-69-异常体系完善/`；
> 其余路径相对仓库根。实测为收口现场取证（2026-11-18，容器内 `.heagent/tmp/py311-venv-linux/bin/python`）。

## Epic summary

**Epic**：epic-69-异常体系完善（R2；3 story，全部新建）

**票态**：3/3 `done`，无 `dropped`。

| Entry | 交付 | 提交 |
|---|---|---|
| 69.1 模块专用异常 | 14 个新异常（provider 认证/限流/超时/响应格式、tool 参数/执行/未注册、engine 台账/策略执行/工作流、agent 迭代上限/子代理/续跑 + `ConfigurationError`），每条都有真实 `raise` 点 | `a21c20e` |
| 69.2 异常层次 | 根 → 6 个分类 → 具体异常；`HeAgentException` 是 `HeAgentError` **别名**（不是第二个基类） | `a21c20e` |
| 69.3 统一错误码 | 每类 `code` / `description` / `suggestion` + `error_catalog()` / `error_code_of()`；`docs/errors.md` 第二节的码表由测试逐条比对 | `a21c20e` |

## 收口现场补的第三件事：3 个游离在层次外的异常

`tests/test_exceptions.py` 的判据按 `__module__ == "heagent.pub.exceptions"` 过滤 ⇒ 定义在别的模块里的
`HeAgentError` 子类既不进层次判据、也没有错误码、也不在 `error_catalog()` 里。收口实测发现 3 个：

| 类 | 原定义地 | 收编后 |
|---|---|---|
| `InputValidationError` | `pub/validation.py`（67.1 新造） | `ConfigurationError` 子类，码 `E_CONFIGURATION_INVALID_INPUT` |
| `McpSdkMissingError` | `tools/mcp/sdk.py`（67.9 新造） | `ToolError` 子类，码 `E_TOOL_MCP_SDK_MISSING` |
| `FactCompactConflictError` | `memory/compact.py` | `EngineError` 子类，码 `E_ENGINE_STORE_CONFLICT` |

处置：三个类**定义搬进 `pub/exceptions.py`**（单一异常家），原模块用 `as X` 显式 re-export 保持导入路径与
既有调用点不变（`*  # noqa: PLC0414` 是 mypy strict 与 ruff 两边都满意的唯一写法）。随之同步：
`_CATALOG_CLASSES` 顺序、`__all__`、`docs/errors.md` 码表（26 → **29** 行，覆盖口径 73 → **76** 条）、
`tests/fixtures/contract_baselines/exception_types.json` 与 `public_exports.json` 重新生成。

## 门禁实测

```text
pytest tests/test_exceptions.py -q                     → 21 passed
pytest tests/test_input_validation.py tests/memory/test_compact.py \
       tests/test_fact_compact_tool.py -q              → 96 passed
pytest tests/test_architecture_contracts.py tests/test_contract_baselines.py \
       tests/providers tests/memory -q                 → 319 passed
python scripts/contract_snapshot.py --check            → 四份基线全绿（exceptions / public / routes / transport_errors）
pytest -q                                              → 5208 passed / 51 skipped / 30 deselected / 1 xfailed
ruff check / ruff format --check / mypy src            → 全绿（mypy: 229 files）
```

## 决策与刻意不做的事

- **不为凑数加无人 `raise` 的类**：69.1 的每个类都有真实 raise 点，判据是源码文本「`raise <Class>`」
  （`test_story_69_1_exceptions_are_really_raised` / `test_every_concrete_exception_is_instantiated_or_raised`）。
- **多继承只为兼容既有 `except`**：`ToolArgumentError(ToolError, ValueError)`、`LedgerError(EngineError, ValueError)`
  等；分类祖先仍恰好一个（多出来的那个是内置异常，不是分类）。
- **不合并 `network/` 的 `HttpErrorCode`**：传输层错误码有独立契约与基线（`transport_errors.json`），
  两套封闭集合刻意并存（29 个框架码 + 35 个传输码）。
- **不用 `__init_subclass__` 强制分类**：显式继承即可读，魔法只会在排查时多一层。

## Open questions / 残留

1. **「错误码只增不复用」没有判据**：传输层 35 码有 INV-8 快照守卫，框架码目前只有「唯一 + 形态 `E_*`」断言。
   若要在发布面钉死，需给 `error_catalog()` 的 `code → class` 对加一份只增快照。
   触发条件 = 第一次因改名/复用引发消费方分支错乱。
2. **空 `except HeAgentError` 的入口层位置未收窄**：分类层已经可用，但入口层仍是「根类一把抓」；
   收窄需要逐入口确认对外错误形状，属后续 UX/错误面工作，不在本 epic 的接受标准内。
3. **`docs/errors.md` 第三节（CLI 自由文本）不在码体系内**：这一层按设计是自由文本检索表，
   没有码也不该有码；口径写在页首的「覆盖口径」段，避免被误读为「未覆盖」。
