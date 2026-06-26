# HeAgent 部署说明

这份文档只说明当前仓库里的部署资产“实际上能做什么”。结论先说在前面：**HeAgent 目前主要是 CLI / Python API 项目，不是现成的常驻 HTTP 服务。**

## 当前现状

代码入口是：

- `python -m heagent "prompt"`：单次执行
- `python -m heagent`：交互模式
- `heagent ...`：等价的安装后命令

当前实现里没有：

- HTTP API
- `/health` 健康检查端点
- 服务模式的 `MODE` 配置
- `LOG_LEVEL`、`HEAGENT_DATA_DIR`、`MAX_TOKENS`、`TEMPERATURE` 这些核心配置项

因此，仓库中的 `Dockerfile`、`docker-compose.yml`、`deploy.sh`、`heagent.service` 应视为**部署草稿或模板资产**，不能不加审查地当成现成生产方案。

## 现在可以可靠使用的方式

### 本地开发

```bash
pip install -e ".[dev]"
python -m heagent "你好"
```

交互模式：

```bash
python -m heagent
```

### 容器里单次执行

镜像本身可以构建，入口也是 `python -m heagent`：

```bash
docker build -t heagent .
docker run --rm --env-file .env.production heagent "你好"
```

交互模式：

```bash
docker run -it --rm --env-file .env.production heagent
```

如果需要在容器里保留 `.heagent/` 运行数据，请自行挂载工作目录或单独的数据卷。

## 仓库内部署资产的限制

### `Dockerfile`

可以构建 CLI 镜像，但有一处明显未对齐的地方：

- 当前 `HEALTHCHECK` 指向 `http://localhost:8080/health`
- 代码里并没有对应的 HTTP 服务

在真正使用前，需要删除或改写这段健康检查。

### `docker-compose.yml`

这个文件更接近示例骨架，而不是已验证方案。当前至少有这些不一致：

- 暴露了 `8080` 端口，但进程并不监听端口
- 注入了 `MODE`、`LOG_LEVEL`、`HEAGENT_DATA_DIR`，但 CLI 不读取这些配置
- 默认形态更像“假设未来会服务化”，不是当前代码的真实运行方式

如果你要保留这个文件，建议把它改成明确的批处理或交互式容器用法。

### `deploy/heagent.service`

这个 unit 文件当前也只是模板：

- `ExecStart=/opt/heagent/.venv/bin/python -m heagent`
- 没有传入 prompt，也没有外层服务循环
- 这会进入交互模式，不适合作为无人值守 systemd 服务

如果要用 systemd，先决定你真正要托管的是什么：

- 固定 prompt 的定时批处理
- 你自己包装的 HTTP/队列消费者
- 另一个上层守护进程

### `deploy/deploy.sh`

它展示了大致部署流程，但不应直接视为可执行运维方案：

- `docker` 模式会在构建镜像后执行 `git pull`
- `host` 模式依赖 `sudo`、复制目录和当前的 systemd 模板
- 缺少对真实服务形态的定义

把它当成脚手架比当成产品脚本更合适。

## 如果你要做真正的部署

建议先补齐一层明确的宿主形态，再谈容器或 systemd：

1. 先定义进程模型。
   例如“单次任务执行器”“队列消费者”“自建 HTTP API 包装层”。
2. 再定义启动命令。
   不要直接把交互式 CLI 当作后台守护进程。
3. 把 `.heagent/` 持久化。
   其中包含技能、记忆、会话、运行快照和 Cron 数据。
4. 提供 OS 级隔离。
   尤其是开启 shell、文件工具或 MCP 时。
5. 单独实现健康检查与可观测性。
   这需要你的包装层暴露明确的进程状态，而不是复用当前占位配置。

## 生产前检查项

- 只使用受控的工作目录，不要直接挂宿主敏感目录。
- 把 Provider 密钥放进环境变量或密钥管理系统。
- 如果启用 MCP，按不可信代码执行模型处理。
- 限制容器/进程的网络出站权限。
- 明确 `.heagent/` 的备份和清理策略。
- 为外层包装服务补日志、指标和健康检查。

## 推荐理解方式

更准确的理解是：

- 这个仓库已经有“可运行的 Agent 内核”
- 但还没有“定义完成的服务部署产品”

所以这里的部署文档不是“一键上线指南”，而是“如何判断哪些资产可复用、哪些需要你自己补齐”的说明。
