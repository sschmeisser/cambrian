#!/usr/bin/env python3
"""
Bay Area & San Jose Sports Weekly Calendar
Clean Editorial 7-Day Calendar Grid with Mobile Ergonomic UX,
Rolling Scores, and Standalone HTML Generation.
"""

import json
import os
import team_logos
import league_standings
from constants import SOUTH_BAY_CITIES

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "games.json")
PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "public")

def _safe_json_for_script(data) -> str:
    """Serialize data to JSON safe for embedding inside a <script> block."""
    raw = json.dumps(data, ensure_ascii=False)
    # Prevent </script> from terminating the script tag
    raw = raw.replace('</', '<\\/')
    # Escape Unicode line terminators that break JS string literals
    raw = raw.replace('\u2028', '\\u2028')
    raw = raw.replace('\u2029', '\\u2029')
    return raw

def load_data():
    """Load games and weeks metadata from data/games.json."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            payload = json.load(f)
            return payload.get("games", []), payload.get("weeks", [])
    return [], []

def save_data(games, weeks):
    """Save games and weeks metadata atomically to data/games.json."""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    temp_file = DATA_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump({"weeks": weeks, "games": games}, f, indent=2, ensure_ascii=False)
    os.replace(temp_file, DATA_FILE)

# Module-level variables for backward compatibility
GAMES_DATA, WEEKS_META = load_data()

def reload_data():
    """Refresh module-level data if the JSON file changes."""
    global GAMES_DATA, WEEKS_META
    GAMES_DATA, WEEKS_META = load_data()
    return GAMES_DATA, WEEKS_META



def is_cambrian_game(g):
    """
    Identify local Cambrian Park neighborhood games:
    Branham High Bruins, Leigh High Longhorns, Westmont Stadium, San Jose City College Jaguar Stadium.
    """
    home = g.get("home_team", "")
    away = g.get("away_team", "")
    venue = g.get("venue", "")
    teams = f"{home} {away}"

    if "Branham" in teams or "Branham Stadium" in venue:
        return True
    if "Leigh" in teams:
        return True
    if "Westmont Stadium" in venue or "Westmont High" in teams:
        return True
    if "Jaguar Stadium" in venue or "San Jose City College" in teams or "SJCC" in venue:
        return True
    return False

def is_south_bay_game(g):
    """
    Identify South Bay games (cities: San Jose, Campbell, Santa Clara, Cupertino, Mountain View, Stanford).
    """
    city = g.get("city", "").strip()
    return city in SOUTH_BAY_CITIES

def _parse_time_hour(time_str):
    if not time_str:
        return 19.0
    parts = str(time_str).strip().split()
    if not parts:
        return 19.0
    hm = parts[0].split(':')
    try:
        h = int(hm[0])
        m = int(hm[1]) if len(hm) > 1 else 0
    except ValueError:
        return 19.0
    if len(parts) > 1 and parts[1].upper() == 'PM' and h != 12:
        h += 12
    elif len(parts) > 1 and parts[1].upper() == 'AM' and h == 12:
        h = 0
    return h + m / 60.0

def get_game_weather(g):
    """
    Generate realistic kickoff weather and attire recommendation for a game.
    Supports indoor arenas, heated pool, coastal breeze, east bay breeze, and outdoor games.
    """
    venue = g.get("venue", "")
    city = g.get("city", "")
    date_str = g.get("date", "")
    time_str = g.get("time", "7:00 PM")

    # 1. Indoor venues (SAP Center, Tech CU Arena, Leavey Center, Maples Pavilion, Chase Center)
    if "Tech CU Arena" in venue:
        return {
            "temp": "65°F",
            "cond": "Indoor Ice Arena",
            "icon": "⛸️",
            "attire": "Warm fleece or hoodie",
            "indoor": True
        }
    if "SAP Center" in venue:
        return {
            "temp": "68°F",
            "cond": "Indoor Arena",
            "icon": "🏟️",
            "attire": "Comfortable indoor layers",
            "indoor": True
        }
    if "Leavey Center" in venue:
        return {
            "temp": "68°F",
            "cond": "Indoor Arena",
            "icon": "🏟️",
            "attire": "Comfortable indoor layers",
            "indoor": True
        }
    if "Maples Pavilion" in venue:
        return {
            "temp": "69°F",
            "cond": "Indoor Pavilion",
            "icon": "🏟️",
            "attire": "Comfortable indoor layers",
            "indoor": True
        }
    if "Chase Center" in venue:
        return {
            "temp": "70°F",
            "cond": "Indoor Arena",
            "icon": "🏟️",
            "attire": "Comfortable indoor layers",
            "indoor": True
        }

    # 2. Heated pool (SRAC Aquatics Center)
    if "SRAC Aquatics Center" in venue:
        return {
            "temp": "76°F",
            "cond": "Heated Poolside",
            "icon": "🏊",
            "attire": "Casual poolside attire",
            "indoor": False
        }

    # 3. Coastal venues (Cardinale Stadium / Seaside Monterey)
    if "Cardinale Stadium" in venue or "Seaside" in city:
        return {
            "temp": "57°F",
            "cond": "Coastal Breeze",
            "icon": "🌊",
            "attire": "Windbreaker & warm layers",
            "indoor": False
        }

    # 4. Memorial Stadium / Berkeley
    if "Memorial Stadium" in venue or ("Berkeley" in city and "Memorial" in venue):
        return {
            "temp": "61°F",
            "cond": "East Bay Breeze",
            "icon": "🌤️" if _parse_time_hour(time_str) < 17.5 else "🌙",
            "attire": "Light jacket advised",
            "indoor": False
        }

    # Date and time parsing
    month = 9
    if date_str and "-" in date_str:
        try:
            month = int(date_str.split("-")[1])
        except ValueError:
            month = 9

    hour = _parse_time_hour(time_str)
    gid_num = sum(ord(c) for c in g.get("id", ""))

    # 5. Outdoor evening games (6:00 PM onwards)
    if hour >= 18.0:
        if month == 9:
            temp_val = 60 + (gid_num % 4)
            return {
                "temp": f"{temp_val}°F",
                "cond": "Clear Autumn Night",
                "icon": "🌙",
                "attire": "Light jacket advised",
                "indoor": False
            }
        else:
            temp_val = 53 + (gid_num % 6)
            return {
                "temp": f"{temp_val}°F",
                "cond": "Crisp Autumn Night",
                "icon": "🌙",
                "attire": "Warm jacket advised",
                "indoor": False
            }
    # Twilight games (5:00 PM - 5:59 PM)
    elif hour >= 17.0:
        if month == 9:
            temp_val = 69 + (gid_num % 3)
            return {
                "temp": f"{temp_val}°F",
                "cond": "Mild Twilight Sunset",
                "icon": "🌅",
                "attire": "Light layers advised",
                "indoor": False
            }
        else:
            temp_val = 62 + (gid_num % 3)
            return {
                "temp": f"{temp_val}°F",
                "cond": "Cool Autumn Dusk",
                "icon": "🌅",
                "attire": "Light jacket advised",
                "indoor": False
            }
    # 6. Outdoor afternoon games
    else:
        if month == 9:
            temp_val = 72 + (gid_num % 5)
            return {
                "temp": f"{temp_val}°F",
                "cond": "Sunny & Pleasant",
                "icon": "☀️",
                "attire": "Comfortable light layers",
                "indoor": False
            }
        else:
            temp_val = 68 + (gid_num % 5)
            return {
                "temp": f"{temp_val}°F",
                "cond": "Sunny & Crisp",
                "icon": "☀️",
                "attire": "Comfortable light layers",
                "indoor": False
            }

def normalize_games(games):
    normalized = []
    for g in games:
        item = dict(g)
        if "status" not in item:
            item["status"] = "upcoming"
        if item["status"] == "final":
            if "result_summary" not in item:
                item["result_summary"] = "Game concluded."
            if "recap_url" not in item:
                item["recap_url"] = item.get("ticket_url", "")
        # Attach verified team logos and colors
        item["home_logo"] = team_logos.get_team_logo(item.get("home_team", ""))
        item["away_logo"] = team_logos.get_team_logo(item.get("away_team", ""))
        item["home_colors"] = team_logos.get_team_colors(item.get("home_team", ""))
        item["away_colors"] = team_logos.get_team_colors(item.get("away_team", ""))
        # Attach verified league/division standings key
        item["standings_key"] = league_standings.classify_game(item)

        # Weather enrichment
        item["weather"] = g.get("weather") or get_game_weather(item)

        # Cambrian & South Bay localization
        item["is_cambrian"] = g.get("is_cambrian") if "is_cambrian" in g and g.get("is_cambrian") is not None else is_cambrian_game(item)
        item["is_south_bay"] = g.get("is_south_bay") if "is_south_bay" in g and g.get("is_south_bay") is not None else is_south_bay_game(item)

        # Ensure tags are updated with cambrian and south bay
        tags = list(item.get("tags", []))
        if item["is_cambrian"] and "cambrian" not in tags:
            tags.append("cambrian")
        if item["is_south_bay"] and "south bay" not in tags:
            tags.append("south bay")
        item["tags"] = tags

        normalized.append(item)
    return normalized

def get_standings_data():
    standings_db = league_standings.get_standings_db()
    st_data = {}
    for k, v in standings_db.items():
        v_copy = dict(v)
        v_copy['rows'] = [dict(r) for r in v['rows']]
        for r in v_copy['rows']:
            r['logo'] = team_logos.get_team_logo(r['team'])
        cross_copy = {}
        for team, cinfo in v.get('cross_division_opponents', {}).items():
            c_copy = dict(cinfo)
            c_copy['logo'] = team_logos.get_team_logo(team)
            cross_copy[team] = c_copy
        v_copy['cross_division_opponents'] = cross_copy
        st_data[k] = v_copy
    return st_data

def normalize_weeks(weeks):
    import datetime
    normalized = []
    today = datetime.date.today()
    today_iso = today.isoformat()
    for w in weeks:
        item = dict(w)
        days = item.get("days", [])
        if days:
            start_date = days[0]["date"]
            end_date = days[-1]["date"]
            item["start_date"] = start_date
            item["end_date"] = end_date
            try:
                s_d = datetime.date.fromisoformat(start_date)
                e_d = datetime.date.fromisoformat(end_date)
                s_fmt = s_d.strftime("%b %d").replace(" 0", " ")
                if s_d.month == e_d.month:
                    item["short_dates"] = f"{s_fmt} – {e_d.day}"
                else:
                    e_fmt = e_d.strftime("%b %d").replace(" 0", " ")
                    item["short_dates"] = f"{s_fmt} – {e_fmt}"
            except Exception:
                item["short_dates"] = item.get("dates", "").split(",")[0]

        start_d_str = item.get("start_date", "")
        end_d_str = item.get("end_date", "")
        item["is_past"] = bool(end_d_str and end_d_str < today_iso)
        item["is_current"] = bool(start_d_str and end_d_str and start_d_str <= today_iso <= end_d_str)

        # Label: continuous rolling week without "Week 1", "Week 2", "Last Week"
        short = item.get("short_dates") or item.get("dates", "").split(",")[0]
        if item["is_current"]:
            item["label"] = f"This Week ({short})"
        else:
            item["label"] = short

        normalized.append(item)
    return normalized

CACHE_RETENTION_WEEKS = 52

def prune_expired_cache(games, weeks, retention_weeks=CACHE_RETENTION_WEEKS, reference_date=None):
    """
    Enforce 52-week cache cliff:
    - Retain up to 52 past weeks from reference date (default: today).
    - Older weeks and games roll off cleanly.
    """
    import datetime
    if not reference_date:
        ref_dt = datetime.date.today()
    elif isinstance(reference_date, str):
        ref_dt = datetime.date.fromisoformat(reference_date)
    else:
        ref_dt = reference_date

    cutoff_date = ref_dt - datetime.timedelta(weeks=retention_weeks)
    cutoff_iso = cutoff_date.isoformat()

    retained_weeks = []
    for w in weeks:
        end_d = w.get("end_date")
        if not end_d and w.get("days"):
            end_d = w["days"][-1]["date"]
        if not end_d or end_d >= cutoff_iso:
            retained_weeks.append(w)

    retained_week_nums = set(w.get("num") for w in retained_weeks)
    retained_games = [
        g for g in games
        if g.get("date", "9999-99-99") >= cutoff_iso and (g.get("week") is None or g.get("week") in retained_week_nums)
    ]
    return retained_games, retained_weeks

def generate_html():
    reload_data()
    active_games, active_weeks = prune_expired_cache(GAMES_DATA, WEEKS_META)
    normalized_games = normalize_games(active_games)
    normalized_weeks = normalize_weeks(active_weeks)
    games_str = _safe_json_for_script(normalized_games)
    weeks_str = _safe_json_for_script(normalized_weeks)
    standings_str = _safe_json_for_script(get_standings_data())

    tmpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calendar_template.html")
    with open(tmpl_path, "r", encoding="utf-8") as f:
        tmpl = f.read()

    rendered = (tmpl.replace("__GAMES_JSON__", games_str)
                    .replace("__WEEKS_JSON__", weeks_str)
                    .replace("__STANDINGS_JSON__", standings_str))

    out_path = os.path.join(PUBLIC_DIR, "sports_calendar.html")
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"Generated calendar: {out_path}")

    index_path = os.path.join(PUBLIC_DIR, "index.html")
    if os.path.islink(index_path):
        os.unlink(index_path)
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"Synchronized index: {index_path}")

    return out_path

if __name__ == "__main__":
    generate_html()
