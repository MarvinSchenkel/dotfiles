from datetime import UTC, datetime, timedelta

import pytest

import rank
from rank import Tier

NOW = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
TODAY = NOW.date()
ISSUE = "music-assistant/support#90001"
PR = "music-assistant/server#90002"
ADV = "GHSA-test-0001"


def ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def link(id: str, rel: str) -> dict[str, str]:
    return {"id": id, "rel": rel, "src": "model"}


def facts(**kw: object) -> rank.PRFacts:
    base = {
        "author": "alice", "draft": False, "review_decision": None, "merge_state": "CLEAN",
        "ci": "green", "unresolved_threads": 0, "marley_approved_head": False,
        "my_last_at": None, "other_last_at": ago(1), "question_for_me": False,
    }
    return rank.PRFacts(**(base | kw))


def issue(id: str = ISSUE, action: str = "reply", **kw: object) -> rank.Ask:
    base = {"last_speaker": "alice", "who_waits": "alice", "waiting_since": ago(1), "last_activity": ago(1)}
    return rank.Ask(id=id, kind="issue", src="issue-triage", title="t", url="u", action=action, **(base | kw))


def pull(id: str = PR, action: str = "review", pr: rank.PRFacts | None = None, **kw: object) -> rank.Ask:
    base = {"who_waits": "alice", "waiting_since": ago(1), "last_activity": ago(1)}
    return rank.Ask(
        id=id, kind="pr", src="pr-review", title="t", url="u", action=action, pr=pr or facts(), **(base | kw)
    )


def advisory(id: str = ADV, action: str = "review_fix", **kw: object) -> rank.Ask:
    base = {"step_owner": "marvin", "ssvc_outcome": rank.SCHEDULED, "last_activity": ago(1)}
    return rank.Ask(id=id, kind="advisory", src="security-inbox", title="t", url="u", action=action, **(base | kw))


def chore(id: str, action: str, **kw: object) -> rank.Ask:
    kind = "lab" if id.startswith("lab:") else "log"
    return rank.Ask(id=id, kind=kind, src="lab-deep", title="t", url="u", action=action, **kw)


def rows_by_id(asks: list[rank.Ask]) -> dict[str, rank.Row]:
    return {row.id: row for row in rank.rank(asks, NOW)}


# gate


@pytest.mark.parametrize("bot", ["github-actions[bot]", "Bot-MArley"])
def test_info_ask_where_bot_spoke_last_is_off(bot: str) -> None:
    assert not rank.gate(issue(last_speaker=bot, who_waits=None), NOW)


def test_marvin_spoke_last_without_draft_is_off() -> None:
    assert not rank.gate(issue(last_speaker=rank.ME, who_waits=None), NOW)


@pytest.mark.parametrize("waiting_on", ["reporter", "team", "release"])
def test_ask_waiting_on_someone_else_is_off(waiting_on: str) -> None:
    assert not rank.gate(issue(waiting_on=waiting_on), NOW)


def test_drafted_replies_after_the_bot_fold_into_one_keep_warm_row() -> None:
    asks = [
        issue(f"music-assistant/support#9000{n}", "post", last_speaker="github-actions[bot]", who_waits=None,
              draft_reply="text")
        for n in range(3)
    ]
    [row] = rank.rank(asks, NOW)
    assert (row.id, row.tier, row.action) == ("batch:drafts", Tier.KEEP_WARM, "Post 3 drafted replies")


def test_unapproved_behind_pr_with_open_thread_is_not_merge() -> None:
    pr = facts(author="carol", review_decision="REVIEW_REQUIRED", merge_state="BEHIND", unresolved_threads=1)
    [row] = rank.rank([pull("music-assistant/frontend#90010", "merge", pr, who_waits="bob")], NOW)
    assert row.action == "Answer bob on frontend#90010"
    assert row.tier is not Tier.LAND


def test_contributor_draft_fix_prs_are_off_until_they_ask_marvin() -> None:
    draft = pull(pr=facts(draft=True))
    assert not rank.gate(draft, NOW)
    assert rank.gate(pull(pr=facts(draft=True, question_for_me=True)), NOW)


def test_advisory_step_owned_by_someone_else_is_off() -> None:
    assert not rank.gate(advisory(step_owner="chrisuthe"), NOW)


def test_deferred_advisory_without_deadline_is_off() -> None:
    assert not rank.gate(advisory(action="decide_fix", ssvc_outcome=rank.DEFER), NOW)


def test_other_pr_is_off_after_my_review_until_the_author_acts() -> None:
    assert not rank.gate(pull(pr=facts(my_last_at=ago(1), other_last_at=ago(2))), NOW)
    assert rank.gate(pull(pr=facts(my_last_at=ago(2), other_last_at=ago(1))), NOW)


def test_own_draft_is_off_until_ready_to_flip() -> None:
    own = {"author": rank.ME, "draft": True, "my_last_at": ago(1), "other_last_at": None}
    assert not rank.gate(pull(pr=facts(**own, ci="pending", marley_approved_head=True)), NOW)
    [row] = rank.rank([pull(pr=facts(**own, marley_approved_head=True), who_waits=None)], NOW)
    assert (row.tier, row.action) == (Tier.LAND, "Mark server#90002 ready for review")


def test_own_pr_approved_by_bot_on_head_is_merge() -> None:
    pr = facts(author=rank.ME, marley_approved_head=True, my_last_at=ago(1), other_last_at=None)
    [row] = rank.rank([pull(pr=pr, action="reply", who_waits=None)], NOW)
    assert (row.tier, row.action, row.reason) == (Tier.LAND, "Merge server#90002", "approved, CI green, clean")


# collapse


def test_issue_with_ready_pr_is_one_row_on_the_pr() -> None:
    asks = [issue(waiting_on="reporter"), pull(links=[link(ISSUE, "fixes")])]
    [row] = rank.rank(asks, NOW)
    assert row.action == "Review server#90002, it resolves support#90001"
    assert [m.id for m in row.members] == [PR, ISSUE]


def test_issue_with_contributor_draft_keeps_the_issue_row() -> None:
    asks = [issue(), pull(pr=facts(draft=True), links=[link(ISSUE, "fixes")])]
    [row] = rank.rank(asks, NOW)
    assert row.id == ISSUE
    assert [m.id for m in row.members] == [ISSUE, PR]


def test_related_link_shows_as_see_also_without_merging() -> None:
    rows = rows_by_id([issue(), pull(links=[link(ISSUE, "related")])])
    assert rows[PR].see_also == [ISSUE]
    assert ISSUE in rows


def test_duplicate_advisories_take_highest_outcome_and_earliest_deadline() -> None:
    dup = advisory("GHSA-test-0002", "publish", step_owner="bob", ssvc_outcome=rank.IMMEDIATE,
                   due=TODAY + timedelta(days=40), links=[link(ADV, "duplicate_of")])
    [row] = rank.rank([dup, advisory()], NOW)
    assert (row.id, row.tier, row.due) == (ADV, Tier.ACT, TODAY + timedelta(days=40))


# tier


def test_blocked_contributor_design_call_leads_decide() -> None:
    asks = [
        issue("music-assistant/support#90003", "design", effort=30, impact_high=True, waiting_since=ago(60)),
        pull("music-assistant/server#90004", waiting_since=ago(2)),
        pull(action="decide", effort=30, waiting_since=ago(14), last_activity=ago(14)),
    ]
    rows = [row for row in rank.rank(asks, NOW) if row.tier is Tier.DECIDE]
    assert rows[0].id == PR
    assert rows[0].state == "live"


def test_deadline_promotes_into_act_and_nowhere_else() -> None:
    def tier_with(due_days: int) -> Tier:
        return rank.tier([chore("log:abc", "log_finding", due=TODAY + timedelta(days=due_days))], NOW)[0]

    assert tier_with(5) is Tier.ACT
    assert tier_with(30) is Tier.KEEP_WARM


def test_age_changes_no_tier() -> None:
    for action in ["design", "post"]:
        tiers = {rank.tier([issue(action=action, who_waits=None, waiting_since=ago(d))], NOW)[0] for d in (1, 300)}
        assert len(tiers) == 1


def test_quick_answer_is_unblock_and_expensive_question_is_decide() -> None:
    assert rank.tier([issue(effort=5)], NOW)[0] is Tier.UNBLOCK
    assert rank.tier([issue(effort=25)], NOW)[0] is Tier.DECIDE
    assert rank.tier([issue(action="post", draft_reply="text")], NOW)[0] is Tier.UNBLOCK


@pytest.mark.parametrize(
    ("ask", "expected"),
    [
        (chore("lab:test_queue", "investigate"), Tier.ACT),
        (issue(action="design", regression_stable=True, impact_high=True), Tier.ACT),
        (advisory(ssvc_outcome=rank.OUT_OF_CYCLE), Tier.ACT),
        (advisory(action="publish", ssvc_outcome=rank.IMMEDIATE), Tier.KEEP_WARM),
        (advisory(), Tier.DECIDE),
    ],
)
def test_act_entry_conditions(ask: rank.Ask, expected: Tier) -> None:
    assert rank.tier([ask], NOW)[0] is expected


# order


def test_release_merge_sits_below_the_security_picks() -> None:
    merge = rank.Ask(id="release:2.10.99", kind="release", src="release", title="t", url="u", action="merge",
                     effort=5, blocked_by=[ADV])
    rows = [row.id for row in rank.rank([merge, advisory(action="review_backport")], NOW)]
    assert rows.index(ADV) < rows.index("release:2.10.99")


def test_blocked_by_cycle_drops_an_edge_with_a_warning() -> None:
    a = issue("music-assistant/support#90005", blocked_by=["music-assistant/support#90006"])
    b = issue("music-assistant/support#90006", blocked_by=["music-assistant/support#90005"])
    with pytest.warns(UserWarning, match="cycle"):
        assert len(rank.rank([a, b], NOW)) == 2


def test_row_is_blocked_by_an_open_ask_even_when_gated_off() -> None:
    blocker = issue("music-assistant/support#90007", waiting_on="reporter")
    rows = rows_by_id([issue(blocked_by=[blocker.id]), blocker])
    assert rows[ISSUE].state == "blocked"
    rows = rows_by_id([issue(blocked_by=[blocker.id]), issue(blocker.id, open=False)])
    assert rows[ISSUE].state == "live"


# batch


def test_approval_batch_never_exceeds_30_minutes() -> None:
    sizes = ["M", "M", "M", "S", "S", "M"]
    asks = [pull(f"music-assistant/server#9010{n}", "approve", size=s) for n, s in enumerate(sizes)]
    rows = rank.rank(asks, NOW)
    [batch] = [row for row in rows if row.id == "batch:approve"]
    assert batch.effort <= rank.BATCH_MAX_MIN
    assert batch.action == "Approve 4 small PRs"
    assert len(rows) == 3


def test_publish_chores_batch_per_release_state() -> None:
    asks = [
        advisory("GHSA-test-0003", "publish", ssvc_outcome=rank.IMMEDIATE),
        advisory("GHSA-test-0004", "cve"),
        advisory("GHSA-test-0005", "publish", ships_in="2.10.99"),
        advisory("GHSA-test-0006", "credit", ships_in="2.10.99"),
    ]
    rows = rows_by_id(asks)
    assert rows["batch:publish-now"].action == "Finish publishing 2 advisories"
    assert rows["batch:publish-later"].action == "Finish publishing 2 advisories when 2.10.99 ships"
    assert {row.tier for row in rows.values()} == {Tier.KEEP_WARM}


# park and cut


def test_blocked_pr_author_never_parks() -> None:
    [row] = rank.rank([pull(action="decide", effort=30, last_activity=ago(40))], NOW)
    assert row.state == "live"


def test_parked_row_with_new_activity_is_live_again() -> None:
    idle = issue(action="design", last_activity=ago(30))
    assert rank.rank([idle], NOW)[0].state == "parked"
    assert rank.rank([issue(action="design", last_activity=ago(1))], NOW)[0].state == "live"


def test_cut_line_counts_only_live_rows() -> None:
    blocked = pull("music-assistant/server#90020", effort=200, waiting_since=ago(9), blocked_by=[ISSUE])
    asks = [blocked, issue(waiting_on="reporter")] + [
        pull(f"music-assistant/server#9002{n}", effort=100, waiting_since=ago(5 - n)) for n in range(1, 4)
    ]
    rows = rank.rank(asks, NOW)
    assert [(row.state, row.cut) for row in rows] == [
        ("blocked", False), ("live", False), ("live", False), ("live", True)
    ]


def test_snoozed_row_folds_only_when_the_gate_passes() -> None:
    snooze = {"until": TODAY + timedelta(days=3), "reason": ""}
    assert rank.rank([issue(snooze=snooze)], NOW)[0].state == "snoozed"
    assert rank.rank([issue(snooze=snooze, last_speaker=rank.ME)], NOW) == []
    assert rank.rank([issue(snooze={"until": TODAY, "reason": ""})], NOW)[0].state == "live"


# ssvc and reason


@pytest.mark.parametrize(
    ("ssvc", "exposure", "chained", "expected"),
    [
        ({"exploitation": "none", "technical_impact": "partial", "reaches": "ma_only"},
         {"auth": "admin", "config": "opt_in", "user_action": False}, [], rank.DEFER),
        ({"exploitation": "none", "technical_impact": "total", "reaches": "host"},
         {"auth": "none", "config": "default", "user_action": False}, [], rank.OUT_OF_CYCLE),
        ({"exploitation": "public_poc", "technical_impact": "partial", "reaches": "ma_only"},
         {"auth": "none", "config": "default", "user_action": False}, ["ha_control"], rank.IMMEDIATE),
    ],
)
def test_ssvc_outcome(ssvc: dict, exposure: dict, chained: list[str], expected: str) -> None:
    assert rank.ssvc_outcome(ssvc, exposure, chained) == expected


def test_reason_names_the_rule_that_fired() -> None:
    rows = rows_by_id([
        pull(action="decide", effort=30, waiting_since=ago(14)),
        issue(action="design", due=datetime(2026, 11, 16).date()),
    ])
    assert rows[PR].reason == "alice waits 14 d on your call"
    assert rows[ISSUE].reason == "due 11-16"
