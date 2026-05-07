"""
Pricing Engine — Flask Backend
Serves xG data from Understat and match odds from The Odds API.
"""

import json
import time
import os
import asyncio
import aiohttp
import requests
from understat import Understat
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app, origins="*")

# ── Config ──────────────────────────────────────────────
ODDS_API_KEY  = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# ── Team name maps ───────────────────────────────────────

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
    "Tottenham":          "Tottenham",
    "West Ham":           "West Ham",
    "Wolverhampton":      "Wolverhampton Wanderers",
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


# ── xG scraper using understat package ───────────────────

async def _fetch_team_xg_async(team_name, last_n=10):
    understat_name = UNDERSTAT_TEAM_MAP.get(team_name, team_name)
    async with aiohttp.ClientSession() as session:
        understat = Understat(session)
        match_data = await understat.get_team_results(
            understat_name, season="2025"
        )

    if not match_data:
        raise ValueError(f"No data returned for {team_name} from Understat.")

    recent = match_data[-last_n:] if len(match_data) >= last_n else match_data

    xg_for_vals     = [float(m["xG"]["h"] if m["side"] == "h" else m["xG"]["a"]) for m in recent]
    xg_against_vals = [float(m["xG"]["a"] if m["side"] == "h" else m["xG"]["h"]) for m in recent]

    return {
        "team":         understat_name,
        "xg_for":       round(sum(xg_for_vals)     / len(xg_for_vals),     3),
        "xg_against":   round(sum(xg_against_vals) / len(xg_against_vals), 3),
        "matches_used": len(recent),
    }


def get_team_xg(team_name, last_n=10):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_fetch_team_xg_async(team_name, last_n))
    finally:
        loop.close()


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
    try:
        data = get_team_xg("Arsenal", last_n=5)
        return jsonify({"status": "ok", "sample": data})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


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
