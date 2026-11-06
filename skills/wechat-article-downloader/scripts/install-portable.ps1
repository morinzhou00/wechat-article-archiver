[CmdletBinding()]
param(
    [string]$DestinationRoot,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot 'skills\wechat-article-downloader\scripts\install-local.ps1'
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Portable installer payload is incomplete: $installer"
}
& $installer `
    -RepoRoot $PSScriptRoot `
    -SkillName 'wechat-article-downloader' `
    -DestinationRoot $DestinationRoot `
    -Mode Copy `
    -Force:$Force
$global:LASTEXITCODE = $LASTEXITCODE
[Environment]::ExitCode = $LASTEXITCODE
return
