# 时效性与技术栈适配评审

审查日期：2026-09-23
范围：依据已提交的项目元数据和锁文件，核查 `ARCHITECTURE-SPINE.md` 中命名的 HTTP 技术栈及版本。

## 发现

### F1 - HTTP 依赖实际上尚未被声明为可选依赖 [必须在实现前解决]

`ARCHITECTURE-SPINE.md:126-131` 将 Starlette 1.3.1 和 Uvicorn 0.50.1 称为“可选 HTTP 依赖”，并要求它们缺失时给出安装诊断。但已提交的 manifest 没有 `http` 可选依赖组，也没有直接声明任一包（`pyproject.toml:29-60`）。当前锁文件是通过必需的 `mcp` 间接引入这两个包（`uv.lock:1004-1022`），因此普通基础安装会得到它们，版本也由 MCP 依赖图控制。

这使架构中的可选安装契约无法按原样实现，并使其容易受到 MCP 依赖变更影响。进入 Story 49-1 前必须显式决策：

- 添加包含兼容 Starlette/Uvicorn 约束的直接 `http` extra，并使 HTTP 命令要求安装该 extra；或
- 将服务端技术栈作为直接基础依赖，并删除“缺失时提示安装”的要求。

不得依赖偶然存在的 MCP 传递依赖作为 HTTP 服务契约。

## 已确认事实

- 脊柱中命名的精确技术栈版本存在于当前锁文件：Starlette 1.3.1（`uv.lock:1926-1935`）和 Uvicorn 0.50.1（`uv.lock:2068-2077`）。
- Pydantic 的说明准确：项目将其约束为 `>=2.13,<2.14`（`pyproject.toml:30`），锁文件解析为 2.13.4（`uv.lock:1378-1387`）。
- ASGI/asyncio 及依赖注入的传输边界与现有 TCP 入口模式一致：`docs/frame.md:102` 将 `network/` 定义为仅负责传输的层，`docs/frame.md:968-989` 将运行时组合交给 `cli_tcp.py`，并共享 `network.exposure`。
