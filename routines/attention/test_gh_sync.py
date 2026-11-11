import json
from pathlib import Path

import pytest

import gh_sync

FIXTURES = Path(__file__).parent / "fixtures"
ME = gh_sync.ME


def _user(login: str, typename: str = "User") -> dict:
    return {"login": login, "__typename": typename}


def _node(**over: object) -> dict:
    node = {
        "number": 10, "state": "OPEN", "isDraft": False, "title": "Fix it", "url": "https://github.com/example/server/pull/10",
        "body": "", "additions": 3, "deletions": 1, "headRefOid": "h1", "baseRefName": "dev", "author": _user("alice"),
        "repository": {"nameWithOwner": "example/server", "defaultBranchRef": {"name": "dev"}},
        "baseRef": {"associatedPullRequests": {"nodes": []}},
        "reviewDecision": "REVIEW_REQUIRED", "mergeStateStatus": "BLOCKED",
        "commits": {"nodes": [{"commit": {"committedDate": "2026-11-01T10:00:00Z", "statusCheckRollup": {"state": "FAILURE"},
                                          "author": {"name": "alice", "user": {"login": "alice"}},
                                          "committer": {"name": "alice", "user": {"login": "alice"}}}}]},
        "reviewThreads": {"nodes": [{"isResolved": True}, {"isResolved": False}]},
        "reviewRequests": {"nodes": [{"requestedReviewer": {"login": ME}}, {"requestedReviewer": {"slug": "core"}}]},
        "latestReviews": {"nodes": [{"author": _user("Bot-MArley"), "state": "APPROVED", "submittedAt": "2026-11-02T00:00:00Z",
                                     "commit": {"oid": "h1"}}]},
        "labels": {"nodes": [{"name": "backport-to-stable"}]},
        "closingIssuesReferences": {"nodes": []},
        "timelineItems": {"nodes": []},
    }
    node.update(over)
    return node


def _comment(login: str, at: str, body: str = "", typename: str = "User") -> dict:
    return {"__typename": "IssueComment", "author": _user(login, typename), "createdAt": at, "body": body}


def test_body_refs_template_body() -> None:
    body = (FIXTURES / "body_template.md").read_text()
    assert gh_sync.body_refs(body, "example/server") == [
        "music-assistant/server#41", "example/server#7", "example/support#6731"]


def test_body_refs_prose_body() -> None:
    body = (FIXTURES / "body_prose.md").read_text()
    assert gh_sync.body_refs(body, "example/server") == [
        "example/models#3", "music-assistant/frontend#20", "example/server#5", "example/support#8"]


def test_links_fixes_follow_up_and_related_without_duplicates() -> None:
    node = _node(baseRefName="feature", baseRef={"associatedPullRequests": {"nodes": [{"number": 4}]}},
                 closingIssuesReferences={"nodes": [{"number": 1, "repository": {"nameWithOwner": "example/support"}}]},
                 body="Fixes example/support#1, stacked on #4 per related issue #4 and example/server#10, see example/lib#2")
    assert gh_sync.pr_facts(node)["links"] == [
        {"id": "example/support#1", "rel": "fixes", "src": "github"},
        {"id": "example/server#4", "rel": "follow_up", "src": "github"},
        {"id": "example/lib#2", "rel": "related", "src": "github"},
    ]


def test_pr_facts_plain_fields() -> None:
    facts = gh_sync.pr_facts(_node())
    assert facts["ci"] == "red" and facts["default_base"] is True
    assert facts["unresolved_threads"] == 1
    assert facts["review_requests"] == [ME, "core"]
    assert facts["reviews"] == {"Bot-MArley": {"state": "APPROVED", "commit": "h1", "at": "2026-11-02T00:00:00Z"}}
    assert facts["labels"] == ["backport-to-stable"]


def test_last_events_skip_bots_and_flag_a_later_mention() -> None:
    node = _node(timelineItems={"nodes": [
        _comment(ME, "2026-11-03T00:00:00Z"),
        {"__typename": "ReadyForReviewEvent", "createdAt": "2026-11-04T00:00:00Z", "actor": _user("bob")},
        _comment("bob", "2026-11-05T00:00:00Z", f"@{ME} can you look?"),
        _comment("Bot-MArley", "2026-11-06T00:00:00Z", f"@{ME} review done"),
        _comment("renovate[bot]", "2026-11-07T00:00:00Z", typename="Bot"),
    ]})
    facts = gh_sync.pr_facts(node)
    assert facts["my_last"] == {"at": "2026-11-03T00:00:00Z", "kind": "comment"}
    assert facts["other_last"] == {"login": "bob", "at": "2026-11-05T00:00:00Z", "kind": "comment"}
    assert facts["mention_after_mine"] is True


def test_mention_before_my_reply_does_not_count() -> None:
    node = _node(timelineItems={"nodes": [
        _comment("bob", "2026-11-03T00:00:00Z", f"@{ME} ping"),
        {"__typename": "PullRequestReview", "author": _user(ME), "state": "COMMENTED",
         "submittedAt": "2026-11-04T00:00:00Z", "body": ""},
    ]})
    facts = gh_sync.pr_facts(node)
    assert facts["my_last"]["kind"] == "review"
    assert facts["mention_after_mine"] is False


def test_push_goes_to_the_committer_and_bot_commits_are_no_push() -> None:
    rebased = _node(commits={"nodes": [{"commit": {
        "committedDate": "2026-11-09T00:00:00Z", "statusCheckRollup": None,
        "author": {"name": "alice", "user": {"login": "alice"}}, "committer": {"name": ME, "user": {"login": ME}}}}]})
    assert gh_sync.pr_facts(rebased)["my_last"] == {"at": "2026-11-09T00:00:00Z", "kind": "push"}
    assert gh_sync.pr_facts(rebased)["ci"] == "none"
    picked = _node(author=_user("github-actions", "Bot"), commits={"nodes": [{"commit": {
        "committedDate": "2026-11-09T00:00:00Z", "statusCheckRollup": {"state": "SUCCESS"},
        "author": {"name": "musicassistant-bot[bot]", "user": {"login": "musicassistant-bot[bot]"}},
        "committer": {"name": "GitHub", "user": None}}}]})
    assert gh_sync.pr_facts(picked)["other_last"] is None


def test_state_targets() -> None:
    pr_review = {"prs": [{"repo": "server", "number": 1, "state": "open"}, {"repo": "server", "number": 2, "state": "merged"}]}
    triage = {"cards": [{"sync": {"pr": [{"repo": "example/models", "n": 3, "state": "OPEN"},
                                         {"repo": "example/models", "n": 4, "state": "MERGED"}]}}, {"n": 5}]}
    security = {"advisories": [
        {"pr": {"url": "https://github.com/example/server-ghsa-test/pull/1"},
         "tracking": {"fix": [{"url": "https://github.com/music-assistant/server/pull/1"},
                              {"url": "https://github.com/example/backlog/issues/6"}]}},
        {"fix_prs": [{"repo": "server", "number": 7}]},
    ]}
    assert gh_sync.state_targets(pr_review, triage, security) == [
        "music-assistant/server#1", "example/models#3", "example/server-ghsa-test#1", "music-assistant/server#7"]


def test_release_facts() -> None:
    backport = {"number": 50, "headRefName": "backport/2.10.10", "commits": {"nodes": [
        {"commit": {"message": "Fix a (#41)\n\n(cherry picked from commit abc)"}},
        {"commit": {"message": "Revert \"Fix b (#30)\" (#42)"}},
        {"commit": {"message": "Bump deps"}},
    ]}}
    merged = [{"number": 44, "title": "Fix d"}, {"number": 41, "title": "Fix a"}, {"number": 43, "title": "Fix c"}]
    assert gh_sync.release_facts(backport, merged, ["Fix c (#43)"]) == {
        "backport_pr": "music-assistant/server#50", "version": "2.10.10", "picked": [41, 42],
        "missing": [{"number": 44, "title": "Fix d"}]}
    assert gh_sync.release_facts(None, merged, []) is None


def test_failed_sync_keeps_the_old_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    cache = tmp_path / "attention-github.json"
    cache.write_text(json.dumps({"fetched_at": "old"}))

    def down(query: str, partial: bool = False) -> dict:
        raise gh_sync.GhError("HTTP 502")

    monkeypatch.setattr(gh_sync, "_graphql", down)
    assert gh_sync.sync(tmp_path, cache) is False
    assert json.loads(cache.read_text()) == {"fetched_at": "old"}
    assert capsys.readouterr().err.strip() == "gh_sync: GhError: HTTP 502"
