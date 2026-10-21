"""Render the security inbox board and its inline digest from the routine's state file.

Usage: python3 build.py <state.json> [--full <board.html>] [--digest <digest.html>]
"""
import argparse
import json
import os
import sys
from html import escape

REPO = "https://github.com/music-assistant/server"
FULL_MAX = 2_000_000
DIGEST_MAX = 40_000
# (key, lane name, lane description, color, board)
LANES = [
    ("draft", "Draft", "New reports to accept or close", "--info", "adv"),
    ("open", "Open", "Accepted, needs a fix or publishing", "--warning", "adv"),
    ("fp", "False positive", "Recommended to close", "--muted-foreground", "adv"),
    ("new", "Alerts: not picked up", "No fix or decision yet", "--destructive", "cs"),
    ("pr", "Alerts: PR in draft", "Fix PR open as draft", "--success", "cs"),
    ("unsure", "Alerts: unsure", "Assessed, look before it gets dismissed or fixed", "--muted-foreground", "cs"),
]
BADGES = {
    "needs_attention": ("bad", "needs attention"),
    "waiting_for_user": ("warn", "waiting for user"),
    "waiting_for_cve": ("info", "waiting for CVE"),
}
SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEV_TONE = {"critical": "bad", "high": "warn"}
REPLY_GRAMMAR = "fix &lt;id&gt;, close &lt;ghsa&gt;, dismiss cs-&lt;n&gt;, draft &lt;id&gt;"

CSS = """
:root { color-scheme: light dark; }
/* Standalone theme for the side panel tab, which gets no T3 theme variables. */
:root {
  --background: #ffffff; --foreground: #18181b; --muted: #f4f4f5; --muted-foreground: #71717a; --border: #e4e4e7;
  --info: #2563eb; --destructive: #dc2626; --warning: #b45309; --success: #15803d; --radius: 8px;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --background: #0f0f11; --foreground: #f4f4f5; --muted: #27272a; --muted-foreground: #a1a1aa; --border: #2e2e33;
    --info: #60a5fa; --destructive: #f87171; --warning: #fbbf24; --success: #4ade80;
  }
}
* { box-sizing: border-box; }
html { background: var(--background); }
body { font-family: var(--font-sans); color: var(--foreground); margin: 0; padding: 16px; font-size: 14px; line-height: 1.5; }
a { color: inherit; text-decoration-color: var(--muted-foreground); text-underline-offset: 2px; }
code, .mono { font-family: var(--font-mono); font-size: .9em; overflow-wrap: anywhere; }
.wrap { display: flex; flex-direction: column; gap: 20px; padding: 4px 0 12px; }
h1 { font-size: 18px; font-weight: 600; margin: 0; }
h2 { font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted-foreground); margin: 0 0 8px; font-weight: 600; }
h4 { font-size: 11.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted-foreground); margin: 6px 0 4px; font-weight: 600; }
.sub { color: var(--muted-foreground); margin: 2px 0 0; font-size: 13px; }
.tools { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.tools input[type=search] { flex: 1 1 240px; min-width: 0; padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius); background: transparent; color: var(--foreground); font: inherit; }
.tools label { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; color: var(--muted-foreground); }
.cols { display: grid; grid-template-columns: repeat(6, minmax(200px, 1fr)); gap: 8px; align-items: start; overflow-x: auto; padding-bottom: 4px; }
.col { border: 1px solid var(--border); border-top: 3px solid var(--c); border-radius: var(--radius); padding: 8px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.col-head { display: flex; justify-content: space-between; align-items: baseline; gap: 6px; }
.col-head b { font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--muted-foreground); line-height: 1.3; }
.col-head .n { font: 500 12px var(--font-mono); color: var(--c); }
.col-desc { font-size: 11.5px; color: var(--muted-foreground); margin: 0; line-height: 1.35; }
.chip { display: flex; flex-direction: column; gap: 3px; padding: 5px 7px; border: 1px solid var(--border); border-left: 3px solid var(--c); border-radius: calc(var(--radius) - 2px); text-decoration: none; min-width: 0; }
.chip:hover { background: var(--muted); }
.num { font: 500 11.5px var(--font-mono); color: var(--muted-foreground); }
.chip .t { font-size: 12.5px; line-height: 1.3; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.tags { display: flex; flex-wrap: wrap; gap: 3px; }
.b { --t: var(--muted-foreground); font: 500 10px var(--font-mono); padding: 0 5px; border-radius: 3px; text-transform: uppercase; letter-spacing: .03em; line-height: 1.7; color: var(--t); background: color-mix(in srgb, var(--t) 14%, transparent); white-space: nowrap; }
.ok { --t: var(--success); } .warn { --t: var(--warning); } .info { --t: var(--info); } .bad { --t: var(--destructive); }
.empty { font-size: 12px; color: var(--muted-foreground); }
.group { display: flex; flex-direction: column; gap: 6px; }
details.card { border: 1px solid var(--border); border-left: 3px solid var(--c); border-radius: var(--radius); scroll-margin-top: 8px; }
details.card > summary { cursor: pointer; padding: 7px 10px; display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; list-style: none; }
details.card > summary::-webkit-details-marker { display: none; }
details.card > summary .t { flex: 1 1 260px; font-size: 13.5px; }
.body { padding: 2px 12px 12px; display: flex; flex-direction: column; gap: 10px; border-top: 1px solid var(--border); }
.body p { margin: 0 0 6px; max-width: 100ch; }
.by { color: var(--muted-foreground); font-size: 12.5px; display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 8px; }
.todo { border-left: 3px solid var(--destructive); background: color-mix(in srgb, var(--destructive) 10%, transparent); border-radius: calc(var(--radius) - 2px); padding: 8px 12px; }
.todo b { font-size: 11.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--destructive); display: block; }
details.older > summary { cursor: pointer; color: var(--muted-foreground); font-size: 12.5px; margin: 2px 0 6px; }
ul.tight { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; max-width: 100ch; }
.tbl { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { font-size: 11.5px; letter-spacing: .05em; text-transform: uppercase; color: var(--muted-foreground); font-weight: 600; }
tr:last-child td { border-bottom: 0; }
td.m { font-family: var(--font-mono); white-space: nowrap; }
td.chg { color: var(--destructive); font-weight: 600; }
.vec { font: 12px var(--font-mono); background: var(--muted); padding: 6px 8px; border-radius: calc(var(--radius) - 2px); overflow-wrap: anywhere; margin-top: 6px; }
.reply-text { white-space: pre-wrap; font: 12.5px/1.5 var(--font-mono); margin: 6px 0; padding: 10px; border: 1px solid var(--border); border-radius: calc(var(--radius) - 2px); overflow-wrap: anywhere; max-width: 100ch; }
button { font: inherit; font-size: 12.5px; font-weight: 500; border-radius: calc(var(--radius) - 2px); padding: 3px 12px; cursor: pointer; border: 1px solid var(--border); background: transparent; color: var(--foreground); }
button:hover { background: var(--muted); }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 12.5px; color: var(--muted-foreground); }
.row code { color: var(--foreground); }
dl.kv { display: grid; grid-template-columns: max-content 1fr; gap: 3px 14px; font-size: 13px; margin: 0 0 8px; }
dl.kv dt { color: var(--muted-foreground); }
dl.kv dd { margin: 0; overflow-wrap: anywhere; }
.note { font-size: 12.5px; color: var(--muted-foreground); border-top: 1px solid var(--border); padding-top: 10px; margin: 0; }
.note code { color: var(--foreground); }
.hide { display: none !important; }
@media (max-width: 1180px) { .cols { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 640px) { .cols { grid-template-columns: 1fr; } }
"""

DIGEST_CSS = """
:root { color-scheme: light dark; }
body { font-family: var(--font-sans); color: var(--foreground); margin: 0; font-size: 13.5px; line-height: 1.45; }
a { color: inherit; text-underline-offset: 2px; text-decoration-color: var(--muted-foreground); }
code { font-family: var(--font-mono); font-size: .9em; }
.wrap { display: flex; flex-direction: column; gap: 14px; padding: 4px 0 8px; }
h1 { font-size: 15px; font-weight: 600; margin: 0; }
h2 { font-size: 11.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted-foreground); margin: 0 0 6px; font-weight: 600; }
.sub { color: var(--muted-foreground); font-size: 12.5px; }
.lanes { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 6px; }
.lane { border: 1px solid var(--border); border-top: 3px solid var(--c); border-radius: var(--radius); padding: 6px 8px; }
.lane .k { font-size: 10.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted-foreground); line-height: 1.25; }
.lane .v { font: 600 17px var(--font-mono); margin-top: 2px; }
.lane .s { font-size: 11px; color: var(--warning); }
.rows { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--radius); }
.r { padding: 6px 10px; border-bottom: 1px solid var(--border); border-left: 3px solid var(--info); }
.r:last-child { border-bottom: 0; }
.r .l1 { display: flex; gap: 8px; align-items: baseline; }
.r .n { font: 500 12px var(--font-mono); white-space: nowrap; }
.r .t { flex: 1; min-width: 0; }
.r .l2 { color: var(--muted-foreground); font-size: 12.5px; margin-top: 1px; }
.foot { font-size: 12px; color: var(--muted-foreground); border-top: 1px solid var(--border); padding-top: 8px; display: flex; flex-direction: column; gap: 3px; }
.foot code { color: var(--foreground); }
"""

JS = """
(function(){
  document.querySelectorAll("a.chip").forEach(a => a.addEventListener("click", e => {
    e.preventDefault();
    const d = document.getElementById(a.hash.slice(1));
    if (!d) return;
    d.open = true;
    d.scrollIntoView({block: "start", behavior: "smooth"});
  }));
  document.querySelectorAll("button[data-copy]").forEach(b => b.addEventListener("click", async () => {
    const src = document.getElementById(b.dataset.copy);
    try { await navigator.clipboard.writeText(src.textContent); b.textContent = "Copied"; }
    catch (e) {
      const r = document.createRange(); r.selectNodeContents(src);
      const s = getSelection(); s.removeAllRanges(); s.addRange(r);
      b.textContent = "Selected, press copy";
    }
    setTimeout(() => { b.textContent = "Copy"; }, 2000);
  }));
  const q = document.getElementById("q"), act = document.getElementById("act");
  function filter(){
    const term = q.value.trim().toLowerCase(), only = act.checked;
    document.querySelectorAll("a.chip").forEach(a => {
      const text = (a.textContent + " " + a.dataset.a).toLowerCase();
      const hide = (term && !text.includes(term)) || (only && !a.dataset.p);
      a.classList.toggle("hide", hide);
      document.getElementById(a.hash.slice(1)).classList.toggle("hide", hide);
    });
    document.querySelectorAll(".col").forEach(col => {
      const n = col.querySelectorAll("a.chip:not(.hide)").length;
      col.querySelector(".n").textContent = n;
      col.querySelector(".empty").classList.toggle("hide", n > 0);
    });
    document.querySelectorAll(".group").forEach(g => g.classList.toggle("hide", !g.querySelector("details.card:not(.hide)")));
  }
  q.addEventListener("input", filter);
  act.addEventListener("change", filter);
})();
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the security inbox board and digest.")
    parser.add_argument("state")
    parser.add_argument("--full", help="write the complete board here")
    parser.add_argument("--digest", help="write the inline digest here")
    args = parser.parse_args()
    if not (args.full or args.digest):
        parser.error("give --full, --digest or both")
    with open(args.state) as f:
        state = json.load(f)
    if args.full:
        _write(args.full, render_full(state), FULL_MAX)
    if args.digest:
        _write(args.digest, render_digest(state, args.full), DIGEST_MAX)


def render_full(state: dict) -> str:
    """Render the complete board with every card in full."""
    lanes, groups = [], []
    for key, name, desc, color, board in LANES:
        in_lane = _lane_cards(state, key, board)
        chips = "".join(_chip(c, color) for c in in_lane)
        empty = '<div class="empty' + (" hide" if in_lane else "") + '">Nothing here</div>'
        lanes.append(
            f'<section class="col" style="--c:var({color})"><div class="col-head"><b>{escape(name)}</b>'
            f'<span class="n">{len(in_lane)}</span></div><p class="col-desc">{escape(desc)}</p>{empty}{chips}</section>'
        )
        if in_lane:
            body = "".join(_card(c, color) for c in in_lane)
            groups.append(f'<section class="group"><h2>{escape(name)} ({len(in_lane)})</h2>{body}</section>')
    parts = [
        '<header><h1>Security inbox</h1>'
        f'<p class="sub">Last run {escape(state.get("last_run") or "never")}</p></header>',
        '<div class="tools"><input id="q" type="search" placeholder="Filter by GHSA id, alert number, title or rule" '
        'aria-label="Filter cards"><label><input type="checkbox" id="act"> Only cards that need attention</label></div>',
        '<div class="cols">' + "".join(lanes) + "</div>",
        *groups,
        _tracking(state),
        _run_note(state),
        '<p class="note">Reply in this thread to act on a card: <code>fix &lt;id&gt;</code> starts a fix thread, '
        "<code>close &lt;ghsa&gt;</code> closes an advisory as a false positive, <code>dismiss cs-&lt;n&gt;</code> "
        "dismisses an alert, <code>draft &lt;id&gt;</code> shows the draft reply in chat.</p>",
    ]
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Security inbox</title><base target="_blank"><style>'
        + CSS
        + '</style></head><body><div class="wrap">'
        + "".join(p for p in parts if p)
        + "</div><script>"
        + JS
        + "</script></body></html>"
    )


def render_digest(state: dict, board_path: str | None) -> str:
    """Render the compact inline digest: lane counts and the cards that changed this run."""
    run = state.get("last_run") or ""
    lanes, changed = [], []
    for key, name, _, color, board in LANES:
        in_lane = _lane_cards(state, key, board)
        due = sum(1 for c in in_lane if _pending(c))
        lanes.append(
            f'<div class="lane" style="--c:var({color})"><div class="k">{escape(name)}</div>'
            f'<div class="v">{len(in_lane)}</div><div class="s">{f"{due} need you" if due else "&nbsp;"}</div></div>'
        )
        changed += [(c, name) for c in in_lane if _changed(c, run)]
    rows = [_row(c, name) for c, name in changed] + [
        f'<div class="r"><div class="l1"><a class="n" href="{REPO}/security/code-scanning/{escape(str(d["number"]))}">'
        f'#{escape(str(d["number"]))}</a><span class="t">{escape(d.get("rule") or "")}</span></div>'
        f'<div class="l2">Dismissed as false positive · {escape(d["reason"])}</div></div>'
        for d in state.get("dismissed_this_run") or []
    ]
    board = escape((board_path or "~/.claude-teamB/routine-reports/security-inbox.html").replace(os.path.expanduser("~"), "~", 1))
    parts = [
        f'<div><h1>Security inbox</h1><div class="sub">Last run {escape(run or "never")}</div></div>',
        '<div class="lanes">' + "".join(lanes) + "</div>",
        f"<section><h2>Changed this run ({len(rows)})</h2>"
        + ('<div class="rows">' + "".join(rows) + "</div>" if rows else '<div class="sub">Nothing changed this run.</div>')
        + "</section>",
        f'<div class="foot"><span>Full board with filter, CVSS and drafts in the side panel, or <code>open {board}</code></span>'
        f"<span>Replies: <code>{REPLY_GRAMMAR}</code></span></div>",
    ]
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Security inbox</title><base target="_blank"><style>'
        + DIGEST_CSS + '</style></head><body><div class="wrap">' + "".join(parts) + "</div></body></html>"
    )


def _write(path: str, html: str, limit: int) -> None:
    """Write a page after checking it against its size limit."""
    if len(html) > limit:
        sys.exit(f"{path}: {len(html)} characters, over the {limit} limit")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        f.write(html)
    print(f"{path}: {len(html)} characters")


def _lane_cards(state: dict, key: str, board: str) -> list:
    """Return the lane's cards, attention first, then by severity."""
    cards = state.get("advisories" if board == "adv" else "code_scanning", [])
    return sorted((c for c in cards if c.get("column") == key), key=_sort_key)


def _row(c: dict, lane: str) -> str:
    """Render one digest row."""
    status = c["action"] if _pending(c) and c.get("action") else _plain((c.get("status") or [""])[0])
    status = " ".join(status.split())
    if len(status) > 160:
        status = status[:160].rstrip() + "…"
    meta = " · ".join(x for x in (lane, escape(status, quote=False)) if x)
    return (
        f'<div class="r"><div class="l1"><a class="n" href="{escape(c["url"])}">{escape(_short(c))}</a>'
        f'<span class="t">{escape(c["title"], quote=False)}</span></div><div class="l2">{meta}</div></div>'
    )


def _changed(c: dict, run: str) -> bool:
    """Whether the card's newest status line was written on the run's day."""
    return bool(run) and (c.get("status") or [""])[0].startswith(run[5:10])


def _plain(text: str) -> str:
    """Strip the HTML tags status lines may carry."""
    out, depth = [], 0
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">" and depth:
            depth -= 1
        elif not depth:
            out.append(ch)
    return "".join(out)


def _badges(c: dict) -> list:
    """Return the card's badge keys."""
    return c.get("badges") or []


def _pending(c: dict) -> bool:
    """Whether the card needs Marvin."""
    return "needs_attention" in _badges(c)


def _sort_key(c: dict) -> tuple:
    """Sort attention first, waiting on the reporter last, then by severity."""
    b = _badges(c)
    rank = 0 if "needs_attention" in b else 2 if "waiting_for_user" in b else 1
    return (rank, SEV_RANK.get(c.get("severity") or "", 9))


def _short(c: dict) -> str:
    """Return the id Marvin types in a reply."""
    cid = c["id"]
    return cid.split("-")[1] if cid.startswith("GHSA-") else cid


def _anchor(c: dict) -> str:
    """Return the DOM id of the card's detail block."""
    return f"card-{c['id']}"


def _tags(c: dict) -> str:
    """Render the severity, accept advice and badge tags."""
    tags = []
    if c.get("severity"):
        tags.append(_badge(SEV_TONE.get(c["severity"], ""), c["severity"]))
    if c.get("should_accept") is not None:
        yes = bool(c["should_accept"])
        tags.append(_badge("ok" if yes else "", f'accept: {"yes" if yes else "no"}'))
    for b in _badges(c):
        if b in BADGES:
            tags.append(_badge(*BADGES[b]))
    return "".join(tags)


def _badge(tone: str, text: str) -> str:
    """Render one badge."""
    return f'<span class="b {tone}">{escape(text)}</span>'


def _search_attrs(c: dict) -> str:
    """Data attributes the filter box reads next to the chip text."""
    extra = " ".join(str(c.get(k) or "") for k in ("id", "rule", "path", "reporter"))
    return f'data-a="{escape(extra)}"' + (' data-p="1"' if _pending(c) else "")


def _chip(c: dict, color: str) -> str:
    """Render one card on the board lanes."""
    return (
        f'<a class="chip" href="#{escape(_anchor(c))}" target="_self" {_search_attrs(c)} style="--c:var({color})">'
        f'<span class="num">{escape(c.get("label") or c["id"])}</span><span class="t">{escape(c["title"], quote=False)}</span>'
        f'<span class="tags">{_tags(c)}</span></a>'
    )


def _card(c: dict, color: str) -> str:
    """Render one card's full detail block."""
    return (
        f'<details class="card" id="{escape(_anchor(c))}" style="--c:var({color})"><summary>'
        f'<span class="num">{escape(c.get("label") or c["id"])}</span><span class="t">{escape(c["title"], quote=False)}</span>'
        f'<span class="tags">{_tags(c)}</span></summary><div class="body">{_card_body(c)}</div></details>'
    )


def _card_body(c: dict) -> str:
    """Render the expanded card contents."""
    out = []
    by = [f'<a href="{escape(c["url"])}">{escape(c.get("label") or c["id"])}</a>']
    for key, label in (("severity", "Severity"), ("rule", "Rule"), ("path", "At"), ("reporter", "Reported by"), ("opened", "Opened"), ("checked", "Checked")):
        if c.get(key):
            by.append(f"<span>{label} {escape(str(c[key]))}</span>")
    if c.get("fix_thread"):
        by.append(f'<span>Fix thread <code>{escape(c["fix_thread"])}</code></span>')
    out.append(f'<div class="by">{"".join(by)}</div>')
    if _pending(c) and c.get("action"):
        out.append(f'<div class="todo"><b>Your move</b>{escape(c["action"])}</div>')
    status = c.get("status") or []
    if status:
        block = f"<div><h4>Status</h4><p>{status[0]}</p>"
        if len(status) > 1:
            older = "".join(f"<p>{s}</p>" for s in status[1:])
            block += f'<details class="older"><summary>Earlier ({len(status) - 1})</summary>{older}</details>'
        out.append(block + "</div>")
    if c.get("facts"):
        out.append('<div><h4>Details</h4><ul class="tight">' + "".join(f"<li>{f}</li>" for f in c["facts"]) + "</ul></div>")
    if c.get("cvss"):
        out.append(_cvss(c["cvss"]))
    if c.get("pr"):
        out.append(f'<div><h4>Fix PR</h4><p><a href="{escape(c["pr"]["url"])}">{escape(c["pr"]["label"])}</a></p></div>')
    if c.get("draft_comment"):
        out.append(_copy_block(c, "reply", c["draft_comment"].get("title") or "Draft reply", c["draft_comment"]["text"]))
    if c.get("dismiss"):
        d = c["dismiss"]
        out.append(
            _copy_block(c, "dismiss", f'Suggested dismissal, reason "{escape(d.get("reason") or "false positive")}"', d.get("comment") or "")
        )
    out.append(_card_hint(c))
    return "".join(out)


def _copy_block(c: dict, kind: str, title: str, text: str) -> str:
    """Render a text block with a copy button."""
    pid = escape(f"{kind}-{c['id']}")
    return (
        f'<div><h4>{title}</h4><div class="reply-text" id="{pid}">{escape(text)}</div>'
        f'<div class="row"><button data-copy="{pid}">Copy</button></div></div>'
    )


def _card_hint(c: dict) -> str:
    """Render the replies that apply to this card."""
    sid = escape(_short(c))
    if c["id"].startswith("GHSA-"):
        verbs = [f"<code>draft {sid}</code>"] if c.get("draft_comment") else []
        if not c.get("fix_thread") and not c.get("pr") and c.get("column") != "fp":
            verbs.append(f"<code>fix {sid}</code>")
        if c.get("column") == "fp":
            verbs.append(f"<code>close {sid}</code>")
    else:
        verbs = [f"<code>dismiss {sid}</code>"]
        if not c.get("fix_thread") and not c.get("pr"):
            verbs.append(f"<code>fix {sid}</code>")
    return f'<div class="row">Reply {", ".join(verbs)}</div>' if verbs else ""


def _cvss(cv: dict) -> str:
    """Render the CVSS suggestion table."""
    rows = []
    for m in cv.get("metrics", []):
        rep, sug = m.get("reported") or "-", m.get("suggested") or "-"
        chg = " chg" if m.get("reported") and m.get("reported") != m.get("suggested") else ""
        rows.append(
            f'<tr><td>{escape(m["name"])}</td><td class="m">{escape(rep)}</td>'
            f'<td class="m{chg}">{escape(sug)}</td><td>{escape(m.get("why") or "")}</td></tr>'
        )
    vec = ""
    if cv.get("reported_vector"):
        vec += f'On advisory: {escape(cv["reported_vector"])} ({escape(str(cv.get("reported_score", "")))})<br>'
    vec += f'Suggested: {escape(cv.get("suggested_vector", ""))} ({escape(str(cv.get("suggested_score", "")))})'
    return (
        f'<div><h4>CVSS 3.1 suggestion</h4><p>{escape(cv.get("summary") or "")}</p>'
        '<div class="tbl"><table><thead><tr><th>Metric</th><th>On advisory</th><th>Suggested</th><th>Why</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div><div class="vec">{vec}</div></div>'
    )


def _tracking(state: dict) -> str:
    """Render the release lines and the per-advisory fix table."""
    rel = state.get("releases") or []
    tracked = sorted((a for a in state.get("advisories", []) if a.get("tracking")), key=_sort_key)
    if not rel and not tracked:
        return ""
    out = ["<section><h2>Release and fix tracking</h2>"]
    if rel:
        rows = []
        for r in rel:
            val = f"<code>{escape(r['value'])}</code>"
            if r.get("url"):
                val = f'<a href="{escape(r["url"])}">{val}</a>'
            note = f" {escape(r['note'])}" if r.get("note") else ""
            rows.append(f"<dt>{escape(r['label'])}</dt><dd>{val}{note}</dd>")
        out.append(f'<dl class="kv">{"".join(rows)}</dl>')
    if tracked:
        rows = []
        for a in tracked:
            t = a["tracking"]
            fixes = ", ".join(f'<a href="{escape(f["url"])}">{escape(f["label"])}</a>' for f in t.get("fix") or [])
            rows.append(
                f'<tr><td class="m">{escape(_short(a))}</td><td>{fixes or "none yet"}</td>'
                f'<td>{escape(t.get("dev") or "")}</td><td>{escape(t.get("beta") or "")}</td>'
                f'<td>{escape(t.get("stable") or "")}</td><td>{escape(t.get("cve") or "")}</td></tr>'
            )
        out.append(
            '<div class="tbl"><table><thead><tr><th>Advisory</th><th>Fix</th><th>Dev</th><th>Beta</th>'
            f'<th>Stable</th><th>CVE</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
        )
    return "".join(out) + "</section>"


def _run_note(state: dict) -> str:
    """Render the run note and the alerts dismissed this run."""
    out = []
    if state.get("note"):
        out.append(f'<p class="sub">{escape(state["note"])}</p>')
    dismissed = state.get("dismissed_this_run") or []
    if dismissed:
        items = "".join(
            f'<li><a href="{REPO}/security/code-scanning/{escape(str(d["number"]))}">#{escape(str(d["number"]))}</a> '
            f'{escape(d.get("rule") or "")}: {escape(d["reason"])}</li>'
            for d in dismissed
        )
        out.append(f'<div class="sub">Dismissed this run as false positives:<ul class="tight">{items}</ul></div>')
    return f'<section><h2>This run</h2>{"".join(out)}</section>' if out else ""


if __name__ == "__main__":
    main()
