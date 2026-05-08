"""
Pricing Engine — Flask Backend
Serves xG data from API-Football (via RapidAPI) and match odds from The Odds API.
"""

import time
import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app, origins="*")

# ── Config ──────────────────────────────────────────────
ODDS_API_KEY     = os.environ.get("ODDS_API_KEY", "")
RAPIDAPI_KEY     = os.environ.get("RAPIDAPI_KEY", "")
ODDS_API_BASE    = "https://api.the-odds-api.com/v4"
APIFOOTBALL_BASE = "https://v3.football.api-sports.io"
EPL_LEAGUE_ID    = 39
SEASON           = 2025

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


def _headers():
    return {
        "x-apisports-key": RAPIDAPI_KEY,
    }


def get_team_xg(team_name, last_n=10):
    if not RAPIDAPI_KEY:
        raise ValueError("No RAPIDAPI_KEY set in Railway Variables.")

    team_id = APIFOOTBALL_TEAM_IDS.get(team_name)
    if not team_id:
        raise ValueError(f"Team '{team_name}' not found in team ID map.")

    resp = requests.get(
        f"{APIFOOTBALL_BASE}/fixtures",
        headers=_headers(),
        params={"team": team_id, "league": EPL_LEAGUE_ID, "season": SEASON, "last": 10},
        timeout=15
    )
    resp.raise_for_status()
    fixtures = resp.json().get("response", [])

    if not fixtures:
        raise ValueError(f"No fixtures found for {team_name} in the {SEASON} season.")

    xg_for_vals         = []
    xg_against_vals     = []
    corner_for_vals     = []
    corner_against_vals = []
    yellow_for_vals     = []
    yellow_against_vals = []
    red_for_vals        = []
    red_against_vals    = []
    shots_for_vals      = []
    shots_against_vals  = []
    fouls_for_vals      = []
    fouls_against_vals  = []
    red_against_vals    = []
    shots_for_vals      = []
    shots_against_vals  = []
    fouls_for_vals      = []
    fouls_against_vals  = []

    for fixture in fixtures:
        fixture_id = fixture.get("fixture", {}).get("id")
        teams      = fixture.get("teams", {})
        is_home    = teams.get("home", {}).get("id") == team_id

        stats_resp = requests.get(
            f"{APIFOOTBALL_BASE}/fixtures/statistics",
            headers=_headers(),
            params={"fixture": fixture_id},
            timeout=15
        )
        all_stats = stats_resp.json().get("response", [])

        team_xg      = None
        opp_xg       = None
        team_corners = None
        opp_corners  = None
        team_yellow  = None
        opp_yellow   = None
        team_red     = None
        opp_red      = None
        team_shots   = None
        opp_shots    = None
        team_fouls   = None
        opp_fouls    = None

        for team_stats in all_stats:
            tid = team_stats.get("team", {}).get("id")
            for stat in team_stats.get("statistics", []):
                stype = stat.get("type")
                val   = stat.get("value")
                def fval(v):
                    try: return float(v) if v and str(v) not in ("None", "") else None
                    except: return None
                if stype in ("Expected Goals", "expected_goals"):
                    if tid == team_id: team_xg = fval(val)
                    else:              opp_xg  = fval(val)
                elif stype == "Corner Kicks":
                    if tid == team_id: team_corners = fval(val)
                    else:              opp_corners  = fval(val)
                elif stype == "Yellow Cards":
                    if tid == team_id: team_yellow = fval(val)
                    else:              opp_yellow  = fval(val)
                elif stype == "Red Cards":
                    # Treat null/None as 0 for red cards
                    rval = fval(val) if val and str(val) not in ("None", "") else 0.0
                    if tid == team_id: team_red = rval
                    else:              opp_red  = rval
                elif stype == "Total Shots":
                    if tid == team_id: team_shots = fval(val)
                    else:              opp_shots  = fval(val)
                elif stype == "Fouls":
                    if tid == team_id: team_fouls = fval(val)
                    else:              opp_fouls  = fval(val)

        if team_xg is not None and opp_xg is not None:
            xg_for_vals.append(team_xg)
            xg_against_vals.append(opp_xg)
        if team_corners is not None and opp_corners is not None:
            corner_for_vals.append(team_corners)
            corner_against_vals.append(opp_corners)
        if team_yellow is not None:
            yellow_for_vals.append(team_yellow)
        if opp_yellow is not None:
            yellow_against_vals.append(opp_yellow)
        if team_red is not None:
            red_for_vals.append(team_red)
        if opp_red is not None:
            red_against_vals.append(opp_red)
        if team_shots is not None:
            shots_for_vals.append(team_shots)
        if opp_shots is not None:
            shots_against_vals.append(opp_shots)
        if team_fouls is not None:
            fouls_for_vals.append(team_fouls)
        if opp_fouls is not None:
            fouls_against_vals.append(opp_fouls)
        if team_shots is not None:
            shots_for_vals.append(team_shots)
        if opp_shots is not None:
            shots_against_vals.append(opp_shots)
        if team_fouls is not None:
            fouls_for_vals.append(team_fouls)
        if opp_fouls is not None:
            fouls_against_vals.append(opp_fouls)

        time.sleep(0.5)

    if not xg_for_vals:
        raise ValueError(f"No xG data found for {team_name} — check your API-Football plan includes statistics.")

    def avg(lst): return round(sum(lst) / len(lst), 2) if lst else None
    def avg_or_zero(lst): return round(sum(lst) / len(lst), 2) if lst else 0.0

    return {
        "team":             team_name,
        "xg_for":           round(sum(xg_for_vals)     / len(xg_for_vals),     3),
        "xg_against":       round(sum(xg_against_vals) / len(xg_against_vals), 3),
        "matches_used":     len(xg_for_vals),
        "corners_for":          avg(corner_for_vals),
        "corners_against":      avg(corner_against_vals),
        "yellow_cards_for":     avg(yellow_for_vals),
        "yellow_cards_against": avg(yellow_against_vals),
        "red_cards_for":        avg(red_for_vals),
        "red_cards_against":    avg(red_against_vals),
        "shots_for":            avg(shots_for_vals),
        "shots_against":        avg(shots_against_vals),
        "fouls_for":            avg(fouls_for_vals),
        "fouls_against":        avg(fouls_against_vals),
        "shots_for":            avg(shots_for_vals),
        "shots_against":        avg(shots_against_vals),
        "fouls_for":            avg(fouls_for_vals),
        "fouls_against":        avg(fouls_against_vals),
    }


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
@app.route("/api/fixtures")
def api_fixtures():
    """Return upcoming EPL fixtures for the next 14 days."""
    if not RAPIDAPI_KEY:
        return jsonify({"error": "RAPIDAPI_KEY not set."})
    try:
        resp = requests.get(
            f"{APIFOOTBALL_BASE}/fixtures",
            headers=_headers(),
            params={
                "league": EPL_LEAGUE_ID,
                "season": SEASON,
                "next":   10,
            },
            timeout=15
        )
        resp.raise_for_status()
        fixtures = resp.json().get("response", [])

        result = []
        for f in fixtures:
            home = f.get("teams", {}).get("home", {})
            away = f.get("teams", {}).get("away", {})
            date = f.get("fixture", {}).get("date", "")
            result.append({
                "fixture_id": f.get("fixture", {}).get("id"),
                "home":       home.get("name"),
                "away":       away.get("name"),
                "date":       date,
            })

        return jsonify({"fixtures": result})
    except Exception as e:
        return jsonify({"error": str(e)})



@app.route("/")
def index():
    return "OK", 200



@app.route("/api/find-team")
def api_find_team():
    name = request.args.get("name", "Sunderland")
    resp = requests.get(
        f"{APIFOOTBALL_BASE}/teams",
        headers=_headers(),
        params={"name": name, "league": EPL_LEAGUE_ID, "season": SEASON},
        timeout=15
    )
    return jsonify(resp.json())

@app.route("/api/debug")
def api_debug():
    if not RAPIDAPI_KEY:
        return jsonify({"error": "RAPIDAPI_KEY not set."})
    try:
        # Get a recent fixture
        resp = requests.get(
            f"{APIFOOTBALL_BASE}/fixtures",
            headers=_headers(),
            params={"team": 42, "league": EPL_LEAGUE_ID, "season": SEASON, "last": 1},
            timeout=15
        )
        fixtures = resp.json().get("response", [])
        if not fixtures:
            return jsonify({"error": "No fixtures found"})

        fixture_id = fixtures[0].get("fixture", {}).get("id")

        # Get statistics for that fixture
        stats_resp = requests.get(
            f"{APIFOOTBALL_BASE}/fixtures/statistics",
            headers=_headers(),
            params={"fixture": fixture_id},
            timeout=15
        )
        all_stats = stats_resp.json().get("response", [])

        # Show all stat types available
        stat_types = []
        for team_stats in all_stats:
            team_name = team_stats.get("team", {}).get("name")
            for stat in team_stats.get("statistics", []):
                stat_types.append({
                    "team": team_name,
                    "type": stat.get("type"),
                    "value": stat.get("value"),
                })

        return jsonify({
            "fixture_id":  fixture_id,
            "fixture_date": fixtures[0].get("fixture", {}).get("date"),
            "stats_count": len(stat_types),
            "all_stats":   stat_types,
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
