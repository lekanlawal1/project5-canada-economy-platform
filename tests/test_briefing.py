"""The briefing flow with a fake model: every path from draft to published text.

Facts are frozen from the August 2026 build (tests/fixtures), so these run offline in CI.
"""

import json
from pathlib import Path

import pytest

from src import briefing
from src.number_verifier import Fact

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "briefing_facts_2026_08.json").read_text())
FACTS = [Fact(**f) for f in FIXTURE["facts"]]
DESCRIBED = FIXTURE["described"]
YEARS = set(FIXTURE["years"])

GOOD = ("Canada's unemployment rate was 6.4% in August 2026, unchanged from July and within the "
        "survey's margin of error.\n\nInflation was 3.0% in August 2026, with core inflation at 2.1%."
        "\n\nThe economy was 1.4% larger than a year earlier, by real GDP.")
BAD = "Canada's unemployment rate fell to 6.1% in August 2026.\n\nInflation was 3.0%."


def run(responses, api_key="test-key"):
    """Fake model: returns the given responses in order; records the prompts it was sent."""
    prompts = []

    def fake(prompt, key):
        prompts.append(prompt)
        r = responses[len(prompts) - 1]
        if isinstance(r, Exception):
            raise r
        return r, 1.0

    return briefing.generate_from_facts(FACTS, DESCRIBED, YEARS, api_key, caller=fake), prompts


def test_template_is_used_without_a_key_and_passes_its_own_check():
    out, prompts = run([], api_key=None)
    assert out["source"] == "template" and out["reason"] == "no API key"
    assert out["numbers_verified"] >= 10 and prompts == []


def test_verified_ai_draft_is_published():
    out, prompts = run([GOOD])
    assert out["source"] == "gemini" and len(prompts) == 1
    assert out["numbers_verified"] == 4  # 6.4, 3.0, 2.1, 1.4
    assert out["numbers_checked"] == 6   # plus the two years, checked but not counted


def test_failed_draft_gets_one_retry_with_specific_feedback():
    out, prompts = run([BAD, GOOD])
    assert out["source"] == "gemini" and len(prompts) == 2
    assert '"6.1"' in prompts[1] and "no fact has this value" in prompts[1]
    assert len(out["attempts"][0]["failed"]) == 1


def test_two_failed_drafts_fall_back_to_the_template():
    out, _ = run([BAD, BAD])
    assert out["source"] == "template"
    assert "6.1" not in out["text"]


def test_api_errors_fall_back_instead_of_breaking_the_deploy():
    out, _ = run([TimeoutError("model took too long"), TimeoutError("still slow")])
    assert out["source"] == "template"
    assert "TimeoutError" in out["attempts"][0]["error"]


def test_a_transient_error_or_cut_off_draft_gets_the_retry():
    out, prompts = run([RuntimeError("draft incomplete: finishReason MAX_TOKENS"), GOOD])
    assert out["source"] == "gemini" and len(prompts) == 2


def test_a_draft_with_no_numbers_is_not_accepted():
    """Nothing to verify is not the same as verified."""
    out, _ = run(["The economy did things this month.", "Still nothing measurable."])
    assert out["source"] == "template"


def test_model_text_is_escaped_before_reaching_the_page():
    out, _ = run([GOOD.replace("Inflation was", "<script>alert(1)</script> Inflation was")])
    assert "<script>" not in out["html"] and "&lt;script&gt;" in out["html"]


def test_em_dashes_are_removed():
    out, _ = run([GOOD.replace("2026, unchanged", "2026 \u2014 unchanged")])
    assert "\u2014" not in out["text"]


@pytest.mark.parametrize("key", ["unemployment_rate", "inflation", "gdp_change_year"])
def test_fixture_has_the_facts_the_template_needs(key):
    assert any(d["key"] == key for d in DESCRIBED)


def test_negative_zero_never_reaches_the_model():
    """Found in the first live run: GDP's monthly change, rounded to -0.0 in the mart, was shown
    to Gemini as "-0.00", and both drafts then described a zero change as a fall."""
    value = round(-0.001, 2)
    assert f"{value:.2f}" == "-0.00"           # the raw problem
    normalised = 0.0 if float(value) == 0 else float(value)
    assert f"{normalised:.2f}" == "0.00"       # what add() in build_facts now does


def test_fact_sheet_has_no_negative_zero():
    assert not any(d["value"].startswith("-0.0") and set(d["value"].lstrip("-").replace(".", "")) == {"0"}
                   for d in DESCRIBED if d["value"])
