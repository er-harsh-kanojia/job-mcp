"""Answer application-form / chatbot questions from config.autofill.

``answer_question`` returns a string answer or ``None`` when the question is not
recognised. Callers must treat ``None`` as "stop and report" rather than guess.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Iterable

# Aliases that map phrases found in questions to config.autofill.experience keys.
SKILL_ALIASES = {
    "ml": "machine learning",
    "machine-learning": "machine learning",
    "dl": "deep learning",
    "natural language processing": "nlp",
    "natural language": "nlp",
    "gen ai": "generative ai",
    "genai": "generative ai",
    "gen-ai": "generative ai",
    "generative artificial intelligence": "generative ai",
    "large language model": "llm",
    "large language models": "llm",
    "llms": "llm",
    "sklearn": "scikit-learn",
    "scikit learn": "scikit-learn",
    "cv": "computer vision",
    "opencv": "computer vision",
    "image processing": "computer vision",
    "retrieval augmented generation": "rag",
    "retrieval-augmented generation": "rag",
    "tf": "tensorflow",
    "torch": "pytorch",
    "ml ops": "mlops",
    "ml-ops": "mlops",
    "python3": "python",
    "artificial intelligence": "machine learning",
    "ai/ml": "machine learning",
    "ai ml": "machine learning",
    "data science": "machine learning",
}

YES_WORDS = ("yes", "y", "true", "agree", "i agree", "accept")
NO_WORDS = ("no", "n", "false", "disagree")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+#/.\- ]+", " ", (text or "").lower())).strip()


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def _first_name(name: str) -> str:
    return (name or "").split()[0] if name else ""


def _last_name(name: str) -> str:
    parts = (name or "").split()
    return " ".join(parts[1:]) if len(parts) > 1 else ""


def _city(location: str) -> str:
    return (location or "").split(",")[0].strip()


def notice_days(notice: str) -> int:
    """'30 days' -> 30, '1 month' -> 30, 'Immediate' -> 0."""
    t = (notice or "").lower()
    if not t:
        return -1
    if "immediate" in t:
        return 0
    m = re.search(r"(\d+)\s*(day|week|month)?", t)
    if not m:
        return -1
    n, unit = int(m.group(1)), (m.group(2) or "day")
    return n * (30 if unit == "month" else 7 if unit == "week" else 1)


def find_skill(question: str, skill_years: dict[str, str]) -> str | None:
    """Find which configured skill a question is about (fuzzy). Returns the key."""
    q = " " + _norm(question).replace("/", " / ") + " "
    keys = sorted(skill_years, key=len, reverse=True)
    for k in keys:  # exact phrase match first (longest wins)
        if " " + k + " " in q or (" " + k.replace("-", " ") + " ") in q.replace("-", " "):
            return k
    for alias, target in sorted(SKILL_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if target in skill_years and (" " + alias + " ") in q:
            return target
    # fuzzy on individual words / bigrams (e.g. "pytorh", "langchian")
    words = re.findall(r"[a-z0-9+#\-]+", q)
    grams = words + [" ".join(words[i:i + 2]) for i in range(len(words) - 1)]
    best, best_ratio = None, 0.0
    for g in grams:
        if len(g) < 4:
            continue
        for k in keys:
            r = difflib.SequenceMatcher(None, g, k).ratio()
            if r > best_ratio:
                best, best_ratio = k, r
    return best if best_ratio >= 0.85 else None


def _num(text: str) -> str | None:
    m = re.search(r"\d+(?:\.\d+)?", str(text or ""))
    return m.group(0) if m else None


def _ctc_value(lakhs: str, question: str) -> str:
    """Return CTC in lakhs, or in full rupees when the question asks for that."""
    q = question.lower()
    try:
        val = float(lakhs)
    except (TypeError, ValueError):
        return str(lakhs)
    in_lakhs = _has(q, r"lakh", r"\blpa\b", r"\blacs?\b", r"\bl\b", r"in l\b")
    in_rupees = _has(q, r"rupees", r"\binr\b", r"₹", r"absolute", r"per annum", r"\bannual\b")
    if in_rupees and not in_lakhs:
        return str(int(round(val * 100000)))
    return f"{val:g}"


def answer_question(question: str, profile: dict, kind: str = "text",
                    options: Iterable[str] | None = None) -> str | None:
    """Best answer for a question, or None if we cannot answer it confidently.

    kind: "text" | "number" | "select" | "radio" | "checkbox" | "textarea" | "date"
    options: visible choices for select/radio/checkbox questions.
    """
    q = _norm(question)
    if not q:
        return None
    af: dict[str, Any] = profile.get("autofill") or {}
    skill_years = {str(k).lower(): str(v) for k, v in (af.get("experience") or {}).items()}
    total_exp = str(af.get("total_experience") or profile.get("experience_years") or "")
    options = [o for o in (options or []) if str(o).strip()]
    answer: str | None = None

    # --- identity / contact -------------------------------------------------
    if _has(q, r"\bfirst name\b"):
        answer = _first_name(profile.get("name", ""))
    elif _has(q, r"\blast name\b", r"\bsurname\b", r"\bfamily name\b"):
        answer = _last_name(profile.get("name", ""))
    elif _has(q, r"^(full )?name$", r"\bfull name\b", r"\byour name\b") and "company" not in q:
        answer = profile.get("name") or None
    elif _has(q, r"e ?mail"):
        answer = profile.get("email") or None
    elif _has(q, r"\bphone\b", r"\bmobile\b", r"contact number", r"whatsapp"):
        answer = re.sub(r"[^\d+]", "", profile.get("phone", "")) or None

    # --- compensation -------------------------------------------------------
    elif _has(q, r"expected", r"desired", r"\becpt?c\b") and _has(q, r"ctc", r"salary", r"compensation", r"package", r"pay"):
        answer = _ctc_value(af.get("expected_ctc", ""), question) if af.get("expected_ctc") else None
    elif _has(q, r"\bctc\b", r"current salary", r"current compensation", r"current package",
              r"present salary", r"\bcctc\b", r"salary"):
        answer = _ctc_value(af.get("current_ctc", ""), question) if af.get("current_ctc") else None

    # --- notice period / joining -------------------------------------------
    elif _has(q, r"notice period", r"\bnotice\b"):
        if _has(q, r"serving", r"are you (currently )?in"):
            answer = "No" if "currently working" in str(af.get("last_working_day", "")).lower() else "Yes"
        else:
            nd = notice_days(af.get("notice_period", ""))
            answer = (str(nd) if kind == "number" else af.get("notice_period")) if nd >= 0 else None
    elif _has(q, r"last working day", r"\blwd\b"):
        answer = af.get("last_working_day") or None
    elif _has(q, r"immediate(ly)? join", r"join immediately", r"immediate joiner"):
        nd = notice_days(af.get("notice_period", ""))
        answer = "Yes" if 0 <= nd <= 15 else "No" if nd > 15 else None
    elif m := re.search(r"join (?:with)?in (\d+)\s*(day|week|month)", q):
        nd = notice_days(af.get("notice_period", ""))
        limit = int(m.group(1)) * (30 if m.group(2) == "month" else 7 if m.group(2) == "week" else 1)
        answer = ("Yes" if nd <= limit else "No") if nd >= 0 else None

    # (checked before "experience" because it also mentions a "year")
    elif _has(q, r"graduat(ion|ed)? year", r"year of (graduation|passing)", r"passing year", r"passout"):
        answer = str(af.get("graduation_year") or "") or None
    # --- experience ---------------------------------------------------------
    elif _has(q, r"experience", r"\byears?\b", r"\byrs\b", r"how long have you"):
        skill = find_skill(question, skill_years)
        if skill:
            answer = skill_years[skill]
        elif _has(q, r"total", r"overall", r"relevant experience", r"professional experience",
                  r"work experience", r"^experience$", r"how many years of experience do you have$",
                  r"years of experience\??$"):
            answer = total_exp or None
        else:
            answer = None  # experience in a skill we know nothing about -> don't guess

    # --- location -----------------------------------------------------------
    elif _has(q, r"relocat"):
        answer = "Yes"
    elif _has(q, r"preferred (work )?location", r"preferred city", r"location preference"):
        prefs = af.get("preferred_locations") or []
        if options:
            for p in prefs:
                hit = _match_option(p, options)
                if hit:
                    return hit
            return None
        answer = ", ".join(prefs) or None
    elif _has(q, r"current (city|location)", r"where are you (currently )?(based|located)",
              r"^(city|location)$", r"your location", r"which city", r"home town|hometown"):
        answer = _city(profile.get("location", "")) or None

    # --- other personal fields ---------------------------------------------
    elif _has(q, r"gender"):
        answer = (af.get("gender") or "").capitalize() or None
    elif _has(q, r"date of birth", r"\bdob\b", r"birth date"):
        answer = af.get("date_of_birth") or None
    elif _has(q, r"highest (qualification|education|degree)", r"qualification", r"education"):
        answer = af.get("highest_qualification") or None
    elif _has(q, r"cloud") and _has(q, r"primary", r"which", r"preferred", r"work(ed)? on"):
        answer = af.get("primary_cloud") or None
    elif _has(q, r"contract"):
        answer = af.get("contract_based") or None
    elif _has(q, r"offer in hand", r"holding (an|any) offer", r"other offers?", r"\boffers?\b"):
        answer = af.get("offer_in_hand") or None

    # --- yes/no defaults ----------------------------------------------------
    elif _has(q, r"sponsorship", r"\bvisa\b", r"\bh1b?\b"):
        answer = "No"
    elif _has(q, r"authori[sz]ed to work", r"legally (eligible|allowed|permitted)", r"right to work",
              r"eligible to work"):
        answer = "Yes"
    elif _has(q, r"(full.?time|part.?time|permanent|contract\w*) employee (with|of|at|in)\b",
              r"\b(been )?employed (with|by|at)\b", r"\bworked as an? (full.?time )?employee\b"):
        # "Have you worked as a full-time employee with InfoEdge?": Yes only for a
        # company listed in autofill.previous_employers.
        employers = [_norm(e) for e in (af.get("previous_employers") or []) if str(e).strip()]
        answer = "Yes" if any(e and e in _norm(question) for e in employers) else "No"
    elif _has(q, r"disabilit", r"criminal", r"convicted", r"previously (worked|employed|applied)",
              r"worked (with|for) us", r"ex.?employee", r"related to anyone"):
        answer = "No"
    elif _has(q, r"\bconsent\b", r"\bagree\b", r"acknowledge", r"privacy", r"terms",
              r"background (check|verification)", r"\bbgv\b"):
        answer = "Yes"
    elif _has(q, r"comfortable", r"willing", r"are you (ok|okay|fine|open|able|available)",
              r"can you (work|commute|attend|join)", r"work from office", r"\bwfo\b", r"hybrid",
              r"on.?site", r"interested in", r"do you have (a |your own )?laptop",
              r"rotational shifts?", r"night shifts?", r"(face to face|f2f|in.?person) interview",
              r"reliable (transport|internet)"):
        answer = "Yes"
    elif _has(q, r"^do you (know|have (experience|knowledge|hands.?on))",
              r"have you (ever )?(worked|used|built|developed|deployed|implemented|designed|created)",
              r"are you (familiar|proficient|experienced)", r"hands.?on"):
        skill = find_skill(question, skill_years)
        if skill:
            try:
                answer = "Yes" if float(skill_years[skill]) > 0 else "No"
            except ValueError:
                answer = None

    if answer is None or answer == "":
        return None
    answer = str(answer)

    if kind == "number":
        return _num(answer)
    if options and kind in ("radio", "select", "checkbox", "chips"):
        opts_norm = {_norm(o) for o in options}
        if opts_norm and opts_norm <= set(YES_WORDS + NO_WORDS) and _num(answer) == answer:
            # numeric answer (years) to a yes/no question: "do you have X experience?"
            answer = "Yes" if float(answer) > 0 else "No"
        return _match_option(answer, options)
    return answer


def _option_number(opt: str) -> float | None:
    o = opt.lower()
    if "immediate" in o or o.strip() in ("fresher", "0"):
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)", o)
    if not m:
        return None
    n = float(m.group(1))
    if "month" in o:
        n *= 30
    elif "week" in o:
        n *= 7
    return n


def _match_option(answer: str, options: list[str]) -> str | None:
    """Map an answer to one of the offered options."""
    a = _norm(answer)
    norm_opts = [(_norm(o), o) for o in options]
    for no, o in norm_opts:
        if no == a:
            return o
    if a in YES_WORDS or a in NO_WORDS:
        want = YES_WORDS if a in YES_WORDS else NO_WORDS
        for no, o in norm_opts:
            if no in want or no.split(" ")[0] in want:
                return o
        return None
    for no, o in norm_opts:
        if a and (a in no or no in a) and len(no) > 1:
            return o
    # numeric closeness (years, days, CTC ranges like "0-5", "1 month")
    a_num = _option_number(answer)
    if "day" in a or "month" in a or "week" in a or "immediate" in a:
        a_num = float(notice_days(answer))
    if a_num is not None:
        best, best_d = None, None
        for _, o in norm_opts:
            rng = re.findall(r"\d+(?:\.\d+)?", o)
            if len(rng) >= 2 and "month" not in o.lower() and "day" not in o.lower():
                lo, hi = float(rng[0]), float(rng[1])
                if lo <= a_num <= hi:
                    return o
                d = min(abs(a_num - lo), abs(a_num - hi))
            else:
                n = _option_number(o)
                if n is None:
                    continue
                if re.search(r"\+|above|more than|or more", o.lower()) and a_num >= n:
                    d = 0.0
                elif re.search(r"less than|or less|below|within", o.lower()) and a_num <= n:
                    d = 0.0
                else:
                    d = abs(a_num - n)
            if best_d is None or d < best_d:
                best, best_d = o, d
        if best is not None:
            return best
    close = difflib.get_close_matches(a, [no for no, _ in norm_opts], n=1, cutoff=0.75)
    if close:
        return next(o for no, o in norm_opts if no == close[0])
    return None
