from datetime import datetime, timezone

import sync

REPO = "example/repo"
NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)
OWNERS = {"carol"}


def _comment(login: str, body: str, at: str = "2026-11-01T00:00:00Z", assoc: str = "NONE", typename: str = "User") -> dict:
    return {"author": {"login": login, "__typename": typename}, "authorAssociation": assoc, "createdAt": at,
            "url": "https://example.test", "body": body}


def _xref(login: str, n: int, actor: str | None = None, assoc: str = "NONE") -> dict:
    return {"__typename": "CrossReferencedEvent", "createdAt": "2026-11-01T00:00:00Z", "willCloseTarget": False,
            "actor": {"login": actor or login},
            "source": {"__typename": "Issue", "number": n, "author": {"login": login}, "authorAssociation": assoc,
                       "repository": {"nameWithOwner": REPO}}}


def _node(comments: list[dict] = (), timeline: list[dict] = (), thumbs: int = 0, body: str = "") -> dict:
    return {"number": 1, "createdAt": "2026-10-01T00:00:00Z", "author": {"login": "alice"}, "body": body,
            "reactionGroups": [{"content": "THUMBS_UP", "reactors": {"totalCount": thumbs}},
                               {"content": "HEART", "reactors": {"totalCount": 4}}],
            "comments": {"nodes": list(comments)}, "timelineItems": {"nodes": list(timeline)}}


def _impact(node: dict) -> dict:
    return sync.impact(node, REPO, OWNERS, NOW)


def test_author_only() -> None:
    body = "### Music Assistant version\n\n2.10.9\n"
    assert _impact(_node(body=body)) == {"affected": 1, "idle_days": 41, "channel": "stable", "version": "2.10.9"}


def test_body_thumbs_count_once_each() -> None:
    assert _impact(_node(thumbs=3))["affected"] == 4


def test_me_too_commenters_count_once_and_set_idle() -> None:
    comments = [_comment("bob", "Same here on my HomePod", "2026-11-09T00:00:00Z"),
                _comment("bob", "+1 still broken"),
                _comment("dave", "Did you restart?"),
                _comment("erin", "Same issue, tried pr-1234 and it still fails")]
    impact = _impact(_node(comments))
    assert impact["affected"] == 2
    assert impact["idle_days"] == 2


def test_duplicates_and_human_cross_references_count_their_authors() -> None:
    timeline = [{"__typename": "MarkedAsDuplicateEvent", "canonical": {"number": 1},
                 "duplicate": {"number": 2, "author": {"login": "frank"}, "authorAssociation": "NONE",
                               "repository": {"nameWithOwner": REPO}}},
                _xref("frank", 2), _xref("gina", 3)]
    assert _impact(_node(timeline=timeline))["affected"] == 3


def test_bots_and_team_are_excluded() -> None:
    comments = [_comment("Bot-MArley", "Same here", "2026-11-10T00:00:00Z"),
                _comment("helper", "I can reproduce", "2026-11-10T00:00:00Z", typename="Bot"),
                _comment("OzGav", "Same here", "2026-11-10T00:00:00Z", assoc="MEMBER"),
                _comment("carol", "Same here", "2026-11-10T00:00:00Z")]
    timeline = [_xref("OzGav", 2, assoc="MEMBER"), _xref("hank", 3, actor="carol"), _xref("ivy", 4, actor="github-actions")]
    impact = _impact(_node(comments, timeline))
    assert impact["affected"] == 1
    assert impact["idle_days"] == 41


def test_version_channels() -> None:
    form = "### Music Assistant version\n\n{}\n"
    assert sync._version(form.format("2.11.0b5")) == ("beta", "2.11.0b5")
    assert sync._version(form.format("`2.11.0.dev2026100703`, server revision abc")) == ("dev", "2.11.0.dev2026100703")
    assert sync._version(form.format("2.11.0.dev.2026110204")) == ("dev", "2.11.0.dev.2026110204")
    assert sync._version(form.format("nightly")) == ("dev", None)
    assert sync._version("Broke after updating to 2.10.8") == ("stable", "2.10.8")
    assert sync._version("No version given") == (None, None)
