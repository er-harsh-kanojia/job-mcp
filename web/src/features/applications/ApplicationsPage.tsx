import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { errorMessage } from '../../api';
import type { Application, AppStatus, Platform } from '../../api/types';
import { Alert, cx, EmptyState, LoadingCard, PlatformBadge, StatusPill } from '../../components/ui';
import { fmtStamp, LIVE_PLATFORMS, parseTime, platName } from '../../lib/format';
import { useApplications, useBackendDown, useLivePlatforms } from '../../lib/queries';
import { readLS, writeLS } from '../../state/ui';

const STATUSES: [AppStatus, string][] = [
  ['applied', 'Applied'],
  ['failed', 'Failed'],
  ['skipped', 'Skipped'],
  ['dry_run', 'Dry run'],
];
type Range = 'd7' | 'd30' | 'custom';
const ALL_ON: Record<AppStatus, boolean> = { applied: true, failed: true, skipped: true, dry_run: true };

function isoDay(d: Date) {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function note(a: Application): string {
  if (a.error) return a.error;
  if (a.status === 'applied') return 'Submitted';
  if (a.status === 'dry_run') return 'Simulated, nothing sent';
  if (a.status === 'skipped') return 'Skipped';
  return 'Failed';
}

export function ApplicationsPage() {
  const nav = useNavigate();
  const [sp] = useSearchParams();
  const down = useBackendDown();
  const plats = useLivePlatforms();
  const initialStatus = sp.get('status') as AppStatus | null;
  const [status, setStatus] = useState<Record<AppStatus, boolean>>(() =>
    initialStatus && initialStatus in ALL_ON ? { applied: false, failed: false, skipped: false, dry_run: false, [initialStatus]: true } : ALL_ON,
  );
  const [platform, setPlatform] = useState<Platform | 'all'>('all');
  const [range, setRange] = useState<Range>(() => (sp.get('range') as Range) || 'd7');
  const today = new Date();
  const monthAgo = new Date(Date.now() - 30 * 86400000);
  const [from, setFrom] = useState(isoDay(monthAgo));
  const [to, setTo] = useState(isoDay(today));
  const [group, setGroupState] = useState(() => readLS('jobmcp.trGroup') === '1');
  const setGroup = (g: boolean) => {
    setGroupState(g);
    writeLS('jobmcp.trGroup', g ? '1' : '0');
  };

  const q = useApplications({ days: range === 'd7' ? 7 : range === 'd30' ? 30 : 0, platform: platform === 'all' ? undefined : platform });
  const base = useMemo(() => {
    const list = q.data ?? [];
    if (range !== 'custom') return list;
    const a = new Date(`${from}T00:00:00`).getTime();
    const b = new Date(`${to}T23:59:59`).getTime();
    return list.filter((x) => {
      const t = parseTime(x.applied_at)?.getTime() ?? 0;
      return (!from || t >= a) && (!to || t <= b);
    });
  }, [q.data, range, from, to]);
  const shown = [...base].filter((a) => status[a.status]).sort((a, b) => b.applied_at.localeCompare(a.applied_at));
  const platIds = (plats.length ? plats.map((p) => p.id) : [...LIVE_PLATFORMS]) as Platform[];
  const groups = group
    ? platIds.map((id) => ({ id, rows: shown.filter((a) => a.platform === id) })).filter((g) => g.rows.length)
    : [{ id: null as Platform | null, rows: shown }];
  const neverApplied = !q.isLoading && (q.data ?? []).length === 0 && range !== 'custom' && platform === 'all' && Object.values(status).every(Boolean);
  const reset = () => {
    setStatus(ALL_ON);
    setPlatform('all');
    setRange('d30');
  };

  return (
    <div className="page">
      <div className="pagehead">
        <div>
          <h1 className="h1">Applications</h1>
          <p className="sub">Everything Job MCP has applied to, simulated or skipped.</p>
        </div>
      </div>
      {q.error && !down && (
        <Alert tone="danger" title="Couldn't load applications" actions={<button className="btn btn-sm" onClick={() => void q.refetch()}>Retry</button>}>
          {errorMessage(q.error)}
        </Alert>
      )}
      <section className="card" style={{ overflow: 'hidden' }}>
        <div className="rtool" style={{ justifyContent: 'flex-start' }}>
          <div className="chips" role="group" aria-label="Status">
            {STATUSES.map(([k, l]) => (
              <button key={k} className={cx('chip', status[k] && 'chip-on')} aria-pressed={status[k]} onClick={() => setStatus({ ...status, [k]: !status[k] })}>
                {l}
                <span className="cnt num">{base.filter((a) => a.status === k).length}</span>
              </button>
            ))}
          </div>
          <div className="chips" role="group" aria-label="Platform">
            <button className={cx('chip', platform === 'all' && 'chip-on')} aria-pressed={platform === 'all'} onClick={() => setPlatform('all')}>
              All platforms
            </button>
            {platIds.map((id) => (
              <button key={id} className={cx('chip', `p-${id}`, platform === id && 'chip-on')} aria-pressed={platform === id} onClick={() => setPlatform(id)}>
                <span className="pdot" />
                {platName(id)}
              </button>
            ))}
          </div>
          <div className="seg" role="group" aria-label="Date range">
            {(
              [
                ['d7', 'Last 7 days'],
                ['d30', 'Last 30 days'],
                ['custom', 'Custom'],
              ] as [Range, string][]
            ).map(([k, l]) => (
              <button key={k} className={range === k ? 'seg-on' : ''} aria-pressed={range === k} onClick={() => setRange(k)}>
                {l}
              </button>
            ))}
          </div>
          {range === 'custom' && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input className="input input-sm" type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From date" />
              <span className="help">to</span>
              <input className="input input-sm" type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To date" />
            </div>
          )}
          <label className="switch" style={{ marginLeft: 'auto' }}>
            <input type="checkbox" checked={group} onChange={() => setGroup(!group)} />
            Group by platform
          </label>
        </div>
        {q.isLoading ? (
          <div style={{ padding: 16 }}>
            <LoadingCard label="Loading applications…" />
          </div>
        ) : (
          <div className="tscroll">
            <div className="atbl" role="table" aria-label="Applications">
              <div className="trow agrid thead" role="row">
                <span role="columnheader">Date</span>
                <span role="columnheader">Role</span>
                <span role="columnheader">Platform</span>
                <span role="columnheader">Status</span>
                <span role="columnheader">Note</span>
              </div>
              {groups.map((g) => (
                <div key={g.id ?? 'all'} role="rowgroup">
                  {g.id && (
                    <div className="ghead" role="row">
                      <PlatformBadge id={g.id} />
                      <span className="help num">{g.rows.length} items</span>
                    </div>
                  )}
                  {g.rows.map((a) => (
                    <div key={a.id} className={cx('trow agrid arow', a.status === 'dry_run' && 'dry-row')} role="row">
                      <span className="mono help" role="cell">
                        {fmtStamp(a.applied_at)}
                      </span>
                      <div className="c-role" role="cell" style={{ minWidth: 0 }}>
                        <a className="rtitle" href={a.apply_url} target="_blank" rel="noopener noreferrer" style={{ color: 'inherit', textDecoration: 'none' }}>
                          {a.title}
                        </a>{' '}
                        <span className="muted">· {a.company}</span>
                      </div>
                      <span role="cell">
                        <PlatformBadge id={a.platform} />
                      </span>
                      <span role="cell">
                        <StatusPill status={a.status} />
                      </span>
                      <span className={a.status === 'failed' ? 'reason-bad' : 'help'} role="cell" style={{ fontSize: 12 }}>
                        {note(a)}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
              {shown.length === 0 && (
                <EmptyState
                  icon="applications"
                  title={neverApplied ? 'No applications yet' : 'Nothing matches these filters'}
                  action={
                    <button className="btn btn-sm" onClick={neverApplied ? () => nav('/search') : reset}>
                      {neverApplied ? 'Go to Search' : 'Reset filters'}
                    </button>
                  }
                >
                  {neverApplied
                    ? 'Run a search, select jobs and start with a dry run. Every application, failure and skip will show up here.'
                    : 'Turn on more statuses or widen the date range.'}
                </EmptyState>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
