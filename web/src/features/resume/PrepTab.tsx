import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, errorMessage } from '../../api';
import type { PlanItem, Question, Review, Round } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Alert, Bar, cx, EmptyState } from '../../components/ui';
import { matchColor } from '../../lib/format';
import { qk, useAiProvider } from '../../lib/queries';
import { useUi } from '../../state/ui';

const YOU = { strong: ['st-strong', 'Strong'], some: ['st-some', 'Some'], gap: ['st-gap', 'Gap'] } as const;
const ROUNDS: Round[] = ['llm', 'design', 'fund', 'code', 'behav'];

export function roundLabel(r: Round, role: string): string {
  return { fund: 'ML fundamentals', llm: role === 'ML Engineer' ? 'Applied ML' : 'LLM and GenAI', design: 'System design', code: 'Python coding', behav: 'Behavioural' }[r];
}

function usePatchReview(role: string) {
  const qc = useQueryClient();
  const optimistic = (fn: (r: Review) => Review) => {
    const prev = qc.getQueryData<Review | null>(qk.review(role));
    qc.setQueryData<Review | null>(qk.review(role), (r) => (r ? fn(r) : r));
    return { prev };
  };
  const rollback = (ctx?: { prev: Review | null | undefined }) => {
    if (ctx && ctx.prev !== undefined) qc.setQueryData(qk.review(role), ctx.prev);
  };
  const plan = useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) => api.patchPlan(id, done),
    onMutate: ({ id, done }) => optimistic((r) => ({ ...r, prep: r.prep && { ...r.prep, plan: r.prep.plan.map((p) => (p.id === id ? { ...p, done } : p)) } })),
    onError: (_e, _v, ctx) => rollback(ctx),
  });
  const question = useMutation({
    mutationFn: ({ id, practised }: { id: string; practised: boolean }) => api.patchQuestion(id, practised),
    onMutate: ({ id, practised }) => optimistic((r) => ({ ...r, prep: r.prep && { ...r.prep, questions: r.prep.questions.map((q) => (q.id === id ? { ...q, practised } : q)) } })),
    onError: (_e, _v, ctx) => rollback(ctx),
  });
  return { plan, question };
}

export function PrepTab({ review, role }: { review: Review; role: string }) {
  const ui = useUi();
  const aip = useAiProvider();
  const { plan: patchPlan, question: patchQ } = usePatchReview(role);
  const [round, setRound] = useState<Round>('llm');
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const prep = review.prep;

  if (!prep)
    return (
      <section className="card">
        <EmptyState icon="resume" title="No prep plan in this review">
          Re-analyse to build a prep plan and interview questions for {role}.
        </EmptyState>
      </section>
    );

  const rows = prep.demand;
  const strong = rows.filter((r) => r.you === 'strong').length;
  const some = rows.filter((r) => r.you === 'some').length;
  const cov = rows.length ? Math.round(((strong + some * 0.5) / rows.length) * 100) : 0;
  const nDone = prep.plan.filter((p) => p.done).length;
  const planPct = prep.plan.length ? Math.round((nDone / prep.plan.length) * 100) : 0;
  const openAll = review.issues.filter((i) => i.status === 'open').length;
  const readiness = Math.round((review.overall + cov + planPct) / 3);
  const estimated = prep.demand_source === 'estimate';
  const scale = prep.demand_scale || prep.matched_jobs || Math.max(1, ...rows.map((r) => r.jobs));
  const totalHours = prep.plan.reduce((a, p) => a + p.hours, 0);
  const qs = prep.questions;
  const practisedN = qs.filter((q) => q.practised).length;
  const parts = [
    { label: 'Resume', v: review.overall, help: `${openAll} review items open` },
    { label: 'Skills coverage', v: cov, help: `${strong} strong, ${some} partial, ${rows.length - strong - some} gaps` },
    { label: 'Prep plan', v: planPct, help: `${nDone} of ${prep.plan.length} tasks done` },
  ];
  const fmtHours = (h: number) => `${Math.round(h * 10) / 10} h`;

  return (
    <>
      {(patchPlan.error || patchQ.error) && (
        <Alert tone="danger" title="Couldn't save that change">
          {errorMessage(patchPlan.error ?? patchQ.error)}
        </Alert>
      )}
      <section className="card ready" aria-label={`${role} readiness`}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, paddingRight: 8 }}>
          <span className="eyebrow">{role} readiness</span>
          <span>
            <span className="bigscore-xl num">{readiness}</span>
            <span className="muted" style={{ fontSize: 15 }}>
              %
            </span>
          </span>
          <span className="help num">{estimated ? 'Based on typical listings (estimated)' : `Based on ${prep.matched_jobs} matched jobs`}</span>
        </div>
        {parts.map((p) => (
          <div className="ready-part" key={p.label}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ fontWeight: 500 }}>{p.label}</span>
              <span className="mono" style={{ fontWeight: 600 }}>
                {p.v}
              </span>
            </div>
            <Bar value={p.v} color={matchColor(p.v / 100)} />
            <span className="help">{p.help}</span>
          </div>
        ))}
      </section>

      <div className="two">
        <section className="card" style={{ overflow: 'hidden' }}>
          <div className="sechead">
            <div>
              <h2 className="h2" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                What your matched jobs ask for
                {estimated && <span className="pill st-warn">Estimated</span>}
              </h2>
              <div className="help num">
                {estimated
                  ? `Estimated per ${scale} typical ${role} postings, because few matching jobs were cached. Compared with your resume.`
                  : `Skills mentioned across ${prep.matched_jobs} ${role} listings, compared with your resume`}
              </div>
            </div>
          </div>
          {[...rows]
            .sort((a, b) => b.jobs - a.jobs)
            .map((d) => (
              <div className="dmrow" key={d.skill}>
                <span style={{ fontWeight: 500 }}>{d.skill}</span>
                <Bar value={(d.jobs / scale) * 100} color="var(--text-3)" />
                <span className="mono help" style={{ textAlign: 'right' }}>
                  {d.jobs}/{scale}
                </span>
                <span>
                  <span className={`pill ${YOU[d.you][0]}`}>{YOU[d.you][1]}</span>
                </span>
              </div>
            ))}
          <div className="help" style={{ padding: '10px 16px', background: 'var(--surface-2)', borderTop: '1px solid var(--border)' }}>
            {prep.note ? `${prep.note} ` : ''}Strong: on your resume with evidence. Some: mentioned without results. Gap: not on your resume. Only add a skill once you've used it.
          </div>
        </section>

        <section className="card" style={{ overflow: 'hidden' }}>
          <div className="sechead">
            <div>
              <h2 className="h2">Two-week prep plan</h2>
              <div className="help num">
                {nDone} of {prep.plan.length} done · about {fmtHours(totalHours)} in total
              </div>
            </div>
            <Bar value={planPct} color="var(--accent)" style={{ width: 120 }} />
          </div>
          {([1, 2] as const).map((w) => {
            const items = prep.plan.filter((p) => p.week === w);
            if (!items.length) return null;
            return (
              <div key={w}>
                <div className="planwk">
                  <span>Week {w}</span>
                  <span className="help num">{fmtHours(items.reduce((a, p) => a + p.hours, 0))}</span>
                </div>
                {items.map((it: PlanItem) => (
                  <label key={it.id} className={cx('planitem', it.done && 'planitem-done')}>
                    <input type="checkbox" checked={it.done} onChange={() => patchPlan.mutate({ id: it.id, done: !it.done })} />
                    <span className="ptext">{it.text}</span>
                    <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      <span className="pill st-skipped">{it.type}</span>
                      <span className="mono help">{it.time}</span>
                    </span>
                  </label>
                ))}
              </div>
            );
          })}
        </section>
      </div>

      <section className="card" style={{ overflow: 'hidden' }}>
        <div className="sechead">
          <div>
            <h2 className="h2">Likely interview questions</h2>
            <div className="help num">
              Picked for {role} roles and your resume · practised {practisedN} of {qs.length}
            </div>
          </div>
          <div className="chips" role="group" aria-label="Interview round">
            {ROUNDS.filter((r) => qs.some((q) => q.round === r)).map((r) => (
              <button key={r} className={cx('chip', round === r && 'chip-on')} aria-pressed={round === r} onClick={() => setRound(r)}>
                {roundLabel(r, role)} · {qs.filter((q) => q.round === r).length}
              </button>
            ))}
          </div>
        </div>
        {qs
          .filter((q) => q.round === round)
          .map((q: Question) => {
            const isOpen = !!open[q.id];
            return (
              <div className="qcard" key={q.id}>
                <button className="qhead" onClick={() => setOpen({ ...open, [q.id]: !isOpen })} aria-expanded={isOpen} aria-controls={`q-${q.id}`}>
                  <span style={{ display: 'flex', gap: 10, alignItems: 'center', minWidth: 0 }}>
                    {q.practised && <Icon name="check" small label="Practised" style={{ color: 'var(--success)' }} />}
                    <span className="qtext">{q.q}</span>
                  </span>
                  <Icon name="chevDown" small style={{ transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }} />
                </button>
                {isOpen && (
                  <div className="qbody" id={`q-${q.id}`}>
                    <div>
                      <div className="eyebrow">What a strong answer covers</div>
                      <ul>
                        {q.outline.map((o) => (
                          <li key={o}>{o}</li>
                        ))}
                      </ul>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                      <div className="help">{q.why}</div>
                      {q.from_resume && (
                        <div className="fromres">
                          <div className="eyebrow" style={{ color: 'var(--accent-text)' }}>
                            Use from your resume
                          </div>
                          {q.from_resume}
                        </div>
                      )}
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        <button className="btn btn-sm btn-primary" onClick={() => ui.openInterview({ questionId: q.id, question: q.q, role, round: roundLabel(q.round, role) })}>
                          <Icon name="chat" small />
                          Practise with {aip.short}
                        </button>
                        <button className="btn btn-sm" onClick={() => patchQ.mutate({ id: q.id, practised: !q.practised })}>
                          {q.practised ? 'Practised · undo' : 'Mark practised'}
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
      </section>
    </>
  );
}
