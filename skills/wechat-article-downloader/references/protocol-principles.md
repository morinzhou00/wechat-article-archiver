# Protocol Principles and Repair Routing

Load this reference only when history authorization, article parsing, or WeChat rules appear to have changed.

## Stable Model

The workflow has four isolated layers:

1. Public article HTML: parse metadata, body, and media.
2. Account identity: obtain public `__biz` from an article.
3. Credential-bound history provider: query and paginate the user's account history capability.
4. Local exporters: HTML, Markdown, PDF, DOCX, JSON, CSV, TXT, MHTML.

Do not put WeChat endpoint fields into the CLI or exporters. Keep them in `capture.py` and `provider.py`.

## Current History Shape

The user opens:

```text
https://mp.weixin.qq.com/mp/profile_ext?action=home&__biz=<biz>&scene=124#wechat_redirect
```

The local scanner looks for recent `mp.weixin.qq.com` URLs in Windows WeChat cache roots, restricted to the target `__biz`. A candidate generally contains either:

- `uin`, `key`, `pass_ticket`; or
- `appmsg_token`, `pass_ticket`.

Newer sessions can add `poc_sid`/`poc_token`. Discovery is not acceptance: the provider must validate the candidate and receive a parsable success response before storage.

Scanning is bounded by file size/count, directory count, total bytes, and elapsed time. A truncated scan or history pagination limit is inconclusive, not proof that no matching article exists.

History is normally requested from:

```text
mp/profile_ext?action=getmsg&__biz=...&f=json&offset=...&count=...
```

Parse `general_msg_list.list[]`, using `comm_msg_info.datetime` for the publication timestamp. The main article is `app_msg_ext_info`; sibling articles from the same send are in `multi_app_msg_item_list`. Follow `next_offset` while `can_msg_continue` is true.

## Failure Routing

- Public fetch fails: inspect URL validation, response status, verification pages, and article parser.
- Body missing: inspect `#js_content` / `.rich_media_content` and lazy-load attributes.
- PDF has title but blank body: inspect runtime hiding on the article root. Remove only `visibility:hidden` and `opacity:0`; preserve author layout.
- Scanner finds no candidates: inspect current WeChat cache roots, mtime window, URL encoding, and required field-name sets.
- Scanner finds candidates but all return `ret=-3`: they are stale or the POC handshake changed. Capture immediately after opening the generated home URL, then compare redacted field-name and Cookie-name sets.
- History succeeds but selection is empty: verify Shanghai timezone, page boundary, and exact inclusive date semantics.
- Export only fails: keep provider untouched and fix the local exporter.

## Evidence Rules

Collect only:

- HTTP status and WeChat `ret`/`errmsg`;
- request parameter names and Cookie names, never values;
- response top-level keys;
- DOM selector presence;
- WeChat/client version and timestamp.

Never write complete authenticated URLs, cookies, or local cache payloads into tests, logs, chat, or GitHub issues.

Add synthetic fixtures for every new shape before changing the provider/parser. Run fixture tests, a public live article smoke test, and a rendered PDF inspection.

Offline exports must not fetch arbitrary article-controlled URLs. Keep media on the HTTPS WeChat/Tencent allowlist, remove unresolved remote/lazy media attributes, and retain the restrictive HTML CSP.
