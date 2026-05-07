"""
Pricing Engine — Flask Backend
Serves xG data from Understat and match odds from The Odds API.

Setup:
    pip install flask flask-cors requests beautifulsoup4 lxml

Run:
    python server.py

Then open index.html in your browser (or visit http://localhost:5000)
"""

import re
import json
import time
import os
import io
import csv as csvlib
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

# ── Config ──────────────────────────────────────────────
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
UNDERSTAT_BASE = "https://understat.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Referer": "https://www.google.com/",
}

# Map frontend team names → Understat team names
UNDERSTAT_TEAM_MAP = {
    "Arsenal":            "Arsenal",
    "Aston Villa":        "Aston Villa",
    "Bournemouth":        "Bournemouth",
    "Brentford":          "Brentford",
    "Brighton":           "Brighton",
    "Burnley":            "Burnley",
    "Chelsea":            "Chelsea",
    "Crystal Palace":     "Crystal Palace",
    "Everton":            "Everton",
    "Fulham":             "Fulham",
    "Leeds United":       "Leeds",
    "Liverpool":          "Liverpool",
    "Manchester City":    "Manchester City",
    "Manchester United":  "Manchester United",
    "Newcastle United":   "Newcastle United",
    "Nottingham Forest":  "Nottingham Forest",
    "Sunderland":         "Sunderland",
    "Tottenham":          "Spurs",
    "West Ham":           "West Ham",
    "Wolverhampton":      "Wolverhampton Wanderers",
}

# Map frontend team names → Odds API team names (partial match friendly)
ODDS_TEAM_MAP = {
    "Arsenal":            "Arsenal",
    "Aston Villa":        "Aston Villa",
    "Bournemouth":        "Bournemouth",
    "Brentford":          "Brentford",
    "Brighton":           "Brighton and Hove Albion",
    "Burnley":            "Burnley",
    "Chelsea":            "Chelsea",
    "Crystal Palace":     "Crystal Palace",
    "Everton":            "Everton",
    "Fulham":             "Fulham",
    "Leeds United":       "Leeds United",
    "Liverpool":          "Liverpool",
    "Manchester City":    "Manchester City",
    "Manchester United":  "Manchester United",
    "Newcastle United":   "Newcastle United",
    "Nottingham Forest":  "Nottingham Forest",
    "Sunderland":         "Sunderland",
    "Tottenham":          "Tottenham Hotspur",
    "West Ham":           "West Ham United",
    "Wolverhampton":      "Wolverhampton Wanderers",
}


# ── xG scraper (football-data.co.uk) ────────────────────

# football-data.co.uk team name mapping
FDOTUK_TEAM_MAP = {
    "Arsenal":            "Arsenal",
    "Aston Villa":        "Aston Villa",
    "Bournemouth":        "Bournemouth",
    "Brentford":          "Brentford",
    "Brighton":           "Brighton",
    "Burnley":            "Burnley",
    "Chelsea":            "Chelsea",
    "Crystal Palace":     "Crystal Palace",
    "Everton":            "Everton",
    "Fulham":             "Fulham",
    "Leeds United":       "Leeds",
    "Liverpool":          "Liverpool",
    "Manchester City":    "Man City",
    "Manchester United":  "Man United",
    "Newcastle United":   "Newcastle",
    "Nottingham Forest":  "Nott'm Forest",
    "Sunderland":         "Sunderland",
    "Tottenham":          "Spurs",
    "West Ham":           "West Ham",
    "Wolverhampton":      "Wolves",
}

# Cache the CSV so we don't re-download every request
_CSV_CACHE = {"data": None, "fetched_at": 0}
CSV_CACHE_TTL = 3600  # 1 hour

def _get_csv_data():
    """Fetch and cache the football-data.co.uk CSV."""
    now = time.time()
    if _CSV_CACHE["data"] and (now - _CSV_CACHE["fetched_at"]) < CSV_CACHE_TTL:
        return _CSV_CACHE["data"]
    
    url = "https://www.football-data.co.uk/mmz4281/2425/E0.csv"
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    resp.raise_for_status()
    
    reader = csvlib.DictReader(io.StringIO(resp.text))
    rows = list(reader)
    _CSV_CACHE["data"] = rows
    _CSV_CACHE["fetched_at"] = now
    return rows


def get_team_xg(team_name: str, season: int = 2025, last_n: int = 10):
    """Fetch rolling average xG for a team from football-data.co.uk."""
    fd_name = FDOTUK_TEAM_MAP.get(team_name, team_name)
    
    rows = _get_csv_data()
    
    # Filter rows for this team (home or away)
    team_rows = []
    for row in rows:
        if row.get("HomeTeam", "").strip() == fd_name:
            team_rows.append({
                "xg_for":     float(row.get("HomeXG") or row.get("HXGH") or 0),
                "xg_against": float(row.get("AwayXG") or row.get("AXGH") or 0),
            })
        elif row.get("AwayTeam", "").strip() == fd_name:
            team_rows.append({
                "xg_for":     float(row.get("AwayXG") or row.get("AXGH") or 0),
                "xg_against": float(row.get("HomeXG") or row.get("HXGH") or 0),
            })
    
    if not team_rows:
        raise ValueError(f"Team '{fd_name}' not found in football-data CSV.")
    
    # Use last N matches
    recent = team_rows[-last_n:] if len(team_rows) >= last_n else team_rows
    
    # Filter out zero xG rows (missing data)
    valid = [r for r in recent if r["xg_for"] > 0 or r["xg_against"] > 0]
    if not valid:
        raise ValueError(f"No xG data available for {team_name} — may not be in current season CSV.")
    
    xg_for     = round(sum(r["xg_for"]     for r in valid) / len(valid), 3)
    xg_against = round(sum(r["xg_against"] for r in valid) / len(valid), 3)
    
    return {
        "team":         team_name,
        "xg_for":       xg_for,
        "xg_against":   xg_against,
        "matches_used": len(valid),
    }

# ── Odds API ─────────────────────────────────────────────

def get_match_odds(home_team: str, away_team: str):
    """Fetch H2H odds for a specific PL fixture from The Odds API."""
    if not ODDS_API_KEY:
        return {"error": "No API key set. Add ODDS_API_KEY to Railway Variables."}

    url = f"{ODDS_API_BASE}/sports/soccer_epl/odds"
    params = {
        "apiKey":    ODDS_API_KEY,
        "regions":   "uk",
        "markets":   "h2h",
        "oddsFormat": "decimal",
    }

    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    events = resp.json()

    home_search = ODDS_TEAM_MAP.get(home_team, home_team).lower()
    away_search = ODDS_TEAM_MAP.get(away_team, away_team).lower()

    for event in events:
        ht = event.get("home_team", "").lower()
        at = event.get("away_team", "").lower()

        # Flexible partial match
        if (home_search in ht or ht in home_search) and \
           (away_search in at or at in away_search):

            # Grab best available odds from first bookmaker
            bookmakers = event.get("bookmakers", [])
            if not bookmakers:
                continue

            # Prefer Betfair EU, then bet365, then William Hill, else first available
            preferred = ["betfair_ex_eu", "bet365", "williamhill", "paddypower"]
            bm = next(
                (b for b in bookmakers if b["key"] in preferred),
                bookmakers[0]
            )

            markets = {m["key"]: m for m in bm.get("markets", [])}
            h2h = markets.get("h2h", {})
            outcomes = {o["name"].lower(): o["price"] for o in h2h.get("outcomes", [])}

            home_odds = outcomes.get(ht) or outcomes.get(home_search)
            away_odds = outcomes.get(at) or outcomes.get(away_search)
            draw_odds  = outcomes.get("draw")

            return {
                "home_team":  event["home_team"],
                "away_team":  event["away_team"],
                "home_odds":  home_odds,
                "draw_odds":  draw_odds,
                "away_odds":  away_odds,
                "bookmaker":  bm["title"],
                "commence":   event.get("commence_time", ""),
            }

    return {"error": f"No fixture found for {home_team} vs {away_team}. May not be scheduled yet."}


# ── Routes ───────────────────────────────────────────────

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/xg")
def api_xg():
    """
    GET /api/xg?home=Leeds United&away=Tottenham&last_n=10
    Returns blended xG lambdas for both teams.
    """
    home = request.args.get("home", "")
    away = request.args.get("away", "")
    last_n = int(request.args.get("last_n", 10))

    if not home or not away:
        return jsonify({"error": "Provide home and away team names"}), 400

    try:
        home_data = get_team_xg(home, last_n=last_n)
        away_data  = get_team_xg(away, last_n=last_n)

        # Blend: home attack vs away defence, and vice versa
        home_lambda = round((home_data["xg_for"] + away_data["xg_against"]) / 2, 3)
        away_lambda  = round((away_data["xg_for"]  + home_data["xg_against"]) / 2, 3)

        return jsonify({
            "home": home_data,
            "away": away_data,
            "home_lambda": home_lambda,
            "away_lambda":  away_lambda,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/odds")
def api_odds():
    """
    GET /api/odds?home=Leeds United&away=Tottenham
    Returns decimal odds for the fixture.
    """
    home = request.args.get("home", "")
    away = request.args.get("away", "")

    if not home or not away:
        return jsonify({"error": "Provide home and away team names"}), 400

    try:
        result = get_match_odds(home, away)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/match")
def api_match():
    """
    GET /api/match?home=Leeds United&away=Tottenham
    Returns both xG and odds in one call.
    """
    home = request.args.get("home", "")
    away = request.args.get("away", "")
    last_n = int(request.args.get("last_n", 10))

    if not home or not away:
        return jsonify({"error": "Provide home and away team names"}), 400

    result = {}

    try:
        home_data   = get_team_xg(home, last_n=last_n)
        away_data   = get_team_xg(away, last_n=last_n)
        home_lambda = round((home_data["xg_for"] + away_data["xg_against"]) / 2, 3)
        away_lambda  = round((away_data["xg_for"]  + home_data["xg_against"]) / 2, 3)
        result["xg"] = {
            "home": home_data,
            "away": away_data,
            "home_lambda": home_lambda,
            "away_lambda":  away_lambda,
        }
    except Exception as e:
        result["xg"] = {"error": str(e)}

    try:
        result["odds"] = get_match_odds(home, away)
    except Exception as e:
        result["odds"] = {"error": str(e)}

    return jsonify(result)


if __name__ == "__main__":
    print("\n  Pricing Engine server starting...")
    print("  Open http://localhost:5000 in your browser\n")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
