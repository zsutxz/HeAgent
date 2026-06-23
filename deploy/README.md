# HeAgent 生产部署指南

## 部署方式

### 方式一：Docker 部署（推荐）

适合：服务器 / 云环境 / CI/CD 流水线

```bash
# 1. 配置环境变量
cp .env.production.example .env.production
# 编辑 .env.production 填入 API Key

# 2. 一键部署
bash deploy/deploy.sh docker

# 3. 查看运行状态
docker-compose ps
docker-compose logs -f

# 4. 测试
docker-compose run --rm heagent "你好，请介绍一下你自己"

# 5. 停止服务
docker-compose down
```

### 方式二：宿主机部署（Systemd）

适合：生产服务器 / 需要与其他服务集成的场景

```bash
# 1. 配置环境变量
cp .env.production.example .env.production
# 编辑 .env.production 填入 API Key

# 2. 一键部署（需 sudo 权限）
bash deploy/deploy.sh host

# 3. 服务管理
sudo systemctl status heagent     # 查看状态
sudo journalctl -u heagent -f     # 查看日志
sudo systemctl restart heagent    # 重启
sudo systemctl stop heagent       # 停止
```

### 方式三：开发/测试

```bash
# 安装
pip install -e ".[dev]"

# 运行
python -m heagent "你的问题"       # 单次模式
python -m heagent                   # 交互模式
```

---

## 生产环境检查清单

### 1. 安全加固 ✅

- [ ] API Key 使用密钥管理服务（如 AWS Secrets Manager / HashiCorp Vault）
- [ ] 永远不要将 `.env.production` 提交到 git（已在 `.gitignore` 中）
- [ ] 使用非 root 用户运行（Dockerfile 已配置 `USER heagent`）
- [ ] 容器安全：`no-new-privileges:true`，`cap_drop: ALL`
- [ ] 启用 HTTPS（如果暴露 HTTP 端点）

### 2. 监控与告警

- [ ] 配置日志聚合（ELK / Grafana Loki / Datadog）
- [ ] 设置 API 调用量监控（避免预算超支）
- [ ] 配置磁盘空间告警（数据持久化目录）
- [ ] 监控 Provider 可用性（降级切换）

### 3. 性能调优

- [ ] 根据业务量调整 `MAX_ITERATIONS`（默认 50）
- [ ] 设置合理的 `MAX_CONTEXT_TOKENS` 防止上下文爆满
- [ ] Docker 资源限制建议：CPU 1-2 核，内存 1-2 GB

### 4. 数据持久化

- [ ] 确保 `.heagent/` 目录挂载到持久化存储
- [ ] 定期备份技能和记忆数据
- [ ] 考虑将数据目录挂载到 NAS / 云存储

### 5. 部署流水线（CI/CD）

```yaml
# .github/workflows/deploy.yml 示例
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Build & Deploy
        run: |
          docker build -t heagent:latest .
          docker tag heagent:latest your-registry/heagent:latest
          docker push your-registry/heagent:latest
          # SSH 到服务器拉取新镜像重启
```

---

## 生产环境最佳实践

### 日志管理

生产环境建议将日志级别设为 `WARNING`，减少磁盘 I/O：

```bash
LOG_LEVEL=WARNING
```

### 多 Provider 冗余

配置多个 API Key，实现自动降级：

```bash
DEEPSEEK_API_KEY=sk-xxx
OPENAI_API_KEY=sk-yyy
ANTHROPIC_API_KEY=sk-zzz
```

当 DeepSeek 不可用时，自动切换到 OpenAI → Anthropic。

### 资源限制

根据实际负载调整 Docker 资源限制：

```yaml
deploy:
  resources:
    limits:
      cpus: "2.0"        # 最多 2 核
      memory: 2G         # 最多 2 GB
    reservations:
      cpus: "0.5"        # 保证 0.5 核
      memory: 512M       # 保证 512 MB
```

---

## 故障排查

| 问题 | 排查方法 |
|------|---------|
| 服务无法启动 | `docker-compose logs` / `journalctl -u heagent -x` |
| API 调用失败 | 检查 `.env.production` 中的 API Key 是否有效 |
| 预算超限 | 检查 `MAX_ITERATIONS` 设置，或配置 Provider 用量限制 |
| 内存不足 | 增大 Docker `memory` 限制，或减少 `MAX_TOKENS` |
| 数据丢失 | 检查 `volumes` 挂载是否正确 |

---

## 更新升级

```bash
# Docker 方式
cd /path/to/heagent
git pull                          # 拉取最新代码
docker-compose down               # 停止旧服务
docker-compose build --no-cache   # 重建镜像
docker-compose up -d              # 启动新服务

# 宿主机方式
cd /path/to/heagent
git pull
bash deploy/deploy.sh host
```
