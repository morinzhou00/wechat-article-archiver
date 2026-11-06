@echo off
setlocal
set "ROOT=%~dp0"
set "SCRIPTS=%ROOT%skills\wechat-article-downloader\scripts"
set "RUNTIME=%SCRIPTS%\.runtime\Scripts"
if not defined WECHAT_DOWNLOADER_HOME set "WECHAT_DOWNLOADER_HOME=%LOCALAPPDATA%\WechatArticleDownloader"

if not exist "%RUNTIME%\python.exe" goto install
"%RUNTIME%\python.exe" -c "import tkinter, bs4, keyring, markdownify, psutil, docx, requests; import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto install
goto launch

:install
  echo First run: installing local dependencies...
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPTS%\bootstrap.ps1"
  if errorlevel 1 (
    echo Installation failed. Install Python 3.10+ or use the windows-x64 desktop ZIP.
    pause
    exit /b 4
  )

:launch
pushd "%SCRIPTS%"
start "" "%RUNTIME%\pythonw.exe" -m wechat_article_downloader.gui
popd
endlocal
