import hashlib
from datetime import UTC, datetime, timedelta

import build
from rank import Ask, Row, Tier

NOW = datetime(2026, 11, 11, 9, 0, tzinfo=UTC)  # Wednesday 10:00 in Amsterdam
EVIL = '</textarea><script>alert("x")</script>'


def _meta(ages: dict, stale: bool = False, now: datetime = NOW) -> dict:
    return {"build_id": "b1", "now": now, "budget_used": 5, "budget": 240, "ages": ages, "stale": stale}


def _row(ask: Ask) -> Row:
    return Row(id=ask.id, tier=Tier.UNBLOCK, rule="quick_answer", members=[ask], action=f"Post the reply on {EVIL}",
               effort=5, reason="alice waits 2 d, quick answer")


def test_titles_and_drafts_are_escaped_and_the_hash_matches_the_server() -> None:
    draft = f"> [!NOTE] written on Marvin's behalf\n\n{EVIL}"
    ask = Ask(id="music-assistant/support#1", kind="issue", src="issue-triage", title=EVIL, url="https://example.com/1",
              action="post", draft_reply=draft)
    html = build.render([_row(ask)], _meta({}))
    assert "<script>alert" not in html
    assert html.count("</textarea>") == 1
    assert f'data-hash="{hashlib.sha256(draft.encode()).hexdigest()[:16]}"' in html
    assert 'data-src="issue-triage" data-repo="music-assistant/support" data-n="1"' in html


def test_pr_drafts_post_with_the_short_repo() -> None:
    ask = Ask(id="music-assistant/server#7", kind="pr", src="pr-review", title="t", url="u", action="reply",
              draft_reply="> [!NOTE] hi")
    assert 'data-src="pr-review" data-repo="server" data-n="7"' in build.render([_row(ask)], _meta({}))


def test_office_hour_sources_are_late_only_in_office_hours() -> None:
    ages = {"pr-review": NOW - timedelta(hours=3), "security-inbox": NOW - timedelta(days=4), "github": None}
    assert build.late_sources(_meta(ages)) == ["pr-review"]
    saturday = NOW + timedelta(days=3)
    assert build.late_sources(_meta({"pr-review": saturday - timedelta(hours=3)}, now=saturday)) == []
    early = NOW - timedelta(hours=1, minutes=30)  # 08:30 local, the first run of the day is still due
    assert build.late_sources(_meta({"pr-review": early - timedelta(hours=14)}, now=early)) == []


def test_date_only_sources_get_slack_and_github_is_late_only_when_the_sync_failed() -> None:
    monday = NOW + timedelta(days=5)  # Monday 10:00, the twice-weekly security run stamped last Tuesday
    ages = {"security-inbox": monday - timedelta(days=6, hours=10), "lab-deep": NOW - timedelta(hours=34),
            "github": NOW - timedelta(days=9)}
    assert build.late_sources(_meta(ages, stale=True, now=monday)) == ["security-inbox", "lab-deep", "github"]
    ages = {"security-inbox": NOW - timedelta(days=5, hours=10), "lab-deep": NOW - timedelta(hours=34)}
    assert build.late_sources(_meta(ages)) == []


def test_rows_lines_address_rows_by_short_id() -> None:
    ask = Ask(id="music-assistant/support#1", kind="issue", src="issue-triage", title="t", url="u", action="post",
              who_waits="alice", last_activity=NOW, blocked_by=["music-assistant/server#2"])
    row = _row(ask)
    row.blocked_by = ask.blocked_by
    assert build.row_lines([row]) == [{
        "id": "support#1", "full_id": "music-assistant/support#1", "source": "issue-triage", "kind": "issue",
        "state": "live", "tier": "Unblock", "action": f"Post the reply on {EVIL}", "reason": "alice waits 2 d, quick answer",
        "effort": 5, "title": "t", "url": "u", "who_waits": None, "last_activity": "2026-11-11T09:00:00+00:00",
        "blocked_by": ["server#2"], "members": [{"id": "support#1", "source": "issue-triage"}],
    }]


def test_expanded_row_has_the_commands_of_every_member_and_the_queue_keeps_its_source() -> None:
    pr = Ask(id="music-assistant/server#2", kind="pr", src="github", title="t", url="u", action="review")
    issue = Ask(id="music-assistant/support#1", kind="issue", src="issue-triage", title="t", url="u", action="input")
    carded = Ask(id="music-assistant/server#3", kind="pr", src="pr-review", title="t", url="u", action="review")
    rows = [Row(id=pr.id, tier=Tier.DECIDE, rule="call", members=[pr, issue], action="a", effort=20),
            Row(id=carded.id, tier=Tier.DECIDE, rule="call", members=[carded], action="a", effort=20)]
    html = build.render(rows[:1], _meta({}))
    assert 'data-cmd="fix support#1"' in html and 'data-cmd="snooze server#2 3d"' in html
    assert [q["id"] for q in build.queue(rows, "pr-review")] == [carded.id]
