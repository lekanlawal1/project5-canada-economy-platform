"""The 'What it means for you' wording rules (src.site_export.so_what_cards).

The cards are fixed rules over numbers from the marts. These tests pin the rules: which
comparison word is chosen, when a card is left out, and that every number shown is one
that was passed in (or simple arithmetic on it).
"""

from src.site_export import so_what_cards


def facts(rent=2.0, all_items=2.0, groceries=3.0, ur=6.5, ur_yoy=0.3, ur_sig=True,
          upv=2.0, upv_prev=1.5, jvr=3.0, jvr_yoy=-0.2, low_q=False, core=2.1):
    return {
        "geo": "Ontario",
        "cpi": {"rent": {"month": "2026-08", "yoy_pct": rent}, "all": {"month": "2026-08", "yoy_pct": all_items},
                "groceries": {"month": "2026-08", "yoy_pct": groceries}},
        "core": {"month": "2026-08", "yoy_pct": core},
        "labour": {"month": "2026-08", "ur": ur, "ur_yoy": ur_yoy, "ur_yoy_sig": ur_sig},
        "jobs": {"month": "2026-07", "upv": upv, "upv_prev": upv_prev, "jvr": jvr, "jvr_yoy": jvr_yoy, "low_q": low_q},
    }


def card(cards, who):
    return next(c for c in cards if c["who"] == who)


def text(c):
    return " ".join([c["headline"], *c["lines"], c["note"]])


def test_three_cards_in_order():
    assert [c["who"] for c in so_what_cards(facts())] == ["Renter", "Job seeker", "Employer"]


def test_rent_pace_words():
    assert "faster than prices overall" in text(card(so_what_cards(facts(rent=5.0, all_items=2.0)), "Renter"))
    assert "slower than prices overall" in text(card(so_what_cards(facts(rent=1.0, all_items=2.0)), "Renter"))
    assert "about the same pace" in text(card(so_what_cards(facts(rent=2.1, all_items=2.0)), "Renter"))


def test_rent_dollar_example_is_arithmetic_on_the_rate():
    t = text(card(so_what_cards(facts(rent=2.4)), "Renter"))
    assert "about $48 a month, or $576 a year" in t        # 2000 x 2.4% = 48; x 12 = 576


def test_falling_and_flat_rent():
    down = card(so_what_cards(facts(rent=-1.5)), "Renter")
    assert down["headline"] == "Rent down 1.5% in a year"
    flat = card(so_what_cards(facts(rent=0.0)), "Renter")
    assert flat["headline"] == "Rent flat over the year" and "up 0.0" not in text(flat)


def test_unemployment_change_respects_margin_of_error():
    sig = text(card(so_what_cards(facts(ur_yoy=0.8, ur_sig=True)), "Job seeker"))
    assert "up 0.8 points from a year ago." in sig and "margin of error" not in sig
    noise = text(card(so_what_cards(facts(ur_yoy=0.2, ur_sig=False)), "Job seeker"))
    assert "within the survey's margin of error" in noise


def test_vacancy_month_is_named_because_it_lags():
    assert "In July 2026 there were 2.0 unemployed people" in text(card(so_what_cards(facts()), "Job seeker"))


def test_hiring_direction_follows_unemployed_per_vacancy():
    assert card(so_what_cards(facts(upv=2.0, upv_prev=1.5)), "Employer")["headline"] == "Hiring: easier than a year ago"
    assert card(so_what_cards(facts(upv=1.2, upv_prev=1.5)), "Employer")["headline"] == "Hiring: harder than a year ago"
    assert card(so_what_cards(facts(upv=1.52, upv_prev=1.5)), "Employer")["headline"] == "Hiring: about as hard as a year ago"


def test_core_inflation_band():
    assert "inside the Bank of Canada's 1 to 3% range" in text(card(so_what_cards(facts(core=2.1)), "Employer"))
    assert "above the Bank of Canada's" in text(card(so_what_cards(facts(core=3.4)), "Employer"))
    assert "below the Bank of Canada's" in text(card(so_what_cards(facts(core=0.6)), "Employer"))


def test_low_quality_vacancy_estimate_is_flagged():
    assert "low quality" in card(so_what_cards(facts(low_q=True)), "Employer")["note"]


def test_missing_facts_drop_the_card_instead_of_guessing():
    f = facts()
    f["cpi"]["rent"] = {}
    f["jobs"] = {}
    cards = so_what_cards(f)
    assert [c["who"] for c in cards] == ["Job seeker"]
    assert "unemployed people for every open job" not in text(cards[0])


def test_unchanged_vacancy_rate_reads_as_unchanged():
    t = text(card(so_what_cards(facts(jvr=2.8, jvr_yoy=0.0)), "Employer"))
    assert "2.8% of jobs are vacant, the same as a year ago." in t and "0.0 points" not in t
