# HeAgent 部署说明

HeAgent 是 CLI 工具 + Python 库，**不是常驻 HTTP 服务**。部署即安装，通过命令行或容器使用。

## 使用方式

### pip install（推荐）

```bash
pip install heagent

# 单次执行
heagent "你的问题"

# 交互模式
heagent
```

### Windows exe（免 Python 环境）

```bash
# 单次执行
heagent.exe "你的问题"

# 交互模式
heagent.exe

# 终端 UI（textual 扩展）
heagent.exe gui
```

exe 为 PyInstaller one-file 单文件产物，含内置工具 / MCP SDK / textual GUI，无需安装 Python 与依赖。

### Docker

```bash
docker compose build
docker compose run --rm heagent "你的问题"   # 单次执行
docker compose run --rm heagent               # 交互模式
```

### 定时任务

HeAgent 内置 cron 调度器（交互模式内 `/cron` 命令或 `cron_add` 工具），进程退出后不持久。生产级定时任务建议外层系统 cron 触发单次执行：

```bash
# crontab -e
0 9 * * * cd /path/to/project && docker compose run --rm heagent '每日任务 prompt'
```

## 仓库部署资产

| 文件 | 用途 | 状态 |
|------|------|------|
| `Dockerfile` | 多阶段构建，非 root 用户，OCI labels | ✅ 就绪 |
| `docker-compose.yml` | `docker compose run --rm` CLI 一次性/交互用法 | ✅ 就绪 |
| `deploy/deploy.sh` | 一键部署脚本（docker / host 两种模式） | ✅ 就绪 |
| `deploy/heagent.spec` | Windows exe 打包 spec（PyInstaller） | ✅ 就绪 |
| `deploy/README.md` | 本文件 | ✅ 当前 |

`deploy/heagent.service` 已移除（交互式 CLI 不适合作为 systemd 守护进程）。

## Windows exe 构建

前置：Windows + Python 3.11+，已安装本项目（含 `[gui]` extra）与 PyInstaller：

```bash
pip install -e ".[gui]"
pip install pyinstaller typer   # typer 仅供 mcp.cli 收集，非运行时依赖

# 构建（在 deploy/ 目录下执行，spec 内相对路径以 deploy/ 为基准）
cd deploy
..\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean heagent.spec
```

产出：`deploy/dist/heagent.exe`（one-file，约 31 MB）。

验证：

```bash
deploy/dist/heagent.exe --help     # CLI 可用
deploy/dist/heagent.exe gui --help # textual GUI 已打包
```

spec 要点：

- `console=True`：heagent 是 CLI 工具（交互式聊天 / 单次执行），非 GUI 窗口程序。
- `collect_all("mcp")`：MCP SDK 含动态子模块导入（stdio/http transport、类型注册），静态分析会漏，须整体收集。
- `collect_all("textual")`：GUI（textual 扩展）含动态 widget/screen 加载，整体收集。
- openai / anthropic / httpx / pydantic 为常规静态导入，由 Analysis 自动追踪。

## 生产前检查项

- **API Key**：通过 `.env.production` 或环境变量注入，勿硬编码。
- **工作目录**：`.heagent/` 含技能、记忆、会话、快照、Cron 数据，确保持久化（Docker 用 volume）。
- **OS 级沙箱**：`shell` / MCP 工具执行不可信代码，须容器或 firejail 等 OS 级隔离（`SafetyGuard` 非真正安全边界）。
- **网络权限**：限制出站到必需的 LLM API 端点即可。
- **备份**：`.heagent/` 定期备份。
- **日志**：生产环境建议 `LOG_LEVEL=WARNING`。

## 版本发布

```bash
# 打与 pyproject.toml 一致的版本 tag 触发 CI release（PyPI + GHCR + Docker Hub）
git tag v0.6.1
git push origin v0.6.1
```

`v0.6.1` 是当前待创建的发布 tag；发布前应确认它与 `pyproject.toml` 和 `src/heagent/__init__.py` 的版本一致。Docker Hub 推送还依赖 CI secrets `DOCKERHUB_USERNAME` 与 `DOCKERHUB_TOKEN`，未配置时该步骤不可用。

CI release job 自动：
1. `twine check` → PyPI（Trusted Publisher OIDC）
2. `docker buildx` → GHCR + Docker Hub（multi-arch: amd64 + arm64）
