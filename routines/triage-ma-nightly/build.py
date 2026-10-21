"""Render the nightly MA triage report page from a run's findings JSON.

Usage: python3 build.py <findings.json> <out.html>
"""
import json
import sys
from html import escape

SEVERITIES = ["critical", "high", "medium", "low"]

CSS = """
:root { color-scheme: light dark; }
body { font-family: var(--font-sans); color: var(--foreground); margin: 0; }
.wrap { display: flex; flex-direction: column; gap: 14px; padding: 4px 0 8px; }
.title { font-size: 15px; font-weight: 600; }
.title .sub { color: var(--muted-foreground); font-weight: 400; font-size: 13px; display: block; margin-top: 2px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px; }
.tile { border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px; border-left-width: 3px; }
.tile.good { border-left-color: var(--success); }
.tile.warn { border-left-color: var(--warning); }
.tile.bad { border-left-color: var(--destructive); }
.tile .k { font-size: 11px; color: var(--muted-foreground); text-transform: uppercase; letter-spacing: .04em; }
.tile .v { font-size: 18px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }
.tile .s { font-size: 11px; color: var(--muted-foreground); margin-top: 2px; }
.verdict { font-size: 14px; line-height: 1.5; }
.sev { display: flex; flex-direction: column; gap: 6px; }
.sev h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .05em; margin: 4px 0 0; color: var(--muted-foreground); display: flex; align-items: center; gap: 6px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.critical, .dot.high { background: var(--destructive); }
.dot.medium { background: var(--warning); }
.dot.low { background: var(--muted-foreground); }
details { border: 1px solid var(--border); border-radius: var(--radius); }
summary { cursor: pointer; padding: 8px 12px; display: flex; gap: 8px; align-items: baseline; font-size: 13px; list-style: none; }
summary::-webkit-details-marker { display: none; }
summary::before { content: "\\25B8"; color: var(--muted-foreground); font-size: 10px; }
details[open] summary::before { content: "\\25BE"; }
.fid { font-family: var(--font-mono); color: var(--muted-foreground); font-size: 12px; }
.ftitle { flex: 1; }
.count { font-family: var(--font-mono); font-size: 12px; color: var(--muted-foreground); white-space: nowrap; }
.badge { font-size: 10px; font-weight: 600; text-transform: uppercase; padding: 1px 6px; border-radius: 999px; background: var(--accent-surface, var(--accent)); color: var(--accent-surface-foreground, var(--accent-foreground)); }
.body { padding: 0 12px 12px 30px; font-size: 13px; line-height: 1.5; display: flex; flex-direction: column; gap: 8px; }
.meta { color: var(--muted-foreground); font-size: 12px; }
.meta code, .read code { font-family: var(--font-mono); font-size: 12px; }
pre { font-family: var(--font-mono); font-size: 11px; line-height: 1.45; background: var(--code-background, var(--muted)); color: var(--code-foreground, var(--foreground)); border-radius: var(--radius); padding: 10px; margin: 0; overflow-x: auto; white-space: pre; }
.footer { font-size: 12px; color: var(--muted-foreground); border-top: 1px solid var(--border); padding-top: 10px; }
.footer code { font-family: var(--font-mono); }
.empty { font-size: 13px; color: var(--muted-foreground); }
"""


def main() -> None:
    src, out = sys.argv[1], sys.argv[2]
    with open(src) as f:
        run = json.load(f)
    parts = [
        f'<div class="title">MA nightly log triage &middot; {escape(run["window"])}'
        f'<span class="sub">{escape(run["version"])} &middot; {escape(run["sources"])}</span></div>',
        '<div class="tiles">' + "".join(_tile(t) for t in run["tiles"]) + "</div>",
        f'<div class="verdict">{run["verdict"]}</div>',
    ]
    findings = [f for f in run["findings"] if not f.get("muted")]
    if not findings:
        parts.append('<div class="empty">Nothing to report.</div>')
    for sev in SEVERITIES:
        group = [f for f in findings if f["severity"] == sev]
        if group:
            parts.append(
                f'<div class="sev"><h3><span class="dot {sev}"></span>{sev} ({len(group)})</h3>'
                + "".join(_finding(f) for f in group)
                + "</div>"
            )
    parts.append(
        '<div class="footer">Reply <code>fix &lt;id&gt;</code> to start a fix session, '
        "<code>mute &lt;id&gt;</code> to stop reporting it.</div>"
    )
    html = (
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        + CSS
        + '</style></head><body><div class="wrap">'
        + "".join(parts)
        + "</div></body></html>"
    )
    with open(out, "w") as f:
        f.write(html)


def _tile(t: dict) -> str:
    """Render one health tile."""
    return (
        f'<div class="tile {escape(t["state"])}"><div class="k">{escape(t["label"])}</div>'
        f'<div class="v">{escape(t["value"])}</div><div class="s">{escape(t.get("sub", ""))}</div></div>'
    )


def _finding(f: dict) -> str:
    """Render one finding as a details block."""
    badge = '<span class="badge">new</span>' if f.get("new") else ""
    meta = (
        f'<div class="meta">{escape(f["where"])} &middot; first {escape(f["first"])} &middot; '
        f'last {escape(f["last"])} &middot; known since {escape(f.get("known_since", "today"))}</div>'
    )
    excerpt = f"<pre>{escape(f['excerpt'])}</pre>" if f.get("excerpt") else ""
    return (
        f'<details><summary><span class="fid">{escape(f["id"])}</span>'
        f'<span class="ftitle">{escape(f["title"])}</span>{badge}'
        f'<span class="count">&times;{f["count"]}</span></summary>'
        f'<div class="body">{meta}{excerpt}<div class="read">{f["read"]}</div></div></details>'
    )


if __name__ == "__main__":
    main()
