---
story_id: "3.3"
story_key: "3-3-token-counter"
epic: 3
status: done
created: '2026-06-05'
completed: '2026-07-21'
---

# Story 3.3: Token 计算功能

Status: done

## Resolution

已实现。`context/tokens.py` 提供 `count_tokens(messages)` 和 `_estimate_text_tokens(text)` ——
CJK 感知字符启发式估算，与 LangChain `count_tokens_approximately` 策略一致。
`loop.py` 的 `_call_provider` 已集成发送前预估算 + 日志对比实际 usage。
`compressor.py` 复用 `_estimate_text_tokens` 做压缩预算估算。
纯 Python，无第三方依赖（tiktoken 等），适用于所有 LLM provider。
