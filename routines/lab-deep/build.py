"""Render the lab deep run report and its inline digest from the routine's state and the runs' JUnit files.

Usage: python3 build.py <state.json> --runs-dir <dir> --flakes <flakes.txt> --ledger <results.jsonl>
       [--full <page.html>] [--digest <digest.html>] [--date YYYY-MM-DD]
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape
from typing import Any

FULL_MAX = 2_000_000
DIGEST_MAX = 40_000
TREND_DAYS = 14
HISTORY_DAYS = 7
SLOWEST = 10
ISSUE_REPOS = {"": "support", "server": "server"}
FOOTER = (
    "Reply <code>investigate &lt;test&gt;</code> to start a session on a red, "
    "<code>known &lt;test&gt;</code> to list it as a known red."
)
# failure order: new reds first, known last
STATUS_ORDER = {"new": 0, "still red": 1, "known": 2}
STATUS_TONE = {"new": "bad", "still red": "warn", "known": "info"}
# fallbacks for hosts that do not define the status variables
TREND_COLOR = {"pass": "var(--success, #15803d)", "fail": "var(--destructive, #dc2626)", "skip": "var(--muted-foreground, #71717a)"}
# a ledger line, a known_red entry, a flake or the state file
Record = dict[str, Any]
# (ref, group, node id): one test across runs
Key = tuple[str, str, str]
DIGEST_FAILURES = 40
# account set name without its "-a" suffix to its tier 2 group, as lab/labctl/areas.py account_set_area
SET_GROUPS = {
    "spotify": "music_spotify",
    "apple": "music_apple_music",
    "tidal": "music_tidal",
    "ytm": "music_ytmusic",
    "qobuz": "music_qobuz",
    "deezer": "music_deezer",
}
OUTCOME_LABEL = {"pass": "passed", "fail": "failed", "skip": "skipped"}

CSS = """
:root { color-scheme: light dark; }
/* Standalone theme for the side panel tab, which gets no T3 theme variables. */
:root {
  --background: #ffffff; --foreground: #18181b; --muted: #f4f4f5; --muted-foreground: #71717a; --border: #e4e4e7;
  --info: #2563eb; --destructive: #dc2626; --warning: #b45309; --success: #15803d; --radius: 8px;
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --background: #0f0f11; --foreground: #f4f4f5; --muted: #27272a; --muted-foreground: #a1a1aa; --border: #2e2e33;
    --info: #60a5fa; --destructive: #f87171; --warning: #fbbf24; --success: #4ade80;
  }
}
* { box-sizing: border-box; }
html { background: var(--background); }
body { font-family: var(--font-sans); color: var(--foreground); margin: 0; padding: 16px; font-size: 14px; line-height: 1.5; }
a { color: inherit; text-decoration-color: var(--muted-foreground); text-underline-offset: 2px; }
code, .mono { font-family: var(--font-mono); font-size: .9em; overflow-wrap: anywhere; }
.wrap { display: flex; flex-direction: column; gap: 22px; padding: 4px 0 12px; }
h1 { font-size: 18px; font-weight: 600; margin: 0; }
h2 { font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted-foreground); margin: 0 0 8px; font-weight: 600; }
.sub { color: var(--muted-foreground); margin: 2px 0 0; font-size: 13px; }
.sub code { color: var(--foreground); }
.runs { display: flex; flex-direction: column; gap: 2px; margin-top: 6px; font-size: 13px; color: var(--muted-foreground); }
.runs b { color: var(--foreground); font-weight: 500; }
.top { display: flex; flex-wrap: wrap; gap: 8px; align-items: stretch; }
.tile { border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 12px; min-width: 110px; }
.tile .k { font-size: 11.5px; color: var(--muted-foreground); }
.tile .v { font-size: 22px; font-weight: 600; line-height: 1.25; }
.tile .s { font-size: 11.5px; color: var(--muted-foreground); min-height: 1.4em; }
.tile .v .dot { margin-right: 6px; vertical-align: middle; }
.trend { border: 1px solid var(--border); border-radius: var(--radius); padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; }
.trend .k { font-size: 11.5px; color: var(--muted-foreground); }
.trend svg { display: block; }
.trend svg g:hover rect.hit { fill: var(--muted); }
.legend { display: flex; gap: 10px; font-size: 11px; color: var(--muted-foreground); }
.legend span { display: inline-flex; gap: 4px; align-items: center; }
.sw { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.tools { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; position: sticky; top: 0; background: var(--background); padding: 6px 0; z-index: 1; }
.tools input[type=search] { flex: 1 1 240px; min-width: 0; padding: 6px 10px; border: 1px solid var(--border); border-radius: var(--radius); background: transparent; color: var(--foreground); font: inherit; }
.tools label { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; color: var(--muted-foreground); }
.b { --t: var(--muted-foreground); font: 500 10px var(--font-mono); padding: 0 5px; border-radius: 3px; text-transform: uppercase; letter-spacing: .03em; line-height: 1.7; color: var(--t); background: color-mix(in srgb, var(--t) 14%, transparent); white-space: nowrap; }
.ok { --t: var(--success); } .warn { --t: var(--warning); } .info { --t: var(--info); } .bad { --t: var(--destructive); }
.iss { font: 500 11.5px var(--font-mono); padding: 0 5px; border: 1px solid var(--border); border-radius: 3px; text-decoration: none; white-space: nowrap; }
.iss:hover { background: var(--muted); }
.cards { display: flex; flex-direction: column; gap: 6px; }
.card { border: 1px solid var(--border); border-left: 3px solid var(--c); border-radius: var(--radius); padding: 8px 12px; display: flex; flex-direction: column; gap: 4px; }
.card .l1 { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; }
.card .t { flex: 1 1 320px; font: 500 13px var(--font-mono); overflow-wrap: anywhere; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; font-size: 12.5px; color: var(--muted-foreground); }
.meta code { color: var(--foreground); }
.msg { font: 12.5px var(--font-mono); overflow-wrap: anywhere; }
.knote { font-size: 12.5px; color: var(--muted-foreground); border-left: 2px solid var(--info); padding-left: 8px; max-width: 110ch; }
details.tb > summary { cursor: pointer; font-size: 12.5px; color: var(--muted-foreground); }
pre { font: 11.5px/1.45 var(--font-mono); background: var(--muted); padding: 8px 10px; border-radius: calc(var(--radius) - 2px); overflow-x: auto; margin: 6px 0 0; max-height: 480px; }
.hist { display: inline-flex; gap: 3px; align-items: center; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: none; }
.d-pass { background: var(--success); } .d-fail { background: var(--destructive); } .d-skip { background: var(--muted-foreground); opacity: .55; }
.d-none { border: 1px solid var(--border); }
ul.tight { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 3px; }
.empty { font-size: 13px; color: var(--muted-foreground); }
.areas { border: 1px solid var(--border); border-radius: var(--radius); }
.ahead, details.area > summary { display: grid; grid-template-columns: minmax(150px, 1.2fr) 90px 70px minmax(140px, 2fr) 190px; gap: 10px; align-items: center; padding: 6px 10px; }
.ahead { font-size: 11.5px; letter-spacing: .05em; text-transform: uppercase; color: var(--muted-foreground); font-weight: 600; border-bottom: 1px solid var(--border); }
details.area { border-bottom: 1px solid var(--border); }
details.area:last-child { border-bottom: 0; }
details.area > summary { cursor: pointer; list-style: none; font-size: 13px; }
details.area > summary::-webkit-details-marker { display: none; }
details.area > summary:hover { background: var(--muted); }
details.area[open] > summary { background: var(--muted); }
.red { color: var(--destructive); font-weight: 600; }
.bar { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted-foreground); white-space: nowrap; }
.bar .track { flex: 1; }
.bar i { display: block; height: 8px; background: var(--info); border-radius: 0 4px 4px 0; min-width: 2px; }
.bar .lbl { width: 64px; }
.tests { padding: 4px 10px 8px 26px; display: flex; flex-direction: column; }
.trow { display: grid; grid-template-columns: 12px minmax(200px, 1fr) 70px minmax(100px, 220px) 90px; gap: 10px; align-items: center; font-size: 12.5px; padding: 2px 0; }
.trow .n { font-family: var(--font-mono); overflow-wrap: anywhere; }
.trow .d { font-family: var(--font-mono); text-align: right; color: var(--muted-foreground); font-variant-numeric: tabular-nums; }
.trow .c { color: var(--muted-foreground); overflow-wrap: anywhere; }
.tbl { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius); }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 5px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { font-size: 11.5px; letter-spacing: .05em; text-transform: uppercase; color: var(--muted-foreground); font-weight: 600; }
tr:last-child td { border-bottom: 0; }
td.m { font-family: var(--font-mono); overflow-wrap: anywhere; }
td.r { text-align: right; font-family: var(--font-mono); font-variant-numeric: tabular-nums; white-space: nowrap; }
.note { font-size: 12.5px; color: var(--muted-foreground); border-top: 1px solid var(--border); padding-top: 10px; margin: 0; }
.note code { color: var(--foreground); }
.hide { display: none !important; }
@media (max-width: 760px) {
  .ahead, details.area > summary { grid-template-columns: 1fr 70px 60px; }
  .ahead > :nth-child(n+4), details.area > summary > :nth-child(n+4) { display: none; }
  .trow { grid-template-columns: 12px 1fr 60px; }
  .trow > :nth-child(n+4) { display: none; }
}
"""

DIGEST_CSS = """
:root { color-scheme: light dark; }
body { font-family: var(--font-sans); color: var(--foreground); margin: 0; font-size: 13.5px; line-height: 1.45; }
a { color: inherit; text-underline-offset: 2px; text-decoration-color: var(--muted-foreground); }
code { font-family: var(--font-mono); font-size: .9em; }
.wrap { display: flex; flex-direction: column; gap: 14px; padding: 4px 0 8px; }
h1 { font-size: 15px; font-weight: 600; margin: 0; }
h2 { font-size: 11.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted-foreground); margin: 0 0 6px; font-weight: 600; }
.sub { color: var(--muted-foreground); font-size: 12.5px; }
.sub code { color: var(--foreground); }
.runs { display: flex; flex-direction: column; gap: 1px; margin-top: 4px; font-size: 12.5px; color: var(--muted-foreground); }
.runs b { color: var(--foreground); font-weight: 500; }
.top { display: flex; flex-wrap: wrap; gap: 6px; align-items: stretch; }
.tile { border: 1px solid var(--border); border-radius: var(--radius); padding: 6px 10px; min-width: 92px; }
.tile .k { font-size: 11px; color: var(--muted-foreground); }
.tile .v { font-size: 18px; font-weight: 600; line-height: 1.25; }
.tile .s { font-size: 11px; color: var(--muted-foreground); min-height: 1.4em; }
.tile .v .dot { margin-right: 5px; vertical-align: middle; }
.trend { border: 1px solid var(--border); border-radius: var(--radius); padding: 6px 10px; display: flex; flex-direction: column; gap: 3px; }
.trend .k { font-size: 11px; color: var(--muted-foreground); }
.trend svg { display: block; }
.legend { display: flex; gap: 10px; font-size: 11px; color: var(--muted-foreground); }
.legend span { display: inline-flex; gap: 4px; align-items: center; }
.sw { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.d-pass { background: var(--success, #15803d); } .d-fail { background: var(--destructive, #dc2626); }
.d-skip { background: var(--muted-foreground); opacity: .55; }
.b { --t: var(--muted-foreground); font: 500 10px var(--font-mono); padding: 0 5px; border-radius: 3px; text-transform: uppercase; letter-spacing: .03em; line-height: 1.7; color: var(--t); background: color-mix(in srgb, var(--t) 14%, transparent); white-space: nowrap; }
.warn { --t: var(--warning, #b45309); } .info { --t: var(--info, #2563eb); } .bad { --t: var(--destructive, #dc2626); }
.rows { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--radius); }
.r { padding: 6px 10px; border-bottom: 1px solid var(--border); border-left: 3px solid var(--c); }
.r:last-child { border-bottom: 0; }
.r .l1 { display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: baseline; }
.r .t { flex: 1 1 260px; font: 500 12.5px var(--font-mono); overflow-wrap: anywhere; }
.r .l2 { color: var(--muted-foreground); font-size: 12.5px; margin-top: 1px; overflow-wrap: anywhere; }
.r .l2 code { color: var(--foreground); }
ul { margin: 0; padding-left: 20px; }
.groups { font-size: 12.5px; color: var(--muted-foreground); line-height: 1.6; }
.groups .red { color: var(--destructive, #dc2626); font-weight: 600; }
.foot { font-size: 12px; color: var(--muted-foreground); border-top: 1px solid var(--border); padding-top: 8px; }
.foot code { color: var(--foreground); }
"""

JS = """
(function(){
  const q = document.getElementById("q"), only = document.getElementById("only");
  function filter(){
    const term = q.value.trim().toLowerCase(), fails = only.checked;
    document.querySelectorAll("[data-f]").forEach(el => {
      const hide = (term && !el.dataset.f.includes(term)) || (fails && el.dataset.o !== "fail");
      el.classList.toggle("hide", hide);
    });
    document.querySelectorAll("details.area").forEach(d => {
      const n = d.querySelectorAll(".trow:not(.hide)").length;
      d.classList.toggle("hide", n === 0);
      if (term || fails) d.open = n > 0;
    });
  }
  q.addEventListener("input", filter);
  only.addEventListener("change", filter);
})();
"""


@dataclass(frozen=True)
class Run:
    """One lab run as read from its summary.json."""

    run_id: str
    ref: str
    sha: str
    duration_s: float
    hw: bool
    has_junit: bool = True
    exit_code: int | None = 0


@dataclass(frozen=True)
class Case:
    """One testcase of one run."""

    run_id: str
    ref: str
    sha: str
    group: str
    test: str
    role: str
    outcome: str
    duration_s: float
    checkpoint: str
    issues: str
    message: str
    traceback: str = ""
    metrics: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> Key:
        """Identity of the test across runs."""
        return (self.ref, self.group, self.test)

    def ledger_line(self, date: str) -> dict[str, object]:
        """Return the ledger record of this case."""
        return {
            "date": date,
            "run_id": self.run_id,
            "ref": self.ref,
            "sha": self.sha,
            "group": self.group,
            "test": self.test,
            "role": self.role,
            "outcome": self.outcome,
            "duration_s": self.duration_s,
            "checkpoint": self.checkpoint,
            "issues": self.issues,
            "message": self.message,
        }


@dataclass
class Report:
    """Everything the two pages show."""

    date: str
    state: Record
    runs: list[Run]
    cases: list[Case]
    status: dict[Key, str]
    known: dict[Key, Record]
    fixed: list[Record]
    flakes: list[Record]
    dates: list[str]
    history: dict[Key, dict[str, str]]
    trend: dict[str, Counter[str]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the lab deep run report and digest.")
    parser.add_argument("state")
    parser.add_argument("--runs-dir", required=True, help="directory with <run id>/{junit.xml,summary.json}")
    parser.add_argument("--flakes", required=True, help="saved `lab flakes` output")
    parser.add_argument("--ledger", required=True, help="results ledger (JSONL), appended to")
    parser.add_argument("--full", help="write the complete report here")
    parser.add_argument("--digest", help="write the inline digest here")
    parser.add_argument("--date", help="run date, defaults to the state's last_run")
    args = parser.parse_args()
    if not (args.full or args.digest):
        parser.error("give --full, --digest or both")
    with open(args.state) as f:
        state = json.load(f)
    with open(args.flakes) as f:
        flakes_text = f.read()
    date = args.date or state["last_run"]
    runs, cases = load_runs(state, args.runs_dir)
    added = append_ledger(args.ledger, date, cases)
    print(f"{args.ledger}: {added} lines added")
    report = build_report(date, state, runs, cases, read_ledger(args.ledger), flakes_text)
    if args.full:
        _write(args.full, render_full(report), FULL_MAX)
    if args.digest:
        _write(args.digest, render_digest(report), DIGEST_MAX)


def load_runs(state: Record, runs_dir: str) -> tuple[list[Run], list[Case]]:
    """Read every run listed in the state from the runs directory."""
    runs_by_ref = state.get("runs") or {}
    hw_ids = set(runs_by_ref.get("hw") or [])
    runs: list[Run] = []
    cases: list[Case] = []
    for ref_key in ("dev", "stable", "hw"):
        for run_id in runs_by_ref.get(ref_key) or []:
            base = os.path.join(runs_dir, run_id)
            with open(os.path.join(base, "summary.json")) as f:
                summary = json.load(f)
            junit = os.path.join(base, "junit.xml")
            # pytest writes no JUnit file when the run failed before or at startup
            has_junit = os.path.exists(junit)
            run = Run(
                run_id,
                summary["ref"],
                summary["sha"],
                float(summary.get("duration_s") or 0),
                run_id in hw_ids,
                has_junit,
                summary.get("exit_code"),
            )
            runs.append(run)
            if has_junit:
                with open(junit) as f:
                    cases += parse_junit(f.read(), run)
    return runs, cases


def parse_junit(xml_text: str, run: Run) -> list[Case]:
    """Return the testcases of a JUnit document, one per node id."""
    by_id: dict[str, Case] = {}
    for el in ET.fromstring(xml_text).iter("testcase"):
        case = _case(el, run)
        # a call failure is followed by its teardown error under the same name; keep the first failure
        prev = by_id.get(case.test)
        if prev is None or (case.outcome == "fail" and prev.outcome != "fail"):
            by_id[case.test] = case
    return list(by_id.values())


def node_id(classname: str, name: str) -> str:
    """Return the pytest node id of a JUnit testcase, relative to /src."""
    return f"{classname.replace('.', '/')}.py::{name}"


def append_ledger(path: str, date: str, cases: list[Case]) -> int:
    """Append the cases of runs not yet in the ledger; return the number of lines written."""
    seen = {e["run_id"] for e in read_ledger(path)}
    lines = [json.dumps(c.ledger_line(date)) for c in cases if c.run_id not in seen]
    if lines:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "a") as f:
            f.write("\n".join(lines) + "\n")
    return len(lines)


def read_ledger(path: str) -> list[Record]:
    """Return the ledger's records; a missing file has none."""
    try:
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


def known_entry(test: str, group: str, known_red: list[Record]) -> Record | None:
    """Return the known_red entry that names this node id in this group, if any."""
    for entry in known_red:
        for part, only_group in _known_parts(entry.get("test") or ""):
            if part and part in test and only_group in (None, group):
                return entry
    return None


def classify(
    cases: list[Case], ledger: list[Record], date: str, known_red: list[Record]
) -> tuple[dict[Key, str], dict[Key, Record], list[Record]]:
    """Return the status of every failed case, the known entries they match and the tests fixed since the previous date."""
    previous = _previous_fails(ledger, date)
    status: dict[Key, str] = {}
    known: dict[Key, Record] = {}
    for c in cases:
        if c.outcome != "fail":
            continue
        entry = known_entry(c.test, c.group, known_red)
        if entry is not None:
            status[c.key], known[c.key] = "known", entry
        else:
            status[c.key] = "still red" if c.key in previous else "new"
    passed = {c.key for c in cases if c.outcome == "pass"}
    fixed = [previous[k] for k in previous if k in passed]
    return status, known, fixed


def parse_flakes(text: str, last_flakes: list[str]) -> list[Record]:
    """Parse `lab flakes` output; a check missing from last_flakes is new, a higher rerun count is noted."""
    last = {f["check"]: f for f in (_flake(line) for line in last_flakes) if f}
    out = []
    for line in text.splitlines():
        f = _flake(line)
        if not f:
            continue
        prev = last.get(f["check"])
        f["new"] = prev is None
        f["more"] = f["reruns"] - prev["reruns"] if prev and f["reruns"] > prev["reruns"] else 0
        out.append(f)
    return out


def build_report(date: str, state: Record, runs: list[Run], cases: list[Case], ledger: list[Record], flakes_text: str) -> Report:
    """Combine today's cases with the ledger history into a report."""
    status, known, fixed = classify(cases, ledger, date, state.get("known_red") or [])
    dates = sorted({e["date"] for e in ledger if e["date"] <= date})
    history: dict[Key, dict[str, str]] = defaultdict(dict)
    trend: dict[str, Counter[str]] = defaultdict(Counter)
    rank = {"fail": 2, "pass": 1, "skip": 0}
    for e in ledger:
        if e["date"] > date:
            continue
        trend[e["date"]][e["outcome"]] += 1
        h = history[(e["ref"], e["group"], e["test"])]
        if rank[e["outcome"]] >= rank.get(h.get(e["date"], ""), -1):
            h[e["date"]] = e["outcome"]
    flakes = parse_flakes(flakes_text, state.get("last_flakes") or [])
    return Report(date, state, runs, cases, status, known, fixed, flakes, dates, history, trend)


def render_full(r: Report) -> str:
    """Render the complete report page."""
    parts = [
        _header(r, full=True),
        f'<div class="top">{_tiles(r)}{_trend(r, 22)}</div>',
        '<div class="tools"><input id="q" type="search" placeholder="Filter by test, group, checkpoint or issue" '
        'aria-label="Filter tests"><label><input type="checkbox" id="only"> Only failures</label></div>',
        _failures_full(r),
        _fixed(r, full=True),
        _areas(r),
        _flakes(r, only_new=False),
        _slowest(r),
        f'<p class="note">{FOOTER}</p>',
    ]
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Lab deep run</title><base target="_blank"><style>'
        + CSS
        + '</style></head><body><div class="wrap">'
        + "".join(p for p in parts if p)
        + "</div><script>"
        + JS
        + "</script></body></html>"
    )


def render_digest(r: Report) -> str:
    """Render the compact inline digest."""
    parts = [_header(r, full=False), f'<div class="top">{_tiles(r)}{_trend(r, 16)}</div>', _group_line(r)]
    broken = any(not run.has_junit or run.exit_code != 0 for run in r.runs)
    if broken or any(c.outcome == "fail" for c in r.cases) or r.fixed or any(f["new"] or f["more"] for f in r.flakes):
        parts += [_failures_digest(r), _fixed(r, full=False), _flakes(r, only_new=True)]
    parts.append(f'<div class="foot">{FOOTER}</div>')
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Lab deep run</title><base target="_blank"><style>'
        + DIGEST_CSS
        + '</style></head><body><div class="wrap">'
        + "".join(p for p in parts if p)
        + "</div></body></html>"
    )


def _write(path: str, html: str, limit: int) -> None:
    """Write a page after checking it against its size limit."""
    if len(html) > limit:
        sys.exit(f"{path}: {len(html)} characters, over the {limit} limit")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        f.write(html)
    print(f"{path}: {len(html)} characters")


def _case(el: ET.Element, run: Run) -> Case:
    """Build a Case from a JUnit testcase element."""
    name = el.get("name", "")
    props = [(p.get("name", ""), p.get("value", "")) for p in el.iter("property")]
    last = dict(props)
    area = last.get("area")
    if run.hw:
        group = "hw"
    elif area and area.startswith("music_"):
        group = area
    else:
        group = f"tier1:{area or '-'}"
    role = last.get("device") or (name[name.index("[") + 1 : -1] if name.endswith("]") and "[" in name else "-")
    bad = el.find("failure")
    if bad is None:
        bad = el.find("error")
    skipped = el.find("skipped")
    if bad is not None:
        outcome, detail = "fail", bad
    elif skipped is not None:
        outcome, detail = "skip", skipped
    else:
        outcome, detail = "pass", None
    message, traceback = "", ""
    if detail is not None:
        traceback = detail.text or ""
        message = _first_line(detail.get("message") or traceback)
    metrics = {k: v for k, v in props if k not in ("area", "device", "checkpoint", "issues", "failed_checkpoint", "failed_issues", "started_at", "ended_at") and _is_number(v)}
    return Case(
        run_id=run.run_id,
        ref=run.ref,
        sha=run.sha,
        group=group,
        test=node_id(el.get("classname", ""), name),
        role=role,
        outcome=outcome,
        duration_s=round(float(el.get("time") or 0), 3),
        checkpoint=last["failed_checkpoint"] if "failed_checkpoint" in last else last.get("checkpoint", ""),
        issues=last["failed_issues"] if "failed_issues" in last else last.get("issues", ""),
        message=message,
        traceback=traceback,
        metrics=metrics,
    )


def _known_parts(text: str) -> list[tuple[str, str | None]]:
    """Split a known_red test field into node id fragments and the tier 2 group an "on <set>" suffix limits it to."""
    parts: list[tuple[str, str | None]] = []
    for part in text.split(" and "):
        part = re.sub(r"\s*\([^)]*\)\s*$", "", part).strip()
        m = re.match(r"^(\S+)(?:\s+on\s+(\S+))?", part)
        if not m:
            continue
        name = m[2].rsplit("-", 1)[0] if m[2] else None
        only_group = SET_GROUPS.get(name, f"music_{name}") if name else None
        parts.append((m[1], only_group))
    return parts


def _previous_fails(ledger: list[Record], date: str) -> dict[Key, Record]:
    """Return the failed records of each group's latest date before `date`, by test key."""
    # per group: the bench skips weekends and a tier 2 set can miss a day
    prev_date: dict[tuple[str, str], str] = {}
    for e in ledger:
        g = (e["ref"], e["group"])
        if e["date"] < date and e["date"] > prev_date.get(g, ""):
            prev_date[g] = e["date"]
    return {
        (e["ref"], e["group"], e["test"]): e
        for e in ledger
        if e["outcome"] == "fail" and prev_date.get((e["ref"], e["group"])) == e["date"]
    }


def _flake(line: str) -> Record | None:
    """Parse one flakes line in either the `lab flakes` or the state form."""
    m = re.match(r"^\s*(\S+)\s+reruns (\d+)\s+passed[ -]on[ -]rerun (\d+)\s+roles (\S+)\s*$", line)
    if not m:
        return None
    return {"check": m[1], "reruns": int(m[2]), "passed": int(m[3]), "roles": m[4]}


def _first_line(text: str) -> str:
    """Return the first non-empty line."""
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _is_number(value: str) -> bool:
    """Whether a property value is a plain number."""
    try:
        float(value)
    except ValueError:
        return False
    return True


def _fmt_s(seconds: float) -> str:
    """Format a duration for humans."""
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes = round(seconds / 60)
    return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"


def _issues(issues: str) -> str:
    """Render issue ids as links to their repository."""
    out = []
    for token in issues.split():
        m = re.fullmatch(r"(server)?#(\d+)", token)
        if m:
            repo = ISSUE_REPOS[m[1] or ""]
            out.append(f'<a class="iss" href="https://github.com/music-assistant/{repo}/issues/{m[2]}">{escape(token)}</a>')
        else:
            out.append(f"<code>{escape(token)}</code>")
    return " ".join(out)


def _badge(tone: str, text: str, title: str = "") -> str:
    """Render one badge."""
    tip = f' title="{escape(title)}"' if title else ""
    return f'<span class="b {tone}"{tip}>{escape(text)}</span>'


def _filter_attrs(c: Case) -> str:
    """Data attributes the filter box and the failures toggle read."""
    text = " ".join((c.test, c.group, c.checkpoint, c.issues)).lower()
    return f'data-f="{escape(text)}" data-o="{c.outcome}"'


def _label(c: Case | Record) -> str:
    """Group label, prefixed with the ref when it is not dev."""
    ref, group = (c.ref, c.group) if isinstance(c, Case) else (c["ref"], c["group"])
    return group if ref == "dev" else f"{ref} {group}"


def _kind(run: Run, cases: list[Case]) -> str:
    """Return tier 1, tier 2 or hw for a run."""
    if run.hw:
        return "hw"
    groups = {c.group for c in cases if c.run_id == run.run_id}
    return "tier 2" if groups and all(g.startswith("music_") for g in groups) else "tier 1"


def _header(r: Report, full: bool) -> str:
    """Render the title, the runs per tier and the bench line."""
    total = _wall_clock(r.runs)
    lines = []
    seen: dict[tuple[str, str], list[Run]] = {}
    for run in r.runs:
        kind = _kind(run, r.cases)
        if kind != "hw":
            seen.setdefault((run.ref, kind), []).append(run)
    for (ref, kind), runs in seen.items():
        shas = ", ".join(dict.fromkeys(run.sha[:12] for run in runs))
        ids = ", ".join(escape(run.run_id) + ("" if run.has_junit else " (no junit)") for run in runs)
        if full:
            lines.append(f"<span><b>{kind}</b> {escape(ref)} <code>{escape(shas)}</code> · {ids}</span>")
        else:
            missing = sum(not run.has_junit for run in runs)
            note = f" ({missing} without junit)" if missing else ""
            lines.append(f"<span><b>{kind}</b> {escape(ref)} <code>{escape(shas)}</code> · {len(runs)} run{'s' if len(runs) != 1 else ''}{note}</span>")
    lines.append(f"<span>{_hw_line(r)}</span>")
    head = f'<h1>Lab deep run</h1><div class="sub">{escape(r.date)} · total {_fmt_s(total)}</div>'
    return f'<header>{head}<div class="runs">{"".join(lines)}</div></header>'


def _wall_clock(runs: list[Run]) -> float:
    """Seconds from the first run's start to the last run's end; a run id starts with its UTC start time."""
    if not runs:
        return 0.0
    starts = [datetime.strptime(run.run_id[:15], "%Y%m%d-%H%M%S") for run in runs]
    end = max(start + timedelta(seconds=run.duration_s) for start, run in zip(starts, runs))
    return (end - min(starts)).total_seconds()


def _hw_line(r: Report) -> str:
    """Render the bench line."""
    if r.state.get("hw_skipped"):
        return f"<b>hw</b> skipped ({escape(r.state['hw_skipped'])})"
    hw = [run for run in r.runs if run.hw]
    if hw:
        n = Counter(c.outcome for c in r.cases if c.group == "hw")
        ids = ", ".join(escape(run.run_id) for run in hw)
        sha = escape(hw[0].sha[:12])
        return f"<b>hw</b> run {ids} at <code>{sha}</code>, {n['pass']}/{n['pass'] + n['fail']} passed"
    return "<b>hw</b> not run"


def _tiles(r: Report) -> str:
    """Render the passed, failed, skipped and pass rate tiles."""
    n = Counter(c.outcome for c in r.cases)
    known = sum(1 for s in r.status.values() if s == "known")
    ran = n["pass"] + n["fail"]
    rate = f"{100 * n['pass'] / ran:.1f}%" if ran else "-"
    tiles = [
        ("Passed", f'<span class="dot d-pass"></span>{n["pass"]}', ""),
        ("Failed", f'<span class="dot d-fail"></span>{n["fail"]}', f"{known} known" if n["fail"] else ""),
        ("Skipped", f'<span class="dot d-skip"></span>{n["skip"]}', ""),
        ("Pass rate", rate, f"{n['pass']} of {ran}"),
    ]
    return "".join(f'<div class="tile"><div class="k">{k}</div><div class="v">{v}</div><div class="s">{s}</div></div>' for k, v, s in tiles)


def _trend(r: Report, height: int) -> str:
    """Render the per-date stacked pass/fail/skip columns, today rightmost."""
    window = _window(r, TREND_DAYS)
    dates = [d for d in window if d]
    col, gap, h = 14, 6, height * 2
    width = TREND_DAYS * (col + gap) - gap
    top = max((sum(r.trend[d].values()) for d in dates), default=0) or 1
    bars = [f'<line x1="0" x2="{width}" y1="{h + 0.5}" y2="{h + 0.5}" stroke="var(--border)" stroke-width="1"/>']
    for i, d in enumerate(window):
        if not d:
            continue
        x = i * (col + gap)
        counts = r.trend[d]
        tip = f"{d}: {counts['pass']} passed, {counts['fail']} failed, {counts['skip']} skipped"
        segs = [(k, counts[k]) for k in ("fail", "pass", "skip") if counts[k]]
        heights = _segment_heights([v for _, v in segs], top, h)
        y = float(h)
        marks = []
        for j, ((k, _), seg) in enumerate(zip(segs, heights)):
            # 2px surface gap between stacked segments
            body = max(seg - (2 if j else 0), 1)
            y -= seg
            color = TREND_COLOR[k]
            opacity = ' opacity=".5"' if k == "skip" else ""
            if j == len(segs) - 1:
                marks.append(f'<path d="{_top_rounded(x, y, col, body, 3)}" fill="{color}"{opacity}/>')
            else:
                marks.append(f'<rect x="{x}" y="{y:.1f}" width="{col}" height="{body:.1f}" fill="{color}"{opacity}/>')
        bars.append(
            f'<g><title>{escape(tip)}</title><rect class="hit" x="{x - gap / 2}" y="0" width="{col + gap}" height="{h}" '
            f'fill="transparent" rx="3"/>{"".join(marks)}</g>'
        )
    first = window.index(dates[0]) if dates else 0
    label = (
        f'<text x="{first * (col + gap)}" y="{h + 12}" font-size="10" fill="var(--muted-foreground)">{escape(dates[0][5:])}</text>'
        if first <= TREND_DAYS - 4
        else ""
    )
    label += f'<text x="{width}" y="{h + 12}" font-size="10" text-anchor="end" fill="var(--muted-foreground)">{escape(r.date[5:])}</text>'
    svg = f'<svg width="{width}" height="{h + 14}" viewBox="0 0 {width} {h + 14}" role="img" aria-label="Results per day, last {TREND_DAYS} days">{"".join(bars)}{label}</svg>'
    legend = (
        f'<div class="legend"><span><i class="sw" style="background:{TREND_COLOR["pass"]}"></i>passed</span>'
        f'<span><i class="sw" style="background:{TREND_COLOR["fail"]}"></i>failed</span>'
        f'<span><i class="sw" style="background:{TREND_COLOR["skip"]};opacity:.5"></i>skipped</span></div>'
    )
    return f'<div class="trend"><div class="k">Last {TREND_DAYS} days</div>{svg}{legend}</div>'


def _segment_heights(values: list[int], top: int, h: int) -> list[float]:
    """Segment heights with a 1.5 px floor, the floor's overflow taken off the largest segment."""
    raw = [v / top * h for v in values]
    heights = [max(x, 1.5) for x in raw]
    if heights:
        big = heights.index(max(heights))
        heights[big] -= sum(heights) - sum(raw)
    return heights


def _top_rounded(x: float, y: float, w: float, h: float, rad: float) -> str:
    """SVG path of a rectangle with rounded top corners and a square base."""
    rad = min(rad, h, w / 2)
    return (
        f"M{x},{y + h:.1f} V{y + rad:.1f} Q{x},{y:.1f} {x + rad},{y:.1f} H{x + w - rad} "
        f"Q{x + w},{y:.1f} {x + w},{y + rad:.1f} V{y + h:.1f} Z"
    )


def _history(r: Report, key: Key) -> str:
    """Render one dot per day of the last week, oldest first; days without a run are blank."""
    h = r.history.get(key, {})
    dots = []
    for d in _window(r, HISTORY_DAYS):
        if not d:
            dots.append('<span class="dot"></span>')
            continue
        o = h.get(d)
        tip = f"{d}: {OUTCOME_LABEL.get(o, 'not run') if o else 'not run'}"
        dots.append(f'<span class="dot d-{o or "none"}" title="{escape(tip)}"></span>')
    return f'<span class="hist" aria-label="history">{"".join(dots)}</span>'


def _window(r: Report, days: int) -> list[str | None]:
    """The `days` calendar days up to the report date, oldest first; None where the ledger has no runs."""
    end = datetime.fromisoformat(r.date).date()
    known = set(r.dates)
    out: list[str | None] = []
    for back in range(days - 1, -1, -1):
        d = (end - timedelta(days=back)).isoformat()
        out.append(d if d in known else None)
    return out


def _failed(r: Report) -> list[Case]:
    """Failed cases, new reds first, then still red, then known."""
    fails = [c for c in r.cases if c.outcome == "fail"]
    return sorted(fails, key=lambda c: STATUS_ORDER[r.status[c.key]])


def _status_badge(r: Report, c: Case) -> str:
    """Render the new, still red or known badge."""
    s = r.status[c.key]
    note = (r.known.get(c.key) or {}).get("note", "")
    return _badge(STATUS_TONE[s], s, note)


def _failures_full(r: Report) -> str:
    """Render every failure with its traceback and history."""
    fails = _failed(r)
    if not fails:
        return '<section><h2>Failures</h2><div class="empty">No failures.</div></section>'
    cards = []
    for c in fails:
        s = r.status[c.key]
        entry = r.known.get(c.key)
        color = {"new": "--destructive", "still red": "--warning", "known": "--info"}[s]
        metrics = " ".join(f"<code>{escape(k)}={escape(v)}</code>" for k, v in c.metrics.items())
        knote = f'<div class="knote">Known since {escape(entry.get("since", "?"))}: {escape(entry.get("note", ""))}</div>' if entry else ""
        tb = f'<details class="tb"><summary>Traceback</summary><pre>{escape(c.traceback)}</pre></details>' if c.traceback else ""
        cards.append(
            f'<div class="card" style="--c:var({color})" {_filter_attrs(c)}>'
            f'<div class="l1"><span class="t">{escape(c.test)}</span>{_status_badge(r, c)}{_history(r, c.key)}</div>'
            f'<div class="meta"><span>{escape(_label(c))}</span><span>checkpoint <code>{escape(c.checkpoint or "-")}</code></span>'
            f"<span>{_issues(c.issues)}</span><span>{_fmt_s(c.duration_s)}</span><span>run {escape(c.run_id)}</span></div>"
            f'<div class="msg">{escape(c.message)}</div>{knote}'
            + (f'<div class="meta">{metrics}</div>' if metrics else "")
            + f"{tb}</div>"
        )
    counts = Counter(r.status[c.key] for c in fails)
    summary = ", ".join(f"{counts[s]} {s}" for s in STATUS_ORDER if counts[s])
    return f'<section><h2>Failures ({len(fails)}: {summary})</h2><div class="cards">{"".join(cards)}</div></section>'


def _failures_digest(r: Report) -> str:
    """Render the failures as compact rows without tracebacks."""
    fails = _failed(r)
    if not fails:
        return ""
    rows = []
    for c in fails[:DIGEST_FAILURES]:
        s = r.status[c.key]
        color = {"new": "--destructive", "still red": "--warning", "known": "--info"}[s]
        rows.append(
            f'<div class="r" style="--c:var({color})"><div class="l1"><span class="t">{escape(c.test)}</span>{_status_badge(r, c)}</div>'
            f'<div class="l2">{escape(_label(c))} · checkpoint <code>{escape(c.checkpoint or "-")}</code> · {_issues(c.issues)}</div>'
            f'<div class="l2">{escape(c.message if len(c.message) <= 240 else c.message[:240].rstrip() + "…")}</div></div>'
        )
    if len(fails) > DIGEST_FAILURES:
        more = len(fails) - DIGEST_FAILURES
        rows.append(f'<div class="r" style="--c:var(--border)"><div class="l2">and {more} more, see the side panel</div></div>')
    return f'<section><h2>Failures ({len(fails)})</h2><div class="rows">{"".join(rows)}</div></section>'


def _fixed(r: Report, full: bool) -> str:
    """Render the tests that failed on the previous date and pass now."""
    if not r.fixed:
        return ""
    items = []
    for e in r.fixed:
        attrs = f' data-f="{escape(" ".join((e["test"], e["group"], e["checkpoint"], e["issues"])).lower())}" data-o="pass"' if full else ""
        items.append(
            f'<li{attrs}><code>{escape(e["test"])}</code> <span class="sub">{escape(_label(e))}, was red at '
            f'<code>{escape(e["checkpoint"] or "-")}</code> on {escape(e["date"])}</span></li>'
        )
    return f'<section><h2>Fixed since previous run ({len(r.fixed)})</h2><ul class="tight">{"".join(items)}</ul></section>'


def _groups(r: Report) -> dict[str, list[Case]]:
    """Today's cases by group label, in run order."""
    groups: dict[str, list[Case]] = {}
    for c in r.cases:
        groups.setdefault(_label(c), []).append(c)
    return groups


def _group_line(r: Report) -> str:
    """Render every group's passed/total on one line, red groups first."""
    items = []
    for label, cs in _groups(r).items():
        n = Counter(c.outcome for c in cs)
        text = f"{escape(label)} {n['pass']}/{n['pass'] + n['fail']}"
        items.append((n["fail"] == 0, f'<span class="red">{text}</span>' if n["fail"] else text))
    items.sort(key=lambda item: item[0])
    return f'<div class="groups">{" · ".join(text for _, text in items)}</div>' if items else ""


def _areas(r: Report) -> str:
    """Render one collapsible row per group with its tests."""
    groups = _groups(r)
    if not groups:
        return ""
    longest = max(sum(c.duration_s for c in cs) for cs in groups.values()) or 1
    rows = []
    for label, cs in groups.items():
        n = Counter(c.outcome for c in cs)
        dur = sum(c.duration_s for c in cs)
        ran = n["pass"] + n["fail"]
        passed = f'<span class="red">{n["pass"]}/{ran}</span>' if n["fail"] else f"{n['pass']}/{ran}"
        run_ids = ", ".join(dict.fromkeys(escape(c.run_id) for c in cs))
        tests = "".join(
            f'<div class="trow" {_filter_attrs(c)}><span class="dot d-{c.outcome}" title="{OUTCOME_LABEL[c.outcome]}"></span>'
            f'<span class="n">{escape(c.test)}</span><span class="d">{c.duration_s:.1f} s</span>'
            f'<span class="c">{escape(c.checkpoint or "-")}</span>{_history(r, c.key)}</div>'
            for c in cs
        )
        rows.append(
            f'<details class="area"><summary><span>{escape(label)}</span><span>{passed}</span><span>{n["skip"] or ""}</span>'
            f'<span class="bar"><span class="track"><i style="width:{100 * dur / longest:.1f}%"></i></span><span class="lbl">{_fmt_s(dur)}</span></span>'
            f'<span class="mono">{run_ids}</span></summary><div class="tests">{tests}</div></details>'
        )
    head = '<div class="ahead"><span>Group</span><span>Passed</span><span>Skipped</span><span>Duration</span><span>Run</span></div>'
    return f'<section><h2>Areas</h2><div class="areas">{head}{"".join(rows)}</div></section>'


def _flakes(r: Report, only_new: bool) -> str:
    """Render the gate reruns, or only the new ones."""
    flakes = [f for f in r.flakes if f["new"] or f["more"]] if only_new else r.flakes
    if not flakes:
        return "" if only_new else '<section><h2>Flakes</h2><div class="empty">No gate reruns in the last 30 days.</div></section>'
    if only_new:
        items = "".join(
            f'<li><code>{escape(f["check"])}</code> reruns {f["reruns"]}'
            + (f" (+{f['more']})" if f["more"] else "")
            + f', passed on rerun {f["passed"]}, roles {escape(f["roles"])}</li>'
            for f in flakes
        )
        return f"<section><h2>New flakes</h2><ul>{items}</ul></section>"
    rows = "".join(
        f'<tr><td class="m">{escape(f["check"])} '
        + (_badge("bad", "new") if f["new"] else _badge("warn", f"+{f['more']}") if f["more"] else "")
        + f'</td><td class="r">{f["reruns"]}</td><td class="r">{f["passed"]}</td><td class="m">{escape(f["roles"])}</td></tr>'
        for f in flakes
    )
    return (
        '<section><h2>Flakes (gate reruns, 30 days)</h2><div class="tbl"><table><thead><tr><th>Check</th><th>Reruns</th>'
        f"<th>Passed on rerun</th><th>Roles</th></tr></thead><tbody>{rows}</tbody></table></div></section>"
    )


def _slowest(r: Report) -> str:
    """Render the slowest tests of the day."""
    slow = sorted(r.cases, key=lambda c: -c.duration_s)[:SLOWEST]
    if not slow:
        return ""
    rows = "".join(
        f'<tr {_filter_attrs(c)}><td><span class="dot d-{c.outcome}" title="{OUTCOME_LABEL[c.outcome]}"></span></td>'
        f'<td class="m">{escape(c.test)}</td><td>{escape(_label(c))}</td><td class="r">{c.duration_s:.1f} s</td></tr>'
        for c in slow
    )
    return (
        f'<section><h2>Slowest {SLOWEST} tests</h2><div class="tbl"><table><thead><tr><th></th><th>Test</th><th>Group</th>'
        f'<th style="text-align:right">Duration</th></tr></thead><tbody>{rows}</tbody></table></div></section>'
    )


if __name__ == "__main__":
    main()
