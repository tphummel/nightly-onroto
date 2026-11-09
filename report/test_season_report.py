"""Tests for season_report.py. Run: python3 -m unittest discover -s report"""
import datetime as dt
import json
import os
import tempfile
import unittest

import season_report as sr

CATS = ["HR", "OBP"]
TEAMS = ["Aces", "Bats", "Cubs"]


def snapshot(date, week_totals, season_totals=None):
    season_totals = season_totals or {t: 10 * (3 - i) for i, t in enumerate(TEAMS)}
    return {
        "standingsDate": date,
        "seasonStandings": [
            {"order": i, "Team Name": t, "HR": "1.0", "OBP": "2.0", "TOTAL": str(float(season_totals[t])), "+/-": "0.0"}
            for i, t in enumerate(TEAMS)
        ],
        "weekStandings": [
            {"order": i, "Team": t, "HR": "1.0", "OBP": "2.0", "TOTAL": str(float(week_totals[t]))}
            for i, t in enumerate(TEAMS)
        ],
        "categoryStandings": [],
    }


def write_season(snaps):
    d = tempfile.mkdtemp()
    for date, snap in snaps.items():
        with open(os.path.join(d, f"{date}.json"), "w") as f:
            json.dump(snap, f)
    return d


A_WINS = {"Aces": 5, "Bats": 3, "Cubs": 1}
B_WINS = {"Aces": 1, "Bats": 5, "Cubs": 3}
TIE = {"Aces": 4, "Bats": 4, "Cubs": 1}


class WeeksTest(unittest.TestCase):
    def setUp(self):
        # 2026-03-25 is a Wednesday: opening week is Wed-Sun (5 days).
        # 2026-04-06 (a Monday) snapshot is missing; the week still ends on Sun 04-12.
        self.snaps = {
            "2026-03-25": snapshot("2026-03-25", TIE),
            "2026-03-29": snapshot("2026-03-29", A_WINS),  # last of week 1
            "2026-03-30": snapshot("2026-03-30", TIE),
            "2026-04-05": snapshot("2026-04-05", B_WINS),  # last of week 2
            "2026-04-07": snapshot("2026-04-07", TIE),
            "2026-04-12": snapshot("2026-04-12", TIE),     # last of week 3
        }
        self.dir = write_season(self.snaps)

    def test_weeks_use_last_snapshot_of_each_week(self):
        weeks = sr.build_weeks(sr.load_snapshots(self.dir, "2026"))
        self.assertEqual(len(weeks), 3)
        self.assertEqual([w["standings"][0]["team"] for w in weeks[:2]], ["Aces", "Bats"])
        self.assertEqual(weeks[0]["start"], dt.date(2026, 3, 25))
        self.assertEqual(weeks[0]["end"], dt.date(2026, 3, 29))
        self.assertEqual(weeks[0]["days"], 5)
        self.assertTrue(weeks[0]["partial"])

    def test_missing_monday_does_not_shorten_a_week(self):
        weeks = sr.build_weeks(sr.load_snapshots(self.dir, "2026"))
        w3 = weeks[2]
        self.assertEqual((w3["start"], w3["end"], w3["days"]), (dt.date(2026, 4, 6), dt.date(2026, 4, 12), 7))
        self.assertFalse(w3["partial"])
        self.assertFalse(w3["stale"])

    def test_ties_are_co_winners(self):
        weeks = sr.build_weeks(sr.load_snapshots(self.dir, "2026"))
        self.assertEqual([r["team"] for r in sr.winners(weeks[2]["standings"])], ["Aces", "Bats"])

    def test_missing_sunday_flags_stale(self):
        del self.snaps["2026-04-12"]
        self.snaps["2026-04-10"] = snapshot("2026-04-10", A_WINS)
        self.snaps["2026-04-13"] = snapshot("2026-04-13", TIE)  # a later week, so week 3 is interior
        weeks = sr.build_weeks(sr.load_snapshots(write_season(self.snaps), "2026"))
        self.assertTrue(weeks[2]["stale"])

    def test_other_seasons_are_ignored(self):
        self.snaps["2025-09-28"] = snapshot("2025-09-28", B_WINS)
        snaps = sr.load_snapshots(write_season(self.snaps), "2026")
        self.assertNotIn("2025-09-28", snaps)

    def test_missing_days(self):
        snaps = sr.load_snapshots(self.dir, "2026")
        self.assertIn(dt.date(2026, 4, 6), sr.missing_days(snaps))


def cat_snapshot(date, hr, obp=None):
    """A snapshot carrying year-to-date category detail: HR (counting) and OBP (rate)."""
    snap = snapshot(date, A_WINS)
    obp = obp or {t: ".300" for t in hr}
    snap["categoryStandings"] = [
        {"team": t, "HOME RUNS": {"Year": str(hr[t]), "Wk": "0", "PTS": "1.0", "+/-": "0.0"},
         "ON BASE PCT": {"Year": obp[t], "Wk": ".300", "PTS": "1.0", "+/-": "0.0"}}
        for t in hr
    ]
    return snap


def hr(a, b):
    return {"Aces": a, "Bats": b}


class DailyTest(unittest.TestCase):
    def series(self, days):
        return sr.load_snapshots(write_season({d: cat_snapshot(d, h) for d, h in days.items()}), "2026")

    def test_single_day_is_change_between_consecutive_snapshots(self):
        daily = sr.daily_changes(self.series({
            "2026-04-01": hr(0, 0), "2026-04-02": hr(2, 1), "2026-04-03": hr(5, 2),
        }))
        got = {(r["team"], str(r["date"])): r["value"] for r in daily["entries"]}
        self.assertEqual(got[("Aces", "2026-04-02")], 2)
        self.assertEqual(got[("Aces", "2026-04-03")], 3)
        self.assertNotIn(("Aces", "2026-04-01"), got)  # first snapshot: nothing to difference against

    def test_rate_stats_are_left_out(self):
        daily = sr.daily_changes(self.series({"2026-04-01": hr(0, 0), "2026-04-02": hr(1, 1)}))
        self.assertEqual(daily["labels"], ["HOME RUNS"])

    def test_day_after_missing_snapshot_is_skipped(self):
        daily = sr.daily_changes(self.series({
            "2026-04-01": hr(0, 0), "2026-04-02": hr(2, 1), "2026-04-04": hr(9, 9),  # 04-03 missing
        }))
        self.assertNotIn("2026-04-04", {str(r["date"]) for r in daily["entries"]})

    def test_day_after_a_quiet_day_is_skipped(self):
        daily = sr.daily_changes(self.series({
            "2026-04-01": hr(0, 0), "2026-04-02": hr(2, 1), "2026-04-03": hr(4, 2),
            "2026-04-04": hr(4, 2),    # nobody moved: quiet
            "2026-04-05": hr(12, 5),   # big catch-up day: must not become a "best single day"
            "2026-04-06": hr(14, 6),
        }))
        dates = {str(r["date"]) for r in daily["entries"]}
        self.assertNotIn("2026-04-05", dates)
        self.assertIn("2026-04-06", dates)
        self.assertEqual([str(d) for d in daily["after_quiet"]], ["2026-04-05"])
        shown, more = sr.top_days(daily, "HOME RUNS", 1)
        self.assertEqual((shown[0]["value"], more), (2, 2))  # Aces 04-02 / 04-03... never the 8-HR day

    def test_top_days_ranks_ties_and_counts_the_rest(self):
        daily = sr.daily_changes(self.series({
            "2026-04-01": hr(0, 0), "2026-04-02": hr(3, 3), "2026-04-03": hr(4, 5),
        }))
        shown, more = sr.top_days(daily, "HOME RUNS", 1)
        self.assertEqual((shown[0]["rank"], shown[0]["tied"], more), (1, True, 1))

    def test_page_has_a_section_only_when_category_detail_exists(self):
        with_cats = write_season({
            "2026-03-29": cat_snapshot("2026-03-29", hr(0, 0)),
            "2026-03-30": cat_snapshot("2026-03-30", hr(3, 1)),
        })
        self.assertIn("Best single days", sr.generate("2026", with_cats))
        without = write_season({"2026-03-29": snapshot("2026-03-29", A_WINS)})
        self.assertNotIn("Best single days", sr.generate("2026", without))


class GapTest(unittest.TestCase):
    def setUp(self):
        # weeks of Mar 30 and Apr 6 have no snapshots at all; Apr 13 week has one
        self.d = write_season({
            "2026-03-29": snapshot("2026-03-29", A_WINS),
            "2026-04-19": snapshot("2026-04-19", B_WINS),
        })

    def test_empty_weeks_are_shown_not_skipped(self):
        weeks = sr.build_weeks(sr.load_snapshots(self.d, "2026"))
        self.assertEqual([w["n"] for w in weeks], [1, 2, 3, 4])
        self.assertEqual([w["missing"] for w in weeks], [False, True, True, False])

    def test_page_reports_gap_and_excludes_it_from_tally(self):
        page = sr.generate("2026", self.d)
        self.assertIn("No snapshots for this week", page)
        self.assertIn("Weeks 2–3", page)
        self.assertIn("2 with no data, not scored", page)
        # Aces won week 1 (A_WINS), Bats won week 4 (B_WINS): one week each, nothing else counted
        self.assertEqual(page.count('<td class="n">1</td></tr>'), 2)


class ReportTest(unittest.TestCase):
    def test_overall_and_page(self):
        d = write_season({
            "2026-03-29": snapshot("2026-03-29", A_WINS),
            "2026-04-05": snapshot("2026-04-05", B_WINS),
        })
        ov, cats = sr.overall_standings(sr.load_snapshots(d, "2026")["2026-04-05"])
        self.assertEqual([r["team"] for r in ov], ["Aces", "Bats", "Cubs"])
        self.assertEqual(cats, CATS)
        page = sr.generate("2026", d)
        self.assertIn("2026 OnRoto Season Report", page)
        self.assertIn("3-team, 2-category", page)
        self.assertIn("max 6, 3 pts × 2 categories", page)
        self.assertIn("Aces", page)

    def test_min_days_excludes_stub_weeks(self):
        d = write_season({
            "2026-03-29": snapshot("2026-03-29", A_WINS),  # Sun only: a 1-day opening week
            "2026-04-05": snapshot("2026-04-05", B_WINS),
        })
        self.assertIn("opening week · 1 day", sr.generate("2026", d))
        page = sr.generate("2026", d, min_days=2)
        self.assertNotIn("opening week", page)
        self.assertIn("Excluded as too short", page)

    def test_team_names_are_escaped(self):
        snap = snapshot("2026-03-29", A_WINS)
        snap["seasonStandings"][0]["Team Name"] = "<b>Aces & Co</b>"
        snap["weekStandings"][0]["Team"] = "<b>Aces & Co</b>"
        page = sr.generate("2026", write_season({"2026-03-29": snap}))
        self.assertIn("&lt;b&gt;Aces &amp; Co&lt;/b&gt;", page)
        self.assertNotIn("<b>Aces", page)


if __name__ == "__main__":
    unittest.main()
