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
COMPACT_MAX = 300
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
h2 { font-size: 13px; font-weight: 600; margin: 8px 0 0; text-transform: uppercase; letter-spacing: .05em; color: var(--muted-foreground); }
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
.c-ready { --c: var(--success); } .c-almost { --c: var(--warning); } .c-not_ready { --c: var(--destructive); } .c-auto { --c: var(--info); }
.tag { font: 500 10px var(--font-mono); padding: 0 5px; border-radius: 3px; text-transform: uppercase; letter-spacing: .03em; color: var(--tc, var(--muted-foreground)); background: color-mix(in srgb, var(--tc, var(--muted-foreground)) 14%, transparent); white-space: nowrap; }
.tag.size { --tc: var(--foreground); }
.tag.ok { --tc: var(--success); } .tag.warn { --tc: var(--warning); } .tag.bad { --tc: var(--destructive); } .tag.info { --tc: var(--info); }
.tag.late { color: var(--card); background: var(--destructive); }
details.pr { border: 1px solid var(--border); border-left: 3px solid var(--c); border-radius: var(--radius); scroll-margin-top: 8px; }
details.pr > summary { cursor: pointer; padding: 8px 12px; display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; list-style: none; }
details.pr > summary::-webkit-details-marker, .fd > summary::-webkit-details-marker, .more > summary::-webkit-details-marker { display: none; }
details.pr > summary::before, .fd > summary::before, .more > summary::before { content: "\\25B8"; color: var(--muted-foreground); font-size: 10px; }
details[open].pr > summary::before, .fd[open] > summary::before, .more[open] > summary::before { content: "\\25BE"; }
.pr .n { font: 500 12px var(--font-mono); color: var(--muted-foreground); }
.pr .t { font-weight: 600; flex: 1 1 300px; }
.pill { font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; padding: 1px 7px; border-radius: 4px; color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent); }
.body { padding: 2px 14px 14px 26px; display: flex; flex-direction: column; gap: 12px; font-size: 13px; }
.by { color: var(--muted-foreground); font-size: 12px; display: flex; flex-wrap: wrap; gap: 2px 12px; }
.tldr { font-size: 14px; margin: 0; }
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
table.closed { border-collapse: collapse; width: 100%; font-size: 12.5px; }
.closed td { padding: 4px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }
.closed td.n { font-family: var(--font-mono); white-space: nowrap; }
.closed td.w { color: var(--muted-foreground); white-space: nowrap; }
.footer { font-size: 12px; color: var(--muted-foreground); border-top: 1px solid var(--border); padding-top: 10px; line-height: 1.7; }
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
    if (d) { e.preventDefault(); d.open = true; d.scrollIntoView({behavior: "smooth", block: "start"}); }
    return;
  }
  const b = e.target.closest("button[data-copy]");
  if (!b) return;
  e.preventDefault();
  const el = document.getElementById(b.dataset.copy);
  const done = () => { b.textContent = "Copied"; };
  const pick = () => {
    el.closest("details").open = true;
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
        for title_len, fold in ((70, False), (48, False), (48, True), (32, True)):
            html = _digest(state, now, title_len, fold)
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
    details = '<h2>Reviews</h2>' + "".join(_detail(p, now) for p in ordered)
    closed = _closed_section(state, now)
    footer = (
        '<div class="footer">Reply in this thread: <code>post 7045 f2</code> posts a finding, '
        "<code>fix 7045</code> pushes the prepared patch, <code>approve 7045</code> approves and queues the merge, "
        "<code>chip 7045</code> starts a fix session, <code>prompt 7045</code> prints the prompt, "
        "<code>show 7045</code> prints the full review, <code>review 7045</code> reviews it again, "
        "<code>skip 7045</code> keeps it out of the report. Other repos use <code>models#438</code>.</div>"
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>PR backlog</title><style>{THEME}{CSS}{PAGE}</style></head><body><div class=\"wrap\">"
        f"{head}{note}{controls}{matrix}{details}{closed}{footer}</div><script>{JS}</script></body></html>"
    )


def _digest(state: dict, now: datetime, title_len: int, fold: bool) -> str:
    """Build the compact page for html_render: no finding bodies, prompts or patches."""
    prs = _matrix_prs(state, now)
    open_prs = [p for p in prs if not _recent_auto(p, now)]
    autos = [p for p in prs if _recent_auto(p, now)]
    groups = []
    for r, rlabel, _ in ROWS:
        for c, clabel, var in COLS[:3]:
            items = [p for p in open_prs if _col(p, now) == c and (p.get("status") == r or (r == "attention" and p.get("status") not in ("attention", "waiting")))]
            items.sort(key=lambda p: (-(_wait_days(p, now) or 0), bool(p.get("draft")), -int(p["number"])))
            if items:
                groups.append((f"{rlabel}, {clabel.lower()}", var, items))
    tallies = "".join(
        f'<span style="--c:var(--{v})">{sum(1 for p in open_prs if _col(p, now) == c)} {escape(label.lower())}</span>'
        for c, label, v in COLS[:3]
    ) + f'<span style="--c:var(--info)">{len(autos)} auto-approved this week</span>'
    late = sum(1 for p in open_prs if (_wait_days(p, now) or 0) >= 7)
    if late:
        tallies += f'<span style="--c:var(--destructive)">{late} over the 1 week SLA</span>'
    rows = []
    for label, var, items in groups:
        shown = items
        folded = []
        if fold and "Waiting" in label:
            folded = [p for p in items if p.get("draft") and p.get("author") != "MarvinSchenkel"]
            shown = [p for p in items if p not in folded]
        rows.append(f'<tr class="g" style="--c:var(--{var})"><th colspan="7">{escape(label)} ({len(items)})</th></tr>')
        rows.extend(_digest_row(p, now, title_len) for p in shown)
        if folded:
            nums = ", ".join(_label(p) for p in folded)
            rows.append(f'<tr><td></td><td class="t muted" colspan="6">{len(folded)} drafts by others: {escape(nums)}</td></tr>')
    table = (
        '<div class="sc"><table><thead><tr><th>PR</th><th>Title, author</th><th>Size</th><th>State</th>'
        f'<th>Copilot</th><th>GPT Sol</th><th>Waits on</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )
    short = []
    for p in sorted(autos, key=lambda p: _ts(p["auto_approved"].get("at")), reverse=True):
        st = p.get("state", "open")
        tail = f", {st} {_fmt(p.get('closed_at'), date_only=True)[5:]}" if st != "open" else ", open"
        short.append(
            f'<li><a href="{escape(p.get("url", ""))}">{escape(_label(p))}</a> {escape(_cut(p.get("title", ""), title_len))}, '
            f'auto-approved {escape(str(p["auto_approved"].get("at", ""))[5:10])}{escape(tail)}</li>'
        )
    week = [
        p for p in state.get("prs", [])
        if p.get("state", "open") != "open" and not _recent_auto(p, now)
        and (_ts(p.get("closed_at")) or now - 2 * WEEK) >= now - WEEK
    ]
    for p in week:
        short.append(
            f'<li><a href="{escape(p.get("url", ""))}">{escape(_label(p))}</a> {escape(_cut(p.get("title", ""), title_len))}, '
            f'{escape(p.get("state", ""))} {escape(_fmt(p.get("closed_at"), date_only=True)[5:])}</li>'
        )
    short_html = f'<div><b class="i">Auto-approved and closed this week</b><ul>{"".join(short)}</ul></div>' if short else ""
    head = (
        f'<div><h1>PR backlog</h1><div class="sub">Run {escape(_fmt(state.get("last_run")))}, dev <code>'
        f'{escape(str(state.get("dev", "")))}</code>, {len(open_prs)} open PRs</div></div>'
    )
    note = f'<p class="note">{_md(state.get("run_note"))}</p>' if state.get("run_note") else ""
    footer = (
        f'<div class="ft">Full report: <code>open {FULL_REPORT}</code>. Replies: <code>post &lt;pr&gt; f&lt;n&gt;</code>, '
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
    cp, cp_cls = _copilot_short(p)
    gs, gs_cls = _gpt_short(p)
    waiting = p.get("waiting_on") or ("you" if p.get("status") == "attention" else "author")
    if age is not None:
        waiting += f" {age}d"
    late = ' class="l"' if age is not None and age >= 7 else ""
    return (
        f'<tr{late}><td class="n"><a href="{escape(p.get("url", ""))}">'
        f'{escape(_label(p))}</a></td><td class="t">{escape(_cut(p.get("title", ""), title_len), quote=False)} '
        f'<span class="muted">{escape(_cut(p.get("author", ""), 16))}</span></td><td><b>{escape(str(p.get("size", "?")))}</b></td><td>{state}</td>'
        f'<td class="{cp_cls}">{cp}</td><td class="{gs_cls}">{gs}</td><td>{escape(_cut(waiting, 24))}</td></tr>'
    )


def _copilot_short(p: dict) -> tuple:
    """Copilot verdict for a digest cell, with a colour class."""
    c = p.get("copilot")
    if not isinstance(c, dict):
        return "none", "muted"
    if not p.get("copilot_reviewed_head", True):
        return "old head", "muted"
    if c.get("green"):
        return "green", "ok"
    n = c.get("findings") or 0
    return (f"{n} open", "wn") if n else ("comments", "muted")


def _gpt_short(p: dict) -> tuple:
    """GPT Sol verdict for a digest cell, from gpt_sol or its findings."""
    if p.get("gpt_sol"):
        v = str(p["gpt_sol"])
        return escape(_cut(v, 18)), "ok" if v == "clean" else "wn"
    n = sum(1 for f in p.get("findings") or [] if f.get("model") == "GPT Sol")
    return (f"{n} found", "wn") if n else ("?", "muted")


def _cut(s: str, n: int) -> str:
    """Shorten text to n characters."""
    s = str(s or "")
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


def _matrix_prs(state: dict, now: datetime) -> list:
    """PRs that belong in the matrix: open ones plus auto-approvals from the last week."""
    return [p for p in state.get("prs", []) if p.get("state", "open") == "open" or _recent_auto(p, now)]


def _closed_section(state: dict, now: datetime) -> str:
    """One compact row per merged or closed PR that left the matrix."""
    rows = [p for p in state.get("prs", []) if p.get("state", "open") != "open" and not _recent_auto(p, now)]
    if not rows:
        return ""
    rows.sort(key=lambda p: _ts(p.get("closed_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    extra = len(rows) - COMPACT_MAX
    out = []
    for p in rows[:COMPACT_MAX]:
        what = f'{p.get("state")} {_fmt(p.get("closed_at"), date_only=True)}'.strip()
        if p.get("auto_approved"):
            what += ", auto-approved"
        out.append(
            f'<tr data-q="{escape(_q(p))}" data-d="0"><td class="n"><a href="{escape(p.get("url", ""))}">{escape(_label(p))}</a></td>'
            f'<td>{escape(p.get("title", ""), quote=False)}</td><td class="w">{escape(p.get("author", ""))}</td>'
            f'<td class="w">{escape(what)}</td></tr>'
        )
    more = f'<p class="hint">{extra} older merged or closed PRs are kept in the state file only.</p>' if extra > 0 else ""
    return f'<h2>Merged or closed</h2><table class="closed">{"".join(out)}</table>{more}'


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
        f'data-d="{1 if p.get("draft") else 0}"><span class="n">{escape(_label(p))}</span>'
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
    """Render one PR's full review as a collapsible block."""
    col = _col(p, now)
    _, col_label, var = next(c for c in COLS if c[0] == col)
    lbl = _label(p)
    sha = str(p.get("head_sha") or "")[:9] or "head"
    summary = (
        f'<summary><span class="n">{escape(lbl)}</span><span class="t">{escape(p.get("title", ""), quote=False)}</span>'
        f'<span class="pill">{escape(col_label)}</span>{"".join(_tags(p, now))}</summary>'
    )
    loc = f'{p.get("code", "?")} loc, +{p.get("add", "?")}/-{p.get("del", "?")} total'
    by = (
        f'<div class="by"><span>{escape(p.get("author", ""))}</span><span>{escape(str(p.get("size", "")))}, {loc}</span>'
        f'<span>reviewed {escape(str(p.get("reviewed_at") or ""))} on <code>{escape(sha)}</code></span>'
        f'<a href="{escape(p.get("url", ""))}">Open on GitHub</a></div>'
    )
    parts = [by]
    if p.get("auto_approved"):
        aa = p["auto_approved"]
        parts.append(f'<p class="box auto">Auto-approved {escape(str(aa.get("at", "")))}. {_md(aa.get("note"))}</p>')
    if p.get("whats_new"):
        parts.append(f'<p class="box">{_md(p["whats_new"])}</p>')
    for key, what in (("reporter_reply", "Reporter reply"), ("author_replied", "Author reply")):
        r = p.get(key)
        if isinstance(r, dict):
            where = f' on {escape(r["issue"])}' if r.get("issue") else ""
            who = f' by {escape(r["author"])}' if r.get("author") else ""
            link = f' <a href="{escape(r["url"])}">open</a>' if r.get("url") else ""
            parts.append(f'<p class="box reply"><b>{what}</b>{where}{who}, {escape(_fmt(r.get("at")))}: {_md(r.get("summary"))}{link}</p>')
    if p.get("fix_thread"):
        parts.append(f'<p class="hint">Fix session: {_md(str(p["fix_thread"]))}</p>')
    parts.append(f'<p class="tldr">{_md(p.get("tldr"))}</p>')
    if p.get("blockers"):
        parts.append(f"<section><h3>Before merge</h3>{_list(p['blockers'])}</section>")
    rl = escape(_reply_label(p))
    facts = [("CI", _md(p.get("ci"))), ("Merge", _md(p.get("merge_state")))]
    bp = p.get("backport")
    if bp and (p.get("verdict") == "ready" or p.get("auto_approved")):
        facts.append(("Backport", ("Recommended. " if bp.get("rec") else "No. ") + _md(bp.get("why"))))
    facts.append(("Copilot", _md(p.get("copilot_note")) or _copilot(p.get("copilot"))))
    parts.append('<dl class="facts">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in facts) + "</dl>")
    sf = p.get("suggested_fix")
    if sf and col != "auto" and p.get("verdict") != "ready":
        patch = sf.get("patch") if isinstance(sf, dict) else None
        desc = sf.get("description") if isinstance(sf, dict) else sf
        pushed = sf.get("pushed") if isinstance(sf, dict) else None
        box = [f"<p>{_md(desc)}</p>"]
        if patch:
            n = patch.rstrip("\n").count("\n") + 1
            box.append(f'<details class="more"><summary>Patch, {n} lines</summary>{_diff(patch)}</details>')
            if pushed:
                box.append(f'<p class="hint">Pushed {escape(str(pushed.get("at", "")))} as <code>{escape(str(pushed.get("sha", "")))}</code>.</p>')
            else:
                box.append(f'<p class="hint">Reply <code>fix {rl}</code> to commit this on top of <code>{escape(sha)}</code> and push it to the PR.</p>')
        parts.append(f'<section><h3>Suggested fix</h3><div class="fixbox">{"".join(box)}</div></section>')
    if p.get("prompt"):
        pid = f"pp-{_anchor(p)}"
        parts.append(
            f'<section><h3>Fix session prompt</h3><details class="more"><summary>Show prompt '
            f'<button class="btn" type="button" data-copy="{pid}">Copy prompt</button></summary>'
            f'<pre id="{pid}">{escape(str(p["prompt"]), quote=False)}</pre></details>'
            f'<p class="hint">Reply <code>chip {rl}</code> to start a fix session with it.</p></section>'
        )
    parts.append(f"<section><h3>Summary</h3><p>{_md(p.get('summary'))}</p></section>")
    parts.append(_findings(p))
    uc = p.get("unaddressed_comments")
    if uc:
        parts.append(f"<section><h3>Unaddressed review comments</h3>{_list(uc)}</section>")
    if p.get("related_prs"):
        parts.append(f"<section><h3>Related PRs</h3>{_list(p['related_prs'])}</section>")
    return _wrap_detail(p, var, summary, parts)


def _wrap_detail(p: dict, var: str, summary: str, parts: list) -> str:
    """Wrap a review body in its details element."""
    return (
        f'<details class="pr" id="{_anchor(p)}" style="--c:var(--{var})" data-q="{escape(_q(p))}" '
        f'data-d="{1 if p.get("draft") else 0}">{summary}<div class="body">{"".join(parts)}</div></details>'
    )


def _findings(p: dict) -> str:
    """Render findings grouped by the model that raised them, numbered f1, f2 and so on."""
    fs = p.get("findings") or []
    if not fs:
        return '<section><h3>Findings</h3><p class="hint">No findings.</p></section>'
    groups: dict = {}
    for i, f in enumerate(fs, 1):
        groups.setdefault(f.get("model") or "", []).append((i, f))
    out = []
    for model, items in groups.items():
        if len(groups) > 1 or model:
            out.append(f"<h4>{escape(model or 'Combined review')}</h4>")
        for i, f in items:
            sev = str(f.get("severity", "")).upper()
            where = escape(str(f.get("file") or "")) + (f":{escape(str(f['line']))}" if f.get("line") else "")
            posted = f.get("posted")
            badge = ""
            if posted:
                url = posted.get("url") if isinstance(posted, dict) else None
                badge = f'<a class="tag ok" href="{escape(url)}">posted</a>' if url else '<span class="tag ok">posted</span>'
            head = (
                f'<span class="fid">f{i}</span><span class="sev">{escape(sev)}</span>'
                f'<span class="ft">{_md(f.get("title"))}</span>{badge}<span class="loc">{where}</span>'
            )
            body = (f"<p>{_md(f.get('detail'))}</p>" if f.get("detail") else "") + (
                f'<p class="fix">{_md(f.get("fix"))}</p>' if f.get("fix") else ""
            )
            out.append(f'<details class="fd s-{escape(sev)}"><summary>{head}</summary><div class="fb">{body}</div></details>')
    hint = f'<p class="hint">Reply <code>post {escape(_reply_label(p))} f1</code> to post a finding as a review comment.</p>'
    return f'<section><h3>Findings</h3><div class="fl">{"".join(out)}</div>{hint}</section>'


def _copilot(c) -> str:
    """Summarise the copilot block when no note was written."""
    if not isinstance(c, dict):
        return "See summary"
    if c.get("green"):
        return "No open findings"
    return f'{c.get("findings", 0)} finding(s), {c.get("comments", 0)} comment(s)'


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
