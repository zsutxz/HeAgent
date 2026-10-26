# ============================================================
# skill_research 每日定时任务包装脚本（无人值守 headless，经 Claude Code）
# 由 Windows 任务计划程序 HeAgent-WriteGoodSkill-Daily 每天 09:20 触发
# 2026-10-26 自 codex exec 移植到 claude.cmd；技能本体在 .claude/skills/skill_research/（仓库项目级）
# 日志：news\runs\skill_research-last-run.log
# ============================================================
$ErrorActionPreference = 'Continue'
# 让 PowerShell 按 UTF-8 解析原生命令(claude.cmd)的中文输出，避免日志乱码
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Set-Location 'E:\AI\HeAgent'

$runDir = 'news\runs'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$log = Join-Path $runDir 'skill_research-last-run.log'
"=== run start ===" | Out-File -FilePath $log -Encoding utf8

$prompt = @"
使用 skill_research 技能（.claude/skills/skill_research/SKILL.md），从 GitHub 选取一个优秀 agent skill 深读，按该技能流程把总结研究对象整体的案例卡（含解剖样本）写入 news/skill_example/<对象名>.md，并基于 news/skill_example/ 全部案例更新 news/skillresearch.md 综合方法报告。这是无人值守的定时任务(headless)，禁止停下来询问用户、禁止等待选择，必须一路执行到底。

联网回退链：优先 WebSearch / web_reader；若报错或被拦，改用 curl 直拉官方来源（如 GitHub raw 文件）；若联网工具整体不可用，则只更新检查日期并在来源说明如实记录"今日因网络受限未更新"，绝不编造来源或结论。

引用来源一律附 URL 与访问日期；无法访问的来源如实报告。
"@

& 'C:\Users\skype\AppData\Roaming\npm\claude.cmd' -p $prompt --dangerously-skip-permissions --verbose *>&1 |
    Out-File -FilePath $log -Encoding utf8 -Append

Add-Content -Path $log -Value "`n=== run end, claude exit=$LASTEXITCODE ==="
