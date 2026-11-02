# ============================================================
# 清理 HeAgent 沙箱孤儿容器
# 场景：Docker daemon 挂起时 docker kill / inspect / rm -f 全部超时，
#       一次性容器可能残留（它们带 workspace 写挂载，属真实暴露面）。
# 安全：只删名字精确匹配 heagent-<12 位十六进制> 的容器，其它容器一律不碰。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\cleanup_orphan_containers.ps1
#       ... -DryRun   仅列出，不删除
# ============================================================
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'

$rows = @(docker ps -a --format '{{.ID}}|{{.Names}}|{{.Status}}')
if ($LASTEXITCODE -ne 0) {
    Write-Error 'docker ps 失败：daemon 可能仍未响应，请先重启 Docker Desktop'
    exit 1
}

$targets = @()
foreach ($row in $rows) {
    if (-not $row) { continue }
    $parts = $row -split '\|', 3
    if ($parts.Count -lt 2) { continue }
    if ($parts[1] -match '^heagent-[0-9a-f]{12}$') {
        $targets += [pscustomobject]@{ Id = $parts[0]; Name = $parts[1]; Status = $parts[2] }
    }
}

if ($targets.Count -eq 0) {
    Write-Host '没有匹配 heagent-<12 hex> 的容器（已清理干净）'
    exit 0
}

Write-Host "匹配到 $($targets.Count) 个 HeAgent 沙箱容器："
$targets | ForEach-Object { Write-Host ("  {0}  {1}  {2}" -f $_.Id, $_.Name, $_.Status) }

if ($DryRun) { Write-Host '(-DryRun：未执行删除)'; exit 0 }

$failed = 0
foreach ($t in $targets) {
    docker rm -f $t.Id | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "删除失败：$($t.Name)（daemon 仍未响应？先重启 Docker Desktop 再跑本脚本）"
        $failed++
    } else {
        Write-Host "已删除：$($t.Name)"
    }
}

Write-Host "完成：成功 $($targets.Count - $failed) 个，失败 $failed 个"
if ($failed -gt 0) { exit 2 }
exit 0
