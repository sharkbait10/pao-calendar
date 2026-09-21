"""
paobc.gr source: the club's own schedule page, which is the only place that lists
Greek League (Stoiximan GBL), Super Cup and Greek Cup fixtures alongside EuroLeague.

Why a headless browser: the site is behind a JavaScript proof-of-work challenge.
A plain HTTP request gets a 503 "Verifying your browser..." page, so urllib and
requests both come back empty. Chromium runs the challenge script the way any
visitor's browser does, then the real HTML is available.

Two quirks of the page, both handled below:
  * Fixtures that have been announced but not yet scheduled are rendered with the
    page's own publish timestamp and no team names or venue. Those are skipped -
    otherwise the calendar fills with phantom games at the same meaningless time.
  * Times are Athens local, so they are converted to UTC via zoneinfo. Do not
    hardcode an offset; Greece switches between UTC+2 and UTC+3.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ATHENS = ZoneInfo("Europe/Athens")
BASE = "https://www.paobc.gr/en/schedule/"
MAX_PAGES = 12          # safety stop; the season listing is ~4 pages
SETTLE_MS = 4000        # time allowed for the challenge to clear and the page to render

CARD_RE = re.compile(
    r'<div class="game relative.*?(?=<div class="game relative|</section>)', re.S
)
LEAGUE_RE = re.compile(r'game__data__league">(.*?)</div>', re.S)
DATE_RE = re.compile(r'game__data__date.*?<span>(.*?)</span>\s*<span>(.*?)</span>', re.S)
STADIUM_RE = re.compile(r'game__data__stadium">(.*?)</div>', re.S)
NAMES_RE = re.compile(r'game__header__name__link">(.*?)</h3>', re.S)
SPAN_RE = re.compile(r"<span>(.*?)</span>", re.S)
SCORE_RE = re.compile(r'game__header__score[^>]*>(.*?)</div>', re.S)


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def fetch(skip_competitions: tuple[str, ...] = ("EUROLEAGUE",)) -> list[dict]:
    """
    Scrape every page of the schedule and return fixtures.

    `skip_competitions` drops leagues already covered by a better source - by
    default EuroLeague, which comes from the official feed with full-season dates.
    Raises ImportError if Playwright is unavailable, so the caller can degrade.
    """
    from playwright.sync_api import sync_playwright  # noqa: PLC0415 - optional dependency

    pages: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        page = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        ).new_page()
        try:
            for number in range(1, MAX_PAGES + 1):
                url = BASE if number == 1 else f"{BASE}page/{number}/"
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(SETTLE_MS)
                html = page.content()
                if "Verifying your browser" in html:
                    raise RuntimeError("paobc.gr challenge did not clear")
                if not CARD_RE.search(html):
                    break
                pages.append(html)
        finally:
            browser.close()

    return _parse_pages(pages, skip_competitions)


def _parse_pages(pages: list[str], skip_competitions: tuple[str, ...]) -> list[dict]:
    raw = []
    for html in pages:
        for card in CARD_RE.findall(html):
            parsed = _parse_card(card)
            if parsed:
                raw.append(parsed)

    # Unscheduled fixtures all inherit the page's publish timestamp. If the same
    # minute shows up repeatedly it is that placeholder, not a real tip-off.
    repeated = {
        moment for moment, count in Counter(item["start"] for item in raw).items() if count >= 3
    }

    skip = tuple(name.upper() for name in skip_competitions)
    fixtures, seen = [], defaultdict(int)
    for item in raw:
        if item["start"] in repeated:
            continue
        if any(name in item["competition"].upper() for name in skip):
            continue

        # Stable key that survives a reschedule, so the event updates in place.
        # The counter separates repeat meetings of the same pairing (playoff series).
        signature = f"{item['competition']}|{item['home']}|{item['away']}"
        seen[signature] += 1
        slug = re.sub(r"[^a-z0-9]+", "-", signature.lower()).strip("-")
        item["key"] = f"paobc-{slug}-{seen[signature]}"
        fixtures.append(item)
    return fixtures


def _parse_card(card: str) -> dict | None:
    league = LEAGUE_RE.search(card)
    date_match = DATE_RE.search(card)
    names_match = NAMES_RE.search(card)
    if not (league and date_match and names_match):
        return None

    names = [_text(span) for span in SPAN_RE.findall(names_match.group(1))]
    names = [name for name in names if name]
    if len(names) < 2:
        return None  # placeholder row: announced but not yet scheduled

    start = _parse_datetime(_text(date_match.group(1)), _text(date_match.group(2)))
    if not start:
        return None

    stadium = STADIUM_RE.search(card)
    home_score, away_score = _parse_scores(card)

    return {
        "source": "paobc",
        "competition": _text(league.group(1)),
        "round": "",
        "start": start,
        "home": names[0],
        "away": names[1],
        "venue": _text(stadium.group(1)) if stadium else "",
        "home_score": home_score,
        "away_score": away_score,
        "status": "confirmed",
        "url": "https://www.paobc.gr/en/schedule/",
    }


def _parse_datetime(date_text: str, time_text: str) -> datetime | None:
    """'Thursday, 24 Sep 2026' + '21:15' (Athens local) -> aware UTC datetime."""
    cleaned = date_text.split(",", 1)[-1].strip()
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            day = datetime.strptime(cleaned, fmt)
            break
        except ValueError:
            continue
    else:
        return None

    hour, minute = 0, 0
    clock = re.match(r"(\d{1,2})[:.](\d{2})", time_text)
    if clock:
        hour, minute = int(clock.group(1)), int(clock.group(2))

    local = day.replace(hour=hour, minute=minute, tzinfo=ATHENS)
    return local.astimezone(timezone.utc)


def _parse_scores(card: str) -> tuple[int | None, int | None]:
    """Finished games show a score block. Absent for fixtures, so this is best-effort."""
    block = SCORE_RE.search(card)
    if not block:
        return None, None
    numbers = re.findall(r"\d{1,3}", _text(block.group(1)))
    if len(numbers) < 2:
        return None, None
    return int(numbers[0]), int(numbers[1])
