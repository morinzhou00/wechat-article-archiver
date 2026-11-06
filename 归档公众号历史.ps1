[CmdletBinding()]
param(
    [string]$ArticleUrl,
    [string]$Alias = "default",
    [string]$Since = "2000-01-01",
    [string]$Until,
    [string]$OutputDir = "$env:USERPROFILE\Downloads\WeChatArticles",
    [string]$MergeInto,
    [switch]$ReuseCredential,
    [switch]$IncludeTemp
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$cli = Join-Path $root "skills\wechat-article-downloader\scripts\wechat-download.ps1"
if (-not $env:WECHAT_DOWNLOADER_HOME) {
    $env:WECHAT_DOWNLOADER_HOME = Join-Path $env:USERPROFILE "AppData\Local\WechatArticleDownloader"
}

if (-not $ArticleUrl) {
    $ArticleUrl = Read-Host "请输入该公众号任意一篇公开文章链接"
}
if (-not $ArticleUrl) {
    throw "必须提供文章链接。"
}

$arguments = @(
    "history",
    $ArticleUrl.Trim(),
    "--credential", $Alias,
    "--since", $Since,
    "--max-pages", "200",
    "--formats", "html,md,json",
    "--assets",
    "--output", $OutputDir
)
if ($Until) {
    $arguments += @("--until", $Until)
}
if ($ReuseCredential) {
    $arguments += "--reuse-credential"
}
if ($IncludeTemp) {
    $arguments += "--include-temp"
}

& $cli @arguments
$exitCode = $LASTEXITCODE
if ($exitCode -eq 0 -and $MergeInto) {
    & $cli merge-archive $OutputDir $MergeInto
    $exitCode = $LASTEXITCODE
}
exit $exitCode
