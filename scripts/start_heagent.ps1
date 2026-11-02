# ============================================================
# HeAgent 启动器：把工作区根钉在本仓库目录（E:\AI\HeAgent）
# 原因：workspace_root = 启动进程的 cwd（cli/composition.py 把
#       WorkspacePaths.from_root(os.getcwd()) 填进 workspace_root）
#       ⇒ 从 E:\ 启动会把整块 537 GB 盘以 9p（cache=0）挂进容器沙箱，
#       这是 Docker daemon/IO 卡顿的放大器；从本目录启动则挂载面自动
#       收窄到仓库（文件工具可见范围一并收窄）。
# 用法：scripts\start_heagent.ps1                    # 交互模式
#       scripts\start_heagent.ps1 http-server        # 网页入口
#       scripts\start_heagent.ps1 "写一个快速排序"   # 单次执行
# ============================================================
$ErrorActionPreference = 'Stop'

# 仓库根 = 本脚本所在目录的父目录；-LiteralPath 防路径含特殊字符被通配
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }

Write-Host "[start_heagent] cwd = $((Get-Location).Path)"
Write-Host "[start_heagent] python = $python"

& $python -m heagent @args
exit $LASTEXITCODE
