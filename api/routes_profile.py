"""Profile (config.json) and resume upload. The credentials block is never
read out, returned, logged or modified here."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from fastapi import APIRouter, Body, File, UploadFile

from tools.ai.review import resume_file_info
from tools.config import data_dir, get_profile, resume_path, update_config

from .errors import ApiError

router = APIRouter(prefix="/api")

MAX_RESUME_BYTES = 5 * 1024 * 1024
RESUME_EXTS = {".pdf", ".doc", ".docx"}
AUTOFILL_STR_KEYS = ("current_ctc", "expected_ctc", "total_experience", "notice_period", "gender",
                     "highest_qualification", "graduation_year", "primary_cloud", "contract_based",
                     "offer_in_hand", "last_working_day")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def profile_out() -> dict:
    prof = get_profile()  # already without credentials
    af = prof.get("autofill") or {}
    autofill = {k: ("" if af.get(k) is None else str(af.get(k))) for k in AUTOFILL_STR_KEYS}
    autofill["experience"] = {str(k): str(v) for k, v in (af.get("experience") or {}).items()}
    autofill["preferred_locations"] = [str(x) for x in (af.get("preferred_locations") or [])]
    for k, v in af.items():  # pass through any other (non-secret) autofill keys
        if k not in autofill and k != "credentials":
            autofill[k] = v
    return {"name": prof.get("name") or "", "email": prof.get("email") or "",
            "phone": prof.get("phone") or "", "location": prof.get("location") or "",
            "experience_years": prof.get("experience_years") or 0,
            "excluded_companies": prof.get("excluded_companies") or [],
            "resume": resume_file_info(resume_path()), "autofill": autofill}


@router.get("/profile")
async def get_profile_route():
    return profile_out()


# --------------------------------------------------------------- validation

def _number(v: Any, lo: float, hi: float) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        x = float(str(v).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return x if lo <= x <= hi else None


def _num_str(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def normalize_phone(v: Any) -> str | None:
    """10-digit Indian mobile number (accepts +91 / 91 / 0 prefixes, spaces, dashes)."""
    digits = re.sub(r"[\s\-().]", "", str(v or ""))
    if digits.startswith("+"):
        digits = digits[1:]
        if not digits.startswith("91"):
            return None
    if not digits.isdigit():
        return None
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 and digits[0] in "6789" else None


def validate_profile(body: dict) -> tuple[dict, dict, dict]:
    """(top-level updates, autofill updates, errors {field: message})."""
    top: dict[str, Any] = {}
    af: dict[str, Any] = {}
    errors: dict[str, str] = {}

    def text(field: str, v: Any, max_len: int = 200, required: bool = False) -> str | None:
        if v is None:
            v = ""
        if not isinstance(v, (str, int, float)) or isinstance(v, bool):
            errors[field] = "Must be text."
            return None
        s = str(v).strip()
        if required and not s:
            errors[field] = "Required."
            return None
        if len(s) > max_len:
            errors[field] = f"Too long (max {max_len} characters)."
            return None
        return s

    if "name" in body:
        s = text("name", body["name"], 100, required=True)
        if s is not None:
            top["name"] = s
    if "email" in body:
        s = text("email", body["email"], 254, required=True)
        if s is not None:
            if EMAIL_RE.match(s):
                top["email"] = s
            else:
                errors["email"] = "Enter a valid e-mail address."
    if "phone" in body:
        ph = normalize_phone(body["phone"])
        if ph is None:
            errors["phone"] = "Enter a 10-digit Indian mobile number (e.g. 98765 43210)."
        else:
            top["phone"] = ph
    if "location" in body:
        s = text("location", body["location"], 120)
        if s is not None:
            top["location"] = s
    if "experience_years" in body:
        x = _number(body["experience_years"], 0, 50)
        if x is None or not float(x).is_integer():
            errors["experience_years"] = "Whole number of years between 0 and 50."
        else:
            top["experience_years"] = int(x)
    if "excluded_companies" in body:
        ex = body["excluded_companies"]
        if not isinstance(ex, list) or not all(isinstance(x, str) for x in ex):
            errors["excluded_companies"] = "Must be a list of company names."
        else:
            top["excluded_companies"] = [x.strip() for x in ex if x.strip()][:100]

    raw_af = body.get("autofill")
    if raw_af is not None and not isinstance(raw_af, dict):
        errors["autofill"] = "Must be an object."
        raw_af = None
    raw_af = raw_af or {}
    for key in ("current_ctc", "expected_ctc"):
        if key in raw_af:
            v = raw_af[key]
            if v in ("", None):
                af[key] = ""
                continue
            x = _number(v, 0, 1000)
            if x is None:
                errors[f"autofill.{key}"] = "Enter a number in lakhs per annum (e.g. 12.5)."
            else:
                af[key] = _num_str(x)
    if "total_experience" in raw_af:
        v = raw_af["total_experience"]
        x = None if v in ("", None) else _number(v, 0, 50)
        if v not in ("", None) and x is None:
            errors["autofill.total_experience"] = "Enter years as a number between 0 and 50."
        else:
            af["total_experience"] = "" if x is None else _num_str(x)
    if "graduation_year" in raw_af:
        v = raw_af["graduation_year"]
        this_year = date.today().year
        x = None if v in ("", None) else _number(v, 1960, this_year + 6)
        if v not in ("", None) and (x is None or not float(x).is_integer()):
            errors["autofill.graduation_year"] = f"Enter a year between 1960 and {this_year + 6}."
        else:
            af["graduation_year"] = "" if x is None else str(int(x))
    for key in ("contract_based", "offer_in_hand"):
        if key in raw_af:
            v = raw_af[key]
            if isinstance(v, bool):
                af[key] = "Yes" if v else "No"
            else:
                s = text(f"autofill.{key}", v, 20)
                if s is not None:
                    af[key] = s
    for key in ("notice_period", "gender", "highest_qualification", "primary_cloud", "last_working_day"):
        if key in raw_af:
            s = text(f"autofill.{key}", raw_af[key], 120)
            if s is not None:
                af[key] = s
    if "experience" in raw_af:
        exp = raw_af["experience"]
        if not isinstance(exp, dict):
            errors["autofill.experience"] = "Must be an object of {skill: years}."
        else:
            clean = {}
            for skill, years in exp.items():
                sk = str(skill).strip()
                if not sk or len(sk) > 60:
                    errors[f"autofill.experience.{skill}"] = "Skill name must be 1-60 characters."
                    continue
                x = _number(years, 0, 50)
                if x is None:
                    errors[f"autofill.experience.{sk}"] = "Years must be a number between 0 and 50."
                    continue
                clean[sk.lower()] = _num_str(x)
            af["experience"] = clean
    if "preferred_locations" in raw_af:
        locs = raw_af["preferred_locations"]
        if not isinstance(locs, list) or not all(isinstance(x, str) for x in locs):
            errors["autofill.preferred_locations"] = "Must be a list of place names."
        else:
            af["preferred_locations"] = [x.strip() for x in locs if x.strip()][:30]
    known = set(AUTOFILL_STR_KEYS) | {"experience", "preferred_locations"}
    for key, v in raw_af.items():  # other autofill keys: plain values only
        if key in known or key == "credentials":
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            af[key] = v
        else:
            errors[f"autofill.{key}"] = "Unsupported value."
    return top, af, errors


@router.put("/profile")
async def put_profile(body: dict = Body(...)):
    top, af, errors = validate_profile(body)
    if errors:
        raise ApiError(422, "validation", "Some fields are invalid.", errors)
    if top or af:
        update_config(top, af)
    return profile_out()


# ------------------------------------------------------------------ resume

def _safe_name(filename: str, ext: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", filename.rsplit(".", 1)[0]).strip("-.") or "resume"
    return f"{stem[:80]}{ext}"


@router.post("/profile/resume")
async def upload_resume(file: UploadFile = File(...)):
    name = file.filename or ""
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in RESUME_EXTS:
        raise ApiError(422, "validation", "Some fields are invalid.", {"file": "Upload a .pdf, .doc or .docx file."})
    data = await file.read(MAX_RESUME_BYTES + 1)
    if len(data) > MAX_RESUME_BYTES:
        raise ApiError(413, "file_too_large", "The resume must be 5 MB or smaller.", {"file": "Max 5 MB."})
    if not data:
        raise ApiError(422, "validation", "Some fields are invalid.", {"file": "The file is empty."})
    folder = data_dir() / "resume"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / _safe_name(name, ext)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    update_config({"resume_path": str(dest.resolve()).replace("\\", "/")})
    return resume_file_info(dest)
