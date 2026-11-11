"""Render the issue triage board from the routine's state file.

Usage: python3 build.py <state.json> --full <board.html>
"""
import argparse
import hashlib
import json
import os
import re
import sys
from html import escape

FULL_MAX = 2_000_000
REPLY_ROWS = 14
REPLY_WRAP = 96
SUPPORT = "music-assistant/support"
COL_COLOR = {
    "info": "--info",
    "user": "--muted-foreground",
    "norepro": "--muted-foreground",
    "cantfix": "--warning",
    "pr": "--success",
    "dev": "--info",
    "merged": "--success",
}
TONES = {"ok", "warn", "info", "bad"}
# Badges worth showing on the board itself; the card body shows all of them.
KEEP = {"booked", "still broken", "backport?", "test asked", "tested", "auto held"}
KEEP_TONE = {"auto held": "warn", "still broken": "bad"}
# Board lanes from CONTRACT.md, in order: key, name, description, colour.
LANES = (
    ("reply", "Needs reply", "A reply to the reporter waits for you.", "--warning"),
    ("decision", "Needs decision", "Input, a design call, a merge or a nudge only you can give.", "--info"),
    ("progress", "In progress", "A fix thread, our own open PR or a local fix is moving.", "--success"),
    ("team", "Waiting on teammate or release", "Fix merged or on dev, or a teammate has the move.", "--muted-foreground"),
    ("reporter", "Waiting on reporter", "We spoke last: a test or info ask is out.", "--muted-foreground"),
)
# Sub-groups inside lanes 1 and 2, in order: ask value, sub-header.
ASKS = (
    ("reply-test", "Test ask"),
    ("reply-info", "Info ask"),
    ("reply-answer", "Answer"),
    ("input", "Input"),
    ("design", "Design"),
    ("merge", "Merge and release"),
    ("nudge", "Nudge"),
)
LAUNCH_COLS = {"cantfix", "norepro"}
REF = re.compile(
    r"(https://github\.com/[\w.\-/#]+|\b(?:home-assistant/core|music-assistant/[\w-]+|server|frontend|models"
    r"|client|aioslimproto|support)#\d+)"
)
BOLD = re.compile(r"\*\*(.+?)\*\*")

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
code, .mono { font-family: var(--font-mono); font-size: .9em; }
.wrap { display: flex; flex-direction: column; gap: 20px; padding: 4px 0 12px; }
h1 { font-size: 18px; font-weight: 600; margin: 0; }
h2 { font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted-foreground); margin: 0 0 8px; font-weight: 600; }
.sub { color: var(--muted-foreground); margin: 2px 0 0; font-size: 13px; }
.tools { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.tools input[type=search] { flex: 1 1 240px; min-width: 0; padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius); background: transparent; color: var(--foreground); font: inherit; }
.tools label { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; color: var(--muted-foreground); }
.cols { display: grid; grid-template-columns: repeat(5, minmax(220px, 1fr)); gap: 8px; align-items: start; overflow-x: auto; padding-bottom: 4px; }
.col { border: 1px solid var(--border); border-top: 3px solid var(--c); border-radius: var(--radius); padding: 8px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.col-head { display: flex; justify-content: space-between; align-items: baseline; gap: 6px; }
.col-head b { font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--muted-foreground); line-height: 1.3; }
.col-head .n { font: 500 12px var(--font-mono); color: var(--c); }
.col-desc { font-size: 11.5px; color: var(--muted-foreground); margin: 0; line-height: 1.35; }
.grp { display: flex; flex-direction: column; gap: 6px; }
.grp-h { display: flex; justify-content: space-between; font-size: 11px; font-weight: 600; color: var(--muted-foreground); border-bottom: 1px solid var(--border); padding: 4px 0 2px; }
.grp-h .gn { font: 500 11px var(--font-mono); }
.chip { display: grid; grid-template-columns: auto 1fr; column-gap: 6px; row-gap: 3px; padding: 5px 7px; border: 1px solid var(--border); border-left: 3px solid var(--c); border-radius: calc(var(--radius) - 2px); text-decoration: none; min-width: 0; }
.chip:hover { background: var(--muted); }
/* Cards that don't need Marvin recede so the ones that do stand out. */
.chip:not([data-p]) { opacity: .45; }
.chip:not([data-p]):hover, .chip:not([data-p]):focus-visible { opacity: 1; }
.num { font: 500 11.5px var(--font-mono); color: var(--muted-foreground); padding-top: 1px; }
.chip .t { font-size: 12.5px; line-height: 1.3; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.chip .tags { grid-column: 2; }
.tags, .badges { display: flex; flex-wrap: wrap; gap: 3px; }
.b { --t: var(--muted-foreground); font: 500 10px var(--font-mono); padding: 0 5px; border-radius: 3px; text-transform: uppercase; letter-spacing: .03em; line-height: 1.7; color: var(--t); background: color-mix(in srgb, var(--t) 14%, transparent); white-space: nowrap; }
.ok { --t: var(--success); } .warn { --t: var(--warning); } .info { --t: var(--info); } .bad { --t: var(--destructive); }
.badges .b { font: 500 11.5px var(--font-sans); text-transform: none; letter-spacing: 0; padding: 1px 8px; border-radius: 999px; }
.empty { font-size: 12px; color: var(--muted-foreground); }
dialog.card { width: min(920px, calc(100vw - 32px)); max-height: calc(100vh - 48px); padding: 0; border: 1px solid var(--border); border-top: 3px solid var(--c); border-radius: var(--radius); background: var(--background); color: var(--foreground); overflow: auto; }
dialog.card::backdrop { background: rgb(0 0 0 / .45); }
.dh { position: sticky; top: 0; z-index: 1; padding: 10px 14px; display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; background: var(--background); border-bottom: 1px solid var(--border); }
.dh .t { font-size: 15px; font-weight: 600; flex: 1 1 300px; }
.dh .gh { margin-left: auto; }
.body { padding: 12px 18px 18px; display: flex; flex-direction: column; gap: 10px; }
.body p { margin: 0; max-width: 90ch; }
.todo { border-left: 3px solid var(--destructive); background: color-mix(in srgb, var(--destructive) 10%, transparent); border-radius: calc(var(--radius) - 2px); padding: 8px 12px; }
.todo b { font-size: 11.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--destructive); display: block; }
.kv { display: grid; grid-template-columns: max-content 1fr; gap: 3px 14px; font-size: 13px; margin: 0; }
.kv dt { color: var(--muted-foreground); }
.kv dd { margin: 0; overflow-wrap: anywhere; }
.sec { border-top: 1px solid var(--border); padding-top: 6px; }
.sec > summary { cursor: pointer; font-size: 13px; font-weight: 500; color: var(--muted-foreground); }
.prose { white-space: pre-wrap; font: 13.5px/1.5 var(--font-sans); margin: 6px 0 0; overflow-wrap: anywhere; max-width: 100ch; }
.reply-text { white-space: pre-wrap; font: 12.5px/1.5 var(--font-mono); margin: 6px 0; padding: 10px; border: 1px solid var(--border); border-radius: calc(var(--radius) - 2px); overflow-wrap: anywhere; max-width: 100ch; }
textarea.reply-text { display: block; width: 100%; resize: vertical; background: transparent; color: inherit; }
.diff { margin: 6px 0 0; overflow: auto; font: 11.5px/1.5 var(--font-mono); padding: 6px 0; max-height: 480px; border: 1px solid var(--border); border-radius: calc(var(--radius) - 2px); }
.diff i { display: block; font-style: normal; padding: 0 10px; white-space: pre; }
.diff .a { background: color-mix(in srgb, var(--success) 14%, transparent); }
.diff .d { background: color-mix(in srgb, var(--destructive) 14%, transparent); }
.diff .h { color: var(--info); }
.diff .f { font-weight: 600; }
ul.tight { margin: 6px 0 0; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; max-width: 100ch; }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 12.5px; color: var(--muted-foreground); }
.row code { color: var(--foreground); }
button, a.btn { font: inherit; font-size: 12.5px; font-weight: 500; border-radius: calc(var(--radius) - 2px); padding: 3px 12px; cursor: pointer; border: 1px solid var(--border); background: transparent; color: var(--foreground); text-decoration: none; }
button:hover, a.btn:hover { background: var(--muted); }
button:disabled { opacity: .6; cursor: progress; }
.perr { color: var(--destructive); }
.hint { color: var(--success); }
a.posted { color: var(--success); border-color: color-mix(in srgb, var(--success) 50%, var(--border)); }
.bk { border-left: 3px solid var(--warning); background: color-mix(in srgb, var(--warning) 10%, transparent); border-radius: calc(var(--radius) - 2px); padding: 6px 12px; font-size: 13px; }
.tbl { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { font-size: 11.5px; letter-spacing: .05em; text-transform: uppercase; color: var(--muted-foreground); font-weight: 600; }
tr:last-child td { border-bottom: 0; }
tr.ms td { font-weight: 600; background: var(--muted); }
.lower { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 20px; }
.note { font-size: 12.5px; color: var(--muted-foreground); border-top: 1px solid var(--border); padding-top: 10px; margin: 0; }
.note code { color: var(--foreground); }
.hide { display: none !important; }
@media (max-width: 1180px) { .cols { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 760px) { .cols { grid-template-columns: repeat(2, minmax(0, 1fr)); } .lower { grid-template-columns: 1fr; } }
"""

JS = """
(function(){
  // report_server.py fills both placeholders when it serves the page.
  const TOKEN = "__ACTION_TOKEN__";
  let POSTED = {};
  try { POSTED = __POSTED__; } catch (e) {}
  function open(id){
    const d = document.getElementById(id);
    if (!d || d.tagName !== "DIALOG" || d.open) return;
    d.querySelectorAll("button[data-post]").forEach(restore);
    d.showModal(); d.scrollTop = 0;
    history.replaceState(null, "", "#" + id);
  }
  document.querySelectorAll("dialog.card").forEach(d => d.addEventListener("close", () => history.replaceState(null, "", location.pathname + location.search)));
  document.addEventListener("click", e => {
    const a = e.target.closest("a.chip");
    if (a) { e.preventDefault(); open(a.hash.slice(1)); return; }
    const r = e.target.closest("a[data-revert]");
    if (r) { e.preventDefault(); revert(r); return; }
    if (e.target.closest("[data-close]") || e.target.matches("dialog.card")) { e.target.closest("dialog").close(); return; }
    const p = e.target.closest("button[data-post]");
    if (p) { post(p); return; }
    const l = e.target.closest("button[data-cmd]");
    if (l) { launch(l); return; }
    const b = e.target.closest("button[data-copy]");
    if (b) copy(b);
  });
  async function launch(b){
    const h = b.parentElement.querySelector(".hint");
    try { await navigator.clipboard.writeText(b.dataset.cmd); h.textContent = "Copied, paste it in the triage thread"; }
    catch (e) { h.textContent = "Copy failed, type: " + b.dataset.cmd; }
    setTimeout(() => { h.textContent = ""; }, 4000);
  }
  async function copy(b){
    const src = document.getElementById(b.dataset.copy);
    try { await navigator.clipboard.writeText(src.value); b.textContent = "Copied"; }
    catch (e) { src.focus(); src.select(); b.textContent = "Selected, press copy"; }
    setTimeout(() => { b.textContent = "Copy"; }, 2000);
  }
  // Edits are kept per draft hash, so a redrafted reply starts from the new draft.
  function key(b){ return "issue-triage-edit:" + b.dataset.repo + "#" + b.dataset.n + ":" + b.dataset.hash; }
  function save(k, v){ try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} }
  function box(el){ return el.closest("details").querySelector("textarea"); }
  function mark(t){ t.closest("details").querySelector(".edited").classList.toggle("hide", t.readOnly || t.value === t.defaultValue); }
  function restore(b){
    const t = box(b);
    let v = null;
    try { v = localStorage.getItem(key(b)); } catch (e) {}
    if (v !== null) t.value = v;
    mark(t);
  }
  function revert(r){
    const t = box(r), b = t.closest("details").querySelector("button[data-post]");
    t.value = t.defaultValue;
    if (b) save(key(b), null);
    mark(t);
  }
  document.addEventListener("input", e => {
    const t = e.target;
    if (!t.matches("textarea.reply-text")) return;
    const b = t.closest("details").querySelector("button[data-post]");
    if (b) save(key(b), t.value === t.defaultValue ? null : t.value);
    mark(t);
  });
  function posted(b, url, body){
    const t = box(b);
    if (body) t.value = body;
    t.readOnly = true; mark(t);
    const a = document.createElement("a");
    a.className = "btn posted"; a.href = url; a.rel = "noopener"; a.textContent = "Posted";
    b.replaceWith(a);
  }
  async function post(b){
    const err = b.parentElement.querySelector(".perr");
    err.textContent = ""; b.disabled = true; b.textContent = "Posting";
    try {
      const r = await fetch("/api/issue-triage/post", {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-Action-Token": TOKEN},
        body: JSON.stringify({repo: b.dataset.repo, n: Number(b.dataset.n), discussion: b.dataset.discussion === "1", hash: b.dataset.hash, body: box(b).value}),
      });
      const j = await r.json().catch(() => ({error: "HTTP " + r.status}));
      if (j.ok) { save(key(b), null); posted(b, j.url); moved(b.dataset.repo + "#" + b.dataset.n); filter(); return; }
      err.textContent = j.error || "HTTP " + r.status;
    } catch (e) { err.textContent = "The report server did not answer: " + e.message; }
    b.disabled = false; b.textContent = "Post";
  }
  // A posted reply hands the move to the reporter, so the card leaves its ask lane at once.
  function moved(k){
    const a = [...document.querySelectorAll("a.chip[data-k]")].find(x => x.dataset.k === k);
    if (!a) return;
    delete a.dataset.p;
    document.querySelector('.col[data-lane="reporter"] .empty').after(a);
  }
  const q = document.getElementById("q"), act = document.getElementById("act");
  function filter(){
    const term = q.value.trim().toLowerCase(), only = act.checked;
    document.querySelectorAll("a.chip").forEach(a => {
      const text = (a.textContent + " " + a.dataset.a).toLowerCase();
      a.classList.toggle("hide", (term && !text.includes(term)) || (only && !a.dataset.p));
    });
    document.querySelectorAll(".grp").forEach(g => {
      const n = g.querySelectorAll("a.chip:not(.hide)").length;
      g.querySelector(".gn").textContent = n;
      g.classList.toggle("hide", n === 0);
    });
    document.querySelectorAll(".col").forEach(col => {
      const n = col.querySelectorAll("a.chip:not(.hide)").length;
      col.querySelector(".n").textContent = n;
      col.querySelector(".empty").classList.toggle("hide", n > 0);
    });
  }
  q.addEventListener("input", filter);
  act.addEventListener("change", filter);
  document.querySelectorAll("button[data-post]").forEach(b => {
    const k = b.dataset.repo + "#" + b.dataset.n, p = POSTED[k];
    if (p && p.hash === b.dataset.hash) { posted(b, p.url, p.body); moved(k); }
  });
  filter();
  // Chat links use ?q=<n>#c-<n>: filter the lanes to the issue and open its card.
  const term = new URLSearchParams(location.search).get("q");
  if (term) { q.value = term; filter(); }
  if (location.hash) open(location.hash.slice(1));
  window.addEventListener("hashchange", () => open(location.hash.slice(1)));
})();
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the issue triage board.")
    parser.add_argument("state")
    parser.add_argument("--full", required=True, help="write the complete board here")
    args = parser.parse_args()
    with open(args.state) as f:
        state = json.load(f)
    _write(args.full, render_full(state), FULL_MAX)


def render_full(state: dict) -> str:
    """Render the complete board with every card in full."""
    names = {key: name for key, name, _ in state["columns"]}
    headers = dict(ASKS)
    cards = sorted(state["cards"], key=_last_at, reverse=True)
    cards.sort(key=_urgency)
    lanes, dialogs = [], []
    for lane, name, desc, lane_color in LANES:
        in_lane = [c for c in cards if _lane(c) == lane]
        if lane in ("reply", "decision"):
            chips = "".join(
                f'<div class="grp"><div class="grp-h"><span>{escape(headers.get(ask, ask))}</span>'
                f'<span class="gn">{len(group)}</span></div>' + "".join(_chip(c, names) for c in group) + "</div>"
                for ask, group in _ask_groups(in_lane)
            )
        else:
            chips = "".join(_chip(c, names) for c in in_lane)
        empty = '<div class="empty' + (" hide" if in_lane else "") + '">Nothing here</div>'
        lanes.append(
            f'<section class="col" data-lane="{lane}" style="--c:var({lane_color})"><div class="col-head"><b>{escape(name)}</b>'
            f'<span class="n">{len(in_lane)}</span></div><p class="col-desc">{escape(desc)}</p>{empty}{chips}</section>'
        )
        dialogs += [_card(c, names, lane) for c in in_lane]
    parts = [
        '<header><h1>Support issue triage</h1>'
        f'<p class="sub">Last run {escape(state.get("last_run") or "never")}</p></header>',
        '<div class="tools"><input id="q" type="search" placeholder="Filter by issue number, title or area" '
        'aria-label="Filter issues"><label><input type="checkbox" id="act"> Only cards that need attention</label></div>',
        '<div class="cols">' + "".join(lanes) + "</div>",
        _release(state, {c["n"] for c in cards if _repo(c) == SUPPORT}),
        '<div class="lower"><section><h2>Design calls for you</h2><div class="tbl"><table><thead><tr><th>Issue</th>'
        "<th>Decision</th><th>Recommendation</th></tr></thead><tbody>"
        + "".join("<tr>" + "".join(f"<td>{_rich(x)}</td>" for x in r) + "</tr>" for r in state.get("design", []))
        + '</tbody></table></div></section><section><h2>Follow-ups spotted</h2><ul class="tight">'
        + "".join(f"<li>{_rich(x)}</li>" for x in state.get("followups", []))
        + "</ul></section></div>",
        '<p class="note">Reply in this thread to act on a card: <code>reply &lt;n&gt;</code> posts the draft, '
        "<code>edit &lt;n&gt; &lt;what to change&gt;</code> redrafts it, <code>book &lt;n&gt;</code> applies the "
        "pending labels and milestone, <code>answer &lt;pr&gt;</code> posts the drafted review replies, "
        "<code>fix &lt;n&gt;</code> starts a fix thread, <code>done &lt;n&gt;</code> clears the action, "
        "<code>drop &lt;n&gt;</code> takes the card off the board.</p>",
    ]
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Support issue triage</title><base target="_blank"><style>'
        + CSS
        + '</style></head><body><div class="wrap">'
        + "".join(parts)
        + "</div>"
        + "".join(dialogs)
        + "<script>"
        + JS
        + "</script></body></html>"
    )


def _write(path: str, html: str, limit: int) -> None:
    """Write a page after checking it against its size limit."""
    if len(html) > limit:
        sys.exit(f"{path}: {len(html)} characters, over the {limit} limit")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        f.write(html)
    print(f"{path}: {len(html)} characters")


def _kind(b: list) -> str:
    """Badge kind, falling back to its label."""
    return b[2] if len(b) > 2 and b[2] else b[1]


def _gh(c: dict, key: str) -> bool:
    """Read a flag from the card's GitHub snapshot."""
    return bool((c.get("gh") or {}).get(key))


def _pending(c: dict) -> bool:
    """Whether the card waits on Marvin."""
    return bool(c.get("ask"))


def _lane(c: dict) -> str:
    """Board lane the card sits in, derived as CONTRACT.md describes."""
    ask = c.get("ask")
    if ask:
        return "reply" if ask.startswith("reply-") else "decision"
    thread = c.get("fix_thread")
    if (thread and not thread.get("done")) or (_own_pr_open(c) and not _test_asked(c)) or _local_fix(c):
        return "progress"
    if c.get("waiting_on") == "reporter":
        return "reporter"
    if c["col"] in ("merged", "dev") or c.get("waiting_on") == "team":
        return "team"
    return "reporter"


def _ask_groups(cards: list) -> list:
    """Cards split into (ask, cards) sub-groups in ASKS order, empty groups left out."""
    order = [ask for ask, _ in ASKS]
    asks = sorted({c["ask"] for c in cards}, key=lambda a: order.index(a) if a in order else len(order))
    return [(ask, [c for c in cards if c["ask"] == ask]) for ask in asks]


def _own_pr_open(c: dict) -> bool:
    """Whether our own PR for the card is open; cards without sync data fall back to the PR outcome."""
    prs = (c.get("sync") or {}).get("pr")
    if prs is not None:
        return any(p.get("own") and p.get("state") == "OPEN" for p in prs)
    return c["col"] == "pr" and _gh(c, "pr_open")


def _local_fix(c: dict) -> bool:
    """Whether a fix sits on a local branch that isn't pushed yet."""
    if any(_kind(b).startswith("local fix") for b in c["badges"]):
        return True
    return c["col"] == "pr" and not _gh(c, "pr_open") and not c.get("prs")


def _test_asked(c: dict) -> bool:
    """Whether the reporter was asked to test a fix."""
    return bool((c.get("sync") or {}).get("test_ask")) or any(_kind(b) == "test asked" for b in c["badges"])


def _in_review(c: dict) -> bool:
    """Whether a PR is open and nobody waits on a tester."""
    return not _pending(c) and _gh(c, "pr_open") and not _test_asked(c)


def _waiting(c: dict) -> bool:
    """Whether the card waits on the reporter."""
    return not _pending(c) and not _in_review(c) and (_gh(c, "team") or _test_asked(c))


def _urgency(c: dict) -> int:
    """Lower means it needs Marvin sooner."""
    if _pending(c):
        return 0 if any(b[0] == "bad" for b in c["badges"]) else 1
    return 2 if _in_review(c) else 4 if _waiting(c) else 3


def _last_at(c: dict) -> str:
    """Time of the last activity on the issue."""
    return (c.get("gh") or {}).get("at") or (c.get("since") or "").replace(" ", "T")


def _repo(c: dict) -> str:
    """Repo the card's issue lives in."""
    return c.get("repo") or SUPPORT


def _ref(c: dict) -> str:
    """Short reference used on the board and in replies."""
    repo = _repo(c)
    if repo == SUPPORT:
        return f"#{c['n']}"
    return ("core" if repo == "home-assistant/core" else repo.split("/")[-1]) + f"#{c['n']}"


def _anchor(c: dict) -> str:
    """Element id of the card's detail block."""
    return "c-" + re.sub(r"[^a-z0-9]+", "-", _ref(c).lower()).strip("-")


def _issue_url(c: dict) -> str:
    """GitHub URL of the card's issue or discussion."""
    return f"https://github.com/{_repo(c)}/{'discussions' if c.get('discussion') else 'issues'}/{c['n']}"


def _tags(c: dict, col_name: str) -> str:
    """Outcome and status tags shown on the chip and the card summary."""
    tags = [("", col_name)]
    if c["col"] == "pr" and _gh(c, "pr_open"):
        tags.append(("ok", "draft PR" if _gh(c, "pr_draft") else "PR open"))
        if not _test_asked(c) and not any(_kind(b) == "tested" for b in c["badges"]):
            tags.append(("", "no test ask"))
    if _local_fix(c):
        tags.append(("warn", "local fix"))
    tags += [(KEEP_TONE.get(_kind(b), b[0]), _kind(b)) for b in c["badges"] if _kind(b) in KEEP]
    return "".join(_badge(t, x) for t, x in tags)


def _search_attrs(c: dict) -> str:
    """Data attributes the filter box reads next to the chip text."""
    return f'data-a="{escape(c.get("area", ""))}"' + (' data-p="1"' if _pending(c) else "")


def _chip(c: dict, names: dict) -> str:
    """Render one card on the board lanes."""
    color = COL_COLOR.get(c["col"], "--muted-foreground")
    return (
        f'<a class="chip" href="#{_anchor(c)}" target="_self" {_search_attrs(c)} data-k="{escape(_repo(c))}#{c["n"]}" '
        f'style="--c:var({color})"><span class="num">{escape(_ref(c))}</span><span class="t">'
        f'{escape(c["title"], quote=False)}</span><span class="tags">{_tags(c, names.get(c["col"], c["col"]))}</span></a>'
    )


def _card(c: dict, names: dict, lane: str) -> str:
    """Render one card's detail dialog."""
    ref = _ref(c)
    col_name = names.get(c["col"], c["col"])
    color = COL_COLOR.get(c["col"], "--muted-foreground")
    out = []
    if _pending(c):
        action = c.get("action") or _todo_fallback(c)
        out.append(f'<div class="todo"><b>Needs your action</b><p>{_rich(action)}</p></div>')
    if lane == "decision" or (lane == "reply" and c["col"] in LAUNCH_COLS):
        cmd = escape(ref.lstrip("#"))
        out.append(
            '<div class="row">Start a thread:'
            + "".join(f'<button type="button" data-cmd="{k} {cmd}">{k.title()}</button>' for k in ("discuss", "fix", "repro"))
            + '<span class="hint"></span></div>'
        )
    badges = _badge("", col_name) + "".join(_badge(b[0], b[1]) for b in c["badges"])
    out.append(f'<div class="badges">{badges}</div>')
    if c.get("summary"):
        out.append(f"<p>{_rich(c['summary'])}</p>")
    kv = [("Issue", f'<a href="{_issue_url(c)}">{escape(_repo(c))}{escape(ref[ref.index("#"):])}</a>')]
    if c.get("area"):
        kv.append(("Area", escape(c["area"], quote=False)))
    if c.get("prs"):
        kv.append(("PR", ", ".join(
            f'<a href="{escape(p["url"])}">{escape(p["label"], quote=False)}</a>'
            for p in c["prs"]
        )))
    if c.get("branch"):
        kv.append(("Branch", f"<code>{escape(c['branch'], quote=False)}</code>"))
    if c.get("fix_thread"):
        kv.append(("Fix thread", escape(c["fix_thread"].get("title") or c["fix_thread"].get("id", ""), quote=False)))
    if c.get("last"):
        kv.append(("Last comment", escape(c["last"], quote=False)))
    kv.append(("First seen", escape(c.get("since", ""), quote=False)))
    out.append('<dl class="kv">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in kv) + "</dl>")
    for bk in c.get("bookkeeping") or []:
        if not bk.get("done"):
            out.append(f'<div class="bk">{_rich(bk["text"])} <code>book {escape(ref.lstrip("#"))}</code></div>')
    if c.get("reply"):
        rid = "r-" + _anchor(c)
        title = "Draft reply: ask the reporter to test" if c.get("prs") else "Draft reply to the reporter"
        out.append(
            # The newline after <textarea> is dropped by the parser, so a draft's own leading newline survives.
            f'<details class="sec" open><summary>{title}</summary><textarea class="reply-text" id="{rid}" '
            f'rows="{_reply_rows(c["reply"])}" aria-label="{title}">\n{escape(c["reply"], quote=False)}</textarea>'
            f'<div class="row"><button type="button" data-copy="{rid}">Copy</button>{_post_button(c)}'
            '<span class="edited hide"><span class="b warn">Edited</span> <a href="#" target="_self" data-revert>Revert</a></span>'
            f'<code>reply {escape(ref.lstrip("#"))}</code><span class="perr"></span></div></details>'
        )
    for rr in c.get("review_replies") or []:
        out.append(
            f'<details class="sec"><summary>Review reply on {escape(rr.get("label") or rr["repo"] + "#" + str(rr["pr"]))}'
            f'</summary><pre class="reply-text">{escape(rr["body"], quote=False)}</pre><div class="row">'
            f'<code>answer {rr["pr"]}</code></div></details>'
        )
    notes = c.get("notes") or []
    if notes:
        out.append(
            f'<details class="sec"><summary>Run notes ({len(notes)})</summary><ul class="tight">'
            + "".join(f"<li>{_rich(n)}</li>" for n in notes) + "</ul></details>"
        )
    for field, title, is_open in (("fix", "What the fix changes", True), ("checked", "How it was checked", False), ("plan", "Analysis and options", False)):
        if c.get(field):
            out.append(
                f'<details class="sec"{" open" if is_open else ""}><summary>{title}</summary>'
                f'<div class="prose">{_rich(c[field])}</div></details>'
            )
    if c.get("diff"):
        out.append(f'<details class="sec"><summary>Diff</summary>{_diff(c["diff"])}</details>')
    head = (
        f'<div class="dh"><span class="num">{escape(ref)}</span><span class="t">{escape(c["title"], quote=False)}</span>'
        f'<span class="tags">{_tags(c, col_name)}</span><a class="btn gh" href="{_issue_url(c)}" rel="noopener">GitHub</a>'
        '<button type="button" data-close aria-label="Close">Close</button></div>'
    )
    return f'<dialog class="card" id="{_anchor(c)}" style="--c:var({color})">{head}<div class="body">{"".join(out)}</div></dialog>'


def _post_button(c: dict) -> str:
    """Post button for the draft reply; the page script swaps it for a link once posted."""
    digest = hashlib.sha256(c["reply"].encode("utf-8")).hexdigest()[:16]
    return (
        f'<button type="button" data-post data-repo="{escape(_repo(c))}" data-n="{c["n"]}" '
        f'data-discussion="{1 if c.get("discussion") else 0}" data-hash="{digest}">Post</button>'
    )


def _reply_rows(text: str) -> int:
    """Textarea height that fits the draft, capped at REPLY_ROWS."""
    return min(REPLY_ROWS, sum(len(line) // REPLY_WRAP + 1 for line in text.split("\n")))


def _badge(tone: str, text: str) -> str:
    """Render one badge."""
    cls = f"b {tone}" if tone in TONES else "b"
    return f'<span class="{cls}">{escape(text, quote=False)}</span>'


def _todo_fallback(c: dict) -> str:
    """Generic action text when the card has none."""
    if any(not b.get("done") for b in c.get("bookkeeping") or []):
        return "Apply the pending labels or milestone."
    if c.get("reply"):
        return "Review and post the draft reply."
    return "See the badges and notes on the card."


def _release(state: dict, on_board: set) -> str:
    """Render the release table per milestone, with the release title line above it."""
    title = (state.get("release") or {}).get("title")
    table = state.get("release_table") or {}
    if not (title or table):
        return ""
    stable = {True: ("ok", "yes"), False: ("bad", "no")}
    rows = []
    for ms, issues in table.items():
        rows.append(f'<tr class="ms"><td colspan="4">{escape(ms, quote=False)}</td></tr>')
        for i in issues:
            n = i["n"]
            link = (f'<a href="#c-{n}" target="_self">#{n}</a>' if n in on_board
                    else f'<a href="https://github.com/{SUPPORT}/issues/{n}">#{n}</a>')
            prs = ", ".join(f'<a href="{escape(_ref_url(p))}">{escape(p, quote=False)}</a>' for p in i.get("prs") or [])
            rows.append(
                f'<tr><td class="mono">{link}</td><td>{escape(i.get("title") or "", quote=False)}</td><td>{prs}</td>'
                f"<td>{_badge(*stable.get(i.get('on_stable'), ('', 'unknown')))}</td></tr>"
            )
    body = (
        '<div class="tbl"><table><thead><tr><th>Issue</th><th>Title</th><th>Fix PRs</th><th>On stable</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>' if table else ""
    )
    return "<section><h2>Release check</h2>" + (f'<p class="sub">{_rich(title)}</p>' if title else "") + body + "</section>"


def _diff(text: str) -> str:
    """Render a unified diff with line colouring."""
    lines = []
    for line in text.split("\n"):
        if line.startswith(("diff --git", "+++", "---", "index ")):
            cls = "f"
        elif line.startswith("@@"):
            cls = "h"
        elif line.startswith("+"):
            cls = "a"
        elif line.startswith("-"):
            cls = "d"
        else:
            cls = ""
        lines.append(f'<i class="{cls}">' if cls else "<i>")
        lines.append(escape(line, quote=False) or " ")
        lines.append("</i>")
    return '<pre class="diff">' + "".join(lines) + "</pre>"


def _ref_url(ref: str) -> str:
    """GitHub URL for a URL or repo#n reference."""
    if ref.startswith("https://"):
        return ref
    repo, num = ref.split("#")
    full = repo if "/" in repo else "music-assistant/" + repo
    kind = "issues" if full in (SUPPORT, "home-assistant/core") else "pull"
    return f"https://github.com/{full}/{kind}/{num}"


def _rich(text: str) -> str:
    """Escape text, link GitHub references and render **bold**."""
    out, last = [], 0
    for m in REF.finditer(text):
        out.append(_bold(escape(text[last:m.start()], quote=False)))
        out.append(f'<a href="{escape(_ref_url(m.group(0)))}">{escape(m.group(0), quote=False)}</a>')
        last = m.end()
    out.append(_bold(escape(text[last:], quote=False)))
    return "".join(out)


def _bold(text: str) -> str:
    """Turn **x** into bold."""
    return BOLD.sub(r"<b>\1</b>", text)


if __name__ == "__main__":
    main()
