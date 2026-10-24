import type { Job } from '../../api/types';
import { Icon } from '../../components/Icon';
import { cx, Overlay, PlatformBadge } from '../../components/ui';
import { expLabel, matchColor, pct, platName, postedLabel, skillMatches } from '../../lib/format';
import { useSearch } from '../../state/search';

export function JobDrawer({
  job,
  rows,
  mine,
  prefLocs,
  onClose,
  onMove,
}: {
  job: Job;
  rows: Job[];
  mine: string[];
  prefLocs: string[];
  onClose: () => void;
  onMove: (i: number) => void;
}) {
  const s = useSearch();
  if (!job) return null;
  const i = rows.findIndex((r) => r.apply_url === job.apply_url);
  const inQ = s.isSelected(job.apply_url);
  const matched = job.skills.filter((k) => skillMatches(k, mine));
  const prefFit = prefLocs.some((l) => job.location.toLowerCase().includes(l.toLowerCase()) || l.toLowerCase().includes(job.location.toLowerCase()));

  return (
    <Overlay variant="right" onClose={onClose} scrimLabel="Close job details">
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={`Job details: ${job.title}`}
        onKeyDown={(e) => {
          const t = e.target as HTMLElement;
          if (t.tagName === 'INPUT') return;
          if ((e.key === 'j' || e.key === 'J') && i >= 0 && i < rows.length - 1) {
            e.preventDefault();
            e.stopPropagation();
            onMove(i + 1);
          } else if ((e.key === 'k' || e.key === 'K') && i > 0) {
            e.preventDefault();
            e.stopPropagation();
            onMove(i - 1);
          } else if (e.key === 'x' || e.key === 'X') {
            e.stopPropagation();
            if (!job.already_applied) s.toggle(job.apply_url);
          }
        }}
      >
        <div className="dhead">
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <button className="btn btn-ghost btn-sm" onClick={() => i > 0 && onMove(i - 1)} disabled={i <= 0} aria-label="Previous job">
              <Icon name="chevUp" small />
              <span className="kbd">K</span>
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => i >= 0 && i < rows.length - 1 && onMove(i + 1)} disabled={i < 0 || i >= rows.length - 1} aria-label="Next job">
              <Icon name="chevDown" small />
              <span className="kbd">J</span>
            </button>
            {i >= 0 && (
              <span className="help num">
                {i + 1} of {rows.length}
              </span>
            )}
          </div>
          <button className="btn btn-ghost btn-icon" onClick={onClose} aria-label="Close">
            <Icon name="x" />
          </button>
        </div>
        <div className="dbody">
          <div>
            <PlatformBadge id={job.platform} />
            <h2 className="dtitle">{job.title}</h2>
            <div style={{ color: 'var(--text-2)' }}>
              {job.company} · {job.location}
            </div>
          </div>
          <div className="scorebox">
            <div>
              <div className="help">Match score</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span className="bigscore mono">{job.match_score.toFixed(2)}</span>
                <span className="mbar mbar-lg" aria-hidden="true">
                  <span style={{ width: pct(job.match_score), background: matchColor(job.match_score) }} />
                </span>
              </div>
            </div>
            <div>
              <div className="help">Rank score</div>
              <div className="bigscore mono" style={{ fontSize: 18 }}>
                {job.rank_score.toFixed(2)}
              </div>
            </div>
          </div>
          <dl className="meta">
            <div>
              <dt>Salary</dt>
              <dd className="num">{job.salary}</dd>
            </div>
            <div>
              <dt>Experience</dt>
              <dd className="num">{expLabel(job.exp_min, job.exp_max)}</dd>
            </div>
            <div>
              <dt>Posted</dt>
              <dd>{postedLabel(job.posted_days_ago)}</dd>
            </div>
            <div>
              <dt>Apply type</dt>
              <dd>{job.easy_apply ? 'Easy Apply' : 'External, on employer site'}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>{job.already_applied ? 'Already applied' : 'Not applied'}</dd>
            </div>
            <div>
              <dt>Location fit</dt>
              <dd>{prefLocs.length ? (prefFit ? 'Preferred location' : 'Outside preferred locations') : '—'}</dd>
            </div>
          </dl>
          <div>
            <div className="eyebrow">About the role</div>
            <p>{job.description || 'No description in the listing.'}</p>
            <div className="help" style={{ marginTop: 6 }}>
              Snippet from the listing. Open it on {platName(job.platform)} for the full description.
            </div>
          </div>
          {job.skills.length > 0 && (
            <div>
              <div className="eyebrow" style={{ marginBottom: 8 }}>
                Skills · {matched.length} of {job.skills.length} match your profile
              </div>
              <div className="chips">
                {job.skills.map((k) => {
                  const m = skillMatches(k, mine);
                  return (
                    <span key={k} className={cx('tag', m && 'tag-match')}>
                      {m && <Icon name="check" small />}
                      {k}
                    </span>
                  );
                })}
              </div>
            </div>
          )}
        </div>
        <div className="dfoot">
          <a className="btn" href={job.apply_url} target="_blank" rel="noopener noreferrer">
            Open on {platName(job.platform)}
            <Icon name="external" small />
          </a>
          <button className={cx('btn', !inQ && 'btn-primary')} onClick={() => s.toggle(job.apply_url)} disabled={job.already_applied}>
            {job.already_applied ? 'Already applied' : inQ ? 'In apply queue · Remove' : 'Add to apply queue'}
          </button>
        </div>
      </aside>
    </Overlay>
  );
}
