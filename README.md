# Panathinaikos AKTOR Athens — auto-updating calendar

Publishes an iCalendar (`.ics`) feed of Panathinaikos fixtures **across all competitions** to
GitHub Pages, rebuilt twice a day by GitHub Actions. Subscribe once in Google / Apple / Outlook
Calendar and reschedules, venue changes and final scores arrive on their own.

**Feed:** `https://USER.github.io/REPO/panathinaikos.ics`

## Setup

1. Create a repo and drop these files in at the root.
2. **Settings → Pages** → Source: *Deploy from a branch* → branch `main`, folder `/docs`.
3. **Settings → Actions → General** → Workflow permissions: *Read and write permissions*.
   Without this the workflow cannot push its commit.
4. Replace `USER` and `REPO` in `docs/index.html` and in this README.
5. **Actions → Update calendar → Run workflow** to build it immediately.

Locally:

```bash
pip install -r requirements.txt
playwright install chromium

python3 scripts/build_calendar.py              # all competitions
python3 scripts/build_calendar.py --no-paobc   # EuroLeague only, no browser needed
```

## Two sources, on purpose

| Source | Covers | How |
| --- | --- | --- |
| `sources/euroleague.py` | EuroLeague | Official public JSON feed, no API key, standard library only |
| `sources/paobc.py` | Stoiximan GBL, Super Cup, Greek Cup | Scrapes paobc.gr with headless Chromium |

EuroLeague games come from the official feed rather than the club site because the feed is simply
better data: all 38 rounds carry real kickoff times, venues, addresses and live scores. On
paobc.gr only the next ~9 games have real dates — everything from November onward currently renders
with the page's publish timestamp (`Monday, 21 Sep 2026 14:06`), no venue and no opponent name.
Those placeholder rows are detected and skipped.

The club site is still needed because it is the only place that lists the domestic competitions.

### Why the scraper needs a browser

paobc.gr sits behind a JavaScript proof-of-work challenge. A plain HTTP request returns a `503`
"Verifying your browser…" page, so `requests` and `urllib` both come back with nothing. Chromium
runs the challenge script the way any visitor's browser does and the real HTML follows. The workflow
caches the browser binary, so most runs spend only a few seconds on it.

If Playwright is missing or the scrape fails, the build **logs a warning and carries on** with
EuroLeague rather than shipping an empty calendar. The warning is also recorded in
`docs/.calendar-state.json`.

### Heads-up on current coverage

At the time of writing, the 2026-27 Greek League, Super Cup and Greek Cup fixtures have not been
published yet — not on paobc.gr, and not on esake.gr. So today the calendar contains the 38
EuroLeague games and the scraper returns zero extra fixtures. That is expected, not a bug: the
domestic games will appear automatically once the club publishes them.

## How updates reach subscribers

Calendar clients only revise an event they have already synced if the `UID` stays the same **and**
the `SEQUENCE` number goes up. Both are handled:

- EuroLeague events use the feed's stable game identifier (`E2026_7@paobc-calendar`).
- Scraped events use a key built from competition + teams, deliberately *not* the date, so a
  rescheduled game updates in place instead of appearing twice. A counter distinguishes repeat
  meetings of the same pairing, such as a playoff series.
- `docs/.calendar-state.json` stores a fingerprint per event; when a fixture's time, venue, status
  or score changes, only that event's `SEQUENCE` increments.

The build is deterministic: if nothing changed, the `.ics` is left untouched and no commit is made.
If a source is unreachable the script exits non-zero without writing, so a bad fetch can never blank
out a working calendar.

### Duplicate protection

A game listed by both sources is dropped from the scraped set. The primary filter is the competition
label, backed up by a time-and-opponent check (same opponent within 12 hours). Verified by running
the scraper with its EuroLeague filter disabled: all 15 overlapping fixtures were caught.

## Adding another competition

Write a module in `scripts/sources/` with a `fetch()` returning the dict shape documented in
`scripts/sources/__init__.py`, then register it in `gather()` in `build_calendar.py`. Nothing else
changes.

`esake.gr` is worth knowing about: it serves plain HTML with no bot protection, so a Greek League
source could use `urllib` alone and avoid the browser entirely — once its fixture list is published.

## Files

```
scripts/build_calendar.py    merge, format, render, commit-avoidance
scripts/sources/euroleague.py  official feed (stdlib only)
scripts/sources/paobc.py       club site (Playwright)
.github/workflows/           twice-daily cron + auto-commit
docs/index.html              subscribe page served by Pages
docs/panathinaikos.ics       generated feed
docs/.calendar-state.json    generated; tracks SEQUENCE — don't delete
```
