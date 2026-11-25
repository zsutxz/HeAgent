# ============================================================
# cpolar 隧道自检：一条命令跑完「公网入口」的六项判据
#
# 判据面（每项独立 PASS/FAIL，最后汇总并给退出码）：
#   C1 四段承兑（绑定面 / TLS 握手 / pin 对账 / 认证闸门）—— 带 token，期望 exit 0
#   C2 无 token 必须被拒（external 档）—— 期望 403 且 exit 0
#   C3 pin 负向对照 —— 用另一套材料当本地参照，期望**失败**且报 pin（防恒绿）
#   C4 业务连接 wss ping —— 期望 ack
#   C5 业务提交 submit —— 期望拿到 run（-SkipSubmit 跳过；会真跑一轮 agent）
#   C6 内网直连不回归 —— 对 WS_HOST:WS_PORT 重跑承兑（-SkipInternal 跳过）
#
# 地址默认四级回读（与 cpolar_tunnel.ps1 / cpolar_publish.py 同序）：本地管理面
# `http://127.0.0.1:9200/api/tunnels`（隧道活着必列 public_url，权威；兼容 4040）→
# `.heagent/tmp/cpolar-address.txt`（隧道脚本落的 = 三脚本地址共享契约）→ 付费档预留地址
# `.heagent/tmp/cpolar-remote-addr.txt` → %LOCALAPPDATA%\cpolar\tunnel*.log 的 Forwarding 行；
# 也可 -Address 显式给；token 默认读用户级 ~\.heagent\setting.md 的 ws_auth_token。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\cpolar_selftest.ps1
#       ... -Address 5.tcp.cpolar.cn:10176 -Token <token>
#       ... -SkipSubmit -SkipInternal
# 退出码：0 全过（SKIP 不算失败）/ 1 有 FAIL / 2 前提缺失（python 或 token 或地址）
# ============================================================
param(
    [string]$Address = '',
    [string]$Token = '',
    [string]$Python = '',
    [switch]$SkipSubmit,
    [switch]$SkipInternal
)

$ErrorActionPreference = 'Stop'

# ── 小工具 ──
function Stop-With([string]$message, [int]$code) {
    [Console]::Error.WriteLine($message)
    exit $code
}

function Get-AddressFromAdminApi {
    # 权威来源：cpolar 本地 web UI / API（默认 127.0.0.1:9200；兼容 ngrok 血统的 4040）。
    # 日志里未必有 Forwarding 行，而 /api/tunnels 只要隧道活着就会列出 public_url。
    # 与 cpolar_tunnel.ps1 里的同名助手刻意各留一份：两个脚本都要能单独拷走用，不互相 dot-source。
    foreach ($port in @(9200, 4040)) {
        $resp = $null
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/tunnels" -TimeoutSec 3 -UseBasicParsing
        }
        catch { continue }
        foreach ($t in @($resp.tunnels)) {
            if (-not $t) { continue }
            $url = [string]$t.public_url
            if ($url -match '^tcp://(\S+:\d+)$') { return $Matches[1] }
        }
    }
    return ''
}

function Get-AddressFromTunnelLog {
    # ⓪ 先问本地管理面：实时且权威（地址文件可能是上一轮残留）
    $live = Get-AddressFromAdminApi
    if (-not [string]::IsNullOrWhiteSpace($live)) { return $live }
    # ① 再读隧道脚本落下的地址文件（宿主 %LOCALAPPDATA% 下的日志不在 agent 可见面里）
    $hint = Join-Path $script:repoRoot '.heagent\tmp\cpolar-address.txt'
    if (Test-Path -LiteralPath $hint) {
        $value = (@(Get-Content -LiteralPath $hint -TotalCount 1 -ErrorAction SilentlyContinue) | Select-Object -First 1)
        if ($value) {
            $value = $value.Trim()
            if ($value -match '^\S+:\d+$') { return $value }
        }
    }
    # ①b 付费档「保留 TCP 地址」：手工起的隧道不落 cpolar-address.txt，但预留地址是确定的
    $reserved = Join-Path $script:repoRoot '.heagent\tmp\cpolar-remote-addr.txt'
    if (Test-Path -LiteralPath $reserved) {
        $value = (@(Get-Content -LiteralPath $reserved -TotalCount 1 -ErrorAction SilentlyContinue) | Select-Object -First 1)
        if ($value) {
            $value = $value.Trim()
            if ($value -match '^\S+:\d+$') { return $value }
        }
    }
    # ② 退到日志：cpolar 后台日志里的 Forwarding 行；只有 -Detach 方式才有。
    # 日志名带时间戳（每次起隧道一份），按 mtime 从新到旧找第一份含 Forwarding 的。
    $dir = Join-Path $env:LOCALAPPDATA 'cpolar'
    if (-not (Test-Path -LiteralPath $dir)) { return '' }
    $files = @(Get-ChildItem -LiteralPath $dir -Filter 'tunnel*' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending)
    foreach ($file in $files) {
        $hit = Select-String -LiteralPath $file.FullName -Pattern 'Forwarding\s+\S+://(\S+)' | Select-Object -Last 1
        if ($hit) { return $hit.Matches[0].Groups[1].Value }
    }
    return ''
}

function Get-UserToken {
    # 用户级 setting.md 的 frontmatter；键名不区分大小写（read_setting_md 会小写化）
    $file = Join-Path (Join-Path $env:USERPROFILE '.heagent') 'setting.md'
    if (-not (Test-Path -LiteralPath $file)) { return '' }
    foreach ($line in Get-Content -LiteralPath $file) {
        if ($line -match '^\s*(?i:ws_auth_token)\s*:\s*(.+?)\s*$') {
            return (($Matches[1] -split '\s+#', 2)[0]).Trim().Trim('"').Trim("'")
        }
    }
    return ''
}

function Get-WsTarget {
    # 内网回归用：与 cpolar_tunnel.ps1 同口径（.env 的 WS_HOST:WS_PORT，行尾注释先剥）
    $envFile = Join-Path $script:repoRoot '.env'
    $wsHost = ''
    $wsPort = 0
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile) {
            $body = ($line -split '#', 2)[0]
            if ($body -match '^\s*WS_HOST\s*=\s*(.+?)\s*$') {
                $wsHost = $Matches[1].Trim().Trim('"').Trim("'")
            }
            elseif ($body -match '^\s*WS_PORT\s*=\s*(\d+)') {
                $wsPort = [int]$Matches[1]
            }
        }
    }
    if ([string]::IsNullOrWhiteSpace($wsHost) -or $wsHost -eq '0.0.0.0' -or $wsHost -eq '::') { $wsHost = '127.0.0.1' }
    if ($wsPort -le 0) { $wsPort = 9201 }
    return "$($wsHost):$wsPort"
}

function Split-Address([string]$value) {
    if ($value -match '^\s*(.+):(\d+)\s*$') { return @($Matches[1].Trim().Trim('[', ']'), [int]$Matches[2]) }
    Stop-With "[selfcheck] 无法解析地址 '$value'（要 host:port）" 2
}

function Mask-Secret([string]$value) {
    if ([string]::IsNullOrEmpty($value)) { return '(未设置)' }
    if ($value.Length -le 8) { return ('*' * $value.Length) }
    return $value.Substring(0, 4) + ('*' * ($value.Length - 8)) + $value.Substring($value.Length - 4)
}

# ── 结果登记 ──
$results = New-Object System.Collections.ArrayList

function Add-Result([string]$name, [string]$state, [string]$detail) {
    [void]$results.Add([pscustomobject]@{ Name = $name; State = $state; Detail = $detail })
    $line = "[$state] $name"
    if ($detail) { $line += " —— $detail" }
    Write-Host $line
}

function Invoke-Step {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [ValidateSet('zero', 'nonzero')][string]$Expect = 'zero',
        [string]$ExpectText = ''
    )
    Write-Host ''
    Write-Host ("── $Name ──")
    # 被测脚本失败时会写 stderr；Stop 偏好下 native stderr 可能终止整个自检，
    # 这里临时降到 Continue，「期望失败」的负向用例才跑得下去
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = (& $script:Python @Arguments 2>&1 | Out-String).Trim()
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($out) { Write-Host $out }
    $okByCode = if ($Expect -eq 'zero') { $code -eq 0 } else { $code -ne 0 }
    $okByText = $true
    if ($ExpectText) { $okByText = ($out -match $ExpectText) }
    if ($okByCode -and $okByText) {
        Add-Result $Name 'PASS' "exit=$code"
        return
    }
    $tail = (($out -split "`r?`n") | Select-Object -Last 3) -join ' | '
    $why = if (-not $okByCode) { "期望 exit $($Expect -replace 'zero', '0' -replace 'nonzero', '非 0')，实际 $code" } else { "输出未含 /$ExpectText/" }
    Add-Result $Name 'FAIL' "$why；尾部：$tail"
}

# ── 前提 ──
$script:repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $script:repoRoot

if ([string]::IsNullOrWhiteSpace($Address)) { $Address = Get-AddressFromTunnelLog }
if ([string]::IsNullOrWhiteSpace($Address)) {
    # 自带诊断：一条命令就能判「隧道没起 / 日志在别处 / 日志里没有 Forwarding」
    $dir = Join-Path $env:LOCALAPPDATA 'cpolar'
    Write-Host '[selfcheck] 回读不到公网地址，诊断：'
    # 先判「隧道到底有没有建立」——权威信号是本地管理面，不是日志文本
    foreach ($port in @(9200, 4040)) {
        $probe = New-Object System.Net.Sockets.TcpClient
        $alive = $false
        try {
            $task = $probe.ConnectAsync('127.0.0.1', $port)
            $alive = $task.Wait(1000) -and $probe.Connected
        }
        catch { $alive = $false }
        finally { $probe.Close() }
        if ($alive) {
            Write-Host ("  管理面 127.0.0.1:{0} => 可连（但 /api/tunnels 里没有 tcp 隧道 ⇒ 隧道没建立）" -f $port)
            try {
                $body = (Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/tunnels" -TimeoutSec 3 -UseBasicParsing).Content
                Write-Host ("    /api/tunnels = {0}" -f ($body -replace '\s+', ' '))
            }
            catch { Write-Host ("    /api/tunnels 取失败：{0}" -f $_.Exception.Message) }
        }
        else {
            Write-Host ("  管理面 127.0.0.1:{0} => 不可连（cpolar 的本地 web UI 没起来）" -f $port)
        }
    }
    $procs = @(Get-Process -Name cpolar -ErrorAction SilentlyContinue)
    if ($procs.Count -eq 0) {
        Write-Host '  cpolar 进程：无 ⇒ 隧道没在跑，先跑 cpolar_tunnel.ps1 -Detach -KillExisting'
    }
    else {
        Write-Host ("  cpolar 进程：pid " + ($procs.Id -join ','))
    }
    if (Test-Path -LiteralPath $dir) {
        $items = @(Get-ChildItem -LiteralPath $dir -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
        Write-Host "  $dir 最近 5 个文件："
        foreach ($item in ($items | Select-Object -First 5)) {
            Write-Host ("    {0}  {1}B  {2}" -f $item.Name, $item.Length, $item.LastWriteTime.ToString('HH:mm:ss'))
        }
        $latest = $items | Where-Object { $_.Name -like 'tunnel*' } | Select-Object -First 1
        if ($latest) {
            Write-Host ("  最新隧道日志末 10 行（{0}）：" -f $latest.Name)
            foreach ($line in (Get-Content -LiteralPath $latest.FullName -Tail 10 -ErrorAction SilentlyContinue)) {
                Write-Host ('    ' + $line)
            }
        }
        else {
            Write-Host '  没有任何 tunnel* 日志 ⇒ 隧道是前台/服务方式起的（那种不回读，请用 -Address）'
        }
    }
    else {
        Write-Host "  $dir 不存在（cpolar 没装到默认位置？起点用了 -Dir 吗）"
    }
    Stop-With '[selfcheck] 用 -Address <host:port> 显式给地址后重跑' 2
}
$pair = Split-Address $Address
$pubHost = $pair[0]
$pubPort = $pair[1]

if ([string]::IsNullOrWhiteSpace($Token)) { $Token = Get-UserToken }
if ([string]::IsNullOrWhiteSpace($Token)) {
    Stop-With '[selfcheck] 缺 token：从 ~\.heagent\setting.md 读不到 ws_auth_token，用 -Token 传入' 2
}

if ([string]::IsNullOrWhiteSpace($Python)) {
    $candidate = Join-Path $script:repoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $candidate) { $Python = $candidate } else { $Python = 'python' }
}
$script:Python = $Python
$hasWebsockets = $false
try {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $script:Python -c 'import websockets' 2>&1 | Out-Null
    $hasWebsockets = ($LASTEXITCODE -eq 0)
}
catch { $hasWebsockets = $false }
finally { $ErrorActionPreference = $previous }
if (-not $hasWebsockets) {
    Stop-With "[selfcheck] $Python 里没有 websockets 包（pip install websockets 后再跑）" 2
}

$certPath = Join-Path $script:repoRoot '.heagent\tls\cert.pem'
$caPath = Join-Path $script:repoRoot '.heagent\tls\ca.pem'
if (-not (Test-Path -LiteralPath $certPath)) { Stop-With "[selfcheck] 缺本地叶证书 $certPath" 2 }

Write-Host "地址 = $($pubHost):$($pubPort)   token = $(Mask-Secret $Token)   python = $script:Python"
Write-Host ''

# ── C1 / C2 / C3 ──
Invoke-Step -Name 'C1 四段承兑（含 pin 对账 + 认证闸门）' -Arguments @(
    'scripts\ws_tls_attest.py', '--host', $pubHost, '--port', "$pubPort", '--token', $Token
)

Invoke-Step -Name 'C2 无 token 必须被拒（external 档）' -Arguments @(
    'scripts\ws_tls_attest.py', '--host', $pubHost, '--port', "$pubPort", '--expect-unauth', '403'
)

if (Test-Path -LiteralPath $caPath) {
    # 负向对照：拿 CA 证书当「本地叶证书」⇒ 算出来的 SPKI 必然与对端不同 ⇒ 必须判红
    Invoke-Step -Name 'C3 pin 负向对照（错材料必须判红）' -Expect 'nonzero' -ExpectText 'pin' -Arguments @(
        'scripts\ws_tls_attest.py', '--host', $pubHost, '--port', "$pubPort", '--cert', $caPath
    )
}
else {
    Add-Result 'C3 pin 负向对照（错材料必须判红）' 'SKIP' "缺 $caPath"
}

# ── C4 / C5 ──
$wssBase = "wss://$($pubHost):$($pubPort)"
Invoke-Step -Name 'C4 wss ping（真实客户端业务连接）' -Arguments @(
    'scripts\ws_manual_probe.py', $wssBase, 'ping', '--token', $Token, '--insecure'
)

if ($SkipSubmit) {
    Add-Result 'C5 wss submit（提交一句话）' 'SKIP' '-SkipSubmit'
}
else {
    Invoke-Step -Name 'C5 wss submit（提交一句话）' -Arguments @(
        'scripts\ws_manual_probe.py', $wssBase, 'submit', '--prompt', 'ping', '--token', $Token, '--insecure', '--seconds', '10'
    )
}

# ── C6 内网不回归 ──
if ($SkipInternal) {
    Add-Result 'C6 内网直连不回归' 'SKIP' '-SkipInternal'
}
else {
    $wsTarget = Get-WsTarget
    $inner = Split-Address $wsTarget
    Invoke-Step -Name "C6 内网直连不回归（$wsTarget）" -Arguments @(
        'scripts\ws_tls_attest.py', '--host', $inner[0], '--port', "$($inner[1])", '--token', $Token
    )
}

# ── 汇总 ──
Write-Host ''
Write-Host '==================== 汇总 ===================='
$pass = @($results | Where-Object { $_.State -eq 'PASS' }).Count
$fail = @($results | Where-Object { $_.State -eq 'FAIL' }).Count
$skip = @($results | Where-Object { $_.State -eq 'SKIP' }).Count
foreach ($r in $results) {
    Write-Host ("  [{0}] {1}  {2}" -f $r.State, $r.Name, $r.Detail)
}
Write-Host "PASS $pass / FAIL $fail / SKIP $skip"

if ($fail -gt 0) { exit 1 }
exit 0
