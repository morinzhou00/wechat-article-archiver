[CmdletBinding()]
param(
    [string]$DestinationRoot,
    [ValidateSet('Copy', 'Junction')]
    [string]$Mode = 'Junction',
    [switch]$Force
)

$repoRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $repoRoot 'skills\wechat-article-downloader\scripts\install-local.ps1') `
    -RepoRoot $repoRoot `
    -SkillName 'wechat-article-downloader' `
    -DestinationRoot $DestinationRoot `
    -Mode $Mode `
    -Force:$Force
$global:LASTEXITCODE = $LASTEXITCODE
[Environment]::ExitCode = $LASTEXITCODE
return
