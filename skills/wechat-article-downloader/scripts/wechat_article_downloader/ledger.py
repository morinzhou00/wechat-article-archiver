from __future__ import annotations


PARITY_LEDGER: list[dict[str, str]] = [
    {"command": "article", "parameter": "url", "web": "control", "notes": "Article download form"},
    {"command": "article", "parameter": "--formats", "web": "control", "notes": "Format checkboxes"},
    {"command": "article", "parameter": "--output", "web": "control", "notes": "Optional output path"},
    {"command": "article", "parameter": "--assets/--no-assets", "web": "control", "notes": "Asset toggle"},
    {"command": "article", "parameter": "--json", "web": "read", "notes": "Web APIs are always JSON"},
    {"command": "account", "parameter": "sample_url", "web": "control", "notes": "Account download form"},
    {"command": "account", "parameter": "--credential", "web": "control", "notes": "Alias only; secrets never enter Web"},
    {"command": "account", "parameter": "--latest", "web": "control", "notes": "Latest article count"},
    {"command": "account", "parameter": "--date", "web": "control", "notes": "Exact publication date"},
    {"command": "account", "parameter": "--since", "web": "control", "notes": "Inclusive start date"},
    {"command": "account", "parameter": "--until", "web": "control", "notes": "Inclusive end date"},
    {"command": "account", "parameter": "--max-pages", "web": "control", "notes": "Bounded history scan"},
    {"command": "account", "parameter": "--formats", "web": "control", "notes": "Format checkboxes"},
    {"command": "account", "parameter": "--output", "web": "control", "notes": "Optional output path"},
    {"command": "account", "parameter": "--assets/--no-assets", "web": "control", "notes": "Asset toggle"},
    {"command": "account", "parameter": "--json", "web": "read", "notes": "Web APIs are always JSON"},
    {"command": "auth guide", "parameter": "sample_url", "web": "read", "notes": "Guidance shown; no secret input"},
    {"command": "auth capture", "parameter": "sample_url", "web": "unsupported", "notes": "Terminal-only local cache scanner"},
    {"command": "auth capture", "parameter": "--alias", "web": "unsupported", "notes": "Secret is saved to Windows Credential Manager"},
    {"command": "auth capture", "parameter": "--watch-seconds", "web": "unsupported", "notes": "Bounded terminal-only watch"},
    {"command": "auth capture", "parameter": "--include-temp", "web": "unsupported", "notes": "Explicit opt-in to broader recent Temp scan"},
    {"command": "auth import", "parameter": "alias", "web": "unsupported", "notes": "Terminal-only hidden prompts protect secrets"},
    {"command": "auth status", "parameter": "alias", "web": "read", "notes": "Aliases and field names only"},
    {"command": "auth delete", "parameter": "alias", "web": "destructive", "notes": "Terminal-only credential deletion"},
    {"command": "auth delete", "parameter": "--yes", "web": "destructive", "notes": "Explicit terminal confirmation"},
    {"command": "config show", "parameter": "--json", "web": "read", "notes": "Configuration panel"},
    {"command": "config set", "parameter": "--output-dir", "web": "control", "notes": "Validated hot setting"},
    {"command": "config set", "parameter": "--request-interval", "web": "control", "notes": "Validated hot setting"},
    {"command": "config set", "parameter": "--timeout", "web": "control", "notes": "Validated hot setting"},
    {"command": "config set", "parameter": "--max-pages", "web": "control", "notes": "Validated hot setting"},
    {"command": "config set", "parameter": "--formats", "web": "control", "notes": "Validated hot setting"},
    {"command": "doctor", "parameter": "--json", "web": "read", "notes": "Overview and status panels"},
    {"command": "status", "parameter": "--json", "web": "read", "notes": "Lightweight status endpoint"},
    {"command": "web", "parameter": "--host", "web": "restart", "notes": "Loopback-only and fixed at startup"},
    {"command": "web", "parameter": "--port", "web": "restart", "notes": "Fixed at startup"},
    {"command": "web", "parameter": "--open", "web": "lifecycle", "notes": "Launch behavior only"},
]


def parity_summary() -> dict[str, object]:
    counts: dict[str, int] = {}
    for item in PARITY_LEDGER:
        counts[item["web"]] = counts.get(item["web"], 0) + 1
    return {"count": len(PARITY_LEDGER), "dispositions": counts, "items": PARITY_LEDGER}
