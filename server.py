"""
Pricing Engine — Flask Backend
Serves xG data from API-Football and match odds from The Odds API.
"""

import json
import time
import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app, origins="*")

# ── Config ──────────────────────────────────────────────
ODDS_API_KEY    = os.environ.get("ODDS_API_KEY", "")
RAPIDAPI_KEY    = os.environ.get("RAPIDAPI_KEY", "")
ODDS_API_BASE   = "https://api.the-odds-api.com/v4"
APIFOOTBALL_BASE = "https://v3.football.api-sports.io"

# Premier League ID on API-Football
EPL_LEAGUE_ID = 39

# ── Team name maps ───────────────────────────────────────

# API-Football team IDs for Premier League 2024-25
# These are the official IDs used by API-Football
APIFOOTBALL_TEAM_IDS = {
    "Arsenal":            42,
    "Aston Villa":        66,
    "Bournemouth":        35,
    "Brentford":          55,
    "Brighton":           51,
    "Burnley":            44,
    "Chelsea":            49,
    "Crystal Palace":     52,
    "Everton":            45,
    "Fulham":             36,
    "Leeds United":       63,
    "Liverpool":          40,
    "Manchester City":    50,
    "Manchester United":  33,
    "Newcastle United":   34,
    "Nottingham Forest":  65,
    "Sunderland":         60,
    "Tottenham":          47,
    "West Ham":           48,
    "Wolverhampton":      39,
}

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


# ── xG scraper via API-Football ──────────────────────────

def _apifootball_headers():
    return {
        "x-apisports-key": RAPIDAPI_KEY,
    }


def get_team_xg(team_name, last_n=10):
    if not RAPIDAPI_KEY:
        raise ValueError("No RAPIDAPI_KEY set in Railway Variables.")

    team_id = APIFOOTBALL_TEAM_IDS.get(team_name)
    if not team_id:
        raise ValueError(f"Team '{team_name}' not found in team ID map.")

    # Fetch last N fixtures for the team in EPL 2024-25 season
    url = f"{APIFOOTBALL_BASE}/fixtures"
    params = {
        "team":   team_id,
        "league": EPL_LEAGUE_ID,
        "season": 2024,
        "last":   last_n,
    }

    resp = requests.get(url, headers=_apifootball_headers(), params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    fixtures = data.get("response", [])
    if not fixtures:
        raise ValueError(f"No fixtures found for {team_name} in API-Football.")

    xg_for_vals     = []
    xg_against_vals = []

    for fixture in fixtures:
        teams    = fixture.get("teams", {})
        score    = fixture.get("score", {})
        goals    = fixture.get("goals", {})

        is_home = teams.get("home", {}).get("id") == team_id

        # API-Football provides xG in the statistics endpoint
        # Use goals as fallback if xG not available
        fixture_id = fixture.get("fixture", {}).get("id")

        # Get statistics for this fixture
        stats_url = f"{APIFOOTBALL_BASE}/fixtures/statistics"
        stats_resp = requests.get(
            stats_url,
            headers=_apifootball_headers(),
            params={"fixture": fixture_id, "team": team_id},
            timeout=15
        )
        stats_data = stats_resp.json().get("response", [])

        xg_for = None
        xg_against = None

        if stats_data:
            stats = stats_data[0].get("statistics", [])
            for stat in stats:
                if stat.get("type") == "Expected Goals":
                    val = stat.get("value")
                    xg_for = float(val) if val and val != "None" else None
                    break

        # If no xG data, skip this fixture
        if xg_for is None:
            continue

        # Get opponent xG
        opp_stats_resp = requests.get(
            stats_url,
            headers=_apifootball_headers(),
            params={"fixture": fixture_id},
            timeout=15
        )
        opp_data = opp_stats_resp.json().get("response", [])
        for team_stats in opp_data:
            if team_stats.get("team", {}).get("id") != team_id:
                for stat in team_stats.get("statistics", []):
                    if stat.get("type") == "Expected Goals":
                        val = stat.get("value")
                        xg_against = float(val) if val and val != "None" else None
                        break

        if xg_for is not None and xg_against is not None:
            xg_for_vals.append(xg_for)
            xg_against_vals.append(xg_against)

        time.sleep(0.3)  # Rate limit: 100 req/day on free tier

    if not xg_for_vals:
        raise ValueError(f"No xG data available for {team_name} — may not be in API-Football free tier.")

    return {
        "team":         team_name,
        "xg_for":       round(sum(xg_for_vals)     / len(xg_for_vals),     3),
        "xg_against":   round(sum(xg_against_vals) / len(xg_against_vals), 3),
        "matches_used": len(xg_for_vals),
    }


# ── Odds API ─────────────────────────────────────────────

def get_match_odds(home_team, away_team):
    if not ODDS_API_KEY:
        return {"error": "No API key set. Add ODDS_API_KEY to Railway Variables."}

    url = f"{ODDS_API_BASE}/sports/soccer_epl/odds"
    params = {
        "apiKey":     ODDS_API_KEY,
        "regions":    "uk",
        "markets":    "h2h",
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

        if (home_search in ht or ht in home_search) and \
           (away_search in at or at in away_search):

            bookmakers = event.get("bookmakers", [])
            if not bookmakers:
                continue

            preferred = ["betfair_ex_eu", "bet365", "williamhill", "paddypower"]
            bm = next(
                (b for b in bookmakers if b["key"] in preferred),
                bookmakers[0]
            )

            markets  = {m["key"]: m for m in bm.get("markets", [])}
            h2h      = markets.get("h2h", {})
            outcomes = {o["name"].lower(): o["price"] for o in h2h.get("outcomes", [])}

            home_odds = outcomes.get(ht) or outcomes.get(home_search)
            away_odds = outcomes.get(at) or outcomes.get(away_search)
            draw_odds = outcomes.get("draw")

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
    return "OK", 200


@app.route("/api/debug")
def api_debug():
    """Test API-Football connection and check xG availability."""
    if not RAPIDAPI_KEY:
        return jsonify({"error": "RAPIDAPI_KEY not set in Railway Variables."})
    try:
        # Just check the API status endpoint
        resp = requests.get(
            f"{APIFOOTBALL_BASE}/status",
            headers=_apifootball_headers(),
            timeout=10
        )
        data = resp.json()
        return jsonify({
            "status":          resp.status_code,
            "account":         data.get("response", {}).get("subscription", {}),
            "requests_left":   data.get("response", {}).get("requests", {}),
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/xg")
def api_xg():
    home   = request.args.get("home", "")
    away   = request.args.get("away", "")
    last_n = int(request.args.get("last_n", 10))

    if not home or not away:
        return jsonify({"error": "Provide home and away team names"}), 400

    try:
        home_data = get_team_xg(home, last_n=last_n)
        away_data = get_team_xg(away, last_n=last_n)

        home_lambda = round((home_data["xg_for"] + away_data["xg_against"]) / 2, 3)
        away_lambda = round((away_data["xg_for"]  + home_data["xg_against"]) / 2, 3)

        return jsonify({
            "home":        home_data,
            "away":        away_data,
            "home_lambda": home_lambda,
            "away_lambda": away_lambda,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/odds")
def api_odds():
    home = request.args.get("home", "")
    away = request.args.get("away", "")

    if not home or not away:
        return jsonify({"error": "Provide home and away team names"}), 400

    try:
        return jsonify(get_match_odds(home, away))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/match")
def api_match():
    home   = request.args.get("home", "")
    away   = request.args.get("away", "")
    last_n = int(request.args.get("last_n", 10))

    if not home or not away:
        return jsonify({"error": "Provide home and away team names"}), 400

    result = {}

    try:
        home_data   = get_team_xg(home, last_n=last_n)
        away_data   = get_team_xg(away, last_n=last_n)
        home_lambda = round((home_data["xg_for"] + away_data["xg_against"]) / 2, 3)
        away_lambda = round((away_data["xg_for"]  + home_data["xg_against"]) / 2, 3)
        result["xg"] = {
            "home":        home_data,
            "away":        away_data,
            "home_lambda": home_lambda,
            "away_lambda": away_lambda,
        }
    except Exception as e:
        result["xg"] = {"error": str(e)}

    try:
        result["odds"] = get_match_odds(home, away)
    except Exception as e:
        result["odds"] = {"error": str(e)}

    return jsonify(result)


if __name__ == "__main__":
    print("\n  Pricing Engine server starting...\n")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
