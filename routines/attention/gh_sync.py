"""Fetch PR facts, mentions, review requests and release facts from GitHub into the attention cache.

Usage: python3 gh_sync.py [--state-dir DIR] [--cache FILE]

Read only: every call is a GraphQL query through `gh api graphql`.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ME = "MarvinSchenkel"
ORG = "music-assistant"
SERVER = f"{ORG}/server"
SUPPORT = f"{ORG}/support"
BACKPORT_LABEL = "backport-to-stable"
BOTS = {b.lower() for b in ("github-actions", "coderabbitai", "musicassistant-bot",
                            "copilot-pull-request-reviewer", "Copilot", "Bot-MArley")}
STATE_DIR = Path("~/git/dotfiles/routines/state").expanduser()
CACHE = Path("~/.claude-teamB/routine-state/attention-github.json").expanduser()
BATCH = 15
WORKERS = 8
TIMELINE = 50
SEARCHES = {"review_requested": f"review-requested:{ME}", "mentions": f"mentions:{ME}"}
CI = {"SUCCESS": "green", "FAILURE": "red", "ERROR": "red", "PENDING": "pending", "EXPECTED": "pending"}

MENTION = re.compile(rf"@{ME}\b", re.I)
PR_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
GH_URL = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull|discussions)/(\d+)")
FULL_REF = re.compile(r"(?<![\w/.-])([\w.-]+/[\w.-]+)#(\d+)\b")
SHORT_REF = re.compile(r"(?<![\w/.-])([a-z][\w.-]*)#(\d+)\b")
BARE_REF = re.compile(r"(?<![\w/#])#(\d+)\b")
RELATED_LINE = re.compile(r"related issues?", re.I)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
# Words people put before "#N" that are not repo names.
NOT_REPOS = {"pr", "prs", "issue", "issues", "pull", "fix", "fixes", "see", "and", "or", "ref"}
PICK = re.compile(r"\(#(\d+)\)")

ACTOR = "login __typename"
PR_FIELDS = f"""
  number state isDraft title url body additions deletions headRefOid baseRefName author{{{ACTOR}}}
  repository{{nameWithOwner defaultBranchRef{{name}}}}
  baseRef{{associatedPullRequests(first:1, states:OPEN){{nodes{{number}}}}}}
  reviewDecision mergeStateStatus
  commits(last:1){{nodes{{commit{{committedDate author{{name user{{login}}}} committer{{name user{{login}}}}
                                 statusCheckRollup{{state}}}}}}}}
  reviewThreads(first:100){{nodes{{isResolved}}}}
  reviewRequests(first:20){{nodes{{requestedReviewer{{... on User{{login}} ... on Team{{slug}}}}}}}}
  latestReviews(first:30){{nodes{{author{{{ACTOR}}} state submittedAt commit{{oid}}}}}}
  labels(first:30){{nodes{{name}}}}
  closingIssuesReferences(first:20){{nodes{{number repository{{nameWithOwner}}}}}}
  timelineItems(last:{TIMELINE}, itemTypes:[ISSUE_COMMENT, PULL_REQUEST_REVIEW, HEAD_REF_FORCE_PUSHED_EVENT,
                                         READY_FOR_REVIEW_EVENT]){{nodes{{__typename
    ... on IssueComment{{author{{{ACTOR}}} createdAt body}}
    ... on PullRequestReview{{author{{{ACTOR}}} state submittedAt body}}
    ... on HeadRefForcePushedEvent{{createdAt actor{{{ACTOR}}}}}
    ... on ReadyForReviewEvent{{createdAt actor{{{ACTOR}}}}}}}}}
"""
SEARCH_FIELDS = f"""__typename
  ... on Issue{{number title url updatedAt author{{login}} repository{{nameWithOwner}}}}
  ... on PullRequest{{number title url updatedAt author{{login}} repository{{nameWithOwner}}}}"""
ISSUE_FIELDS = f"""
  author{{{ACTOR}}} createdAt body
  comments(last:{TIMELINE}){{nodes{{author{{{ACTOR}}} createdAt body}}}}
"""
BACKPORT_FIELDS = "... on PullRequest{number title headRefName commits(first:250){nodes{commit{message}}}}"


class GhError(Exception):
    """A GitHub query failed as a whole."""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--state-dir", type=Path, default=STATE_DIR)
    p.add_argument("--cache", type=Path, default=CACHE)
    args = p.parse_args()
    sys.exit(0 if sync(args.state_dir, args.cache) else 1)


def sync(state_dir: Path, cache_path: Path) -> bool:
    """Refresh the GitHub cache from the routine state in state_dir; False leaves the old cache in place."""
    try:
        cache = _fetch(state_dir)
    # Whatever broke, the build carries on with the old cache and marks it stale.
    except Exception as e:  # noqa: BLE001
        print(f"gh_sync: {type(e).__name__}: {e}".splitlines()[0][:300], file=sys.stderr)
        return False
    _write_atomic(cache_path, cache)
    return True


def state_targets(pr_review: dict, issue_triage: dict, security: dict) -> list[str]:
    """PR ids the routines track: open review cards, open issue fixes and every advisory fix PR."""
    ids = [f"{ORG}/{c['repo']}#{c['number']}" for c in pr_review.get("prs", []) if c.get("state") == "open"]
    for card in issue_triage.get("cards", []):
        ids += [f"{p['repo']}#{p['n']}" for p in (card.get("sync") or {}).get("pr") or [] if p.get("state") == "OPEN"]
    for adv in security.get("advisories", []):
        ids += [f"{_full_repo(p['repo'])}#{p['number']}" for p in adv.get("fix_prs") or []]
        urls = [(adv.get("pr") or {}).get("url")] + [f.get("url") for f in (adv.get("tracking") or {}).get("fix") or []]
        ids += [f"{m[1]}#{m[2]}" for u in urls if u and (m := PR_URL.search(u))]
    return list(dict.fromkeys(ids))


def pr_facts(node: dict) -> dict:
    """Cache entry for one PR node of the PR_FIELDS shape."""
    repo = node["repository"]["nameWithOwner"]
    default = (node["repository"].get("defaultBranchRef") or {}).get("name")
    commit = node["commits"]["nodes"][0]["commit"] if node["commits"]["nodes"] else {}
    rollup = (commit.get("statusCheckRollup") or {}).get("state")
    return {
        "state": node["state"], "draft": node["isDraft"], "author": _login(node.get("author")),
        "title": node["title"], "url": node["url"], "head": node["headRefOid"],
        "base": node["baseRefName"], "default_base": node["baseRefName"] == default,
        "review_decision": node.get("reviewDecision"), "merge_state": node.get("mergeStateStatus"),
        "ci": CI.get(rollup, "none"),
        "unresolved_threads": sum(not t["isResolved"] for t in node["reviewThreads"]["nodes"]),
        "review_requests": [r["requestedReviewer"].get("login") or r["requestedReviewer"].get("slug")
                            for r in node["reviewRequests"]["nodes"] if r.get("requestedReviewer")],
        "reviews": {_login(r["author"]): {"state": r["state"], "commit": (r.get("commit") or {}).get("oid"),
                                          "at": r["submittedAt"]}
                    for r in node["latestReviews"]["nodes"] if r.get("author")},
        **_turn(_events(node, commit)),
        "additions": node["additions"], "deletions": node["deletions"],
        "labels": [lb["name"] for lb in node["labels"]["nodes"]],
        "links": pr_links(node, repo, default),
    }


def pr_links(node: dict, repo: str, default: str | None) -> list[dict]:
    """GitHub-derived links of a PR: closing refs, body refs and the PR it is stacked on."""
    self_id = f"{repo}#{node['number']}"
    fixes = [f"{i['repository']['nameWithOwner']}#{i['number']}" for i in node["closingIssuesReferences"]["nodes"]]
    follow = []
    if node["baseRefName"] != default and node.get("baseRef"):
        follow = [f"{repo}#{p['number']}" for p in node["baseRef"]["associatedPullRequests"]["nodes"]]
    related = [i for i in body_refs(node.get("body") or "", repo) if i not in {self_id, *fixes, *follow}]
    return ([{"id": i, "rel": "fixes", "src": "github"} for i in fixes]
            + [{"id": i, "rel": "follow_up", "src": "github"} for i in follow]
            + [{"id": i, "rel": "related", "src": "github"} for i in related])


def body_refs(body: str, repo: str) -> list[str]:
    """Issue and PR ids a PR body points at: GitHub URLs, owner/repo#N, repo#N, and #N on a related-issue line."""
    text = HTML_COMMENT.sub("", body)
    found: list[tuple[int, str]] = []
    found += [(m.start(), f"{m[1]}/{m[2]}#{m[3]}") for m in GH_URL.finditer(text)]
    found += [(m.start(), f"{m[1]}#{m[2]}") for m in FULL_REF.finditer(text)]
    found += [(m.start(), f"{ORG}/{m[1]}#{m[2]}") for m in SHORT_REF.finditer(text) if m[1] not in NOT_REPOS]
    pos = 0
    for line in text.splitlines(keepends=True):
        if RELATED_LINE.search(line):
            found += [(pos + m.start(), f"{repo}#{m[1]}") for m in BARE_REF.finditer(line)]
        pos += len(line)
    return list(dict.fromkeys(i for _, i in sorted(found)))


def search_entry(node: dict) -> dict:
    """Mentions entry for one search node (issue or PR)."""
    return {"id": _node_id(node), "is_pr": node["__typename"] == "PullRequest", "title": node["title"],
            "url": node["url"], "author": _login(node.get("author")), "updated_at": node["updatedAt"]}


def issue_turn(node: dict) -> dict:
    """my_last, other_last and mention_after_mine of an issue node of the ISSUE_FIELDS shape."""
    events = [_event(node.get("author"), node["createdAt"], "comment", node.get("body"))]
    events += [_event(c.get("author"), c["createdAt"], "comment", c.get("body")) for c in node["comments"]["nodes"]]
    return _turn(sorted((e for e in events if e), key=lambda e: e["at"]))


def release_facts(backport: dict | None, merged: list[dict], stable_messages: list[str]) -> dict | None:
    """Open backport PR, the PRs it picked, and labelled merges that are on neither it nor stable."""
    if backport is None:
        return None
    picked = [n for c in backport["commits"]["nodes"] if (n := _pick_number(c["commit"]["message"]))]
    on_stable = {n for m in stable_messages if (n := _pick_number(m))}
    missing = [{"number": p["number"], "title": p["title"]} for p in sorted(merged, key=lambda p: p["number"])
               if p["number"] not in picked and p["number"] not in on_stable]
    return {"backport_pr": f"{SERVER}#{backport['number']}", "version": backport["headRefName"].removeprefix("backport/"),
            "picked": picked, "missing": missing}


def _fetch(state_dir: Path) -> dict:
    """Run the whole pass: searches and release head first, then PR and mentioned issue batches and the missing picks."""
    states = [_read_json(state_dir / f"{name}.json") for name in ("pr-review", "issue-triage", "security-inbox")]
    first = _graphql(_first_query())
    searches = {k: [n for n in first[k]["nodes"] if n] for k in SEARCHES}
    backports = [n for n in first["backport"]["nodes"] if n and n["headRefName"].startswith("backport/")]
    backport = min(backports, key=lambda n: n["number"]) if backports else None
    released_at = first["server"]["latestRelease"]["publishedAt"]
    issues = [_node_id(n) for n in searches["mentions"] if n["__typename"] == "Issue"]
    ids = list(dict.fromkeys(state_targets(*states) + [_node_id(n) for k in SEARCHES for n in searches[k]
                                                        if n["__typename"] == "PullRequest"]))
    batches = [ids[i:i + BATCH] for i in range(0, len(ids), BATCH)]
    with ThreadPoolExecutor(WORKERS) as pool:
        missing_job = pool.submit(_graphql, _missing_query(released_at)) if backport else None
        issue_jobs = [pool.submit(_fetch_issues, issues[i:i + BATCH]) for i in range(0, len(issues), BATCH)]
        results = list(pool.map(_fetch_prs, batches)) + [job.result() for job in issue_jobs]
        missing_data = missing_job.result() if missing_job else None
    fetched: dict[str, dict] = {}
    cost = first["rateLimit"]["cost"] + (missing_data["rateLimit"]["cost"] if missing_data else 0)
    remaining = first["rateLimit"]["remaining"]
    for part, rate in results:
        fetched.update(part)
        cost += rate["cost"]
        remaining = min(remaining, rate["remaining"])
    release = None
    if missing_data:
        history = missing_data["server"]["ref"]["target"]["history"]["nodes"]
        release = release_facts(backport, [n for n in missing_data["merged"]["nodes"] if n],
                                [h["message"] for h in history])
    return {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rate": {"cost": cost, "remaining": remaining},
        "prs": {i: fetched[i] for i in ids if i in fetched},
        "review_requested": [_node_id(n) for n in searches["review_requested"]],
        # Issue mentions carry the turn facts a PR has, PR mentions find theirs under "prs".
        "mentions": [search_entry(n) | (fetched.get(_node_id(n), {}) if n["__typename"] == "Issue" else {})
                     for n in searches["mentions"]],
        "release": release,
    }


def _fetch_prs(batch: list[str]) -> tuple[dict, dict]:
    """Fetch one batch of PRs; a PR GitHub will not return is skipped with a stderr line."""
    parts = []
    for i, pid in enumerate(batch):
        repo, n = pid.split("#")
        owner, name = repo.split("/")
        parts.append(f'p{i}: repository(owner:"{owner}", name:"{name}"){{ pullRequest(number:{n}){{{PR_FIELDS}}} }}')
    data = _graphql("{ rateLimit{cost remaining}\n" + "\n".join(parts) + "}", partial=True)
    out = {}
    for i, pid in enumerate(batch):
        node = (data.get(f"p{i}") or {}).get("pullRequest")
        if node is None:
            print(f"gh_sync: skipped {pid}, not found or not readable", file=sys.stderr)
        else:
            out[pid] = pr_facts(node)
    return out, data["rateLimit"]


def _fetch_issues(batch: list[str]) -> tuple[dict, dict]:
    """Turn facts of one batch of mentioned issues; an issue GitHub will not return is skipped."""
    parts = []
    for i, iid in enumerate(batch):
        repo, n = iid.split("#")
        owner, name = repo.split("/")
        parts.append(f'i{i}: repository(owner:"{owner}", name:"{name}"){{ issue(number:{n}){{{ISSUE_FIELDS}}} }}')
    data = _graphql("{ rateLimit{cost remaining}\n" + "\n".join(parts) + "}", partial=True)
    out = {}
    for i, iid in enumerate(batch):
        node = (data.get(f"i{i}") or {}).get("issue")
        if node is None:
            print(f"gh_sync: skipped {iid}, not found or not readable", file=sys.stderr)
        else:
            out[iid] = issue_turn(node)
    return out, data["rateLimit"]


def _first_query() -> str:
    """Searches, the open backport PR and the latest stable release in one query."""
    parts = [f'{k}: search(query:{json.dumps(q + f" org:{ORG} is:open")}, type:ISSUE, first:100)'
             f'{{nodes{{{SEARCH_FIELDS}}}}}' for k, q in SEARCHES.items()]
    backport_q = json.dumps(f"repo:{SERVER} is:pr is:open head:backport/")
    parts.append(f"backport: search(query:{backport_q}, type:ISSUE, first:5){{nodes{{{BACKPORT_FIELDS}}}}}")
    parts.append(f'server: repository(owner:"{ORG}", name:"server"){{latestRelease{{publishedAt}}}}')
    return "{ rateLimit{cost remaining}\n" + "\n".join(parts) + "}"


def _missing_query(since: str) -> str:
    """Labelled server PRs merged since the last release, and stable commits since then."""
    merged_q = json.dumps(f"repo:{SERVER} is:pr is:merged label:{BACKPORT_LABEL} merged:>={since}")
    return ("{ rateLimit{cost remaining}\n"
            f"merged: search(query:{merged_q}, type:ISSUE, first:100){{nodes{{... on PullRequest{{number title}}}}}}\n"
            f'server: repository(owner:"{ORG}", name:"server"){{ref(qualifiedName:"refs/heads/stable"){{target{{'
            f'... on Commit{{history(first:100, since:{json.dumps(since)}){{nodes{{message}}}}}}}}}}}}}}')


def _events(node: dict, commit: dict) -> list[dict]:
    """Human comment, review, push and ready events of a PR, oldest first."""
    events = []
    for item in node["timelineItems"]["nodes"]:
        kind = item["__typename"]
        if kind == "IssueComment":
            events.append(_event(item.get("author"), item["createdAt"], "comment", item.get("body")))
        elif kind == "PullRequestReview" and item["state"] != "PENDING":
            events.append(_event(item.get("author"), item["submittedAt"], "review", item.get("body")))
        elif kind == "HeadRefForcePushedEvent":
            events.append(_event(item.get("actor"), item["createdAt"], "push"))
        elif kind == "ReadyForReviewEvent":
            events.append(_event(item.get("actor"), item["createdAt"], "ready"))
    if commit:
        events.append(_event(_commit_actor(commit, node.get("author")), commit["committedDate"], "push"))
    return sorted((e for e in events if e), key=lambda e: e["at"])


def _turn(events: list[dict]) -> dict:
    """Marvin's newest event, the newest other human event and whether a later one mentions him."""
    mine = [e for e in events if e["login"] == ME]
    others = [e for e in events if e["login"] != ME]
    my_last = mine[-1] if mine else None
    return {
        "my_last": {"at": my_last["at"], "kind": my_last["kind"]} if my_last else None,
        "other_last": {k: others[-1][k] for k in ("login", "at", "kind")} if others else None,
        "mention_after_mine": any(e["kind"] in ("comment", "review") and MENTION.search(e["body"])
                                  and (not my_last or e["at"] > my_last["at"]) for e in others),
    }


def _event(actor: dict | None, at: str, kind: str, body: str | None = None) -> dict | None:
    """One event, or None for a bot or a deleted account."""
    login = _login(actor)
    if not login or _is_bot(actor):
        return None
    return {"login": login, "at": at, "kind": kind, "body": body or ""}


def _commit_actor(commit: dict, pr_author: dict | None) -> dict | None:
    """Who pushed the head commit: committer, then author, then the PR author; None for a bot commit."""
    # A rebase or cherry-pick keeps the original author, the committer is who pushed it.
    # Web UI commits ("Update branch", suggestions) have GitHub as committer, so the author did it.
    for who in (commit.get("committer"), commit.get("author")):
        who = who or {}
        if who.get("name") == "GitHub":
            continue
        if who.get("user"):
            return who["user"]
        if (who.get("name") or "").endswith("[bot]"):
            return None
    return pr_author


def _is_bot(actor: dict | None) -> bool:
    """Whether an actor is a bot."""
    login = _login(actor) or ""
    return (actor or {}).get("__typename") == "Bot" or login.lower() in BOTS or login.endswith("[bot]")


def _login(actor: dict | None) -> str | None:
    """Login of an actor node."""
    return (actor or {}).get("login")


def _node_id(node: dict) -> str:
    """Canonical owner/repo#n id of a search node."""
    return f"{node['repository']['nameWithOwner']}#{node['number']}"


def _pick_number(message: str) -> int | None:
    """PR number at the end of a squash or cherry-pick subject."""
    found = PICK.findall(message.splitlines()[0] if message else "")
    return int(found[-1]) if found else None


def _full_repo(repo: str) -> str:
    """owner/name for a repo stored short or full."""
    return repo if "/" in repo else f"{ORG}/{repo}"


def _graphql(query: str, partial: bool = False) -> dict:
    """Run a read-only GraphQL query through gh; partial keeps data that came with per-node errors."""
    res = subprocess.run(["gh", "api", "graphql", "--input", "-"], input=json.dumps({"query": query}),
                         capture_output=True, text=True, timeout=60)
    try:
        body = json.loads(res.stdout or "{}")
    except json.JSONDecodeError:
        body = {}
    if body.get("data") and (partial or not body.get("errors")):
        return body["data"]
    raise GhError((body.get("errors") or [{}])[0].get("message") or (res.stderr or res.stdout).strip()[:200])


def _read_json(path: Path) -> dict:
    """A state file, or {} when the routine has not written it yet."""
    return json.loads(path.read_text()) if path.exists() else {}


def _write_atomic(path: Path, data: dict) -> None:
    """Write JSON through a temp file in the same directory and swap it in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
