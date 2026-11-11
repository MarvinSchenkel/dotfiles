"""Build the attention page: sync GitHub, collect every routine's asks, rank them and render the page.

Usage: python3 build.py [--no-sync] [--source NAME [--handled]] [--state-dir DIR] [--cache FILE] [--out FILE]
                        [--queue SOURCE] [--rows]

Prints the rows that entered Act or Unblock since the previous build, then one summary line.
`--handled` records that the source's routine handled the commands forwarded to it so far.
`--queue pr-review` prints the live rows pr-review owns as JSON and writes nothing. `--rows` prints every row as
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
# Date-only stamps (security-inbox, lab-deep) count from local midnight, hence the slack past their cadence.
CADENCE_H = {"pr-review": 2, "issue-triage": 2, "security-inbox": 6 * 24, "lab-deep": 36, "triage-ma-nightly": 26}
OFFICE_SOURCES = frozenset({"pr-review", "issue-triage"})  # their cadence holds on weekdays in office hours only
OFFICE_HOURS = (9, 18)  # before 09:00 the first runs of the day are still due
POST_ENDPOINTS = frozenset({"issue-triage", "pr-review"})  # sources whose drafts report_server.py can post
DRAFT_ROWS = 12
DETAIL_NAMES = {"pr-review": "matrix", "issue-triage": "board", "security-inbox": "inbox"}
TIER_NOTES = {
    Tier.ACT: "Security steps, deadlines and regressions on stable",
    Tier.UNBLOCK: "Someone waits on a short answer",
    Tier.LAND: "Ready for your approval or merge",
    Tier.DECIDE: "Design calls, reviews and input",
    Tier.KEEP_WARM: "Chores and drafted replies",
}
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
    p.add_argument("--handled", action="store_true", help="the source handled the commands forwarded to it")
    p.add_argument("--state-dir", type=Path, default=gh_sync.STATE_DIR)
    p.add_argument("--cache", type=Path, default=gh_sync.CACHE)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--queue", choices=("pr-review",), help="print the live PR rows as JSON and write nothing")
    p.add_argument("--rows", action="store_true", help="print every row as one JSON line and write nothing")
    args = p.parse_args()
    if args.handled and not args.source:
        p.error("--handled needs --source")
    now = datetime.now(collect.LOCAL)
    handled = _handled(collect.read_json(_build_file(args.out)))
    if args.queue:
        print(json.dumps(queue(_rank(args.state_dir, args.cache, now, handled), args.queue), indent=1))
        return
    if args.rows:
        for line in row_lines(_rank(args.state_dir, args.cache, now, handled)):
            print(json.dumps(line))
        return
    stale = not args.no_sync and not gh_sync.sync(args.state_dir, args.cache)
    for line in build(args.state_dir, args.cache, args.out, now, stale, args.source if args.handled else None):
        print(line)


def build(
    state_dir: Path, cache_path: Path, out: Path, now: datetime, stale: bool, handled_by: str | None = None
) -> list[str]:
    """Write the page and its build file; returns the stdout lines.

    `handled_by` is the source whose routine just handled its forwarded commands, so their markers clear.
    """
    build_file = _build_file(out)
    previous = collect.read_json(build_file)
    handled = _handled(previous) | ({handled_by: now} if handled_by else {})
    rows = _rank(state_dir, cache_path, now, handled)
    build_id = f"{now.astimezone(UTC):%Y%m%dT%H%M%SZ}"
    collect.write_atomic(out, render(rows, page_meta(rows, state_dir, cache_path, now, build_id, stale)))
    data = {"id": build_id, "top": top_ids(rows)}
    if handled:
        data["handled"] = {src: at.astimezone(UTC).isoformat() for src, at in handled.items()}
    collect.write_atomic(build_file, json.dumps(data) + "\n")
    return summary(rows, previous.get("top"), out.name)


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


def queue(rows: list[Row], source: str) -> list[dict]:
    """Live PR rows whose act-on ask comes from the source, best first; a batch gives one entry per member."""
    out = []
    for row in rows:
        if row.state != "live":
            continue
        batch = row.rule == "batch"
        for ask in row.members if batch else row.members[:1]:
            if ask.src != source or ask.kind != "pr":
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
            "members": [{"id": short_id(ask.id), "source": ask.src} for ask in row.members],
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
    today, later = by_section["Today"], by_section["Later"]
    body = [
        _header(meta, today, late),
        f'<section class="today" aria-label="Today">{page.groups(today, lead=True) or EMPTY_TODAY}</section>',
    ]
    if later:
        body.append(
            f'<section class="later"><div class="cut" role="separator">{meta["budget"]} min line</div>'
            f'<h2>Later <span class="n">{_count(later)}</span></h2>{page.groups(later)}</section>'
        )
    folds = [
        f'<details class="fold" id="fold-{name.lower()}"><summary><h2>{name}</h2>'
        f'<span class="n">{len(by_section[name])}</span><span class="chev" aria-hidden="true"></span></summary>'
        f"{page.groups(by_section[name])}</details>"
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
        self.number = {row.id: n for n, row in enumerate((r for r in rows if r.state == "live"), 1)}
        self.anchor = {ask.id: _slug(row.id) for row in rows for ask in row.members}
        self.anchor.update({row.id: _slug(row.id) for row in rows})
        self.unblocks: dict[str, list[str]] = {}
        for row in rows:
            for blocker in row.blocked_by:
                ids = self.unblocks.setdefault(self.anchor.get(blocker, blocker), [])
                if row.id not in ids:
                    ids.append(row.id)

    def groups(self, rows: list[Row], lead: bool = False) -> str:
        """Rows under a tier heading wherever the tier changes; the lead section's headings say what the tier is."""
        out = []
        for tier, group in _runs(rows):
            slug = tier.name.lower()
            anchor = f' id="t-{slug}"' if lead else ""
            note = f'<p class="note">{TIER_NOTES[tier]}</p>' if lead else ""
            out.append(
                f'<div class="grp tier-{slug}"{anchor}><div class="gh"><h3>{tier.label}</h3>'
                f'<span class="n">{_count(group)}</span>{note}</div>'
                f'<ol class="rows">{"".join(f"<li>{self.row(row)}</li>" for row in group)}</ol></div>'
            )
        return "".join(out)

    def row(self, row: Row) -> str:
        """One row: the summary line and its folded detail."""
        act = row.members[0]
        chips = f'<span class="chip sent">sent: {escape(act.pending)}</span>' if act.pending else ""
        chips += self._due_chip(row)
        bits = []
        if row.who_waits and row.who_waits not in row.reason:
            bits.append(escape(f"{row.who_waits} waits"))
        if row.rule != "due":
            bits.append(escape(row.reason))
        if row.rule != "batch" and act.title != row.action:
            bits.append(f'<span class="t">{escape(act.title)}</span>')
        est = '<span class="est"> est.</span>' if act.effort is None else ""
        body = self._batch_body(row) if row.rule == "batch" else self._body(row)
        return (
            f'<details class="row" id="r-{_slug(row.id)}" data-id="{escape(row.id)}">'
            f'<summary><span class="num" aria-hidden="true">{self.number.get(row.id, "")}</span><span class="main">'
            f'<span class="act">{escape(row.action)}</span><span class="meta">{chips}{" · ".join(bits)}</span></span>'
            f'<span class="eff">{row.effort} min{est}</span><span class="chev" aria-hidden="true"></span></summary>'
            f'<div class="body">{body}</div></details>'
        )

    def _due_chip(self, row: Row) -> str:
        """The row's due date as a chip that says how far off it is."""
        if not row.due:
            return ""
        days = (row.due - self.today).days
        text = f"overdue {-days} d" if days < 0 else "due today" if days == 0 else f"due {row.due:%m-%d}"
        return f'<span class="chip due{" late" * (days <= 0)}">{text}</span>'

    def _body(self, row: Row) -> str:
        """Detail of a work item: members, related rows, drafts and commands."""
        parts = [f'<ul class="items">{"".join(_item(ask) for ask in row.members)}</ul>']
        parts += [self._refs(label, ids) for label, ids in (
            ("Blocked by", row.blocked_by), ("Unblocks", self.unblocks.get(_slug(row.id), [])),
            ("See also", row.see_also),
        ) if ids]
        parts += [_draft(ask) for ask in row.members if _postable(ask)]
        parts.append(_commands(row.members, short_id(row.id), row.state))
        return "".join(parts)

    def _batch_body(self, row: Row) -> str:
        """Detail of a batch: every member with its own link, draft and commands."""
        members = "".join(
            f'<li class="member">{_item(ask, rank.effort_of(ask))}{_draft(ask) if _postable(ask) else ""}'
            f"{_commands([ask], short_id(ask.id), row.state)}</li>"
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


def _rank(state_dir: Path, cache_path: Path, now: datetime, handled: dict[str, datetime]) -> list[Row]:
    """Ranked rows from the states, the cache and attention.json."""
    attention = collect.load_attention(state_dir / "attention.json")
    return rank.rank(collect.collect(state_dir, collect.read_json(cache_path), attention, now, handled), now)


def _build_file(out: Path) -> Path:
    """Build file next to the page."""
    return out.with_name(f"{out.stem}.build.json")


def _handled(build_data: dict) -> dict[str, datetime]:
    """When each source last handled its forwarded commands, from the build file."""
    return {src: datetime.fromisoformat(at) for src, at in build_data.get("handled", {}).items()}


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


def _header(meta: dict, today: list[Row], late: list[str]) -> str:
    """Title, date, the day's budget as a bar split by tier and, when a source is late, one line naming it."""
    local = meta["now"].astimezone(collect.LOCAL)
    used, budget = meta["budget_used"], meta["budget"]
    segments, legend = [], []
    for tier, group in _runs(today):
        slug, minutes = tier.name.lower(), sum(row.effort for row in group)
        segments.append(f'<i class="tier-{slug}" style="flex:{minutes}"></i>')
        legend.append(
            f'<a class="tier-{slug}" href="#t-{slug}"><b>{tier.label}</b> <span>{len(group)} · {minutes} min</span></a>'
        )
    if used < budget:
        segments.append(f'<i style="flex:{budget - used}"></i>')
        legend.append(f'<span class="free">{budget - used} min free</span>')
    alert = ""
    if late:
        names = ", ".join("GitHub sync failed" if src == "github" else f"{src} {_age(meta['now'], meta['ages'][src])}"
                          for src in late)
        alert = f'<p class="alert">Old data: {escape(names)}</p>'
    rows = f"{len(today)} row{'s' * (len(today) != 1)} today"
    return (
        f'<header><div class="top"><h1>Attention</h1>'
        f'<p class="date">{local:%A} {local.day} {local:%B} · built {local:%H:%M}</p></div>'
        f'<div class="budget"><p class="bline"><b>{rows}</b><span>{used} of {budget} min</span></p>'
        f'<div class="meter" role="img" aria-label="{used} of {budget} minutes planned">{"".join(segments)}</div>'
        f'<nav class="legend" aria-label="Tiers">{"".join(legend)}</nav></div>{alert}</header>'
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
        f'<div class="draft"><span class="lbl">Draft reply</span>'
        f'<textarea id="d-{_slug(ask.id)}" rows="{rows}" aria-label="{label}">\n'
        f"{escape(text, quote=False)}</textarea><div class=\"bar\">"
        f'<button class="btn post" type="button" data-post data-src="{ask.src}" data-repo="{escape(repo)}" '
        f'data-n="{n}" data-hash="{draft_hash(text)}">Post</button>'
        '<span class="edited" hidden>Edited · <a href="#" data-revert>Revert</a></span>'
        '<span class="perr" role="status"></span></div></div>'
    )


def _commands(asks: list[Ask], ref: str, state: str) -> str:
    """Copy chips: each ask's routine commands by its short id, then the attention thread's own by `ref`."""
    routine = [cmd.format(r=short_id(ask.id)) for ask in asks
               for cmd in ACTION_COMMANDS.get((ask.src, ask.action)) or SOURCE_COMMANDS.get(ask.src, ())]
    own = {"snoozed": ("unsnooze {r}",), "blocked": ("unblock {r}",)}.get(state, ("snooze {r} 3d", "later {r}"))
    chips = "".join(
        f'<button class="cmd" type="button" data-cmd="{escape(c)}" title="Copy for the attention thread">{escape(c)}</button>'
        for c in (*routine, *(cmd.format(r=ref) for cmd in own))
    )
    return f'<div class="cmds"><span class="lbl">Copy a command</span>{chips}</div>'


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
  --background: #f4f6f5; --accent: #eaefec; --destructive: #b03c2a; --destructive-surface: #f8e4df; --warning: #a66a12;
  --info: #2c5e8c; --ask: #c2410c; --land: #3f5a50; --decide: #84948d; --warm: #b7c2bd; --track: #e2e8e5;
  --radius: 8px; --font-sans: system-ui, -apple-system, "Segoe UI", sans-serif; --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
  color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --foreground: #e4eae7; --muted-foreground: #95a39d;
  --border: #2c3632; --card: #1a211e; --background: #121715; --accent: #1f2824; --destructive: #ec7e6b;
  --destructive-surface: #3b211c; --warning: #e2a64a; --info: #7fb0de; --ask: #fb923c; --land: #a3bdb2; --decide: #6b7a74;
  --warm: #46524d; --track: #232c28; color-scheme: dark; } }
:root[data-theme="dark"] { --foreground: #e4eae7; --muted-foreground: #95a39d; --border: #2c3632; --card: #1a211e;
  --background: #121715; --accent: #1f2824; --destructive: #ec7e6b; --destructive-surface: #3b211c; --warning: #e2a64a;
  --info: #7fb0de; --ask: #fb923c; --land: #a3bdb2; --decide: #6b7a74; --warm: #46524d; --track: #232c28;
  color-scheme: dark; }
"""

# One ranked column. Tier headings carry the structure, the budget bar is the summary, and only an
# open row becomes a card. Colour marks the two urgent tiers and nothing below the cut line.
CSS = THEME + """
* { box-sizing: border-box; }
body { margin: 0; background: var(--background); color: var(--foreground); font: 14px/1.5 var(--font-sans);
  padding-block: 36px 72px; padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
.wrap { max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; gap: 40px; }
a { color: var(--info); text-decoration: none; } a:hover { text-decoration: underline; }
:focus-visible { outline: 2px solid var(--info); outline-offset: 2px; border-radius: 4px; }
ol, ul { list-style: none; margin: 0; padding: 0; }
p, h1, h2, h3 { margin: 0; }
.n { font-size: 13px; font-weight: 400; color: var(--muted-foreground); font-variant-numeric: tabular-nums; white-space: nowrap; }
.tier-act { --tier: var(--destructive); } .tier-unblock { --tier: var(--ask); } .tier-land { --tier: var(--land); }
.tier-decide { --tier: var(--decide); } .tier-keep_warm { --tier: var(--warm); }

header { display: flex; flex-direction: column; gap: 18px; }
.top { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 2px 16px; }
h1 { font-size: 28px; font-weight: 700; letter-spacing: -.02em; line-height: 1.15; }
.date { color: var(--muted-foreground); font-size: 13px; }
.budget { display: flex; flex-direction: column; gap: 9px; }
.bline { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; font-variant-numeric: tabular-nums; }
.bline b { font-size: 15px; font-weight: 600; } .bline span { font-size: 13px; color: var(--muted-foreground); }
.meter { display: flex; gap: 2px; height: 10px; border-radius: 5px; overflow: hidden; }
.meter i { background: var(--tier, var(--track)); min-width: 0; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 20px; font-size: 13px; }
.legend a { color: var(--foreground); display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
.legend a::before { content: ""; width: 9px; height: 9px; border-radius: 3px; background: var(--tier); }
.legend b { font-weight: 600; }
.legend span { color: var(--muted-foreground); font-variant-numeric: tabular-nums; }
.legend .free { margin-left: auto; }
.alert { color: var(--warning); font-weight: 600; font-size: 13px; }

.today { display: flex; flex-direction: column; gap: 34px; }
.grp { scroll-margin-top: 16px; }
.gh { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: baseline; gap: 0 12px; padding: 0 12px 10px; }
.gh h3 { font-size: 19px; font-weight: 650; letter-spacing: -.01em; line-height: 1.3; display: flex; align-items: center; gap: 10px; }
.gh h3::before { content: ""; flex: none; width: 10px; height: 10px; border-radius: 3px; background: var(--tier); }
.note { grid-column: 1 / -1; padding-left: 20px; font-size: 13px; color: var(--muted-foreground); }
ol.rows { border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
ol.rows > li + li { border-top: 1px solid var(--border); }
ol.rows > li:has(> .row[open]), ol.rows > li:has(> .row[open]) + li { border-top-color: transparent; }

.row { border: 1px solid transparent; border-radius: var(--radius); }
.row > summary { list-style: none; cursor: pointer; display: grid; grid-template-columns: 20px minmax(0, 1fr) auto 10px;
  gap: 0 12px; align-items: baseline; padding: 11px 12px; border-radius: var(--radius); }
.row > summary::-webkit-details-marker { display: none; }
.row:not([open]) > summary:hover { background: var(--accent); }
.num { font: 12px var(--font-mono); color: var(--muted-foreground); text-align: right; font-variant-numeric: tabular-nums; }
.main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.act { font-size: 15px; line-height: 1.35; overflow-wrap: anywhere; }
.meta { font-size: 13px; color: var(--muted-foreground); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chip { display: inline-block; font-size: 11.5px; font-weight: 600; line-height: 18px; padding: 0 8px; margin-right: 8px;
  border-radius: 999px; border: 1px solid var(--border); color: var(--muted-foreground); vertical-align: 1px;
  font-variant-numeric: tabular-nums; }
.chip.sent { font-family: var(--font-mono); font-weight: 400; background: var(--accent); border-color: transparent; }
.eff { font-size: 13px; color: var(--muted-foreground); font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }
.est { font-size: 11px; }
.chev { width: 7px; height: 7px; border: solid var(--muted-foreground); border-width: 0 1.5px 1.5px 0; transform: rotate(-45deg);
  align-self: center; opacity: .55; }
details[open] > summary > .chev { transform: rotate(45deg); }
.today .act { font-weight: 600; }
.today .eff { color: var(--foreground); }
.today .chip.due { color: var(--foreground); }
.today .chip.late { background: var(--destructive-surface); border-color: transparent; color: var(--destructive); }

.row[open] { background: var(--card); border-color: var(--border); margin: 8px 0; box-shadow: 0 1px 2px rgb(0 0 0 / .05); }
.row[open] > summary { border-bottom: 1px solid var(--border); border-radius: var(--radius) var(--radius) 0 0; }
.row[open] .meta { white-space: normal; }
.body { padding: 14px 16px 16px 44px; display: flex; flex-direction: column; gap: 14px; font-size: 13px; }
.items, .members { display: flex; flex-direction: column; gap: 6px; }
.members { gap: 18px; }
.member { display: flex; flex-direction: column; gap: 10px; }
.member + .member { border-top: 1px solid var(--border); padding-top: 16px; }
.item { overflow-wrap: anywhere; padding-left: 1.5em; text-indent: -1.5em; }
.item .id { font: 12px var(--font-mono); white-space: nowrap; margin-right: 6px; }
.m { font-size: 12px; color: var(--muted-foreground); white-space: nowrap; margin-left: 8px; }
a.m { color: var(--info); }
.refs { display: flex; flex-wrap: wrap; gap: 2px 10px; align-items: baseline; font: 12px var(--font-mono); }
.lbl { font: 600 11px var(--font-sans); text-transform: uppercase; letter-spacing: .06em; color: var(--muted-foreground); }
.draft { display: flex; flex-direction: column; gap: 6px; }
textarea { display: block; width: 100%; resize: vertical; font: 12.5px/1.55 var(--font-mono); padding: 10px 12px;
  color: var(--foreground); background: var(--background); border: 1px solid var(--border); border-radius: 6px; }
textarea[readonly] { background: transparent; }
.bar { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; font-size: 12.5px; color: var(--muted-foreground); }
.btn { font: 600 12.5px var(--font-sans); padding: 5px 14px; border-radius: 6px; border: 1px solid var(--foreground);
  background: var(--foreground); color: var(--background); cursor: pointer; }
.btn:disabled { cursor: progress; }
a.btn { background: transparent; color: var(--foreground); border-color: var(--border); text-decoration: none; }
.perr { color: var(--destructive); }
.cmds { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.cmds .lbl { margin-right: 4px; }
.cmd { font: 11.5px var(--font-mono); padding: 3px 9px; border-radius: 5px; border: 1px solid var(--border);
  background: transparent; color: var(--muted-foreground); cursor: copy; }
.cmd:hover { color: var(--foreground); border-color: var(--muted-foreground); }

.later { display: flex; flex-direction: column; gap: 14px; }
.cut { display: flex; align-items: center; gap: 12px; font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .08em; color: var(--muted-foreground); }
.cut::before, .cut::after { content: ""; flex: 1; border-top: 1px dashed var(--muted-foreground); opacity: .5; }
.later > h2 { font-size: 19px; font-weight: 650; letter-spacing: -.01em; padding: 0 12px; display: flex; gap: 12px;
  justify-content: space-between; align-items: baseline; }
.later .grp + .grp, .fold .grp + .grp { margin-top: 18px; }
.later .gh, .fold .gh { padding-bottom: 6px; }
.later .gh h3, .fold .gh h3 { font-size: 13px; font-weight: 600; letter-spacing: 0; color: var(--muted-foreground); }
.later .gh h3::before, .fold .gh h3::before { display: none; }

.folds { display: flex; flex-direction: column; border-bottom: 1px solid var(--border); }
.fold { border-top: 1px solid var(--border); }
.fold > summary { list-style: none; cursor: pointer; display: flex; align-items: center; gap: 10px; padding: 13px 12px; }
.fold > summary::-webkit-details-marker { display: none; }
.fold > summary:hover { background: var(--accent); }
.fold h2 { font-size: 15px; font-weight: 600; }
.fold > summary .chev { margin-left: auto; }
.fold[open] { padding-bottom: 18px; }
.fold > .grp:first-of-type { margin-top: 8px; }
.empty { color: var(--muted-foreground); }

footer { display: flex; flex-direction: column; gap: 8px; }
footer h2 { font: 600 11px var(--font-sans); text-transform: uppercase; letter-spacing: .06em; color: var(--muted-foreground); }
.src { display: flex; flex-wrap: wrap; gap: 4px 20px; font-size: 13px; color: var(--muted-foreground); }
.src span { font-variant-numeric: tabular-nums; }
.src .late, .src .late a, .src .late span { color: var(--warning); font-weight: 600; }

@media (max-width: 520px) {
  body { padding-block: 24px 56px; }
  .wrap { gap: 32px; }
  h1 { font-size: 24px; }
  .gh, .later > h2 { padding-inline: 4px; }
  .row > summary { grid-template-columns: 16px minmax(0, 1fr) auto; gap: 0 10px; padding-inline: 4px; }
  .row > summary > .chev { display: none; }
  .row[open] > summary { padding-inline: 10px; }
  .body { padding: 12px; }
  .fold > summary { padding-inline: 4px; }
  .legend .free { margin-left: 0; }
}
@media (prefers-reduced-motion: no-preference) {
  .row > summary, .fold > summary { transition: background-color .12s; }
  .chev { transition: transform .12s; }
}
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
const BUILD_URL = location.pathname.replace(/\\.html$/, ".build.json");
// The first id polled after load is the baseline: the page's own id can trail a build that finished just after it.
let BUILD = null;
setInterval(async () => {
  if ([...document.querySelectorAll(".draft textarea")].some(dirty)) return;
  let id;
  try { id = (await (await fetch(BUILD_URL, {cache: "no-store"})).json()).id; } catch (e) { return; }
  if (BUILD === null || id === BUILD) { BUILD = id; return; }
  store(session, OPEN, JSON.stringify([...document.querySelectorAll("details[open]")].map(d => d.id).filter(Boolean)));
  location.reload();
}, 60000);
"""


if __name__ == "__main__":
    main()
