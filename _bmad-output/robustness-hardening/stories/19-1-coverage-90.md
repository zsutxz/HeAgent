# Story 19-1: 测试覆盖率从 88% → 90%

**Epic:** 19 (质量工程化)
**Status:** in-progress
**Source:** coverage report 2026-07-21

## 目标

将语句覆盖率从当前 88%（3852/4310）提升到 ≥90%（≥3879），需覆盖 **≥27 条** 未覆盖语句。

## 策略

优先覆盖 1-4 条缺失的模块，按难度排序：

### 1-miss 模块（7 条，最简单）

| 文件 | 行 | 未覆盖原因 |
|------|-----|-----------|
| `tools/registry.py` | 45 | `ToolRegistry.reset()` 从未直接调用 |
| `tools/decorator.py` | 79 | `@tool` 参数无默认值路径缺失 |
| `tools/safety.py` | 106 | `_DANGEROUS_PATTERNS` 命中但非 tool-name 拦截路径 |
| `tools/mcp/mapping.py` | 93 | `EmbeddedResource` 内容块分支缺失 |
| `tools/mcp/config.py` | 72 | `_parse_server` 无 command 也无 url 路径 |
| `agent/middleware.py` | 106 | `make_retry_middleware` 返回值未验证 |
| `engine/store.py` | 100 | `checkpoint()` 更新已存在快照的路径 |

### 2-miss 模块（4 条）

| 文件 | 行 | 未覆盖原因 |
|------|-----|-----------|
| `tools/path_safety.py` | 41 | `WorkspacePathError` raise 路径 |
| `tools/path_safety.py` | 67 | `configure_workspace_root()` 未直接测试 |
| `tools/builtins/subagent.py` | 173 | `_resolve_role` unknown role 路径 |
| `tools/builtins/subagent.py` | 275 | `_record_step` None runtime 路径 |

### 3-4 miss 模块（7+ 条）

| 文件 | 行 | 未覆盖原因 |
|------|-----|-----------|
| `engine/observability.py` | 94,105-106,131 | subscribe/emit-exception/recent_events 未测 |
| `engine/container.py` | 91-96 | WinJobBackend 回退路径 |
| `tools/builtins/file.py` | 73-74,87-88 | WorkspacePathError except 分支 |

### 6-8 miss 模块（补充）

| 文件 | 行 | 未覆盖原因 |
|------|-----|-----------|
| `agent/system_prompt.py` | 65-66,124-127 | context_files 禁用/空 profile 路径 |
| `agent/tool_execution.py` | 51-53,145-155,165 | BaseException 处理/异常捕获/cache_key None 路径 |

## 测试清单

1. `test_registry_reset` — `tests/test_tools.py`
2. `test_decorator_default_param` — `tests/test_tools.py`
3. `test_safety_dangerous_fallthrough` — `tests/test_safety.py`
4. `test_bridge_result_embedded_resource` — `tests/test_mcp_mapping.py`
5. `test_parse_server_no_command_no_url` — `tests/test_mcp_config.py`
6. `test_make_retry_middleware_returns_callable` — `tests/test_agent_loop.py`
7. `test_checkpoint_update_existing` — `tests/test_coverage_store.py`
8. `test_resolve_under_root_escape` — `tests/test_file_search.py`
9. `test_configure_workspace_root` — `tests/test_file_search.py`
10. `test_resolve_role_unknown` — `tests/test_subagent_tools.py`
11. `test_record_step_no_runtime` — `tests/test_subagent_tools.py`
12. `test_eventbus_subscribe_recent` — `tests/test_engine_p0.py`
13. `test_eventbus_observer_exception` — `tests/test_engine_p0.py`
14. `test_container_winjob_fallback` — `tests/test_engine_p0.py`
15. `test_file_read_workspace_error` — `tests/test_file_search.py`
16. `test_file_write_workspace_error` — `tests/test_file_search.py`
17. `test_build_system_context_disabled` — `tests/test_soul.py`
18. `test_tool_execution_base_exception` — `tests/test_agent_loop.py`

## 验收标准

- AC1: `pytest --cov=src/heagent --cov-report=term` 报告 ≥90% 覆盖率
- AC2: 全部 890+ 现有测试保持通过
- AC3: ruff check + mypy src 零错误
