"""Render the security inbox report page from the routine's state file.

Usage: python3 build.py <state.json> <out.html>
"""
import json
import sys
from html import escape

REPO = "https://github.com/music-assistant/server"
ADV_COLS = [
    ("draft", "Draft", "New reports to accept or close"),
    ("open", "Open", "Accepted, needs a fix or publishing"),
    ("fp", "False positive", "Recommended to close"),
]
CS_COLS = [
    ("new", "Not picked up", "No fix or decision yet"),
    ("pr", "PR with fixes in draft", "Fix PR open as draft"),
    ("unsure", "Unsure", "Assessed, look before it gets dismissed or fixed"),
]
BADGES = {
    "needs_attention": ("att", "Needs attention"),
    "waiting_for_user": ("wait", "Waiting for user"),
    "waiting_for_cve": ("cve", "Waiting for CVE"),
}
SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: var(--font-sans); color: var(--foreground); margin: 0; font-size: 13px; line-height: 1.5; }
a { color: var(--info, var(--accent)); }
code { font-family: var(--font-mono); font-size: 12px; overflow-wrap: anywhere; }
.wrap { display: flex; flex-direction: column; gap: 22px; padding: 4px 0 8px; }
header { display: flex; flex-direction: column; gap: 8px; }
h1 { font-size: 16px; font-weight: 600; margin: 0; }
.sub { color: var(--muted-foreground); margin: 0; }
.tallies { display: flex; flex-wrap: wrap; gap: 8px; }
.tally { display: flex; align-items: baseline; gap: 6px; padding: 5px 10px; border: 1px solid var(--border); border-left-width: 3px; border-radius: var(--radius); font-variant-numeric: tabular-nums; }
.tally b { font-size: 16px; }
.tally.att { border-left-color: var(--destructive); }
.tally.wait { border-left-color: var(--warning); }
.tally.cve { border-left-color: var(--info); }
.tally.fp { border-left-color: var(--muted-foreground); }
section { display: flex; flex-direction: column; gap: 8px; }
h2 { font-size: 14px; font-weight: 600; margin: 0; display: flex; gap: 10px; align-items: baseline; }
h2 a { font-weight: 400; font-size: 12px; }
.matrix { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; align-items: start; }
@media (max-width: 520px) { .matrix { grid-template-columns: 1fr; } }
.col { border: 1px solid var(--border); border-radius: var(--radius); padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.colhead { display: flex; flex-direction: column; padding: 0 2px 2px; }
.colhead .k { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: var(--muted-foreground); }
.colhead .h { font-size: 11px; color: var(--muted-foreground); }
.empty { color: var(--muted-foreground); font-style: italic; padding: 0 2px; }
.tile, .pane { border: 1px solid var(--border); border-left: 3px solid var(--border); border-radius: var(--radius); background: var(--card); color: var(--card-foreground); }
.tile { font: inherit; text-align: left; width: 100%; cursor: pointer; padding: 8px 10px; display: flex; flex-direction: column; gap: 4px; }
.tile:hover { border-color: var(--foreground); }
.tile.sel { outline: 2px solid var(--ring); outline-offset: 1px; }
.tile.att, .pane.att { border-left-color: var(--destructive); }
.tile.wait, .pane.wait { border-left-color: var(--warning); }
.tile.fp, .pane.fp { border-left-color: var(--muted-foreground); }
.tile.ok, .pane.ok { border-left-color: var(--success); }
.pane[hidden] { display: none; }
.panehead { padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; }
.cid { font-family: var(--font-mono); font-size: 11.5px; color: var(--muted-foreground); }
.ttl { font-size: 13px; overflow-wrap: anywhere; }
.badges { display: flex; flex-wrap: wrap; gap: 4px; }
.tag { font-family: var(--font-mono); font-size: 10.5px; padding: 1px 6px; border-radius: 999px; border: 1px solid var(--border); color: var(--muted-foreground); text-transform: uppercase; letter-spacing: .03em; }
.tag.att { border-color: var(--destructive); color: var(--destructive); font-weight: 600; }
.tag.wait { border-color: var(--warning); color: var(--warning); }
.tag.cve { border-color: var(--info); color: var(--info); }
.tag.yes { border-color: var(--success); color: var(--success); }
.tag.no { border-color: var(--muted-foreground); }
.tag.sev { color: var(--foreground); }
.body { padding: 4px 12px 14px; display: flex; flex-direction: column; gap: 14px; border-top: 1px solid var(--border); }
.body h4 { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted-foreground); margin: 10px 0 4px; }
.body p { margin: 0 0 6px; }
.by { color: var(--muted-foreground); font-size: 12px; display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 10px; }
.attn { border: 1px solid var(--destructive); border-left-width: 4px; border-radius: var(--radius); padding: 8px 12px; }
.attn h4 { color: var(--destructive); margin-top: 0; }
.attn p { margin: 0; }
details.older > summary { cursor: pointer; color: var(--muted-foreground); font-size: 12px; margin: 2px 0 6px; }
ul.plain { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 4px; }
.tw { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
th, td { border-bottom: 1px solid var(--border); padding: 5px 8px; text-align: left; vertical-align: top; }
th { font-size: 11px; font-weight: 600; color: var(--muted-foreground); text-transform: uppercase; letter-spacing: .05em; }
td.m { font-family: var(--font-mono); white-space: nowrap; }
td.chg { color: var(--destructive); font-weight: 600; }
.vec { font-family: var(--font-mono); font-size: 11.5px; background: var(--code-background, var(--muted)); color: var(--code-foreground, var(--foreground)); padding: 6px 8px; border-radius: var(--radius); overflow-wrap: anywhere; margin-top: 6px; }
pre { font-family: var(--font-mono); font-size: 12px; line-height: 1.5; background: var(--code-background, var(--muted)); color: var(--code-foreground, var(--foreground)); padding: 10px 12px; border-radius: var(--radius); white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; user-select: all; }
.row { display: flex; gap: 8px; align-items: center; margin-top: 6px; flex-wrap: wrap; }
.btn { font: 500 12px var(--font-sans); padding: 4px 10px; border-radius: var(--radius); border: 1px solid var(--border); background: transparent; color: var(--foreground); cursor: pointer; }
.btn:hover { border-color: var(--foreground); }
.hint { font-size: 12px; color: var(--muted-foreground); }
.hint code { color: var(--foreground); }
dl.rel { display: grid; grid-template-columns: max-content 1fr; gap: 3px 14px; margin: 0; }
dl.rel dt { color: var(--muted-foreground); }
dl.rel dd { margin: 0; }
.note { color: var(--muted-foreground); margin: 0; }
.footer { font-size: 12px; color: var(--muted-foreground); border-top: 1px solid var(--border); padding-top: 10px; }
.footer code { color: var(--foreground); }
"""

COPY_JS = """
document.querySelectorAll("button[data-pane]").forEach(function (t) {
  t.addEventListener("click", function () {
    var pane = document.getElementById(t.dataset.pane);
    var board = t.closest("section");
    var wasOpen = !pane.hidden;
    board.querySelectorAll(".pane").forEach(function (p) { p.hidden = true; });
    board.querySelectorAll(".tile").forEach(function (b) { b.classList.remove("sel"); });
    if (!wasOpen) { pane.hidden = false; t.classList.add("sel"); }
  });
});
document.querySelectorAll("button[data-copy]").forEach(function (b) {
  b.addEventListener("click", function () {
    var pre = document.getElementById(b.dataset.copy);
    var done = function () { b.textContent = "Copied"; };
    if (navigator.clipboard) {
      navigator.clipboard.writeText(pre.textContent).then(done, function () { select(pre); });
    } else { select(pre); }
  });
});
function select(el) {
  var r = document.createRange(); r.selectNodeContents(el);
  var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
}
"""


def main() -> None:
    src, out = sys.argv[1], sys.argv[2]
    with open(src) as f:
        state = json.load(f)
    advs = state.get("advisories", [])
    alerts = state.get("code_scanning", [])
    parts = [
        _header(state, advs, alerts),
        _board("Security advisories", f"{REPO}/security/advisories", ADV_COLS, advs),
        _board("Code scanning", f"{REPO}/security/code-scanning", CS_COLS, alerts),
        _tracking(state, advs),
        _run_note(state),
        '<div class="footer">Reply <code>fix &lt;id&gt;</code> to start a fix session, '
        "<code>close &lt;ghsa&gt;</code> to close an advisory as a false positive, "
        "<code>dismiss cs-&lt;n&gt;</code> to dismiss an alert, "
        "<code>draft &lt;id&gt;</code> to get a draft reply in chat.</div>",
    ]
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Security inbox</title><style>"
        + CSS
        + '</style></head><body><div class="wrap">'
        + "".join(p for p in parts if p)
        + "</div><script>"
        + COPY_JS
        + "</script></body></html>"
    )
    with open(out, "w") as f:
        f.write(html)


def _badges(c: dict) -> list:
    """Return the card's badge keys."""
    return c.get("badges") or []


def _tone(c: dict) -> str:
    """Return the card's accent class."""
    b = _badges(c)
    if "needs_attention" in b:
        return "att"
    if "waiting_for_user" in b:
        return "wait"
    if c.get("column") == "fp":
        return "fp"
    return "ok"


def _sort_key(c: dict) -> tuple:
    """Sort attention first, waiting on the reporter last, then by severity."""
    b = _badges(c)
    rank = 0 if "needs_attention" in b else 2 if "waiting_for_user" in b else 1
    return (rank, SEV_RANK.get(c.get("severity") or "", 9))


def _short(c: dict) -> str:
    """Return the id Marvin types in a reply."""
    cid = c["id"]
    return cid.split("-")[1] if cid.startswith("GHSA-") else cid


def _header(state: dict, advs: list, alerts: list) -> str:
    """Render the title, subtitle and tallies."""
    cards = advs + alerts

    def n(key: str) -> int:
        return sum(1 for c in cards if key in _badges(c))

    fp = sum(1 for c in advs if c.get("column") == "fp")
    sub = (
        f"{len(advs)} unpublished advisories and {len(alerts)} open code scanning alerts on "
        f"music-assistant/server. Last run {escape(state.get('last_run') or 'never')}"
        f"{', run ' + str(state['run_count']) if state.get('run_count') else ''}"
        f", dev @ <code>{escape(state.get('dev') or '?')}</code>."
    )
    tallies = (
        f'<span class="tally att"><b>{n("needs_attention")}</b> need you</span>'
        f'<span class="tally wait"><b>{n("waiting_for_user")}</b> waiting on reporter</span>'
        f'<span class="tally cve"><b>{n("waiting_for_cve")}</b> waiting for CVE</span>'
        f'<span class="tally fp"><b>{fp}</b> false positive</span>'
    )
    return (
        f'<header><h1>Music Assistant security inbox</h1><p class="sub">{sub}</p>'
        f'<div class="tallies">{tallies}</div></header>'
    )


def _board(title: str, url: str, cols: list, cards: list) -> str:
    """Render one board as a column matrix; a picked card opens full width below it."""
    head = f'<h2>{escape(title)} <a href="{url}" target="_blank" rel="noopener">GitHub</a></h2>'
    columns, panes = [], []
    for key, label, hint in cols:
        items = sorted((c for c in cards if c.get("column") == key), key=_sort_key)
        tiles = "".join(_tile(c) for c in items) or '<div class="empty">Nothing here</div>'
        columns.append(
            f'<div class="col"><div class="colhead"><span class="k">{label} &middot; {len(items)}</span>'
            f'<span class="h">{hint}</span></div>{tiles}</div>'
        )
        panes.extend(_pane(c) for c in items)
    return f'<section>{head}<div class="matrix">{"".join(columns)}</div>{"".join(panes)}</section>'


def _tile(c: dict) -> str:
    """Render the card's tile inside its column."""
    return (
        f'<button type="button" class="tile {_tone(c)}" data-pane="{escape(_pane_id(c))}">'
        f'<span class="cid">{escape(c.get("label") or c["id"])}</span>'
        f'<span class="ttl">{escape(c["title"])}</span><span class="badges">{_tags(c)}</span></button>'
    )


def _pane(c: dict) -> str:
    """Render the card's full-width details, hidden until its tile is picked."""
    return (
        f'<div class="pane {_tone(c)}" id="{escape(_pane_id(c))}" hidden><div class="panehead">'
        f'<span class="cid">{escape(c.get("label") or c["id"])}</span>'
        f'<span class="ttl">{escape(c["title"])}</span><span class="badges">{_tags(c)}</span></div>'
        f'<div class="body">{_card_body(c)}</div></div>'
    )


def _pane_id(c: dict) -> str:
    """Return the DOM id of the card's pane."""
    return f"pane-{c['id']}"


def _tags(c: dict) -> str:
    """Render the severity, accept advice and badge tags."""
    tags = []
    if c.get("severity"):
        tags.append(f'<span class="tag sev">{escape(c["severity"])}</span>')
    if c.get("should_accept") is not None:
        yes = bool(c["should_accept"])
        tags.append(f'<span class="tag {"yes" if yes else "no"}">Should accept: {"yes" if yes else "no"}</span>')
    for b in _badges(c):
        if b in BADGES:
            tags.append(f'<span class="tag {BADGES[b][0]}">{BADGES[b][1]}</span>')
    return "".join(tags)


def _card_body(c: dict) -> str:
    """Render the expanded card contents."""
    out = []
    by = [f'<a href="{escape(c["url"])}" target="_blank" rel="noopener">{escape(c.get("label") or c["id"])}</a>']
    for key, label in (("severity", "Severity"), ("rule", "Rule"), ("path", "At"), ("reporter", "Reported by"), ("opened", "Opened"), ("checked", "Checked")):
        if c.get(key):
            by.append(f"<span>{label} {escape(str(c[key]))}</span>")
    if c.get("fix_thread"):
        by.append(f'<span>Fix thread <code>{escape(c["fix_thread"])}</code></span>')
    out.append(f'<div class="by">{"".join(by)}</div>')
    if "needs_attention" in _badges(c) and c.get("action"):
        out.append(f'<div class="attn"><h4>Your move</h4><p>{escape(c["action"])}</p></div>')
    status = c.get("status") or []
    if status:
        block = f"<div><h4>Status</h4><p>{status[0]}</p>"
        if len(status) > 1:
            older = "".join(f"<p>{s}</p>" for s in status[1:])
            block += f'<details class="older"><summary>Earlier ({len(status) - 1})</summary>{older}</details>'
        out.append(block + "</div>")
    if c.get("facts"):
        out.append('<div><h4>Details</h4><ul class="plain">' + "".join(f"<li>{f}</li>" for f in c["facts"]) + "</ul></div>")
    if c.get("cvss"):
        out.append(_cvss(c["cvss"]))
    if c.get("pr"):
        out.append(
            f'<div><h4>Fix PR</h4><p><a href="{escape(c["pr"]["url"])}" target="_blank" rel="noopener">'
            f'{escape(c["pr"]["label"])}</a></p></div>'
        )
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
    """Render a pre block with a copy button."""
    pid = f"{kind}-{c['id']}"
    return (
        f'<div><h4>{title}</h4><pre id="{escape(pid)}">{escape(text)}</pre>'
        f'<div class="row"><button class="btn" data-copy="{escape(pid)}">Copy</button></div></div>'
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
    return f'<div class="hint">Reply {", ".join(verbs)}</div>' if verbs else ""


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
        '<div class="tw"><table><thead><tr><th>Metric</th><th>On advisory</th><th>Suggested</th><th>Why</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div><div class="vec">{vec}</div></div>'
    )


def _tracking(state: dict, advs: list) -> str:
    """Render the release lines and the per-advisory fix table."""
    rel = state.get("releases") or []
    tracked = [a for a in advs if a.get("tracking")]
    if not rel and not tracked:
        return ""
    out = ["<section><h2>Release and fix tracking</h2>"]
    if rel:
        rows = []
        for r in rel:
            val = f"<code>{escape(r['value'])}</code>"
            if r.get("url"):
                val = f'<a href="{escape(r["url"])}" target="_blank" rel="noopener">{val}</a>'
            note = f" {escape(r['note'])}" if r.get("note") else ""
            rows.append(f"<dt>{escape(r['label'])}</dt><dd>{val}{note}</dd>")
        out.append(f'<dl class="rel">{"".join(rows)}</dl>')
    if tracked:
        rows = []
        for a in sorted(tracked, key=_sort_key):
            t = a["tracking"]
            fixes = ", ".join(
                f'<a href="{escape(f["url"])}" target="_blank" rel="noopener">{escape(f["label"])}</a>' for f in t.get("fix") or []
            )
            rows.append(
                f'<tr><td class="m">{escape(_short(a))}</td><td>{fixes or "none yet"}</td>'
                f'<td>{escape(t.get("dev") or "")}</td><td>{escape(t.get("beta") or "")}</td>'
                f'<td>{escape(t.get("stable") or "")}</td><td>{escape(t.get("cve") or "")}</td></tr>'
            )
        out.append(
            '<div class="tw"><table><thead><tr><th>Advisory</th><th>Fix</th><th>Dev</th><th>Beta</th>'
            f'<th>Stable</th><th>CVE</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
        )
    return "".join(out) + "</section>"


def _run_note(state: dict) -> str:
    """Render the run note and the alerts dismissed this run."""
    out = []
    if state.get("note"):
        out.append(f'<p class="note">{escape(state["note"])}</p>')
    dismissed = state.get("dismissed_this_run") or []
    if dismissed:
        items = "".join(
            f'<li><a href="{REPO}/security/code-scanning/{escape(str(d["number"]))}" target="_blank" rel="noopener">'
            f'#{escape(str(d["number"]))}</a> {escape(d.get("rule") or "")}: {escape(d["reason"])}</li>'
            for d in dismissed
        )
        out.append(f'<div class="note">Dismissed this run as false positives:<ul class="plain">{items}</ul></div>')
    return f'<section>{"".join(out)}</section>' if out else ""


if __name__ == "__main__":
    main()
