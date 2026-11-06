# Contributing

Thanks for improving the project.

1. Create a branch from `main`.
2. Keep changes limited to the requested behavior.
3. Do not include downloaded articles, WeChat cache files, credentials, cookies, or authenticated URLs.
4. Run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt -e .
$env:PYTHONPATH = (Resolve-Path .\skills\wechat-article-downloader\scripts)
.\.venv\Scripts\ruff.exe check .\skills\wechat-article-downloader\scripts\wechat_article_downloader .\tests .\tools
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe .\tools\validate_repo.py
```

Open a pull request with the behavior change and verification results.
