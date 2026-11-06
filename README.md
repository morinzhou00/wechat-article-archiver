# 微信公众号文章归档器

输入任意一篇公众号文章链接，即可归档该账号在指定日期范围内的历史文章。
项目提供命令行、桌面窗口、断点续抓、多格式导出和本地图片归档。

面向 Codex/Agent Skills 的微信公众号文章下载工具。给它一篇公开文章链接，即可下载单篇文章，或在用户本人已登录的微信桌面端授权下，按“最新 N 篇、某一天、日期区间”筛选公众号历史文章，并导出 HTML、Markdown、PDF、DOCX、JSON、CSV、TXT、MHTML。

项目地址：<https://github.com/morinzhou00/wechat-article-archiver>

## 分享给同事

对方可以直接从 [Releases](https://github.com/morinzhou00/wechat-article-archiver/releases)
下载 **`wechat-article-archiver-windows-x64-v0.3.2.zip`**，完整解压后双击 **`WechatArchiver.exe`**。
该包自带运行环境，Windows 10/11 64 位电脑无需安装 Python、Git 或 Codex，也不需要管理员权限。
必须保留 EXE 旁边的 `_internal` 文件夹；不要在压缩包里直接运行，不要只转发 EXE。

1. 登录 Windows 桌面微信，复制目标公众号任意一篇公开文章的链接。
2. 启动程序，粘贴链接、选择日期和下载目录，点击“一键开始 / 继续归档”。
3. 首次使用或登录态过期时，将程序复制的主页链接发给微信“文件传输助手”，在微信内打开。
4. 等待下载；默认保存 HTML、Markdown、JSON 和图片。中断后用相同条件再次运行即可继续。

**打开普通文章本身不一定足够**，请按程序提示打开生成的公众号主页。
历史获取依赖微信版本及其本地缓存，无法保证所有微信版本均兼容；未取得授权时不会显示下载成功。
Windows 桌面包是未签名程序，企业电脑可能需要 IT 审核；不要关闭杀毒软件。

另两个 `wechat-article-downloader-*.zip` 是源码/Skill 包，需要 Python 3.10+。
使用 Codex 的同事也可以安装 Skill：

```powershell
gh skill install morinzhou00/wechat-article-archiver wechat-article-downloader --agent codex --scope user
```

```text
下载 https://mp.weixin.qq.com/s/Jc15wgR7FxDh6tb_StPEBQ 所在公众号最新 3 篇文章，
保存 PDF 和 Markdown，然后分析文章主题。
```

## 特点

- 不是 GUI 自动点击封装：协议发现、文章解析、历史 provider、筛选和导出均为可测试的纯 CLI 模块。
- 单篇公开文章无需密钥。
- 历史文章凭据只在本机捕获、验证，并保存到 Windows Credential Manager；不会要求用户把密钥粘贴到聊天中。
- 历史列表 provider 与正文下载解耦。微信字段或接口变化时，可单独替换 provider。
- PDF 使用已安装的 Edge/Chrome 无头打印；DOCX 使用 `python-docx`，不依赖来源不明的转换程序。
- 完整 localhost Web 控制台：状态、资源、数据源、处理管线、任务历史、安全边界和 CLI/Web 参数覆盖一页可见。
- 仅访问 `https://mp.weixin.qq.com` 及文章引用的微信/腾讯 CDN 白名单域；没有更新服务器、遥测或远程后备服务。

## 安装

前置条件：

- 桌面 EXE 包：Windows 10/11 x64；源码/Skill 包：另需 Python 3.10+（含 tkinter）；
- 下载公众号历史时，需要已登录的微信桌面客户端；
- PDF 需要 Microsoft Edge、Google Chrome 或 Chromium（Windows 通常已带 Edge）；
- 单篇公开文章下载不要求微信登录。

作为 Agent Skill 安装：

```powershell
gh skill install morinzhou00/wechat-article-archiver wechat-article-downloader --agent codex --scope user
```

也可克隆后初始化独立运行环境：

```powershell
git clone https://github.com/morinzhou00/wechat-article-archiver.git
cd wechat-article-archiver
.\skills\wechat-article-downloader\scripts\bootstrap.ps1
```

如已安装到 Codex，重新打开任务或刷新 Skills 后，使用 `$wechat-article-downloader`。

### 便携 ZIP

GitHub Release 同时提供免安装桌面包、纯 Skill 包和源码便携包。以下命令针对源码便携包。下载 ZIP 与 `SHA256SUMS-vX.Y.Z.txt` 后先验证：

```powershell
Get-FileHash .\wechat-article-downloader-v0.3.2.zip -Algorithm SHA256
```

确认与校验和文件一致，再解压并运行。便携安装器始终复制文件，不会创建指向解压目录的 junction：

```powershell
Expand-Archive .\wechat-article-downloader-v0.3.2.zip -DestinationPath .\wechat-portable
.\wechat-portable\wechat-article-downloader-v0.3.2\启动公众号归档器.cmd
```

更新 GitHub Skill：

```powershell
gh skill update wechat-article-downloader
```

默认输出目录是 `%USERPROFILE%\Downloads\WeChatArticles`，配置、脱敏历史记录保存在 `%LOCALAPPDATA%\WechatArticleDownloader`，密钥值保存在 Windows Credential Manager。可用 `config set --output-dir <目录>` 修改下载目录；需要隔离本地配置/历史时，可在启动前设置 `WECHAT_DOWNLOADER_HOME`。自动化环境也可用 `WECHAT_DOWNLOADER_PYTHON` 指向一个已安装依赖的 Python 可执行文件。

卸载前如需清除密钥，先在 Skill 仍可用时运行 `auth status`，再逐个执行 `auth delete <alias> --yes`。随后删除 Agent 的 `wechat-article-downloader` Skill 目录即可；本地配置/下载文件默认保留。只有用户明确希望清除本地状态时，才删除上述 data/output 目录。

## CLI 快速开始

以下示例中的 `$cli` 是 Skill 内脚本：

```powershell
$cli = ".\skills\wechat-article-downloader\scripts\wechat-download.ps1"

# 单篇文章，无需凭据
& $cli article "https://mp.weixin.qq.com/s/Jc15wgR7FxDh6tb_StPEBQ" `
  --formats "html,md,pdf"

# 先生成授权指引
& $cli auth guide "https://mp.weixin.qq.com/s/Jc15wgR7FxDh6tb_StPEBQ"

# 本机捕获：运行后按提示，把生成的公众号主页链接在微信内打开一次
& $cli auth capture "https://mp.weixin.qq.com/s/Jc15wgR7FxDh6tb_StPEBQ" `
  --alias default --watch-seconds 120

# 最新 3 篇
& $cli account "https://mp.weixin.qq.com/s/Jc15wgR7FxDh6tb_StPEBQ" `
  --latest 3 --formats "md,pdf"

# 精确日期或日期区间
& $cli account "https://mp.weixin.qq.com/s/Jc15wgR7FxDh6tb_StPEBQ" `
  --date 2026-07-16 --formats "html,pdf"
& $cli account "https://mp.weixin.qq.com/s/Jc15wgR7FxDh6tb_StPEBQ" `
  --since 2026-07-01 --until 2026-07-31 --formats "md,pdf"
```

机器调用将 `--json` 放在子命令前：

```powershell
& $cli --json doctor
& $cli --json article "https://mp.weixin.qq.com/s/..." --formats "md,json"
```

稳定错误码包括 `INVALID_INPUT`、`AUTH_REQUIRED`、`REMOTE_ERROR`、`EXPORT_ERROR` 和 `DEPENDENCY_MISSING`。进程退出码 `7` 表示批量结果不完整（例如历史分页达到上限或个别文章失败），调用方不得把它当作完整成功。

## 凭据与隐私

公众号历史接口是微信登录态能力。工具会：

1. 从示例文章提取公开的 `__biz`；
2. 生成 `profile_ext?action=home` 主页链接；
3. 用户在本人已登录的微信中打开一次；
4. CLI 只扫描近期本地微信缓存里的 `mp.weixin.qq.com` 请求 URL；
5. 对候选逐个调用只读历史接口验证；
6. 仅把服务器接受的字段保存到 Windows Credential Manager。

控制台、日志、manifest 和 Web API 只显示别名与字段名，不显示值。请勿把 `key`、`pass_ticket`、Cookie 或完整认证 URL 发到聊天、Issue 或日志。凭据通常会过期，出现 `AUTH_REQUIRED` 时重新运行 `auth capture`。

默认扫描仅限微信自己的 `%APPDATA%\Tencent\xwechat` / `WeChat` 目录。若新版微信只把请求写入临时目录，可由用户明确选择 `auth capture ... --include-temp`；该选项会额外查看近期 `%LOCALAPPDATA%\Temp` 文件，因此不应默认开启。

## Web 控制台

```powershell
& $cli web --open
```

控制台只允许绑定 `127.0.0.1` 或 `::1`。修改请求必须使用 JSON、同源检查和会话头；凭据导入/删除故意不在 Web 中提供。

## 原理与适配

完整研究记录见 [docs/protocol-principles.md](docs/protocol-principles.md)。核心稳定层次是：

```text
公开文章 URL
  ├─ 公开 HTML → 元数据/正文解析 → 资源下载 → 多格式导出
  └─ __biz → 微信内打开 profile_ext 主页
                  ↓
        本地缓存发现候选登录态
                  ↓
         历史 provider 验证与分页
                  ↓
        最新 N 篇 / 日期范围筛选
                  ↓
        回到公开 HTML 下载与导出
```

微信改规则时，先保存脱敏失败响应和成功请求的“字段名集合”，再修改 `capture.py` 或 `provider.py`；不要把接口参数散落到 CLI、Skill 提示或导出器中。

## 上游参考与声明

本项目参考 [qiye45/wechatDownload](https://github.com/qiye45/wechatDownload) 的产品流程进行二次开发。

截至本项目开发时，上游仓库未提供应用源码与明确的开源许可证。因此本仓库采用独立重写/兼容层方式实现：不复制、不分发上游闭源 EXE、解包文件或专有资源，也不代表获得上游授权、与上游存在隶属关系或得到其背书。研究工具仅用于对用户本人提供的可执行文件进行互操作性分析。

## 开发与验证（仅源码仓库）

便携 ZIP 不包含测试和研究工具；以下命令应在源码仓库中运行。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\skills\wechat-article-downloader\scripts\requirements.txt
.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
$env:PYTHONPATH = (Resolve-Path .\skills\wechat-article-downloader\scripts)
.\.venv\Scripts\ruff.exe check .\skills\wechat-article-downloader\scripts\wechat_article_downloader .\tests .\tools
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools\validate_repo.py
```

真实网络测试是显式选择，不会在普通测试中运行：

```powershell
.\.venv\Scripts\python.exe tools\live_smoke.py `
  "https://mp.weixin.qq.com/s/Jc15wgR7FxDh6tb_StPEBQ"
```

## 许可证

本仓库独立编写的代码采用 [MIT License](LICENSE)。微信、WeChat 及相关商标归其权利人所有。使用者应只下载其有权访问和保存的内容，并遵守平台规则、版权与适用法律。
