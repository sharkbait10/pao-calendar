"""
EuroLeague source: the official public feed. No API key, no bot protection.

Returns fixtures in the shared shape documented in sources/__init__.py.
This is the authoritative source for EuroLeague games - it carries real kickoff
times for the whole season, plus venues, addresses and live scores.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

TEAM_CODE = "PAN"
TIMEOUT = 30
USER_AGENT = "paobc-calendar/1.0"

FEED_URL = (
    "https://feeds.incrowdsports.com/provider/euroleague-feeds/v2"
    "/competitions/E/seasons/{season}/games?teamCode={team}"
)
GAME_CENTER = "https://www.euroleaguebasketball.net/en/euroleague/game-center/"


def current_season_code(today: datetime | None = None) -> str:
    """EuroLeague seasons are named for their starting year: E2026 = 2026-27."""
    today = today or datetime.now(timezone.utc)
    year = today.year if today.month >= 7 else today.year - 1
    return f"E{year}"


def fetch(season: str | None = None) -> list[dict]:
    season = season or current_season_code()
    url = FEED_URL.format(season=season, team=TEAM_CODE)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))

    games = payload.get("data") or []
    if not games:
        raise RuntimeError(f"EuroLeague feed returned no games for {season}")

    fixtures = []
    for game in games:
        fixture = _parse(game)
        if fixture:
            fixtures.append(fixture)
    return fixtures


def _parse(game: dict) -> dict | None:
    raw_date = game.get("date")
    if not raw_date:
        return None
    try:
        start = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
    except ValueError:
        return None

    home = game.get("home") or {}
    away = game.get("away") or {}
    venue = game.get("venue") or {}

    home_score = home.get("score") or 0
    away_score = away.get("score") or 0
    played = bool(home_score or away_score)

    round_info = game.get("round") or {}
    phase = (game.get("phaseType") or {}).get("name") or ""

    return {
        "key": str(game.get("identifier") or game.get("code")),
        "source": "euroleague",
        "competition": "EuroLeague",
        "round": round_info.get("name") or phase or "",
        "start": start.astimezone(timezone.utc),
        "home": home.get("name") or "TBD",
        "away": away.get("name") or "TBD",
        "venue": ", ".join(
            part for part in (venue.get("name"), venue.get("address")) if part
        ),
        "home_score": home_score if played else None,
        "away_score": away_score if played else None,
        "status": "confirmed" if (played or game.get("status") == "confirmed") else "tentative",
        "url": GAME_CENTER,
    }
