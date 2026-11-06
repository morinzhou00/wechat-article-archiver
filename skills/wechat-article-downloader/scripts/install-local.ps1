[CmdletBinding()]
param(
    [string]$RepoRoot,
    [ValidatePattern('^[a-z0-9-]+$')]
    [string]$SkillName,
    [string]$DestinationRoot,
    [ValidateSet('Copy', 'Junction')]
    [string]$Mode = 'Junction',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
if (-not $RepoRoot) {
    if (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'skills')) {
        $RepoRoot = $PSScriptRoot
    } else {
        throw 'Pass -RepoRoot when running the installer from inside a source skill.'
    }
}
$repoPath = [IO.Path]::GetFullPath($RepoRoot)
if (-not $SkillName) {
    $candidates = @(Get-ChildItem -LiteralPath (Join-Path $repoPath 'skills') -Directory |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'SKILL.md') })
    if ($candidates.Count -ne 1) {
        throw 'Pass -SkillName because the portable package does not contain exactly one installable skill.'
    }
    $SkillName = $candidates[0].Name
}
$source = [IO.Path]::GetFullPath((Join-Path $repoPath "skills\$SkillName"))
if (-not (Test-Path -LiteralPath (Join-Path $source 'SKILL.md'))) {
    throw "Installable source not found: $source"
}
if (-not $DestinationRoot) {
    if ($env:CODEX_HOME) {
        $DestinationRoot = Join-Path $env:CODEX_HOME 'skills'
    } elseif (Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.codex')) {
        $DestinationRoot = Join-Path $env:USERPROFILE '.codex\skills'
    } else {
        $DestinationRoot = Join-Path $env:USERPROFILE '.agents\skills'
    }
}
$root = [IO.Path]::GetFullPath($DestinationRoot)
$destination = [IO.Path]::GetFullPath((Join-Path $root $SkillName))
if (-not $destination.StartsWith($root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
    [IO.Path]::GetFileName($destination) -ne $SkillName) {
    throw "Refusing unsafe destination: $destination"
}
New-Item -ItemType Directory -Path $root -Force | Out-Null
if (Test-Path -LiteralPath $destination) {
    if (-not $Force) { throw "Destination exists: $destination" }
    Remove-Item -LiteralPath $destination -Recurse -Force
}
if ($Mode -eq 'Junction') {
    New-Item -ItemType Junction -Path $destination -Target $source | Out-Null
} else {
    Copy-Item -LiteralPath $source -Destination $destination -Recurse
}
[ordered]@{
    ok = $true
    skill = $SkillName
    source = $source
    destination = $destination
    mode = $Mode
} | ConvertTo-Json -Depth 4
