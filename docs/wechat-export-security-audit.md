# “软件【退掉杀毒软件】”静态安全审计

- 审计时间：2026-10-25
- 审计范围：用户下载目录中的三套公众号下载程序、附带 DLL、配置和说明
- 审计方式：文件清单、SHA-256、数字签名、PE 导入/导出、资源与字符串静态检查
- 执行状态：未运行任何样本；未关闭或修改安全软件

## 结论

不建议安装或运行该软件包。包内说明要求关闭杀毒软件；主要可执行文件和 DLL 均无有效数字签名；批次工具请求管理员权限；其中的 `capture64.dll` 是 SunnyNet 网络代理/HTTPS 中间人组件，具有证书生成、系统代理、进程筛选、请求/响应正文和 Cookie 读取等导出能力。

这说明其“获取密钥”的工作流可以通过局域网/系统代理层截获微信网络通信，而不是仅解析公开文章 HTML。该实现超出了完成公众号文章归档所必需的最小权限，也提高了口令、登录态和聊天数据暴露风险。

## 主要文件

| 文件 | SHA-256 | 签名 | 观察 |
|---|---|---|---|
| 微信公众号批量下载工具3.9.exe | `ab7a91b2fddb2da7f6e29bf312b64f36cc131879fdd83c7e77c989767619abe2` | 无 | x64；Nuitka/PySide6；可静态解包；包含本地缓存提取与 HTTP 更新/服务地址 |
| 微信公众号文章批量下载3.2.zip 内主程序 | `730fc84d540004c59c38dc8e3baea99c160d88a9b2aaf4b5260d0ddc8bc8928a` | 无 | x64；清单要求 `requireAdministrator`；可静态解包；直接装载 `./capture64.dll` |
| capture64.dll | `f4b5678f279aad47b9710a6ff96c557ddc23103d96a388baa4ae54942f332f29` | 无 | x64；SunnyNet 网络代理组件 |
| WeChatArticleDownloader.exe | `81651bd92b411ea26b8f0b6379d288238669b7f9d0270e52fa66945fc36684ac` | 无 | .NET Framework 4.8.1；单篇下载器；不是批量历史工具 |

## `capture64.dll` 的敏感能力

静态导出的函数包含：

- `StartProcess`、`ProcessAddName`、`ProcessAddPid`
- `SetGlobalProxy`、`SetIeProxy`
- `SunnyNetInstallCert`、`CreateCA`、`CreateCertificate`
- `SetRequestHeader`、`SetRequestCookie`、`GetRequestALLCookie`
- `GetRequestBody`、`GetResponseBody`
- `SunnyNetStart`、`SunnyNetSetPort`

文件中也直接出现 `github.com/qtgolang/SunnyNet` 和 `github.com/Trisia/gosysproxy` 标识。SunnyNet 是网络抓包/代理框架，具备 TLS 解密能力；`gosysproxy` 用于设置系统代理。

静态解包 3.2 主程序后，还能直接看到 `./capture64.dll`、`LibSunny`、`SunnyNetInstallCert`、`SetGlobalProxy`、`getmsg`、`uin`、`key`、`pass_ticket` 等 Python 层符号。由此确认：3.2 批次工具不是只解析本地缓存，而是会安装证书、设置代理并调用 SunnyNet 截取微信历史鉴权数据。

3.9 可执行文件同样是 Nuitka 打包的 Python/PySide6 程序；其内层代码包含 `extract_uin_key_from_file`、`get_poc_token`、`verify_key_poc_token` 和历史分页逻辑。未从 3.9 内层代码中找到对 `capture64.dll` 的引用，因此不能断言它也执行同一套代理行为；但它仍包含明文 HTTP 服务地址 `http://47.243.175.212:5000/tool/wechat2/1` 和 `/tooluse/wechat2/1`，用途未在静态分析中确认，不能视为无网络的可信程序。

## 与“公众号历史归档”目标的最小实现对比

该包的做法：

```text
启动管理员权限程序
→ 启动 SunnyNet 代理与证书
→ 修改网络代理
→ 筛选并截获微信进程流量
→ 从请求中提取登录态
→ 调历史列表和下载正文
```

我们采用的本地安全边界：

```text
公开文章链接提取 __biz
→ 用户在本人微信内打开公众号主页
→ 仅扫描近期微信数据目录中的 mp.weixin.qq.com URL
→ 只接受目标 __biz
→ 调历史接口只读验证
→ 通过的凭据存 Windows Credential Manager
→ 分页拉取索引
→ 回到公开文章 URL 下载正文
```

我们的方案不会安装证书、修改系统代理、注入进程或扫描其他网站 Cookie。

## 残余风险

- 本机安全软件当前未启用，无法获得 Defender 对样本的检测结论。
- 静态分析不能证明样本的每一次运行行为；未观察到不等于不可能发生。
- 公众号历史接口没有稳定公开契约，凭据会过期，需维护适配层。
- 付费内容仍受账号访问权限和版权限制。
