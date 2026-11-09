#!/usr/bin/env python3
"""Generate a single-page HTML season report from nightly-onroto standings.

The report has the final overall standings with a top-3 podium, the winner of
every week (Monday-Sunday, each week scored in isolation), and a weeks-won
tally.

    python3 report/season_report.py 2026 --out report/out/2026.html

Data comes from the daily `YYYY-MM-DD.json` assets attached to this repo's
GitHub releases. They are downloaded into a cache directory the first time a
season is run (and only the missing days after that). Use --data-dir to point
at a folder of already-downloaded files instead.

Weekly results are OnRoto's own weekly roto points, read from the last
snapshot of each Monday-Sunday week, so nothing is estimated. Standard
library only.
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_REPO = "tphummel/nightly-onroto"
SKIP_KEYS = {"order", "Team Name", "TOTAL", "+/-"}
EPS = 1e-9

e = html.escape


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------
def _request(url):
    headers = {"User-Agent": "nightly-onroto-season-report"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def list_tags(repo, season):
    """Release tags for the season (YYYY-MM-DD), newest releases first."""
    pat = re.compile(rf"^{season}-\d\d-\d\d$")
    tags, page = [], 1
    while True:
        url = f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}"
        with urllib.request.urlopen(_request(url), timeout=60) as r:
            batch = json.load(r)
        tags += [x["tag_name"] for x in batch if pat.match(x["tag_name"])]
        if len(batch) < 100:
            return sorted(set(tags))
        page += 1


def download_season(repo, season, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    todo = [t for t in list_tags(repo, season)
            if not os.path.exists(os.path.join(data_dir, f"{t}.json"))]
    if not todo:
        return

    def get(tag):
        url = f"https://github.com/{repo}/releases/download/{tag}/{tag}.json"
        try:
            with urllib.request.urlopen(_request(url), timeout=60) as r:
                body = r.read()
            json.loads(body)  # make sure it is valid before caching it
        except Exception as ex:  # noqa: BLE001 - report and carry on
            print(f"warning: could not fetch {tag}: {ex}", file=sys.stderr)
            return
        with open(os.path.join(data_dir, f"{tag}.json"), "wb") as f:
            f.write(body)

    print(f"downloading {len(todo)} snapshot(s) for {season}...", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(get, todo))


# --------------------------------------------------------------------------
# computing
# --------------------------------------------------------------------------
def load_snapshots(data_dir, season):
    snaps = {}
    for name in sorted(os.listdir(data_dir)):
        m = re.fullmatch(rf"({season}-\d\d-\d\d)\.json", name)
        if not m:
            continue
        with open(os.path.join(data_dir, name)) as f:
            d = json.load(f)
        if not d.get("seasonStandings") or not d.get("weekStandings"):
            print(f"warning: {name} has no standings; skipped", file=sys.stderr)
            continue
        snaps[m.group(1)] = d
    return snaps


def _day(s):
    return dt.date.fromisoformat(s)


def winners(rows):
    top = rows[0]["total"]
    return [r for r in rows if abs(r["total"] - top) < EPS]


def overall_standings(final):
    """Final overall standings plus the ordered list of category columns."""
    cats = [k for k in final["seasonStandings"][0] if k not in SKIP_KEYS]
    rows = [
        {"team": r["Team Name"], "total": float(r["TOTAL"]),
         "cats": {c: float(r[c]) for c in cats}}
        for r in final["seasonStandings"]
    ]
    rows.sort(key=lambda r: -r["total"])  # stable: OnRoto order breaks display ties
    return rows, cats


def build_weeks(snaps):
    """One entry per Monday-Sunday week, scored from its last snapshot.

    A week's result is the weekStandings of the last snapshot taken in that
    week (normally Sunday's). The first and last weeks of a season can be
    shorter than seven days; each still counts as its own week.
    """
    dates = sorted(snaps)
    first, last = _day(dates[0]), _day(dates[-1])
    groups = {}
    for s in dates:
        monday = _day(s) - dt.timedelta(days=_day(s).weekday())
        groups.setdefault(monday, []).append(s)
    weeks = []
    n_weeks = (max(groups) - min(groups)).days // 7 + 1
    for i in range(n_weeks):
        monday = min(groups) + dt.timedelta(days=7 * i)
        start = max(monday, first)
        sunday = monday + dt.timedelta(days=6)
        end = min(sunday, last)
        if monday not in groups:  # a whole week with no snapshots: show the gap, don't hide it
            weeks.append({
                "n": i + 1, "start": start, "end": end, "days": (end - start).days + 1,
                "partial": False, "is_first": False, "is_last": False,
                "snapshot": None, "stale": False, "missing": True, "standings": [],
            })
            continue
        end_snap = groups[monday][-1]
        rows = sorted(
            [{"team": w.get("Team") or w.get("Team Name"), "total": float(w["TOTAL"])}
             for w in snaps[end_snap]["weekStandings"]],
            key=lambda r: -r["total"],
        )
        weeks.append({
            "n": i + 1,
            "start": start, "end": end, "days": (end - start).days + 1,
            "partial": (end - start).days + 1 < 7,
            "is_first": i == 0, "is_last": i == n_weeks - 1,
            "snapshot": _day(end_snap),
            "stale": _day(end_snap) < end,  # Sunday snapshot missing
            "missing": False,
            "standings": rows,
        })
    return weeks


def day_ranges(days):
    """Group sorted dates into (first, last) runs of consecutive days."""
    runs = []
    for d in days:
        if runs and (d - runs[-1][1]).days == 1:
            runs[-1][1] = d
        else:
            runs.append([d, d])
    return [(a, b) for a, b in runs]


def num_runs(nums):
    runs = []
    for n in nums:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    return [str(a) if a == b else f"{a}–{b}" for a, b in runs]


def missing_days(snaps):
    dates = sorted(_day(s) for s in snaps)
    have = set(dates)
    return [d for d in (dates[0] + dt.timedelta(n) for n in range((dates[-1] - dates[0]).days + 1))
            if d not in have]


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
def fmt(x):
    return f"{x:g}" if x == int(x) else f"{x:.1f}"


def md(d, f="%b %-d"):
    return d.strftime(f)


def days_label(n):
    return f"{n} day" + ("" if n == 1 else "s")


def date_range(a, b, f="%b %-d"):
    return md(a, f) if a == b else f"{md(a, f)} – {md(b, f)}"


def human_list(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def names(ws):
    return " &amp; ".join(e(w["team"]) for w in ws)


CSS = """:root{color-scheme:light dark;--bg:#fafaf7;--card:#fff;--text:#1c2230;--muted:#667085;--border:#e3e5ea;--accent:#1f5fbf;--gold:#d4a017;--silver:#9aa4b2;--bronze:#b9733a;--win:#0a7a3d;--warn:#b45309;--tagbg:#eef1f6}
@media(prefers-color-scheme:dark){:root{--bg:#0b1020;--card:#141b2d;--text:#e9edf7;--muted:#a5afc3;--border:#27314b;--accent:#4da3ff;--gold:#f2c230;--silver:#aeb8c6;--bronze:#d98f56;--win:#4ade80;--warn:#fbbf24;--tagbg:#1d2740}}
*{box-sizing:border-box}
body{margin:0;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.45}
main{max-width:880px;margin:0 auto;padding:1.25rem 16px 3rem}
h1{font-size:1.7rem;margin:.2rem 0 .25rem} h2{font-size:1.25rem;margin:2.2rem 0 .6rem;padding-top:.4rem;border-top:1px solid var(--border)}
.meta,.muted{color:var(--muted)} .small{font-size:.85rem}
.podium{display:grid;grid-template-columns:1fr 1.1fr 1fr;gap:.6rem;align-items:end;margin:1.2rem 0}
.pod{text-align:center;display:flex;flex-direction:column;align-items:center}
.medal{font-size:1.8rem} .pname{font-weight:700;margin:.15rem 0;overflow-wrap:anywhere} .ppts{color:var(--muted);font-variant-numeric:tabular-nums;margin-bottom:.35rem}
.bar{width:100%;border-radius:.5rem .5rem 0 0;display:flex;align-items:flex-start;justify-content:center;font-size:1.6rem;font-weight:800;padding-top:.3rem;color:#fff}
.p1 .bar{height:130px} .p2 .bar{height:96px} .p3 .bar{height:70px}
.r1 .bar{background:var(--gold)} .r2 .bar{background:var(--silver)} .r3 .bar{background:var(--bronze)}
.p1 .pname{font-size:1.15rem}
.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--border);border-radius:.6rem}
table{border-collapse:collapse;width:100%;font-size:.92rem} th,td{padding:.45rem .6rem;text-align:left;white-space:nowrap}
thead th{font-size:.78rem;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);border-bottom:1px solid var(--border)}
tbody tr+tr td{border-top:1px solid var(--border)}
.n{text-align:right;font-variant-numeric:tabular-nums} .tot{font-weight:700} .t{font-weight:600} .win{color:var(--win)}
.narrow{max-width:420px}
.tag{font-size:.7rem;font-weight:600;background:var(--tagbg);color:var(--muted);border-radius:.8rem;padding:.05rem .45rem;margin-left:.25rem;white-space:nowrap} .tag.warn{color:var(--warn)}
ul{padding-left:1.2rem} li{margin:.3rem 0}
@media(max-width:560px){.hide-s{display:none} td.t,td.win{white-space:normal} th,td{padding:.4rem .4rem;font-size:.85rem} .p1 .bar{height:100px} .p2 .bar{height:76px} .p3 .bar{height:56px} h1{font-size:1.4rem}}"""


def rank_of(rows, r):
    return 1 + sum(1 for x in rows if x["total"] > r["total"] + EPS)


def render_podium(ov):
    """Podium of the top three places; medals and colors follow rank, so tied teams share one."""
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    slots = [(1, "p2"), (0, "p1"), (2, "p3")]
    out = ""
    for i, cls in slots:
        if i >= len(ov):
            continue
        r = ov[i]
        rk = min(rank_of(ov, r), 3)
        cls += f" r{rk}"
        medal = medals[rk]
        tied = sum(1 for x in ov if abs(x["total"] - r["total"]) < EPS) > 1
        out += (f'<div class="pod {cls}"><div class="medal">{medal}</div>'
                f'<div class="pname">{e(r["team"])}</div><div class="ppts">{fmt(r["total"])}</div>'
                f'<div class="bar"><span>{"T-" if tied else ""}{rank_of(ov, r)}</span></div></div>')
    return out


def podium_note(ov):
    if len(ov) <= 3:
        return ""
    off = [x["team"] for x in ov[3:] if abs(x["total"] - ov[2]["total"]) < EPS]
    if not off:
        return ""
    return (f'<p class="muted small">Also tied for {rank_of(ov, ov[2])}{"rd" if rank_of(ov, ov[2]) == 3 else "th"}: '
            + human_list([e(t) for t in off]) + ".</p>")


def render_overall(ov, cats):
    rows = ""
    for r in ov:
        tie = "T-" if sum(1 for x in ov if abs(x["total"] - r["total"]) < EPS) > 1 else ""
        rows += (f'<tr><td class="n">{tie}{rank_of(ov, r)}</td><td class="t">{e(r["team"])}</td>'
                 + "".join(f'<td class="n">{fmt(r["cats"][k])}</td>' for k in cats)
                 + f'<td class="n tot">{fmt(r["total"])}</td></tr>')
    head = "".join(f'<th class="n">{e(k)}</th>' for k in cats)
    return (f'<div class="scroll"><table><thead><tr><th>#</th><th>Team</th>{head}'
            f'<th class="n">Total</th></tr></thead><tbody>{rows}</tbody></table></div>')


def render_weeks(weeks):
    rows, wins, tie_weeks = "", {}, []
    for w in weeks:
        if w["missing"]:
            rows += (f'<tr><td class="n">{w["n"]}</td><td>{date_range(w["start"], w["end"])}</td>'
                     '<td class="muted" colspan="3">No snapshots for this week</td></tr>')
            continue
        ws = winners(w["standings"])
        for x in ws:
            wins[x["team"]] = wins.get(x["team"], 0) + 1
        if len(ws) > 1:
            tie_weeks.append(w["n"])
        ru = [r for r in w["standings"] if r not in ws][:1]
        dtags, tags = "", ""
        if w["partial"] and w["is_first"]:
            dtags = f' <span class="tag">opening week · {days_label(w["days"])}</span>'
        elif w["partial"] and w["is_last"]:
            dtags = f' <span class="tag">final week · {days_label(w["days"])}</span>'
        if w["stale"]:
            tags += f' <span class="tag warn">as of {md(w["snapshot"])}</span>'
        if len(ws) > 1:
            tags += ' <span class="tag">tie</span>'
        ru_html = f'{e(ru[0]["team"])} <span class="muted">{fmt(ru[0]["total"])}</span>' if ru else ""
        rows += (f'<tr><td class="n">{w["n"]}</td><td>{date_range(w["start"], w["end"])}{dtags}</td>'
                 f'<td class="t win">{names(ws)}{tags}</td><td class="n tot">{fmt(ws[0]["total"])}</td>'
                 f'<td class="hide-s">{ru_html}</td></tr>')
    table = ('<div class="scroll"><table><thead><tr><th class="n">Wk</th><th>Dates (Mon–Sun)</th>'
             '<th>Winner</th><th class="n">Pts</th><th class="hide-s">Runner-up</th></tr></thead>'
             f'<tbody>{rows}</tbody></table></div>')
    return table, wins, tie_weeks


def render_tally(ov, wins, tie_weeks):
    rows = "".join(f'<tr><td class="t">{e(r["team"])}</td><td class="n">{wins.get(r["team"], 0)}</td></tr>'
                   for r in ov)
    note = "Ties count as a win for each tied team"
    if tie_weeks:
        note += " (" + ", ".join(f"week {n}" for n in tie_weeks) + ")"
    return ('<div class="scroll"><table class="narrow"><thead><tr><th>Team (final order)</th>'
            f'<th class="n">Weeks won</th></tr></thead><tbody>{rows}</tbody></table></div>'
            f'<p class="muted small">{note}.</p>')


def render_page(season, repo, ov, cats, weeks, snaps, in_progress=False, excluded=()):
    nteams, ncats = len(ov), len(cats)
    last = _day(sorted(snaps)[-1])
    weeks_tbl, wins, tie_weeks = render_weeks(weeks)

    notes = []
    first_w, last_w = weeks[0], weeks[-1]
    nodata = [w for w in weeks if w["missing"]]
    span = f"{len(weeks)} weeks, {md(first_w['start'])} – {md(last_w['end'])}"
    if nodata:
        span += f"; {len(nodata)} with no data, not scored"
    intro_extra = ""
    if first_w["partial"]:
        intro_extra = (f" Week 1 is the shortened opening week ({date_range(first_w['start'], first_w['end'], '%a %b %-d')}) "
                       f"and counts as its own week.")
    if last_w["partial"] and not in_progress:
        intro_extra += (f" The final week is shortened ({date_range(last_w['start'], last_w['end'], '%a %b %-d')}) "
                        f"and counts as its own week.")
    if last_w["partial"] and in_progress:
        intro_extra += f" The latest week is in progress (through {md(last_w['end'], '%a %b %-d')})."
    nodata_days = {d for w in nodata for d in (w["start"] + dt.timedelta(n) for n in range(w["days"]))}
    miss = [d for d in missing_days(snaps) if d not in nodata_days]
    stale = [w for w in weeks if w["stale"] and not w["is_last"]]
    notes.append("<b>Weekly:</b> taken directly from OnRoto's own weekly standings in the last "
                 "snapshot of each week (normally Sunday's).")
    if miss and not stale:
        notes[-1] += (" Missing snapshots on " + human_list([date_range(a, b, "%a %b %-d") for a, b in day_ranges(miss)])
                      + " don't affect any week.")
    elif stale:
        one = len(stale) == 1
        notes[-1] += (f" Week{'' if one else 's'} " + human_list([str(w["n"]) for w in stale])
                      + f" {'uses' if one else 'use'} the latest earlier snapshot because Sunday's was missing (tagged above).")
    if nodata:
        notes.append("Week" + ("" if len(nodata) == 1 else "s") + " " + human_list(num_runs([w["n"] for w in nodata])) + " ("
                     + date_range(nodata[0]["start"], nodata[-1]["end"])
                     + (") has no nightly snapshots, so it cannot" if len(nodata) == 1 else ") have no nightly snapshots, so they cannot")
                     + " be scored or counted in the tally.")
    if excluded:
        notes.append("Excluded as too short to score as a week: " + human_list(
            [f"{date_range(w['start'], w['end'])} ({days_label(w['days'])}"
             + ("" if w["missing"] else f", won by {names(winners(w['standings']))}") + ")"
             for w in excluded]) + ".")
    notes.append("Results reflect each week's last snapshot, so any later OnRoto stat corrections "
                 "are not included.")

    final_h = "Current standings" if in_progress else "Final standings"
    status = f"season through {md(last, '%B %-d, %Y')}"
    max_pts = nteams * ncats
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{season} OnRoto Season Report</title>
<meta name="description" content="{final_h} and weekly winners for the {season} OnRoto rotisserie season.">
<style>
{CSS}
</style></head><body><main>
<h1>{season} OnRoto Season Report</h1>
<div class="meta">{nteams}-team, {ncats}-category rotisserie league · {status} · data from <a href="https://github.com/{repo}">{e(repo.split('/')[-1])}</a></div>

<h2 id="final">{final_h}</h2>
<div class="podium" aria-label="Top 3 podium">{render_podium(ov)}</div>
{podium_note(ov)}
{render_overall(ov, cats)}
<p class="muted small">Category columns are roto points ({nteams} = best, 1 = worst, ties split) from the {"latest" if in_progress else "final"} nightly snapshot.</p>

<h2 id="weekly">Weekly winners</h2>
<p class="muted">Each week scored in isolation: teams are ranked on that week's stats only, and the winner has the most roto points (max {max_pts}, {nteams} pts × {ncats} categories). Weeks run Monday–Sunday ({span}).{intro_extra}</p>
{weeks_tbl}

<h2 id="tally">Weeks won</h2>
{render_tally(ov, wins, tie_weeks)}

<h2 id="method">Method &amp; caveats</h2>
<ul>
{"".join(f"<li>{n}</li>" + chr(10) for n in notes)}</ul>
</main></body></html>"""


# --------------------------------------------------------------------------
def generate(season, data_dir, repo=DEFAULT_REPO, in_progress=False, min_days=1):
    snaps = load_snapshots(data_dir, season)
    if not snaps:
        raise SystemExit(f"no {season} snapshots found in {data_dir}")
    final = snaps[sorted(snaps)[-1]]
    ov, cats = overall_standings(final)
    all_weeks = build_weeks(snaps)
    weeks = [w for w in all_weeks if w["days"] >= min_days]
    excluded = [w for w in all_weeks if w["days"] < min_days]
    if not weeks:
        raise SystemExit(f"no weeks of at least {min_days} days")
    for i, w in enumerate(weeks):  # renumber and re-flag after any exclusions
        w["n"], w["is_first"], w["is_last"] = i + 1, i == 0, i == len(weeks) - 1
    return render_page(season, repo, ov, cats, weeks, snaps, in_progress, excluded)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("season", help="season year, e.g. 2026")
    ap.add_argument("--out", help="output HTML path (default: report/out/<season>.html)")
    ap.add_argument("--data-dir", help="folder of YYYY-MM-DD.json files (default: report/.cache/<season>)")
    ap.add_argument("--no-download", action="store_true", help="use files already in the data dir only")
    ap.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub repo holding the releases (default {DEFAULT_REPO})")
    ap.add_argument("--min-days", type=int, default=1,
                    help="leave out shortened opening/closing weeks with fewer days than this (default 1: count every week)")
    ap.add_argument("--in-progress", action="store_true",
                    help="label the standings as current rather than final (for a season still under way)")
    a = ap.parse_args(argv)

    here = os.path.dirname(os.path.abspath(__file__))
    data_dir = a.data_dir or os.path.join(here, ".cache", a.season)
    out = a.out or os.path.join(here, "out", f"{a.season}.html")
    if not a.no_download:
        download_season(a.repo, a.season, data_dir)
    page = generate(a.season, data_dir, a.repo, a.in_progress, a.min_days)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        f.write(page)
    print(f"wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
