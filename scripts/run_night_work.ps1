# ============================================================
# HeAgent 每日自动工作清单 · 总调度（无人值守 headless）
# 由 Windows 任务计划程序 HeAgent-NightWork-Daily 触发（测试期 12:10，验收后改 00:05）
# 职责：按序执行任务表里的包装脚本；单实例锁防重叠；逐任务超时+失败隔离；
#       总日志 news\runs\night_work-last-run.log，结尾输出汇总。
# 任务表里的条目是**包装脚本**（提示词在各自脚本里，本脚本不含任何提示词）。
# everyday-news 不在本清单（用户裁定 2026-11-05：保持会话内手动触发，不定时）。
# 2026-11-05 建立，收编原 HeAgent-LearningClaude-Daily / HeAgent-WriteGoodSkill-Daily 两条 09:30 任务。
# ============================================================
$ErrorActionPreference = 'Continue'
# 让 PowerShell 按 UTF-8 解析原生命令的中文输出，避免日志乱码（同 run_learning_claude.ps1 口径）
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Set-Location 'E:\AI\HeAgent'

$runDir = 'news\runs'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$log = Join-Path $runDir 'night_work-last-run.log'

function Write-Log([string]$msg) {
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $log -Value $line -Encoding utf8
}

# ---- 单实例锁：锁文件存 PID；陈旧锁（>6h）自动破，否则视为上一轮仍在跑，直接退出 ----
$lockFile = Join-Path $runDir 'night_work.lock'
if (Test-Path $lockFile) {
    $prev = (Get-Content $lockFile -ErrorAction SilentlyContinue) -join ','
    $ageH = ((Get-Date) - (Get-Item $lockFile).LastWriteTime).TotalHours
    if ($ageH -gt 6) {
        Write-Log ("LOCK stale ({0:n1}h) -> break, prev=[{1}]" -f $ageH, $prev)
    }
    else {
        Write-Log ("LOCK held by [{0}], age={1:n2}h -> exit (another run in progress)" -f $prev, $ageH)
        exit 1
    }
}
$PID | Out-File -FilePath $lockFile -Encoding ascii

try {
    # ---- 任务表：加任务 = 加一行（新包装脚本照 run_learning_claude.ps1 的模子写） ----
    $jobs = @(
        @{ name = 'learningclaude'; script = 'E:\AI\HeAgent\scripts\run_learning_claude.ps1'; timeoutMin = 45 },
        @{ name = 'skillresearch';  script = 'E:\AI\HeAgent\scripts\run_skill_research.ps1';  timeoutMin = 60 }
    )

    '=== night_work start ===' | Out-File -FilePath $log -Encoding utf8
    Write-Log ("night_work start, jobs={0}" -f $jobs.Count)

    $results = @()
    foreach ($job in $jobs) {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        Write-Log ("JOB start: {0} (timeout {1}min)" -f $job.name, $job.timeoutMin)
        $proc = Start-Process -FilePath 'powershell.exe' `
            -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $job.script) `
            -PassThru -WindowStyle Hidden
        if (-not $proc.WaitForExit($job.timeoutMin * 60000)) {
            # 超时杀整棵进程树（taskkill /T）：只 Kill 包装进程会留下 claude.cmd 的孤儿 node
            taskkill /PID $proc.Id /T /F 2>$null | Out-Null
            $exit = 'TIMEOUT-KILLED'
        }
        else {
            $exit = $proc.ExitCode
        }
        $sw.Stop()
        $ok = ($exit -eq 0)
        Write-Log ("JOB end:   {0} exit={1} elapsed={2:n1}min" -f $job.name, $exit, $sw.Elapsed.TotalMinutes)
        $results += [pscustomobject]@{ name = $job.name; exit = $exit; minutes = [math]::Round($sw.Elapsed.TotalMinutes, 1); ok = $ok }
    }

    # ---- 收尾汇总（晨报雏形：后续任务多了在这里接 morning_brief） ----
    Write-Log 'SUMMARY:'
    foreach ($r in $results) {
        Write-Log ('  {0,-14} exit={1,-14} {2,5:n1}min {3}' -f $r.name, $r.exit, $r.minutes, $(if ($r.ok) { 'OK' } else { 'FAIL' }))
    }
    $failed = @($results | Where-Object { -not $_.ok })
    Write-Log ('night_work end, ok={0}/{1}, fail={2}' -f ($results.Count - $failed.Count), $results.Count, $failed.Count)
    '=== night_work end ===' | Add-Content -Path $log -Encoding utf8
}
finally {
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}
