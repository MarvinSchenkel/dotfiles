"""Render the pr-review report from the routine's state file.

Usage: python3 build.py <state.json> [--full <out.html>] [--digest <out.html>]

--full writes the complete report for a browser, --digest the compact page for html_render.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from html import escape

FULL_LIMIT = 2_000_000
DIGEST_LIMIT = 40_000
FULL_REPORT = "~/.claude-teamB/routine-reports/pr-review.html"
WEEK = timedelta(days=7)
COLS = [
    ("ready", "Ready to merge", "success"),
    ("almost", "Almost ready", "warning"),
    ("not_ready", "Not ready yet", "destructive"),
    ("auto", "Auto-approved", "info"),
]
ROWS = [
    ("attention", "Needs my attention", "Your call: merge, decide or post"),
    ("waiting", "Waiting for user", "Author or reporter has to act"),
]
TZ_NAMES = {"CEST": 2, "CET": 1, "UTC": 0}

THEME = """
:root { --foreground: #18201d; --muted-foreground: #5b6863; --border: #d9e0dc; --card: #ffffff; --card-foreground: #18201d;
  --background: #f4f6f5; --accent: #eaefec; --destructive: #b03c2a; --warning: #a66a12; --success: #23784a; --info: #2c5e8c;
  --radius: 6px; --font-sans: system-ui, -apple-system, "Segoe UI", sans-serif; --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace; }
@media (prefers-color-scheme: dark) { :root { --foreground: #e4eae7; --muted-foreground: #95a39d; --border: #2c3632; --card: #1a211e;
  --card-foreground: #e4eae7; --background: #121715; --accent: #222b27; --destructive: #ec7e6b; --warning: #e2a64a; --success: #5cc48a; --info: #7fb0de; } }
"""

PAGE = """
body { background: var(--background); padding: 24px 16px 48px; }
.wrap { max-width: 1240px; margin: 0 auto; }
"""

DIGEST_CSS = """
:root { color-scheme: light dark; }
body { font: 13px/1.45 var(--font-sans); color: var(--foreground); margin: 0; }
a { color: var(--info); text-decoration: none; }
code { font: 11.5px var(--font-mono); }
.w { display: flex; flex-direction: column; gap: 10px; padding: 2px 0 8px; }
h1 { font-size: 15px; font-weight: 600; margin: 0; }
.sub, .ft, .muted { color: var(--muted-foreground); }
.sub { font-size: 12px; }
.note { margin: 0; max-width: 95ch; }
.tl { display: flex; flex-wrap: wrap; gap: 6px; font-size: 12px; }
.tl span { padding: 2px 8px; border-radius: var(--radius); color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent); }
.sc { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; }
td, th { padding: 3px 6px; text-align: left; vertical-align: baseline; border-bottom: 1px solid var(--border); white-space: nowrap; }
th { font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--muted-foreground); }
td.t { white-space: normal; width: 100%; min-width: 220px; }
td.s { white-space: normal; }
td.s b { display: inline-block; margin: 1px 0; white-space: nowrap; }
tr.g th { padding-top: 10px; color: var(--foreground); text-transform: none; letter-spacing: 0; font-size: 12px; border-bottom-color: var(--c); }
tr.l td { background: color-mix(in srgb, var(--destructive) 13%, transparent); }
tr.l td:first-child { box-shadow: inset 3px 0 var(--destructive); }
td.n { font-family: var(--font-mono); font-size: 12px; }
b { font: 600 10px var(--font-mono); padding: 0 5px; border-radius: 3px; text-transform: uppercase; color: var(--c, var(--muted-foreground)); background: color-mix(in srgb, var(--c, var(--muted-foreground)) 14%, transparent); }
.r { --c: var(--success); } .a { --c: var(--warning); } .x { --c: var(--destructive); } .i { --c: var(--info); }
.ok { color: var(--success); } .wn { color: var(--warning); } .bd { color: var(--destructive); }
ul { margin: 0; padding-left: 18px; }
.ft { font-size: 12px; border-top: 1px solid var(--border); padding-top: 8px; }
"""

VERDICT_SHORT = {"ready": ("ready", "r"), "almost": ("almost", "a"), "not_ready": ("not ready", "x")}

CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font: 14px/1.5 var(--font-sans); color: var(--foreground); margin: 0; }
a { color: var(--info); }
code { font: 12px var(--font-mono); background: color-mix(in srgb, var(--muted-foreground) 12%, transparent); padding: 0 4px; border-radius: 3px; overflow-wrap: anywhere; }
pre { font: 11.5px/1.45 var(--font-mono); background: color-mix(in srgb, var(--muted-foreground) 10%, transparent); border-radius: var(--radius); padding: 10px; margin: 4px 0 0; overflow-x: auto; white-space: pre; }
pre code { background: none; padding: 0; }
.wrap { display: flex; flex-direction: column; gap: 16px; padding: 4px 0 12px; }
header { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: end; gap: 10px; }
h1 { font-size: 17px; font-weight: 600; margin: 0; }
.sub { color: var(--muted-foreground); font-size: 13px; margin: 2px 0 0; }
.note { font-size: 13px; margin: 0; max-width: 90ch; }
.tallies { display: flex; flex-wrap: wrap; gap: 6px; }
.tally { padding: 4px 10px; border-radius: var(--radius); font-size: 12px; color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent); font-variant-numeric: tabular-nums; }
.tally b { font-size: 16px; margin-right: 4px; }
.controls { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; font-size: 12.5px; color: var(--muted-foreground); }
.controls input[type=search] { flex: 1 1 260px; min-width: 0; padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius); background: transparent; color: var(--foreground); font: inherit; font-size: 13px; }
.controls label { display: flex; gap: 6px; align-items: center; cursor: pointer; }
.legend { margin-left: auto; }
.scroll { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius); }
table.matrix { border-collapse: collapse; width: 100%; min-width: 760px; table-layout: fixed; }
.matrix th, .matrix td { border-bottom: 1px solid var(--border); vertical-align: top; text-align: left; }
.matrix tr:last-child td, .matrix tr:last-child th { border-bottom: 0; }
.matrix thead th { padding: 8px 10px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: var(--muted-foreground); }
.matrix th.status { width: 120px; padding: 10px; border-right: 1px solid var(--border); }
.status b { display: block; font-size: 14px; color: var(--foreground); text-transform: none; letter-spacing: 0; }
.status span { font-size: 11px; font-weight: 400; color: var(--muted-foreground); text-transform: none; letter-spacing: 0; }
.matrix td { padding: 8px; border-left: 1px solid var(--border); }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; background: var(--c); }
.cell { display: flex; flex-direction: column; gap: 6px; }
.empty { color: var(--muted-foreground); font: 12px var(--font-mono); opacity: .6; }
.chip { display: grid; grid-template-columns: auto 1fr; column-gap: 8px; row-gap: 2px; padding: 6px 8px; border: 1px solid var(--border); border-left: 3px solid var(--c); border-radius: var(--radius); background: var(--card); color: var(--card-foreground); text-decoration: none; }
.chip:hover { background: color-mix(in srgb, var(--c) 8%, var(--card)); }
.chip .n { font: 500 12px var(--font-mono); color: var(--muted-foreground); }
.chip .t { font-size: 13px; line-height: 1.35; overflow-wrap: anywhere; }
.chip .m { grid-column: 2; display: flex; flex-wrap: wrap; gap: 3px 6px; font-size: 11px; color: var(--muted-foreground); }
.chip.late { border-color: var(--destructive); background: color-mix(in srgb, var(--destructive) 12%, var(--card)); }
.chip[data-d="1"] { opacity: .45; }
.chip[data-d="1"]:hover { opacity: .85; }
.c-ready { --c: var(--success); } .c-almost { --c: var(--warning); } .c-not_ready { --c: var(--destructive); } .c-auto { --c: var(--info); }
.tag { font: 500 10px var(--font-mono); padding: 0 5px; border-radius: 3px; text-transform: uppercase; letter-spacing: .03em; color: var(--tc, var(--muted-foreground)); background: color-mix(in srgb, var(--tc, var(--muted-foreground)) 14%, transparent); white-space: nowrap; }
.tag.size { --tc: var(--foreground); }
.tag.ok { --tc: var(--success); } .tag.warn { --tc: var(--warning); } .tag.bad { --tc: var(--destructive); } .tag.info { --tc: var(--info); }
.tag.late { color: var(--card); background: var(--destructive); }
dialog.pr { width: min(920px, calc(100vw - 32px)); max-height: calc(100vh - 48px); padding: 0; border: 1px solid var(--border); border-top: 3px solid var(--c); border-radius: var(--radius); background: var(--card); color: var(--card-foreground); overflow: auto; }
dialog.pr::backdrop { background: rgb(0 0 0 / .45); }
.rh { position: sticky; top: 0; z-index: 1; padding: 10px 14px; display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; background: var(--card); border-bottom: 1px solid var(--border); }
.rh .btn { text-decoration: none; }
.rh .tag + .btn, .rh .pill + .btn { margin-left: auto; }
.rh .t { font-size: 15px; font-weight: 600; flex: 1 1 300px; }
.next { border-radius: var(--radius); padding: 10px 14px; border-left: 4px solid var(--nc); background: color-mix(in srgb, var(--nc) 10%, transparent); display: flex; flex-direction: column; gap: 6px; }
.next .nt { font-size: 15px; font-weight: 600; color: var(--foreground); }
.next ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 2px; }
.t-ok { --nc: var(--success); } .t-warn { --nc: var(--warning); } .t-bad { --nc: var(--destructive); } .t-info { --nc: var(--info); } .t-muted { --nc: var(--muted-foreground); }
.cmds { display: flex; flex-wrap: wrap; gap: 6px; }
.cmd { font: 500 12px var(--font-mono); padding: 3px 9px; border-radius: var(--radius); border: 1px solid color-mix(in srgb, var(--nc) 50%, var(--border)); background: var(--card); color: var(--foreground); cursor: pointer; }
.cmd:hover { border-color: var(--nc); }
.sigs { display: flex; flex-wrap: wrap; gap: 6px; }
.sig { font-size: 12px; padding: 2px 9px 2px 7px; border-radius: 999px; border: 1px solid var(--border); color: var(--foreground); cursor: default; display: inline-flex; align-items: center; gap: 6px; }
.sig::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--sc); }
.s-ok { --sc: var(--success); } .s-warn { --sc: var(--warning); } .s-bad { --sc: var(--destructive); } .s-muted { --sc: var(--muted-foreground); }
.fm { font-size: 11px; color: var(--muted-foreground); margin-left: auto; }
.more-all > summary { cursor: pointer; font-size: 12.5px; color: var(--muted-foreground); list-style: none; display: flex; gap: 6px; align-items: baseline; }
.more-all > summary::-webkit-details-marker { display: none; }
.more-all > summary::before { content: "\\25B8"; font-size: 10px; }
.more-all[open] > summary::before { content: "\\25BE"; }
.mb { display: flex; flex-direction: column; gap: 12px; padding: 10px 0 0 14px; border-left: 2px solid var(--border); margin: 6px 0 0 4px; color: var(--muted-foreground); }
.mb p, .mb dd { color: var(--foreground); }
.fd > summary::-webkit-details-marker, .more > summary::-webkit-details-marker { display: none; }
.fd > summary::before, .more > summary::before { content: "\\25B8"; color: var(--muted-foreground); font-size: 10px; }
.fd[open] > summary::before, .more[open] > summary::before { content: "\\25BE"; }
.pr .n { font: 500 12px var(--font-mono); color: var(--muted-foreground); }
.pr .t { font-weight: 600; flex: 1 1 300px; }
.pill { font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; padding: 1px 7px; border-radius: 4px; color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent); }
.body { padding: 12px 18px 18px; display: flex; flex-direction: column; gap: 12px; font-size: 13px; }
.by { color: var(--muted-foreground); font-size: 12px; display: flex; flex-wrap: wrap; gap: 2px 12px; }
.tldr { font-size: 14px; margin: 0; max-width: 75ch; }
.box { border-radius: var(--radius); padding: 7px 11px; margin: 0; background: color-mix(in srgb, var(--bc, var(--warning)) 12%, transparent); }
.box.auto { --bc: var(--info); } .box.reply { --bc: var(--success); }
dl.facts { display: grid; grid-template-columns: auto 1fr; gap: 3px 14px; margin: 0; }
.facts dt { color: var(--muted-foreground); } .facts dd { margin: 0; }
h3 { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: var(--muted-foreground); margin: 0 0 4px; }
h4 { font-size: 12px; font-weight: 600; margin: 4px 0 2px; }
section p { margin: 0; }
ul.plain { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 3px; }
.hint { color: var(--muted-foreground); font-size: 12px; }
.fl { display: flex; flex-direction: column; gap: 5px; }
.fd { border: 1px solid var(--border); border-left: 3px solid var(--fc, var(--muted-foreground)); border-radius: var(--radius); }
.fd > summary { padding: 5px 10px; display: flex; flex-wrap: wrap; gap: 2px 8px; align-items: baseline; list-style: none; }
.fd > summary { cursor: pointer; }
.fd .fid { font: 12px var(--font-mono); color: var(--muted-foreground); }
.fd .sev { font: 600 10px var(--font-mono); color: var(--fc, var(--muted-foreground)); }
.fd .ft { flex: 1 1 240px; }
.fd .loc { font: 11px var(--font-mono); color: var(--muted-foreground); overflow-wrap: anywhere; }
.fd .fb { padding: 0 10px 8px 26px; display: flex; flex-direction: column; gap: 4px; }
.fd .fix::before { content: "Fix: "; font-weight: 600; color: var(--muted-foreground); }
.s-CRITICAL { --fc: var(--destructive); } .s-PROBLEM { --fc: var(--warning); } .s-SUGGESTION { --fc: var(--info); }
.fixbox { border: 1px solid var(--border); border-left: 3px solid var(--warning); border-radius: var(--radius); padding: 8px 11px; display: flex; flex-direction: column; gap: 6px; }
.more > summary { cursor: pointer; list-style: none; font-size: 12px; color: var(--muted-foreground); display: flex; gap: 6px; align-items: baseline; }
.da { color: var(--success); background: color-mix(in srgb, var(--success) 12%, transparent); }
.dr { color: var(--destructive); background: color-mix(in srgb, var(--destructive) 12%, transparent); }
.dh { color: var(--info); } .df { color: var(--muted-foreground); font-weight: 600; }
.btn { font: 500 11.5px var(--font-sans); padding: 3px 9px; border-radius: var(--radius); border: 1px solid var(--border); background: transparent; color: var(--foreground); cursor: pointer; }
.btn:hover { border-color: var(--info); }
[hidden] { display: none !important; }
"""

JS = """
const q = document.getElementById("q"), hd = document.getElementById("hd");
function filt() {
  const s = q.value.trim().toLowerCase().replace(/^#/, "");
  document.querySelectorAll("[data-q]").forEach(e => {
    e.hidden = (hd.checked && e.dataset.d === "1") || (s !== "" && !e.dataset.q.includes(s));
  });
}
q.addEventListener("input", filt);
hd.addEventListener("change", filt);
document.addEventListener("click", e => {
  const a = e.target.closest("a.chip");
  if (a) {
    const d = document.getElementById(a.getAttribute("href").slice(1));
    if (d) { e.preventDefault(); d.showModal(); d.scrollTop = 0; }
    return;
  }
  if (e.target.closest("[data-close]") || e.target.matches("dialog.pr")) {
    e.target.closest("dialog").close();
    return;
  }
  const c = e.target.closest("button[data-cmd]");
  if (c) {
    const t = c.dataset.cmd;
    const ok = () => { c.textContent = "Copied"; setTimeout(() => { c.textContent = t; }, 1200); };
    if (navigator.clipboard) navigator.clipboard.writeText(t).then(ok, () => {});
    return;
  }
  const b = e.target.closest("button[data-copy]");
  if (!b) return;
  e.preventDefault();
  const el = document.getElementById(b.dataset.copy);
  const done = () => { b.textContent = "Copied"; };
  const pick = () => {
    const box = el.closest("details");
    if (box) box.open = true;
    const r = document.createRange(); r.selectNodeContents(el);
    const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
    b.textContent = "Selected, press copy";
  };
  if (navigator.clipboard) navigator.clipboard.writeText(el.textContent).then(done, pick); else pick();
});
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Render the pr-review report.")
    ap.add_argument("state")
    ap.add_argument("--full", metavar="OUT")
    ap.add_argument("--digest", metavar="OUT")
    args = ap.parse_args()
    if not (args.full or args.digest):
        ap.error("pass --full, --digest or both")
    with open(args.state) as f:
        state = json.load(f)
    now = datetime.now(timezone.utc)
    if args.full:
        _write(args.full, _page(state, now), FULL_LIMIT, "full")
    if args.digest:
        html = ""
        for title_len in (70, 48, 32):
            html = _digest(state, now, title_len)
            if len(html) <= DIGEST_LIMIT:
                break
        _write(args.digest, html, DIGEST_LIMIT, "digest")


def _write(path: str, html: str, limit: int, what: str) -> None:
    """Write a page, refusing to go over its size budget."""
    if len(html) > limit:
        sys.exit(f"{what} page is {len(html)} chars, over the {limit} budget")
    with open(path, "w") as f:
        f.write(html)
    print(f"wrote {what} page, {len(html)} chars, to {path}")


def _page(state: dict, now: datetime) -> str:
    """Build the full report for a browser."""
    prs = _matrix_prs(state, now)
    cells: dict = {(r, c): [] for r, _, _ in ROWS for c, _, _ in COLS}
    for p in prs:
        col = _col(p, now)
        row = "attention" if col == "auto" else (p.get("status") if p.get("status") in ("attention", "waiting") else "attention")
        cells[(row, col)].append(p)
    for items in cells.values():
        items.sort(key=lambda p: (bool(p.get("draft")), not p.get("reviewed_now"), -int(p["number"])))
    ordered = [p for r, _, _ in ROWS for c, _, _ in COLS for p in cells[(r, c)]]

    repos = sorted({p.get("repo") or "server" for p in prs if p.get("state", "open") == "open"}, key=lambda r: (r != "server", r))
    n_open = sum(1 for p in prs if p.get("state", "open") == "open")
    tallies = "".join(
        f'<span class="tally" style="--c:var(--{v})"><b>{sum(len(cells[(r, c)]) for r, _, _ in ROWS)}</b>{escape(label.lower())}</span>'
        for c, label, v in COLS
    )
    head = (
        f'<header><div><h1>Music Assistant PR backlog</h1><p class="sub">{n_open} open PRs across '
        f'{escape(", ".join(repos))}. Last run {escape(_fmt(state.get("last_run")))}, base dev @ '
        f'<code>{escape(str(state.get("dev", "")))}</code>.</p></div><div class="tallies">{tallies}</div></header>'
    )
    note = f'<p class="note">{_md(state.get("run_note"))}</p>' if state.get("run_note") else ""
    controls = (
        '<div class="controls"><input id="q" type="search" placeholder="Filter by PR number, repo, title, author or provider" '
        'aria-label="Filter PRs"><label><input type="checkbox" id="hd"> Hide drafts</label>'
        '<span class="legend">Red cards have waited on you for a week or more. Size counts changed lines of code, '
        "without tests, icons, translations and lockfiles.</span></div>"
    )
    thead = "".join(f'<th><span class="dot" style="--c:var(--{v})"></span>{escape(label)}</th>' for _, label, v in COLS)
    rows = []
    for r, label, hint in ROWS:
        tds = []
        for c, _, _ in COLS:
            if c == "auto" and r == "waiting":
                tds.append('<td><span class="empty">n/a</span></td>')
                continue
            items = cells[(r, c)]
            body = "".join(_chip(p, now) for p in items) if items else '<span class="empty">none</span>'
            tds.append(f'<td><div class="cell">{body}</div></td>')
        rows.append(f'<tr><th class="status"><b>{escape(label)}</b><span>{escape(hint)}</span></th>{"".join(tds)}</tr>')
    matrix = (
        f'<div class="scroll"><table class="matrix"><thead><tr><th class="status">Status</th>{thead}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>'
    )
    reviews = "".join(_detail(p, now) for p in ordered)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>PR backlog</title><style>{THEME}{CSS}{PAGE}</style></head><body><div class=\"wrap\">"
        f"{head}{note}{controls}{matrix}</div>{reviews}<script>{JS}</script></body></html>"
    )


def _digest(state: dict, now: datetime, title_len: int) -> str:
    """Build the compact page for html_render: tallies plus only the PRs this run changed."""
    prs = _matrix_prs(state, now)
    open_prs = [p for p in prs if not _recent_auto(p, now)]
    autos = [p for p in prs if _recent_auto(p, now)]
    tallies = ""
    for c, label, v in COLS[:3]:
        col = [p for p in open_prs if _col(p, now) == c]
        mine = sum(1 for p in col if p.get("status") == "attention")
        tallies += f'<span style="--c:var(--{v})">{len(col)} {escape(label.lower())}, {mine} need you</span>'
    tallies += f'<span style="--c:var(--info)">{len(autos)} auto-approved this week</span>'
    late = sum(1 for p in open_prs if (_wait_days(p, now) or 0) >= 7)
    if late:
        tallies += f'<span style="--c:var(--destructive)">{late} over the 1 week SLA</span>'
    changed = [p for p in open_prs if p.get("changed_now") or p.get("reviewed_now")]
    changed.sort(key=lambda p: (p.get("status") != "attention", -(_wait_days(p, now) or 0), -int(p["number"])))
    if changed:
        rows = "".join(_digest_row(p, now, title_len) for p in changed)
        table = (
            '<div class="sc"><table><thead><tr><th>PR</th><th>Title, author</th><th>Size</th><th>State</th>'
            f'<th>Bot-MArley</th><th>Waits on</th></tr></thead><tbody>{rows}</tbody></table></div>'
        )
    else:
        table = '<p class="muted">No open PR changed this run.</p>'
    short = []
    for p in state.get("prs", []):
        if not p.get("changed_now") or p in changed:
            continue
        what = p.get("state", "open")
        if p.get("auto_approved"):
            what = f"auto-approved, {what}"
        short.append(
            f'<li><a href="{escape(p.get("url", ""))}">{escape(_label(p))}</a> {escape(_cut(p.get("title", ""), title_len))}, '
            f'{escape(what)}</li>'
        )
    short_html = f'<div><b class="i">Merged, closed or auto-approved this run</b><ul>{"".join(short)}</ul></div>' if short else ""
    head = (
        f'<div><h1>PR backlog</h1><div class="sub">Run {escape(_fmt(state.get("last_run")))}, dev <code>'
        f'{escape(str(state.get("dev", "")))}</code>, {len(open_prs)} open PRs, {len(changed)} changed</div></div>'
    )
    note = f'<p class="note">{_md(state.get("run_note"))}</p>' if state.get("run_note") else ""
    footer = (
        f'<div class="ft">Full matrix with every review in the side panel, or <code>open {FULL_REPORT}</code>. Replies: <code>post &lt;pr&gt; f&lt;n&gt;</code>, '
        "<code>fix &lt;pr&gt;</code>, <code>approve &lt;pr&gt;</code>, <code>chip &lt;pr&gt;</code>, <code>prompt &lt;pr&gt;</code>, "
        "<code>show &lt;pr&gt;</code>, <code>review &lt;pr&gt;</code>, <code>skip &lt;pr&gt;</code>, <code>render</code>; "
        "&lt;pr&gt; is 7045 or models#438.</div>"
    )
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{DIGEST_CSS}</style></head><body><div class="w">'
        f'{head}<div class="tl">{tallies}</div>{note}{table}{short_html}{footer}</div></body></html>'
    )


def _digest_row(p: dict, now: datetime, title_len: int) -> str:
    """One compact digest row."""
    age = _wait_days(p, now)
    text, cls = VERDICT_SHORT.get(p.get("verdict"), ("not ready", "x"))
    state = f'<b class="{cls}">{text}</b>' + (" <b>draft</b>" if p.get("draft") else "")
    change = p.get("changed_now") or ("reviewed" if p.get("reviewed_now") else "")
    if change:
        state += f' <b class="i">{escape(_cut(str(change), 20))}</b>'
    mv, mv_cls = _marley_short(p)
    waiting = p.get("waiting_on") or ("you" if p.get("status") == "attention" else "author")
    if age is not None:
        waiting += f" {age}d"
    late = ' class="l"' if age is not None and age >= 7 else ""
    return (
        f'<tr{late}><td class="n"><a href="{escape(p.get("url", ""))}">'
        f'{escape(_label(p))}</a></td><td class="t">{escape(_cut(p.get("title", ""), title_len), quote=False)} '
        f'<span class="muted">{escape(_cut(p.get("author", ""), 16))}</span></td><td><b>{escape(str(p.get("size", "?")))}</b></td><td class="s">{state}</td>'
        f'<td class="{mv_cls}">{mv}</td><td>{escape(_cut(waiting, 24))}</td></tr>'
    )


def _marley_short(p: dict) -> tuple:
    """Bot-MArley verdict for a digest cell, with a colour class."""
    m = p.get("marley")
    if not isinstance(m, dict):
        return "?", "muted"
    if m.get("verdict") in (None, "none"):
        return "none", "muted"
    if not m.get("reviewed_head", True):
        return "old head", "muted"
    n = m.get("open_threads") or 0
    if m.get("verdict") == "approved" and not n:
        return "approved", "ok"
    return (f"{n} open" if n else "changes"), "wn"


def _cut(s: str, n: int) -> str:
    """Shorten text to n characters."""
    s = str(s or "")
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


def _matrix_prs(state: dict, now: datetime) -> list:
    """PRs that belong in the matrix: open ones plus auto-approvals from the last week."""
    return [p for p in state.get("prs", []) if p.get("state", "open") == "open" or _recent_auto(p, now)]


def _chip(p: dict, now: datetime) -> str:
    """Render a matrix card that jumps to the PR's review."""
    col = _col(p, now)
    age = _wait_days(p, now)
    late = age is not None and age >= 7
    counts = {}
    for f in p.get("findings") or []:
        sev = str(f.get("severity", "")).upper()
        counts[sev] = counts.get(sev, 0) + 1
    fs = ", ".join(
        x
        for x in (
            f'{counts["CRITICAL"]} critical' if counts.get("CRITICAL") else "",
            f'{counts["PROBLEM"]} problem{"s" if counts["PROBLEM"] > 1 else ""}' if counts.get("PROBLEM") else "",
        )
        if x
    )
    meta = f"<span>{escape(p.get('author', ''))}</span>" + (f"<span>{fs}</span>" if fs else "") + "".join(_tags(p, now))
    return (
        f'<a class="chip c-{col}{" late" if late else ""}" href="#{_anchor(p)}" data-q="{escape(_q(p))}" '
        f'data-d="{1 if p.get("draft") and p.get("status") != "attention" else 0}"><span class="n">{escape(_label(p))}</span>'
        f'<span class="t">{escape(p.get("title", ""), quote=False)}</span><span class="m">{meta}</span></a>'
    )


def _tags(p: dict, now: datetime) -> list:
    """Badges shown on a card and on its review header."""
    col = _col(p, now)
    tags = [f'<span class="tag size">{escape(str(p.get("size", "?")))}</span>']
    if p.get("draft"):
        tags.append('<span class="tag">draft</span>')
    if col == "auto":
        tags.append(f'<span class="tag info">auto-approved {escape(str(p["auto_approved"].get("at", ""))[5:10])}</span>')
    if p.get("author") == "MarvinSchenkel":
        tags.append('<span class="tag info">yours</span>')
    bp = p.get("backport") or {}
    if bp.get("rec") and (p.get("verdict") == "ready" or p.get("auto_approved")):
        tags.append('<span class="tag ok">backport</span>')
    if p.get("author_replied"):
        tags.append('<span class="tag ok">user replied</span>')
    if p.get("reporter_reply"):
        tags.append('<span class="tag ok">reporter replied</span>')
    if p.get("reviewed_now"):
        tags.append('<span class="tag warn">new review</span>')
    if p.get("ci_fail"):
        tags.append('<span class="tag bad">ci</span>')
    if p.get("stacked"):
        tags.append('<span class="tag warn">stacked</span>')
    age = _wait_days(p, now)
    if age is not None:
        cls = "tag late" if age >= 7 else "tag"
        tags.append(f'<span class="{cls}" title="Waiting on you since {escape(p["attention_since"][:10])}">{age}d on you</span>')
    return tags


def _detail(p: dict, now: datetime) -> str:
    """Render one PR's review as the dialog its card opens: next step first, details folded away."""
    col = _col(p, now)
    _, col_label, var = next(c for c in COLS if c[0] == col)
    sha = str(p.get("head_sha") or "")[:9] or "head"
    age = _wait_days(p, now)
    wait = f'<span class="tag{" late" if (age or 0) >= 7 else ""}">{age}d on you</span>' if age is not None else ""
    head = (
        f'<div class="rh"><span class="n">{escape(_label(p))}</span><span class="t">{escape(p.get("title", ""), quote=False)}</span>'
        f'<span class="pill">{escape(col_label)}</span>{wait}'
        f'<a class="btn" href="{escape(p.get("url", ""))}" target="_blank" rel="noopener">GitHub</a>'
        '<button class="btn" data-close aria-label="Close">Close</button></div>'
    )
    meta = [escape(p.get("author", "")), f'{escape(str(p.get("size", "?")))}, {escape(str(p.get("code", "?")))} loc']
    if p.get("draft"):
        meta.append("draft")
    meta.append(f'reviewed {escape(str(p.get("reviewed_at") or "never"))} on <code>{escape(sha)}</code>')
    parts = [f'<div class="by">{"".join(f"<span>{m}</span>" for m in meta)}</div>', _next_step(p, now), _signals(p)]
    if p.get("tldr"):
        parts.append(f'<p class="tldr">{_md(p["tldr"])}</p>')
    parts.append(_findings(p))
    parts.append(_more(p, col, sha))
    return (
        f'<dialog class="pr" id="{_anchor(p)}" style="--c:var(--{var})">{head}'
        f'<div class="body">{"".join(parts)}</div></dialog>'
    )


def _next_step(p: dict, now: datetime) -> str:
    """The one thing to do on this PR, its blockers and the replies that do it."""
    rl = _reply_label(p)
    mine = p.get("author") == "MarvinSchenkel"
    sf = p.get("suggested_fix") if isinstance(p.get("suggested_fix"), dict) else {}
    open_fs = [
        f"f{i}" for i, f in enumerate(p.get("findings") or [], 1)
        if str(f.get("severity", "")).upper() in ("CRITICAL", "PROBLEM") and not f.get("posted")
    ]
    bullets = [b for b in (p.get("blockers") or []) if b]
    cmds: list = []
    rr = p.get("reporter_reply")
    if p.get("state", "open") != "open":
        aa = p.get("auto_approved") or {}
        what = f'Auto-approved {aa.get("at", "")[:10]}, now {p.get("state")}' if aa else f'{p.get("state", "").capitalize()}'
        tone, title, bullets = "info", what, []
    elif p.get("status") != "attention":
        tone, title = "muted", f'Waiting on {p.get("waiting_on") or "the author"}'
    elif isinstance(rr, dict) and mine:
        tone, title = "warn", f'Reporter replied on {rr.get("issue", "the issue")}'
        bullets = [rr.get("summary", "")] + bullets
    elif p.get("verdict") == "ready":
        tone = "ok"
        if mine:
            title = "Ready. Merge it once someone else approves"
        else:
            title, cmds = "Approve and queue the merge", [f"approve {rl}"]
    elif p.get("verdict") == "almost":
        tone = "warn"
        if sf.get("patch") and not sf.get("pushed"):
            title, cmds = "Push the prepared fix", [f"fix {rl}"]
        else:
            title = "Answer the open points"
        cmds += [f"post {rl} {' '.join(open_fs)}"] if open_fs else []
    else:
        tone, title = "bad", "Decide on the open findings"
        cmds += [f"post {rl} {' '.join(open_fs)}"] if open_fs else []
    if p.get("prompt") and p.get("state", "open") == "open" and p.get("status") == "attention":
        cmds.append(f"chip {rl}")
    shown, extra = bullets[:3], len(bullets) - 3
    items = "".join(f"<li>{_md(b)}</li>" for b in shown) + (f'<li class="hint">{extra} more under details</li>' if extra > 0 else "")
    ul = f"<ul>{items}</ul>" if items else ""
    chips = "".join(f'<button class="cmd" type="button" data-cmd="{escape(c)}" title="Copy reply">{escape(c)}</button>' for c in cmds)
    return f'<div class="next t-{tone}"><div class="nt">{escape(title)}</div>{ul}{f"<div class=cmds>{chips}</div>" if chips else ""}</div>'


def _signals(p: dict) -> str:
    """One-word health pills for CI, merge, reviews and backport; the full text sits in the tooltip."""
    out = []
    ci = str(p.get("ci") or "")
    if p.get("ci_fail"):
        out.append(("bad", "CI failing", ci))
    elif "green" in ci.lower() or "pass" in ci.lower():
        out.append(("ok", "CI green", ci))
    else:
        out.append(("muted", "CI n/a", ci))
    ms = str(p.get("merge_state") or "")
    low = ms.lower()
    if re.search(r"(?<!no )conflict|dirty", low):
        out.append(("bad", "Conflicts", ms))
    elif "clean" in low or "mergeable" in low:
        out.append(("ok", "Merges clean", ms))
    else:
        out.append(("muted", "Merge n/a", ms))
    tones = {"ok": "ok", "wn": "warn", "bd": "bad"}
    mv, mc = _marley_short(p)
    out.append((tones.get(mc, "muted"), f"Bot-MArley {mv}", str((p.get("marley") or {}).get("note") or "")))
    lab = p.get("lab")
    if isinstance(lab, dict) and lab.get("result"):
        res = str(lab["result"])
        tone = {"green": "ok", "red": "bad"}.get(res, "muted")
        out.append((tone, f"Lab {res}", f'{", ".join(lab.get("areas") or [])} {lab.get("run_id") or ""} {lab.get("note") or ""}'.strip()))
    bp = p.get("backport")
    if isinstance(bp, dict) and (p.get("verdict") == "ready" or p.get("auto_approved")):
        out.append(("ok" if bp.get("rec") else "muted", "Backport" if bp.get("rec") else "No backport", str(bp.get("why") or "")))
    pills = "".join(f'<span class="sig s-{t}" title="{escape(tip)}">{escape(label)}</span>' for t, label, tip in out)
    return f'<div class="sigs">{pills}</div>'


def _more(p: dict, col: str, sha: str) -> str:
    """Everything that is not needed to decide, folded into one details block."""
    rl = escape(_reply_label(p))
    parts = []
    if p.get("whats_new"):
        parts.append(f"<section><h3>This run</h3><p>{_md(p['whats_new'])}</p></section>")
    for key, what in (("reporter_reply", "Reporter reply"), ("author_replied", "Author reply")):
        r = p.get(key)
        if isinstance(r, dict):
            src = " ".join(escape(str(r[k])) for k in ("issue", "author") if r.get(k))
            link = f' <a href="{escape(r["url"])}">open</a>' if r.get("url") else ""
            parts.append(f"<section><h3>{what}</h3><p>{src}, {escape(_fmt(r.get('at')))}: {_md(r.get('summary'))}{link}</p></section>")
    if p.get("auto_approved"):
        aa = p["auto_approved"]
        parts.append(f"<section><h3>Auto-approval</h3><p>{escape(str(aa.get('at', '')))}. {_md(aa.get('note'))}</p></section>")
    facts = [("CI", _md(p.get("ci"))), ("Merge", _md(p.get("merge_state")))]
    bp = p.get("backport")
    if isinstance(bp, dict) and (p.get("verdict") == "ready" or p.get("auto_approved")):
        facts.append(("Backport", ("Recommended. " if bp.get("rec") else "No. ") + _md(bp.get("why"))))
    facts.append(("Bot-MArley", _marley(p.get("marley"))))
    parts.append('<section><h3>Checks</h3><dl class="facts">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts) + "</dl></section>")
    sf = p.get("suggested_fix")
    if sf and col != "auto" and p.get("verdict") != "ready":
        patch = sf.get("patch") if isinstance(sf, dict) else None
        desc = sf.get("description") if isinstance(sf, dict) else sf
        pushed = sf.get("pushed") if isinstance(sf, dict) else None
        box = [f"<p>{_md(desc)}</p>"]
        if patch:
            box.append(_diff(patch))
            if pushed:
                box.append(f'<p class="hint">Pushed {escape(str(pushed.get("at", "")))} as <code>{escape(str(pushed.get("sha", "")))}</code>.</p>')
            else:
                box.append(f'<p class="hint"><code>fix {rl}</code> commits this on top of <code>{escape(sha)}</code> and pushes it.</p>')
        parts.append(f"<section><h3>Suggested fix</h3>{''.join(box)}</section>")
    if p.get("prompt"):
        pid = f"pp-{_anchor(p)}"
        parts.append(
            f'<section><h3>Fix session prompt <button class="btn" type="button" data-copy="{pid}">Copy</button></h3>'
            f'<pre id="{pid}">{escape(str(p["prompt"]), quote=False)}</pre></section>'
        )
    if p.get("summary"):
        parts.append(f"<section><h3>Review notes</h3><p>{_md(p['summary'])}</p></section>")
    blockers = p.get("blockers") or []
    if len(blockers) > 3:
        parts.append(f"<section><h3>All blockers</h3>{_list(blockers)}</section>")
    if p.get("unaddressed_comments"):
        parts.append(f"<section><h3>Unaddressed review comments</h3>{_list(p['unaddressed_comments'])}</section>")
    if p.get("related_prs"):
        parts.append(f"<section><h3>Related PRs</h3>{_list(p['related_prs'])}</section>")
    if p.get("fix_thread"):
        parts.append(f"<section><h3>Fix session</h3><p>{_md(str(p['fix_thread']))}</p></section>")
    return f'<details class="more-all"><summary>More details</summary><div class="mb">{"".join(parts)}</div></details>'


def _findings(p: dict) -> str:
    """Findings as one line each, most severe first, numbered f1, f2 in state order."""
    fs = p.get("findings") or []
    if not fs:
        return ""
    order = {"CRITICAL": 0, "PROBLEM": 1, "SUGGESTION": 2, "NIT": 3}
    items = sorted(enumerate(fs, 1), key=lambda x: (order.get(str(x[1].get("severity", "")).upper(), 4), x[0]))
    out = []
    for i, f in items:
        sev = str(f.get("severity", "")).upper()
        where = escape(str(f.get("file") or "")) + (f":{escape(str(f['line']))}" if f.get("line") else "")
        posted = f.get("posted")
        badge = ""
        if posted:
            url = posted.get("url") if isinstance(posted, dict) else None
            badge = f'<a class="tag ok" href="{escape(url)}">posted</a>' if url else '<span class="tag ok">posted</span>'
        model = f'<span class="fm">{escape(f["model"])}</span>' if f.get("model") else ""
        head = (
            f'<span class="fid">f{i}</span><span class="sev">{escape(sev.lower())}</span>'
            f'<span class="ft">{_md(f.get("title"))}</span>{badge}{model}'
        )
        body = (f'<p class="loc">{where}</p>' if where else "") + (f"<p>{_md(f.get('detail'))}</p>" if f.get("detail") else "") + (
            f'<p class="fix">{_md(f.get("fix"))}</p>' if f.get("fix") else ""
        )
        out.append(f'<details class="fd s-{escape(sev)}"><summary>{head}</summary><div class="fb">{body}</div></details>')
    return f'<section><h3>Findings</h3><div class="fl">{"".join(out)}</div></section>'


def _marley(m) -> str:
    """Summarise the marley block, preferring its note."""
    if not isinstance(m, dict):
        return "See summary"
    text = _md(m.get("note")) or f'{escape(str(m.get("verdict") or "none"))}, {m.get("open_threads") or 0} open thread(s)'
    if m.get("review_url"):
        text += f' <a href="{escape(m["review_url"])}">review</a>'
    return text


def _list(items) -> str:
    """Render a list whose entries may be strings, numbers or small objects."""
    if isinstance(items, (int, str)):
        items = [items]
    lis = []
    for x in items:
        if isinstance(x, dict):
            if "summary" in x:
                who = " ".join(escape(str(x[k])) for k in ("author", "at") if x.get(k))
                link = f' <a href="{escape(x["url"])}">open</a>' if x.get("url") else ""
                lis.append(f"<li>{who}: {_md(x['summary'])}{link}</li>")
            else:
                ref = f'{x["repo"]}#{x["number"]}' if x.get("repo") else f'#{x.get("number", "")}'
                rest = ", ".join(str(x[k]) for k in ("title", "state", "relation", "note") if x.get(k))
                lis.append(f"<li>{escape(ref)}{': ' + _md(rest) if rest else ''}</li>")
        elif isinstance(x, int):
            lis.append(f"<li>#{x}</li>")
        else:
            lis.append(f"<li>{_md(x)}</li>")
    return f'<ul class="plain">{"".join(lis)}</ul>'


def _md(s) -> str:
    """Render the small markdown subset the state uses: code fences, inline code, bold, links, newlines."""
    if not s:
        return ""
    out = []
    for i, part in enumerate(re.split(r"```(?:\w+)?\n?", str(s))):
        if i % 2:
            out.append(f"<pre><code>{escape(part.rstrip(chr(10)), quote=False)}</code></pre>")
            continue
        for j, seg in enumerate(re.split(r"(`[^`\n]+`)", part)):
            if j % 2:
                out.append(f"<code>{escape(seg[1:-1], quote=False)}</code>")
                continue
            h = escape(seg, quote=False)
            h = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", h)
            h = re.sub(r"(https?://[^\s<)\]]+[^\s<)\].,;:])", r'<a href="\1">\1</a>', h)
            out.append(h.replace("\n", "<br>"))
    return "".join(out)


def _diff(patch: str) -> str:
    """Colour a unified diff."""
    lines = []
    for line in str(patch).rstrip("\n").split("\n"):
        text = escape(line, quote=False)
        if line.startswith(("+++", "---")):
            lines.append(f'<span class="df">{text}</span>')
        elif line.startswith("@@"):
            lines.append(f'<span class="dh">{text}</span>')
        elif line.startswith("+"):
            lines.append(f'<span class="da">{text}</span>')
        elif line.startswith("-"):
            lines.append(f'<span class="dr">{text}</span>')
        else:
            lines.append(text)
    return "<pre>" + "\n".join(lines) + "</pre>"


def _col(p: dict, now: datetime) -> str:
    """Matrix column for a PR."""
    if _recent_auto(p, now):
        return "auto"
    v = p.get("verdict")
    return v if v in ("ready", "almost", "not_ready") else "not_ready"


def _recent_auto(p: dict, now: datetime) -> bool:
    """Whether the PR was auto-approved within the last week."""
    aa = p.get("auto_approved")
    at = _ts(aa.get("at")) if isinstance(aa, dict) else None
    return at is not None and now - at <= WEEK


def _wait_days(p: dict, now: datetime):
    """Whole days the PR has waited on Marvin, or None."""
    if p.get("status") != "attention" or _recent_auto(p, now) or p.get("state", "open") != "open":
        return None
    since = _ts(p.get("attention_since"))
    return None if since is None else max(0, (now - since).days)


def _ts(s):
    """Parse ISO timestamps and the 'YYYY-MM-DD HH:MM CEST' form."""
    if not s:
        return None
    s = str(s).strip()
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(?::\d{2})?\s*([A-Z]{3,4})", s)
    if m and m.group(3) in TZ_NAMES:
        tz = timezone(timedelta(hours=TZ_NAMES[m.group(3)]))
        return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}").replace(tzinfo=tz)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _fmt(s, date_only: bool = False) -> str:
    """Format a timestamp in local time for display."""
    dt = _ts(s)
    if dt is None:
        return str(s or "")
    local = dt.astimezone()
    return local.strftime("%Y-%m-%d") if date_only else local.strftime("%Y-%m-%d %H:%M")


def _key(p: dict) -> str:
    """Stable key for a PR across repos."""
    return f'{p.get("repo") or "server"}-{p["number"]}'


def _anchor(p: dict) -> str:
    """Element id of the PR's review block."""
    return f"pr-{_key(p)}"


def _label(p: dict) -> str:
    """Display label, bare number for server PRs."""
    repo = p.get("repo") or "server"
    return f'#{p["number"]}' if repo == "server" else f'{repo}#{p["number"]}'


def _reply_label(p: dict) -> str:
    """How a reply addresses the PR."""
    repo = p.get("repo") or "server"
    return str(p["number"]) if repo == "server" else f'{repo}#{p["number"]}'


def _q(p: dict) -> str:
    """Lowercased search text for the filter box."""
    prov = p.get("providers_touched") if isinstance(p.get("providers_touched"), list) else []
    return " ".join(str(x) for x in [p["number"], p.get("repo", ""), p.get("title", ""), p.get("author", ""), *prov]).lower()


if __name__ == "__main__":
    main()
