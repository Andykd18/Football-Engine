"""
Pricing Engine — Flask Backend
Serves xG data from Understat via ScraperAPI and match odds from The Odds API.
"""

import re
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
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")
ODDS_API_BASE   = "https://api.the-odds-api.com/v4"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.google.com/",
}

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


# ── xG scraper ───────────────────────────────────────────

def _extract_json_var(html, var_name):
    pattern = rf"var\s+{var_name}\s*=\s*JSON\.parse\('(.+?)'\)"
    match = re.search(pattern, html)
    if not match:
        return None
    raw = match.group(1)
    raw = raw.replace("\\'", "'")
    try:
        raw = raw.encode("utf-8").decode("unicode_escape")
    except Exception:
        pass
    return json.loads(raw)


def get_team_xg(team_name, last_n=10):
    understat_name = UNDERSTAT_TEAM_MAP.get(team_name, team_name)
    target_url = "https://understat.com/league/EPL/2025"

    if SCRAPER_API_KEY:
        url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={target_url}&render=true"
    else:
        url = target_url

    time.sleep(1)
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()

    if "teamsData" not in resp.text:
        raise ValueError("Could not load Understat data — try again in a moment.")

    teams_data = _extract_json_var(resp.text, "teamsData")
    if not teams_data:
        raise ValueError("Could not parse Understat data.")

    matched = None
    for tid, tdata in teams_data.items():
        if understat_name.lower() in tdata["title"].lower():
            matched = tdata
            break

    if not matched:
        available = [v["title"] for v in teams_data.values()]
        raise ValueError(f"Team '{understat_name}' not found. Available: {available}")

    history = matched.get("history", [])
    recent = history[-last_n:] if len(history) >= last_n else history

    if not recent:
        raise ValueError(f"No match history for {team_name}")

    xg_for     = round(sum(float(m["xG"])  for m in recent) / len(recent), 3)
    xg_against = round(sum(float(m["xGA"]) for m in recent) / len(recent), 3)

    return {
        "team":         matched["title"],
        "xg_for":       xg_for,
        "xg_against":   xg_against,
        "matches_used": len(recent),
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
    target_url  = "https://understat.com/league/EPL/2025"
    scraper_key = os.environ.get("SCRAPER_API_KEY", "")
    url = f"http://api.scraperapi.com?api_key={scraper_key}&url={target_url}&render=true"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=60)
        return jsonify({
            "status":            resp.status_code,
            "has_teamsData":     "teamsData" in resp.text,
            "has_JSON_parse":    "JSON.parse" in resp.text,
            "has_var_teamsData": "var teamsData" in resp.text,
            "content_length":    len(resp.text),
            "first_200":         resp.text[:200],
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
