"""
AI study assistant + generation, powered by Google Gemini only.

The assistant is NOT limited to the uploaded course material — it uses the
material as its primary, most-trustworthy source (and says so), but is
explicitly allowed to draw on Gemini's general knowledge to fill gaps the
notes don't cover, same as asking Gemini directly.

The API key is configured once at the app level (GEMINI_API_KEY in .env)
— students never enter a key or pick a provider themselves. If it isn't
set, or a call fails, every function here falls back to a local
heuristic (extractive summary / pattern-matched flashcards / plain
keyword search) so the app stays usable with zero configuration, just
without the AI layer.
"""

import os
import re
import json
import random
import logging
import requests

logger = logging.getLogger("ai_service")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# "gemini-flash-latest" is an alias Google keeps pointed at their current
# recommended flash model, so this doesn't go stale the way pinning an
# exact version (e.g. gemini-1.5-flash, since deprecated) eventually does.
# Pin a specific version instead if you need stable, reproducible behavior.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")


def is_available() -> bool:
    return bool(GEMINI_API_KEY)


def _call_gemini(prompt: str) -> str:
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        params={"key": GEMINI_API_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _generate(prompt: str):
    """Returns (text, "gemini") on success, or (None, None) if no key is
    configured or the call failed — callers with a local heuristic fall
    back to that; never raises. Failures ARE logged server-side (with the
    key redacted) so a misconfiguration is diagnosable instead of just
    silently degrading forever."""
    if not GEMINI_API_KEY:
        return None, None
    try:
        return _call_gemini(prompt), "gemini"
    except requests.HTTPError as e:
        body = ""
        try:
            body = e.response.text[:300]
        except Exception:
            pass
        logger.warning("Gemini call failed: HTTP %s calling model '%s' — %s",
                        e.response.status_code if e.response is not None else "?", GEMINI_MODEL, body)
        return None, None
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        logger.warning("Gemini call failed: %s", e)
        return None, None


# ---------------------------------------------------------------------------
# AI study assistant (RAG-grounded, but not RAG-limited — general knowledge
# fills gaps the uploaded material doesn't cover, with persistent chat
# history as context)
# ---------------------------------------------------------------------------

def answer_question(question: str, context_chunks: list, history: list):
    """`history` is a list of {"role", "content"} dicts, oldest first —
    this is what makes the assistant's memory persistent across sessions
    rather than starting fresh every question.

    Returns (answer, provider_used)."""
    context_text = "\n\n".join(f"[Source {i+1}] {c['text']}" for i, c in enumerate(context_chunks))
    history_text = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in history[-10:])

    prompt = (
        "You are a study assistant for one specific course. Prioritize the course "
        "material excerpts below as your primary, most-trustworthy source — but you "
        "are NOT limited to them. If the excerpts don't fully answer the question, "
        "use your own general knowledge to fill the gap, the same way you would if "
        "the student asked you directly with no notes attached. When you do this, "
        "say so briefly (e.g. \"Beyond your uploaded notes:\") so the student can tell "
        "what came from their material versus general knowledge.\n\n"
        f"COURSE MATERIAL EXCERPTS:\n{context_text or '(none uploaded yet for this course)'}\n\n"
        f"RECENT CONVERSATION:\n{history_text or '(none yet)'}\n\n"
        f"STUDENT QUESTION: {question}\n\nANSWER:"
    )
    result, provider = _generate(prompt)
    if result:
        return result, provider

    # Local fallback: no Gemini key configured — do plain keyword retrieval
    # over the uploaded material instead of pretending to generate a real
    # answer, and say plainly that it can't reach outside knowledge either.
    if not context_chunks:
        return (
            "The AI assistant isn't reachable right now (check GEMINI_API_KEY in .env, or "
            "Gemini may be temporarily unavailable) and there's no uploaded material yet to search either.",
            "local heuristic",
        )
    terms = [w for w in re.findall(r"[a-z0-9]+", question.lower()) if len(w) > 2]
    scored = []
    for c in context_chunks:
        score = sum(1 for t in terms if t in c["text"].lower())
        scored.append((score, c["text"]))
    scored.sort(key=lambda x: x[0], reverse=True)
    best = [t for s, t in scored if s > 0][:2]
    if not best:
        return "The AI assistant isn't reachable right now, and no uploaded material matches that question closely.", "local heuristic"
    return (
        "(The AI assistant isn't reachable right now — showing the most relevant excerpt(s) "
        "from your notes instead of a generated answer.)\n\n" + "\n\n---\n\n".join(best),
        "local heuristic",
    )


# ---------------------------------------------------------------------------
# Local heuristic generation (used directly when no provider is configured,
# and as the always-available fallback for summaries/flashcards/quizzes)
# ---------------------------------------------------------------------------

STOPWORDS = set(
    "a an the this that these those and or but if then so of in on at for to from with "
    "is are was were be been being it its as by an into about over under between which who whom "
    "will would can could should shall may might not no do does did has have had you your we our "
    "i he she they them his her their there here".split()
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_WORD_RE = re.compile(r"[a-z0-9]+")
_TERM_DEF_RE = re.compile(r"^(.{2,60}?)\s*[:\u2013-]\s+(.{3,})$")
_IS_ARE_RE = re.compile(r"^(.{2,60}?)\s+(is|are|refers to|means)\s+(.{5,})$", re.IGNORECASE)


def _split_sentences(text):
    text = re.sub(r"\s+", " ", text).strip()
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()] if text else []


def _local_summarize(text, max_sentences=5):
    sentences = _split_sentences(text)
    if len(sentences) <= max_sentences:
        return sentences
    freq = {}
    for s in sentences:
        for w in _WORD_RE.findall(s.lower()):
            if len(w) < 3 or w in STOPWORDS:
                continue
            freq[w] = freq.get(w, 0) + 1
    scored = []
    for idx, s in enumerate(sentences):
        words = _WORD_RE.findall(s.lower())
        score = sum(freq.get(w, 0) for w in words) / len(words) if words else 0
        scored.append((idx, s, score))
    top = sorted(scored, key=lambda t: t[2], reverse=True)[:max_sentences]
    top.sort(key=lambda t: t[0])
    return [s for _, s, _ in top]


def _local_flashcards(text, limit=12):
    cards = []
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        m = _TERM_DEF_RE.match(line)
        if m:
            cards.append({"q": f"What is {m.group(1).rstrip('.')}?", "a": m.group(2)})
    if len(cards) < 3:
        for s in _split_sentences(text):
            m2 = _IS_ARE_RE.match(s)
            if m2 and len(cards) < limit:
                cards.append({"q": f"What {m2.group(2).lower()} {m2.group(1)}?", "a": m2.group(3).rstrip(".")})
    seen, unique = set(), []
    for c in cards:
        if c["q"] in seen:
            continue
        seen.add(c["q"])
        unique.append(c)
        if len(unique) >= limit:
            break
    return unique


def generate_summary(text: str):
    prompt = f"Summarize the following course material in 4-6 sentences, plain language:\n\n{text[:6000]}"
    result, provider = _generate(prompt)
    if result:
        return result, provider
    return " ".join(_local_summarize(text, 5)), "local heuristic"


def generate_flashcards(text: str, count: int = 10):
    prompt = (
        f"Create {count} flashcards from the course material below. "
        'Respond as a JSON array only, like [{"q": "...", "a": "..."}], no other text.\n\n'
        f"{text[:6000]}"
    )
    result, provider = _generate(prompt)
    if result:
        try:
            cleaned = re.sub(r"^```json|```$", "", result.strip(), flags=re.MULTILINE).strip()
            cards = json.loads(cleaned)
            if isinstance(cards, list) and cards:
                return cards[:count], provider
        except (json.JSONDecodeError, TypeError):
            pass
    return _local_flashcards(text, count), "local heuristic"


def generate_quiz(text: str, num_questions: int = 5):
    """Multiple-choice quiz. With Gemini configured, ask it directly for
    JSON. Without a key, build MCQs out of the local flashcard extractor,
    using other cards' answers as distractors."""
    prompt = (
        f"Create a {num_questions}-question multiple choice quiz from the course material below. "
        'Respond as JSON only: [{"question": "...", "options": ["...","...","...","..."], '
        '"correct_index": 0, "explanation": "..."}]\n\n'
        f"{text[:6000]}"
    )
    result, provider = _generate(prompt)
    if result:
        try:
            cleaned = re.sub(r"^```json|```$", "", result.strip(), flags=re.MULTILINE).strip()
            quiz = json.loads(cleaned)
            if isinstance(quiz, list) and quiz:
                return quiz[:num_questions], provider
        except (json.JSONDecodeError, TypeError):
            pass

    cards = _local_flashcards(text, max(num_questions * 2, 8))
    if len(cards) < 2:
        return [], "local heuristic"
    quiz = []
    all_answers = [c["a"] for c in cards]
    for c in cards[:num_questions]:
        distractor_pool = [a for a in all_answers if a != c["a"]]
        random.shuffle(distractor_pool)
        options = distractor_pool[:3] + [c["a"]]
        random.shuffle(options)
        quiz.append({
            "question": c["q"], "options": options, "correct_index": options.index(c["a"]),
            "explanation": f"From the material: {c['a']}",
        })
    return quiz, "local heuristic"
