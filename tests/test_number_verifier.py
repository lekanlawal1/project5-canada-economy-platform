"""Adversarial evaluation of the number verifier.

BAD drafts each plant one error of the kind language models actually make; every one must be
caught. GOOD drafts are correct paraphrases; none may be flagged. KNOWN_GAPS documents what
the verifier cannot catch, as passing tests, so the limits are tested facts, not hopes.

Facts mirror the August 2026 data so the cases read like real briefings.
"""

import pytest

from src.briefing import CONTEXT_NUMBERS as CONTEXT
from src.number_verifier import Fact, passes, verify

INFL = ["inflation", "consumer price", "cpi", "prices"]
FACTS = [
    Fact("unemployment_rate", 6.4, 1, ["unemploy"]),
    Fact("unemployment_rate_change_month", 0.0, 1, ["unemploy"], is_change=True),
    Fact("unemployment_rate_change_year", -0.7, 1, ["unemploy"], is_change=True),
    Fact("employment_change_month", -41.7, 1, ["employment", "jobs", "job"], is_change=True, scale_forms=[-41700]),
    Fact("unemployment_highest_province", 8.6, 1, ["Newfoundland and Labrador"], requires=["unemploy"]),
    Fact("unemployment_lowest_province", 5.0, 1, ["Manitoba"], requires=["unemploy"]),
    Fact("inflation", 3.0, 1, INFL),
    Fact("inflation_previous_month", 3.0, 1, INFL),
    Fact("core_inflation", 2.1, 1, ["core"]),
    Fact("inflation_highest_province", 5.1, 1, ["Nova Scotia"], requires=INFL),
    Fact("gasoline_inflation", 22.8, 1, ["gasoline"], is_change=True),
    Fact("new_home_prices_change_year", -2.0, 1, ["home", "housing"], is_change=True),
    Fact("unemployed_per_vacancy", 3.02, 2, ["vacanc"]),
    Fact("gdp_change_year", 1.4, 1, ["gdp", "economy"], is_change=True),
    Fact("bank_of_canada_target", 2.0, 0, ["target", "bank of canada"]),
]
YEARS = {2026}


def check(text):
    return verify(text, FACTS, YEARS, CONTEXT)


BAD = {
    "wrong value": "Canada's unemployment rate was 6.5% in August 2026.",
    "metric swap (inflation value as unemployment)": "The unemployment rate was 3.0% in August 2026.",
    "wrong direction": "Unemployment rose 0.7 points from a year earlier.",
    "wrong explicit sign": "The unemployment rate changed by +0.7 points over the year.",
    "invented statistic": "Average hourly wages grew 4.2% over the year.",
    "false precision": "Inflation was 3.03% in August 2026.",
    "rounding up a value": "Core inflation was 2.2% in August 2026.",
    "scale error (thousands)": "Employment fell by 417,000 jobs in August 2026.",
    "number glued to a unit": "Employment fell by 417k jobs in August 2026.",
    "wrong province": "Unemployment was highest in Ontario at 8.6%.",
    "right province, wrong metric": "Inflation was highest in Newfoundland and Labrador at 8.6%.",
    "wrong direction for a fall in prices": "New home prices rose 2.0% over 12 months.",
    "GDP direction flipped": "The economy shrank 1.4% from a year earlier.",
    "zero change described as a move": "The unemployment rate rose 0.0 points in August 2026.",
    "made-up ordinal": "It was the 3rd straight month of gains in jobs.",
}

GOOD = {
    "plain": "Canada's unemployment rate was 6.4% in August 2026, unchanged from July.",
    "decline wording": "Unemployment was down 0.7 points from a year earlier.",
    "people not thousands": "Employment declined by 41,700 jobs, within the survey's margin of error.",
    "thousands form": "Employment fell by 41.7 thousand jobs.",
    "province pair": "Unemployment was highest in Newfoundland and Labrador at 8.6% and lowest in Manitoba at 5.0%.",
    "honest rounding": "There were about 3 unemployed people for every job vacancy.",
    "target and context numbers": "Inflation held at 3.0% on a 12-month basis, above the Bank of Canada's 2% target.",
    "explicit negative sign": "New home prices changed by -2.0% over 12 months.",
    "gasoline": "Gasoline prices climbed 22.8% over 12 months.",
}


@pytest.mark.parametrize("name", list(BAD))
def test_bad_draft_is_caught(name):
    findings = check(BAD[name])
    assert not passes(findings), f"missed: {name}: {[f.__dict__ for f in findings]}"


@pytest.mark.parametrize("name", list(GOOD))
def test_good_draft_passes(name):
    findings = check(GOOD[name])
    assert passes(findings), f"false alarm: {name}: {[f.__dict__ for f in findings if not f.ok]}"


def test_reasons_are_specific():
    reasons = {f.reason for f in check(BAD["metric swap (inflation value as unemployment)"]) if not f.ok}
    assert any("not for the subject" in r for r in reasons)
    reasons = {f.reason for f in check(BAD["wrong direction"]) if not f.ok}
    assert any("wrong direction" in r for r in reasons)


# ---------------------------------------------------------------- known gaps, tested as such

def test_known_gap_two_subjects_in_one_sentence():
    """Subject matching works per sentence. With two measures in one sentence, a number can
    borrow the other measure's subject words. Mitigation: the prompt asks for one measure per
    sentence where possible; the gap is documented in docs/06_briefing.md."""
    text = "Inflation was 3.0% while the unemployment rate was also 3.0%."
    assert passes(check(text))  # NOT caught


def test_known_gap_claims_without_numbers():
    """Only numbers are verified. A wrong claim with no number in it passes."""
    assert passes(check("Unemployment surged to a record high in August 2026."))  # NOT caught


# ---------------------------------------------------------------- regressions from live runs
# Real sentences from the first live evaluation (10 Gemini runs, October 2026). The first
# group were verifier false alarms, now fixed; the second are genuine rule breaks by the model
# and must stay rejected.

LIVE_FALSE_ALARMS = [
    "Real GDP for July 2026 showed a month to month change of 0.00 and rose 1.4 from a year earlier.",
    "Real GDP for July 2026 showed a change of 0.00 per cent, though output rose 1.4 per cent from a year earlier.",
    "In July 2026, real GDP showed a month to month change of 0.00, while real GDP rose 1.4 from a year earlier.",
    "Gasoline prices rose 22.8, food from stores rose 2.8, and shelter prices rose 1.5.",
]
LIVE_TRUE_REJECTIONS = [
    # "the rate" never says which rate: the measure must be named in the sentence.
    "The monthly change of 0.0 is within the survey's margin of error, though the rate fell 0.7 from a year earlier.",
]

LIVE_FACTS = FACTS + [
    Fact("gdp_change_month", 0.0, 2, ["gdp", "output", "economy"], is_change=True),
    Fact("grocery_inflation", 2.8, 1, ["grocer", "food purchased", "food from stores"], is_change=True),
    Fact("shelter_inflation", 1.5, 1, ["shelter"], is_change=True),
]


@pytest.mark.parametrize("text", LIVE_FALSE_ALARMS)
def test_live_false_alarms_now_pass(text):
    findings = verify(text, LIVE_FACTS, YEARS, CONTEXT)
    assert passes(findings), [f.__dict__ for f in findings if not f.ok]


@pytest.mark.parametrize("text", LIVE_TRUE_REJECTIONS)
def test_live_rule_breaks_still_rejected(text):
    assert not passes(verify(text, LIVE_FACTS, YEARS, CONTEXT))


def test_bounded_window_still_catches_a_wrong_direction_in_a_list():
    text = "Gasoline prices fell 22.8, and shelter prices rose 1.5."
    assert not passes(verify(text, LIVE_FACTS, YEARS, CONTEXT))
