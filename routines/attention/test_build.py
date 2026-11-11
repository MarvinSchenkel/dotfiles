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


def test_security_is_late_after_five_days_and_github_only_when_the_sync_failed() -> None:
    ages = {"security-inbox": NOW - timedelta(days=6), "github": NOW - timedelta(days=9)}
    assert build.late_sources(_meta(ages, stale=True)) == ["security-inbox", "github"]
