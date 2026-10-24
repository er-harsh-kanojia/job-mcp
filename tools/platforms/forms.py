"""Generic HTML form handling for multi-step application forms.

``fill_visible_form`` enumerates the visible controls on a page, answers each
empty one from the profile via ``tools.autofill.answer_question`` and reports the
required fields it could not answer, so the caller can stop instead of guessing.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..autofill import answer_question

log = logging.getLogger("job_mcp.forms")

# Enumerate controls, tag each with data-jobmcp="<n>" so Python can target it.
_ENUM_JS = r"""
() => {
  const vis = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const clean = t => (t || '').replace(/\s+/g, ' ').trim();
  const byId = id => document.getElementById(id);
  const labelOf = el => {
    let t = '';
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) t = l.innerText; }
    if (!t && el.getAttribute('aria-labelledby'))
      t = el.getAttribute('aria-labelledby').split(/\s+/).map(i => (byId(i) || {}).innerText || '').join(' ');
    if (!t) t = el.getAttribute('aria-label') || '';
    if (!t) { const l = el.closest('label'); if (l) t = l.innerText; }
    if (!t) t = el.getAttribute('placeholder') || '';
    return clean(t);
  };
  const groupQuestion = el => {
    const rg = el.closest('[role=radiogroup], [role=group], fieldset');
    if (rg) {
      if (rg.getAttribute('aria-labelledby')) {
        const t = rg.getAttribute('aria-labelledby').split(/\s+/).map(i => (byId(i) || {}).innerText || '').join(' ');
        if (clean(t)) return clean(t);
      }
      if (rg.getAttribute('aria-label')) return clean(rg.getAttribute('aria-label'));
      const lg = rg.querySelector('legend'); if (lg) return clean(lg.innerText);
    }
    // nearest preceding text block
    let p = el.parentElement;
    for (let i = 0; i < 5 && p; i++, p = p.parentElement) {
      const lab = p.querySelector('label:not(:has(input)), legend, [class*=question], [class*=label]');
      if (lab && clean(lab.innerText)) return clean(lab.innerText);
    }
    return el.name || '';
  };
  const out = []; const groups = {}; let n = 0;
  document.querySelectorAll('input, textarea, select').forEach(el => {
    const type = (el.tagName === 'INPUT' ? (el.type || 'text') : el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) return;
    if (el.disabled || el.readOnly && type !== 'file') return;
    const required = !!(el.required || el.getAttribute('aria-required') === 'true');
    const id = String(n++); el.setAttribute('data-jobmcp', id);
    if (type === 'radio' || type === 'checkbox') {
      const lab = labelOf(el);
      const visible = vis(el) || vis(el.closest('label')) || (el.id && vis(document.querySelector('label[for="' + CSS.escape(el.id) + '"]')));
      if (!visible) return;
      const key = type + ':' + (el.name || groupQuestion(el) || id);
      if (!groups[key]) {
        groups[key] = {kind: type, question: groupQuestion(el), required: false, options: [], ids: [], checked: []};
        out.push(groups[key]);
      }
      const g = groups[key];
      g.required = g.required || required;
      g.options.push(lab); g.ids.push(id); if (el.checked) g.checked.push(lab);
      return;
    }
    if (type !== 'file' && !vis(el)) return;
    const f = {kind: type === 'select' ? 'select' : type === 'textarea' ? 'textarea' : type,
               question: labelOf(el), required, id, value: el.value || '', options: []};
    if (f.kind === 'select') {
      f.options = Array.from(el.options).map(o => clean(o.text));
      const sel = el.options[el.selectedIndex];
      f.value = sel && sel.value && !/^(select|choose|--)/i.test(clean(sel.text)) ? clean(sel.text) : '';
    }
    out.push(f);
  });
  out.forEach(f => { if (/\*\s*$|\(required\)/i.test(f.question)) f.required = true;
                     f.optional = /\(optional\)/i.test(f.question); });
  return out;
}
"""

TEXT_KINDS = {"text", "email", "tel", "number", "textarea", "url", "date"}


def _clean_q(q: str) -> str:
    return re.sub(r"\s*\*\s*$|\(required\)|\(optional\)", "", q or "", flags=re.I).strip()


async def enumerate_fields(page) -> list[dict]:
    try:
        return await page.evaluate(_ENUM_JS)
    except Exception as exc:
        log.debug("field enumeration failed: %s", exc)
        return []


async def fill_visible_form(page, profile: dict, resume: Path | None = None,
                            treat_unlabelled_as_required: bool = False) -> dict:
    """Fill empty visible fields. Returns {"filled": [...], "unanswered": [...]}.

    ``unanswered`` lists required (or, for Indeed, non-optional) questions we
    could not answer. Nothing is submitted here.
    """
    filled, unanswered = [], []
    for f in await enumerate_fields(page):
        q = _clean_q(f.get("question", ""))
        kind = f["kind"]
        must = f.get("required") or (treat_unlabelled_as_required and not f.get("optional"))
        try:
            if kind == "file":
                if resume and re.search(r"resume|cv|curriculum", q, re.I) or (resume and not q):
                    loc = page.locator(f'[data-jobmcp="{f["id"]}"]')
                    await loc.set_input_files(str(resume))
                    filled.append({"question": q or "resume", "answer": resume.name})
                elif must:
                    unanswered.append(q or "file upload")
                continue
            if kind in TEXT_KINDS:
                if (f.get("value") or "").strip():
                    continue
                ans = answer_question(q, profile, kind="number" if kind == "number" else "text")
                if ans is None:
                    if must:
                        unanswered.append(q or f"{kind} field")
                    continue
                loc = page.locator(f'[data-jobmcp="{f["id"]}"]')
                await loc.fill(str(ans))
                filled.append({"question": q, "answer": ans})
            elif kind == "select":
                if f.get("value"):
                    continue
                opts = [o for o in f.get("options", []) if o and not re.match(r"^(select|choose|--)", o, re.I)]
                ans = answer_question(q, profile, kind="select", options=opts)
                if ans is None:
                    if must:
                        unanswered.append(q or "select")
                    continue
                await page.locator(f'[data-jobmcp="{f["id"]}"]').select_option(label=ans)
                filled.append({"question": q, "answer": ans})
            elif kind in ("radio", "checkbox"):
                if f.get("checked"):
                    continue
                opts = f.get("options", [])
                if kind == "checkbox" and len(opts) == 1:
                    # single consent-style checkbox: the label itself is the question
                    single_q = q if q and q != opts[0] else opts[0]
                    ans = answer_question(single_q, profile, kind="text")
                    if ans and ans.lower().startswith("y"):
                        await _check(page, f["ids"][0])
                        filled.append({"question": single_q, "answer": "checked"})
                    elif must:
                        unanswered.append(single_q)
                    continue
                ans = answer_question(q, profile, kind="radio", options=opts)
                if ans is None or ans not in opts:
                    if must or kind == "radio":
                        unanswered.append(q or "choice")
                    continue
                await _check(page, f["ids"][opts.index(ans)])
                filled.append({"question": q, "answer": ans})
        except Exception as exc:
            log.debug("could not fill %r: %s", q, exc)
            if must:
                unanswered.append(q or kind)
    return {"filled": filled, "unanswered": unanswered}


async def _check(page, field_id: str) -> None:
    loc = page.locator(f'[data-jobmcp="{field_id}"]')
    try:
        await loc.check(timeout=4000)
    except Exception:
        # custom-styled inputs: click the associated label instead
        await loc.check(force=True, timeout=4000)


async def visible_errors(page) -> list[str]:
    """Collect visible validation error messages."""
    js = r"""() => Array.from(document.querySelectorAll(
        '[role=alert], [aria-live=assertive], .error, [class*=error i], [id*=error i]'))
        .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; })
        .map(e => (e.innerText || '').replace(/\s+/g, ' ').trim())
        .filter(t => t && t.length < 300)"""
    try:
        errs = await page.evaluate(js)
    except Exception:
        return []
    seen, out = set(), []
    for e in errs:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out[:10]
