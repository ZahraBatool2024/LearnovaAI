"""
Heuristic extraction of assignment/quiz/exam dates out of raw syllabus
text. Regex + keyword + dateutil — deliberately transparent rather than
a black box: every candidate keeps its exact source line AND a
confidence level, so low-confidence guesses can be routed to a review
queue instead of being silently trusted (see status/confidence in
models.DeadlineItem and the /pending endpoints in main.py).

Confidence rules:
  high   — an explicit item-type keyword (quiz/exam/homework/...) AND an
            explicit year in the date phrase.
  medium — explicit keyword, but the year had to be inferred.
  low    — no specific item-type keyword; classified only because the line
            contains a generic due-date verb ("due", "deadline", "submit",
            "turn in") next to a date.
"""

import re
import datetime
from dateutil import parser as dateparser

KEYWORD_TYPES = [
    (["final exam", "midterm exam", "midterm", "exam"], "exam"),
    (["quiz"], "quiz"),
    (["project", "presentation"], "project"),
    (["reading"], "reading"),
    (["homework", "assignment", "hw", "problem set", "pset"], "assignment"),
    (["final"], "exam"),  # bare "final" checked last — usually means final exam
]

GENERIC_DUE_WORDS = ["due", "deadline", "submit", "turn in", "no later than", "by "]

# Matches just the date phrase inside a line (not the whole sentence). Isolating
# it matters: dateutil's fuzzy mode gets confused by other numbers in the same
# line (e.g. "Quiz 1 ... chapter 1"), but parses a clean phrase reliably.
_DATE_PHRASE_RE = re.compile(
    r"(?:"
    r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*,?\s+"  # optional leading weekday, e.g. "Monday, "
    r")?"
    r"(?:"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s*\d{4})?"  # March 10, 2026
    r"|\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?:,?\s*\d{4})?"  # 10 March 2026
    r"|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?"       # 03/10 or 03/10/2026
    r"|\d{4}-\d{1,2}-\d{1,2}"                     # 2026-03-10
    r")",
    re.IGNORECASE,
)


def _classify(line: str):
    """Returns (item_type, confident) — confident=False means it was only
    picked up via a generic due-date word, not a specific keyword."""
    lower = line.lower()
    for keywords, item_type in KEYWORD_TYPES:
        for kw in keywords:
            if kw in lower:
                return item_type, True
    if any(w in lower for w in GENERIC_DUE_WORDS):
        return "assignment", False
    return None, False


def _clean_title(line: str) -> str:
    title = re.sub(r"^[\s\-\*\u2022\d.\)]+", "", line).strip()
    title = re.sub(r"\s+", " ", title)
    return title[:100] if title else line[:100]


def _resolve_date(line: str, today: datetime.date):
    match = _DATE_PHRASE_RE.search(line)
    if not match:
        return None, False
    date_str = match.group(0)
    has_explicit_year = bool(re.search(r"\d{4}", date_str))
    try:
        default_dt = datetime.datetime(today.year, 1, 1)
        parsed = dateparser.parse(date_str, default=default_dt)
    except (ValueError, OverflowError):
        return None, False
    if parsed is None:
        return None, False
    parsed_date = parsed.date()
    # If the guessed date is well in the past relative to "today" and the phrase
    # didn't specify a year explicitly, it's more likely next year's occurrence
    # of that month/day (e.g. a syllabus written in August for a January date).
    if not has_explicit_year and (today - parsed_date).days > 180:
        parsed_date = parsed_date.replace(year=parsed_date.year + 1)
    return parsed_date.isoformat(), has_explicit_year


def extract_deadlines_from_text(text: str, today: datetime.date = None):
    """Returns a list of {title, item_type, due_date, source_line, confidence}."""
    if today is None:
        today = datetime.date.today()

    candidates = []
    seen = set()
    rough_lines = re.split(r"[\n\r]+|(?<=[.!?])\s+(?=[A-Z0-9])", text)

    for raw_line in rough_lines:
        line = raw_line.strip()
        if len(line) < 6 or len(line) > 300:
            continue

        item_type, keyword_confident = _classify(line)
        if not item_type:
            continue

        due_date, has_explicit_year = _resolve_date(line, today)
        if not due_date:
            continue

        if keyword_confident and has_explicit_year:
            confidence = "high"
        elif keyword_confident:
            confidence = "medium"
        else:
            confidence = "low"

        key = (due_date, item_type, _clean_title(line).lower())
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "title": _clean_title(line),
            "item_type": item_type,
            "due_date": due_date,
            "source_line": line,
            "confidence": confidence,
        })

    candidates.sort(key=lambda c: c["due_date"])
    return candidates
