[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptRoot = $PSScriptRoot
$runtimeDir = Join-Path $scriptRoot ".runtime"
$requirements = Join-Path $scriptRoot "requirements.txt"

if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    & py.exe -3 -m venv $runtimeDir
} elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
    & python.exe -m venv $runtimeDir
} else {
    throw "Python 3.10+ is required."
}
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create the Python runtime (exit code $LASTEXITCODE)."
}

$python = Join-Path $runtimeDir "Scripts\python.exe"
& $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10 or newer is required."
}
& $python -m pip install --disable-pip-version-check --requirement $requirements
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install Python dependencies (exit code $LASTEXITCODE)."
}
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = if ($previousPythonPath) { "$scriptRoot;$previousPythonPath" } else { $scriptRoot }
    & $python -m wechat_article_downloader.cli --json doctor
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime doctor failed (exit code $LASTEXITCODE)."
    }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
