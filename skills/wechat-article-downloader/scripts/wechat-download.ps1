[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CliArgs
)

$ErrorActionPreference = "Stop"
$scriptRoot = $PSScriptRoot
$runtimePython = Join-Path $scriptRoot ".runtime\Scripts\python.exe"
$configuredPython = $env:WECHAT_DOWNLOADER_PYTHON
$normalizedArgs = @()
for ($index = 0; $index -lt $CliArgs.Count; $index++) {
    $argument = $CliArgs[$index]
    if ($index -gt 0 -and $CliArgs[$index - 1] -eq "--formats" -and $argument -match "\s") {
        $argument = (($argument -split "\s+") -join ",")
    }
    $normalizedArgs += $argument
}

if ($configuredPython) {
    $pythonCommand = Get-Command $configuredPython -ErrorAction SilentlyContinue
    if (-not $pythonCommand -or -not (Test-Path -LiteralPath $pythonCommand.Source -PathType Leaf)) {
        throw "WECHAT_DOWNLOADER_PYTHON does not point to a Python executable."
    }
    $python = $pythonCommand.Source
} elseif (Test-Path -LiteralPath $runtimePython) {
    $python = $runtimePython
} elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
    $python = "py.exe"
    $prefix = @("-3")
} elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
    $python = "python.exe"
} else {
    throw "Python 3.10+ was not found. Run scripts\bootstrap.ps1 after installing Python."
}

$previousPythonPath = $env:PYTHONPATH
$previousPythonIoEncoding = $env:PYTHONIOENCODING
$previousConsoleEncoding = [Console]::OutputEncoding
$previousOutputEncoding = $OutputEncoding
try {
    $utf8Encoding = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $utf8Encoding
    $OutputEncoding = $utf8Encoding
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONPATH = if ($previousPythonPath) { "$scriptRoot;$previousPythonPath" } else { $scriptRoot }
    $previousErrorPreference = $ErrorActionPreference
    $hasNativePreference = $null -ne (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue)
    if ($hasNativePreference) { $previousNativePreference = $PSNativeCommandUseErrorActionPreference }
    try {
        $ErrorActionPreference = "Continue"
        if ($hasNativePreference) { $PSNativeCommandUseErrorActionPreference = $false }
        & $python @prefix -c "import bs4, keyring, markdownify, psutil, docx, requests" *> $null
        $dependencyExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorPreference
        if ($hasNativePreference) { $PSNativeCommandUseErrorActionPreference = $previousNativePreference }
    }
    if ($dependencyExitCode -ne 0) {
        $bootstrap = Join-Path $scriptRoot "bootstrap.ps1"
        if ($normalizedArgs -contains "--json") {
            [ordered]@{
                ok = $false
                error = "DEPENDENCY_MISSING"
                message = "Python dependencies are missing."
                details = @{ action = "Run: $bootstrap" }
            } | ConvertTo-Json -Depth 4
        } else {
            Write-Output "[DEPENDENCY_MISSING] Python dependencies are missing. Run: $bootstrap"
        }
        $global:LASTEXITCODE = 4
        [Environment]::ExitCode = 4
        return
    }
    & $python @prefix -m wechat_article_downloader.cli @normalizedArgs
    $commandExitCode = $LASTEXITCODE
    $global:LASTEXITCODE = $commandExitCode
    [Environment]::ExitCode = $commandExitCode
    return
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:PYTHONIOENCODING = $previousPythonIoEncoding
    [Console]::OutputEncoding = $previousConsoleEncoding
    $OutputEncoding = $previousOutputEncoding
}
