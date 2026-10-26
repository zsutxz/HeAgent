# ============================================================
# learningclaude 每日定时任务包装脚本（无人值守 headless，经 Claude Code）
# 由 Windows 任务计划程序 HeAgent-LearningClaude-Daily 每天 09:05 触发
# 2026-10-26 自 codex exec 移植到 claude.cmd；技能本体在 .claude/skills/learningclaude/（仓库项目级）
# 日志：news\runs\learningclaude-last-run.log
# ============================================================
$ErrorActionPreference = 'Continue'
# 让 PowerShell 按 UTF-8 解析原生命令(claude.cmd)的中文输出，避免日志乱码
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Set-Location 'E:\AI\HeAgent'

$runDir = 'news\runs'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$log = Join-Path $runDir 'learningclaude-last-run.log'
"=== run start ===" | Out-File -FilePath $log -Encoding utf8

$prompt = @"
使用 learningclaude 技能（.claude/skills/learningclaude/SKILL.md），调研 Claude Code 与 Claude 模型的最新功能、新闻、基础用法、最佳实践与官方教程，并严格按该技能流程更新 news/learningclaude.md。这是无人值守的定时任务(headless)，禁止停下来询问用户、禁止等待选择，必须一路执行到底。

联网回退链：优先 WebSearch / web_reader；若报错或被拦，改用 curl 直拉官方来源（如 GitHub raw 的 CHANGELOG.md）；若联网工具整体不可用，则只更新检查日期并在来源说明如实记录"今日因网络受限未更新"，绝不凭模型记忆编造版本号或功能。

引用来源一律附 URL 与访问日期；无法访问的来源如实报告。
"@

& 'C:\Users\skype\AppData\Roaming\npm\claude.cmd' -p $prompt --dangerously-skip-permissions --verbose *>&1 |
    Out-File -FilePath $log -Encoding utf8 -Append

Add-Content -Path $log -Value "`n=== run end, claude exit=$LASTEXITCODE ==="
