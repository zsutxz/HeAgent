$ErrorActionPreference = 'Stop'
$repo = 'E:\AI\HeAgent'
$codex = 'C:\Users\skype\AppData\Roaming\npm\node_modules\@openai\codex\bin\codex.js'
$prompt = @'
Use the local skill at .agents/skills/skillresearch/SKILL.md to research current techniques for writing effective AI agent skills. Follow that skill and update news/writegoodskill.md. Use current sources, cite URLs and access dates, and clearly report access limitations.
'@
Set-Location -LiteralPath $repo
& node $codex exec --cd $repo --sandbox workspace-write $prompt
if ($LASTEXITCODE -ne 0) { throw "Codex skill research failed with exit code $LASTEXITCODE" }
