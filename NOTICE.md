# Attribution and provenance

This repository is a modified fork of:

- Project: `tingaidehua/wechat-article-downloader-skill`
- Source commit imported for development: `d97c255419e9a6de1c32bb5a9cf0f747630499bd`
- Upstream license: MIT (`LICENSE`)

This fork additionally includes:

- derive `__biz` from a full article URL before any network request;
- support authenticated article requests using the same short-lived local
  WeChat fields accepted for history pagination;
- add an end-to-end `history` command;
- scan the standard older/newer WeChat data directories without requiring a
  proxy or certificate installation;
- update the audited `requests` dependency to `2.33.0`;
- add a Chinese setup guide and a local security audit of the untrusted
  “退掉杀毒软件” package.

The original project and its license notice remain applicable.
