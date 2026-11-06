[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RepoRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^[a-z0-9-]+$')][string]$SkillName,
    [Parameter(Mandatory = $true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'

function Copy-SkillTree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $sourceFull = [IO.Path]::GetFullPath($Source).TrimEnd('\')
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    & robocopy.exe $sourceFull $Destination /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP `
        /XD '.runtime' '__pycache__' '*.egg-info' `
        /XF '*.pyc' '*.pyo' | Out-Null
    $copyExitCode = $LASTEXITCODE
    if ($copyExitCode -gt 7) {
        throw "Failed to stage Skill files with robocopy (exit code $copyExitCode)."
    }
    $global:LASTEXITCODE = 0
}

$repo = [IO.Path]::GetFullPath($RepoRoot)
$skill = [IO.Path]::GetFullPath((Join-Path $repo "skills\$SkillName"))
if (-not (Test-Path -LiteralPath (Join-Path $skill 'SKILL.md'))) {
    throw "Installable source not found: $skill"
}
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $repo 'release' }
$output = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $output -Force | Out-Null
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$stageName = 'wechat-skill-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$stageRoot = [IO.Path]::GetFullPath((Join-Path $tempRoot $stageName))
if (
    -not $stageRoot.StartsWith($tempRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or
    -not (Split-Path -Leaf $stageRoot).StartsWith('wechat-skill-', [StringComparison]::OrdinalIgnoreCase)
) {
    throw "Unsafe staging path: $stageRoot"
}
$skillStage = Join-Path $stageRoot $SkillName
$portable = Join-Path $stageRoot "$SkillName-v$Version"
New-Item -ItemType Directory -Path $skillStage,(Join-Path $portable "skills\$SkillName") -Force | Out-Null
try {
    Copy-SkillTree -Source $skill -Destination $skillStage
    Copy-SkillTree -Source $skill -Destination (Join-Path $portable "skills\$SkillName")
    Copy-Item -LiteralPath (Join-Path $skillStage 'scripts\install-portable.ps1') -Destination (Join-Path $portable 'install.ps1')
    foreach ($name in @(
        'README.md',
        'LICENSE',
        'SECURITY.md',
        '公众号历史归档器-使用说明.md',
        '启动公众号归档器.cmd',
        '归档公众号历史.ps1'
    )) {
        $source = Join-Path $repo $name
        if (Test-Path -LiteralPath $source) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $portable $name)
        }
    }
    $docs = Join-Path $repo 'docs'
    if (Test-Path -LiteralPath $docs) {
        Copy-Item -LiteralPath $docs -Destination (Join-Path $portable 'docs') -Recurse -Force
    }
    $skillZip = Join-Path $output "$SkillName-skill-v$Version.zip"
    $portableZip = Join-Path $output "$SkillName-v$Version.zip"
    foreach ($zip in @($skillZip, $portableZip)) {
        if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    }
    Compress-Archive -LiteralPath $skillStage -DestinationPath $skillZip -CompressionLevel Optimal
    Compress-Archive -LiteralPath $portable -DestinationPath $portableZip -CompressionLevel Optimal
    $checksums = Join-Path $output "SHA256SUMS-v$Version.txt"
    $hashRows = foreach ($zip in @($skillZip, $portableZip)) {
        '{0}  {1}' -f (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash.ToLowerInvariant(), (Split-Path -Leaf $zip)
    }
    $hashRows | Set-Content -Encoding ASCII -LiteralPath $checksums
    [ordered]@{
        ok = $true
        skillZip = $skillZip
        portableZip = $portableZip
        checksums = $checksums
    } | ConvertTo-Json -Depth 4
} finally {
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
}
