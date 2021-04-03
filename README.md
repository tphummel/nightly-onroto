# nightly onroto standings scrape

[![Capture Fantasy Baseball Standings Each Night](https://github.com/tphummel/nightly-onroto/actions/workflows/nightly-release.yml/badge.svg)](https://github.com/tphummel/nightly-onroto/actions/workflows/nightly-release.yml)

## what/why?

- I play in a [rotisserie baseball league](https://en.wikipedia.org/wiki/Fantasy_baseball#Rotisserie_League_Baseball) on [onroto.com](https://onroto.com)
- Results are compiled each day but the historical results aren't made available.
- I want to have access to these daily records after the fact.

## novel bit

- Run arbitrary scheduled jobs using github actions in an open source repo (free compute)
- Scrape data from an authenticated website
- Save data to Github Releases as json artifacts (free storage and access to non-sensitive data)
