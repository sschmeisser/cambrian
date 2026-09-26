#!/usr/bin/env python3
"""
schedule_fetcher.py — ESPN Schedule Verification & Discovery Engine
Bay Area Sports Gazette

Autonomous engine that:
1. Verifies existing GAMES_DATA entries against live ESPN scoreboards.
2. Discovers missing or newly scheduled games for tracked Bay Area teams (Sharks, 49ers,
   Earthquakes, Bay FC, Warriors, Valkyries, Stanford, Cal, SJSU, etc.).
3. Converts UTC timestamps to accurate Pacific Local Time (America/Los_Angeles), eliminating
   timezone bleed where evening games slip to the next calendar date.
4. Auto-ingests discovered matchups into data/games.json with full Gazette metadata.

Usage:
    python3 schedule_fetcher.py --verify
    python3 schedule_fetcher.py --discover
    python3 schedule_fetcher.py --sync
"""

import json
import logging
import sys
from datetime import date, timedelta, datetime

try:
    from zoneinfo import ZoneInfo
    PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
except ImportError:
    from datetime import timezone
    PACIFIC_TZ = timezone(timedelta(hours=-7))

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
)
log = logging.getLogger("schedule_fetcher")

# ---------------------------------------------------------------------------
# ESPN public API endpoints — all free, no key required
# ---------------------------------------------------------------------------
ESPN_ENDPOINTS = {
    "nfl":           "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "nhl":           "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard",
    "nba":           "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "wnba":          "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    "mls":           "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard",
    "nwsl":          "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.nwsl/scoreboard",
    "ncaa_football": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
    "ncaa_soccer_m": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.ncaa.m.1/scoreboard",
}

# HTTP headers that avoid 403 blocks from ESPN
_HEADERS = {
    "Accept": "application/json",
}

# ---------------------------------------------------------------------------
# Bay Area team keyword lists (used for name-matching)
# ---------------------------------------------------------------------------
BAY_AREA_TEAM_KEYWORDS = {
    # NFL
    "nfl":           ["49ers", "San Francisco 49ers"],
    # NHL
    "nhl":           ["Sharks", "San Jose Sharks"],
    # NBA / WNBA
    "nba":           ["Warriors", "Golden State Warriors"],
    "wnba":          ["Valkyries", "Golden State Valkyries"],
    # MLS
    "mls":           ["Earthquakes", "San Jose Earthquakes"],
    # NWSL
    "nwsl":          ["Bay FC"],
    # College football
    "ncaa_football": ["California Golden Bears", "San José State", "San Jose State",
                      "Stanford Cardinal"],
    # Men's college soccer
    "ncaa_soccer_m": ["Santa Clara", "Stanford", "San Jose State", "California"],
}

SOUTH_BAY_CITIES = {
    "San Jose", "Campbell", "Santa Clara", "Cupertino", "Mountain View", "Stanford", "Los Gatos", "Saratoga"
}

# ---------------------------------------------------------------------------
# Cache: {(endpoint_key, date_str) -> list[event_dict]}
# ---------------------------------------------------------------------------
_cache: dict = {}


def _fetch_scoreboard(endpoint_key: str, date_str: str) -> list:
    """
    Fetch ESPN scoreboard for a given endpoint and YYYYMMDD date string.
    Returns list of raw ESPN event dicts, or [] on failure.
    Caches results to avoid duplicate network calls.
    """
    cache_key = (endpoint_key, date_str)
    if cache_key in _cache:
        return _cache[cache_key]

    if not HAS_REQUESTS:
        log.warning("'requests' library not installed — cannot fetch ESPN data.")
        _cache[cache_key] = []
        return []

    url = ESPN_ENDPOINTS.get(endpoint_key)
    if not url:
        log.warning("Unknown endpoint key: %s", endpoint_key)
        _cache[cache_key] = []
        return []

    params = {"dates": date_str, "limit": 200}
    try:
        resp = requests.get(url, headers=_HEADERS, params=params, timeout=10)
        resp.raise_for_status()
        events = resp.json().get("events", [])
        _cache[cache_key] = events
        log.debug("Fetched %d events from %s on %s", len(events), endpoint_key, date_str)
        return events
    except Exception as exc:
        log.warning("ESPN fetch failed (%s, %s): %s", endpoint_key, date_str, exc)
        _cache[cache_key] = []
        return []


def _dates_around(date_str: str, days: int = 2) -> list:
    """Return YYYYMMDD strings for ±days around date_str."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return [date_str]
    result = []
    for delta in range(-days, days + 1):
        result.append((d + timedelta(days=delta)).strftime("%Y%m%d"))
    return result


def _extract_games(events: list) -> list:
    """
    Normalize ESPN event list into standardized dicts with local Pacific Time:
    {home_team, away_team, home_score, away_score, venue, venue_city, date_str,
     time_str, day_name, source_url, season_type, is_completed, status_detail, event_id}
    """
    out = []
    for ev in events:
        for comp in ev.get("competitions", []):
            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue
            venue_obj = comp.get("venue", {})
            links = ev.get("links", [])
            source_url = links[0].get("href", "") if links else ""
            status_obj = comp.get("status", {}) or ev.get("status", {})
            status_type = status_obj.get("type", {})
            is_completed = bool(status_type.get("completed", False) or status_type.get("name") == "STATUS_FINAL")
            status_detail = status_type.get("shortDetail") or status_type.get("detail") or status_type.get("description") or ""

            # Timezone conversion: parse UTC string and convert to America/Los_Angeles
            utc_str = comp.get("date") or ev.get("date", "")
            local_date_str = ""
            local_time_str = "TBD"
            day_name = ""
            if utc_str:
                try:
                    dt_utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
                    dt_local = dt_utc.astimezone(PACIFIC_TZ)
                    local_date_str = dt_local.date().isoformat()
                    local_time_str = dt_local.strftime("%I:%M %p").lstrip("0")
                    day_name = dt_local.strftime("%A")
                except Exception:
                    local_date_str = utc_str[:10]

            out.append({
                "home_team":    home["team"].get("displayName", ""),
                "away_team":    away["team"].get("displayName", ""),
                "home_score":   home.get("score"),
                "away_score":   away.get("score"),
                "venue":        venue_obj.get("fullName", ""),
                "venue_city":   (venue_obj.get("address") or {}).get("city", ""),
                "date_str":     local_date_str,
                "utc_date":     utc_str,
                "time_str":     local_time_str,
                "day_name":     day_name,
                "source_url":   source_url,
                "season_type":  ev.get("season", {}).get("type"),  # 1=pre, 2=regular, 3=post
                "is_completed": is_completed,
                "status_detail": status_detail,
                "event_id":     str(ev.get("id", "")),
            })
    return out


def _name_match_score(a: str, b: str) -> float:
    """
    Return 0.0–1.0 similarity score between two team name strings.
    Uses word-overlap heuristic.
    """
    a_words = set(a.lower().split())
    b_words = set(b.lower().split())
    common = a_words & b_words
    if not common:
        return 0.0
    union = a_words | b_words
    return len(common) / len(union)


def _best_match(
    game: dict, espn_games: list, threshold: float = 0.3
) -> tuple:
    """
    Find the best-matching ESPN game for a GAMES_DATA entry.
    Considers both team name similarity and date proximity.
    Returns (espn_game_dict | None, confidence_float).
    """
    listed_home = game.get("home_team", "")
    listed_away = game.get("away_team", "")
    listed_date = game.get("date", "")
    best_score = 0.0
    best_match = None

    for eg in espn_games:
        score_a = max(
            _name_match_score(listed_home, eg["home_team"]),
            _name_match_score(listed_home, eg["away_team"]),
        )
        score_b = max(
            _name_match_score(listed_away, eg["home_team"]),
            _name_match_score(listed_away, eg["away_team"]),
        )
        combined = (score_a + score_b) / 2

        # Reward date match
        if listed_date and eg.get("date_str") == listed_date:
            combined = min(1.0, combined + 0.15)

        if combined > best_score:
            best_score = combined
            best_match = eg

    if best_score < threshold:
        return None, 0.0
    return best_match, min(best_score, 1.0)


def _sport_to_endpoints(game: dict) -> list:
    """Map a GAMES_DATA sport + league to relevant ESPN endpoint keys."""
    sport  = game.get("sport", "").lower()
    league = game.get("league", "").lower()
    level  = game.get("level", "").lower()
    if sport == "football":
        if "nfl" in league or level == "pro":
            return ["nfl"]
        if "college" in level or "ncaa" in league or "fbs" in league:
            return ["ncaa_football"]
    if sport == "hockey":
        return ["nhl"]
    if sport == "basketball":
        if "wnba" in league:
            return ["wnba"]
        if "nba" in league or level == "pro":
            return ["nba"]
    if sport == "soccer":
        if "nwsl" in league:
            return ["nwsl"]
        if "mls" in league:
            return ["mls"]
        if "ncaa" in league or "college" in level:
            return ["ncaa_soccer_m"]
    return []


# ---------------------------------------------------------------------------
# Verification Engine
# ---------------------------------------------------------------------------

def verify_game(game: dict) -> dict:
    """
    Verify a single GAMES_DATA entry against ESPN live data.

    Returns:
    {
        'match_found': bool,
        'confidence':  float 0.0–1.0,
        'corrections': {field: corrected_value, ...},
        'source_url':  str,
        'notes':       str,
    }
    """
    result = {
        "match_found": False,
        "confidence":  0.0,
        "corrections": {},
        "source_url":  "",
        "notes":       "",
    }

    endpoints = _sport_to_endpoints(game)
    if not endpoints:
        result["notes"] = "No ESPN endpoint mapped for this sport/league."
        return result

    game_date = game.get("date", "")
    all_espn_games: list = []
    # Search around date (with ±2 days to ensure all timezone overlaps are captured)
    for date_str in _dates_around(game_date, days=2):
        for ep_key in endpoints:
            events = _fetch_scoreboard(ep_key, date_str)
            all_espn_games.extend(_extract_games(events))

    if not all_espn_games:
        result["notes"] = "No ESPN events fetched (API unavailable or no games in window)."
        return result

    match, confidence = _best_match(game, all_espn_games)
    if match is None:
        result["notes"] = "No matching game found in ESPN data."
        return result

    result["match_found"] = True
    result["confidence"]  = round(confidence, 2)
    result["source_url"]  = match.get("source_url", "")

    # Build corrections dict
    corrections = {}
    listed_home = game.get("home_team", "")
    listed_away = game.get("away_team", "")
    espn_home   = match.get("home_team", "")
    espn_away   = match.get("away_team", "")

    is_swapped = False
    if (_name_match_score(listed_home, espn_away) > _name_match_score(listed_home, espn_home)
            and _name_match_score(listed_away, espn_home) > _name_match_score(listed_away, espn_away)):
        is_swapped = True
        corrections["home_team"] = espn_away
        corrections["away_team"] = espn_home
        corrections["_note_swap"] = "Home/away teams appear reversed vs ESPN data."
    else:
        if _name_match_score(listed_away, espn_away) < 0.5:
            corrections["away_team"] = espn_away
        if _name_match_score(listed_home, espn_home) < 0.5:
            corrections["home_team"] = espn_home

    # Venue mismatch
    listed_venue = game.get("venue", "")
    espn_venue   = match.get("venue", "")
    if espn_venue and listed_venue and _name_match_score(listed_venue, espn_venue) < 0.4:
        corrections["venue"] = espn_venue

    # Time update
    if match.get("time_str") and match["time_str"] != "TBD" and game.get("time") in [None, "", "TBD"]:
        corrections["time"] = match["time_str"]

    # Score corrections (for final games, or when ESPN indicates match is completed)
    is_espn_completed = match.get("is_completed", False)
    if match.get("home_score") is not None and match.get("away_score") is not None:
        try:
            raw_h = int(match.get("home_score"))
            raw_a = int(match.get("away_score"))
            espn_home_score = raw_a if is_swapped else raw_h
            espn_away_score = raw_h if is_swapped else raw_a

            if is_espn_completed or game.get("status") == "final":
                corrections["home_score"] = espn_home_score
                corrections["away_score"] = espn_away_score
                if is_espn_completed:
                    corrections["status"] = "final"
                if match.get("status_detail"):
                    corrections["status_detail"] = match.get("status_detail")
        except (TypeError, ValueError):
            pass

    result["corrections"] = corrections
    return result


# ---------------------------------------------------------------------------
# Schedule Discovery Engine
# ---------------------------------------------------------------------------

def _sport_defaults(endpoint_key: str, season_type: int = 2) -> dict:
    """Map an ESPN endpoint key to Gazette sports taxonomy."""
    is_preseason = (season_type == 1)
    if endpoint_key == "nhl":
        return {
            "sport": "Hockey",
            "sport_icon": "🏒",
            "league": "NHL Preseason" if is_preseason else "NHL",
            "level": "Pro",
            "city": "San Jose",
            "venue": "SAP Center",
            "ticket_text": "Sharks Tickets",
            "ticket_url": "https://www.nhl.com/sharks/tickets",
            "is_south_bay": True,
            "tags": ["hockey", "nhl", "sharks", "south bay", "san jose"]
        }
    if endpoint_key == "nfl":
        return {
            "sport": "Football",
            "sport_icon": "🏈",
            "league": "NFL",
            "level": "Pro",
            "city": "Santa Clara",
            "venue": "Levi's Stadium",
            "ticket_text": "49ers Tickets",
            "ticket_url": "https://www.49ers.com/tickets",
            "is_south_bay": True,
            "tags": ["football", "nfl", "49ers", "south bay", "santa clara"]
        }
    if endpoint_key == "nba":
        return {
            "sport": "Basketball",
            "sport_icon": "🏀",
            "league": "NBA Preseason" if is_preseason else "NBA",
            "level": "Pro",
            "city": "San Francisco",
            "venue": "Chase Center",
            "ticket_text": "Warriors Tickets",
            "ticket_url": "https://www.nba.com/warriors/tickets",
            "is_south_bay": False,
            "tags": ["basketball", "nba", "warriors", "chase center", "san francisco"]
        }
    if endpoint_key == "wnba":
        return {
            "sport": "Basketball",
            "sport_icon": "🏀",
            "league": "WNBA",
            "level": "Pro",
            "city": "San Francisco",
            "venue": "Chase Center",
            "ticket_text": "Valkyries Tickets",
            "ticket_url": "https://valkyries.wnba.com/tickets",
            "is_south_bay": False,
            "tags": ["basketball", "wnba", "valkyries", "womens sports"]
        }
    if endpoint_key == "mls":
        return {
            "sport": "Soccer",
            "sport_icon": "⚽",
            "league": "MLS",
            "level": "Pro",
            "city": "San Jose",
            "venue": "PayPal Park",
            "ticket_text": "Earthquakes Tickets",
            "ticket_url": "https://www.sjearthquakes.com/tickets",
            "is_south_bay": True,
            "tags": ["soccer", "mls", "earthquakes", "south bay", "san jose"]
        }
    if endpoint_key == "nwsl":
        return {
            "sport": "Soccer",
            "sport_icon": "⚽",
            "league": "NWSL",
            "level": "Pro",
            "city": "San Jose",
            "venue": "PayPal Park",
            "ticket_text": "Bay FC Tickets",
            "ticket_url": "https://bayfc.com/tickets",
            "is_south_bay": True,
            "tags": ["soccer", "nwsl", "bay fc", "womens sports", "south bay"]
        }
    if endpoint_key == "ncaa_football":
        return {
            "sport": "Football",
            "sport_icon": "🏈",
            "league": "NCAA FBS",
            "level": "College",
            "city": "San Jose",
            "venue": "CEFCU Stadium",
            "ticket_text": "Spartans Tickets",
            "ticket_url": "https://sjsuspartans.com/tickets",
            "is_south_bay": True,
            "tags": ["football", "college", "south bay"]
        }
    return {
        "sport": "Soccer",
        "sport_icon": "⚽",
        "league": "NCAA Division I",
        "level": "College",
        "city": "Santa Clara",
        "venue": "Stevens Stadium",
        "ticket_text": "Broncos Tickets",
        "ticket_url": "https://santaclarabroncos.com/tickets",
        "is_south_bay": True,
        "tags": ["soccer", "college", "south bay"]
    }


def discover_bay_area_games(start_date: str, end_date: str, home_only: bool = True) -> list:
    """
    Scan all ESPN endpoints for events between start_date and end_date (inclusive, YYYY-MM-DD).
    Returns list of discovered Bay Area matchups in local Pacific Time.
    """
    try:
        s_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        e_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        log.warning(f"Invalid date format in discovery: {start_date} to {end_date}")
        return []

    discovered = []
    seen_ids = set()

    # Iterate through days
    curr = s_dt
    while curr <= e_dt:
        # Date queries for ESPN (include ±1 day around curr to cover UTC boundaries)
        date_keys = [
            (curr - timedelta(days=1)).strftime("%Y%m%d"),
            curr.strftime("%Y%m%d"),
            (curr + timedelta(days=1)).strftime("%Y%m%d"),
        ]
        for ep_key in ESPN_ENDPOINTS:
            keywords = BAY_AREA_TEAM_KEYWORDS.get(ep_key, [])
            for dk in date_keys:
                events = _fetch_scoreboard(ep_key, dk)
                games = _extract_games(events)
                for g in games:
                    ev_id = g.get("event_id")
                    if ev_id and ev_id in seen_ids:
                        continue
                    # Match date strictly in Pacific Local Time
                    if g.get("date_str") != curr.isoformat():
                        continue

                    h_team = g.get("home_team", "")
                    a_team = g.get("away_team", "")

                    # Exclude non-Bay Area false positives
                    if "Baptist" in h_team or "Baptist" in a_team:
                        continue

                    # Check Bay Area hosting or participation
                    is_home_bay = any(k.lower() in h_team.lower() for k in keywords)
                    is_away_bay = any(k.lower() in a_team.lower() for k in keywords)

                    if is_home_bay or (not home_only and is_away_bay):
                        seen_ids.add(ev_id)
                        g["endpoint_key"] = ep_key
                        g["is_bay_host"] = is_home_bay
                        discovered.append(g)

        curr += timedelta(days=1)

    log.info(f"Discovered {len(discovered)} Bay Area games between {start_date} and {end_date}.")
    return discovered


def sync_schedule_for_window(
    games: list,
    weeks: list,
    start_date: str = None,
    end_date: str = None
) -> tuple:
    """
    Synchronize the active calendar window with live ESPN schedules:
    - Finds games that already exist and updates scores/status/recap/times.
    - Automatically discovers and ingests missing games (e.g. newly scheduled or overlooked games).
    Returns: (new_games_count, updated_games_count, changelog)
    """
    if not start_date or not end_date:
        today_iso = datetime.now(PACIFIC_TZ).date().isoformat()
        # Find current or upcoming week range
        matched_weeks = [w for w in weeks if w.get("start_date") and w.get("end_date")]
        if matched_weeks:
            # Span from current week to rolling next week
            curr_week = next((w for w in matched_weeks if w.get("start_date") <= today_iso <= w.get("end_date")), matched_weeks[0])
            start_date = curr_week.get("start_date")
            end_date = curr_week.get("end_date")
        else:
            start_date = (datetime.now(PACIFIC_TZ).date() - timedelta(days=7)).isoformat()
            end_date = (datetime.now(PACIFIC_TZ).date() + timedelta(days=7)).isoformat()

    discovered = discover_bay_area_games(start_date, end_date, home_only=True)
    new_count = 0
    updated_count = 0
    changelog = []

    for dg in discovered:
        # Match against existing games
        match, confidence = _best_match(
            {"home_team": dg["home_team"], "away_team": dg["away_team"], "date": dg["date_str"]},
            [{"home_team": g.get("home_team", ""), "away_team": g.get("away_team", ""), "date_str": g.get("date", "")} for g in games]
        )

        existing_game = None
        if match and confidence >= 0.6:
            for g in games:
                if (g.get("date") == match.get("date_str") and
                        _name_match_score(g.get("home_team", ""), match.get("home_team", "")) > 0.4 and
                        _name_match_score(g.get("away_team", ""), match.get("away_team", "")) > 0.4):
                    existing_game = g
                    break

        if existing_game:
            # Update existing game details
            mod = False
            if dg.get("is_completed") and existing_game.get("status") != "final":
                try:
                    existing_game["home_score"] = int(dg["home_score"])
                    existing_game["away_score"] = int(dg["away_score"])
                    existing_game["status"] = "final"
                    if dg.get("source_url") and not existing_game.get("recap_url"):
                        existing_game["recap_url"] = dg["source_url"]
                    mod = True
                except (ValueError, TypeError):
                    pass
            if dg.get("time_str") and dg["time_str"] != "TBD" and existing_game.get("time") in ["TBD", "", None]:
                existing_game["time"] = dg["time_str"]
                mod = True
            if mod:
                updated_count += 1
                summary = f"Updated existing game [{existing_game.get('id')}] {existing_game.get('away_team')} @ {existing_game.get('home_team')} ({existing_game.get('date')})"
                changelog.append(summary)
        else:
            # DISCOVERED NEW GAME — Ingest into Gazette
            ep_key = dg.get("endpoint_key", "nhl")
            defaults = _sport_defaults(ep_key, dg.get("season_type", 2))

            # Determine matching week
            target_week = None
            g_date = dg["date_str"]
            for w in weeks:
                w_start = w.get("start_date", "")
                w_end = w.get("end_date", "")
                if w_start <= g_date <= w_end:
                    target_week = w
                    break
            week_num = target_week.get("num", 1) if target_week else 1

            # Generate new sequential ID
            week_games = [g for g in games if g.get("week") == week_num]
            next_idx = len(week_games) + 1
            new_id = f"w{week_num}-{next_idx:02d}"

            is_completed = dg.get("is_completed", False)
            h_score = int(dg["home_score"]) if is_completed and dg.get("home_score") is not None else None
            a_score = int(dg["away_score"]) if is_completed and dg.get("away_score") is not None else None

            # Generate punchy editorial badge and context
            h_team = dg["home_team"]
            a_team = dg["away_team"]
            if "Sharks" in h_team:
                badge = f"🦈 Preseason Hockey: {a_team} at {h_team}" if "Preseason" in defaults["league"] else f"⭐ Pacific Division Clash: {a_team} vs Sharks"
                context_reason = f"Hockey returns to SAP Center as San Jose's dynamic young core tests their chemistry against {a_team}."
                insider_tips = "Diridon Station is right across Autumn Street from the arena — ride Caltrain or VTA Light Rail to skip parking. San Pedro Square Market is ideal for pregame dinner."
            elif "49ers" in h_team:
                badge = f"🏈 NFC Showdown: {a_team} at 49ers"
                context_reason = f"The 49ers host {a_team} at Levi's Stadium in a pivotal regular season clash."
                insider_tips = "Take the VTA Orange Line light rail directly to the Great America station outside Intel Gate A."
            else:
                badge = f"⭐ Local Showcase: {a_team} at {h_team}"
                context_reason = f"{h_team} host {a_team} in an exciting {defaults['league']} contest."
                insider_tips = f"Arrive early at {dg.get('venue') or defaults['venue']} for easy parking and concessions."

            result_summary = None
            if is_completed and h_score is not None and a_score is not None:
                winner = h_team if h_score > a_score else a_team
                loser = a_team if winner == h_team else h_team
                w_score = max(h_score, a_score)
                l_score = min(h_score, a_score)
                result_summary = f"{winner} secured an emphatic {w_score}-{l_score} victory over {loser} at {dg.get('venue') or defaults['venue']}."

            new_game = {
                "id": new_id,
                "week": week_num,
                "date": g_date,
                "day_of_week": dg.get("day_name") or datetime.strptime(g_date, "%Y-%m-%d").strftime("%A"),
                "time": dg.get("time_str") or "7:00 PM",
                "sport": defaults["sport"],
                "sport_icon": defaults["sport_icon"],
                "league": defaults["league"],
                "level": defaults["level"],
                "home_team": h_team,
                "away_team": a_team,
                "home_score": h_score,
                "away_score": a_score,
                "status": "final" if is_completed else "upcoming",
                "venue": dg.get("venue") or defaults["venue"],
                "city": dg.get("venue_city") or defaults["city"],
                "badge": badge,
                "context_reason": context_reason,
                "insider_tips": insider_tips,
                "importance": "high" if defaults["level"] == "Pro" else "standard",
                "ticket_text": defaults["ticket_text"],
                "ticket_url": defaults["ticket_url"],
                "recap_url": dg.get("source_url") or defaults["ticket_url"],
                "result_summary": result_summary,
                "is_cambrian": False,
                "is_south_bay": bool(defaults["is_south_bay"] or (dg.get("venue_city") in SOUTH_BAY_CITIES)),
                "tags": defaults["tags"],
                "weather": {
                    "temp": "68°F",
                    "cond": "Indoor Arena" if "Arena" in (dg.get("venue") or defaults["venue"]) else "Clear Evening",
                    "icon": "🏟️" if "Arena" in (dg.get("venue") or defaults["venue"]) else "🌙",
                    "attire": "Comfortable indoor layers",
                    "indoor": bool("Arena" in (dg.get("venue") or defaults["venue"]))
                }
            }

            games.append(new_game)
            new_count += 1
            summary = f"Discovered & ingested [{new_id}] {a_team} @ {h_team} ({g_date}) - {new_game['status'].upper()}"
            changelog.append(summary)
            log.info(f"✓ {summary}")

    return new_count, updated_count, changelog


def verify_all(games_list: list) -> None:
    """Iterate all games, verify each against ESPN, print a formatted report."""
    RESET   = "\033[0m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    RED     = "\033[31m"
    BOLD    = "\033[1m"
    CYAN    = "\033[36m"

    print()
    print(f"{BOLD}{'='*70}{RESET}")
    print(f"{BOLD}  Bay Area Sports Gazette — ESPN Verification Report{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")
    print()

    verified_count   = 0
    unmatched_count  = 0
    corrections_count = 0

    for game in games_list:
        gid    = game.get("id", "?")
        home   = game.get("home_team", "")
        away   = game.get("away_team", "")
        date_s = game.get("date", "")
        sport  = game.get("sport", "")
        league = game.get("league", "")

        label = f"[{gid}]  {away} @ {home}  ({date_s})  {sport}/{league}"
        print(f"{CYAN}{label}{RESET}")

        v = verify_game(game)

        if not v["match_found"]:
            unmatched_count += 1
            reason = v.get("notes", "No match.")
            print(f"  {YELLOW}⚠  UNVERIFIED — {reason}{RESET}")
        else:
            verified_count += 1
            pct = int(v["confidence"] * 100)
            url = v.get("source_url", "")
            if v["corrections"]:
                corrections_count += 1
                print(f"  {RED}✗  MATCH ({pct}% confidence) — CORRECTIONS NEEDED:{RESET}")
                for field, val in v["corrections"].items():
                    if field.startswith("_note"):
                        print(f"       ⚠  {val}")
                    else:
                        old_val = game.get(field, "<missing>")
                        print(f"       {field}: {old_val!r}  →  {val!r}")
                if url:
                    print(f"       source: {url}")
            else:
                print(f"  {GREEN}✓  VERIFIED ({pct}% confidence)  {url}{RESET}")

        print()

    print(f"{BOLD}{'='*70}{RESET}")
    print(f"  Total games:     {len(games_list)}")
    print(f"  Verified:        {GREEN}{verified_count}{RESET}")
    print(f"  Unmatched:       {YELLOW}{unmatched_count}{RESET}  (sport not in ESPN or no API data)")
    print(f"  Need correction: {RED}{corrections_count}{RESET}")
    print(f"{BOLD}{'='*70}{RESET}")
    print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from build_calendar import GAMES_DATA, WEEKS_META, save_data

    if "--verify" in sys.argv:
        verify_all(GAMES_DATA)
    elif "--discover" in sys.argv:
        today_iso = datetime.now(PACIFIC_TZ).date().isoformat()
        res = discover_bay_area_games(today_iso, today_iso)
        print(json.dumps(res, indent=2))
    elif "--sync" in sys.argv:
        new_cnt, upd_cnt, log_msgs = sync_schedule_for_window(GAMES_DATA, WEEKS_META)
        print(f"Sync complete: {new_cnt} new, {upd_cnt} updated.")
        if new_cnt > 0 or upd_cnt > 0:
            save_data(GAMES_DATA, WEEKS_META)
            print("Saved updated games to data/games.json")
    else:
        print("Usage:")
        print("  python3 schedule_fetcher.py --verify     # Verify existing games")
        print("  python3 schedule_fetcher.py --discover   # Discover games for today")
        print("  python3 schedule_fetcher.py --sync       # Discover and sync schedule window")
