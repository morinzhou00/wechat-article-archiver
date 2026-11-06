# 微信公众号文章下载原理与规则变化适配

## 结论

微信公众号文章下载并不是一个接口：

1. **单篇内容面**：公开文章 URL 返回 HTML，可解析标题、作者、公众号、发布时间、正文与媒体地址。
2. **账号发现面**：文章 HTML 或长链接中存在公开账号标识 `__biz`。
3. **历史索引面**：`mp/profile_ext?action=getmsg` 需要用户本人微信登录态，返回分页历史索引。
4. **导出面**：HTML/PDF/DOCX 等是本地转换，与微信历史协议无关。

最重要的架构决策，是让这四个面互相隔离。微信改变历史鉴权时，单篇下载和格式导出仍可用；微信改变正文 DOM 时，不需要改凭据捕获。

## 对 4.3 工具的可复现研究

研究对象：

- 用户提供路径：`微信公众号批量下载工具4.3`
- 外层 EXE SHA-256：`A6DF37C425386A22295EE3E33A466774AECF1308468502C02F530EA14D134D5D`
- 外层结构：x64 PE 包装器，RCDATA 以 `KAY` 标记开始，主体为 Zstandard 数据。
- 解包后主程序：Nuitka 打包的 Python 3.10/PySide6 应用。
- 内层主程序 SHA-256：`8A3515FDC3E4856B1737521B92733B9969C77A37B241A9DF132526C7ED9ABDA5`

仓库中的 `tools/research_upstream.py` 可以对用户自行提供的 EXE 重复执行 PE 资源清点和容器解包。仓库不包含研究对象、解包产物或上游资源。

可执行文件中的模块名、方法名、URL 模板和运行时字符串共同表明其工作流：

1. `get_biz` 从任意文章获取 `__biz`。
2. 构造：

   ```text
   https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=<biz>&scene=124#wechat_redirect
   ```

3. 提示用户复制到微信并打开。
4. `get_key` / `extract_uin_key_from_file` 扫描近期微信本地缓存文件，不是安装抓包证书。
5. 从缓存 URL 中提取 `uin`、`key`、`pass_ticket`，新规则下可能同时使用 `poc_sid`、`poc_token`。
6. `verify_key` / `verify_key_poc_token` 请求历史接口验证。
7. `getmsg` 响应中的 `general_msg_list` 包含 `app_msg_ext_info`，群发中的次条位于 `multi_app_msg_item_list`。
8. `comm_msg_info.datetime` 是发布时间；`next_offset` 与 `can_msg_continue` 控制分页。
9. 每条历史索引最终回到公开文章 URL 下载正文。
10. 4.3 的 PDF/DOCX 由附带转换程序完成，不属于微信协议。

## 本项目的实现映射

| 稳定职责 | 模块 | 变化时修改 |
|---|---|---|
| URL 校验、公开身份字段 | `utils.py`, `parser.py` | 新文章链接形式、变量名 |
| 正文 DOM 与运行时隐藏规则 | `parser.py` | `#js_content`、懒加载属性、隐藏样式 |
| 微信本地缓存候选发现 | `capture.py` | 新缓存根、编码、字段组合 |
| 历史鉴权与分页 | `provider.py` | endpoint、POC 握手、参数/响应字段 |
| 最新/日期选择 | `service.py` | 一般无需随微信变化 |
| HTML/MD/PDF/DOCX | `exporter.py` | 一般无需随微信变化 |
| CLI/Web/Skill | `cli.py`, `server.py`, `SKILL.md` | 一般无需随微信变化 |

## 凭据捕获为什么这样设计

### 不使用中间人代理

本项目不安装 CA、不解密 TLS、不修改系统代理。微信桌面端会把已访问 URL 或网络状态写入自己的缓存；只读扫描这些近期文件即可发现候选。

### 扫描边界

Windows 默认候选根：

- `%APPDATA%\Tencent\xwechat`
- `%APPDATA%\Tencent\WeChat`
- `%LOCALAPPDATA%\Temp`（仅当用户显式传入 `--include-temp`）

扫描器：

- 按 mtime 只看近期文件；
- 跳过 Video、FileStorage、Image、Avatar、Attachment 等大目录；
- 对单文件、文件总数、目录数、读取总字节和扫描时间设上限，并在触及预算时报告 `truncated`；
- 只接受 `mp.weixin.qq.com`；
- 只保留与目标 `__biz` 相同且字段组合可用的候选；
- 不向终端、日志或 Web 输出字段值。

### 发现不等于成功

缓存 mtime 新，不代表 token 未过期。因此 `auth capture` 会把候选交给 history provider 做只读验证。只有 `ret=0` 且响应可解析，才保存到 Windows Credential Manager。`ret=-3` 等被拒绝候选不会保存。

## 历史响应解析

当前 provider 请求的逻辑参数包括：

```text
action=getmsg
__biz=<target>
f=json
offset=<n>
count=<bounded>
scene=124
uin/key/pass_ticket 或 appmsg_token/pass_ticket
可选 poc_token
```

不要把这份字段表当成永久 API。真正稳定的是“用户在微信内打开账号主页后，客户端具有一组短期账号历史能力；provider 用这组能力换取分页索引”。

解析规则：

```text
general_msg_list
└─ list[]
   ├─ comm_msg_info.datetime
   └─ app_msg_ext_info
      ├─ 主文章
      └─ multi_app_msg_item_list[]  # 同次群发的其他文章
```

所有发布时间按 `Asia/Shanghai` 解释，再执行：

- `--latest N`：按时间降序取前 N 条；
- `--date YYYY-MM-DD`：起止日期相同；
- `--since/--until`：闭区间；
- 若最老一页已经早于起始日期，则停止分页。

## 正文解析中的真实故障案例

2026-07-28 用真实文章测试时，微信返回的正文根节点包含：

```html
<div id="js_content" style="visibility: hidden; opacity: 0">
```

浏览器中的微信脚本会把它显示出来，但离线导出没有运行该脚本，导致 PDF 只有标题、正文页空白。修复不是删除全部样式，而是只移除正文根节点上的 `visibility:hidden` 与 `opacity:0`。这样保留作者原有排版，又消除对微信运行时脚本的依赖。

## 微信规则变化时的排障顺序

1. **先分层定位**

   - 公开 URL 取不到：正文/反爬层。
   - 单篇成功、历史 `AUTH_REQUIRED`：捕获或 history provider。
   - 历史列表成功、某些文章失败：链接规范化或文章权限。
   - HTML 正常、PDF 异常：本地导出层。

2. **保存最小脱敏证据**

   - HTTP 状态、`ret`、`errmsg`；
   - 请求参数的字段名，不保存值；
   - 响应顶层 key；
   - DOM 选择器是否存在；
   - 微信版本、时间、系统。

3. **比较结构，不比较密钥**

   对比成功/失败请求的字段名集合、Cookie 名集合、请求次序和 Referer。不要把完整 URL 放入 Issue。

4. **只改 provider 或 parser**

   新建 provider 版本或特性探测，不在 CLI 中写条件分支。保留旧 fixture，添加新 fixture。

5. **回归**

   - 公开文章 fixture；
- 历史主条/次条 fixture；
- 日期边界；
- 分页/扫描预算耗尽时的“不完整”语义；
- 真实单篇 PDF 渲染；
   - `AUTH_REQUIRED` 指引不泄密；
   - Web API 不返回密钥。

## 安全与合规边界

- 只访问用户明确给出的公众号及其公开文章。
- 历史访问使用用户本人已登录微信产生的短期能力。
- 不绕过验证码、访问控制、付费墙或被删除内容。
- 不提供提高阅读量、点赞、评论等写操作。
- 媒体下载只允许微信/腾讯 HTTPS CDN 后缀，拒绝正文中任意第三方或本地网络 URL。
- 离线 HTML 使用 CSP 禁止远程回连；未下载的远程媒体及懒加载属性会从导出正文移除。
- 不包含上游 EXE、反编译源码或专有资产。
- 研究只服务于兼容性和独立实现。
