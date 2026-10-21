"""Serve the routine reports on localhost and post issue-triage draft replies from the board.

Replaces `python3 -m http.server` in the local.routine-reports LaunchAgent. GET serves the report pages
with the action token and the posted state filled in. POST /api/issue-triage/post posts a card's draft
reply with `gh` after checking that the board is current and nobody commented since the draft, and
appends the post to a log the issue-triage routine folds back into its state.

Runs on the system /usr/bin/python3 (3.9), stdlib only.
"""
import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple
from urllib.parse import unquote, urlsplit

POST_PATH = "/api/issue-triage/post"
SUPPORT = "music-assistant/support"
GH_TIMEOUT = 60
MAX_BODY = 10_000
TOKEN = secrets.token_urlsafe(24)
POST_LOCK = threading.Lock()

ISSUE_QUERY = """query($owner: String!, $name: String!, $n: Int!) {
  repository(owner: $owner, name: $name) {
    issue(number: $n) { state comments(last: 20) { nodes { author { __typename login } createdAt } } }
  }
}"""
DISCUSSION_QUERY = """query($owner: String!, $name: String!, $n: Int!) {
  repository(owner: $owner, name: $name) {
    discussion(number: $n) {
      id closed
      comments(last: 20) {
        nodes { author { __typename login } createdAt replies(last: 1) { nodes { author { __typename login } createdAt } } }
      }
    }
  }
}"""
ADD_COMMENT = """mutation($id: ID!, $body: String!) {
  addDiscussionComment(input: {discussionId: $id, body: $body}) { comment { url } }
}"""


class Refused(Exception):
    """A post that was turned down, with the HTTP status to answer."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the routine reports and the issue-triage Post button.")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--dir", default="~/.claude-teamB/routine-reports")
    ap.add_argument("--state", default="~/git/dotfiles/routines/state/issue-triage.json")
    ap.add_argument("--log", default="~/.claude-teamB/routine-state/issue-triage-actions.jsonl")
    ap.add_argument("--dry-run", action="store_true", help="check everything but skip the GitHub write")
    args = ap.parse_args()
    for key in ("dir", "state", "log"):
        setattr(args, key, os.path.realpath(os.path.expanduser(getattr(args, key))))
    os.makedirs(os.path.dirname(args.log), exist_ok=True)
    Handler.cfg = args
    Handler.origins = {f"http://127.0.0.1:{args.port}", f"http://localhost:{args.port}"}
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.daemon_threads = True
    print(f"serving {args.dir} on http://{args.bind}:{args.port}{' (dry run)' if args.dry_run else ''}", flush=True)
    server.serve_forever()


class Handler(BaseHTTPRequestHandler):
    """Static report pages plus the post endpoint."""

    cfg: argparse.Namespace
    origins: set

    def do_GET(self) -> None:
        path = self._file(urlsplit(self.path).path)
        if not path:
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        with open(path, "rb") as f:
            data = f.read()
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.endswith(".html"):
            posted = json.dumps(_posted(self.cfg.log)).replace("</", "<\\/")
            data = data.replace(b"__ACTION_TOKEN__", TOKEN.encode()).replace(b"__POSTED__", posted.encode())
            ctype = "text/html; charset=utf-8"
        self._send(200, data, ctype)

    def do_POST(self) -> None:
        if urlsplit(self.path).path != POST_PATH:
            self._json(404, {"ok": False, "error": "Unknown endpoint"})
            return
        if self.headers.get("Origin") not in self.origins or not hmac.compare_digest(
            self.headers.get("X-Action-Token", ""), TOKEN
        ):
            self._json(403, {"ok": False, "error": "Forbidden"})
            return
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            self._json(415, {"ok": False, "error": "Send application/json"})
            return
        try:
            req = self._request()
            with POST_LOCK:
                url = _post(self.cfg, *req)
        except Refused as e:
            self._json(e.status, {"ok": False, "error": str(e)})
            return
        self._json(200, {"ok": True, "url": url})

    def _request(self) -> Tuple[str, int, str]:
        """Parse and validate the POST body."""
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY:
            raise Refused(400, "Bad request body")
        try:
            body = json.loads(self.rfile.read(length))
            repo, n, digest = body["repo"], body["n"], body["hash"]
        except (ValueError, KeyError, TypeError):
            raise Refused(400, "Bad request body")
        if not (isinstance(repo, str) and isinstance(n, int) and isinstance(digest, str)):
            raise Refused(400, "Bad request body")
        return repo, n, digest

    def _file(self, url_path: str) -> Optional[str]:
        """Map a URL path to a file in the report dir, or None."""
        parts = [p for p in unquote(url_path).split("/") if p]
        if not parts or any(p.startswith(".") for p in parts):
            return None
        path = os.path.realpath(os.path.join(self.cfg.dir, *parts))
        if not path.startswith(self.cfg.dir + os.sep) or not os.path.isfile(path):
            return None
        return path

    def _json(self, status: int, payload: dict) -> None:
        """Send a JSON answer."""
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _send(self, status: int, data: bytes, ctype: str) -> None:
        """Send a complete response."""
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def _post(cfg: argparse.Namespace, repo: str, n: int, digest: str) -> str:
    """Check the card and the thread, post the reply, log it and return the comment URL."""
    with open(cfg.state) as f:
        card = next(
            (c for c in json.load(f)["cards"] if (c.get("repo") or SUPPORT) == repo and c.get("n") == n), None
        )
    if not card:
        raise Refused(404, f"No card for {repo}#{n}")
    reply = card.get("reply") or ""
    if not reply.strip():
        raise Refused(409, f"{repo}#{n} has no draft reply")
    if hashlib.sha256(reply.encode("utf-8")).hexdigest()[:16] != digest:
        raise Refused(409, "The board is out of date, reload it")
    if any(e.get("repo") == repo and e.get("n") == n and e.get("hash") == digest for e in _log_entries(cfg.log)):
        raise Refused(409, "This draft was already posted")
    discussion = bool(card.get("discussion"))
    node_id = _guard(repo, n, discussion, (card.get("gh") or {}).get("at"))
    if cfg.dry_run:
        url = f"dry-run://{repo}#{n}"
    elif discussion:
        out = _gh(["api", "graphql", "--input", "-"], json.dumps({"query": ADD_COMMENT, "variables": {"id": node_id, "body": reply}}))
        url = json.loads(out)["data"]["addDiscussionComment"]["comment"]["url"]
    else:
        out = _gh(["issue", "comment", str(n), "-R", repo, "--body-file", "-"], reply)
        url = next((line for line in reversed(out.split()) if line.startswith("https://")), "")
    entry = {"at": _now(), "action": "post", "repo": repo, "n": n, "discussion": discussion, "hash": digest, "url": url}
    with open(cfg.log, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return url


def _guard(repo: str, n: int, discussion: bool, drafted_at: Optional[str]) -> str:
    """Refuse when the thread is closed or has a comment newer than the draft; return the discussion node id."""
    owner, name = repo.split("/", 1)
    query = DISCUSSION_QUERY if discussion else ISSUE_QUERY
    out = _gh(["api", "graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}", "-F", f"n={n}"])
    node = json.loads(out)["data"]["repository"]["discussion" if discussion else "issue"]
    if not node:
        raise Refused(404, f"{repo}#{n} was not found on GitHub")
    if node.get("closed") or node.get("state") == "CLOSED":
        raise Refused(409, f"{repo}#{n} is closed")
    comments = node["comments"]["nodes"]
    # Discussion replies sit inside threads, so the newest one can hide under an older top-level comment.
    comments += [r for c in comments for r in (c.get("replies") or {}).get("nodes", [])]
    # The routine leaves bot comments out of gh.at, so the triage bot's auto-reply must not block a post.
    people = [c for c in comments if (c.get("author") or {}).get("__typename") != "Bot"]
    last = max(people, key=lambda c: c["createdAt"], default=None)
    if last and (not drafted_at or _ts(last["createdAt"]) > _ts(drafted_at)):
        who = (last.get("author") or {}).get("login") or "ghost"
        raise Refused(409, f"New comment from {who} at {last['createdAt']} since the draft. Ask in the thread.")
    return node.get("id", "")


def _gh(args: list, stdin: Optional[str] = None) -> str:
    """Run gh and return stdout; a failure becomes a 502 with gh's stderr."""
    gh = shutil.which("gh") or "/opt/homebrew/bin/gh"
    try:
        res = subprocess.run([gh, *args], input=stdin, capture_output=True, text=True, timeout=GH_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Refused(502, f"gh failed: {e}")
    if res.returncode:
        raise Refused(502, f"gh failed: {(res.stderr or res.stdout).strip()[-500:]}")
    return res.stdout


def _posted(log: str) -> dict:
    """Latest post per repo#n, as the page's POSTED map."""
    return {f"{e['repo']}#{e['n']}": {"hash": e.get("hash"), "url": e.get("url")} for e in _log_entries(log)}


def _log_entries(log: str) -> list:
    """Post entries from the action log, skipping lines that don't parse."""
    entries = []
    try:
        with open(log) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("action") == "post" and "repo" in e and "n" in e:
                    entries.append(e)
    except FileNotFoundError:
        pass
    return entries


def _ts(value: str) -> datetime:
    """Parse a GitHub ISO timestamp."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _now() -> str:
    """Current UTC time in ISO-8601."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    main()
