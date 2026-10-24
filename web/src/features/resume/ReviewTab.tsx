import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { api, errorMessage } from '../../api';
import type { Issue, IssueStatus, Review, ScoreKey, Severity } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Alert, Bar, cx, EmptyState } from '../../components/ui';
import { matchColor } from '../../lib/format';
import { qk } from '../../lib/queries';

const SEV: Record<Severity, [string, number]> = { mistake: ['Mistake', 0], change: ['Change', 1], polish: ['Polish', 2] };
const SCORE_ROWS: [ScoreKey, string, (role: string) => string][] = [
  ['accuracy', 'Accuracy', () => 'Dates, contact details and spelling agree with your profile'],
  ['impact', 'Impact', () => 'Bullets show results and numbers, not duties'],
  ['fit', 'Role fit', (r) => `Keywords and focus for ${r}`],
  ['ats', 'ATS readability', () => 'Parses cleanly, standard sections, sensible length'],
];

/** Optimistic PATCH of an issue's status; the server answer replaces overall/projected/issue. */
export function useIssueStatus(role: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: IssueStatus }) => api.patchIssue(id, status),
    onMutate: async ({ id, status }) => {
      await qc.cancelQueries({ queryKey: qk.review(role) });
      const prev = qc.getQueryData<Review | null>(qk.review(role));
      qc.setQueryData<Review | null>(qk.review(role), (r) => (r ? { ...r, issues: r.issues.map((i) => (i.id === id ? { ...i, status } : i)) } : r));
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev !== undefined) qc.setQueryData(qk.review(role), ctx.prev);
    },
    onSuccess: (res) => {
      qc.setQueryData<Review | null>(qk.review(role), (r) =>
        r ? { ...r, overall: res.overall, projected: res.projected, issues: r.issues.map((i) => (i.id === res.issue.id ? res.issue : i)) } : r,
      );
    },
  });
}

export function ReviewTab({ review, role }: { review: Review; role: string }) {
  const issues = review.issues;
  const firstOpen = issues.find((i) => i.status === 'open')?.id ?? null;
  const [active, setActive] = useState<string | null>(firstOpen);
  const [sev, setSev] = useState<'all' | Severity>('all');
  const [showDone, setShowDone] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const patch = useIssueStatus(role);

  const num = useMemo(() => new Map(issues.map((i, ix) => [i.id, ix + 1])), [issues]);
  const open = (i: Issue) => i.status === 'open';
  const visible = issues.filter((i) => (sev === 'all' || i.severity === sev) && (showDone || open(i)));
  const openAll = issues.filter(open).length;

  // Sub-scores: as analysed, plus the gains of fixed issues (overall/projected come from the server).
  const now = useMemo(() => {
    const sc = { ...review.scores };
    issues.forEach((i) => {
      if (i.status === 'fixed') (Object.keys(i.gain) as ScoreKey[]).forEach((k) => (sc[k] = Math.min(100, sc[k] + (i.gain[k] ?? 0))));
    });
    return sc;
  }, [review.scores, issues]);

  const setStatus = (it: Issue, status: IssueStatus) => {
    patch.mutate({ id: it.id, status });
    setCopied(null);
    if (status !== 'open') {
      const next = visible.find((x) => x.id !== it.id && open(x));
      setActive(next ? next.id : null);
    }
  };
  const copy = async (it: Issue) => {
    try {
      await navigator.clipboard.writeText(it.after);
    } catch {
      // clipboard blocked; the suggestion stays visible to copy by hand
    }
    setCopied(it.id);
  };

  return (
    <>
      <section className="card scorecard" aria-label="Resume score">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span className="eyebrow">Resume score</span>
          <span>
            <span className="bigscore-xl num">{review.overall}</span>
            <span className="muted" style={{ fontSize: 15 }}>
              {' '}
              / 100
            </span>
          </span>
          <span className="help num">{review.projected > review.overall && openAll ? `About ${review.projected} once the ${openAll} open items are fixed` : 'Nothing left to fix'}</span>
        </div>
        <div className="subscores">
          {SCORE_ROWS.map(([k, label, help]) => (
            <div className="subscore" key={k}>
              <div className="row">
                <span style={{ fontWeight: 500 }}>{label}</span>
                <span className="mono" style={{ fontWeight: 600 }}>
                  {now[k]}
                </span>
              </div>
              <Bar value={now[k]} color={matchColor(now[k] / 100)} />
              <span className="help">{help(role)}</span>
            </div>
          ))}
        </div>
      </section>

      {patch.error && (
        <Alert tone="danger" title="Couldn't update that item">
          {errorMessage(patch.error)}
        </Alert>
      )}

      <div className="rv-grid">
        <section className="card" style={{ overflow: 'hidden' }} aria-label="Review items">
          <div className="rtool">
            <div className="chips" role="group" aria-label="Filter by type">
              {(
                [
                  ['all', 'All open'],
                  ['mistake', 'Mistakes'],
                  ['change', 'Changes'],
                  ['polish', 'Polish'],
                ] as ['all' | Severity, string][]
              ).map(([k, l]) => (
                <button key={k} className={cx('chip', sev === k && 'chip-on')} aria-pressed={sev === k} onClick={() => setSev(k)}>
                  {l}
                  <span className="cnt num">{issues.filter((i) => (k === 'all' || i.severity === k) && open(i)).length}</span>
                </button>
              ))}
            </div>
            <label className="switch" style={{ fontSize: 12 }}>
              <input type="checkbox" checked={showDone} onChange={() => setShowDone(!showDone)} />
              Show fixed and dismissed
            </label>
          </div>
          {visible.map((it, ix) => {
            const on = active === it.id;
            const done = !open(it);
            const nxt = visible[ix + 1];
            return (
              <div key={it.id} className={cx('issue', on && 'issue-on', done && 'issue-done')}>
                <button className="issue-head" onClick={() => setActive(on ? null : it.id)} aria-expanded={on} aria-controls={`issue-${it.id}`}>
                  <span className={cx('sevn', done ? 'sev-done' : `sev-${it.severity}`)} aria-label={SEV[it.severity][0]}>
                    {num.get(it.id)}
                  </span>
                  <span style={{ minWidth: 0 }}>
                    <span className="issue-title">{it.title}</span>
                    <span className="help" style={{ display: 'block' }}>
                      {SEV[it.severity][0]} · {it.where}
                    </span>
                  </span>
                  <span>{done && <span className="pill st-skipped">{it.status === 'fixed' ? 'Fixed' : 'Dismissed'}</span>}</span>
                </button>
                {on && (
                  <div className="issue-body" id={`issue-${it.id}`}>
                    {it.why && <div style={{ color: 'var(--text-2)' }}>{it.why}</div>}
                    {it.before && (
                      <div className="diff">
                        <span className="diff-k">Now</span>
                        <span className="diff-old">{it.before}</span>
                        <span className="diff-k">Suggested</span>
                        <span className="diff-new">{it.after}</span>
                      </div>
                    )}
                    {it.note && <div className="help">{it.note}</div>}
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {!done && (
                        <>
                          {it.before && it.after && (
                            <button className="btn btn-sm" onClick={() => void copy(it)}>
                              <Icon name={copied === it.id ? 'check' : 'copy'} small />
                              {copied === it.id ? 'Copied' : 'Copy suggestion'}
                            </button>
                          )}
                          <button className="btn btn-sm btn-primary" onClick={() => setStatus(it, 'fixed')}>
                            <Icon name="check" small />
                            Mark fixed
                          </button>
                          <button className="btn btn-sm btn-ghost" onClick={() => setStatus(it, 'dismissed')}>
                            Dismiss
                          </button>
                        </>
                      )}
                      {done && (
                        <button className="btn btn-sm" onClick={() => setStatus(it, 'open')}>
                          Reopen
                        </button>
                      )}
                      {nxt && (
                        <button className="btn btn-sm btn-ghost" onClick={() => setActive(nxt.id)} style={{ marginLeft: 'auto' }}>
                          Next issue
                          <Icon name="chevDown" small />
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {visible.length === 0 && (
            <EmptyState icon="check" title="Nothing left here">
              Every item in this filter is fixed or dismissed. Re-analyse after you update the file to check again.
            </EmptyState>
          )}
        </section>

        <section className="card rv-paper" style={{ overflow: 'hidden', position: 'sticky', top: 68 }} aria-label="Your resume">
          <div className="sechead">
            <div>
              <h2 className="h2">{review.resume_filename}</h2>
              <div className="help">Click a highlighted line to see its suggestion</div>
            </div>
          </div>
          <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)' }} className="legend-sev">
            <span>
              <i className="lg-box rl-mistake" />
              Mistake
            </span>
            <span>
              <i className="lg-box rl-change" />
              Change
            </span>
            <span>
              <i className="lg-box rl-polish" />
              Polish
            </span>
          </div>
          <div className="paper">
            {review.sections.map((sec, si) => (
              <div key={si}>
                {sec.title && <div className="psec-t">{sec.title}</div>}
                {sec.lines.map((l) => {
                  const lineIssues = issues.filter((i) => i.line_ids.includes(l.id) && open(i));
                  const kind = l.kind === 'name' || l.kind === 'role' ? `rl-${l.kind}` : '';
                  if (!lineIssues.length)
                    return (
                      <div key={l.id} className={cx('rl', kind)}>
                        {l.text}
                      </div>
                    );
                  const top = [...lineIssues].sort((a, b) => SEV[a.severity][1] - SEV[b.severity][1])[0];
                  const act = lineIssues.some((i) => i.id === active);
                  const nums = lineIssues.map((i) => num.get(i.id)).join(',');
                  return (
                    <button
                      key={l.id}
                      className={cx('rl', kind, `rl-${top.severity}`, act && 'rl-active')}
                      onClick={() => {
                        setSev('all');
                        setShowDone(false);
                        setActive(act ? active : top.id);
                      }}
                      aria-label={`Issue ${nums}: ${l.text}`}
                    >
                      {l.text}
                      <span className="rl-n">{nums}</span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
