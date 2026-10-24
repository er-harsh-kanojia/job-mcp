"""Downloadable resume-review reports (Markdown, HTML, and PDF rendered from the HTML).

Built from the stored Review dict, so a download never calls the AI again.
"""

from __future__ import annotations

import html
import re
from datetime import datetime

SCORE_LABELS = {"accuracy": "Accuracy", "ats": "ATS readability", "fit": "Role fit", "impact": "Impact"}
SEVERITY = {"mistake": "Mistake", "change": "Change", "polish": "Polish"}
STATUS = {"open": "Open", "fixed": "Fixed", "dismissed": "Dismissed"}
OUTCOME = {"resolved": "Resolved", "partly": "Partly fixed", "still_open": "Still open",
           "not_applicable": "No longer applies"}
YOU = {"strong": "Strong", "some": "Some", "gap": "Gap"}
ROUNDS = {"llm": "LLM and GenAI", "design": "System design", "fund": "ML fundamentals",
          "code": "Python coding", "behav": "Behavioural"}
PROVIDERS = {"anthropic": "Claude", "openai": "ChatGPT", "local": "Local AI"}


def _date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y, %H:%M")
    except (TypeError, ValueError):
        return iso or ""


def filename(review: dict, ext: str) -> str:
    role = re.sub(r"[^A-Za-z0-9]+", "-", review.get("target_role") or "resume").strip("-")
    day = (review.get("analysed_at") or "")[:10]
    return f"Resume-report-{role}-{day}.{ext}"


def _delta(a: float, b: float) -> str:
    d = round(b - a)
    return f"+{d}" if d > 0 else str(d)


# ------------------------------------------------------------------ markdown

def to_markdown(review: dict) -> str:
    r = review
    by = PROVIDERS.get(r.get("provider") or "", "AI")
    out = [f"# Resume report: {r['target_role']}", "",
           f"Resume: **{r.get('resume_filename') or 'resume'}** · Reviewed {_date(r['analysed_at'])} by {by}"
           f" ({r.get('model') or ''})", "",
           f"## Score: {r['overall']} / 100", "",
           f"About {r['projected']} once the open items are fixed.", "",
           "| Score | Value |", "|---|---|"]
    out += [f"| {SCORE_LABELS[k]} | {r['scores'].get(k, 0)} |" for k in SCORE_LABELS]
    out.append("")

    c = r.get("comparison")
    if c:
        out += [f"## Compared with your report from {_date(c['previous_analysed_at'])}", "",
                f"Previous resume: {c.get('previous_filename') or 'resume'} · "
                f"Score {c['overall_before']} → {c['overall_after']} ({_delta(c['overall_before'], c['overall_after'])})",
                "", c.get("summary") or "", "",
                "| Score | Before | Now | Change |", "|---|---|---|---|"]
        for k, label in SCORE_LABELS.items():
            a, b = c["scores_before"].get(k, 0), c["scores_after"].get(k, 0)
            out.append(f"| {label} | {a} | {b} | {_delta(a, b)} |")
        out.append("")
        if c.get("changes"):
            out += ["### What changed", ""] + [f"- {x}" for x in c["changes"]] + [""]
        if c.get("previous"):
            out += ["### Previous issues", ""]
            out += [f"- **{OUTCOME.get(p['outcome'], p['outcome'])}**: {p['title']}"
                    + (f". {p['evidence']}" if p.get("evidence") else "") for p in c["previous"]]
            out.append("")
        new_ids = set(c.get("new_issue_ids") or [])
        if new_ids:
            out += ["### New problems introduced by the changes", ""]
            out += [f"- {i['title']}" for i in r["issues"] if i["id"] in new_ids]
            out.append("")

    out += ["## Issues", ""]
    for n, i in enumerate(r["issues"], 1):
        out += [f"### {n}. {i['title']}",
                f"*{SEVERITY.get(i['severity'], i['severity'])} · {i['where']} · {STATUS.get(i['status'], i['status'])}*",
                "", i.get("why") or ""]
        if i.get("before") or i.get("after"):
            out += ["", f"- **Now:** {i.get('before') or '(missing)'}", f"- **Suggested:** {i.get('after') or ''}"]
        if i.get("note"):
            out += ["", f"> {i['note']}"]
        out.append("")

    p = r.get("prep")
    if p:
        out += [f"## Prepare for {r['target_role']}", "", p.get("note") or "", "",
                "### What matched jobs ask for", "", "| Skill | Jobs | You |", "|---|---|---|"]
        scale = p.get("demand_scale") or p.get("matched_jobs") or 0
        out += [f"| {d['skill']} | {d['jobs']}/{scale} | {YOU.get(d['you'], d['you'])} |" for d in p.get("demand", [])]
        out += ["", "### Two-week plan", ""]
        for wk in (1, 2):
            items = [it for it in p.get("plan", []) if it.get("week") == wk]
            if items:
                out += [f"**Week {wk}**", ""]
                out += [f"- [{'x' if it.get('done') else ' '}] {it['text']} ({it['type']}, {it['time']}, "
                        f"{it['hours']:g} h)" for it in items]
                out.append("")
        out += ["### Likely interview questions", ""]
        for key, label in ROUNDS.items():
            qs = [q for q in p.get("questions", []) if q.get("round") == key]
            if not qs:
                continue
            out += [f"#### {label}", ""]
            for q in qs:
                out += [f"**{q['q']}**", "", f"*{q.get('why') or ''}*", ""]
                out += [f"- {o}" for o in q.get("outline", [])]
                if q.get("from_resume"):
                    out += ["", f"From your resume: {q['from_resume']}"]
                out.append("")
    return "\n".join(out).rstrip() + "\n"


# ------------------------------------------------------------------ html

_CSS = """
*{box-sizing:border-box}body{margin:0;font-family:'Segoe UI',system-ui,-apple-system,sans-serif;color:#16161b;
font-size:12.5px;line-height:1.5}main{max-width:760px;margin:0 auto;padding:28px 8px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:26px 0 8px;padding-bottom:4px;border-bottom:1px solid #e3e3e8}
h3{font-size:13.5px;margin:14px 0 4px}h4{font-size:12.5px;margin:12px 0 4px;color:#4f4f5a;text-transform:uppercase;
letter-spacing:.04em}.sub{color:#4f4f5a;margin:0}.big{font-size:34px;font-weight:700}.muted{color:#676772}
table{border-collapse:collapse;width:100%;margin:6px 0}td,th{border-bottom:1px solid #e3e3e8;padding:5px 8px;
text-align:left}th{background:#f2f2f4;font-weight:600}.num{font-variant-numeric:tabular-nums;text-align:right}
.issue{border:1px solid #e3e3e8;border-radius:8px;padding:10px 12px;margin:8px 0;break-inside:avoid}
.pill{display:inline-block;border-radius:999px;padding:0 8px;font-size:11px;font-weight:600;margin-right:6px}
.mistake{background:#fbe8e5;color:#bf321f}.change{background:#fcf0da;color:#8a5000}.polish{background:#e3eef9;color:#1b66ab}
.resolved{background:#e4f3ea;color:#17794a}.partly{background:#fcf0da;color:#8a5000}.still_open{background:#fbe8e5;color:#bf321f}
.not_applicable{background:#eceef2;color:#555c6b}.diff{display:grid;grid-template-columns:80px 1fr;gap:4px 10px;margin-top:6px}
.k{font-size:10.5px;font-weight:700;color:#676772;text-transform:uppercase}.old{background:#fbe8e5;padding:2px 6px;border-radius:4px}
.new{background:#e4f3ea;padding:2px 6px;border-radius:4px}.note{color:#676772;font-style:italic}
.card{background:#f6f6f7;border-radius:8px;padding:10px 12px;margin:8px 0}ul{margin:4px 0 4px 18px;padding:0}
.q{margin:10px 0;break-inside:avoid}
"""


def _e(s) -> str:
    return html.escape(str(s or ""))


def to_html(review: dict) -> str:
    r = review
    by = PROVIDERS.get(r.get("provider") or "", "AI")
    h = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{_e(filename(r, 'html'))}</title>"
         f"<style>{_CSS}</style></head><body><main>",
         f"<h1>Resume report: {_e(r['target_role'])}</h1>",
         f"<p class='sub'>Resume: <b>{_e(r.get('resume_filename') or 'resume')}</b> · Reviewed "
         f"{_e(_date(r['analysed_at']))} by {_e(by)} ({_e(r.get('model'))})</p>",
         f"<h2>Score</h2><div><span class='big'>{r['overall']}</span><span class='muted'> / 100</span> "
         f"<span class='muted'>· about {r['projected']} once the open items are fixed</span></div>",
         "<table><tr><th>Score</th><th class='num'>Value</th></tr>"]
    h += [f"<tr><td>{SCORE_LABELS[k]}</td><td class='num'>{r['scores'].get(k, 0)}</td></tr>" for k in SCORE_LABELS]
    h.append("</table>")

    c = r.get("comparison")
    if c:
        h += [f"<h2>Compared with your report from {_e(_date(c['previous_analysed_at']))}</h2>",
              f"<p class='sub'>Previous resume: {_e(c.get('previous_filename') or 'resume')} · score "
              f"<b>{c['overall_before']} → {c['overall_after']}</b> ({_delta(c['overall_before'], c['overall_after'])})</p>",
              f"<div class='card'>{_e(c.get('summary'))}</div>",
              "<table><tr><th>Score</th><th class='num'>Before</th><th class='num'>Now</th><th class='num'>Change</th></tr>"]
        for k, label in SCORE_LABELS.items():
            a, b = c["scores_before"].get(k, 0), c["scores_after"].get(k, 0)
            h.append(f"<tr><td>{label}</td><td class='num'>{a}</td><td class='num'>{b}</td>"
                     f"<td class='num'>{_delta(a, b)}</td></tr>")
        h.append("</table>")
        if c.get("changes"):
            h += ["<h3>What changed</h3><ul>"] + [f"<li>{_e(x)}</li>" for x in c["changes"]] + ["</ul>"]
        if c.get("previous"):
            h.append("<h3>Previous issues</h3><ul>")
            h += [f"<li><span class='pill {p['outcome']}'>{OUTCOME.get(p['outcome'], p['outcome'])}</span>"
                  f"{_e(p['title'])}{(' <span class=muted>· ' + _e(p['evidence']) + '</span>') if p.get('evidence') else ''}</li>"
                  for p in c["previous"]]
            h.append("</ul>")
        new_ids = set(c.get("new_issue_ids") or [])
        if new_ids:
            h += ["<h3>New problems introduced by the changes</h3><ul>"]
            h += [f"<li>{_e(i['title'])}</li>" for i in r["issues"] if i["id"] in new_ids]
            h.append("</ul>")

    h.append("<h2>Issues</h2>")
    for n, i in enumerate(r["issues"], 1):
        h.append(f"<div class='issue'><div><span class='pill {i['severity']}'>{SEVERITY.get(i['severity'], '')}</span>"
                 f"<b>{n}. {_e(i['title'])}</b> <span class='muted'>· {_e(i['where'])} · "
                 f"{STATUS.get(i['status'], i['status'])}</span></div><div>{_e(i.get('why'))}</div>")
        if i.get("before") or i.get("after"):
            h.append(f"<div class='diff'><span class='k'>Now</span><span class='old'>{_e(i.get('before') or '(missing)')}</span>"
                     f"<span class='k'>Suggested</span><span class='new'>{_e(i.get('after'))}</span></div>")
        if i.get("note"):
            h.append(f"<div class='note'>{_e(i['note'])}</div>")
        h.append("</div>")

    p = r.get("prep")
    if p:
        scale = p.get("demand_scale") or p.get("matched_jobs") or 0
        h += [f"<h2>Prepare for {_e(r['target_role'])}</h2><p class='sub'>{_e(p.get('note'))}</p>",
              "<h3>What matched jobs ask for</h3><table><tr><th>Skill</th><th class='num'>Jobs</th><th>You</th></tr>"]
        h += [f"<tr><td>{_e(d['skill'])}</td><td class='num'>{d['jobs']}/{scale}</td><td>{YOU.get(d['you'], d['you'])}</td></tr>"
              for d in p.get("demand", [])]
        h.append("</table><h3>Two-week plan</h3>")
        for wk in (1, 2):
            items = [it for it in p.get("plan", []) if it.get("week") == wk]
            if items:
                h.append(f"<h4>Week {wk}</h4><ul>")
                h += [f"<li>{'☑' if it.get('done') else '☐'} {_e(it['text'])} <span class='muted'>· {_e(it['type'])}, "
                      f"{_e(it['time'])}, {it['hours']:g} h</span></li>" for it in items]
                h.append("</ul>")
        h.append("<h3>Likely interview questions</h3>")
        for key, label in ROUNDS.items():
            qs = [q for q in p.get("questions", []) if q.get("round") == key]
            if not qs:
                continue
            h.append(f"<h4>{label}</h4>")
            for q in qs:
                h.append(f"<div class='q'><b>{_e(q['q'])}</b><div class='note'>{_e(q.get('why'))}</div><ul>"
                         + "".join(f"<li>{_e(o)}</li>" for o in q.get("outline", [])) + "</ul>"
                         + (f"<div class='card'><b>From your resume:</b> {_e(q['from_resume'])}</div>"
                            if q.get("from_resume") else "") + "</div>")
    h.append("</main></body></html>")
    return "".join(h)

