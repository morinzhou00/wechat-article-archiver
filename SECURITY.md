# Security

Do not report credentials in a public issue. Never include a complete authenticated
`mp.weixin.qq.com/mp/profile_ext` URL, Cookie header, `key`, `pass_ticket`,
`appmsg_token`, `poc_token`, or credential-store export.

For a suspected vulnerability, open a GitHub security advisory for this repository.
Include the affected version, minimal reproduction, and redacted field names only.

The tool intentionally:

- binds its Web console to loopback only;
- stores secrets in Windows Credential Manager;
- excludes secret values from logs, manifests, status, and Web APIs;
- performs read-only article and history requests;
- does not install a TLS certificate or change system proxy settings;
- does not use upstream update/telemetry servers.
- restricts media downloads to HTTPS WeChat/Tencent CDN suffixes instead of following arbitrary article URLs.

Resume checkpoints contain only public article metadata, pagination offsets, and
article/directory identities. They never store `key`, `pass_ticket`,
`appmsg_token`, `poc_token`, `poc_sid`, or Cookie values.

Archive merging is non-destructive: it adds missing articles, verifies matching
article identities before accepting equal content, and reports conflicts instead
of overwriting existing files. A `--dry-run` mode performs no writes.
