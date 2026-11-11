"""Build the attention page: sync GitHub, collect every routine's asks, rank them and render the page.

Usage: python3 build.py [--no-sync] [--source NAME] [--state-dir DIR] [--cache FILE] [--out FILE]
                        [--queue SOURCE] [--rows]

Prints the rows that entered Act or Unblock since the previous build, then one summary line.
`--queue pr-review` prints the live PR rows as JSON and writes nothing. `--rows` prints every row as
one JSON line and writes nothing.
"""
import argparse
import hashlib
import json
import re
from datetime import UTC, date, datetime, timedelta
from html import escape
from pathlib import Path

import collect
import gh_sync
import rank
from rank import Ask, Row, Tier, short_id

OUT = Path("~/.claude-teamB/routine-reports/attention.html").expanduser()
TOP_TIERS = (Tier.ACT, Tier.UNBLOCK)
SECTIONS = ("Today", "Later", "Blocked", "Snoozed", "Parked")
CADENCE_H = {"pr-review": 2, "issue-triage": 2, "security-inbox": 5 * 24, "lab-deep": 26, "triage-ma-nightly": 26}
OFFICE_SOURCES = frozenset({"pr-review", "issue-triage"})  # their cadence holds on weekdays in office hours only
OFFICE_HOURS = (7, 18)
POST_ENDPOINTS = frozenset({"issue-triage", "pr-review"})  # sources whose drafts report_server.py can post
DRAFT_ROWS = 12
DETAIL_NAMES = {"pr-review": "matrix", "issue-triage": "board", "security-inbox": "inbox"}
# Copy chips per source, in the owning routine's reply grammar; an action entry replaces the source's list.
SOURCE_COMMANDS = {
    "pr-review": ("show {r}", "review {r}", "chip {r}"),
    "issue-triage": ("fix {r}", "repro {r}", "discuss {r}", "done {r}"),
    "security-inbox": ("fix {r}", "draft {r}"),
}
ACTION_COMMANDS = {
    ("pr-review", "approve"): ("approve {r}", "show {r}"),
    ("issue-triage", "post"): ("done {r}",),
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--no-sync", action="store_true", help="use the GitHub cache as it is")
    p.add_argument("--source", choices=(*collect.SOURCES, "attention"), help="routine that triggered the build")
    p.add_argument("--state-dir", type=Path, default=gh_sync.STATE_DIR)
    p.add_argument("--cache", type=Path, default=gh_sync.CACHE)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--queue", choices=("pr-review",), help="print the live PR rows as JSON and write nothing")
    p.add_argument("--rows", action="store_true", help="print every row as one JSON line and write nothing")
    args = p.parse_args()
    now = datetime.now(UTC)
    if args.queue:
        print(json.dumps(queue(_rank(args.state_dir, args.cache, now)), indent=1))
        return
    if args.rows:
        for line in row_lines(_rank(args.state_dir, args.cache, now)):
            print(json.dumps(line))
        return
    stale = not args.no_sync and not gh_sync.sync(args.state_dir, args.cache)
    for line in build(args.state_dir, args.cache, args.out, now, stale):
        print(line)


def build(state_dir: Path, cache_path: Path, out: Path, now: datetime, stale: bool) -> list[str]:
    """Write the page and its build file; returns the stdout lines."""
    rows = _rank(state_dir, cache_path, now)
    build_file = out.with_name(f"{out.stem}.build.json")
    previous = collect.read_json(build_file).get("top")
    build_id = f"{now:%Y%m%dT%H%M%SZ}"
    collect.write_atomic(out, render(rows, page_meta(rows, state_dir, cache_path, now, build_id, stale)))
    collect.write_atomic(build_file, json.dumps({"id": build_id, "top": top_ids(rows)}) + "\n")
    return summary(rows, previous, out.name)


def summary(rows: list[Row], previous_top: list[str] | None, page: str) -> list[str]:
    """`+` lines for live Act and Unblock rows new since the previous build, then the budget line.

    Without a previous build there is nothing to compare, so only the budget line comes back.
    """
    seen = set(previous_top) if previous_top is not None else set(top_ids(rows))
    lines = [f"+ {row.tier.label}: {row.action} ({row.reason})" for row in rows if _top(row) and row.id not in seen]
    today = _today(rows)
    lines.append(f"attention: {len(today)} today, {sum(r.effort for r in today)} min of {rank.CUT_MIN}"
                 f" · {collect.REPORTS}/{page}")
    return lines


def top_ids(rows: list[Row]) -> list[str]:
    """Ids of the live Act and Unblock rows, in page order."""
    return [row.id for row in rows if _top(row)]


def queue(rows: list[Row]) -> list[dict]:
    """Live rows whose act-on ask is a PR, best first; a batch row gives one entry per PR member."""
    out = []
    for row in rows:
        if row.state != "live":
            continue
        batch = row.rule == "batch"
        for ask in row.members if batch else row.members[:1]:
            if ask.kind != "pr":
                continue
            repo, number = ask.id.split("#")
            out.append({
                "id": ask.id, "repo": repo.split("/")[1], "number": int(number), "tier": row.tier.label,
                "action": ask.action, "effort": rank.effort_of(ask) if batch else row.effort, "reason": row.reason,
            })
    return out


def row_lines(rows: list[Row]) -> list[dict]:
    """Every row in page order as a flat dict, addressed by the short id Marvin types."""
    out = []
    for row in rows:
        act = row.members[0]
        last = max((ask.last_activity for ask in row.members if ask.last_activity), default=None)
        out.append({
            "id": short_id(row.id), "full_id": row.id, "source": act.src, "kind": act.kind, "state": row.state,
            "tier": row.tier.label, "action": row.action, "reason": row.reason, "effort": row.effort,
            "title": act.title, "url": act.url, "who_waits": row.who_waits,
            "last_activity": last and last.isoformat(), "blocked_by": [short_id(id) for id in row.blocked_by],
            "members": [short_id(ask.id) for ask in row.members],
        })
    return out


def page_meta(rows: list[Row], state_dir: Path, cache_path: Path, now: datetime, build_id: str, stale: bool) -> dict:
    """What the page shows besides the rows: build id, budget, source ages and the stale flag."""
    ages = {source: collect.last_run(state) for source, state in collect.load_states(state_dir).items()}
    fetched = collect.read_json(cache_path).get("fetched_at")
    ages["github"] = datetime.fromisoformat(fetched.replace("Z", "+00:00")) if fetched else None
    return {
        "build_id": build_id, "now": now, "budget_used": sum(r.effort for r in _today(rows)),
        "budget": rank.CUT_MIN, "ages": ages, "stale": stale,
    }


def render(rows: list[Row], meta: dict) -> str:
    """The page as HTML: Today above the cut line, Later below it, the folded states, then the sources."""
    by_section: dict[str, list[Row]] = {name: [] for name in SECTIONS}
    for row in rows:
        by_section[_section(row)].append(row)
    page = _Page(rows, meta["now"].astimezone(collect.LOCAL).date())
    late = late_sources(meta)
    later = by_section["Later"]
    body = [
        _header(meta, len(by_section["Today"]), late),
        f'<section class="today" aria-label="Today">{page.groups(by_section["Today"]) or EMPTY_TODAY}</section>',
    ]
    if later:
        body.append(
            f'<section class="later"><h2>Later <span>below the {meta["budget"]} min line · {_count(later)}</span></h2>'
            f"{page.groups(later)}</section>"
        )
    folds = [
        f'<details class="fold" id="fold-{name.lower()}"><summary><h2>{name} <span>{len(by_section[name])}</span>'
        f"</h2></summary>{page.groups(by_section[name])}</details>"
        for name in ("Blocked", "Snoozed", "Parked") if by_section[name]
    ]
    if folds:
        body.append(f'<div class="folds">{"".join(folds)}</div>')
    body.append(_footer(meta, late))
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f"<title>Attention</title><style>{CSS}</style></head>\n"
        f'<body><main class="wrap" data-build="{escape(meta["build_id"])}">\n' + "\n".join(body)
        + f"\n</main>\n<script>{JS}</script></body></html>\n"
    )


def late_sources(meta: dict) -> list[str]:
    """Sources older than their cadence, plus `github` when the last sync failed."""
    now = meta["now"]
    late = [src for src, at in meta["ages"].items() if src in CADENCE_H and _late(src, at, now)]
    return late + ["github"] * meta["stale"]


def draft_hash(text: str) -> str:
    """The draft digest the report server checks a Post against."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class _Page:
    """Renders rows; knows every row on the page so links between rows stay on the page."""

    def __init__(self, rows: list[Row], today: date) -> None:
        self.today = today
        self.anchor = {ask.id: _slug(row.id) for row in rows for ask in row.members}
        self.anchor.update({row.id: _slug(row.id) for row in rows})
        self.unblocks: dict[str, list[str]] = {}
        for row in rows:
            for blocker in row.blocked_by:
                ids = self.unblocks.setdefault(self.anchor.get(blocker, blocker), [])
                if row.id not in ids:
                    ids.append(row.id)

    def groups(self, rows: list[Row]) -> str:
        """Rows under a small tier heading wherever the tier changes."""
        out = []
        for tier, group in _runs(rows):
            out.append(
                f'<div class="grp"><h3>{tier.label} <span>{_count(group)}</span></h3>'
                f'<ol class="rows">{"".join(f"<li>{self.row(row)}</li>" for row in group)}</ol></div>'
            )
        return "".join(out)

    def row(self, row: Row) -> str:
        """One row: the summary line and its folded detail."""
        act = row.members[0]
        bits = []
        if act.pending:
            bits.append(f'<span class="sent">sent: {escape(act.pending)}</span>')
        if row.who_waits and row.who_waits not in row.reason:
            bits.append(escape(f"{row.who_waits} waits"))
        if row.due and row.rule != "due":
            bits.append(f'<span class="due">due {row.due:%m-%d}</span>')
        bits.append(f'<span class="due">{escape(row.reason)}</span>' if row.rule == "due" else escape(row.reason))
        if row.rule != "batch":
            bits.append(f'<span class="t">{escape(act.title)}</span>')
        due_cls = " overdue" if row.due and row.due <= self.today else ""
        est = '<span class="est"> est.</span>' if act.effort is None else ""
        body = self._batch_body(row) if row.rule == "batch" else self._body(row)
        return (
            f'<details class="row tier-{row.tier.name.lower()}{due_cls}" id="r-{_slug(row.id)}" data-id="{escape(row.id)}">'
            f'<summary><span class="dot" aria-hidden="true"></span><span class="main">'
            f'<span class="act">{escape(row.action)}</span><span class="meta">{" · ".join(bits)}</span></span>'
            f'<span class="eff">{row.effort} min{est}</span></summary><div class="body">{body}</div></details>'
        )

    def _body(self, row: Row) -> str:
        """Detail of a work item: members, related rows, drafts and commands."""
        parts = [f'<ul class="items">{"".join(_item(ask) for ask in row.members)}</ul>']
        parts += [self._refs(label, ids) for label, ids in (
            ("Blocked by", row.blocked_by), ("Unblocks", self.unblocks.get(_slug(row.id), [])),
            ("See also", row.see_also),
        ) if ids]
        parts += [_draft(ask) for ask in row.members if _postable(ask)]
        parts.append(_commands(row.members[0], short_id(row.id), row.state))
        return "".join(parts)

    def _batch_body(self, row: Row) -> str:
        """Detail of a batch: every member with its own link, draft and commands."""
        members = "".join(
            f'<li class="member">{_item(ask, rank.effort_of(ask))}{_draft(ask) if _postable(ask) else ""}'
            f"{_commands(ask, short_id(ask.id), row.state)}</li>"
            for ask in row.members
        )
        return f'<ol class="members">{members}</ol>'

    def _refs(self, label: str, ids: list[str]) -> str:
        """A labelled line of ids, linked to their row on this page or else to GitHub."""
        links = []
        for id in ids:
            text = escape(short_id(id))
            href = f"#r-{self.anchor[id]}" if id in self.anchor else _gh_url(id)
            links.append(f'<a href="{escape(href)}">{text}</a>' if href else text)
        return f'<p class="refs"><span class="lbl">{label}</span> {" ".join(links)}</p>'


def _rank(state_dir: Path, cache_path: Path, now: datetime) -> list[Row]:
    """Ranked rows from the states, the cache and attention.json."""
    attention = collect.load_attention(state_dir / "attention.json")
    return rank.rank(collect.collect(state_dir, collect.read_json(cache_path), attention, now), now)


def _top(row: Row) -> bool:
    """A live Act or Unblock row."""
    return row.state == "live" and row.tier in TOP_TIERS


def _today(rows: list[Row]) -> list[Row]:
    """Live rows above the cut line."""
    return [row for row in rows if row.state == "live" and not row.cut]


def _section(row: Row) -> str:
    """Page section of a row."""
    if row.state == "live":
        return "Later" if row.cut else "Today"
    return row.state.capitalize()


def _header(meta: dict, today: int, late: list[str]) -> str:
    """Date, budget line and, when a source is late, one line naming it."""
    local = meta["now"].astimezone(collect.LOCAL)
    alert = ""
    if late:
        names = ", ".join("GitHub sync failed" if src == "github" else f"{src} {_age(meta['now'], meta['ages'][src])}"
                          for src in late)
        alert = f'<p class="alert">Old data: {escape(names)}</p>'
    return (
        f'<header><h1>Attention</h1><p class="date">{local:%A} {local.day} {local:%B} · built {local:%H:%M}</p>'
        f'<p class="budget"><b>{today} rows</b>, {meta["budget_used"]} of {meta["budget"]} min</p>{alert}</header>'
    )


def _footer(meta: dict, late: list[str]) -> str:
    """Age of every source with a link to its page; late ones stand out."""
    items = []
    for src, at in meta["ages"].items():
        name = "GitHub sync" if src == "github" else f'<a href="{src}.html">{src}</a>'
        cls = ' class="late"' if src in late else ""
        items.append(f"<li{cls}>{name} <span>{_age(meta['now'], at)}</span></li>")
    return f'<footer><h2>Sources</h2><ul class="src">{"".join(items)}</ul></footer>'


def _late(source: str, at: datetime | None, now: datetime) -> bool:
    """Older than the source's cadence; office-hours sources are never late outside office hours."""
    local = now.astimezone(collect.LOCAL)
    if source in OFFICE_SOURCES and not (local.weekday() < 5 and OFFICE_HOURS[0] <= local.hour < OFFICE_HOURS[1]):
        return False
    return at is None or now - at > timedelta(hours=CADENCE_H[source])


def _runs(rows: list[Row]) -> list[tuple[Tier, list[Row]]]:
    """Consecutive rows of the same tier."""
    runs: list[tuple[Tier, list[Row]]] = []
    for row in rows:
        if runs and runs[-1][0] is row.tier:
            runs[-1][1].append(row)
        else:
            runs.append((row.tier, [row]))
    return runs


def _count(rows: list[Row]) -> str:
    """Text like '3 rows · 45 min'."""
    return f"{len(rows)} row{'s' * (len(rows) != 1)} · {sum(r.effort for r in rows)} min"


def _item(ask: Ask, effort: int | None = None) -> str:
    """A member line: id linked to GitHub, title, effort when given, and a link to its detail page."""
    parts = [f'<a class="id" href="{escape(ask.url)}" target="_blank" rel="noopener">{escape(short_id(ask.id))}</a>',
             f'<span class="t">{escape(ask.title)}</span>']
    if effort is not None:
        parts.append(f'<span class="m">{effort} min{" est." * (ask.effort is None)}</span>')
    if ask.detail_url:
        parts.append(f'<a class="m" href="{escape(ask.detail_url)}">{DETAIL_NAMES.get(ask.src, ask.src)}</a>')
    return f'<li class="item">{" ".join(parts)}</li>'


def _postable(ask: Ask) -> bool:
    """A drafted reply the report server can post."""
    return bool(ask.draft_reply) and ask.src in POST_ENDPOINTS


def _draft(ask: Ask) -> str:
    """Editable draft with its Post button, wired to the owning routine's endpoint."""
    repo, n = ask.id.split("#")
    if ask.src == "pr-review":
        repo = repo.split("/")[1]
    text = ask.draft_reply or ""
    rows = min(DRAFT_ROWS, sum(len(line) // 90 + 1 for line in text.split("\n")))
    label = escape(f"Draft reply on {short_id(ask.id)}")
    return (
        # The parser drops the newline right after <textarea>, so a draft's own leading newline survives.
        f'<div class="draft"><textarea id="d-{_slug(ask.id)}" rows="{rows}" aria-label="{label}">\n'
        f"{escape(text, quote=False)}</textarea><div class=\"bar\">"
        f'<button class="btn post" type="button" data-post data-src="{ask.src}" data-repo="{escape(repo)}" '
        f'data-n="{n}" data-hash="{draft_hash(text)}">Post</button>'
        '<span class="edited" hidden>Edited · <a href="#" data-revert>Revert</a></span>'
        '<span class="perr" role="status"></span></div></div>'
    )


def _commands(ask: Ask, ref: str, state: str) -> str:
    """Copy chips for the commands that fit the ask, addressed by its short id."""
    routine = ACTION_COMMANDS.get((ask.src, ask.action)) or SOURCE_COMMANDS.get(ask.src, ())
    own = {"snoozed": ("unsnooze {r}",), "blocked": ("unblock {r}",)}.get(state, ("snooze {r} 3d", "later {r}"))
    chips = "".join(
        f'<button class="cmd" type="button" data-cmd="{escape(c)}" title="Copy for the attention thread">{escape(c)}</button>'
        for c in (cmd.format(r=ref) for cmd in (*routine, *own))
    )
    return f'<div class="cmds">{chips}</div>'


def _gh_url(id: str) -> str | None:
    """GitHub URL of an `owner/repo#n` or `orgs/owner#n` id; None for other ids."""
    if m := re.fullmatch(r"orgs/([\w.-]+)#(\d+)", id):
        return f"https://github.com/orgs/{m[1]}/discussions/{m[2]}"
    if m := re.fullmatch(r"([\w.-]+/[\w.-]+)#(\d+)", id):
        return f"https://github.com/{m[1]}/issues/{m[2]}"
    return None


def _slug(id: str) -> str:
    """Id as an HTML id fragment."""
    return re.sub(r"[^a-z0-9]+", "-", id.lower()).strip("-")


def _age(now: datetime, at: datetime | None) -> str:
    """Age like '40 min', '3 h' or '2 d', or 'never'."""
    if at is None:
        return "never"
    minutes = int((now - at).total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h" if minutes < 48 * 60 else f"{minutes // 1440} d"


EMPTY_TODAY = '<p class="empty">Nothing above the line. Work from Later, or take the day.</p>'

THEME = """
:root { --foreground: #18201d; --muted-foreground: #5b6863; --border: #d9e0dc; --card: #ffffff;
  --background: #f4f6f5; --accent: #eaefec; --destructive: #b03c2a; --warning: #a66a12; --info: #2c5e8c; --ask: #c2410c;
  --radius: 6px; --font-sans: system-ui, -apple-system, "Segoe UI", sans-serif; --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
  color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --foreground: #e4eae7; --muted-foreground: #95a39d;
  --border: #2c3632; --card: #1a211e; --background: #121715; --accent: #222b27; --destructive: #ec7e6b; --warning: #e2a64a;
  --info: #7fb0de; --ask: #fb923c; color-scheme: dark; } }
:root[data-theme="dark"] { --foreground: #e4eae7; --muted-foreground: #95a39d; --border: #2c3632; --card: #1a211e;
  --background: #121715; --accent: #222b27; --destructive: #ec7e6b; --warning: #e2a64a; --info: #7fb0de; --ask: #fb923c;
  color-scheme: dark; }
"""

# A calm reading list: one column, hairlines between rows, colour and weight only on Today rows.
CSS = THEME + """
* { box-sizing: border-box; }
body { margin: 0; background: var(--background); color: var(--foreground); font: 14px/1.5 var(--font-sans);
  padding-block: 28px 64px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.wrap { max-width: 780px; margin: 0 auto; display: flex; flex-direction: column; gap: 28px; }
a { color: var(--info); text-decoration: none; } a:hover { text-decoration: underline; }
:focus-visible { outline: 2px solid var(--info); outline-offset: 2px; border-radius: 3px; }
header { display: flex; flex-direction: column; gap: 2px; }
h1 { font-size: 22px; font-weight: 650; letter-spacing: -.01em; margin: 0 0 2px; }
header p { margin: 0; } .date { color: var(--muted-foreground); }
.budget { font-size: 15px; font-variant-numeric: tabular-nums; } .budget b { font-weight: 600; }
.alert { color: var(--warning); font-weight: 600; font-size: 13px; }
h2 { font-size: 13px; font-weight: 600; margin: 0; display: flex; gap: 8px; align-items: baseline; }
h2 span, h3 span { font-weight: 400; color: var(--muted-foreground); font-variant-numeric: tabular-nums; }
h3 { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .07em; color: var(--muted-foreground);
  margin: 0; padding: 14px 0 4px 26px; display: flex; gap: 8px; align-items: baseline; }
h3 span { text-transform: none; letter-spacing: 0; }
.grp:first-child h3 { padding-top: 0; }
ol, ul { list-style: none; margin: 0; padding: 0; }
ol.rows > li + li { border-top: 1px solid var(--border); }
.row > summary { list-style: none; cursor: pointer; display: grid; grid-template-columns: 12px minmax(0, 1fr) auto;
  gap: 2px 14px; align-items: baseline; padding: 8px 6px; border-radius: var(--radius); }
.row > summary::-webkit-details-marker { display: none; }
.row > summary:hover, .row[open] > summary { background: var(--accent); }
.main { display: flex; flex-direction: column; min-width: 0; }
.act { font-size: 14.5px; overflow-wrap: anywhere; }
.meta { font-size: 12.5px; color: var(--muted-foreground); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.meta .sent { font-style: italic; }
.eff { font-size: 12.5px; color: var(--muted-foreground); font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.est { font-size: 11px; }
.dot { width: 8px; height: 8px; border-radius: 50%; align-self: start; margin-top: 8px; }
.today .act { font-weight: 600; }
.today .eff { color: var(--foreground); }
.today .dot { background: var(--ask); }
.today .tier-act .dot { background: var(--destructive); }
.today .overdue .due { color: var(--destructive); font-weight: 600; }
.body { padding: 6px 6px 16px 32px; display: flex; flex-direction: column; gap: 10px; font-size: 13px; }
.items, .members { display: flex; flex-direction: column; gap: 4px; }
.members { gap: 14px; }
.member { display: flex; flex-direction: column; gap: 8px; }
.item { overflow-wrap: anywhere; padding-left: 1.5em; text-indent: -1.5em; }
.item .id { font: 12px var(--font-mono); white-space: nowrap; margin-right: 6px; }
.m { font-size: 12px; color: var(--muted-foreground); white-space: nowrap; margin-left: 8px; }
a.m { color: var(--info); }
.refs { margin: 0; display: flex; flex-wrap: wrap; gap: 2px 10px; align-items: baseline; font: 12px var(--font-mono); }
.lbl { font: 600 11px var(--font-sans); text-transform: uppercase; letter-spacing: .06em; color: var(--muted-foreground); }
.draft { display: flex; flex-direction: column; gap: 6px; }
textarea { display: block; width: 100%; resize: vertical; font: 12.5px/1.5 var(--font-mono); padding: 8px 10px;
  color: var(--foreground); background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); }
textarea[readonly] { background: transparent; }
.bar { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; font-size: 12.5px; color: var(--muted-foreground); }
.btn { font: 500 12px var(--font-sans); padding: 4px 12px; border-radius: var(--radius); border: 1px solid var(--foreground);
  background: var(--foreground); color: var(--background); cursor: pointer; }
.btn:disabled { cursor: progress; }
a.btn { background: transparent; color: var(--foreground); border-color: var(--border); text-decoration: none; }
.perr { color: var(--destructive); }
.cmds { display: flex; flex-wrap: wrap; gap: 6px; }
.cmd { font: 11.5px var(--font-mono); padding: 2px 8px; border-radius: 4px; border: 1px solid var(--border);
  background: transparent; color: var(--muted-foreground); cursor: copy; }
.cmd:hover { color: var(--foreground); border-color: var(--muted-foreground); }
.later { display: flex; flex-direction: column; gap: 10px; }
.later > h2 { border-top: 1px dashed var(--muted-foreground); padding-top: 12px; }
.folds { display: flex; flex-direction: column; gap: 2px; }
.fold > summary { list-style: none; cursor: pointer; padding: 4px 0; }
.fold > summary::-webkit-details-marker { display: none; }
.fold > summary h2::before { content: "\\25B8"; font-size: 10px; color: var(--muted-foreground); }
.fold[open] > summary h2::before { content: "\\25BE"; }
.fold > .grp { margin-top: 6px; }
.empty { margin: 0; color: var(--muted-foreground); }
footer { display: flex; flex-direction: column; gap: 6px; border-top: 1px solid var(--border); padding-top: 14px; }
.src { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 4px 18px; font-size: 12.5px; color: var(--muted-foreground); }
.src span { font-variant-numeric: tabular-nums; }
.src .late, .src .late a, .src .late span { color: var(--warning); font-weight: 600; }
@media (max-width: 520px) {
  .row > summary { gap: 2px 10px; padding-inline: 2px; }
  .body { padding-left: 8px; }
  h3 { padding-left: 22px; }
}
@media (prefers-reduced-motion: no-preference) { .row > summary { transition: background-color .12s; } }
[hidden] { display: none !important; }
"""

JS = """
// report_server.py fills these placeholders when it serves the page.
const TOKEN = "__ACTION_TOKEN__";
let POSTED = {"issue-triage": {}, "pr-review": {}};
try { POSTED["issue-triage"] = __POSTED__; } catch (e) {}
try { POSTED["pr-review"] = __PR_REVIEW_POSTED__; } catch (e) {}
const ENDPOINT = {"issue-triage": "/api/issue-triage/post", "pr-review": "/api/pr-review/post"};
function store(f, k, v) { try { return v === undefined ? f().getItem(k) : v === null ? f().removeItem(k) : f().setItem(k, v); } catch (e) { return null; } }
const local = () => localStorage, session = () => sessionStorage;
// Same keys as the issue-triage and pr-review pages, so an edit started there shows up here.
function key(b) { return b.dataset.src + "-edit:" + b.dataset.repo + "#" + b.dataset.n + ":" + b.dataset.hash; }
function box(el) { return el.closest(".draft").querySelector("textarea"); }
function button(t) { return t.closest(".draft").querySelector("button[data-post]"); }
function dirty(t) { return !t.readOnly && t.value !== t.defaultValue; }
function mark(t) { t.closest(".draft").querySelector(".edited").hidden = !dirty(t); }
function posted(b, url, body) {
  const t = box(b);
  if (body) t.value = body;
  t.readOnly = true; mark(t);
  const a = document.createElement("a");
  a.className = "btn"; a.href = url; a.target = "_blank"; a.rel = "noopener"; a.textContent = "Posted";
  b.replaceWith(a);
}
async function post(b) {
  const err = b.parentElement.querySelector(".perr"), t = box(b);
  err.textContent = ""; b.disabled = true; b.textContent = "Posting";
  try {
    const r = await fetch(ENDPOINT[b.dataset.src], {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Action-Token": TOKEN},
      body: JSON.stringify({repo: b.dataset.repo, n: Number(b.dataset.n), hash: b.dataset.hash, body: t.value}),
    });
    const j = await r.json().catch(() => ({error: "HTTP " + r.status}));
    if (j.ok) { store(local, key(b), null); posted(b, j.url, t.value); return; }
    err.textContent = j.error || "HTTP " + r.status;
  } catch (e) { err.textContent = "The report server did not answer: " + e.message; }
  b.disabled = false; b.textContent = "Post";
}
document.querySelectorAll("button[data-post]").forEach(b => {
  const p = POSTED[b.dataset.src][b.dataset.repo + "#" + b.dataset.n];
  if (p && p.hash === b.dataset.hash) { posted(b, p.url, p.body); return; }
  const v = store(local, key(b));
  if (v !== null) box(b).value = v;
  mark(box(b));
});
document.addEventListener("input", e => {
  const t = e.target;
  if (!t.matches(".draft textarea")) return;
  store(local, key(button(t)), dirty(t) ? t.value : null);
  mark(t);
});
function show(id) {
  const d = document.getElementById(id);
  if (!d || !d.matches("details.row")) return;
  const fold = d.closest("details.fold");
  if (fold) fold.open = true;
  d.open = true;
  d.querySelector("summary").focus();
}
document.addEventListener("click", e => {
  const pb = e.target.closest("button[data-post]");
  if (pb) { post(pb); return; }
  const rv = e.target.closest("a[data-revert]");
  if (rv) {
    e.preventDefault();
    const t = box(rv);
    t.value = t.defaultValue; store(local, key(button(t)), null); mark(t);
    return;
  }
  const c = e.target.closest("button[data-cmd]");
  if (c) {
    const done = text => { c.textContent = text; setTimeout(() => { c.textContent = c.dataset.cmd; }, 1200); };
    if (navigator.clipboard) navigator.clipboard.writeText(c.dataset.cmd).then(() => done("Copied"), () => done("Copy failed"));
    return;
  }
  const a = e.target.closest('a[href^="#r-"]');
  if (a) { e.preventDefault(); show(a.getAttribute("href").slice(1)); history.replaceState(null, "", a.getAttribute("href")); }
});
// Open rows and folds survive the automatic reload.
const OPEN = "attention-open";
(JSON.parse(store(session, OPEN) || "[]")).forEach(id => { const d = document.getElementById(id); if (d) d.open = true; });
if (location.hash.startsWith("#r-")) show(location.hash.slice(1));
const BUILD = document.querySelector("main").dataset.build;
const BUILD_URL = location.pathname.replace(/\\.html$/, ".build.json");
setInterval(async () => {
  if ([...document.querySelectorAll(".draft textarea")].some(dirty)) return;
  try {
    const r = await fetch(BUILD_URL, {cache: "no-store"});
    if ((await r.json()).id === BUILD) return;
  } catch (e) { return; }
  store(session, OPEN, JSON.stringify([...document.querySelectorAll("details[open]")].map(d => d.id).filter(Boolean)));
  location.reload();
}, 60000);
"""


if __name__ == "__main__":
    main()
