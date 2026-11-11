import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

import build
import collect
import rank
from rank import ME, Tier

NOW = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)
PR = "music-assistant/server#90002"
FIX = "music-assistant/server#90003"
ADV = "GHSA-test-0001"


def pr_facts(**over: object) -> dict:
    base = {
        "state": "OPEN", "draft": False, "author": "alice", "title": "Fix it", "url": "https://example/pr", "head": "h1",
        "base": "dev", "default_base": True, "review_decision": None, "merge_state": "CLEAN", "ci": "green",
        "unresolved_threads": 0, "review_requests": [], "reviews": {},
        "my_last": {"at": "2026-11-05T00:00:00Z", "kind": "review"},
        "other_last": {"login": "alice", "at": "2026-11-06T00:00:00Z", "kind": "push"},
        "my_said": {"at": "2026-11-05T00:00:00Z", "kind": "review"},
        "author_last": {"at": "2026-11-06T00:00:00Z", "kind": "push"},
        "mention_after_mine": False, "additions": 1, "deletions": 1, "labels": [], "links": [],
    }
    return base | over


def card(**over: object) -> dict:
    return {"repo": "server", "number": 90002, "state": "open", "status": "waiting", "title": "Fix it", "size": "S"} | over


def issue_card(**over: object) -> dict:
    sync = {"last_human": {"login": "bob", "at": "2026-11-09T00:00:00Z", "team": False}, "pr": [], "test_ask": None}
    return {"n": 90001, "title": "Broken", "col": "info", "ask": "reply-answer", "sync": sync} | over


def advisory(**over: object) -> dict:
    return {"id": ADV, "title": "t", "url": "u", "column": "open"} | over


# pr-review adapter


def test_pr_card_without_facts_needs_a_mark_and_closed_cards_never_count() -> None:
    state = {"prs": [
        card(),
        card(number=1, needs_reply={"at": "2026-11-08T00:00:00Z", "who": "bob"}),
        card(number=2, state="merged", status="attention"),
    ]}
    asks = collect.pr_review_asks(state, {})
    assert [(a.id, a.action, a.who_waits) for a in asks] == [("music-assistant/server#1", "reply", "bob")]


def test_pr_card_with_facts_falls_back_to_rereview_and_skips_the_backport() -> None:
    cache = {"prs": {PR: pr_facts(reviews={ME: {"state": "CHANGES_REQUESTED", "commit": "h0", "at": "x"}}),
                     "music-assistant/server#7": pr_facts()},
             "release": {"backport_pr": "music-assistant/server#7"}}
    asks = collect.pr_review_asks({"prs": [card(), card(number=7)]}, cache)
    assert len(asks) == 1
    ask = asks[0]
    assert (ask.action, ask.who_waits, ask.size) == ("rereview", "alice", "S")
    assert ask.detail_url == "http://127.0.0.1:8765/pr-review.html#pr-server-90002"


def test_unflagged_pr_card_is_off_although_the_author_pushed_after_his_review() -> None:
    state = {"last_run": "2026-11-11T09:00:00Z", "prs": [card(), card(number=1, status="attention")]}
    waiting, flagged = collect.pr_review_asks(state, {"prs": {PR: pr_facts(), "music-assistant/server#1": pr_facts()}})
    assert (waiting.flagged, waiting.checked_at) == (False, datetime(2026, 11, 11, 9, 0, tzinfo=UTC))
    assert not rank.gate(waiting, NOW)
    assert flagged.flagged and rank.gate(flagged, NOW)


def test_pr_snooze_until_activity_ends_with_a_human_event() -> None:
    snooze = {"at": "2026-11-07T00:00:00Z", "until": "activity", "reason": ""}
    quiet = collect.pr_ask(PR, pr_facts(), card(snooze=snooze))
    assert quiet.snooze == {"until": date.max, "reason": ""}
    busy = collect.pr_ask(PR, pr_facts(other_last={"login": "alice", "at": "2026-11-08T00:00:00Z", "kind": "comment"}),
                          card(snooze=snooze))
    assert busy.snooze is None


# issue-triage adapter


def test_drafted_replies_split_by_who_spoke_last() -> None:
    marvin_last = issue_card()["sync"] | {"last_human": {"login": ME, "at": "2026-11-10T00:00:00Z", "team": True}}
    cards = [
        issue_card(n=1, reply="draft"),
        issue_card(n=2, ask="reply-info", reply="draft"),
        issue_card(n=3, ask="reply-test", reply="draft"),
        issue_card(n=4, reply="draft", sync=marvin_last),
    ]
    rows = {row.id: row for row in rank.rank(collect.issue_asks({"cards": cards}), NOW)}
    assert rows["music-assistant/support#1"].tier is Tier.UNBLOCK
    assert rows["music-assistant/support#1"].action == "Post the reply to bob on support#1"
    assert [a.id for a in rows["batch:drafts"].members] == [f"music-assistant/support#{n}" for n in (2, 3, 4)]
    assert len(rows) == 2


def test_reporter_waits_after_the_last_human_unless_marvin_asked_him() -> None:
    teammate_last = issue_card()["sync"] | {"last_human": {"login": "OzGav", "at": "2026-11-10T00:00:00Z", "team": True}}
    waits = {ask: collect.issue_ask(issue_card(ask=ask)).who_waits for ask in ("input", "design", "reply-info", "reply-test")}
    assert waits == {"input": "bob", "design": "bob", "reply-info": None, "reply-test": None}
    assert collect.issue_ask(issue_card(ask="input")).waiting_since == datetime(2026, 11, 9, tzinfo=UTC)
    assert collect.issue_ask(issue_card(ask="input", sync=teammate_last)).who_waits is None


def test_drafts_on_input_and_design_asks_keep_their_action() -> None:
    assert collect.issue_ask(issue_card(ask="input", reply="draft")).action == "input"
    assert collect.issue_ask(issue_card(ask="input", reply="draft")).draft_reply == "draft"
    assert collect.issue_ask(issue_card(ask=None, reply="draft")).action == "post"


def test_issue_ask_fields() -> None:
    sync = issue_card()["sync"] | {"pr": [{"repo": "music-assistant/server", "n": 5, "state": "OPEN"},
                                         {"repo": "music-assistant/server", "n": 6, "state": "MERGED"}],
                                  "impact": {"affected": rank.HIGH_AFFECTED}}
    ask = collect.issue_ask(issue_card(repo="music-assistant/frontend", col="user", sync=sync,
                                       regression={"broke_in": "2.10.3", "worked_in": "2.10.2", "on": "beta"}))
    assert (ask.id, ask.action, ask.who_waits) == ("music-assistant/frontend#90001", "reply", "bob")
    assert ask.impact_high and not ask.regression_stable and ask.low_impact
    assert ask.links == [{"id": "music-assistant/server#5", "rel": "related", "src": "sync"}]
    assert ask.detail_url == "http://127.0.0.1:8765/issue-triage.html?q=90001#c-frontend-90001"


def test_unanswered_test_ask_is_the_reporters_turn() -> None:
    sync = issue_card()["sync"] | {"test_ask": {"at": "2026-11-09T00:00:00Z"}, "after_test_ask_reporter": False}
    assert collect.issue_ask(issue_card(ask="input", sync=sync)).waiting_on == "reporter"


def test_merge_ask_becomes_the_linked_pr_row_with_the_action_from_its_facts(tmp_path: Path) -> None:
    sync = issue_card()["sync"] | {"pr": [{"repo": "music-assistant/server", "n": 90003, "state": "OPEN"}]}
    triage = {"cards": [issue_card(ask="merge", sync=sync)]}
    security = {"advisories": [advisory(fix_prs=[{"repo": "server", "number": 90003}], remaining_steps=[])]}
    (tmp_path / "issue-triage.json").write_text(json.dumps(triage))
    (tmp_path / "security-inbox.json").write_text(json.dumps(security))
    behind = pr_facts(review_decision="REVIEW_REQUIRED", merge_state="BEHIND", unresolved_threads=1)
    cache = {"prs": {FIX: behind}, "review_requested": [FIX],
             "mentions": [{"id": FIX, "is_pr": True, "title": "t", "url": "u", "author": "alice"}]}
    asks = collect.collect(tmp_path, cache, {}, NOW)
    assert [(a.id, a.action) for a in asks] == [("music-assistant/support#90001", "merge"), (FIX, "merge")]
    [row] = rank.rank(asks, NOW)
    assert row.action == "Answer alice on server#90003, it resolves support#90001"


def test_linked_pr_without_review_card_is_an_event_rule_pr_ask() -> None:
    linked = [{"repo": "music-assistant/server", "n": n, "state": "OPEN"} for n in (90002, 90003, 90004)]
    state = {"cards": [issue_card(ask="input", sync=issue_card()["sync"] | {"pr": linked})]}
    cache = {"prs": {PR: pr_facts(), FIX: pr_facts()}}
    [ask] = collect.issue_pr_asks(state, cache, covered={PR})
    assert (ask.id, ask.action, ask.flagged) == (FIX, "review", None)


# security adapter


def test_advisory_steps_due_links_and_waiting() -> None:
    adv = advisory(
        remaining_steps=[{"step": "review_fix", "owner": "marvin", "effort": 25}],
        deadlines=[{"kind": "ack", "date": "2026-11-12"}, {"kind": "fix", "date": "2027-01-10"}],
        ack_sent_at="2026-11-10", fix_prs=[{"repo": "music-assistant/server", "number": 90003, "backport_label": True}],
        blocked_since={"who": "carol", "since": "2026-11-01"},
    )
    ask = collect.advisory_ask(adv, {ADV: adv}, {})
    assert (ask.action, ask.step_owner, ask.effort, ask.due) == ("review_fix", "marvin", 25, date(2027, 1, 10))
    assert ask.links == [{"id": FIX, "rel": "advisory_fix", "src": "model"}]
    assert (ask.who_waits, ask.waiting_since) == ("carol", datetime(2026, 11, 1, tzinfo=UTC))


def test_unassessed_done_and_publish_chore_advisories() -> None:
    assert collect.advisory_ask(advisory(), {}, {}).action == "decide_fix"
    assert collect.advisory_ask(advisory(remaining_steps=[]), {}, {}) is None
    chore = advisory(remaining_steps=[{"step": "publish", "owner": "marvin"}],
                     fix_prs=[{"repo": "music-assistant/server", "number": 90003}])
    release = {"version": "2.10.10", "picked": [], "missing": [{"number": 90003, "title": "t"}]}
    assert collect.advisory_ask(chore, {}, release).ships_in == "2.10.10"


def test_publish_stage_advisory_is_one_publish_chore() -> None:
    steps = [{"step": s, "owner": "marvin", "effort": 2} for s in ("reply", "set_ranges", "cve", "credit", "publish")]
    adv = advisory(remaining_steps=steps, ssvc={"exploitation": "active", "technical_impact": "total", "reaches": "host"},
                   exposure={"auth": "none", "config": "default", "user_action": False})
    ask = collect.advisory_ask(adv, {ADV: adv}, {})
    assert (ask.action, ask.effort, ask.ssvc_outcome) == ("publish", 10, None)


def test_backport_step_is_due_by_the_planned_stable_cut() -> None:
    releases = [{"label": "beta", "next_cut": {"channel": "beta", "version": "2.11.0b9", "planned_date": "2026-11-13"}},
                {"label": "stable", "next_cut": {"channel": "stable", "version": "2.10.10", "planned_date": "2026-11-20"}}]
    backport = advisory(remaining_steps=[{"step": "backport_decision", "owner": "marvin"}])
    fix = advisory(id="GHSA-test-0002", remaining_steps=[{"step": "review_fix", "owner": "marvin"}])
    asks = collect.security_asks({"releases": releases, "advisories": [backport, fix]}, {}, carded=set())
    assert [a.due for a in asks] == [date(2026, 11, 20), None]


def test_code_scanning_cards_that_wait_on_marvin_are_decide_asks() -> None:
    cards = [{"id": "cs-1", "column": "unsure", "title": "Unsure about it"}, {"id": "cs-2", "column": "new", "title": "t"}]
    [ask] = collect.security_asks({"code_scanning": cards}, {}, carded=set())
    assert (ask.id, ask.kind, ask.action, ask.url) == ("cs-1", "alert", "decide",
                                                       "http://127.0.0.1:8765/security-inbox.html#card-cs-1")
    assert rank.rank([ask], NOW)[0].action == "Unsure about it"


def test_uncarded_fix_pr_becomes_a_pr_ask() -> None:
    state = {"advisories": [advisory(fix_prs=[{"repo": "music-assistant/server", "number": 90003}])]}
    asks = collect.security_asks(state, {"prs": {FIX: pr_facts()}}, carded=set())
    assert [(a.id, a.kind) for a in asks] == [(ADV, "advisory"), (FIX, "pr")]
    assert collect.security_asks(state, {"prs": {FIX: pr_facts()}}, carded={FIX})[1:] == []


# lab-deep, nightly, github and release adapters


def test_lab_reds_by_read() -> None:
    state = {"reds": [{"test": "t1", "read": "server", "since": "2026-11-10"}, {"test": "t2", "read": "lab"}]}
    assert [(a.id, a.action, a.title) for a in collect.lab_asks(state)] == [
        ("lab:t1", "investigate", "Investigate t1 on dev"), ("lab:t2", "lab_error", "Fix the lab error in t2")]


def test_nightly_findings_of_the_last_run_only() -> None:
    seen = {"title": "x", "last_seen": "2026-11-11"}
    state = {"last_run_end": "2026-11-11T05:00:10+01:00", "muted": ["muted"], "known": {
        "new": seen, "old": seen | {"last_seen": "2026-11-10"}, "fixed": seen | {"fix": "server#1"},
        "gone": seen | {"resolved": "11-10"}, "muted": seen,
    }}
    assert [(a.id, a.title) for a in collect.nightly_asks(state)] == [("log:new", "Look at x")]


def test_github_issue_mention_counts_only_after_his_reply() -> None:
    mention = {"id": "example/repo#1", "is_pr": False, "title": "t", "url": "u", "author": "bob",
               "my_last": None, "other_last": {"login": "bob", "at": "2026-11-09T00:00:00Z", "kind": "comment"}}
    cache = {"prs": {PR: pr_facts()}, "review_requested": [PR],
             "mentions": [mention | {"mention_after_mine": True}, mention | {"id": "example/repo#2", "mention_after_mine": False}]}
    asks = collect.github_asks(cache, carded=set())
    assert [(a.id, a.action, a.who_waits) for a in asks] == [(PR, "review", "alice"), ("example/repo#1", "input", "bob")]
    assert collect.github_asks(cache, carded={PR, "example/repo#1"}) == []


def test_mentioned_pr_is_a_reply_unless_his_review_is_requested() -> None:
    mention = {"id": FIX, "is_pr": True, "title": "t", "url": "u", "author": "alice"}
    cache = {"prs": {PR: pr_facts(), FIX: pr_facts(mention_after_mine=True)}, "review_requested": [PR],
             "mentions": [mention, mention | {"id": PR}]}
    assert [(a.id, a.action) for a in collect.github_asks(cache, carded=set())] == [(PR, "review"), (FIX, "reply")]


def test_mentioned_pr_without_a_mention_past_his_reply_is_off() -> None:
    cache = {"prs": {FIX: pr_facts()}, "mentions": [{"id": FIX, "is_pr": True, "title": "t", "url": "u", "author": "a"}]}
    assert collect.github_asks(cache, carded=set()) == []


def test_pr_review_skip_map_keeps_a_mentioned_pr_out(tmp_path: Path) -> None:
    (tmp_path / "pr-review.json").write_text('{"prs": [], "skip": {"server#90003": "stale draft"}}')
    cache = {"prs": {FIX: pr_facts(mention_after_mine=True)},
             "mentions": [{"id": FIX, "is_pr": True, "title": "t", "url": "u", "author": "a"}]}
    assert collect.collect(tmp_path, cache, {}, NOW) == []


def test_pr_review_skip_map_keeps_an_advisory_fix_pr_out(tmp_path: Path) -> None:
    (tmp_path / "pr-review.json").write_text('{"prs": [], "skip": {"server#90003": "stale draft"}}')
    security = {"advisories": [advisory(fix_prs=[{"repo": "server", "number": 90003}])]}
    (tmp_path / "security-inbox.json").write_text(json.dumps(security))
    assert [a.id for a in collect.collect(tmp_path, {"prs": {FIX: pr_facts()}}, {}, NOW)] == [ADV]


def test_release_merge_waits_on_picks_and_unpicked_security_fixes() -> None:
    cache = {"prs": {FIX: pr_facts()},
             "release": {"backport_pr": "music-assistant/server#7", "version": "2.10.10", "picked": [90004],
                         "missing": [{"number": 1, "title": "a"}, {"number": 2, "title": "b"}]}}
    picked = {"repo": "music-assistant/server", "number": 90004, "backport_label": True}
    on_stable = {"repo": "music-assistant/server", "number": 90005, "backport_label": True}
    security = {"advisories": [
        advisory(fix_prs=[{"repo": "music-assistant/server", "number": 90003, "backport_label": True}, picked]),
        advisory(id="GHSA-test-0002", fix_prs=[picked], remaining_steps=[{"step": "review_backport", "owner": "marvin"}]),
        advisory(id="GHSA-test-0003", fix_prs=[on_stable], remaining_steps=[{"step": "publish", "owner": "marvin"}]),
    ]}
    merge, picks = collect.release_asks(cache, security)
    assert (merge.id, merge.action, merge.url) == ("release:2.10.10", "merge", "https://github.com/music-assistant/server/pull/7")
    assert merge.title == "Merge the 2.10.10 backport PR"
    assert merge.blocked_by == ["release:2.10.10/picks", ADV, "GHSA-test-0002"]
    assert (picks.id, picks.title) == ("release:2.10.10/picks", "Cherry-pick 2 missing PRs into 2.10.10")


# overrides, last_run and the build output


def test_overrides_by_id() -> None:
    ask = collect.issue_ask(issue_card())
    attention = {
        "snooze": {ask.id: {"until": "2026-11-14", "reason": "busy"}},
        "due": {ask.id: "2026-11-20"},
        "blocked_by": {ask.id: [PR]},
        "pending": {ask.id: {"cmd": "post 90001", "at": "2026-11-11T09:00:00Z"}},
    }
    handled = {"issue-triage": datetime(2026, 11, 11, 8, 0, tzinfo=UTC)}
    [out] = collect.apply_overrides([ask], attention, handled, NOW)
    assert out.snooze == {"until": date(2026, 11, 14), "reason": "busy"}
    assert (out.due, out.blocked_by, out.pending) == (date(2026, 11, 20), [PR], "post 90001")


def test_pending_command_clears_once_handled_or_after_a_day() -> None:
    ask = collect.issue_ask(issue_card())
    attention = {"pending": {ask.id: {"cmd": "post 90001", "at": "2026-11-11T09:00:00Z"}}}
    assert collect.apply_overrides([ask], attention, {}, NOW)[0].pending == "post 90001"
    handled = {"issue-triage": datetime(2026, 11, 11, 9, 30, tzinfo=UTC)}
    assert collect.apply_overrides([ask], attention, handled, NOW)[0].pending is None
    assert collect.apply_overrides([ask], attention, {}, NOW + timedelta(days=1))[0].pending is None


@pytest.mark.parametrize(("state", "expected"), [
    ({"last_run": "2026-11-11T11:00:00+01:00"}, datetime(2026, 11, 11, 10, 0, tzinfo=UTC)),
    ({"last_run": "2026-11-11 10:30 CET"}, datetime(2026, 11, 11, 9, 30, tzinfo=UTC)),
    ({"last_run": "2026-11-11"}, datetime(2026, 11, 10, 23, 0, tzinfo=UTC)),
    ({"last_run_end": "2026-11-11T05:00:10+01:00"}, datetime(2026, 11, 11, 4, 0, 10, tzinfo=UTC)),
])
def test_last_run_formats(state: dict, expected: datetime) -> None:
    assert collect.last_run(state) == expected


def test_summary_prints_rows_new_in_act_or_unblock() -> None:
    lab = rank.Ask(id="lab:t1", kind="lab", src="lab-deep", title="Investigate t1 on dev", url="u", action="investigate")
    old = rank.Ask(id="lab:t0", kind="lab", src="lab-deep", title="t", url="u", action="investigate")
    rows = rank.rank([lab, old], NOW)
    lines = build.summary(rows, ["lab:t0"], "attention.html")
    assert lines == [
        "+ Act: Investigate t1 on dev (dev regression in the lab)",
        "attention: 2 today, 30 min of 240 · http://127.0.0.1:8765/attention.html",
    ]
    assert build.summary(rows, None, "attention.html") == lines[1:]


def test_build_writes_page_and_build_file(tmp_path: Path) -> None:
    (tmp_path / "lab-deep.json").write_text('{"last_run": "2026-11-11", "reds": [{"test": "t1", "read": "server"}]}')
    out = tmp_path / "attention.html"
    build.build(tmp_path, tmp_path / "cache.json", out, NOW, stale=True)
    assert "Investigate t1 on dev" in out.read_text()
    assert collect.read_json(tmp_path / "attention.build.json") == {"id": "20261111T100000Z", "top": ["lab:t1"]}


def test_handled_build_records_the_source_and_keeps_the_others(tmp_path: Path) -> None:
    (tmp_path / "attention.json").write_text(json.dumps({"pending": {
        "lab:t1": {"cmd": "known t1", "at": "2026-11-11T09:00:00Z"}}}))
    (tmp_path / "lab-deep.json").write_text('{"reds": [{"test": "t1", "read": "server"}]}')
    out = tmp_path / "attention.html"
    (tmp_path / "attention.build.json").write_text('{"id": "x", "top": [], "handled": {"pr-review": "2026-11-10T08:00:00+00:00"}}')
    build.build(tmp_path, tmp_path / "cache.json", out, NOW, stale=False)
    assert "sent: known t1" in out.read_text()
    build.build(tmp_path, tmp_path / "cache.json", out, NOW, stale=False, handled_by="lab-deep")
    assert "sent: known t1" not in out.read_text()
    assert collect.read_json(tmp_path / "attention.build.json")["handled"] == {
        "pr-review": "2026-11-10T08:00:00+00:00", "lab-deep": "2026-11-11T10:00:00+00:00"}
