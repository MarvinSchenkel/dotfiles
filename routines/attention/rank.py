"""Rules engine of the attention queue: turns normalized asks into ranked rows.

Pure: no I/O and no clock, `now` is always passed in. `rank()` runs the pipeline
gate, collapse, tier, park, batch, order, cut. Thresholds and vocabulary sit on top.
"""

import warnings
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from enum import IntEnum

ME = "MarvinSchenkel"
BOTS = frozenset({
    "github-actions", "coderabbitai", "musicassistant-bot", "copilot-pull-request-reviewer", "Copilot",
    "Bot-MArley",
})

# Thresholds
CUT_MIN = 240  # minutes of live work above the "today" line
PARK_DAYS = 14
DUE_DAYS = 14  # a deadline this close (after lead time) promotes into Act
UNBLOCK_MAX_MIN = 10
BATCH_MAX_MIN = 30  # cap of the small approvals batch
HIGH_AFFECTED = 3  # collectors: distinct affected users that make impact high
SWEEP_ROWS = 5  # attention thread: parked rows per weekly sweep
DEFER_HORIZON_DAYS = 60  # a deferred advisory comes back this long before its deadline
SSVC_LEAD_DAYS = {"decide_fix": 45, "review_fix": 21, "merge_fix": 21, "publish": 0}
DEFAULT_EFFORT = {"reply": 10, "input": 20, "design": 30, "merge": 10, "nudge": 10, "review": 20, "post": 5,
                  "log_finding": 5}
APPROVE_EFFORT = {"S": 5, "M": 10, "L": 20, "XL": 40}
OTHER_EFFORT = 15  # any action without a default above
_LAST = datetime.max.replace(tzinfo=UTC)

# SSVC supplier outcomes, lowest first
DEFER, SCHEDULED, OUT_OF_CYCLE, IMMEDIATE = "Defer", "Scheduled", "Out-of-cycle", "Immediate"
OUTCOMES = (DEFER, SCHEDULED, OUT_OF_CYCLE, IMMEDIATE)
SAFETY_REACHES = frozenset({"ha_control", "host"})
# (exploitation, utility) -> outcome per column (partial, minimal), (partial, significant),
# (total, minimal), (total, significant). Value density is always diffuse for MA, so utility is
# never super effective.
SSVC_TABLE = {
    ("none", "laborious"): (DEFER, SCHEDULED, SCHEDULED, OUT_OF_CYCLE),
    ("none", "efficient"): (SCHEDULED, OUT_OF_CYCLE, SCHEDULED, OUT_OF_CYCLE),
    ("public_poc", "laborious"): (SCHEDULED, OUT_OF_CYCLE, SCHEDULED, IMMEDIATE),
    ("public_poc", "efficient"): (SCHEDULED, IMMEDIATE, OUT_OF_CYCLE, IMMEDIATE),
    ("active", "laborious"): (OUT_OF_CYCLE, IMMEDIATE, OUT_OF_CYCLE, IMMEDIATE),
    ("active", "efficient"): (OUT_OF_CYCLE, IMMEDIATE, OUT_OF_CYCLE, IMMEDIATE),
}

# Vocabulary
ISSUE_KINDS = frozenset({"issue", "discussion"})
MERGE_RELS = frozenset({"fixes", "advisory_fix", "duplicate_of"})
SEE_ALSO_RELS = frozenset({"related", "follow_up"})
ANSWERS = frozenset({"reply", "post", "input", "design", "decide"})  # Unblock when quick and someone waits
LAND_ACTIONS = frozenset({"approve", "merge", "flip"})
DECIDE_ACTIONS = frozenset({
    "review", "rereview", "decide", "design", "input", "reply",
    "ack_coordinator", "decide_fix", "review_fix", "merge_fix", "backport_decision", "review_backport",
})
CHORE_STEPS = frozenset({"set_ranges", "cve", "credit", "publish"})  # advisory publish chores
TITLE_KINDS = frozenset({"release", "lab", "log"})  # no GitHub-style id, so the title is the sentence
ACTION_TEXT = {
    "review": "Review {id}", "rereview": "Re-review {id}", "approve": "Approve {id}", "merge": "Merge {id}",
    "flip": "Mark {id} ready for review", "decide": "Decide on {id}", "reply": "Reply on {id}",
    "post": "Post the drafted reply on {id}", "input": "Give input on {id}",
    "design": "Make the design call on {id}", "nudge": "Send a nudge on {id}",
    "pick": "Cherry-pick the missing PRs for {id}", "investigate": "Investigate {id}",
    "lab_error": "Fix the lab error {id}", "log_finding": "Look at {id}",
    "ack_coordinator": "Acknowledge the report on {id}", "decide_fix": "Decide the fix for {id}",
    "review_fix": "Review the fix for {id}", "merge_fix": "Merge the fix for {id}",
    "backport_decision": "Decide the backport of {id}", "review_backport": "Review the backport of {id}",
    "set_ranges": "Set the affected versions on {id}", "cve": "Request a CVE for {id}",
    "credit": "Credit the reporter on {id}", "publish": "Publish {id}",
}
WHO_TEXT = {"reply": "Answer {who} on {id}", "post": "Post the reply to {who} on {id}"}
BATCH_TEXT = {
    "batch:approve": ("Approve {n} small PRs", "small, review done"),
    "batch:drafts": ("Post {n} drafted replies", "drafted, nobody waits"),
    "batch:publish-now": ("Finish publishing {n} advisories", "fix shipped"),
    "batch:publish-later": ("Finish publishing {n} advisories when {release} ships", "after {release} ships"),
    "batch:lab-errors": ("Fix {n} lab errors", "reds read as lab errors"),
    "batch:log-findings": ("Look at {n} log findings", "seen in the last nightly"),
}


class Tier(IntEnum):
    ACT = 0
    UNBLOCK = 1
    LAND = 2
    DECIDE = 3
    KEEP_WARM = 4

    @property
    def label(self) -> str:
        return self.name.replace("_", " ").capitalize()


@dataclass(frozen=True)
class PRFacts:
    """GitHub facts of a PR, as the collector read them from the cache."""

    author: str
    draft: bool
    review_decision: str | None  # GitHub reviewDecision
    merge_state: str | None  # GitHub mergeStateStatus
    ci: str  # green | red | pending | none
    unresolved_threads: int
    marley_approved_head: bool  # Bot-MArley's review approves the current head commit
    my_last_at: datetime | None  # Marvin's newest comment, review, push or ready event
    other_last_at: datetime | None  # the same for any other human
    my_said_at: datetime | None  # Marvin's newest comment or review
    author_last_at: datetime | None  # the PR author's newest comment, review, push or ready event
    question_for_me: bool  # a human @-mentioned Marvin after my_said_at

    @property
    def own(self) -> bool:
        return self.author == ME


@dataclass(frozen=True)
class Ask:
    """One thing a routine wants from Marvin, normalized by a collector."""

    id: str  # canonical id
    kind: str  # pr | issue | discussion | advisory | lab | log | release
    src: str  # source name
    title: str
    url: str
    action: str  # key of ACTION_TEXT; advisories use their next remaining step
    effort: int | None = None  # minutes; None shows the default as an estimate
    detail_url: str | None = None
    author: str | None = None
    who_waits: str | None = None  # login of the person waiting on Marvin
    waiting_since: datetime | None = None  # when who_waits started waiting
    last_speaker: str | None = None  # issues: login of the newest human comment
    last_activity: datetime | None = None  # newest human event by anyone
    open: bool = True
    waiting_on: str | None = None  # reporter | team | release: not his turn
    step_owner: str | None = None  # advisories: "marvin" or a login
    pr: PRFacts | None = None
    flagged: bool | None = None  # pr-review card: the routine marks it for Marvin; None without a card
    checked_at: datetime | None = None  # pr-review card: when the routine last looked
    size: str | None = None  # S | M | L | XL
    impact_high: bool = False
    regression_stable: bool = False
    due: date | None = None
    ssvc_outcome: str | None = None  # from ssvc_outcome()
    ships_in: str | None = None  # publish chores: release the chore waits for
    draft_reply: str | None = None
    low_impact: bool = False
    links: list[dict[str, str]] = field(default_factory=list)  # {id, rel, src}
    blocked_by: list[str] = field(default_factory=list)
    snooze: dict | None = None  # {"until": date, "reason": str}
    pending: str | None = None  # forwarded command not yet handled


@dataclass
class Row:
    """One line on the page: a work item or a batch, its member asks with the act-on ask first."""

    id: str
    tier: Tier
    rule: str  # the rule that set the tier
    members: list[Ask]
    action: str  # human sentence
    effort: int
    who_waits: str | None = None
    waiting_since: datetime | None = None
    due: date | None = None
    blocked_by: list[str] = field(default_factory=list)
    see_also: list[str] = field(default_factory=list)
    reason: str = ""
    state: str = "live"  # live | blocked | parked | snoozed
    cut: bool = False  # live and below the CUT_MIN line


def rank(asks: list[Ask], now: datetime) -> list[Row]:
    """Every row that passed the gate, in final order, with state, reason and cut set."""
    asks = [replace(ask, action=_checked_action(ask)) for ask in asks]
    on = {ask.id for ask in asks if gate(ask, now)}
    open_ids = {ask.id for ask in asks if ask.open}
    rows = [_row(cluster, now) for cluster in collapse(asks, on)]
    for row in rows:
        row.state = _state(row, open_ids, now)
    rows = order(batch(rows))
    for row in rows:
        row.reason = reason(row, now)
    return cut(rows)


def ssvc_outcome(ssvc: dict, exposure: dict, chained_reaches: Iterable[str] = ()) -> str:
    """SSVC supplier outcome of an advisory: Defer, Scheduled, Out-of-cycle or Immediate.

    `ssvc` and `exposure` are the advisory's state fields; `chained_reaches` holds the `reaches`
    of open `chain_with` advisories on the same release.
    """
    automatable = exposure["auth"] == "none" and exposure["config"] == "default" and not exposure["user_action"]
    utility = "efficient" if automatable else "laborious"
    total = ssvc["technical_impact"] == "total"
    significant = any(reach in SAFETY_REACHES for reach in (ssvc["reaches"], *chained_reaches))
    return SSVC_TABLE[(ssvc["exploitation"], utility)][2 * total + significant]


def gate(ask: Ask, now: datetime) -> bool:
    """True when it is Marvin's turn on the ask. Snoozes are not checked here."""
    if not ask.open or ask.waiting_on is not None:
        return False
    if ask.pr is not None:
        return _pr_turn(ask)
    if ask.kind == "advisory":
        return ask.step_owner == "marvin" and not _deferred(ask, now)
    if ask.kind in ISSUE_KINDS:
        # A nudge exists because Marvin spoke last and nobody answered.
        return ask.draft_reply is not None or ask.action == "nudge" or _other_human(ask.last_speaker)
    return True


def collapse(asks: list[Ask], on: set[str]) -> list[list[Ask]]:
    """Linked asks grouped into work items, act-on ask first; only items with an ask that is on."""
    parent = {ask.id: ask.id for ask in asks}
    for ask in asks:
        for link in ask.links:
            if link["rel"] in MERGE_RELS:
                # A target without an ask (a merged fix PR) still joins the asks that link to it.
                parent.setdefault(link["id"], link["id"])
                parent[_root(parent, ask.id)] = _root(parent, link["id"])
    groups: dict[str, list[Ask]] = {}
    for ask in asks:
        groups.setdefault(_root(parent, ask.id), []).append(ask)
    clusters = []
    for members in groups.values():
        candidates = [ask for ask in members if ask.id in on]
        if candidates:
            act = min(candidates, key=_act_on_rank)
            clusters.append([act, *(ask for ask in members if ask is not act)])
    return clusters


def tier(cluster: list[Ask], now: datetime) -> tuple[Tier, str]:
    """Tier of a work item and the name of the rule that set it, first match wins."""
    act = cluster[0]
    if _outcome(cluster) in (OUT_OF_CYCLE, IMMEDIATE) and act.action not in CHORE_STEPS:
        return Tier.ACT, "ssvc"
    if _deadline_near(cluster, now):
        return Tier.ACT, "due"
    if any(ask.regression_stable and ask.impact_high for ask in cluster):
        return Tier.ACT, "regression"
    if act.action == "investigate":
        return Tier.ACT, "lab_red"
    if _quick_answer(act):
        return Tier.UNBLOCK, "quick_answer"
    if act.action == "pick":
        return Tier.KEEP_WARM, "pick"  # done in bulk before a release
    if act.action in LAND_ACTIONS:
        return Tier.LAND, act.action
    if act.action in DECIDE_ACTIONS and not act.low_impact:
        return Tier.DECIDE, "call"
    return Tier.KEEP_WARM, "chore"


def park(row: Row, now: datetime) -> bool:
    """True when a Decide or Keep warm row idled PARK_DAYS and no PR author or teammate waits on it."""
    last = _last_activity(row)
    return (
        row.tier >= Tier.DECIDE
        and not _person_blocked(row)
        and last is not None
        and now - last >= timedelta(days=PARK_DAYS)
    )


def batch(rows: list[Row]) -> list[Row]:
    """Rows with small approvals and Keep warm chores folded into batch rows."""
    rows = _fold(rows, "batch:approve", _approval_batch(rows))
    groups: dict[str, list[Row]] = {}
    for row in rows:
        batch_id = _chore_batch(row)
        if batch_id:
            groups.setdefault(batch_id, []).append(row)
    for batch_id, picked in groups.items():
        rows = _fold(rows, batch_id, picked)
    return rows


def order(rows: list[Row]) -> list[Row]:
    """Rows by tier and the tier's own order, each moved below the rows it is blocked by."""
    return _respect_blockers(sorted(rows, key=lambda row: (row.tier, _tier_key(row))))


def cut(rows: list[Row]) -> list[Row]:
    """The same rows with `cut` set on live rows below CUT_MIN cumulative minutes."""
    total = 0
    for row in rows:
        if row.state == "live":
            total += row.effort
            row.cut = total > CUT_MIN
    return rows


def reason(row: Row, now: datetime) -> str:
    """One short line naming the rule that placed the row."""
    act = row.members[0]
    if row.rule == "batch":
        return BATCH_TEXT[row.id][1].format(release=act.ships_in)
    waits = _waits(row, now)
    match row.rule:
        case "ssvc":
            return f"{_outcome(row.members)}, your step"
        case "due":
            return f"due {row.due:%m-%d}"
        case "regression":
            return "stable regression, high impact"
        case "lab_red":
            return "dev regression in the lab"
        case "quick_answer":
            return f"{waits}, quick answer"
        case "merge":
            if act.kind == "release":
                return "release PR"
            return "approved, CI green, clean" if act.pr else "ready to merge"
        case "flip":
            return "CI green, Bot-MArley approved the head"
        case "approve":
            return "review done, ready for your approval"
        case "pick":
            return "the release waits on these picks"
        case "call":
            return f"{waits} on your call" if waits else "needs your call"
    return "low impact" if act.low_impact else waits or "nobody waits on this"


def short_id(id: str) -> str:
    """Id as shown in text: no `music-assistant/` owner, GHSA ids by their second group."""
    if id.startswith("GHSA-"):
        return id.split("-")[1]
    return id.removeprefix("music-assistant/")


def effort_of(ask: Ask) -> int:
    """Minutes the ask takes, its own estimate first, else the default for its action."""
    if ask.effort is not None:
        return ask.effort
    if ask.action == "approve":
        return APPROVE_EFFORT.get(ask.size, OTHER_EFFORT)
    return DEFAULT_EFFORT.get(ask.action, OTHER_EFFORT)


def _checked_action(ask: Ask) -> str:
    """Action corrected by PR facts: own PRs by readiness, no merge on a PR that is not ready."""
    pr = ask.pr
    if pr is None:
        return ask.action
    if pr.own:
        return "merge" if _ready_to_merge(pr) else "flip" if _ready_to_flip(pr) else "reply"
    if ask.action == "merge" and not _ready_to_merge(pr):
        return "reply" if pr.unresolved_threads else "review"
    return ask.action


def _pr_turn(ask: Ask) -> bool:
    """Marvin's turn on a PR: his own by its facts, a carded one by the routine's flag, the rest by events."""
    pr = ask.pr
    if pr.own:
        return _ready_to_merge(pr) or _ready_to_flip(pr) or _newer(pr.other_last_at, pr.my_last_at)
    if ask.flagged is not None:
        # His comment after the routine's last look answers the flag until the author moves again.
        answered = _newer(pr.my_said_at, ask.checked_at) and _newer(pr.my_said_at, pr.author_last_at)
        return ask.flagged and not answered
    if pr.draft:
        return pr.question_for_me
    return not _newer(pr.my_said_at, pr.author_last_at)


def _ready_to_merge(pr: PRFacts) -> bool:
    """Approved, CI green, clean merge state and no open threads."""
    approved = pr.review_decision == "APPROVED" or (pr.own and pr.marley_approved_head)
    return (
        not pr.draft and approved and pr.ci == "green" and pr.merge_state == "CLEAN" and pr.unresolved_threads == 0
    )


def _ready_to_flip(pr: PRFacts) -> bool:
    """Own draft with CI green and Bot-MArley approval on the head."""
    return pr.own and pr.draft and pr.ci == "green" and pr.marley_approved_head


def _deferred(ask: Ask, now: datetime) -> bool:
    """Defer outcome, no fix in hand and no deadline within DEFER_HORIZON_DAYS."""
    near = ask.due is not None and (ask.due - now.date()).days <= DEFER_HORIZON_DAYS
    return ask.ssvc_outcome == DEFER and ask.action == "decide_fix" and not near


def _other_human(login: str | None) -> bool:
    """A human other than Marvin."""
    return login is not None and login != ME and not (login in BOTS or login.endswith("[bot]"))


def _newer(a: datetime | None, b: datetime | None) -> bool:
    """a happened and after b (or b never happened)."""
    return a is not None and (b is None or a > b)


def _root(parent: dict[str, str], id: str) -> str:
    """Union-find root."""
    while parent[id] != id:
        id = parent[id]
    return id


def _act_on_rank(ask: Ask) -> tuple[int, bool, int]:
    """Act-on preference: PR, then canonical advisory, then the rest; the larger step among equals."""
    kind_rank = {"pr": 0, "advisory": 1}.get(ask.kind, 2)
    return kind_rank, any(link["rel"] == "duplicate_of" for link in ask.links), -effort_of(ask)


def _row(cluster: list[Ask], now: datetime) -> Row:
    """Row for one work item."""
    act = cluster[0]
    row_tier, rule = tier(cluster, now)
    ids = {ask.id for ask in cluster}
    blockers = [b for ask in cluster for b in ask.blocked_by + _link_ids(ask, {"blocked_by"})]
    see_also = [i for ask in cluster for i in _link_ids(ask, SEE_ALSO_RELS)]
    return Row(
        id=act.id, tier=row_tier, rule=rule, members=cluster, action=_sentence(cluster), effort=effort_of(act),
        who_waits=act.who_waits, waiting_since=act.waiting_since,
        due=min((ask.due for ask in cluster if ask.due), default=None),
        blocked_by=_unique(b for b in blockers if b not in ids),
        see_also=_unique(i for i in see_also if i not in ids),
    )


def _link_ids(ask: Ask, rels: Iterable[str]) -> list[str]:
    """Ids of the ask's links with one of these rels."""
    return [link["id"] for link in ask.links if link["rel"] in rels]


def _unique(ids: Iterable[str]) -> list[str]:
    """Ids without repeats, first seen first."""
    return list(dict.fromkeys(ids))


def _sentence(cluster: list[Ask]) -> str:
    """Action sentence of a work item."""
    act = cluster[0]
    if act.kind in TITLE_KINDS:
        return act.title
    template = (act.who_waits and WHO_TEXT.get(act.action)) or ACTION_TEXT[act.action]
    text = template.format(id=short_id(act.id), who=act.who_waits)
    resolves = [short_id(ask.id) for ask in cluster[1:] if ask.kind != "pr"]
    if act.kind == "pr" and resolves:
        text += f", it resolves {', '.join(resolves)}"
    return text


def _outcome(cluster: list[Ask]) -> str | None:
    """Highest SSVC outcome in the work item."""
    outcomes = [ask.ssvc_outcome for ask in cluster if ask.ssvc_outcome]
    return max(outcomes, key=OUTCOMES.index, default=None)


def _deadline_near(cluster: list[Ask], now: datetime) -> bool:
    """Some member must move within DUE_DAYS, counting the lead time of its step."""
    move_by = [ask.due - timedelta(days=SSVC_LEAD_DAYS.get(ask.action, 0)) for ask in cluster if ask.due]
    return any((day - now.date()).days <= DUE_DAYS for day in move_by)


def _quick_answer(ask: Ask) -> bool:
    """Someone waits on an answer that takes at most UNBLOCK_MAX_MIN."""
    return (
        ask.who_waits is not None
        and ask.action in ANSWERS
        and not ask.low_impact
        and effort_of(ask) <= UNBLOCK_MAX_MIN
    )


def _state(row: Row, open_ids: set[str], now: datetime) -> str:
    """Display state of a fresh work item row."""
    snooze = row.members[0].snooze
    if snooze and now.date() < snooze["until"]:
        return "snoozed"
    if any(b in open_ids for b in row.blocked_by):
        return "blocked"
    return "parked" if park(row, now) else "live"


def _last_activity(row: Row) -> datetime | None:
    """Newest human activity over the row's members."""
    return max((ask.last_activity for ask in row.members if ask.last_activity), default=None)


def _person_blocked(row: Row) -> bool:
    """A PR author or teammate, not a reporter, waits on Marvin."""
    return row.who_waits is not None and row.members[0].kind not in ISSUE_KINDS


def _impact(row: Row) -> bool:
    """Any member has high impact."""
    return any(ask.impact_high for ask in row.members)


def _approval_batch(rows: list[Row]) -> list[Row]:
    """Small approvals that fit in BATCH_MAX_MIN, smallest first."""
    candidates = sorted((row for row in rows if _small_approval(row)), key=lambda row: row.effort)
    picked, total = [], 0
    for row in candidates:
        if total + row.effort <= BATCH_MAX_MIN:
            picked.append(row)
            total += row.effort
    return picked


def _small_approval(row: Row) -> bool:
    """Live Land approval of size S or M on someone else's PR without high impact."""
    act = row.members[0]
    return (
        row.state == "live"
        and row.tier is Tier.LAND
        and act.action == "approve"
        and act.size in ("S", "M")
        and not (act.pr and act.pr.own)
        and not _impact(row)
    )


def _chore_batch(row: Row) -> str | None:
    """Batch id of a live Keep warm chore row."""
    if row.state != "live" or row.tier is not Tier.KEEP_WARM or row.rule == "batch":
        return None
    action = row.members[0].action
    if action in CHORE_STEPS:
        return "batch:publish-later" if row.members[0].ships_in else "batch:publish-now"
    return {"post": "batch:drafts", "lab_error": "batch:lab-errors", "log_finding": "batch:log-findings"}.get(action)


def _fold(rows: list[Row], batch_id: str, picked: list[Row]) -> list[Row]:
    """Rows with the picked ones replaced by one batch row, when at least two were picked."""
    if len(picked) < 2:
        return rows
    members = [row.members[0] for row in picked]
    sentence = BATCH_TEXT[batch_id][0].format(n=len(picked), release=members[0].ships_in)
    folded = Row(
        id=batch_id, tier=picked[0].tier, rule="batch", members=members, action=sentence,
        effort=sum(row.effort for row in picked),
        waiting_since=min((row.waiting_since for row in picked if row.waiting_since), default=None),
        due=min((row.due for row in picked if row.due), default=None),
    )
    picked_ids = {row.id for row in picked}
    return [row for row in rows if row.id not in picked_ids] + [folded]


def _waits(row: Row, now: datetime) -> str:
    """Text like 'alice waits 14 d', empty when nobody waits."""
    if row.who_waits is None:
        return ""
    if row.waiting_since is None:
        return f"{row.who_waits} waits"
    return f"{row.who_waits} waits {(now - row.waiting_since).days} d"


def _since(row: Row) -> datetime:
    """Start of the wait, falling back to the last activity; unknown sorts last."""
    return row.waiting_since or _last_activity(row) or _LAST


def _tier_key(row: Row) -> tuple:
    """Order inside the row's tier."""
    match row.tier:
        case Tier.ACT:
            return row.due or date.max, row.effort
        case Tier.LAND:
            return not _impact(row), row.effort
        case Tier.DECIDE:
            return not _person_blocked(row), not _impact(row), _since(row)
    return (_since(row),)


def _respect_blockers(rows: list[Row]) -> list[Row]:
    """Stable reorder so no row sits above a row it is blocked by; cycle edges are dropped."""
    owner = {ask.id: row.id for row in rows for ask in row.members}
    deps: dict[str, list[str]] = {}
    for row in rows:
        for blocker in row.blocked_by:
            target = owner.get(blocker)
            if target is None or target == row.id:
                continue
            if _reaches(deps, target, row.id):
                warnings.warn(f"blocked_by cycle: dropped {row.id} -> {target}", stacklevel=2)
                continue
            deps.setdefault(row.id, []).append(target)
    placed: list[Row] = []
    done: set[str] = set()
    pending = list(rows)
    while pending:
        nxt = next(row for row in pending if all(dep in done for dep in deps.get(row.id, ())))
        pending.remove(nxt)
        placed.append(nxt)
        done.add(nxt.id)
    return placed


def _reaches(deps: dict[str, list[str]], start: str, goal: str) -> bool:
    """goal is reachable from start over blocked_by edges."""
    stack, seen = [start], set()
    while stack:
        node = stack.pop()
        if node == goal:
            return True
        if node not in seen:
            seen.add(node)
            stack.extend(deps.get(node, ()))
    return False

