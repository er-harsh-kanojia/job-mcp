import type { Job } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Overlay, PlatformBadge } from '../../components/ui';
import { expLabel, postedLabel, salaryLow, skillMatches } from '../../lib/format';

export function CompareModal({ jobs, mine, onClose, onApply }: { jobs: Job[]; mine: string[]; onClose: () => void; onApply: (urls: string[]) => void }) {
  const cmp = [...jobs].sort((a, b) => b.rank_score - a.rank_score).slice(0, 4);
  if (cmp.length < 2) return null;
  const bestMatch = Math.max(...cmp.map((j) => j.match_score));
  const bestSal = Math.max(...cmp.map((j) => salaryLow(j.salary)));
  const tpl = `132px repeat(${cmp.length}, minmax(170px, 1fr))`;
  const F = (label: string, fn: (j: Job) => string, best?: (j: Job) => boolean) => ({ label, fn, best });
  const fields = [
    F('Company', (j) => j.company),
    F('Location', (j) => j.location),
    F('Salary', (j) => j.salary, (j) => salaryLow(j.salary) > 0 && salaryLow(j.salary) === bestSal),
    F('Experience', (j) => expLabel(j.exp_min, j.exp_max)),
    F('Posted', (j) => postedLabel(j.posted_days_ago)),
    F('Apply type', (j) => (j.easy_apply ? 'Easy Apply' : 'External site')),
    F('Match score', (j) => j.match_score.toFixed(2), (j) => j.match_score === bestMatch),
    F('Rank score', (j) => j.rank_score.toFixed(2)),
    F('Skills matched', (j) => `${j.skills.filter((k) => skillMatches(k, mine)).length} of ${j.skills.length}`),
    F('Status', (j) => (j.already_applied ? 'Already applied' : 'Not applied')),
  ];
  return (
    <Overlay variant="center" onClose={onClose} scrimLabel="Close comparison">
      <section className="modal" role="dialog" aria-modal="true" aria-label="Compare jobs">
        <div className="mhead">
          <h2 className="h2 num">Compare {cmp.length} jobs</h2>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn btn-sm btn-primary" onClick={() => onApply(cmp.map((j) => j.apply_url))}>
              Bulk apply these
            </button>
            <button className="btn btn-ghost btn-sm btn-icon" onClick={onClose} aria-label="Close">
              <Icon name="x" small />
            </button>
          </div>
        </div>
        <div className="cscroll">
          <div className="crow crow-head" style={{ gridTemplateColumns: tpl }}>
            <div />
            {cmp.map((j) => (
              <div key={j.apply_url}>
                <PlatformBadge id={j.platform} />
                <div style={{ fontWeight: 600, fontSize: 14, marginTop: 4 }}>{j.title}</div>
              </div>
            ))}
          </div>
          {fields.map((f) => (
            <div className="crow" style={{ gridTemplateColumns: tpl }} key={f.label}>
              <div className="clabel">{f.label}</div>
              {cmp.map((j) => (
                <div key={j.apply_url} className={f.best?.(j) ? 'ccell-best num' : 'num'}>
                  {f.fn(j)}
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>
    </Overlay>
  );
}
