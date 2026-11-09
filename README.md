# nightly onroto standings scrape

[![Capture Fantasy Baseball Standings Each Night](https://github.com/tphummel/nightly-onroto/actions/workflows/nightly-release.yml/badge.svg)](https://github.com/tphummel/nightly-onroto/actions/workflows/nightly-release.yml) [![Latest Release](https://img.shields.io/github/v/release/tphummel/nightly-onroto)](https://github.com/tphummel/nightly-onroto/releases)

## what/why?

- I play in a [rotisserie baseball league](https://en.wikipedia.org/wiki/Fantasy_baseball#Rotisserie_League_Baseball) on [onroto.com](https://onroto.com)
- Results are compiled each day but the historical results aren't made available.
- I want to have access to these daily records after the fact.

## novel bit

- Run arbitrary scheduled jobs using github actions in an open source repo (free compute)
- Scrape data from an authenticated website
- Save data to Github Releases as json artifacts (free storage and access to non-sensitive data)

## season report

`report/season_report.py` turns a season of nightly standings into a single-page HTML report: final standings with a top-3 podium, the winner of every Monday-Sunday week (each week scored in isolation), and a weeks-won tally. Python 3 standard library only.

```sh
# download the season's snapshots (cached in report/.cache/<season>) and write report/out/<season>.html
python3 report/season_report.py 2026

# choose the output path, e.g. to publish on mlb.tomhummel.com
python3 report/season_report.py 2026 --out ../mlb.tomhummel.com/static/onroto-2026/index.html

# re-run for another season
python3 report/season_report.py 2025
```

Options: `--data-dir` (use a folder of already-downloaded `YYYY-MM-DD.json` files), `--no-download`, `--repo`, `--min-days N` (leave out a shortened opening/closing week with fewer than N days; the default counts every week), and `--in-progress` (label the standings as current rather than final).

Notes:

- Weekly results are OnRoto's own weekly roto points from the last snapshot in each Monday-Sunday week, so nothing is estimated. A week whose Sunday snapshot is missing uses the latest earlier snapshot and is tagged on the page.
- A season that starts or ends mid-week gets a shortened first or last week, tagged on the page, that counts as its own week.
- Teams, categories and league size are read from the data, so the report adapts to each season.
- Tests: `python3 -m unittest discover -s report`
