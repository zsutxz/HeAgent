---
story_id: "3.3"
story_key: "3-3-token-counter"
epic: 3
status: ready-for-dev
created: '2026-06-05'
---

# Story 3.3: Token 计算功能

Status: ready-for-dev

## Story

As a 开发者,
I want 在发送前估算消息的 token 数量,
so that 可以进行上下文预算管理和压缩触发判断，不依赖 provider 返回的 usage。

## Acceptance Criteria

1. **Given** 一个消息列表 `list[Message]`
   **When** 调用 `count_tokens(messages)`
   **Then** 返回估算的 token 总数（int）

2. **Given** 包含中文的消息
   **When** 调用 `count_tokens(messages)`
   **Then** CJK 字符按 ~1 token/字符估算，其他字符按 ~4 字符/token

3. **Given** AgentLoop 调用 provider 前后
   **When** `_call_provider` 执行
   **Then** 日志记录预估 token 数和实际 token 数（从 response.usage）

4. **Given** `count_tokens` 函数
   **When** 被其他模块调用
   **Then** 为纯函数，无外部依赖，无 I/O

5. **Given** 每条消息
   **When** 计算 token
   **Then** 包含消息结构开销（每条消息 +3 tokens，角色标签 +3 tokens）

## Tasks / Subtasks

- [ ] Task 1: 创建 `context/tokens.py` 模块 (AC: #1, #2, #4, #5)
  - [ ] 实现 `count_tokens(messages: list[Message]) -> int`
  - [ ] 实现 `_estimate_text_tokens(text: str) -> int` — CJK 感知字符启发式
  - [ ] 消息结构开销计算
- [ ] Task 2: AgentLoop 集成 token 日志 (AC: #3)
  - [ ] 在 `_call_provider` 中记录预估 token 数和实际 token 数
- [ ] Task 3: 测试 (AC: 全部)
  - [ ] 纯英文文本估算
  - [ ] 纯中文文本估算
  - [ ] 中英混合文本估算
  - [ ] 消息列表估算（含开销）
  - [ ] 空消息列表边界

## Dev Notes

### 架构决策

- **不引入 tiktoken 依赖**：HeAgent 是多 provider 框架，tiktoken 仅适用于 OpenAI 模型
- **字符启发式**：~4 字符/token（英文），~1 字符/token（CJK），与 LangChain 的 `count_tokens_approximately` 策略一致
- **模块位置**：`context/tokens.py`，与 `context/compressor.py` 同属上下文管理

### 关键文件

- `src/heagent/context/tokens.py` — 新建
- `src/heagent/agent/loop.py` — 修改 `_call_provider` 添加日志
- `src/heagent/types.py` — `Message`, `Role` 类型

### 现有 Token 使用数据流

```
Provider.send() → ProviderResponse(usage=TokenUsage) → AgentLoop → ContextCompressor.compress(token_count=usage.total_tokens)
```

新增：发送前 `count_tokens(messages)` 估算 → 日志 → 发送 → 对比实际 usage

### Project Structure Notes

- 新模块 `context/tokens.py` 遵循模块依赖 DAG：`context/` 依赖 `types.py`，无反向依赖
- 符合 HeAgent "最小依赖" 原则：纯 Python，无第三方库

### References

- [Source: src/heagent/types.py#L23-L28] TokenUsage 定义
- [Source: src/heagent/agent/loop.py#L144-L159] 当前压缩触发逻辑
- [Source: LangChain count_tokens_approximately] 字符启发式参考
- [Source: tiktoken o200k_base] OpenAI tokenization 参考

## Dev Agent Record

### Agent Model Used

claude-opus-4-8

### Debug Log References

### Completion Notes List

### File List
