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
| `deploy/README.md` | 本文件 | ✅ 当前 |

`deploy/heagent.service` 已移除（交互式 CLI 不适合作为 systemd 守护进程）。

## 生产前检查项

- **API Key**：通过 `.env.production` 或环境变量注入，勿硬编码。
- **工作目录**：`.heagent/` 含技能、记忆、会话、快照、Cron 数据，确保持久化（Docker 用 volume）。
- **OS 级沙箱**：`shell` / MCP 工具执行不可信代码，须容器或 firejail 等 OS 级隔离（`SafetyGuard` 非真正安全边界）。
- **网络权限**：限制出站到必需的 LLM API 端点即可。
- **备份**：`.heagent/` 定期备份。
- **日志**：生产环境建议 `LOG_LEVEL=WARNING`。

## 版本发布

```bash
# 打 tag 触发 CI release（PyPI + GHCR + Docker Hub）
git tag v0.3.0
git push origin v0.3.0
```

CI release job 自动：
1. `twine check` → PyPI（Trusted Publisher OIDC）
2. `docker buildx` → GHCR + Docker Hub（multi-arch: amd64 + arm64）
