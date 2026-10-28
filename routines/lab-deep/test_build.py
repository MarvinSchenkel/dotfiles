from pathlib import Path

import build

RUN = build.Run("20261028-000000-aaaa", "dev", "abc123", 10.0, hw=False)
JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">
<testcase classname="scenarios.deep.test_queue" name="test_now_playing[slim-1]" time="3.5">
  <properties><property name="area" value="queue" /><property name="checkpoint" value="starts" />
  <property name="issues" value="#1" /><property name="checkpoint" value="reports" />
  <property name="issues" value="#2 server#3" /><property name="lag_s" value="4.2" /></properties>
  <failure message="AssertionError: late&#10;more">trace</failure></testcase>
<testcase classname="scenarios.deep.test_queue" name="test_now_playing[slim-1]" time="0.1">
  <error message="teardown failed">teardown</error></testcase>
<testcase classname="scenarios.deep.test_queue" name="test_album[snap-1]" time="1">
  <properties><property name="area" value="queue" /><property name="checkpoint" value="starts" />
  <property name="issues" value="#1" /><property name="checkpoint" value="advances" /><property name="issues" value="#1" />
  <property name="failed_checkpoint" value="starts" /><property name="failed_issues" value="#1" /></properties>
  <failure message="boom">trace</failure></testcase>
<testcase classname="scenarios.tier2.test_album" name="test_ends[sendspin-1]" time="2">
  <properties><property name="area" value="music_spotify" /></properties></testcase>
</testsuite></testsuites>"""
HW_RUN = build.Run("20261028-000000-bbbb", "dev", "abc123", 10.0, hw=True)
HW_JUNIT = """<testsuites><testsuite name="pytest">
<testcase classname="scenarios.hw.test_bench" name="test_wiim[wiim-1]" time="1"><failure message="late">t</failure></testcase>
<testcase classname="scenarios.hw.test_bench" name="test_cast[nestmini-1]" time="1" />
</testsuite></testsuites>"""


def _cases() -> dict[str, build.Case]:
    return {c.test: c for c in build.parse_junit(JUNIT, RUN)}


def test_parse_node_id_and_properties() -> None:
    cases = _cases()
    late = cases["scenarios/deep/test_queue.py::test_now_playing[slim-1]"]
    assert (late.group, late.role, late.outcome) == ("tier1:queue", "slim-1", "fail")
    # no failed_checkpoint: the last checkpoint reached
    # the teardown error that follows the call failure does not replace it
    assert (late.checkpoint, late.issues, late.message) == ("reports", "#2 server#3", "AssertionError: late")
    assert late.metrics == {"lag_s": "4.2"}
    album = cases["scenarios/deep/test_queue.py::test_album[snap-1]"]
    assert album.checkpoint == "starts"
    assert cases["scenarios/tier2/test_album.py::test_ends[sendspin-1]"].group == "music_spotify"


def test_ledger_append_is_idempotent(tmp_path: Path) -> None:
    path = str(tmp_path / "ledger.jsonl")
    cases = list(_cases().values())
    assert build.append_ledger(path, "2026-10-28", cases) == 3
    assert build.append_ledger(path, "2026-10-28", cases) == 0
    assert len(build.read_ledger(path)) == 3


def test_classify_new_still_fixed_known() -> None:
    def rec(test: str, outcome: str, date: str = "2026-10-27", group: str = "tier1:queue") -> build.Record:
        return {"date": date, "ref": "dev", "group": group, "test": test, "outcome": outcome, "checkpoint": "x", "issues": ""}

    today = list(_cases().values()) + build.parse_junit(HW_JUNIT, HW_RUN)
    ledger = [
        rec("scenarios/deep/test_queue.py::test_now_playing[slim-1]", "fail"),
        rec("scenarios/deep/test_queue.py::test_album[snap-1]", "pass"),
        rec("scenarios/deep/test_queue.py::test_gone[slim-1]", "fail"),
        # an older date is not the previous one
        rec("scenarios/deep/test_queue.py::test_album[snap-1]", "fail", "2026-10-20"),
    ]
    ledger.append(rec("scenarios/tier2/test_album.py::test_ends[sendspin-1]", "fail", group="music_spotify"))
    # the bench did not run on the 27th: its previous date is the 26th
    ledger.append(rec("scenarios/hw/test_bench.py::test_wiim[wiim-1]", "fail", "2026-10-26", "hw"))
    ledger.append(rec("scenarios/hw/test_bench.py::test_cast[nestmini-1]", "fail", "2026-10-26", "hw"))
    status, known, fixed = build.classify(today, ledger, "2026-10-28", [])
    assert status[("dev", "tier1:queue", "scenarios/deep/test_queue.py::test_now_playing[slim-1]")] == "still red"
    assert status[("dev", "tier1:queue", "scenarios/deep/test_queue.py::test_album[snap-1]")] == "new"
    assert status[("dev", "hw", "scenarios/hw/test_bench.py::test_wiim[wiim-1]")] == "still red"
    assert sorted(f["test"] for f in fixed) == [
        "scenarios/hw/test_bench.py::test_cast[nestmini-1]",
        "scenarios/tier2/test_album.py::test_ends[sendspin-1]",
    ]
    known_red = [{"test": "scenarios/deep/test_queue.py::test_now_playing[slim-1] (reports)", "note": "n"}]
    status, known, _ = build.classify(today, ledger, "2026-10-28", known_red)
    key = ("dev", "tier1:queue", "scenarios/deep/test_queue.py::test_now_playing[slim-1]")
    assert status[key] == "known" and known[key]["note"] == "n"


def test_known_red_and_form() -> None:
    known_red = [
        {"test": "scenarios/deep/test_players.py::test_member_rejoins[slim-1] and test_member_restart_ungroups[slim-1]"},
        {"test": "scenarios/tier2/test_continuity.py::test_continuity[sendspin-1] on spotify-a"},
        {"test": "scenarios/tier2/test_album.py::test_last_track_ends_clean[sendspin-1] on apple-a"},
    ]
    players = "tier1:players"
    assert build.known_entry("scenarios/deep/test_players.py::test_member_restart_ungroups[slim-1]", players, known_red) is known_red[0]
    assert build.known_entry("scenarios/deep/test_players.py::test_member_rejoins[slim-1]", players, known_red) is known_red[0]
    assert build.known_entry("scenarios/deep/test_players.py::test_member_rejoins[snap-1]", players, known_red) is None
    # "on spotify-a" limits the entry to the music_spotify group
    continuity = "scenarios/tier2/test_continuity.py::test_continuity[sendspin-1]"
    assert build.known_entry(continuity, "music_spotify", known_red) is known_red[1]
    assert build.known_entry(continuity, "music_tidal", known_red) is None
    album = "scenarios/tier2/test_album.py::test_last_track_ends_clean[sendspin-1]"
    assert build.known_entry(album, "music_apple_music", known_red) is known_red[2]
    assert build.known_entry(album, "music_spotify", known_red) is None
