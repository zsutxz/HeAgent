# 示例：自定义工具

演示三件事：

1. `@tool` 装饰器如何**自动注册**（不用手动调 `ToolRegistry.register`）；
2. 函数签名与 docstring 如何变成给模型的工具描述；
3. Agent 如何在一轮里先调工具、再据结果给答案。

## 运行

```bash
python examples/custom-tool/main.py
```

不需要网络、不需要 API key。

## 期望输出

```text
最终答案: 工具返回了 1 条结果。
直接调用工具: chars=19 words=3
```

若你的 `.env` 里 `SANDBOX_BACKEND` 指向本机不可用的后端（例如没起 docker 却写了 `docker`），
启动时会多一行 `DockerRunner requested but not available; falling back to Passthrough`
——那是沙箱后端的显性降级提示，与本示例无关。

## 要点

- **注册时机**：装饰发生在模块导入时。`Agent()` 缺省使用全局 `ToolRegistry` 单例，
  所以只要模块被导入，工具就在表里。
- **描述来源**：`docstring` 首行 = 工具描述；参数名 + 类型注解 = JSON Schema。
  想改描述用 `@tool(description="自定义描述")`，想改名字用 `@tool(name="my_tool")`。
- **只读标注**：`read_only=True` 会设置 `readOnlyHint`，`PLAN_MODE=true` / `SANDBOX_MODE=read-only`
  下这类工具仍可用；写类工具会被拦。
- **工具名冲突**：同名重复注册会覆盖旧值（并自动从禁用集合移除）。生产代码请给前缀，
  例如 `myapp_word_count`。
- **路径校验**：示例没有接文件路径。真实工具若读写文件，必须经 `heagent.tools.path_safety`
  校验（`AGENTS.md` 的扩展约束），不要自己拼 `open()`。
