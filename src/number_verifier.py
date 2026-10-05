"""Check that every number in a piece of text traces to a known fact.

A number in the text passes only if some fact matches on all three:
  1. Value: equal to the fact at the fact's published precision (or the fact rounded to
     fewer decimals: "about 3" for 3.02 is honest rounding; "3.1" for 3.02 is not).
  2. Subject: one of the fact's keywords appears in the same sentence, so the inflation
     rate cannot be passed off as the unemployment rate just because both are 3.0.
  3. Direction: for a change, words like "rose" or "fell" near the number must agree with
     the sign of the change. "Rose 0.7 points" cannot stand in for a fall of 0.7.

Anything else is reported as a failure with a reason. The verifier is deliberately strict:
a false alarm costs a fallback to the template briefing; a missed error publishes a wrong
number under the project's name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

UP = re.compile(r"\b(rose|rise|rising|risen|increas\w*|up|higher|climb\w*|gain\w*|grew|grow\w*|"
                r"accelerat\w*|jump\w*|added|edged up|picked up)\b", re.I)
DOWN = re.compile(r"\b(fell|fall\w*|declin\w*|decreas\w*|down|lower|dropp?\w*|lost|loss|eas\w*|"
                  r"slow\w*|contract\w*|shed|cool\w*|shrank|shrink\w*|dipp?\w*)\b", re.I)
# Digits glued to letters ("417k", "3rd") are still numbers and still checked; skipping them
# would be a loophole. The cost: "COVID-19" is flagged too. Strict is the safe direction.
NUMBER = re.compile(r"(?<![A-Za-z\d.])([-\u2212+]?)(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d])")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


@dataclass
class Fact:
    key: str
    value: float                 # signed value, as stored in the warehouse
    decimals: int                # published precision
    keywords: list[str]          # at least one must appear in the sentence (case-insensitive)
    is_change: bool = False      # if True, direction words are checked against the sign
    scale_forms: list[float] = field(default_factory=list)  # e.g. 41.7 thousand also as 41700
    requires: list[str] = field(default_factory=list)  # if set, one of these must ALSO appear

    def matches_value(self, x: float) -> bool:
        candidates = [abs(self.value)] + [abs(f) for f in self.scale_forms]
        for c in candidates:
            for d in range(self.decimals, -1, -1):
                if round(c, d) == x and _decimals_of(x) <= self.decimals:
                    return True
        return False

    def matches_subject(self, sentence: str) -> bool:
        s = sentence.lower()
        if not any(k.lower() in s for k in self.keywords):
            return False
        # Province facts need the place AND the metric: Ontario's inflation must not pass as
        # Ontario's unemployment rate.
        return not self.requires or any(r.lower() in s for r in self.requires)

    def direction_ok(self, window: str) -> bool:
        if not self.is_change:
            return True
        up, down = bool(UP.search(window)), bool(DOWN.search(window))
        if up and down:
            return True  # ambiguous wording: do not guess
        if self.value > 0:
            return not down
        if self.value < 0:
            return not up
        return not (up or down)  # a zero change described as a move is wrong


@dataclass
class Finding:
    number: str
    sentence: str
    ok: bool
    fact: str | None = None
    reason: str = ""


def _decimals_of(x: float) -> int:
    s = repr(x)
    return len(s.split(".")[1].rstrip("0")) if "." in s else 0


def _parse(raw: str) -> float:
    return float(raw.replace(",", ""))


def verify(text: str, facts: list[Fact], allowed_years: set[int] | None = None,
           context_numbers: dict[float, list[str]] | None = None) -> list[Finding]:
    """Return one Finding per number in the text."""
    allowed_years = allowed_years or set()
    context_numbers = context_numbers or {}
    findings = []
    for sentence in SENTENCE.split(text.strip()):
        for m in NUMBER.finditer(sentence):
            raw = m.group(2)
            x = _parse(raw)
            # The words just before the number decide its direction ("fell 0.7", "down 0.7").
            window = " ".join(sentence[: m.start()].split()[-6:]) + " " + sentence[m.end(): m.end() + 30]
            # An explicit sign is a direction claim too: "-0.7" must not stand for a rise.
            if m.group(1) in ("-", "−"):
                window += " down"
            elif m.group(1) == "+":
                window += " up"

            if x.is_integer() and int(x) in allowed_years and "," not in raw:
                findings.append(Finding(raw, sentence, True, "year"))
                continue
            ctx = context_numbers.get(x)
            if ctx and any(k.lower() in sentence.lower() for k in ctx):
                findings.append(Finding(raw, sentence, True, "context"))
                continue

            value_hits = [f for f in facts if f.matches_value(x)]
            if not value_hits:
                findings.append(Finding(raw, sentence, False, reason="no fact has this value"))
                continue
            subject_hits = [f for f in value_hits if f.matches_subject(sentence)]
            if not subject_hits:
                findings.append(Finding(raw, sentence, False, reason=
                    f"value exists ({', '.join(f.key for f in value_hits)}) but not for the subject of this sentence"))
                continue
            good = [f for f in subject_hits if f.direction_ok(window)]
            if not good:
                findings.append(Finding(raw, sentence, False, reason=
                    f"wrong direction for {', '.join(f.key for f in subject_hits)}"))
                continue
            findings.append(Finding(raw, sentence, True, good[0].key))
    return findings


def passes(findings: list[Finding]) -> bool:
    return all(f.ok for f in findings)
