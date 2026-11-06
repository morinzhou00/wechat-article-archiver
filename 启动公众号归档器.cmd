@echo off
setlocal
set "ROOT=%~dp0"
set "SCRIPTS=%ROOT%skills\wechat-article-downloader\scripts"
set "RUNTIME=%SCRIPTS%\.runtime\Scripts"
set "WECHAT_DOWNLOADER_HOME=%USERPROFILE%\AppData\Local\WechatArticleDownloader"

if not exist "%RUNTIME%\pythonw.exe" (
  echo First run: installing local dependencies...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPTS%\bootstrap.ps1"
  if errorlevel 1 (
    echo Installation failed.
    pause
    exit /b 4
  )
)

pushd "%SCRIPTS%"
start "" "%RUNTIME%\pythonw.exe" -m wechat_article_downloader.gui
popd
endlocal
