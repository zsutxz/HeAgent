# ============================================================
# cpolar 内网穿透一键装配：下载绿色版 → 解压 → authtoken → 起隧道
#
# 用途：把本机 HeAgent 的 WS 入口（默认取 .env 的 WS_HOST:WS_PORT，本机即
#       192.168.2.226:9201）经 cpolar 暴露到公网，供非内网客户端连入。
# 分工（三份 cpolar 脚本，地址口径只有一套）：
#   本脚本                  = 唯一「起隧道」实现（authtoken / -remote-addr 预留地址 / 三源回读），
#                             并把结果落到 .heagent\tmp\cpolar-address.txt（host:port）——**地址唯一落点**；
#   cpolar_selftest.ps1     = 只读该文件（管理面 → 地址文件 → 预留地址 → 日志 兜底），跑六项外部判据；
#   cpolar_publish.py       = 只读该文件，把地址回填进手机 App 的 prefs（--apply / --watch），
#                             自己不拼 cpolar 参数、不解析日志当唯一来源。
# 保真：默认 `cpolar tcp <host:port>`（TCP 透传）—— TLS 端到端仍在本机，
#       客户端对服务端证书的 SPKI pin 继续有效（公网域名变了、pin 不变）。
#       换成 `-Protocol http` 会让 cpolar 在边缘终结 TLS，客户端看到的是
#       cpolar 自己的证书 ⇒ 必然 pin_mismatch（只有不校 pin 的客户端才可用）。
# 目标：**不要**只传端口 —— WS_HOST 若不是回环，127.0.0.1 上并没有 listener
#       （绑非回环后回环腿消失），只转 127.0.0.1:9201 隧道会连不上。
#       默认从仓库 .env 读 WS_HOST:WS_PORT，可用 -Target 覆盖。
# 来源：https://www.cpolar.com/download —— 版本号取自该页下载按钮，
#       若下载 404，用 -Version 传页面上的新版本号。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\cpolar_tunnel.ps1 -Authtoken <token>
#       ... -Authtoken <token> -Detach        后台起并回读公网地址
#       ... -CheckOnly                        只装配（下载+解压，无 token 也可），不起隧道
#       ... -Target 127.0.0.1:9200            改转发目标
#       ... -Reinstall                        强制重新下载
#       ... -KillExisting                     先停掉已在跑的 cpolar 进程（默认检测到就停手）
#       ... -RemoteAddr 1.tcp.vip.cpolar.cn:20046   绑定付费档「保留 TCP 地址」（固定公网 host:port）
#       ... -Region cn_vip                    保留地址所属区域（不传=账号默认区，见后台「预留」页）
# 付费档（2026-11-25 用户已升级）：后台「预留 → 保留 TCP 地址」分配固定 host:port，起隧道时用
#       -remote-addr 绑定它（官方文档 https://www.cpolar.com/blog/reserved-tcp-address：命令行是
#       `-remote-addr=`、配置文件键是 `remote_addr`，中划线/下划线不同）。绑定后公网入口不再随
#       重启漂移 ⇒ 手机端地址一次写死；TLS 仍端到端在本机，客户端 SPKI pin 不变。
#       地址会缓存到 .heagent/tmp/cpolar-remote-addr.txt，重跑不必再传。
# 回读（三源，按可信度降序）：① 本地管理面 http://127.0.0.1:9200/api/tunnels（cpolar web UI
#       默认 9200，兼容 4040）→ ② 日志里的 Forwarding 行，退到任意 `tcp://host:port` →
#       ③ -RemoteAddr 保留地址。三路都空时自动打印诊断块（管理面是否可连 + 日志相关行末 15 条）。
#       教训：3.3.12 的日志只吐 ctl 控制通道的 debug 行（`Pong from Switch Server` 只能证明
#       authtoken 有效、控制通道在线），**隧道地址不在日志里** ⇒ 只认 Forwarding 会被判成
#       「隧道没起来」的假阴性（2026-11-25 实测：三次回读全空，隧道其实已在线）。
# 退出码：0 成功 / 1 运行失败 / 2 参数或前提缺失
# ============================================================
param(
    [string]$Authtoken = '',
    [string]$Target = '',
    [ValidateSet('tcp', 'http')][string]$Protocol = 'tcp',
    [string]$Version = '3.3.12',
    [string]$Dir = '',
    [switch]$Detach,
    [switch]$CheckOnly,
    [switch]$Reinstall,
    [switch]$KillExisting,
    [string]$RemoteAddr = '',
    [string]$Region = ''
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# ── 小工具 ──
function Stop-With([string]$message, [int]$code) {
    # 走 Console.Error 而不是 Write-Error：后者在 $ErrorActionPreference='Stop'
    # 下会抛终止错误、吞掉下面的 exit，退出码就不再是这里给的语义三分
    [Console]::Error.WriteLine($message)
    exit $code
}

function Mask-Secret([string]$value) {
    if ([string]::IsNullOrEmpty($value)) { return '(未设置)' }
    if ($value.Length -le 8) { return ('*' * $value.Length) }
    return $value.Substring(0, 4) + ('*' * ($value.Length - 8)) + $value.Substring($value.Length - 4)
}

function Get-StoredAuthtoken {
    # cpolar authtoken 落在用户级 ~\.cpolar\cpolar.yml；已设过就不必再传参
    $cfg = Join-Path $env:USERPROFILE '.cpolar\cpolar.yml'
    if (-not (Test-Path -LiteralPath $cfg)) { return '' }
    $line = Get-Content -LiteralPath $cfg | Where-Object { $_ -match '^\s*authtoken\s*:' } | Select-Object -First 1
    if (-not $line) { return '' }
    return ($line -replace '^\s*authtoken\s*:\s*', '').Trim().Trim('"').Trim("'")
}

function Get-DefaultTarget {
    # 与 docs/frame/network.md 的口径一致：隧道目标 = WS listener 的真实绑定地址；
    # 绑 0.0.0.0/:: 时回落到 127.0.0.1，否则直接用 WS_HOST
    $envFile = Join-Path (Split-Path -Parent $PSScriptRoot) '.env'
    $wsHost = ''
    $wsPort = 0
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile) {
            # .env 允许行尾注释（本仓 WS_HOST 那行就带），值只取 # 之前的部分
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

function Split-Target([string]$value) {
    if ($value -match '^\s*(\d+)\s*$') { return @('127.0.0.1', [int]$Matches[1]) }
    if ($value -match '^\s*(.+):(\d+)\s*$') {
        # 只在此处做一次 IPv6 方括号脱除（py 侧唯一实现是 network.exposure.unbracket_host）
        return @($Matches[1].Trim().Trim('[', ']'), [int]$Matches[2])
    }
    Stop-With "[cpolar] 无法解析 -Target '$value'（要 host:port 或纯端口）" 2
}

function Get-PublicAddressFromAdminApi {
    # 权威来源：cpolar 本地 web UI / API（默认 127.0.0.1:9200，官方文档「cpolar web UI 默认端口号」；
    # 兼容 ngrok 血统的 4040）。日志里的 Forwarding 行在 3.3.12 上不一定出现，
    # 而 /api/tunnels 只要隧道活着就一定列出 public_url。
    # 与 cpolar_selftest.ps1 里的同名助手刻意各留一份：两个脚本都要能单独拷走用，不互相 dot-source。
    foreach ($port in @(9200, 4040)) {
        $resp = $null
        try {
            $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/tunnels" -TimeoutSec 3 -UseBasicParsing
        }
        catch { continue }
        foreach ($t in @($resp.tunnels)) {
            if (-not $t) { continue }
            $url = [string]$t.public_url
            if ($url -match '^tcp://(\S+:\d+)$') { return [pscustomobject]@{ Address = $Matches[1]; ApiPort = $port } }
        }
    }
    return $null
}

function Show-TunnelDiagnostics([string]$LogPath, [string]$ErrPath) {
    # 回读失败时一次性把判据摊开：管理面是否活着 + 日志里与隧道/失败相关的行
    Write-Host '[cpolar] 诊断（回读失败时自动跑）：'
    foreach ($port in @(9200, 4040)) {
        $probe = New-Object System.Net.Sockets.TcpClient
        $alive = $false
        try {
            $task = $probe.ConnectAsync('127.0.0.1', $port)
            $alive = $task.Wait(1000) -and $probe.Connected
        }
        catch { $alive = $false }
        finally { $probe.Close() }
        Write-Host ("  管理面 127.0.0.1:{0} => {1}" -f $port, $(if ($alive) { '可连' } else { '不可连' }))
        if ($alive) {
            try {
                $body = (Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/tunnels" -TimeoutSec 3 -UseBasicParsing).Content
                Write-Host ("    /api/tunnels = {0}" -f ($body -replace '\s+', ' '))
            }
            catch { Write-Host ("    /api/tunnels 取失败：{0}" -f $_.Exception.Message) }
        }
    }
    foreach ($f in @($LogPath, $ErrPath)) {
        if (-not (Test-Path -LiteralPath $f)) { continue }
        $hits = @(Select-String -LiteralPath $f -Pattern 'tcp://|Forwarding|error|fail|auth|region|url' -AllMatches |
            Select-Object -Last 15)
        Write-Host ("  日志 {0} 命中 {1} 行（末 15）：" -f (Split-Path -Leaf $f), $hits.Count)
        foreach ($line in $hits) { Write-Host ('    ' + $line.Line) }
    }
}

function Test-Endpoint([string]$address, [int]$port) {
    # 只做提示用：服务没起也能先起隧道，故不阻断
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync($address, $port)
        if (-not $task.Wait(2000)) { return $false }
        return $client.Connected
    }
    catch { return $false }
    finally { $client.Close() }
}

function Get-CpolarExe {
    param([string]$Root, [string]$Ver, [switch]$ForceDownload)

    $target = Join-Path $Root 'cpolar.exe'
    if ((Test-Path -LiteralPath $target) -and -not $ForceDownload) { return $target }

    $url = "https://www.cpolar.com/static/downloads/releases/$Ver/cpolar-stable-windows-amd64.zip"
    $zip = Join-Path $Root 'cpolar.zip'
    Write-Host "[cpolar] 下载 $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing

    $bytes = (Get-Item -LiteralPath $zip).Length
    if ($bytes -lt 512KB) {
        throw "下载内容仅 $bytes 字节，不像官方 zip（版本号 $Ver 是否已下线？去 https://www.cpolar.com/download 核对）"
    }

    Expand-Archive -LiteralPath $zip -DestinationPath $Root -Force
    if (Test-Path -LiteralPath $target) { return $target }

    # 官方 zip 若把 exe 放在子目录，兜底递归找一次
    $found = Get-ChildItem -LiteralPath $Root -Recurse -Filter 'cpolar.exe' -File | Select-Object -First 1
    if (-not $found) { throw '解压后未找到 cpolar.exe —— 下载内容可能不是官方包' }
    return $found.FullName
}

# ── 解析转发目标 ──
if ([string]::IsNullOrWhiteSpace($Target)) { $Target = Get-DefaultTarget }
$pair = Split-Target $Target
$targetHost = $pair[0]
$targetPort = $pair[1]
Write-Host "[cpolar] 转发目标 = $($targetHost):$($targetPort)"

# ── 装配 ──
if ([string]::IsNullOrWhiteSpace($Dir)) { $Dir = Join-Path $env:LOCALAPPDATA 'cpolar' }
if (-not (Test-Path -LiteralPath $Dir)) { New-Item -ItemType Directory -Path $Dir -Force | Out-Null }

try {
    $exe = Get-CpolarExe -Root $Dir -Ver $Version -ForceDownload:$Reinstall
}
catch {
    Stop-With "[cpolar] 准备可执行文件失败：$($_.Exception.Message)" 2
}

Write-Host "[cpolar] exe = $exe"
$verText = (& $exe version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -eq 0) {
    Write-Host "[cpolar] 版本：$verText"
}
else {
    # 版本子命令的形态随版本变，不拿它当可用性判据，只在失败时提示
    Write-Host "[cpolar] 版本探测退出码 $LASTEXITCODE（继续）：$verText"
}

# ── authtoken ──
$token = $Authtoken
if ([string]::IsNullOrWhiteSpace($token)) { $token = Get-StoredAuthtoken }
if ([string]::IsNullOrWhiteSpace($token)) {
    if ($CheckOnly) {
        # 「先只安装」的场景就该走得通：没有 token 也能把 bin 装好
        Write-Host '[cpolar] 未配置 authtoken（-CheckOnly 不阻断）：注册后到 https://dashboard.cpolar.com/auth 取，再用 -Authtoken 传入'
    }
    else {
        Stop-With '[cpolar] 缺 authtoken：到 https://dashboard.cpolar.com/auth 取，或用 -Authtoken 传入' 2
    }
}
else {
    Write-Host "[cpolar] authtoken = $(Mask-Secret $token)"
    & $exe authtoken $token | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Stop-With '[cpolar] authtoken 写入失败（cpolar 退出码非 0，检查 token 是否有效）' 1
    }
}

if ($CheckOnly) {
    Write-Host "[cpolar] -CheckOnly：已装配到 $Dir，未起隧道"
    exit 0
}

# ── 起隧道 ──
if (-not (Test-Endpoint $targetHost $targetPort)) {
    Write-Warning "[cpolar] $($targetHost):$($targetPort) 当前没有监听（服务未启动？隧道仍会建立，但访问会失败）"
}

if ($Protocol -ne 'tcp') {
    Write-Warning "[cpolar] -Protocol $Protocol 会在 cpolar 侧终结 TLS ⇒ 客户端看到的证书不是本机 cert.pem，SPKI pin 会不匹配"
}

$tunnelArg = "$($targetHost):$($targetPort)"

# ── 保留（固定）TCP 地址 ──
# 付费档在后台「预留 → 保留 TCP 地址」分配固定 host:port；绑定后公网入口不再漂移。
# 缓存与 cpolar-address.txt 分开：那个是「本次实际生效的公网地址」，这个是「账号预留的那一个」。
$repoRoot = Split-Path -Parent $PSScriptRoot
$tmpDir = Join-Path $repoRoot '.heagent\tmp'
$reservedFile = Join-Path $tmpDir 'cpolar-remote-addr.txt'
if ([string]::IsNullOrWhiteSpace($RemoteAddr) -and (Test-Path -LiteralPath $reservedFile)) {
    $cached = (@(Get-Content -LiteralPath $reservedFile -TotalCount 1 -ErrorAction SilentlyContinue) | Select-Object -First 1)
    if ($cached -and $cached.Trim()) { $RemoteAddr = $cached.Trim() }
}
if (-not [string]::IsNullOrWhiteSpace($RemoteAddr)) {
    $RemoteAddr = $RemoteAddr.Trim()
    if ($RemoteAddr -notmatch '^\S+:\d+$') {
        Stop-With "[cpolar] -RemoteAddr 形状不对（要 host:port，如 1.tcp.vip.cpolar.cn:20046）：$RemoteAddr" 2
    }
    if (-not (Test-Path -LiteralPath $tmpDir)) { New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null }
    Set-Content -LiteralPath $reservedFile -Value $RemoteAddr -Encoding ASCII
    Write-Host "[cpolar] 保留 TCP 地址 = $RemoteAddr（固定入口，重启/重连不变）"
}

# 额外参数集中在一处：前台与后台两种起法必须同源，否则只改一边就等于没绑定保留地址
$extraArgs = @()
if (-not [string]::IsNullOrWhiteSpace($Region)) { $extraArgs += "-region=$($Region.Trim())" }
if (-not [string]::IsNullOrWhiteSpace($RemoteAddr)) { $extraArgs += "-remote-addr=$RemoteAddr" }

# 已有 cpolar 进程时不要盲目再起一个（两条隧道抢同一入口，现象是间歇性连不上）
$existing = @(Get-Process -Name cpolar -ErrorAction SilentlyContinue)
if ($existing.Count -gt 0) {
    if (-not $KillExisting) {
        Stop-With ("[cpolar] 已有 $($existing.Count) 个 cpolar 进程在跑（pid " + ($existing.Id -join ',') +
            '）；确认要替换就加 -KillExisting，或先 Stop-Process 清掉') 2
    }
    $existing | Stop-Process -Force
    Start-Sleep -Milliseconds 800
    Write-Host "[cpolar] 已停止 $($existing.Count) 个既有 cpolar 进程"
}

if (-not $Detach) {
    $shown = (@($Protocol) + $extraArgs + @($tunnelArg)) -join ' '
    Write-Host "[cpolar] 前台运行：cpolar $shown（Ctrl+C 结束）"
    & $exe $Protocol @extraArgs $tunnelArg
    exit $LASTEXITCODE
}

# 每次起新隧道用独立日志名：上一个进程可能仍持有旧日志句柄，
# 沿用固定名会让 Remove-Item 抛「正由另一进程使用」而中断整条命令
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $Dir "tunnel-$stamp.log"
$errLog = "$log.err"
# 走 -RedirectStandardOutput 而不是 -log=<文件>：日志路径含空格时不用操心引号解析
$proc = Start-Process -FilePath $exe -ArgumentList (@($Protocol) + $extraArgs + @($tunnelArg, '-log=stdout')) `
    -RedirectStandardOutput $log -RedirectStandardError $errLog -PassThru
Write-Host "[cpolar] 后台启动 pid=$($proc.Id)，日志 $log"

$forward = $null
$source = ''
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 700
    # ① 本地管理面 /api/tunnels（权威：隧道活着就会列出 public_url）
    $api = Get-PublicAddressFromAdminApi
    if ($api) {
        $forward = "tcp://$($api.Address)"
        $source = "127.0.0.1:$($api.ApiPort)/api/tunnels"
        break
    }
    # ② 日志：Forwarding 行优先，退到文件里任意 tcp://host:port
    foreach ($f in @($log, $errLog)) {
        if (-not (Test-Path -LiteralPath $f)) { continue }
        $hit = Select-String -LiteralPath $f -Pattern 'Forwarding\s+\S+://(\S+:\d+)' | Select-Object -First 1
        if (-not $hit) { $hit = Select-String -LiteralPath $f -Pattern '(tcp://\S+:\d+)' | Select-Object -First 1 }
        if ($hit) {
            $forward = $hit.Matches[0].Groups[1].Value
            if ($forward -notmatch '^tcp://') { $forward = "tcp://$forward" }
            $source = (Split-Path -Leaf $f)
            break
        }
    }
    if ($forward) { break }
}

# 保留地址在握时不必依赖任何回读：它本来就不该漂移
if (-not $forward -and -not [string]::IsNullOrWhiteSpace($RemoteAddr)) {
    $forward = "tcp://$RemoteAddr"
    $source = '保留地址（-RemoteAddr）'
    Write-Host "[cpolar] 回读没拿到地址，按保留地址判定入口：$forward（连不上再看 $log）"
}

if ($forward) {
    Write-Host "[cpolar] 公网地址：$forward（来源：$source）"
    # 落一份到仓库内 = 地址共享契约：宿主 %LOCALAPPDATA% 不在 agent 的可见面里，
    # 而 cpolar_selftest.ps1 与 cpolar_publish.py 都从这里取地址（三脚本唯一公共落点）
    $addressOnly = ($forward -replace '^\w+://', '')
    if (-not (Test-Path -LiteralPath $tmpDir)) { New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null }
    Set-Content -LiteralPath (Join-Path $tmpDir 'cpolar-address.txt') -Value $addressOnly -Encoding ASCII
}
else {
    Write-Warning "[cpolar] 20 秒内回读不到公网地址（管理面 + 日志两路都空）；看下面的诊断与 $log"
    Show-TunnelDiagnostics $log $errLog
}

Write-Host ''
Write-Host '下一步：'
Write-Host '  - tcp 透传：客户端连公网地址时仍用 wss://，pin 仍是本机那份（域名变、pin 不变）'
if (-not [string]::IsNullOrWhiteSpace($RemoteAddr)) {
    Write-Host "  - 已绑定保留地址 $RemoteAddr：入口固定，手机端地址一次写死；重启后重跑本脚本即可恢复隧道"
}
else {
    Write-Host '  - 未绑定保留地址：免费额度下每次重启域名/端口会变，脚本重跑即可回读新地址'
    Write-Host '  - 付费档想固定入口：后台「预留 → 保留 TCP 地址」拿到 host:port，再用 -RemoteAddr 传入'
}
Write-Host '  - 外部验收：python scripts/ws_tls_attest.py --host <cpolar域名> --port <端口> --cert .heagent/tls/cert.pem'
Write-Host "  - 停止：Stop-Process -Id $($proc.Id)"
exit 0
