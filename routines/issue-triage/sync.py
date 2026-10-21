"""Fold board posts and GitHub facts into the issue triage state before the model runs.

Usage: python3 sync.py <state.json> [--since <ISO>] [--report <path>] [--actions-log <path>] [--dry-run]

Writes card["sync"], refreshes gh, last, milestone and the test-asked badge, drops closed cards, prunes
design rows and follow-ups, rebuilds release_table and emits a JSON delta report for the model.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MARVIN = "MarvinSchenkel"
SUPPORT = "music-assistant/support"
CORE = "home-assistant/core"
SERVER = "music-assistant/server"
SERVER_DIR = os.path.expanduser("~/git/music-assistant/server")
ACTIONS_LOG = os.path.expanduser("~/.claude-teamB/routine-state/issue-triage-actions.jsonl")
LOCAL = ZoneInfo("Europe/Amsterdam")
TZ_OFFSETS = {"CEST": 2, "CET": 1, "UTC": 0}
TEAM_ASSOC = {"MEMBER", "OWNER", "COLLABORATOR"}
BOTS = {"musicassistant-bot", "github-actions", "copilot"}
TEST_ASK = re.compile(r"pr-\d+|server_repo|DEV SERVER|music_assistant_dev")
FIX_LABEL = "fix to be confirmed"
TAG = "@marvinschenkel"
MERGED_REPOS = (
    "server", "frontend", "models", "client", "home-assistant-addon", "desktop-app", "airplay-cli",
    "music-assistant.io",
)
SUPPORT_REF = re.compile(r"(?:music-assistant/support#|\bsupport#|github\.com/music-assistant/support/(?:issues|discussions)/)(\d+)")
LEAD_REFS = re.compile(r"^#\d+(?:\s*(?:,|/|\+|&|and)\s*#\d+)*")
PR_URL = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
STABLE_SUBJECT = re.compile(r"\(#(\d+)\)")
CARD_BATCH = 12
PR_BATCH = 25
COMMENTS = 15
WORKERS = 8

PR_FIELDS = "number url state isDraft mergedAt createdAt author{login} repository{nameWithOwner} mergeCommit{oid}"
COMMENT_FIELDS = "author{login __typename} authorAssociation createdAt url body"
ISSUE_FIELDS = f"""
  number title url state stateReason createdAt closedAt author{{login}} assignees(first:10){{nodes{{login}}}}
  labels(first:30){{nodes{{name}}}} milestone{{title}}
  comments(last:{COMMENTS}){{nodes{{{COMMENT_FIELDS}}}}}
  timelineItems(itemTypes:[CROSS_REFERENCED_EVENT,CONNECTED_EVENT,CLOSED_EVENT], last:50){{nodes{{__typename
    ... on CrossReferencedEvent{{createdAt willCloseTarget source{{... on PullRequest{{{PR_FIELDS}}}}}}}
    ... on ConnectedEvent{{createdAt subject{{... on PullRequest{{{PR_FIELDS}}}}}}}
    ... on ClosedEvent{{createdAt actor{{login}}}}}}}}
"""
DISCUSSION_FIELDS = f"""
  number title url closed closedAt stateReason createdAt author{{login}} labels(first:30){{nodes{{name}}}}
  comments(last:{COMMENTS}){{nodes{{{COMMENT_FIELDS} replies(last:1){{nodes{{{COMMENT_FIELDS}}}}}}}}}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync the issue triage state with GitHub.")
    parser.add_argument("state")
    parser.add_argument("--since", help="ISO time the delta report starts at (default: last_run)")
    parser.add_argument("--report", help="write the JSON delta report here (default: stdout)")
    parser.add_argument("--actions-log", default=ACTIONS_LOG, help="board posts log")
    parser.add_argument("--dry-run", action="store_true", help="print the report, leave the state alone")
    args = parser.parse_args()
    with open(args.state) as f:
        state = json.load(f)
    now = datetime.now(timezone.utc)
    since = _parse(args.since) if args.since else _run_time(state.get("last_run") or "")
    if since is None:
        parser.error("no --since and last_run can't be parsed")
    report = sync(state, now, since, args.actions_log)
    out = json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    if args.report:
        with open(args.report, "w") as f:
            f.write(out)
    else:
        sys.stdout.write(out)
    if not args.dry_run:
        tmp = args.state + ".tmp"
        with open(tmp, "w") as f:
            f.write(json.dumps(state, indent=1, ensure_ascii=False) + "\n")
        os.replace(tmp, args.state)


def sync(state: dict, now: datetime, since: datetime, actions_log: str) -> dict:
    """Apply every deterministic sweep to the state in place and return the delta report."""
    errors: list[str] = []
    report: dict = {"at": _iso(now), "since": _iso(since), "counts": {}}
    report["posted_from_board"] = fold_board_posts(state, actions_log)
    cards = state["cards"]
    gh_before = {_key(c): dict(c.get("gh") or {}) for c in cards}

    with ThreadPoolExecutor(WORKERS) as pool:
        server_job = pool.submit(_server_facts, errors)
        searches = {
            "new_issues": pool.submit(_new_issues, since, errors),
            "ha_core": pool.submit(_ha_core, since, errors),
            "discussions_tagged": pool.submit(_discussions_tagged, since, errors),
            "merged_prs": pool.submit(_merged_prs, since, errors),
        }
        nodes = _fetch_cards(cards, pool, errors)
        details = _fetch_pr_details(cards, nodes, pool, errors)
        codeowners, stable_oids, stable_prs = server_job.result()
        search_results = {k: v.result() for k, v in searches.items()}

    ctx = {"now": now, "since": since, "codeowners": codeowners, "details": details}
    facts, closed = {}, []
    for c in cards:
        node = nodes.get(_key(c))
        if node is None:
            continue
        if node.get("state") == "CLOSED" or node.get("closed"):
            closed.append((c, node))
        else:
            facts[_key(c)] = sync_card(c, node, ctx)

    report["closed_dropped"] = [_drop(state, c, node, now) for c, node in closed]
    report["pruned"] = _prune(state, {c["n"] for c, _ in closed})
    state["release_table"] = _release_table(state, facts, stable_oids, stable_prs)

    on_board = {_key(c) for c in state["cards"]}
    report["reporter_new"] = [_new_entry(c, facts, False) for c in state["cards"] if _key(c) in facts and facts[_key(c)]["reporter_new"]]
    report["team_new"] = [_new_entry(c, facts, True) for c in state["cards"] if _key(c) in facts and facts[_key(c)]["team_new"]]
    report["prs_merged_since"] = [e for c in state["cards"] if _key(c) in facts for e in facts[_key(c)]["merged_since"]]
    report["prs_opened_since"] = [e for c in state["cards"] if _key(c) in facts for e in facts[_key(c)]["opened_since"]]
    report["test_ask_found"] = [facts[_key(c)]["test_ask"] for c in state["cards"] if _key(c) in facts and facts[_key(c)]["test_ask"]]
    search_results["new_issues"] = [i for i in search_results["new_issues"] if (i["repo"], i["n"]) not in on_board]
    for key, items in search_results.items():
        report[key] = _mark_on_board(items, on_board)
    report["drift"] = _drift(state["cards"], gh_before)
    report["errors"] = errors
    report["counts"] = {k: len(v) for k, v in report.items() if isinstance(v, list)}
    report["counts"].update({f"pruned_{k}": len(v) for k, v in report["pruned"].items()})
    report["counts"]["cards"] = len(state["cards"])
    return report


def fold_board_posts(state: dict, path: str) -> list[dict]:
    """Treat board posts newer than actions_applied_at as replies that already went out."""
    applied = _parse(state.get("actions_applied_at")) or datetime.min.replace(tzinfo=timezone.utc)
    newest = applied
    by_key = {_key(c): c for c in state["cards"]}
    out = []
    for line in _read_lines(path):
        at = _parse(line.get("at"))
        if not at or at <= applied or line.get("action", "post") != "post":
            continue
        newest = max(newest, at)
        card = by_key.get((line.get("repo") or SUPPORT, line.get("n")))
        out.append({"n": line.get("n"), "repo": line.get("repo") or SUPPORT, "at": line["at"], "url": line.get("url"),
                    "edited": bool(line.get("edited")), "on_board": card is not None})
        if card is None:
            continue
        card["reply"] = ""
        card["badges"] = [b for b in card.get("badges") or [] if _kind(b) not in ("needs attention", "auto held")]
        # Only a reply ask is answered by the post; a design call or input stays with Marvin.
        if str(card.get("ask") or "").startswith("reply-") or not card.get("ask"):
            card["action"] = ""
            card.pop("ask", None)
            if not any(_kind(b) == "waiting" for b in card["badges"]):
                card["badges"].append(["info", "Waiting for user", "waiting"])
        card.setdefault("gh", {}).update({"login": MARVIN, "team": True, "at": _iso(at)})
        card["last"] = f"{MARVIN} {at:%Y-%m-%d %H:%M}"
        url = line.get("url") or ""
        notes = card.setdefault("notes", [])
        if not url or not any(url in n for n in notes):
            edits = ", with your edits" if line.get("edited") else ""
            notes.append(f"{_local(at)} sync: you posted from the board ({url}){edits}")
    if newest > applied:
        state["actions_applied_at"] = _iso(newest)
    return out


def sync_card(card: dict, node: dict, ctx: dict) -> dict:
    """Refresh one open card from its GitHub node and return the facts the report needs."""
    repo, n = _key(card)
    since = ctx["since"]
    author = _login(node.get("author"))
    humans = []
    for cm in _comments(node):
        login = _login(cm.get("author"))
        if not login or _is_bot(cm.get("author")):
            continue
        team = _is_team(login, cm.get("authorAssociation"), author, ctx["codeowners"])
        humans.append({"login": login, "team": team, "at": cm["createdAt"], "url": cm["url"], "body": cm.get("body") or ""})
    humans.sort(key=lambda h: h["at"])
    if humans:
        last = humans[-1]
    else:
        last = {"login": author or "ghost", "team": author == MARVIN, "at": node["createdAt"], "url": node["url"]}

    gh = card.setdefault("gh", {})
    prev_at = _parse(gh.get("at"))
    fresh = [h for h in humans if prev_at and _parse(h["at"]) > prev_at]

    prs, merged_since, opened_since = _card_prs(card, node, ctx)
    own_open = [p for p in prs if p["own"] and p["state"] == "OPEN"]
    gh.update({"login": last["login"], "team": last["team"], "at": last["at"],
               "pr_open": bool(own_open), "pr_draft": bool(own_open) and all(p["draft"] for p in own_open)})
    card["last"] = f"{last['login']} {_parse(last['at']):%Y-%m-%d %H:%M}"
    card["milestone"] = (node.get("milestone") or {}).get("title")

    asks = [h for h in humans if h["team"] and TEST_ASK.search(h["body"])]
    ask = asks[-1] if asks else None
    after_ask = bool(ask) and any(not h["team"] and h["at"] > ask["at"] for h in humans)
    test_entry = None
    if ask:
        changed = _set_test_badge(card, ask["at"])
        if changed or _parse(ask["at"]) >= since:
            test_entry = {"n": n, "repo": repo, "at": ask["at"], "url": ask["url"], "by": ask["login"],
                          "badge_changed": changed, "after_test_ask_reporter": after_ask}

    labels = [x["name"] for x in (node.get("labels") or {}).get("nodes") or []]
    card["sync"] = {
        "at": _iso(ctx["now"]),
        "last_human": {k: last[k] for k in ("login", "at", "team", "url")},
        "reporter_new": any(not h["team"] for h in fresh),
        "team_new": any(h["team"] for h in fresh),
        "closed": False,
        "pr": [{k: p[k] for k in ("repo", "n", "state", "draft", "merged_at", "own")} for p in prs],
        "test_ask": {"at": ask["at"], "url": ask["url"]} if ask else None,
        "after_test_ask_reporter": after_ask,
        "labels": labels,
    }
    return {
        "reporter_new": card["sync"]["reporter_new"],
        "team_new": card["sync"]["team_new"],
        "fresh": fresh,
        "prs": prs,
        "labels": labels,
        "merged_since": merged_since,
        "opened_since": opened_since,
        "test_ask": test_entry,
    }


def _card_prs(card: dict, node: dict, ctx: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Merge listed and cross-referenced PRs into sync.pr entries plus the report's merged/opened lists."""
    repo, n = _key(card)
    since = ctx["since"]
    listed = _listed_prs(card)
    refs: dict[tuple[str, int], dict] = {}
    for ev in ((node.get("timelineItems") or {}).get("nodes") or []):
        pr = ev.get("source") or ev.get("subject")
        if not pr or "number" not in pr:
            continue
        k = (pr["repository"]["nameWithOwner"], pr["number"])
        prev = refs.get(k)
        refs[k] = {"pr": pr, "at": min(ev["createdAt"], prev["at"]) if prev else ev["createdAt"],
                   "closes": ev.get("willCloseTarget") or ev["__typename"] == "ConnectedEvent" or bool(prev and prev["closes"])}
    out, merged_since, opened_since = [], [], []
    for k in list(dict.fromkeys(listed + list(refs))):
        ref = refs.get(k)
        pr = ref["pr"] if ref else ctx["details"].get(k)
        if not pr:
            continue
        detail = ctx["details"].get(k) or {}
        is_listed = k in listed
        fixes = is_listed or bool(ref and ref["closes"]) or _body_fixes(detail.get("body") or "", repo, n, k[0])
        entry = {
            "repo": k[0], "n": k[1], "state": pr["state"], "draft": bool(pr.get("isDraft")),
            "merged_at": pr.get("mergedAt"),
            # A docs PR documents a fix, it doesn't make the card "in progress".
            "own": _login(pr.get("author")) == MARVIN and fixes and not k[0].endswith("music-assistant.io"),
            "fixes": fixes, "listed": is_listed, "author": _login(pr.get("author")),
            "merge_oid": (pr.get("mergeCommit") or {}).get("oid"), "url": pr["url"],
        }
        out.append(entry)
        ref_label = _short(k[0]) + f"#{k[1]}"
        if entry["merged_at"] and _parse(entry["merged_at"]) >= since:
            merged_since.append({"n": n, "repo": repo, "pr": ref_label, "url": entry["url"], "author": entry["author"],
                                 "merged_at": entry["merged_at"], "own": entry["own"], "fixes": fixes, "listed": is_listed})
        if not is_listed and ref and max(_parse(ref["at"]), _parse(pr["createdAt"])) >= since:
            opened_since.append({"n": n, "repo": repo, "pr": ref_label, "url": entry["url"], "author": entry["author"],
                                 "state": entry["state"], "draft": entry["draft"], "own": entry["own"], "fixes": fixes})
    return out, merged_since, opened_since


def _body_fixes(body: str, issue_repo: str, n: int, pr_repo: str) -> bool:
    """Whether a PR body names the issue on a 'related issue' or closing-keyword line."""
    refs = [rf"{re.escape(issue_repo)}#{n}\b", rf"github\.com/{re.escape(issue_repo)}/(?:issues|discussions)/{n}\b"]
    if issue_repo == SUPPORT:
        refs.append(rf"\bsupport#{n}\b")
    if issue_repo == pr_repo:
        refs.append(rf"(?<![\w/])#{n}\b")
    ref = "(?:" + "|".join(refs) + ")"
    keyword = r"(?:related issues?|fix(?:es|ed)?|close[sd]?|resolve[sd]?)"
    return bool(re.search(rf"{keyword}\b[^\n]{{0,80}}?{ref}", body, re.I))


def _set_test_badge(card: dict, at: str) -> bool:
    """Put one current test-asked badge on the card; returns whether it changed."""
    badge = ["info", f"Test asked {_parse(at).astimezone(LOCAL):%m-%d}", "test asked"]
    badges = card.setdefault("badges", [])
    idx = [i for i, b in enumerate(badges) if _kind(b) == "test asked"]
    if len(idx) == 1 and badges[idx[0]] == badge:
        return False
    # Fix merged cards drop their open test ask (SKILL "Issue bookkeeping"), so don't re-add one there.
    if not idx and card.get("col") == "merged":
        return False
    if idx:
        badges[idx[0]] = badge
        for i in reversed(idx[1:]):
            del badges[i]
    else:
        badges.append(badge)
    return True


def _drop(state: dict, card: dict, node: dict, now: datetime) -> dict:
    """Remove a closed card, log it in gone and drop its design rows and follow-ups."""
    closed_at, actor = node.get("closedAt"), None
    for ev in reversed((node.get("timelineItems") or {}).get("nodes") or []):
        if ev.get("__typename") == "ClosedEvent":
            closed_at, actor = ev["createdAt"], _login(ev.get("actor"))
            break
    reason = (node.get("stateReason") or "").lower().replace("_", " ")
    how = " ".join(x for x in (f"as {reason}" if reason else "", f"by {actor}" if actor else "") if x)
    when = f"{_parse(closed_at):%m-%d %H:%M} UTC" if closed_at else "date unknown"
    ref = _ref(card)
    state["cards"].remove(card)
    state["gone"] = (state.get("gone") or "") + f" Dropped {_local(now)}: {ref} (closed {how} {when})."
    return {"n": card["n"], "repo": _key(card)[0], "title": card.get("title"), "reason": reason or None,
            "by": actor, "closed_at": closed_at}


def _prune(state: dict, closed_now: set[int]) -> dict:
    """Drop design rows and follow-ups of issues closed this run, once none of their leading #refs is on the board."""
    board = {c["n"] for c in state["cards"] if _key(c)[0] == SUPPORT}

    def gone(text: str) -> bool:
        m = LEAD_REFS.match(text or "")
        refs = {int(x) for x in re.findall(r"\d+", m.group(0))} if m else set()
        return bool(refs & closed_now) and not refs & board

    design = state.get("design") or []
    followups = state.get("followups") or []
    pruned = {"design": [r[0] for r in design if gone(r[0])], "followups": [f for f in followups if gone(f)]}
    if "design" in state:
        state["design"] = [r for r in design if not gone(r[0])]
    if "followups" in state:
        state["followups"] = [f for f in followups if not gone(f)]
    return pruned


def _release_table(state: dict, facts: dict, stable_oids: set[str] | None, stable_prs: set[int]) -> dict:
    """Group open 'Fix to be Confirmed' cards with a milestone by milestone, with their merged fixes."""
    table: dict[str, list] = {}
    for c in state["cards"]:
        f = facts.get(_key(c))
        if not f or not c.get("milestone") or FIX_LABEL not in {x.lower() for x in f["labels"]}:
            continue
        merged = [p for p in f["prs"] if p["state"] == "MERGED" and p["fixes"]]
        server = [p for p in merged if p["repo"] == SERVER and p["merge_oid"]]
        on_stable = None
        if server and stable_oids is not None:
            on_stable = all(p["merge_oid"] in stable_oids or p["n"] in stable_prs for p in server)
        table.setdefault(c["milestone"], []).append({
            "n": c["n"], "title": c.get("title"), "prs": [f"{_short(p['repo'])}#{p['n']}" for p in merged],
            "on_stable": on_stable,
        })
    return dict(sorted(table.items()))


def _fetch_cards(cards: list[dict], pool: ThreadPoolExecutor, errors: list[str]) -> dict:
    """Read every card's issue or discussion in batched, aliased GraphQL queries."""
    batches = [cards[i:i + CARD_BATCH] for i in range(0, len(cards), CARD_BATCH)]

    def run(batch: list[dict]) -> dict:
        parts = []
        for i, c in enumerate(batch):
            owner, name = _key(c)[0].split("/")
            kind, fields = ("discussion", DISCUSSION_FIELDS) if c.get("discussion") else ("issue", ISSUE_FIELDS)
            parts.append(f'c{i}: repository(owner:"{owner}", name:"{name}"){{ {kind}(number:{c["n"]}){{{fields}}} }}')
        data = _graphql("{" + "\n".join(parts) + "}", errors)
        out = {}
        for i, c in enumerate(batch):
            repo_node = data.get(f"c{i}") or {}
            node = repo_node.get("discussion" if c.get("discussion") else "issue")
            if node is None:
                errors.append(f"{_ref(c)}: not found or not readable, card left as is")
            else:
                out[_key(c)] = node
        return out

    nodes = {}
    for part in pool.map(run, batches):
        nodes.update(part)
    return nodes


def _fetch_pr_details(cards: list[dict], nodes: dict, pool: ThreadPoolExecutor, errors: list[str]) -> dict:
    """Read listed PRs the timeline lacks, and bodies of cross-referenced PRs not listed on the card."""
    want: dict[tuple[str, int], bool] = {}
    for c in cards:
        node = nodes.get(_key(c))
        if node is None:
            continue
        listed = _listed_prs(c)
        refs = {(p["repository"]["nameWithOwner"], p["number"])
                for ev in (node.get("timelineItems") or {}).get("nodes") or []
                if (p := ev.get("source") or ev.get("subject")) and "number" in p}
        for k in listed:
            if k not in refs:
                want.setdefault(k, False)
        for k in refs - set(listed):
            want[k] = True
    items = list(want.items())
    batches = [items[i:i + PR_BATCH] for i in range(0, len(items), PR_BATCH)]

    def run(batch: list) -> dict:
        parts = []
        for i, ((repo, n), body) in enumerate(batch):
            owner, name = repo.split("/")
            parts.append(f'p{i}: repository(owner:"{owner}", name:"{name}"){{ pullRequest(number:{n}){{{PR_FIELDS}{" body" if body else ""}}} }}')
        data = _graphql("{" + "\n".join(parts) + "}", errors)
        return {k: (data.get(f"p{i}") or {}).get("pullRequest") for i, (k, _) in enumerate(batch)}

    details = {}
    for part in pool.map(run, batches):
        details.update({k: v for k, v in part.items() if v})
    return details


def _server_facts(errors: list[str]) -> tuple[set[str], set[str] | None, set[int]]:
    """Fetch the server repo and read provider codeowners plus what is on origin/stable."""
    fetch = _git(["fetch", "--quiet", "origin", "dev", "stable"], errors)
    if fetch is None:
        errors.append("server: git fetch failed, using the local origin/dev and origin/stable")
    owners: set[str] = set()
    paths = _git(["ls-tree", "-r", "--name-only", "origin/dev", "music_assistant/providers"], errors) or ""
    manifests = [p for p in paths.splitlines() if re.fullmatch(r"music_assistant/providers/[^/]+/manifest\.json", p)]
    if manifests:
        blob = subprocess.run(["git", "-C", SERVER_DIR, "cat-file", "--batch"], capture_output=True,
                              input="".join(f"origin/dev:{p}\n" for p in manifests).encode())
        for text in _split_cat_file(blob.stdout):
            try:
                for login in json.loads(text).get("codeowners") or []:
                    owners.add(login.lstrip("@").lower())
            except (json.JSONDecodeError, AttributeError):
                continue
    log = _git(["log", "origin/stable", "--format=%H %s"], errors)
    if log is None:
        return owners, None, set()
    oids, prs = set(), set()
    for line in log.splitlines():
        oid, _, subject = line.partition(" ")
        oids.add(oid)
        prs.update(int(x) for x in STABLE_SUBJECT.findall(subject))
    return owners, oids, prs


def _new_issues(since: datetime, errors: list[str]) -> list[dict]:
    """Open support issues updated since, not assigned to someone else."""
    q = f"repo:{SUPPORT} is:issue is:open updated:>={_iso(since)}"
    out = []
    for node in _search(q, "ISSUE", "... on Issue{number title url createdAt updatedAt author{login} assignees(first:5){nodes{login}} labels(first:10){nodes{name}}}", errors):
        assignees = [a["login"] for a in node["assignees"]["nodes"]]
        if assignees and MARVIN not in assignees:
            continue
        out.append({"n": node["number"], "repo": SUPPORT, "title": node["title"], "author": _login(node.get("author")),
                    "created": node["createdAt"], "updated": node["updatedAt"], "url": node["url"],
                    "assignees": assignees, "labels": [x["name"] for x in node["labels"]["nodes"]]})
    return out


def _ha_core(since: datetime, errors: list[str]) -> list[dict]:
    """HA core issues with the music_assistant integration label updated since."""
    q = f'repo:{CORE} is:issue label:"integration: music_assistant" updated:>={_iso(since)}'
    return [{"n": node["number"], "repo": CORE, "title": node["title"], "state": node["state"],
             "author": _login(node.get("author")), "created": node["createdAt"], "updated": node["updatedAt"],
             "url": node["url"], "assignees": [a["login"] for a in node["assignees"]["nodes"]]}
            for node in _search(q, "ISSUE", "... on Issue{number title url state createdAt updatedAt author{login} assignees(first:5){nodes{login}}}", errors)]


def _discussions_tagged(since: datetime, errors: list[str]) -> list[dict]:
    """Support discussions where an OzGav comment tags Marvin."""
    q = f"repo:{SUPPORT} commenter:OzGav updated:>={_iso(since)}"
    fields = (f"... on Discussion{{number title url closed updatedAt comments(last:30){{nodes{{{COMMENT_FIELDS} "
              f"replies(last:10){{nodes{{{COMMENT_FIELDS}}}}}}}}}}}")
    out = []
    for node in _search(q, "DISCUSSION", fields, errors):
        tags = [cm for cm in _comments(node)
                if _login(cm.get("author")) == "OzGav" and TAG in (cm.get("body") or "").lower()]
        if tags:
            tag = max(tags, key=lambda cm: cm["createdAt"])
            out.append({"n": node["number"], "repo": SUPPORT, "discussion": True, "title": node["title"],
                        "url": node["url"], "closed": node["closed"], "tagged_at": tag["createdAt"], "tag_url": tag["url"],
                        "new": _parse(tag["createdAt"]) >= since})
    return out


def _merged_prs(since: datetime, errors: list[str]) -> list[dict]:
    """PRs merged since in the MA repos, with the support issues their body references."""

    def run(name: str) -> list[dict]:
        repo = f"music-assistant/{name}"
        raw = _gh(["pr", "list", "--repo", repo, "--state", "merged", "--search", f"merged:>={_iso(since)}",
                   "--limit", "100", "--json", "number,title,mergedAt,author,body,labels,url"], errors)
        out = []
        for pr in json.loads(raw or "[]"):
            issues = sorted({int(x) for x in SUPPORT_REF.findall(pr.get("body") or "")})
            out.append({"repo": repo, "pr": f"{name}#{pr['number']}", "title": pr["title"], "merged_at": pr["mergedAt"],
                        "author": _login(pr.get("author")), "labels": [x["name"] for x in pr.get("labels") or []],
                        "url": pr["url"], "issues": issues})
        return out

    with ThreadPoolExecutor(len(MERGED_REPOS)) as pool:
        return [pr for prs in pool.map(run, MERGED_REPOS) for pr in prs]


def _mark_on_board(items: list[dict], on_board: set) -> list[dict]:
    """Flag search hits that already have a card."""
    for it in items:
        if "issues" in it:
            it["on_board"] = [n for n in it["issues"] if (SUPPORT, n) in on_board]
        else:
            it["on_board"] = (it["repo"], it["n"]) in on_board
    return items


def _new_entry(card: dict, facts: dict, team: bool) -> dict:
    """Report entry for a card with new comments from the reporter side or the team."""
    f = facts[_key(card)]
    return {"n": card["n"], "repo": _key(card)[0], "title": card.get("title"), "col": card.get("col"),
            "ask": card.get("ask"), "has_reply": bool(card.get("reply")),
            "comments": [{"login": h["login"], "at": h["at"], "url": h["url"], "text": h["body"][:300]}
                         for h in f["fresh"] if h["team"] == team]}


def _drift(cards: list[dict], before: dict) -> list[dict]:
    """Cards whose gh snapshot changed this run, with the changed fields."""
    out = []
    for c in cards:
        old, new = before.get(_key(c)) or {}, c.get("gh") or {}
        diff = {k: [old.get(k), new.get(k)] for k in ("login", "team", "at", "pr_open", "pr_draft") if old.get(k) != new.get(k)}
        # Older runs stored minute-rounded times; a seconds-only shift isn't drift.
        if "at" in diff and "login" not in diff and _close(old.get("at"), new.get("at")):
            del diff["at"]
        if diff:
            out.append({"n": c["n"], "repo": _key(c)[0], "changed": diff})
    return out


def _search(query: str, kind: str, fields: str, errors: list[str]) -> list[dict]:
    """Run a GraphQL search and return its nodes."""
    q = f'{{ search(query:{json.dumps(query)}, type:{kind}, first:100){{ nodes{{ {fields} }} }} }}'
    return [n for n in ((_graphql(q, errors).get("search") or {}).get("nodes") or []) if n]


def _graphql(query: str, errors: list[str]) -> dict:
    """Run a GraphQL query through gh, retrying once, and return its data (partial on errors)."""
    for attempt in (1, 2):
        res = subprocess.run(["gh", "api", "graphql", "--input", "-"], input=json.dumps({"query": query}),
                             capture_output=True, text=True)
        try:
            body = json.loads(res.stdout or "{}")
        except json.JSONDecodeError:
            body = {}
        if body.get("data"):
            for e in body.get("errors") or []:
                errors.append(f"graphql: {e.get('message')}")
            return body["data"]
        if attempt == 2:
            errors.append(f"graphql failed: {(res.stderr or res.stdout).strip()[:300]}")
    return {}


def _gh(args: list[str], errors: list[str]) -> str | None:
    """Run a read-only gh command and return stdout."""
    res = subprocess.run(["gh", *args], capture_output=True, text=True)
    if res.returncode:
        errors.append(f"gh {' '.join(args[:4])}: {res.stderr.strip()[:300]}")
        return None
    return res.stdout


def _git(args: list[str], errors: list[str]) -> str | None:
    """Run git in the server repo and return stdout."""
    res = subprocess.run(["git", "-C", SERVER_DIR, *args], capture_output=True, text=True)
    if res.returncode:
        errors.append(f"git {' '.join(args[:3])}: {res.stderr.strip()[:300]}")
        return None
    return res.stdout


def _split_cat_file(raw: bytes) -> list[str]:
    """Split `git cat-file --batch` output into blob texts."""
    out, pos = [], 0
    while pos < len(raw):
        end = raw.index(b"\n", pos)
        header = raw[pos:end].split()
        pos = end + 1
        if len(header) < 3 or header[1] == b"missing":
            continue
        size = int(header[2])
        out.append(raw[pos:pos + size].decode(errors="replace"))
        pos += size + 1
    return out


def _comments(node: dict) -> list[dict]:
    """Flatten comments and their fetched replies."""
    out = []
    for cm in (node.get("comments") or {}).get("nodes") or []:
        if not cm:
            continue
        out.append(cm)
        out.extend(r for r in ((cm.get("replies") or {}).get("nodes") or []) if r)
    return out


def _listed_prs(card: dict) -> list[tuple[str, int]]:
    """PRs linked in the card's prs field, in order."""
    out = []
    for p in card.get("prs") or []:
        m = PR_URL.search(p.get("url") or "")
        if m and (m.group(1), int(m.group(2))) not in out:
            out.append((m.group(1), int(m.group(2))))
    return out


def _is_team(login: str, assoc: str | None, author: str | None, codeowners: set[str]) -> bool:
    """Whether a comment author counts as Marvin or a teammate on this issue."""
    if login == MARVIN:
        return True
    if login == author:
        return False
    return assoc in TEAM_ASSOC or login.lower() in codeowners


def _is_bot(author: dict | None) -> bool:
    """Whether a comment author is a bot."""
    login = (author or {}).get("login") or ""
    return (author or {}).get("__typename") == "Bot" or login in BOTS or login.endswith("[bot]")


def _login(author: dict | None) -> str | None:
    """Login of a GraphQL actor, if any."""
    return (author or {}).get("login")


def _key(card: dict) -> tuple[str, int]:
    """Repo and number identifying a card."""
    return card.get("repo") or SUPPORT, card["n"]


def _ref(card: dict) -> str:
    """Short reference used in gone, design and follow-ups."""
    repo = _key(card)[0]
    return f"#{card['n']}" if repo == SUPPORT else f"{'core' if repo == CORE else repo.split('/')[-1]}#{card['n']}"


def _short(repo: str) -> str:
    """Repo name as used in short PR refs like server#7131."""
    return repo.split("/")[1] if repo.startswith("music-assistant/") else repo


def _kind(b: list) -> str:
    """Badge kind, falling back to its label."""
    return b[2] if len(b) > 2 and b[2] else b[1]


def _read_lines(path: str) -> list[dict]:
    """Parse a JSONL file, skipping blank and broken lines."""
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _run_time(run: str) -> datetime | None:
    """Parse a last_run string like '2026-10-21 07:38 CEST'."""
    try:
        stamp, tz = run[:16], run[17:].strip() or "UTC"
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=timezone(timedelta(hours=TZ_OFFSETS.get(tz, 0))))
    except ValueError:
        return None


def _parse(value: str | None) -> datetime | None:
    """Parse an ISO time, treating a naive one as UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _close(a: str | None, b: str | None) -> bool:
    """Whether two ISO times are under a minute apart."""
    x, y = _parse(a), _parse(b)
    return bool(x and y) and abs((x - y).total_seconds()) < 60


def _iso(dt: datetime) -> str:
    """UTC ISO time with a Z suffix, as GitHub writes it."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local(dt: datetime) -> str:
    """Note stamp 'MM-DD HH:MM' in Marvin's time zone."""
    return dt.astimezone(LOCAL).strftime("%m-%d %H:%M")


if __name__ == "__main__":
    main()
