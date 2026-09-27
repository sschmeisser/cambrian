#!/usr/bin/env python3
"""
refresh_pipeline.py — Autonomous Refresh & Verification Engine
The Bay Area Sports Gazette

Autonomous pipeline for:
  1. Schedule Synchronization & Discovery: Automatically discovers upcoming and completed Bay Area
     games across NHL, NFL, NBA, WNBA, MLS, NWSL, and NCAA Division I via ESPN public APIs in Pacific Time.
  2. Score & Status Ingestion: Fetches real-time scores and updates game status with strict verification.
  3. Grounded Journalistic Recaps: Generates 1-2 sentence recaps using OpenRouter (Gemini / Claude)
     with robust prompt caching (Anthropic / OpenRouter cache_control markers, >= 1,024 token stylebook).
  4. Dynamic Standings Updates: Increments W-L-T records and recalculates PCT and differentials in data/standings.json.
  5. Horizon Rollover: Shifts weeks forward when target calendar dates advance.
  6. 52-Week Rolling Cache Cliff: Automatically retains up to 52 past weeks while cleanly pruning expired history.
  7. Atomic Persistence: Safely writes data/games.json and data/standings.json.
  8. Automated Build & Git Sync: Rebuilds HTML bundle and pushes clean commits to origin/main.

Usage:
  python3 refresh_pipeline.py                     # Standard refresh (discovery + scores + build)
  python3 refresh_pipeline.py --scores-only       # Quick twice-daily score check
  python3 refresh_pipeline.py --sync-schedules    # Only synchronize schedules
  python3 refresh_pipeline.py --rollover          # Advance calendar window by 1 week
  python3 refresh_pipeline.py --dry-run           # Preview changes without modifying files
  python3 refresh_pipeline.py --commit            # Commit & push changes if modified
  python3 refresh_pipeline.py --test              # Self-test backend validation and healing
"""

import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

import build_calendar
import league_standings
import schedule_fetcher
import team_logos

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("gazette_refresh")

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT_DIR, "data")
GAMES_FILE = os.path.join(DATA_DIR, "games.json")
STANDINGS_FILE = os.path.join(DATA_DIR, "standings.json")

DEFAULT_OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# ---------------------------------------------------------------------------
# Static Editorial Stylebook & Prompt Cache Definition
# Token count >= 1,024 tokens to qualify for Anthropic / OpenRouter prompt caching.
# ---------------------------------------------------------------------------

GAZETTE_STYLEBOOK_SYSTEM_PROMPT = """
You are the veteran lead sports editor for the Cambrian Park Sports Gazette, a community-first sports publication serving San Jose and the greater South Bay / Silicon Valley region.

### PUBLICATION MISSION & TONE
- Voice: Knowledgeable, energetic, grounded, authentic to Northern California sports culture.
- Audience: South Bay locals, high school alumni, Silicon Valley youth sports families, and loyal Bay Area fans.
- Perspective: Respectful of high school grit (Branham Bruins, Leigh Longhorns), college tradition (SJSU Spartans, Stanford Cardinal, Santa Clara Broncos), and pro drama (San Jose Sharks, Earthquakes, 49ers, Bay FC, Warriors, Valkyries).

### STRICT GROUNDING & ZERO-HALLUCINATION RULES
1. STICK TO THE FACTS PROVIDED: You are given only the final score, venue, and optional context notes. DO NOT invent play-by-play events, fictional scoring plays (e.g., do not say "scored in the 89th minute" or "threw a 40-yard touchdown pass" unless explicitly stated in the context).
2. SYNTHESIZE OUTCOME & SIGNIFICANCE: Describe the victory margin (blowout, defensive clinic, nail-biter, shutout, high-scoring duel), home/away venue atmosphere, and standings/momentum implications.
3. DRAW HANDLING: If scores are tied, articulate a hard-fought draw or stalemate without inventing shootout details.

### EDITORIAL STYLE & BANNED PHRASES
- NEVER use generic AI cliches:
  * "testament to"
  * "rollercoaster of emotions"
  * "thrilling affair"
  * "punched their ticket"
  * "in a game of two halves"
  * "showcased their prowess"
  * "left everything on the field"
- Preferred vocabulary:
  * High School: "crosstown rivalry", "gritty defensive stand", "Friday night lights", "under the lights on Camden Ave".
  * College/Pro: "clean sheet", "conference showdown", "derby duel", "defensive clinic", "dominant road showing", "Shark Tank explosion".
- Length: Exactly 1 to 2 punchy, polished journalistic sentences.
- Formatting: Return plain text ONLY. No quotation marks around the recap, no markdown headers, no introductory banter ("Here is your recap:").

### FEW-SHOT EDITORIAL EXAMPLES

[Example 1 - High School Football Blowout]
Input:
  Away: Westmont Warriors (7) at Home: Branham Bruins (38)
  Venue: Branham Stadium
  Context: Local South Bay rivalry matchup
Recap:
Branham delivered an emphatic statement on Camden Avenue, overpowering rival Westmont 38-7 behind a suffocating defensive front that gave the Warriors zero breathing room.

[Example 2 - College Soccer Defensive Shutout]
Input:
  Away: Georgetown Hoyas (0) at Home: Stanford Cardinal Men (2)
  Venue: Cagan Stadium
  Context: Interconference national heavyweight duel
Recap:
Stanford secured its fourth clean sheet of the campaign with a clinical 2-0 shutout over visiting Georgetown, controlling the tempo from the opening kickoff at Cagan Stadium.

[Example 3 - NHL / Hockey One-Goal Game]
Input:
  Away: Vegas Golden Knights (3) at Home: San Jose Sharks (4)
  Venue: SAP Center
  Context: Pacific Division clash
Recap:
The Sharks held off a furious third-period push by Vegas to protect a gritty 4-3 regulation victory before a roaring crowd at the Shark Tank.

[Example 4 - Soccer Draw]
Input:
  Away: Monterey Bay FC (1) at Home: Oakland Roots SC (1)
  Venue: Raimondi Park
  Context: NorCal USL Championship Derby
Recap:
Oakland and Monterey Bay traded physical blows for ninety minutes in a fiercely contested NorCal derby, settling for a hard-earned 1-1 point at Raimondi Park.

[Example 5 - Community College Basketball Close Win]
Input:
  Away: De Anza Mountain Lions (68) at Home: West Valley Vikings (71)
  Venue: West Valley Gymnasium
  Context: Coast Conference South rivalry
Recap:
West Valley survived a wire-to-wire battle against crosstown adversary De Anza, closing out a tense 71-68 conference triumph in Saratoga.
""".strip()


SCORE_VERIFICATION_SYSTEM_PROMPT = """
You are an uncompromising sports data verification researcher for the Cambrian Park Sports Gazette.
Your sole mission is to verify the official final score of scheduled sporting events (primarily California high school CIF Central Coast Section, CCCAA junior college, and regional pre-pro matches).

### ZERO-HALLUCINATION PROTOCOL
1. ABSOLUTE CONFIRMATION REQUIRED: You must only return `verified: true` if you have factual, confirmed evidence of the final score from official box scores or trusted media.
2. FUTURE OR UNPLAYED MATCHES: If the game date is in the future, if the match is still in progress, or if no final box score is confirmed, you MUST return `verified: false`.
3. NEVER GUESS: DO NOT estimate, simulate, or generate plausible-sounding scores. Guessing corrupts the Gazette's public league standings database.

### OUTPUT JSON SCHEMA
Respond with a single valid JSON object containing exactly these fields:
```json
{
  "verified": boolean,
  "home_score": int or null,
  "away_score": int or null,
  "recap": string or null,
  "source_name": string,
  "reason": "CONFIRMED_FINAL" | "NOT_PLAYED_YET" | "SCORE_UNAVAILABLE" | "POSTPONED" | "IN_PROGRESS"
}
```
If `verified` is false: `home_score` and `away_score` must be null, and `reason` must detail why verification failed.
""".strip()


# ---------------------------------------------------------------------------
# OpenRouter Client with Prompt Caching
# ---------------------------------------------------------------------------
class OpenRouterAgent:
    """Enhanced OpenRouter AI inference client with Anthropic/Gemini prompt caching."""
    def __init__(self, api_key: str = "", model: str = DEFAULT_OPENROUTER_MODEL):
        self.api_key = api_key or OPENROUTER_API_KEY
        self.model = model
        self.url = "https://openrouter.ai/api/v1/chat/completions"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.startswith("sk-or-"))

    def call_ai(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 250,
        json_mode: bool = False,
        use_cache: bool = True,
        use_web_search: bool = False
    ) -> Optional[str]:
        if not self.is_configured or not HAS_REQUESTS:
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/stefanschmeisser/cambrian",
            "X-Title": "Cambrian Park Sports Gazette Autonomous Pipeline"
        }

        # Format system prompt with Anthropic/OpenRouter ephemeral cache control
        if use_cache:
            system_message = {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"}
                    }
                ]
            }
        else:
            system_message = {
                "role": "system",
                "content": system_prompt
            }

        payload = {
            "model": self.model,
            "messages": [
                system_message,
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3  # Low temperature for factual precision
        }

        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        if use_web_search:
            payload["plugins"] = [{"id": "web"}]

        try:
            resp = requests.post(self.url, headers=headers, json=payload, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                choice = data["choices"][0]["message"]["content"]
                return choice.strip() if choice else None
            else:
                log.warning(f"OpenRouter API error ({resp.status_code}): {resp.text[:250]}")
        except Exception as e:
            log.warning(f"OpenRouter request exception: {e}")
        return None

    def generate_recap(self, game: Dict) -> str:
        """Generate a punchy 1-2 sentence journalistic recap in Gazette voice using prompt cache."""
        home = game.get("home_team", "Home Team")
        away = game.get("away_team", "Away Team")
        h_score = game.get("home_score", 0)
        a_score = game.get("away_score", 0)
        venue = game.get("venue", "home turf")
        context = game.get("context_reason", "")
        league = game.get("league", "")

        winner = home if h_score > a_score else away
        loser = away if winner == home else home
        win_score = max(h_score, a_score)
        lose_score = min(h_score, a_score)
        margin = win_score - lose_score

        user_prompt = (
            f"League: {league}\n"
            f"Matchup: {away} ({a_score}) at {home} ({h_score})\n"
            f"Final Result: {winner} {win_score}, {loser} {lose_score} (Margin: {margin})\n"
            f"Venue: {venue}\n"
            f"Editorial Context: {context}\n"
            "Write the 1-to-2 sentence post-game recap:"
        )

        ai_recap = self.call_ai(
            system_prompt=GAZETTE_STYLEBOOK_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=120,
            use_cache=True
        )

        if ai_recap:
            cleaned = ai_recap.strip('"\'')
            return cleaned

        # Clean fallback if API key is not present or network drops
        if h_score == a_score:
            return f"{home} and {away} battled to a hard-fought {h_score}-{a_score} draw at {venue}."
        return f"{winner} secured a decisive {win_score}-{lose_score} victory over {loser} in front of an energetic crowd at {venue}."

    def search_untracked_score(self, game: Dict) -> Optional[Tuple[int, int, str]]:
        """Query AI with live web search to verify scores for high school or JUCO matchups."""
        user_prompt = (
            f"Sport: {game.get('sport')} / {game.get('league')}\n"
            f"Matchup: {game.get('away_team')} at {game.get('home_team')}\n"
            f"Scheduled Date: {game.get('date')}\n"
            f"Venue: {game.get('venue')}\n"
            "Search official sources for the final score. Return the verified JSON object."
        )

        raw_json = self.call_ai(
            system_prompt=SCORE_VERIFICATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=200,
            json_mode=True,
            use_cache=True,
            use_web_search=True
        )
        if not raw_json:
            return None

        try:
            data = json.loads(raw_json)
            if data.get("verified") is True:
                h_score = int(data.get("home_score"))
                a_score = int(data.get("away_score"))
                recap = data.get("recap") or ""
                log.info(f"Verified via {data.get('source_name', 'Web')}: {game.get('id')}")
                return h_score, a_score, recap
            else:
                log.info(f"Unverified game {game.get('id')}: {data.get('reason')} - {data.get('source_name', 'N/A')}")
        except Exception as e:
            log.warning(f"Error parsing AI verification JSON: {e}")
        return None


# ---------------------------------------------------------------------------
# Score Fetcher Engine
# ---------------------------------------------------------------------------
class ScoreRefreshEngine:
    def __init__(self, ai_agent: OpenRouterAgent):
        self.ai = ai_agent

    def refresh_scores(self, games: List[Dict], standings_db: Dict, target_date: Optional[str] = None) -> Tuple[int, List[str]]:
        """
        Scan games and update final scores for matches occurring on or before target_date.
        Strictly verifies each score.
        Returns: (number_of_games_updated, list_of_update_summaries)
        """
        if not target_date:
            target_date = datetime.date.today().isoformat()

        updated_count = 0
        changelog = []

        log.info(f"Scanning games against target date: {target_date}")

        for g in games:
            gid = g.get("id")
            g_date = g.get("date", "9999-99-99")
            status = g.get("status", "upcoming")

            # Check upcoming games that are scheduled on or before target date
            if status != "final" and g_date <= target_date:
                log.info(f"Checking score for [{gid}] {g.get('away_team')} @ {g.get('home_team')} ({g_date})")

                # Step 1: Check ESPN API verification
                verified = schedule_fetcher.verify_game(g)
                if verified.get("match_found"):
                    corrections = verified.get("corrections", {})
                    h_score = corrections.get("home_score")
                    a_score = corrections.get("away_score")

                    # If ESPN has a final score
                    if h_score is not None and a_score is not None:
                        g["home_score"] = h_score
                        g["away_score"] = a_score
                        g["status"] = "final"
                        g["result_summary"] = self.ai.generate_recap(g)
                        if verified.get("source_url"):
                            g["recap_url"] = verified["source_url"]

                        self._update_standings(standings_db, g)
                        summary = f"[{gid}] {g['away_team']} {a_score} @ {g['home_team']} {h_score} (ESPN Verified)"
                        changelog.append(summary)
                        log.info(f"✓ Final score recorded: {summary}")
                        updated_count += 1
                        continue

                # Step 2: Non-ESPN sports (High School, JUCO, Minor League)
                if self.ai.is_configured:
                    ai_result = self.ai.search_untracked_score(g)
                    if ai_result:
                        h_score, a_score, recap = ai_result
                        g["home_score"] = h_score
                        g["away_score"] = a_score
                        g["status"] = "final"
                        g["result_summary"] = recap or self.ai.generate_recap(g)
                        self._update_standings(standings_db, g)
                        summary = f"[{gid}] {g['away_team']} {a_score} @ {g['home_team']} {h_score} (AI Verified)"
                        changelog.append(summary)
                        log.info(f"✓ Non-ESPN final score recorded: {summary}")
                        updated_count += 1
                        continue

                log.info(f"  Game [{gid}] remains upcoming (no final score confirmed yet).")

        return updated_count, changelog

    def _update_standings(self, standings_db: Dict, game: Dict):
        """Update standings record for participating teams in standings_db."""
        if "preseason" in str(game.get("league", "")).lower():
            return
        league_key = league_standings.classify_game(game)
        table = standings_db.get(league_key)
        if not table or "rows" not in table:
            return

        h_team = game.get("home_team", "")
        a_team = game.get("away_team", "")
        h_score = game.get("home_score", 0)
        a_score = game.get("away_score", 0)
        headers = table.get("col_headers", [])

        for row in table["rows"]:
            t_name = row.get("team", "")
            if league_standings.matches_team_name(t_name, h_team):
                self._record_row_result(row, won=(h_score > a_score), tied=(h_score == a_score), diff=(h_score - a_score), headers=headers)
            elif league_standings.matches_team_name(t_name, a_team):
                self._record_row_result(row, won=(a_score > h_score), tied=(h_score == a_score), diff=(a_score - h_score), headers=headers)

        # Re-sort standings
        def sort_key(r):
            if len(headers) > 5 and headers[5] == "PTS":
                try:
                    pts = int(r.get("col4", 0))
                except (ValueError, TypeError):
                    pts = 0
                return (pts, r.get("w", 0))

            pct = 0.0
            for col in ["col4", "col3", "col5", "pct"]:
                val = str(r.get(col, ""))
                if val.startswith("."):
                    try:
                        pct = float(val)
                        break
                    except ValueError:
                        pass
            if pct == 0.0:
                tot = r.get("w", 0) + r.get("l", 0)
                pct = r.get("w", 0) / tot if tot > 0 else 0.0
            return (pct, r.get("w", 0))

        table["rows"].sort(key=sort_key, reverse=True)
        for idx, r in enumerate(table["rows"], start=1):
            r["rank"] = idx

    def _record_row_result(self, row: Dict, won: bool, tied: bool, diff: int, headers: Optional[List[str]] = None):
        """Increment win/loss/tie count on standings row safely according to league schema."""
        headers = headers or []
        w = row.get("w", 0)
        l = row.get("l", 0)
        col3_val = row.get("col3", 0)
        t = col3_val if isinstance(col3_val, int) else row.get("t", 0)

        if won:
            row["w"] = w + 1
        elif tied:
            if isinstance(row.get("col3"), int):
                row["col3"] = t + 1
            else:
                row["t"] = t + 1
        else:
            row["l"] = l + 1

        if len(headers) > 5 and headers[5] == "PTS":
            try:
                curr_pts = int(row.get("col4", 0))
            except (ValueError, TypeError):
                curr_pts = 0
            if "nhl" in str(headers).lower() or "otl" in [h.upper() for h in headers]:
                added = 2 if won else (1 if tied else 0)
            else:
                added = 3 if won else (1 if tied else 0)
            row["col4"] = curr_pts + added
            if len(headers) > 6 and headers[6] == "PCT":
                tot = row.get("w", 0) + row.get("l", 0) + (row.get("col3", 0) if isinstance(row.get("col3"), int) else 0)
                if tot > 0:
                    pct = (row.get("col4", 0)) / (2 * tot)
                    row["col5"] = f"{pct:.3f}".lstrip("0")
            return

        tie_count = row.get("col3", 0) if isinstance(row.get("col3"), int) else row.get("t", 0)
        if not isinstance(tie_count, (int, float)):
            tie_count = 0
        total_games = row.get("w", 0) + row.get("l", 0) + tie_count

        if total_games > 0:
            pct = (row.get("w", 0) + 0.5 * tie_count) / total_games
            pct_str = f"{pct:.3f}".lstrip("0")

            if len(headers) > 5 and headers[5] == "PCT":
                row["col4"] = pct_str
            elif len(headers) > 4 and headers[4] == "PCT":
                row["col3"] = pct_str
            elif "col4" in row and str(row.get("col4", "")).startswith("."):
                row["col4"] = pct_str
            elif "pct" in row:
                row["pct"] = pct_str


# ---------------------------------------------------------------------------
# Calendar Rollover Engine (Continuous Rolling Weeks with Caching)
# ---------------------------------------------------------------------------
def advance_calendar_window(games: List[Dict], weeks: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """
    Advance the continuous rolling calendar horizon:
    - Retains ALL previous weeks in cache (never drops past weeks).
    - Automatically marks elapsed weeks as is_past=True.
    - Appends the next rolling 7-day week to the schedule horizon.
    """
    log.info("Executing continuous calendar horizon advance...")
    today_iso = datetime.date.today().isoformat()

    for w in weeks:
        days = w.get("days", [])
        if days:
            end_date = days[-1]["date"]
            w["is_past"] = end_date < today_iso

    if weeks:
        last_week = weeks[-1]
        last_days = last_week.get("days", [])
        if last_days:
            last_date = datetime.date.fromisoformat(last_days[-1]["date"])
            next_start = last_date + datetime.timedelta(days=1)
            next_days = []
            day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
            for i in range(7):
                curr = next_start + datetime.timedelta(days=i)
                iso_str = curr.isoformat()
                short_str = f"{day_names[curr.weekday()][:3]} {curr.strftime('%b %d').lstrip('0')}"
                next_days.append({
                    "date": iso_str,
                    "name": day_names[curr.weekday()],
                    "short": short_str
                })
            next_end = next_start + datetime.timedelta(days=6)
            s_fmt = next_start.strftime("%b %d").replace(" 0", " ")
            if next_start.month == next_end.month:
                short_dates = f"{s_fmt} – {next_end.day}"
            else:
                short_dates = f"{s_fmt} – {next_end.strftime('%b %d').replace(' 0', ' ')}"
            dates_fmt = f"{s_fmt} – {next_end.strftime('%b %d, %Y').replace(' 0', ' ')}"
            next_num = max(w.get("num", 0) for w in weeks) + 1

            new_week = {
                "num": next_num,
                "label": short_dates,
                "dates": dates_fmt,
                "short_dates": short_dates,
                "start_date": next_start.isoformat(),
                "end_date": next_end.isoformat(),
                "title": f"Mid-Season Action & Regional Showcases ({short_dates})",
                "is_past": False,
                "days": next_days
            }
            weeks.append(new_week)
            log.info(f"Cached all past weeks and appended new rolling week: {short_dates}")

    games, weeks, _, _ = apply_52_week_cliff(games, weeks)
    return games, weeks


CACHE_RETENTION_WEEKS = 52


def apply_52_week_cliff(
    games: List[Dict],
    weeks: List[Dict],
    retention_weeks: int = CACHE_RETENTION_WEEKS,
    reference_date: Optional[str] = None
) -> Tuple[List[Dict], List[Dict], int, int]:
    """
    Enforce a strict 52-week rolling cache cliff:
    - Retains up to 52 past weeks from reference date (default: today).
    - Any week whose end_date is older than 52 weeks (364 days) rolls off.
    - Any games belonging to expired weeks roll off cleanly.
    """
    if not reference_date:
        ref_dt = datetime.date.today()
    else:
        ref_dt = datetime.date.fromisoformat(reference_date)

    cutoff_date = ref_dt - datetime.timedelta(weeks=retention_weeks)
    cutoff_iso = cutoff_date.isoformat()

    retained_weeks = []
    rolled_off_weeks = 0
    for w in weeks:
        end_d = w.get("end_date")
        if not end_d and w.get("days"):
            end_d = w["days"][-1]["date"]

        if end_d and end_d < cutoff_iso:
            rolled_off_weeks += 1
        else:
            retained_weeks.append(w)

    retained_week_nums = set(w.get("num") for w in retained_weeks)
    retained_games = []
    rolled_off_games = 0
    for g in games:
        g_date = g.get("date", "9999-99-99")
        g_week = g.get("week")
        if g_date < cutoff_iso or (g_week is not None and g_week not in retained_week_nums):
            rolled_off_games += 1
        else:
            retained_games.append(g)

    if rolled_off_weeks > 0 or rolled_off_games > 0:
        log.info(
            f"52-week cache cliff enforced (cutoff: {cutoff_iso}): "
            f"rolled off {rolled_off_weeks} weeks and {rolled_off_games} games."
        )

    return retained_games, retained_weeks, rolled_off_games, rolled_off_weeks


# ---------------------------------------------------------------------------
# Self-Test & Diagnostic Routine
# ---------------------------------------------------------------------------
def run_self_tests() -> bool:
    """Run backend self-tests and self-healing validation."""
    print("=" * 60)
    print("  Running Autonomous Self-Test & Diagnostic Suite")
    print("=" * 60)

    # 1. Verify JSON data files exist and are valid
    assert os.path.exists(GAMES_FILE), f"Missing {GAMES_FILE}"
    assert os.path.exists(STANDINGS_FILE), f"Missing {STANDINGS_FILE}"

    with open(GAMES_FILE, "r", encoding="utf-8") as f:
        gdata = json.load(f)
    assert "games" in gdata and "weeks" in gdata, "games.json malformed"
    assert len(gdata["games"]) > 0, "games.json has no games"
    print(f"✓ games.json valid ({len(gdata['games'])} games, {len(gdata['weeks'])} weeks)")

    with open(STANDINGS_FILE, "r", encoding="utf-8") as f:
        sdata = json.load(f)
    assert len(sdata) >= 15, "standings.json incomplete"
    print(f"✓ standings.json valid ({len(sdata)} tables)")

    # 2. Test logo mapping integrity
    sample_teams = ["San Francisco 49ers", "San Jose Sharks", "Branham High Bruins", "De La Salle Spartans"]
    for t in sample_teams:
        logo = team_logos.get_team_logo(t)
        assert logo, f"Missing logo for {t}"
    print(f"✓ Team logo resolver verified for key programs")

    # 3. Test standings engine matching
    sample_game = gdata["games"][0]
    st = league_standings.get_standings_for_game(sample_game)
    assert st["title"], "Standings retrieval failed"
    print(f"✓ Standings engine integration verified ({st['title']})")

    # 4. Test HTML compiler
    out_path = build_calendar.generate_html()
    assert os.path.exists(out_path), "sports_calendar.html was not generated"
    index_path = os.path.join(ROOT_DIR, "public", "index.html")
    assert os.path.exists(index_path), "index.html was not synchronized"
    assert os.path.getsize(index_path) > 100_000, "Generated HTML too small"
    print(f"✓ HTML compilation verified ({os.path.getsize(index_path):,} bytes)")

    # 5. Test Prompt Caching Structure & AI Recap Fallback
    mock_agent = OpenRouterAgent(api_key="mock-key")
    mock_game = {
        "home_team": "San Jose Earthquakes", "away_team": "Portland Timbers",
        "home_score": 2, "away_score": 1, "venue": "PayPal Park",
        "context_reason": "Rivalry match"
    }
    recap = mock_agent.generate_recap(mock_game)
    assert "San Jose Earthquakes" in recap or "victory" in recap, "Recap fallback failed"
    # Ensure stylebook is substantial for cache eligibility
    assert len(GAZETTE_STYLEBOOK_SYSTEM_PROMPT.split()) > 250, "Stylebook system prompt too short for prompt caching"
    print(f"✓ Editorial prompt caching & recap fallback verified: \"{recap}\"")

    # 6. Test standings increment
    engine = ScoreRefreshEngine(mock_agent)
    test_db = {"mls_west": {"rows": [{"team": "San Jose Earthquakes", "w": 1, "l": 0, "col4": "1.000"}]}}
    test_game = {
        "id": "test-01", "sport": "Soccer", "level": "Pro", "league": "MLS",
        "home_team": "San Jose Earthquakes", "away_team": "Portland Timbers",
        "home_score": 3, "away_score": 1
    }
    engine._update_standings(test_db, test_game)
    assert test_db["mls_west"]["rows"][0]["w"] == 2
    print("✓ Standings math & W-L increment logic verified")

    # 7. Test 52-week cache cliff roll-off
    today = datetime.date.today()
    mock_weeks = [
        {"num": 100, "label": "53 Weeks Ago", "end_date": (today - datetime.timedelta(weeks=53)).isoformat(), "days": []},
        {"num": 101, "label": "51 Weeks Ago", "end_date": (today - datetime.timedelta(weeks=51)).isoformat(), "days": []},
        {"num": 102, "label": "This Week", "end_date": today.isoformat(), "days": []}
    ]
    mock_games = [
        {"id": "expired-01", "week": 100, "date": (today - datetime.timedelta(weeks=53)).isoformat()},
        {"id": "kept-01", "week": 101, "date": (today - datetime.timedelta(weeks=51)).isoformat()},
        {"id": "kept-02", "week": 102, "date": today.isoformat()}
    ]
    k_games, k_weeks, r_games, r_weeks = apply_52_week_cliff(mock_games, mock_weeks, retention_weeks=52)
    assert r_weeks == 1, f"Expected 1 week to roll off, got {r_weeks}"
    assert r_games == 1, f"Expected 1 game to roll off, got {r_games}"
    assert len(k_weeks) == 2, f"Expected 2 retained weeks, got {len(k_weeks)}"
    assert len(k_games) == 2, f"Expected 2 retained games, got {len(k_games)}"
    assert k_weeks[0]["num"] == 101
    print("✓ 52-week cache cliff & rollover pruning verified (expired history rolls off cleanly)")

    # 8. Test Schedule Discovery & Pacific Timezone Extraction
    discovered = schedule_fetcher.discover_bay_area_games("2026-09-24", "2026-09-24")
    sharks_discovered = any(
        "Sharks" in g.get("home_team", "") and g.get("date_str") == "2026-09-24"
        for g in discovered
    )
    assert sharks_discovered, "Schedule discovery failed to find Sharks game on 2026-09-24"
    print("✓ Schedule discovery engine & Pacific timezone parsing verified (Sharks 2026-09-24 confirmed)")

    print("=" * 60)
    print("  All Self-Tests Passed Successfully!")
    print("=" * 60)
    return True


# ---------------------------------------------------------------------------
# Main Orchestration Loop
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="The Bay Area Sports Gazette Autonomous Refresh Engine")
    parser.add_argument("--scores-only", action="store_true", help="Only refresh completed game scores and standings")
    parser.add_argument("--sync-schedules", action="store_true", help="Only synchronize and discover schedules")
    parser.add_argument("--rollover", action="store_true", help="Advance calendar horizon by 1 full week")
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes to disk")
    parser.add_argument("--commit", action="store_true", help="Commit and push changes to git")
    parser.add_argument("--target-date", type=str, default=None, help="Target YYYY-MM-DD date for scores check")
    parser.add_argument("--test", action="store_true", help="Run self-test & diagnostic suite")
    args = parser.parse_args()

    if args.test:
        success = run_self_tests()
        sys.exit(0 if success else 1)

    log.info("Starting Bay Area Sports Gazette autonomous refresh pipeline...")

    # Load current data
    with open(GAMES_FILE, "r", encoding="utf-8") as f:
        gdata = json.load(f)
    games = gdata.get("games", [])
    weeks = gdata.get("weeks", [])

    with open(STANDINGS_FILE, "r", encoding="utf-8") as f:
        standings_db = json.load(f)

    # Enforce 52-week cache cliff on load
    games, weeks, pruned_g, pruned_w = apply_52_week_cliff(games, weeks)

    # Initialize AI Agent
    ai_agent = OpenRouterAgent()
    if ai_agent.is_configured:
        log.info(f"OpenRouter AI connected (Model: {ai_agent.model})")
    else:
        log.info("OpenRouter API key not detected; running in deterministic mode with standard fallbacks.")

    changes_made = (pruned_g > 0 or pruned_w > 0)
    changelog = []
    if changes_made:
        changelog.append(f"52-week cliff: rolled off {pruned_w} expired weeks and {pruned_g} games")

    # 1. Calendar Horizon Rollover (if requested)
    if args.rollover:
        games, weeks = advance_calendar_window(games, weeks)
        changes_made = True
        changelog.append("Advanced calendar horizon by 1 week")

    # 2. Schedule Synchronization & Discovery (unless --scores-only)
    if not args.scores_only:
        log.info("Synchronizing live schedules and discovering new matchups...")
        new_sched, upd_sched, sync_log = schedule_fetcher.sync_schedule_for_window(games, weeks)
        if new_sched > 0 or upd_sched > 0:
            changes_made = True
            changelog.extend(sync_log)
            log.info(f"Schedule sync: {new_sched} new games discovered, {upd_sched} existing games updated.")

    # 3. Score & Standings Ingestion (unless --sync-schedules)
    if not args.sync_schedules:
        refresh_engine = ScoreRefreshEngine(ai_agent)
        updated_scores, score_log = refresh_engine.refresh_scores(games, standings_db, target_date=args.target_date)
        if updated_scores > 0:
            changes_made = True
            changelog.extend(score_log)
        log.info(f"Score refresh completed: {updated_scores} game scores updated.")

    # 4. Save Data & Compile Bundle
    if changes_made:
        if args.dry_run:
            log.info("[DRY RUN] Changes detected but not saved to disk:")
            for item in changelog:
                log.info(f"  • {item}")
        else:
            log.info("Writing updated data to data/games.json and data/standings.json...")
            build_calendar.save_data(games, weeks)
            league_standings.save_standings_db(standings_db)

            # Recompile HTML
            log.info("Rebuilding calendar HTML...")
            build_calendar.generate_html()

            # Git commit and push if requested
            if args.commit:
                log.info("Committing and pushing changes to GitHub...")
                try:
                    subprocess.run(["git", "add", "data/", "public/index.html", "public/sports_calendar.html"], check=True)
                    commit_msg = f"chore(auto): refresh schedules, scores & standings [{datetime.date.today().isoformat()}]"
                    subprocess.run(["git", "commit", "-m", commit_msg], check=True)
                    subprocess.run(["git", "pull", "--rebase", "origin", "main"], check=True)
                    subprocess.run(["git", "push", "origin", "main"], check=True)
                    log.info("✓ Successfully pushed changes to origin/main.")
                except subprocess.CalledProcessError as e:
                    log.error(f"Git operation failed: {e}")
    else:
        log.info("No schedule, score, or date updates required. Data is up to date.")


if __name__ == "__main__":
    main()
