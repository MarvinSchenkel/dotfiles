"""Collectors of the attention queue: routine state files and the GitHub cache turned into asks.

`collect()` runs one adapter per source and applies the `attention.json` overrides, so `rank.py`
gets plain `Ask` objects and never reads a file.
"""
import json
import os
import re
import tempfile
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import rank
from rank import ME, Ask, PRFacts

ORG = "music-assistant"
SERVER = f"{ORG}/server"
SUPPORT = f"{ORG}/support"
REPORTS = "http://127.0.0.1:8765"
LOCAL = ZoneInfo("Europe/Amsterdam")
TZ_ABBR = {"CET": 1, "CEST": 2, "UTC": 0}
SOURCES = ("pr-review", "issue-triage", "security-inbox", "lab-deep", "triage-ma-nightly")
# Derived rows have no routine; commands on them go to the pr-review thread.
OWNER = {"github": "pr-review", "release": "pr-review"}
ISSUE_ACTIONS = {"reply-test": "reply", "reply-info": "reply", "reply-answer": "reply"}
PUBLISH_STEPS = rank.CHORE_STEPS | {"reply"}
BACKPORT_STEPS = frozenset({"backport_decision", "review_backport"})
LOCAL_STAMP = re.compile(r"(\d{4}-\d\d-\d\d \d\d:\d\d) ([A-Z]+)")


def collect(state_dir: Path, cache: dict, attention: dict, now: datetime) -> list[Ask]:
    """Every ask of every source, with snoozes, due dates, blockers and pending commands applied."""
    states = load_states(state_dir)
    backport = (cache.get("release") or {}).get("backport_pr")
    asks = pr_review_asks(states["pr-review"], cache) + issue_asks(states["issue-triage"])
    carded = _card_ids(states) | {backport}
    asks += security_asks(states["security-inbox"], cache, carded)
    asks += lab_asks(states["lab-deep"]) + nightly_asks(states["triage-ma-nightly"])
    asks += release_asks(cache, states["security-inbox"])
    skipped = {f"{ORG}/{ref}" for ref in states["pr-review"].get("skip") or {}}
    asks += github_asks(cache, carded | skipped | {ask.id for ask in asks})
    runs = {source: last_run(state) for source, state in states.items()}
    return apply_overrides(asks, attention, runs)


def load_states(state_dir: Path) -> dict[str, dict]:
    """State of each routine by source name; a routine that never wrote its file gives {}."""
    return {source: read_json(state_dir / f"{source}.json") for source in SOURCES}


def load_attention(path: Path) -> dict:
    """The attention thread's own state; {} when the file does not exist yet."""
    return read_json(path)


def save_attention(path: Path, data: dict) -> None:
    """Replace the attention thread's state in one atomic swap."""
    write_atomic(path, json.dumps(data, indent=1) + "\n")


def read_json(path: Path) -> dict:
    """JSON file contents, or {} when the file does not exist."""
    return json.loads(path.read_text()) if path.exists() else {}


def write_atomic(path: Path, text: str) -> None:
    """Write text through a temp file in the same directory and swap it in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def last_run(state: dict) -> datetime | None:
    """When the routine last ran, in UTC; a date-only stamp counts from local midnight."""
    raw = state.get("last_run_end") or state.get("last_run")
    if not raw:
        return None
    if m := LOCAL_STAMP.fullmatch(raw):
        offset = timezone(timedelta(hours=TZ_ABBR[m[2]]))
        return datetime.strptime(m[1], "%Y-%m-%d %H:%M").replace(tzinfo=offset).astimezone(UTC)
    if len(raw) == len("2026-11-11"):
        return datetime.combine(date.fromisoformat(raw), time(), LOCAL).astimezone(UTC)
    return _time(raw)


def apply_overrides(asks: list[Ask], attention: dict, runs: dict[str, datetime | None]) -> list[Ask]:
    """Asks with the attention.json snooze, due, blocked_by and pending entries applied by id.

    A manual due date only moves a due date earlier. A pending command shows only while it is newer
    than the last run of the routine that owns the ask.
    """
    out = []
    for ask in asks:
        changes: dict = {}
        if snooze := attention.get("snooze", {}).get(ask.id):
            changes["snooze"] = {"until": date.fromisoformat(snooze["until"]), "reason": snooze.get("reason", "")}
        if due := attention.get("due", {}).get(ask.id):
            manual = date.fromisoformat(due)
            changes["due"] = min(ask.due, manual) if ask.due else manual
        if blockers := attention.get("blocked_by", {}).get(ask.id):
            changes["blocked_by"] = list(dict.fromkeys(ask.blocked_by + blockers))
        pending = attention.get("pending", {}).get(ask.id)
        if pending and _after(_time(pending["at"]), runs.get(OWNER.get(ask.src, ask.src))):
            changes["pending"] = pending["cmd"]
        out.append(replace(ask, **changes) if changes else ask)
    return out


def pr_review_asks(state: dict, cache: dict) -> list[Ask]:
    """Open review cards: all of them with GitHub facts, else only those the routine marked."""
    backport = (cache.get("release") or {}).get("backport_pr")
    asks = []
    for card in state.get("prs", []):
        if card.get("state") != "open":
            continue
        id = f"{ORG}/{card['repo']}#{card['number']}"
        facts = cache.get("prs", {}).get(id)
        marked = card.get("status") == "attention" or card.get("needs_reply")
        if id != backport and (facts or marked):
            asks.append(pr_ask(id, facts, card))
    return asks


def pr_ask(id: str, facts: dict | None, card: dict | None = None, src: str = "pr-review") -> Ask:
    """Ask for a PR from its cache facts, its review card, or both."""
    card = card or {}
    facts = facts or {}
    needs = card.get("needs_reply") or {}
    pr = _pr_facts(facts, needs) if facts else None
    author = facts.get("author") or card.get("author")
    my_last = _time((facts.get("my_last") or {}).get("at"))
    other_last = _time((facts.get("other_last") or {}).get("at"))
    repo, number = id.split("#")
    return Ask(
        id=id, kind="pr", src=src, title=card.get("title") or facts.get("title", ""),
        url=card.get("url") or facts.get("url", ""), action=card.get("action") or _pr_action(pr, facts, needs),
        effort=card.get("effort"),
        detail_url=f"{REPORTS}/pr-review.html#pr-{repo.split('/')[1]}-{number}" if card else None,
        author=author, who_waits=needs.get("who") or (author if _other_human(author) else None),
        waiting_since=_time(needs.get("at") or card.get("attention_since")) or other_last,
        last_activity=max((t for t in (my_last, other_last) if t), default=None),
        open=facts.get("state", "OPEN") == "OPEN", pr=pr, size=card.get("size"),
        draft_reply=_unposted_draft(card.get("preread")),
        links=list(card.get("links") or []) + list(facts.get("links") or []),
        snooze=_card_snooze(card.get("snooze"), facts),
    )


def issue_asks(state: dict) -> list[Ask]:
    """Open triage cards with an ask or a drafted reply."""
    cards = state.get("cards", [])
    return [issue_ask(c) for c in cards if (c.get("ask") or c.get("reply")) and not (c.get("sync") or {}).get("closed")]


def issue_ask(card: dict) -> Ask:
    """Ask for one triage card; a drafted reply on a reply ask, or on a card without an ask, makes it `post`."""
    repo = card.get("repo") or SUPPORT
    sync = card.get("sync") or {}
    last = sync.get("last_human") or {}
    speaker = sync.get("last_speaker") or {}
    # When a human spoke last, last_human is that same comment and carries the team flag.
    reporter_spoke = speaker.get("login") not in (None, ME) and not speaker.get("bot") and not last.get("team")
    draft = card.get("reply") or None
    ask = card.get("ask")
    action = "post" if draft and (not ask or ask in ISSUE_ACTIONS) else ISSUE_ACTIONS.get(ask, ask)
    stable = (card.get("regression") or {}).get("on") == "stable"
    affected = (sync.get("impact") or {}).get("affected", 0)
    kind = "discussion" if card.get("discussion") else "issue"
    related = [{"id": f"{p['repo']}#{p['n']}", "rel": "related", "src": "sync"}
               for p in sync.get("pr") or [] if p.get("state") == "OPEN"]
    return Ask(
        id=f"{repo}#{card['n']}", kind=kind, src="issue-triage", title=card.get("title", ""),
        url=f"https://github.com/{repo}/{'discussions' if kind == 'discussion' else 'issues'}/{card['n']}",
        action=action, effort=card.get("effort"),
        detail_url=f"{REPORTS}/issue-triage.html?q={card['n']}#{_board_anchor(repo, card['n'])}",
        who_waits=speaker["login"] if reporter_spoke else None,
        waiting_since=_time(speaker.get("at")) if reporter_spoke else None,
        last_speaker=_speaker_login(speaker), last_activity=_time(last.get("at")),
        waiting_on=card.get("waiting_on") or _test_pending(sync, draft, action),
        impact_high=stable or affected >= rank.HIGH_AFFECTED, regression_stable=stable, draft_reply=draft,
        low_impact=kind == "discussion" or card.get("col") == "user" or action == "nudge",
        links=list(card.get("links") or []) + related,
    )


def security_asks(state: dict, cache: dict, carded: set[str]) -> list[Ask]:
    """Advisory asks, plus a PR ask for each cached fix PR that no review card covers."""
    advisories = {adv["id"]: adv for adv in state.get("advisories", [])}
    release = cache.get("release") or {}
    asks = [ask for adv in advisories.values() if (ask := advisory_ask(adv, advisories, release))]
    fix_ids = [_fix_id(p) for adv in advisories.values() for p in adv.get("fix_prs") or []]
    for id in dict.fromkeys(fix_ids):
        if id not in carded and id in cache.get("prs", {}):
            asks.append(pr_ask(id, cache["prs"][id], src="github"))
    return asks


def advisory_ask(adv: dict, advisories: dict[str, dict], release: dict) -> Ask | None:
    """Ask for one advisory; None once its remaining steps are done.

    An unassessed advisory (no `remaining_steps`) asks Marvin to decide the fix. A duplicate is never
    his turn itself; it takes the canonical advisory's next step so its deadlines get the same lead time.
    """
    canonical = adv.get("duplicate_of")
    steps = adv.get("remaining_steps")
    if canonical:
        steps = advisories.get(canonical, {}).get("remaining_steps") or [{"step": "decide_fix"}]
    elif steps == []:
        return None
    steps = steps or [{"step": "decide_fix", "owner": "marvin"}]
    step = steps[0]
    chore = all(s["step"] in PUBLISH_STEPS for s in steps)
    blocked = adv.get("blocked_since") or {}
    links = [{"id": _fix_id(p), "rel": "advisory_fix", "src": "model"} for p in adv.get("fix_prs") or []]
    if canonical:
        links.append({"id": canonical, "rel": "duplicate_of", "src": "model"})
    return Ask(
        id=adv["id"], kind="advisory", src="security-inbox", title=adv.get("title", ""), url=adv.get("url", ""),
        action="publish" if chore else step["step"],
        effort=(sum(s.get("effort") or 0 for s in steps) or None) if chore else step.get("effort"),
        detail_url=f"{REPORTS}/security-inbox.html#card-{adv['id']}",
        who_waits=blocked.get("who"), waiting_since=_day(blocked.get("since")),
        step_owner=None if canonical else step.get("owner"), due=_advisory_due(adv),
        ssvc_outcome=None if chore else _ssvc(adv, advisories),
        ships_in=_ships_in("publish" if chore else step["step"], adv, release), links=links,
    )


def lab_asks(state: dict) -> list[Ask]:
    """One ask per lab red: a server read is investigated, a lab read is a lab error to fix."""
    return [
        Ask(id=f"lab:{red['test']}", kind="lab", src="lab-deep",
            title=f"Investigate {red['test']} on dev" if red["read"] == "server" else f"Fix the lab error in {red['test']}",
            url=f"{REPORTS}/lab-deep.html", action="investigate" if red["read"] == "server" else "lab_error",
            last_activity=_day(red.get("since")))
        for red in state.get("reds", [])
    ]


def nightly_asks(state: dict) -> list[Ask]:
    """Log findings seen in the last nightly run that have no fix, are not resolved and not muted."""
    day = (state.get("last_run_end") or "")[:10]
    muted = set(state.get("muted") or [])
    return [
        Ask(id=f"log:{fp}", kind="log", src="triage-ma-nightly", title=f"Look at {f.get('title') or fp}",
            url=f"{REPORTS}/triage-ma-nightly.html", action="log_finding", last_activity=_day(f.get("last_seen")))
        for fp, f in (state.get("known") or {}).items()
        if f.get("last_seen") == day and not f.get("fix") and not f.get("resolved") and fp not in muted
    ]


def release_asks(cache: dict, security: dict) -> list[Ask]:
    """The backport merge ask and the missing picks ask of the pending release.

    The merge waits on the picks and on every advisory with a backport step left or a labelled fix PR
    that still has to reach the backport.
    """
    release = cache.get("release")
    if not release:
        return []
    merge_id = f"release:{release['version']}"
    picks_id = f"{merge_id}/picks"
    url = cache.get("prs", {}).get(release["backport_pr"], {}).get("url") or _pr_url(release["backport_pr"])
    # Open or listed as missing: a merged labelled PR that is neither is on stable already.
    pending = {id for id, pr in cache.get("prs", {}).items() if pr["state"] == "OPEN"}
    pending |= {f"{SERVER}#{m['number']}" for m in release["missing"]}
    waiting = [adv["id"] for adv in security.get("advisories", []) if _needs_backport(adv, pending)]
    missing = release["missing"]
    merge = Ask(id=merge_id, kind="release", src="release", title=f"Merge the {release['version']} backport PR",
                url=url, action="merge", blocked_by=([picks_id] if missing else []) + waiting)
    if not missing:
        return [merge]
    picks = Ask(id=picks_id, kind="release", src="release", url=url, action="pick",
                title=f"Cherry-pick {len(missing)} missing PRs into {release['version']}")
    return [merge, picks]


def github_asks(cache: dict, carded: set[str]) -> list[Ask]:
    """Review requests and mentions on items no routine covers; an issue only after a mention past his reply.

    A mentioned PR without his review requested is a reply; a mentioned issue asks for his input.
    """
    prs = cache.get("prs", {})
    mentions = cache.get("mentions", [])
    requested = cache.get("review_requested", [])
    pr_ids = requested + [m["id"] for m in mentions if m["is_pr"]]
    asks = []
    for id in dict.fromkeys(pr_ids):
        if id in carded or id not in prs:
            continue
        ask = pr_ask(id, prs[id], src="github")
        asks.append(ask if id in requested else replace(ask, action="reply"))
    for m in mentions:
        if m["is_pr"] or m["id"] in carded or not m.get("mention_after_mine"):
            continue
        other = m["other_last"]
        asks.append(Ask(
            id=m["id"], kind="issue", src="github", title=m["title"], url=m["url"], action="input", author=m["author"],
            who_waits=other["login"], waiting_since=_time(other["at"]), last_speaker=other["login"],
            last_activity=_time(other["at"]),
        ))
    return asks


def _card_ids(states: dict[str, dict]) -> set[str]:
    """Ids of every pr-review and issue-triage card, whatever its state."""
    prs = {f"{ORG}/{c['repo']}#{c['number']}" for c in states["pr-review"].get("prs", [])}
    issues = {f"{c.get('repo') or SUPPORT}#{c['n']}" for c in states["issue-triage"].get("cards", [])}
    return prs | issues


def _pr_facts(facts: dict, needs: dict) -> PRFacts:
    """rank.PRFacts from a cache entry and the card's needs_reply."""
    my_last = _time((facts.get("my_last") or {}).get("at"))
    marley = facts.get("reviews", {}).get("Bot-MArley") or {}
    return PRFacts(
        author=facts["author"], draft=facts["draft"], review_decision=facts.get("review_decision"),
        merge_state=facts.get("merge_state"), ci=facts["ci"], unresolved_threads=facts["unresolved_threads"],
        marley_approved_head=marley.get("state") == "APPROVED" and marley.get("commit") == facts.get("head"),
        my_last_at=my_last, other_last_at=_time((facts.get("other_last") or {}).get("at")),
        question_for_me=facts.get("mention_after_mine", False) or _after(_time(needs.get("at")), my_last),
    )


def _pr_action(pr: PRFacts | None, facts: dict, needs: dict) -> str:
    """Action of a PR without one on its card."""
    if (pr and pr.question_for_me) or (pr is None and needs):
        return "reply"
    return "rereview" if ME in facts.get("reviews", {}) else "review"


def _card_snooze(snooze: dict | None, facts: dict) -> dict | None:
    """rank snooze of a review card; `until: activity` holds until a push or another human's event."""
    if not snooze:
        return None
    if snooze["until"] != "activity":
        return {"until": date.fromisoformat(snooze["until"]), "reason": snooze.get("reason", "")}
    at = _time(snooze["at"])
    mine = facts.get("my_last") or {}
    pushed = mine.get("kind") == "push" and _after(_time(mine["at"]), at)
    if pushed or _after(_time((facts.get("other_last") or {}).get("at")), at):
        return None
    return {"until": date.max, "reason": snooze.get("reason", "")}


def _unposted_draft(preread: dict | None) -> str | None:
    """Draft reply of a pre-read that has not been posted."""
    if not preread or preread.get("posted"):
        return None
    return preread.get("draft_reply") or None


def _speaker_login(speaker: dict) -> str | None:
    """Login of the last speaker, with GitHub's `[bot]` suffix when sync.py saw a bot."""
    login = speaker.get("login")
    return f"{login}[bot]" if login and speaker.get("bot") and not login.endswith("[bot]") else login


def _needs_backport(adv: dict, pending: set[str]) -> bool:
    """A backport step is left, or a labelled fix PR still has to reach the backport."""
    steps = {s["step"] for s in adv.get("remaining_steps") or []}
    unpicked = any(p.get("backport_label") and _fix_id(p) in pending for p in adv.get("fix_prs") or [])
    return bool(steps & BACKPORT_STEPS) or unpicked


def _test_pending(sync: dict, draft: str | None, action: str) -> str | None:
    """`reporter` while a test ask is out that the reporter has not answered."""
    if sync.get("test_ask") and not sync.get("after_test_ask_reporter") and not draft and action != "nudge":
        return "reporter"
    return None


def _board_anchor(repo: str, n: int) -> str:
    """Element id of a card on the issue-triage board."""
    ref = "" if repo == SUPPORT else "core" if repo == "home-assistant/core" else repo.split("/")[-1]
    return "c-" + re.sub(r"[^a-z0-9]+", "-", f"{ref}#{n}".lower()).strip("-")


def _advisory_due(adv: dict) -> date | None:
    """Earliest deadline; an ack deadline stops counting once the ack went out."""
    dates = [date.fromisoformat(d["date"]) for d in adv.get("deadlines") or []
             if not (d["kind"] == "ack" and adv.get("ack_sent_at"))]
    return min(dates, default=None)


def _ssvc(adv: dict, advisories: dict[str, dict]) -> str | None:
    """SSVC outcome with the reach of open chained advisories; None before the inputs are recorded."""
    if not (adv.get("ssvc") and adv.get("exposure")):
        return None
    chained = [advisories[c]["ssvc"]["reaches"] for c in adv.get("chain_with") or []
               if c in advisories and advisories[c].get("ssvc") and advisories[c].get("remaining_steps") != []]
    return rank.ssvc_outcome(adv["ssvc"], adv["exposure"], chained)


def _ships_in(step: str, adv: dict, release: dict) -> str | None:
    """Release a publish chore waits for: one of its fix PRs is picked or missing on the backport."""
    if step not in rank.CHORE_STEPS or not release:
        return None
    pending = {f"{SERVER}#{n}" for n in release["picked"]} | {f"{SERVER}#{m['number']}" for m in release["missing"]}
    return release["version"] if any(_fix_id(p) in pending for p in adv.get("fix_prs") or []) else None


def _fix_id(pr: dict) -> str:
    """Canonical id of a fix_prs entry."""
    repo = pr["repo"] if "/" in pr["repo"] else f"{ORG}/{pr['repo']}"
    return f"{repo}#{pr['number']}"


def _pr_url(id: str) -> str:
    """GitHub URL of a PR id."""
    repo, number = id.split("#")
    return f"https://github.com/{repo}/pull/{number}"


def _other_human(login: str | None) -> bool:
    """A human other than Marvin."""
    return login is not None and login != ME and login not in rank.BOTS and not login.endswith("[bot]")


def _after(a: datetime | None, b: datetime | None) -> bool:
    """a happened and after b (or b never happened)."""
    return a is not None and (b is None or a > b)


def _time(value: str | None) -> datetime | None:
    """UTC datetime of an ISO time; a naive one counts as UTC."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)


def _day(value: str | None) -> datetime | None:
    """UTC midnight of an ISO date."""
    return datetime.combine(date.fromisoformat(value[:10]), time(), UTC) if value else None
