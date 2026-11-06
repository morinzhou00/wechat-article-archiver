[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,
    [string]$OutputDirectory
)

$repoRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $repoRoot 'skills\wechat-article-downloader\scripts\package-skill.ps1') `
    -RepoRoot $repoRoot `
    -SkillName 'wechat-article-downloader' `
    -Version $Version `
    -OutputDirectory $OutputDirectory
$global:LASTEXITCODE = $LASTEXITCODE
[Environment]::ExitCode = $LASTEXITCODE
return
