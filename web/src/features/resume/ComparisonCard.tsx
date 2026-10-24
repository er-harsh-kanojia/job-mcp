import type { Comparison, Issue, PrevOutcome, ScoreKey } from '../../api/types';
import { Pill } from '../../components/ui';
import { fmtDayTime } from '../../lib/format';

const SCORES: [ScoreKey, string][] = [
  ['accuracy', 'Accuracy'],
  ['impact', 'Impact'],
  ['fit', 'Role fit'],
  ['ats', 'ATS readability'],
];
const OUTCOME: Record<PrevOutcome, [string, string]> = {
  resolved: ['Resolved', 'st-strong'],
  partly: ['Partly fixed', 'st-some'],
  still_open: ['Still open', 'st-gap'],
  not_applicable: ['No longer applies', 'st-skipped'],
};

function Delta({ before, after }: { before: number; after: number }) {
  const d = Math.round(after - before);
  const color = d > 0 ? 'var(--success)' : d < 0 ? 'var(--danger)' : 'var(--text-3)';
  return (
    <span className="mono" style={{ color, fontWeight: 600 }}>
      {d > 0 ? `+${d}` : d}
    </span>
  );
}

/** Progress since an earlier report: score changes, what changed, and what happened to each old issue. */
export function ComparisonCard({ c, issues }: { c: Comparison; issues: Issue[] }) {
  const counts = c.previous.reduce<Record<PrevOutcome, number>>(
    (a, p) => ({ ...a, [p.outcome]: (a[p.outcome] ?? 0) + 1 }),
    { resolved: 0, partly: 0, still_open: 0, not_applicable: 0 },
  );
  const newIssues = issues.filter((i) => c.new_issue_ids.includes(i.id));
  return (
    <section className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }} aria-label="Progress since your previous report">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div>
          <span className="eyebrow">Progress since your report from {fmtDayTime(c.previous_analysed_at)}</span>
          <div className="help">
            Previous file: {c.previous_filename || 'resume'}
            {c.previous_role ? ` · role then: ${c.previous_role}` : ''}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span className="mono help">{c.overall_before}</span>
          <span className="help">→</span>
          <span className="mono" style={{ fontSize: 24, fontWeight: 600 }}>
            {c.overall_after}
          </span>
          <Delta before={c.overall_before} after={c.overall_after} />
        </div>
      </div>

      <p style={{ margin: 0, color: 'var(--text-2)' }}>{c.summary}</p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 10 }}>
        {SCORES.map(([k, label]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '6px 10px', background: 'var(--surface-2)', borderRadius: 8 }}>
            <span>{label}</span>
            <span>
              <span className="mono help">{c.scores_before[k]}→</span>
              <span className="mono">{c.scores_after[k]} </span>
              <Delta before={c.scores_before[k]} after={c.scores_after[k]} />
            </span>
          </div>
        ))}
      </div>

      {!c.identical_resume && (
        <div className="two" style={{ alignItems: 'start' }}>
          <div>
            <h3 className="h2" style={{ fontSize: 14, marginBottom: 6 }}>
              What changed
            </h3>
            {c.changes.length ? (
              <ul style={{ margin: 0, paddingLeft: 18, listStyle: 'disc', display: 'flex', flexDirection: 'column', gap: 4 }}>
                {c.changes.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            ) : (
              <span className="help">No meaningful text changes found.</span>
            )}
            {newIssues.length > 0 && (
              <>
                <h3 className="h2" style={{ fontSize: 14, margin: '12px 0 6px' }}>
                  New problems from these changes
                </h3>
                <ul style={{ margin: 0, paddingLeft: 18, listStyle: 'disc' }}>
                  {newIssues.map((i) => (
                    <li key={i.id}>{i.title}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
          <div>
            <h3 className="h2" style={{ fontSize: 14, marginBottom: 6 }}>
              Previous issues{' '}
              <span className="help num" style={{ fontWeight: 400 }}>
                {counts.resolved} resolved · {counts.partly} partly · {counts.still_open} still open
              </span>
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {c.previous.map((p, i) => (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 8px', alignItems: 'start' }}>
                  <Pill tone={OUTCOME[p.outcome][1]}>{OUTCOME[p.outcome][0]}</Pill>
                  <span>
                    {p.title}
                    {p.previous_status === 'fixed' && p.outcome !== 'resolved' && (
                      <span className="help"> · you marked this fixed</span>
                    )}
                    {p.evidence && <span className="help" style={{ display: 'block' }}>{p.evidence}</span>}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      {c.identical_resume && <span className="help">Upload your edited resume and analyse again to see what changed.</span>}
    </section>
  );
}
