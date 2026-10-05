"""Monthly briefing: Gemini drafts it, code verifies every number, a template is the fallback.

Flow:
  1. Build a fact sheet from the marts: every number the briefing may use, with its subject
     words and published precision.
  2. Ask Gemini for a short briefing using only those facts.
  3. Verify every number in the draft (src/number_verifier.py). If anything fails, ask once
     more, telling the model exactly which numbers failed and why.
  4. If the second draft also fails, or there is no API key, or the API errors, publish the
     template briefing instead. The template is built from the same facts and is itself run
     through the verifier, so it is checked, not assumed, to be correct.

The published file (site/data/briefing.json) records which path was taken and every check,
so the page can say "drafted by Gemini, 23 numbers verified" or "template: AI draft failed".

Usage:
    python -m src.briefing            (after src.site_export)
"""

from __future__ import annotations

import html
import json
import os
import sys
import time
from datetime import datetime, timezone

import duckdb
import requests

from src.config import DB_PATH, ROOT
from src.number_verifier import Fact, Finding, passes, verify

MODEL = "gemini-3-flash-preview"
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
OUT_PATH = ROOT / "site" / "data" / "briefing.json"
HEADLINE = "gender = 'Total - Gender' AND age_group = '15 years and over'"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]

# Numbers that may appear for reasons other than a data value, and the words that must sit
# in the same sentence for them to count ("12-month", "ages 15 and over", "80% range").
CONTEXT_NUMBERS = {12.0: ["12-month", "12 month", "year"], 15.0: ["15 and over", "aged 15", "ages 15"],
                   10.0: ["provinces"], 80.0: ["80%", "80 per cent"]}


def month_name(d) -> str:
    return f"{MONTHS[d.month - 1]} {d.year}"


# --------------------------------------------------------------------------- facts


def build_facts(con) -> tuple[list[Fact], list[dict], set[int]]:
    """Return verifier facts, the same facts described for the model, and allowed years."""
    one = lambda sql, p=None: con.execute(sql, p or []).fetchone()
    facts, described, years = [], [], set()

    def add(key, value, decimals, keywords, description, month, is_change=False, display=None,
            scale_forms=None, requires=None, note=None, place=None):
        if value is None:
            return
        facts.append(Fact(key, float(value), decimals, keywords, is_change, scale_forms or [], requires or []))
        years.add(month.year)
        described.append({"key": key, "description": description, "month": month_name(month),
                          "value": display or f"{value:.{decimals}f}", **({"note": note} if note else {}),
                          **({"place": place} if place else {})})

    lab = one(f"""SELECT month, unemployment_rate, unemployment_rate_mom_pp, unemployment_rate_mom_significant,
        unemployment_rate_yoy_pp, unemployment_rate_yoy_significant, employment_mom_k, employment_mom_significant
        FROM mart_labour_monthly WHERE geo = 'Canada' AND {HEADLINE} ORDER BY month DESC LIMIT 1""")
    m, ur, ur_mom, ur_mom_sig, ur_yoy, ur_yoy_sig, emp, emp_sig = lab
    sig = lambda s: "statistically significant (beyond StatCan's margin of error)" if s else \
        "NOT statistically significant (within StatCan's margin of error)"
    add("unemployment_rate", ur, 1, ["unemploy"], "Canada unemployment rate, %, seasonally adjusted", m)
    add("unemployment_rate_change_month", ur_mom, 1, ["unemploy"], "Change in unemployment rate from previous month, percentage points",
        m, True, note=sig(ur_mom_sig))
    add("unemployment_rate_change_year", ur_yoy, 1, ["unemploy"], "Change in unemployment rate from a year earlier, percentage points",
        m, True, note=sig(ur_yoy_sig))
    add("employment_change_month", emp, 1, ["employment", "jobs", "job"], "Change in employment from previous month, thousands of people",
        m, True, display=f"{emp:+.1f} thousand ({emp * 1000:+,.0f} people)", scale_forms=[emp * 1000], note=sig(emp_sig))

    hi = one(f"""SELECT geo, unemployment_rate FROM mart_province_scorecard WHERE geo_level = 'province'
        ORDER BY unemployment_rate DESC LIMIT 1""")
    lo = one(f"""SELECT geo, unemployment_rate FROM mart_province_scorecard WHERE geo_level = 'province'
        ORDER BY unemployment_rate ASC LIMIT 1""")
    add("unemployment_highest_province", hi[1], 1, [hi[0]], f"Highest provincial unemployment rate: {hi[0]}, %", m, requires=["unemploy", "jobless"], place=hi[0])
    add("unemployment_lowest_province", lo[1], 1, [lo[0]], f"Lowest provincial unemployment rate: {lo[0]}, %", m, requires=["unemploy", "jobless"], place=lo[0])

    cpi = one("""SELECT month, yoy_pct, yoy_change_pp FROM mart_cpi_monthly
        WHERE geo = 'Canada' AND product = 'All-items' ORDER BY month DESC LIMIT 1""")
    prev = one("""SELECT month, yoy_pct FROM mart_cpi_monthly WHERE geo = 'Canada' AND product = 'All-items'
        ORDER BY month DESC LIMIT 1 OFFSET 1""")
    core = one("""SELECT month, yoy_pct FROM mart_cpi_monthly WHERE geo = 'Canada'
        AND product = 'All-items excluding food and energy' ORDER BY month DESC LIMIT 1""")
    infl = ["inflation", "consumer price", "cpi", "prices"]
    add("inflation", cpi[1], 1, infl, "Canada CPI inflation, 12-month % change, all-items", cpi[0])
    add("inflation_previous_month", prev[1], 1, infl, "Canada CPI inflation in the previous month, 12-month %", prev[0])
    add("core_inflation", core[1], 1, ["core", "excluding food and energy"], "Core inflation (CPI excluding food and energy), 12-month %", core[0])

    top = one("""SELECT geo, cpi_yoy_pct FROM mart_province_scorecard WHERE geo_level = 'province' ORDER BY cpi_yoy_pct DESC LIMIT 1""")
    bot = one("""SELECT geo, cpi_yoy_pct FROM mart_province_scorecard WHERE geo_level = 'province' ORDER BY cpi_yoy_pct ASC LIMIT 1""")
    add("inflation_highest_province", top[1], 1, [top[0]], f"Highest provincial inflation: {top[0]}, 12-month %", cpi[0], requires=infl, place=top[0])
    add("inflation_lowest_province", bot[1], 1, [bot[0]], f"Lowest provincial inflation: {bot[0]}, 12-month %", cpi[0], requires=infl, place=bot[0])

    for product, key, words in (("Gasoline", "gasoline_inflation", ["gasoline", "gas prices"]),
                                ("Shelter", "shelter_inflation", ["shelter"]),
                                ("Food purchased from stores", "grocery_inflation", ["grocer", "food purchased"])):
        r = one("""SELECT month, yoy_pct FROM mart_cpi_monthly WHERE geo = 'Canada' AND product = ?
            ORDER BY month DESC LIMIT 1""", [product])
        add(key, r[1], 1, words, f"{product} prices, 12-month % change", r[0], True)

    add("bank_of_canada_target", 2.0, 0, ["target", "bank of canada"], "Bank of Canada inflation target, %", cpi[0])
    add("bank_of_canada_band_low", 1.0, 0, ["target", "range", "band"], "Bottom of the Bank of Canada 1 to 3% control range", cpi[0])
    add("bank_of_canada_band_high", 3.0, 0, ["target", "range", "band"], "Top of the Bank of Canada 1 to 3% control range", cpi[0])

    h = one("""SELECT month, yoy_pct FROM mart_housing_monthly WHERE geo = 'Canada'
        AND component = 'Total (house and land)' ORDER BY month DESC LIMIT 1""")
    add("new_home_prices_change_year", h[1], 1, ["home", "housing", "house"], "New home prices, 12-month % change (New Housing Price Index)", h[0], True)

    j = one("""SELECT month, job_vacancy_rate, unemployed_per_vacancy FROM mart_job_market_monthly
        WHERE geo = 'Canada' ORDER BY month DESC LIMIT 1""")
    add("job_vacancy_rate", j[1], 1, ["vacanc"], "Job vacancy rate, %", j[0])
    add("unemployed_per_vacancy", j[2], 2, ["vacanc", "per job", "per opening"], "Unemployed people per job vacancy", j[0])

    g = one("""SELECT month, mom_pct, yoy_pct FROM mart_gdp_monthly WHERE naics_code = 'T001' ORDER BY month DESC LIMIT 1""")
    gdp = ["gdp", "gross domestic product", "output", "economy"]
    add("gdp_change_month", g[1], 2, gdp, "Real GDP, % change from previous month", g[0], True)
    add("gdp_change_year", g[2], 1, gdp, "Real GDP, % change from a year earlier", g[0], True)

    for r in con.execute("SELECT series, horizon, target, method, forecast, low_80, high_80 FROM forecast_latest "
                         "WHERE horizon = 1").fetchall():
        series, _, target, method, fc, lo80, hi80 = r
        subj = ["unemploy"] if series == "unemployment" else infl
        target_d = datetime.strptime(target, "%Y-%m").date()
        how = "seasonal ARIMA model (it beat the naive forecast in backtests)" if method != "naive" else \
              "no-change forecast (no model beat it in backtests)"
        add(f"{series}_forecast_next_month", fc, 1, ["forecast", "expect", "project", "outlook"],
            f"{'Unemployment rate' if series == 'unemployment' else 'CPI inflation'} forecast for next month, %, from a {how}",
            target_d, requires=subj)
        add(f"{series}_forecast_low", lo80, 1, ["range", "between", "forecast"], "Bottom of the 80% forecast range, %", target_d, requires=subj)
        add(f"{series}_forecast_high", hi80, 1, ["range", "between", "forecast"], "Top of the 80% forecast range, %", target_d, requires=subj)

    return facts, described, years


# --------------------------------------------------------------------------- template


def template_briefing(d: dict) -> str:
    """Deterministic briefing from the same facts. Used when the AI draft cannot be verified."""
    f = {x["key"]: x for x in d}
    v = lambda k: float(f[k]["value"].split()[0])
    move = lambda x, up, down, flat: up if x > 0 else down if x < 0 else flat
    ur_mom = v("unemployment_rate_change_month")
    emp = v("employment_change_month")
    sig_emp = "NOT" not in f["employment_change_month"]["note"]
    p1 = (f"Canada's unemployment rate was {v('unemployment_rate'):.1f}% in {f['unemployment_rate']['month']}, "
          f"{move(ur_mom, f'up {abs(ur_mom):.1f} points', f'down {abs(ur_mom):.1f} points', 'unchanged')} from the previous month. "
          f"Employment {move(emp, 'rose', 'fell', 'was unchanged')}"
          f"{f' by {abs(emp) * 1000:,.0f} jobs' if emp else ''}, "
          f"{'a move beyond' if sig_emp else 'a change within'} the survey's margin of error. "
          f"Among the provinces, unemployment was highest in {f['unemployment_highest_province']['place']} "
          f"at {v('unemployment_highest_province'):.1f}% and lowest in "
          f"{f['unemployment_lowest_province']['place']} at {v('unemployment_lowest_province'):.1f}%.")
    infl, prev = v("inflation"), v("inflation_previous_month")
    p2 = (f"Consumer price inflation was {infl:.1f}% in {f['inflation']['month']}, "
          f"{move(infl - prev, f'up from {prev:.1f}%', f'down from {prev:.1f}%', f'matching the previous month at {prev:.1f}%')}. "
          f"Core inflation, excluding food and energy, was {v('core_inflation'):.1f}%. "
          f"Gasoline prices were {move(v('gasoline_inflation'), 'up', 'down', 'flat')} {abs(v('gasoline_inflation')):.1f}% "
          f"over 12 months, and new home prices were {move(v('new_home_prices_change_year'), 'up', 'down', 'unchanged')} "
          f"{abs(v('new_home_prices_change_year')):.1f}% over 12 months.")
    gm = v("gdp_change_month")
    p3 = (f"Real GDP was {move(gm, f'up {abs(gm):.2f}%', f'down {abs(gm):.2f}%', 'flat')} in {f['gdp_change_month']['month']} "
          f"and {move(v('gdp_change_year'), 'up', 'down', 'flat')} {abs(v('gdp_change_year')):.1f}% from a year earlier. "
          f"There were {v('unemployed_per_vacancy'):.2f} unemployed people per job vacancy in {f['unemployed_per_vacancy']['month']}.")
    return "\n\n".join([p1, p2, p3])


# --------------------------------------------------------------------------- Gemini

SYSTEM = """You write the monthly briefing for a public dashboard about Canada's economy.

Rules, all mandatory:
- Use ONLY numbers that appear in the FACTS list, written exactly as given (same decimals).
  No other numbers at all: no dates except month names with their year, no invented figures,
  no calculations of your own.
- Every number must be in the same sentence as words naming what it measures (for example
  "unemployment", "inflation", "GDP", or the province name together with the measure).
- Describe changes with the right direction: a negative change "fell", a positive change "rose".
- Where a fact's note says a change is NOT statistically significant, say it is within the
  survey's margin of error. Do not call it a rise or fall in the headline sense.
- Neutral, plain English for a general reader. No advice, no predictions beyond the forecast
  facts, no causes that are not in the facts.
- 3 short paragraphs, 150 to 200 words in total: labour market; prices and housing; output,
  job vacancies and the one-month outlook. Plain text, paragraphs separated by a blank line.
- Do not use em dashes or en dashes. Use commas, colons or full stops."""


def call_gemini(prompt: str, api_key: str) -> tuple[str, float]:
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        # thinkingLevel low: in a previous project the default thinking level sometimes ran
        # for minutes per request. The task is short and fully specified.
        "generationConfig": {"thinkingConfig": {"thinkingLevel": "low"}, "maxOutputTokens": 2048},
    }
    start = time.perf_counter()
    resp = requests.post(API_URL, headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                         json=body, timeout=(10, 120))
    elapsed = time.perf_counter() - start
    resp.raise_for_status()
    parts = resp.json()["candidates"][0]["content"]["parts"]
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    return text.strip(), elapsed


def user_prompt(described: list[dict], feedback: list[Finding] | None = None) -> str:
    msg = "FACTS (JSON):\n" + json.dumps(described, indent=1) + "\n\nWrite the briefing."
    if feedback:
        bad = "\n".join(f'- "{f.number}" in: "{f.sentence}" ({f.reason})' for f in feedback if not f.ok)
        msg += ("\n\nYour previous draft was rejected by an automatic number checker. These numbers "
                f"failed:\n{bad}\nRewrite the whole briefing so every number follows the rules.")
    return msg


def tidy(text: str) -> str:
    # House style: no em or en dashes. Replaced, not rejected: punctuation cannot change a number.
    return text.replace(" — ", ", ").replace("—", ", ").replace(" – ", ", ").replace("–", " to ")


def to_html(text: str) -> str:
    # The model's text is escaped before it touches the page: it is untrusted input.
    return "".join(f"<p>{html.escape(p.strip())}</p>" for p in text.split("\n\n") if p.strip())


# --------------------------------------------------------------------------- main


def data_values(findings: list[Finding]) -> int:
    """Numbers matched to a data fact. Years and context numbers ("12-month") are checked
    but not counted, so the published "N numbers verified" is not inflated."""
    return sum(1 for f in findings if f.ok and f.fact not in ("year", "context"))


def generate(con, api_key: str | None, caller=call_gemini) -> dict:
    return generate_from_facts(*build_facts(con), api_key=api_key, caller=caller)


def generate_from_facts(facts: list[Fact], described: list[dict], years: set[int],
                        api_key: str | None, caller=call_gemini) -> dict:
    """Draft, verify, retry once with feedback, else fall back. Separate from the database
    so the whole flow can be tested offline with a fake model."""
    check = lambda text: verify(text, facts, years, CONTEXT_NUMBERS)
    attempts = []
    if api_key:
        feedback = None
        for attempt in (1, 2):
            try:
                text, secs = caller(user_prompt(described, feedback), api_key)
            except Exception as err:  # network, quota, malformed response: fall back, never crash the deploy
                attempts.append({"attempt": attempt, "error": f"{type(err).__name__}: {err}"[:300]})
                break
            text = tidy(text)
            findings = check(text)
            attempts.append({"attempt": attempt, "seconds": round(secs, 1), "numbers": len(findings),
                             "failed": [f.__dict__ for f in findings if not f.ok]})
            if passes(findings) and data_values(findings):
                return dict(source="gemini", model=MODEL, text=text, html=to_html(text),
                            numbers_verified=data_values(findings), numbers_checked=len(findings),
                            attempts=attempts, facts=described)
            feedback = findings

    text = template_briefing(described)
    findings = check(text)
    if not passes(findings):  # the template must be correct; if not, that is a bug to surface
        raise AssertionError(f"template briefing failed verification: {[f.__dict__ for f in findings if not f.ok]}")
    reason = "no API key" if not api_key else "AI draft failed verification or the API errored"
    return dict(source="template", reason=reason, text=text, html=to_html(text),
                numbers_verified=data_values(findings), numbers_checked=len(findings),
                attempts=attempts, facts=described)


def main() -> int:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        result = generate(con, os.environ.get("GEMINI_API_KEY"))
    result["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"briefing: {result['source']}, {result['numbers_verified']} numbers verified, "
          f"{len(result['attempts'])} AI attempts")
    print(result["text"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
