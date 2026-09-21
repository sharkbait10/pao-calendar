"""
Fixture sources.

Every source module exposes `fetch()` returning a list of dicts in this shape:

    {
        "key":         str,            # stable per fixture; becomes the iCal UID
        "source":      str,            # "euroleague" | "paobc"
        "competition": str,            # "EuroLeague", "STOIXIMAN GBL", ...
        "round":       str,            # "Round 4", "Final", or ""
        "start":       datetime,       # timezone-aware, UTC
        "home":        str,
        "away":        str,
        "venue":       str,
        "home_score":  int | None,     # None until the game is played
        "away_score":  int | None,
        "status":      str,            # "confirmed" | "tentative"
        "url":         str,
    }

To add another competition, write a module with a `fetch()` of that shape and
register it in build_calendar.py. Nothing else needs to change.
"""
