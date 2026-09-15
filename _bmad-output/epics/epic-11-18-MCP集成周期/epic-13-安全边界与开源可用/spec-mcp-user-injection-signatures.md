---
title: '用户可配置 MCP 注入签名入口'
type: 'feature'
created: '2026-07-27'
revised: '2026-09-01'
status: 'done'
route: 'quick-dev'
source: 'docs/frame.md §五 已知缺口（deferred）'
---

# 用户可配置 MCP 注入签名入口

## Intent

**Problem:** `tools/mcp/mapping.py` 的返回内容启发式围栏（DP-4 第二半）当前只有**硬编码内置签名集**（`_INJECTION_PATTERNS`，10 条 = 7 条 ChatML/Mistral/system 标签 + 3 条 ignore/disregard/forget 短语）。`frame.md §五` 明确登记「用户自定义签名 deferred」——用户无法针对自己的 MCP server 工具返回特征补充签名（例如某 server 返回的私有 tokenizer 标记、领域特定的注入话术），围栏覆盖面被锁死在内置集。

**Approach:** 新增项目级配置文件 `.heagent/injection_signatures.json`，启动时（懒加载）编译为正则、与内置 `_INJECTION_PATTERNS` **合并扫描**（OR 关系）。命中处理复用现有 `guard_content` 标记透传路径，零新增语义分支。

**非目标（显式排除）:**
- ❌ 不做用户全局级 `~/.heagent/injection_signatures.json` 两级加载（简约至上；项目级单文件已满足，全局级留待后续按需开 spec）
- ❌ 不做 per-server 命名空间签名（所有 MCP server 返回共用同一签名集，与内置集一致的「MCP 整体不可信」立场）
- ❌ 不做文件热重载 / mtime 监听（进程生命周期内缓存一次，投机性灵活性）
- ❌ 不改变围栏立场：用户签名同内置——**非真正安全边界**，标记透传不阻断，须 OS 级沙箱兜底（见 CLAUDE.md 安全声明）

## Design Decisions（冻结）

| 决策 | 选定 | 理由 |
|------|------|------|
| 配置入口 | 项目级 `.heagent/injection_signatures.json` 单文件 | 与 `.heagent/` 运行时配置结构一致；受 `resolve_under_root` workspace 围栏保护 |
| 签名格式 | JSON 数组 `[{"pattern": "<regex>", "description": "<public_desc>"}]` | 与内置 `(compiled_pattern, public_desc, raw_signature)` 同构；`description` 即 public_desc |
| 加载时机 | 首次 `guard_content` 调用懒加载 → 模块级 `_USER_PATTERNS` 缓存（进程内） | `guard_content` 每次 MCP 返回都调，不能每次读盘；不监听变更（简约） |
| 测试隔离 | 加载拆为纯函数 `_load_user_signatures(path)`（无副作用、可单测）；缓存经 `_reset_user_patterns_cache()` 重置，或 `monkeypatch.setattr(mapping, "_USER_PATTERNS", [...])` 注入预编译签名 | 模块级缓存固化会跨测试污染——与 `Settings.model_config` 固化同类坑（见 commit a1c4708 conftest fixture 教训） |
| 合并语义 | `_scan_injection` 遍历 `_INJECTION_PATTERNS + _USER_PATTERNS` | OR 关系，命中 desc 合并进同一 warning 块 |
| 无效正则 | ERROR 日志 + 跳过该条，不阻断加载 | 平衡「显性失败」与「可用性」（一条坏签名不毁全部）；对齐 persist.py 损坏 JSON 容错 |
| JSON 损坏 / 文件缺失 | ERROR 日志 + 视为空签名集（零回归） | 对齐 persist.py `load_json_model` 损坏容错惯例 |
| raw 泄漏约束 | 用户签名 `raw = pattern` 字符串，**仅 DEBUG 日志**，不进 in-band warning | 与内置一致——避免 tokenizer 标记二次写入上下文放大攻击面（mapping.py:100-101 既有约束） |

## Acceptance Criteria

- **AC1**：项目根存在合法 `.heagent/injection_signatures.json`（≥1 条签名）时，MCP 工具返回命中用户签名 → 返回文本前缀 warning 标记块（`[⚠ MCP 返回命中注入启发式: ...]`），`is_error=False` 透传。
- **AC2**：用户签名 + 内置签名同时命中 → warning 块的 `patterns` 字段合并两者的 public_desc（去重可选，不强制）。
- **AC3**：用户签名的原始 `pattern` 字节**不出现在 in-band warning 文本**中（仅 `description` 出现）；DEBUG 日志含 raw（与内置一致）。**且 `description` 本身不得含字面 tokenizer 标记**——它也在 in-band（作 public_desc），同样放大攻击面；加载器校验 description 命中 `_INJECTION_PATTERNS` 的条目 → WARNING + 跳过。
- **AC4**：`.heagent/injection_signatures.json` 含**无效正则**条目 → 该条跳过、记 ERROR 日志，其余有效条目正常生效，围栏不整体失效。
- **AC5**：`.heagent/injection_signatures.json` **JSON 损坏**或**文件缺失** → 记 ERROR（损坏）/ 静默（缺失），等价空签名集，内置围栏零回归。
- **AC6**：生产路径懒加载只读盘一次（进程内缓存）——第二次 `guard_content` 调用不重复读盘/编译。**测试不依赖读盘副作用**：经 `monkeypatch.setattr(mapping, "_USER_PATTERNS", [...])` 注入预编译签名或调 `_reset_user_patterns_cache()` 驱动各文件状态，避免缓存跨测试污染。
- **AC7**：ruff / mypy 干净；新增测试全绿；既有 `tests/test_mcp_mapping.py` guard_content / bridge_result 围栏测试（约 15 例）零回归。

## Constraints（硬约束，违反即架构错误）

1. **立场不变**：用户签名层非真正安全边界，须 OS 级沙箱兜底。CLAUDE.md / frame.md §五 安全声明同步加一句「用户自定义签名同属 defense-in-depth，非真正边界」。
2. **raw 不进 in-band**：用户签名的 `pattern` 原始字节只在 DEBUG 日志，不进返回给 LLM 的 warning 文本（防 tokenizer 标记二次注入）。
3. **不抛裸 Exception**：加载/编译错误经 `logging.getLogger(__name__)` 记录，不向上抛（围栏失败不得崩 MCP 调用链）。
4. **Pydantic / 类型**：用户签名加载后转为 `list[tuple[re.Pattern[str], str, str]]`（与 `_INJECTION_PATTERNS` 同型），`_scan_injection` 不引入原始 dict。
5. **路径围栏**：配置文件经 `resolve_under_root`（`tools/path_safety.py`）解析到 workspace_root 下，禁止路径逃逸（与 file 工具一致）。
6. **全异步库无同步 I/O 例外**：配置加载是启动期一次性同步 `Path.read_text`（非工具 handler 路径、非热路径），与 `config.py` 加载 `.env` 同性质，可接受；不引入 `asyncio.to_thread`（过度工程）。
7. **description 在 in-band（与 raw 同约束）**：用户签名的 `description` 进 warning 文本，**不得含字面 tokenizer 特殊标记**（防二次注入，见 AC3）；加载器校验，命中 `_INJECTION_PATTERNS` 记 WARNING + 跳过该条（fail-safe，不阻断其余）。

## Test Anchors（`tests/test_mcp_mapping.py` 扩展）

- `test_user_signature_hit_adds_warning`：写临时 `.heagent/injection_signatures.json`（1 条），断言命中 → warning 标记 + 透传。
- `test_user_and_builtin_signatures_merge`：用户签名 + 内置签名同时命中 → 合并 desc。
- `test_user_pattern_raw_not_in_band`：用户 pattern 含 `<|im_start|>` 类标记 → 返回文本不含 pattern 原始字节，只含 description。
- `test_user_description_with_token_marker_skipped`：description 含字面 tokenizer 标记（如 `<|im_start|>`）→ WARNING + 跳过该条（AC3 / 约束 7）。
- `test_invalid_user_regex_skipped_with_error`：1 条无效正则 + 1 条有效 → 无效跳过（ERROR 日志）、有效命中。
- `test_corrupted_json_falls_back_to_builtin`：损坏 JSON → ERROR + 内置围栏零回归。
- `test_missing_signature_file_silent`：无文件 → 静默，零回归。
- `test_lazy_load_cached_once`：spy `_load_user_signatures`，两次 guard_content → 仅调用一次（验证生产路径懒加载；其余用例经 monkeypatch 注入预编译签名，不走读盘）。

## Suggested Review Order（实施后审查）

- `src/heagent/tools/mcp/mapping.py` —— `_USER_PATTERNS` 懒加载 + `_scan_injection` 合并 + raw 不泄漏
- `tests/test_mcp_mapping.py` —— 7 例新测试
- `docs/frame.md` §五 —— 移除「用户自定义签名 deferred」（改为「已交付：项目级 `.heagent/injection_signatures.json`，全局级仍 deferred」）
- `CLAUDE.md` 安全声明 —— 加「用户自定义签名同属 defense-in-depth，非真正边界」一句

## 附带 chore（独立于本 spec，实施时顺手）

核实 `frame.md §五` + `docs/learning.md` 的「流式 tool_calls 回退」缺口描述**已过时**——OpenAI/Anthropic `stream` 已原生化产出 tool_calls（openai.py:230-245 / anthropic.py:257-259），`run_stream` loop.py:298-299 已收集；loop.py:348 的 `finish_reason=="tool_calls"` 回退是 defense-in-depth 死路径（当前所有 provider 不同时缺失 tool_calls）。**不改代码**（不改不坏的代码），仅同步两份文档的缺口描述。
