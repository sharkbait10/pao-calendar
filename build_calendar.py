#!/usr/bin/env python3
"""
Build an auto-updating iCalendar feed of Panathinaikos AKTOR Athens fixtures.

Sources (see scripts/sources/):
  * euroleague - official public feed. Authoritative for EuroLeague: real kickoff
    times for the full season, venues, scores. No key, no bot protection.
  * paobc      - the club site, scraped with a headless browser. Supplies every
    other competition: Stoiximan GBL, Super Cup, Greek Cup.

The paobc source is optional. If Playwright is missing or the scrape fails, the
build logs a warning and continues with EuroLeague rather than shipping nothing.

Output is deterministic: an unchanged fixture list leaves the .ics untouched, so
the daily cron does not produce empty commits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from sources import euroleague, paobc  # noqa: E402

TEAM_MARKER = "PANATHINAIKOS"
CALENDAR_NAME = "Panathinaikos AKTOR Athens"
CALENDAR_DESC = "All competitions: EuroLeague, Stoiximan GBL, Super Cup, Greek Cup"
UID_DOMAIN = "paobc-calendar"          # any stable string; never change it
GAME_DURATION = timedelta(hours=2)
DTSTAMP_TOKEN = "@@DTSTAMP@@"

# A paobc fixture this close to a EuroLeague one against the same opponent is
# assumed to be the same game listed twice under a different competition label.
DUPLICATE_WINDOW = timedelta(hours=12)


# --------------------------------------------------------------------------- #
# Gathering
# --------------------------------------------------------------------------- #

def gather(season: str | None, use_paobc: bool) -> tuple[list[dict], list[str]]:
    problems: list[str] = []

    fixtures = euroleague.fetch(season)          # fatal if this fails - see main()
    print(f"euroleague: {len(fixtures)} fixtures")

    if use_paobc:
        try:
            extra = paobc.fetch()
            print(f"paobc: {len(extra)} non-EuroLeague fixtures")
            fixtures += deduplicate(fixtures, extra)
        except ImportError:
            problems.append("Playwright not installed - skipped paobc.gr")
        except Exception as error:                # noqa: BLE001 - never fail the build on a scrape
            problems.append(f"paobc.gr scrape failed ({error}) - EuroLeague only")

    for problem in problems:
        print(f"WARNING: {problem}", file=sys.stderr)
    return fixtures, problems


def deduplicate(existing: list[dict], candidates: list[dict]) -> list[dict]:
    """Drop scraped fixtures that duplicate one already covered by the feed."""
    kept = []
    for candidate in candidates:
        clash = any(
            abs(candidate["start"] - known["start"]) < DUPLICATE_WINDOW
            and _opponent(candidate).upper()[:8] == _opponent(known).upper()[:8]
            for known in existing
        )
        if not clash:
            kept.append(candidate)
    dropped = len(candidates) - len(kept)
    if dropped:
        print(f"  dropped {dropped} duplicate(s) already in the EuroLeague feed")
    return kept


def _opponent(fixture: dict) -> str:
    return fixture["away"] if _is_home(fixture) else fixture["home"]


def _is_home(fixture: dict) -> bool:
    return TEAM_MARKER in fixture["home"].upper()


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #

def to_event(fixture: dict) -> dict:
    home, away = fixture["home"], fixture["away"]
    played = fixture["home_score"] is not None and fixture["away_score"] is not None
    prefix = "🏠" if _is_home(fixture) else "✈️"

    if played:
        summary = f"{prefix} {home} {fixture['home_score']}-{fixture['away_score']} {away}"
    else:
        summary = f"{prefix} {home} vs {away}"

    tag = " / ".join(part for part in (fixture["competition"], fixture["round"]) if part)
    if tag:
        summary = f"{summary} ({tag})"

    description = [tag] if tag else []
    if fixture["venue"]:
        description.append(f"Venue: {fixture['venue']}")
    if played:
        description.append(
            f"Final: {home} {fixture['home_score']} - {fixture['away_score']} {away}"
        )
    description.append(f"Source: {fixture['source']}")

    return {
        "uid": f"{fixture['key']}@{UID_DOMAIN}",
        "start": fixture["start"],
        "end": fixture["start"] + GAME_DURATION,
        "summary": summary,
        "location": fixture["venue"],
        "description": "\n".join(description),
        "status": "CONFIRMED" if (played or fixture["status"] == "confirmed") else "TENTATIVE",
        "url": fixture["url"],
    }


# --------------------------------------------------------------------------- #
# iCalendar serialisation
# --------------------------------------------------------------------------- #

def escape(value: str) -> str:
    """Escape per RFC 5545 section 3.3.11."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Fold content lines at 75 octets, continuing with a leading space."""
    if len(line.encode("utf-8")) <= 75:
        return line
    chunks, current = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        limit = 75 if not chunks else 74      # continuation lines spend a byte on the space
        if len(current) + len(encoded) > limit:
            chunks.append(current)
            current = b""
        current += encoded
    chunks.append(current)
    return "\r\n ".join(chunk.decode("utf-8") for chunk in chunks)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fingerprint(event: dict) -> str:
    """Hash of the fields a subscriber would notice changing."""
    payload = "|".join([
        stamp(event["start"]), stamp(event["end"]), event["summary"],
        event["location"], event["description"], event["status"],
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def render(events: list[dict], sequences: dict[str, int]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{UID_DOMAIN}//Panathinaikos fixtures//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(CALENDAR_NAME)}",
        f"X-WR-CALDESC:{escape(CALENDAR_DESC)}",
        "X-WR-TIMEZONE:Europe/Athens",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    for event in sorted(events, key=lambda item: item["start"]):
        lines += [
            "BEGIN:VEVENT",
            f"UID:{event['uid']}",
            f"DTSTAMP:{DTSTAMP_TOKEN}",
            f"DTSTART:{stamp(event['start'])}",
            f"DTEND:{stamp(event['end'])}",
            f"SEQUENCE:{sequences.get(event['uid'], 0)}",
            f"SUMMARY:{escape(event['summary'])}",
            f"STATUS:{event['status']}",
            "TRANSP:TRANSPARENT",
        ]
        if event["location"]:
            lines.append(f"LOCATION:{escape(event['location'])}")
        if event["description"]:
            lines.append(f"DESCRIPTION:{escape(event['description'])}")
        if event["url"]:
            lines.append(f"URL:{event['url']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(line) for line in lines) + "\r\n"


def strip_dtstamp(text: str) -> str:
    return "\n".join(
        line for line in text.replace("\r\n", "\n").split("\n")
        if not line.startswith("DTSTAMP:")
    )


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/panathinaikos.ics")
    parser.add_argument("--state", default="docs/.calendar-state.json")
    parser.add_argument("--season", default=None, help="e.g. E2026 (default: current)")
    parser.add_argument("--no-paobc", action="store_true",
                        help="EuroLeague only; skip the headless-browser scrape")
    args = parser.parse_args()

    try:
        fixtures, problems = gather(args.season, use_paobc=not args.no_paobc)
    except Exception as error:                    # noqa: BLE001
        # Never overwrite a good calendar with a broken one.
        print(f"ERROR: could not build fixture list: {error}", file=sys.stderr)
        return 1

    events = [to_event(fixture) for fixture in fixtures]
    if not events:
        print("ERROR: no events, refusing to write", file=sys.stderr)
        return 1

    output_path = pathlib.Path(args.output)
    state_path = pathlib.Path(args.state)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            state = {}
    previous = state.get("events", {})

    # SEQUENCE only moves for events that genuinely changed - that is what makes
    # a calendar client revise an already-synced entry instead of ignoring it.
    sequences, new_state, changed = {}, {}, []
    for event in events:
        uid = event["uid"]
        current = fingerprint(event)
        old = previous.get(uid)
        if old is None:
            sequence = 0
        elif old.get("fingerprint") == current:
            sequence = old.get("sequence", 0)
        else:
            sequence = old.get("sequence", 0) + 1
            changed.append(event["summary"])
        sequences[uid] = sequence
        new_state[uid] = {"fingerprint": current, "sequence": sequence}

    body = render(events, sequences)

    if output_path.exists():
        if strip_dtstamp(output_path.read_bytes().decode("utf-8")) == strip_dtstamp(body):
            print("no changes - calendar left untouched")
            return 0

    output_path.write_text(
        body.replace(DTSTAMP_TOKEN, stamp(datetime.now(timezone.utc))),
        encoding="utf-8", newline="",
    )
    state_path.write_text(
        json.dumps(
            {
                "updated": datetime.now(timezone.utc).isoformat(),
                "warnings": problems,
                "events": new_state,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    by_competition: dict[str, int] = {}
    for fixture in fixtures:
        by_competition[fixture["competition"]] = by_competition.get(fixture["competition"], 0) + 1
    print(f"wrote {output_path}: {len(events)} events " + str(by_competition))
    for summary in changed:
        print(f"  changed: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
