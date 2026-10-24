import { useNavigate } from 'react-router-dom';
import { isAiNotConfigured } from '../../api';
import type { Application, PlatformInfo } from '../../api/types';
import { Alert, LoadingCard, PlatformBadge } from '../../components/ui';
import { Icon } from '../../components/Icon';
import { fmtDayTimeShort, fmtFeedTime, fmtLongDate, hhmm, joinList, LIVE_PLATFORMS, parseTime, platName, PLATFORM_ORDER, plural, weekStartLabel, daysAgo } from '../../lib/format';
import { useAiProvider, useBackendDown, useLastSearch, usePlatforms, useReview, useStats } from '../../lib/queries';
import { useSearch } from '../../state/search';
import { useUi } from '../../state/ui';
import { useStartLogin } from '../shell/Shell';

type Feed = { t: string; at: string; dot: string; a: string; b: string };

function feedFor(a: Application): Feed {
  const via = `${a.title} at ${a.company} via ${platName(a.platform)}`;
  switch (a.status) {
    case 'applied':
      return { t: fmtFeedTime(a.applied_at), at: a.applied_at, dot: 'fdot fd-ok', a: 'Applied', b: via };
    case 'failed':
      return { t: fmtFeedTime(a.applied_at), at: a.applied_at, dot: 'fdot fd-bad', a: 'Failed', b: `${via}.${a.error ? ` ${a.error}.` : ''}`.replace('..', '.') };
    case 'dry_run':
      return { t: fmtFeedTime(a.applied_at), at: a.applied_at, dot: 'fdot fd-dry', a: 'Dry run', b: `${via}, nothing sent` };
    default:
      return { t: fmtFeedTime(a.applied_at), at: a.applied_at, dot: 'fdot fd-muted', a: 'Skipped', b: `${via}${a.error ? `. ${a.error}` : ''}` };
  }
}

export function DashboardPage() {
  const nav = useNavigate();
  const ui = useUi();
  const down = useBackendDown();
  const stats = useStats();
  const platQ = usePlatforms();
  const last = useLastSearch();
  const review = useReview(ui.role);
  const aip = useAiProvider();
  const search = useSearch();
  const startLogin = useStartLogin();
  const plats = platQ.data ?? [];
  const live = plats.filter((p) => p.live);
  const soon = plats.filter((p) => !p.live).sort((a, b) => PLATFORM_ORDER.indexOf(a.id) - PLATFORM_ORDER.indexOf(b.id));
  const expired = live.filter((p) => p.session === 'expired');
  const noSessions = live.length > 0 && !live.some((p) => p.session === 'logged_in');
  const st = stats.data;
  const firstRun = !!st && noSessions && st.recent.length === 0;

  const runSearch = () => {
    void search.run();
    nav('/search');
  };

  return (
    <div className="page">
      <div className="pagehead">
        <div>
          <h1 className="h1">Dashboard</h1>
          <p className="sub">{fmtLongDate()}</p>
        </div>
        <button className="btn btn-primary" onClick={runSearch} disabled={down || noSessions || search.running}>
          <Icon name="play" />
          Run search
        </button>
      </div>

      {firstRun && <Onboarding />}

      {!firstRun && (
        <>
          {!down &&
            expired.map((p) => (
              <Alert
                key={p.id}
                tone="danger"
                title={`${p.name} session expired${p.last_checked ? ` at ${hhmm(parseTime(p.last_checked)!)}` : ''}`}
                actions={
                  <button className="btn btn-sm" onClick={() => startLogin(String(p.id))}>
                    Log in to {p.name}
                  </button>
                }
              >
                New searches and bulk applies skip {p.name} until you log in again.
              </Alert>
            ))}
          {stats.isLoading && <LoadingCard label="Loading your activity…" />}
          {st && (
            <>
              <div className="kpis">
                <div className="card kpi">
                  <span className="eyebrow">Applied today</span>
                  <span className="kpi-v num">{st.applied_today}</span>
                  <span className="help">{todayBreakdown(st.recent, st.applied_today)}</span>
                </div>
                <div className="card kpi">
                  <span className="eyebrow">Applied this week</span>
                  <span className="kpi-v num">{st.applied_week}</span>
                  <span className="help">Since {weekStartLabel()}</span>
                </div>
                <div className="card kpi">
                  <span className="eyebrow">Success rate</span>
                  <span className="kpi-v num">{Math.round(st.success_rate * 100)}%</span>
                  <span className="help">Applied vs failed, last 30 days</span>
                </div>
                <div className="card kpi">
                  <span className="eyebrow">Resume score</span>
                  {review.data ? (
                    <>
                      <span className="kpi-v num">
                        {review.data.overall}
                        <span className="kpi-unit"> / 100</span>
                      </span>
                      <span className="help" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                        {resumeSub(review.data.issues)}
                        <button className="btn btn-sm" onClick={() => nav('/resume')}>
                          Review
                        </button>
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="kpi-v num muted">—</span>
                      <span className="help" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                        {isAiNotConfigured(review.error) ? `Set up ${aip.short} to review` : review.isLoading ? 'Loading…' : 'Not analysed yet'}
                        <button className="btn btn-sm" onClick={() => nav('/resume')}>
                          {isAiNotConfigured(review.error) ? 'Set up' : 'Analyse'}
                        </button>
                      </span>
                    </>
                  )}
                </div>
                <div className="card kpi">
                  <span className="eyebrow">Last search</span>
                  {last.data ? (
                    <>
                      <span className="kpi-v num">
                        {last.data.total ?? lastTotal(last.data.platforms, last.data.jobs.length)} <span className="kpi-unit">matches</span>
                      </span>
                      <span className="help" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                        {fmtDayTimeShort(last.data.finished_at)} · {plural(last.data.params.platforms.length, 'platform')}
                        <button className="btn btn-sm" onClick={() => nav('/search')}>
                          Open
                        </button>
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="kpi-v num muted">—</span>
                      <span className="help" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                        No search yet
                        <button className="btn btn-sm" onClick={() => nav('/search')}>
                          Open
                        </button>
                      </span>
                    </>
                  )}
                </div>
              </div>
              <div className="two">
                <WeekByPlatform byPlatform={st.by_platform} live={live} soon={soon} days={st.window_days} />
                <section className="card">
                  <div className="sechead">
                    <h2 className="h2">Recent activity</h2>
                    <button className="btn btn-ghost btn-sm" onClick={() => nav('/applications')}>
                      Open tracker
                    </button>
                  </div>
                  <ActivityFeed recent={st.recent} expired={expired} last={last.data ?? null} />
                </section>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

function resumeSub(issues: { severity: string; status: string }[]): string {
  const m = issues.filter((i) => i.severity === 'mistake' && i.status === 'open').length;
  const all = issues.filter((i) => i.status === 'open').length;
  if (m) return `${plural(m, 'mistake')} to fix`;
  return all ? `${plural(all, 'suggestion')} open` : 'Nothing left to fix';
}

function lastTotal(events: { count?: number }[], fallback: number): number {
  const n = events.reduce((a, e) => a + (e.count ?? 0), 0);
  return n || fallback;
}

function todayBreakdown(recent: Application[], appliedToday: number): string {
  if (!appliedToday) return 'Nothing applied yet today';
  const today = recent.filter((a) => a.status === 'applied' && daysAgo(a.applied_at) === 0);
  if (today.length !== appliedToday) return 'Since midnight';
  const parts = LIVE_PLATFORMS.map((p) => [p, today.filter((a) => a.platform === p).length] as const).filter(([, n]) => n > 0);
  return parts.map(([p, n]) => `${n} ${platName(p)}`).join(' · ');
}

function WeekByPlatform({ byPlatform, live, soon, days }: { byPlatform: Record<string, { applied: number; failed: number; skipped: number; dry_run: number }>; live: PlatformInfo[]; soon: PlatformInfo[]; days?: number }) {
  const ids = live.length ? live.map((p) => String(p.id)) : [...LIVE_PLATFORMS];
  const rows = ids.map((id) => ({ id, ...(byPlatform[id] ?? { applied: 0, failed: 0, skipped: 0, dry_run: 0 }) }));
  const max = Math.max(1, ...rows.map((r) => r.applied + r.failed + r.skipped));
  return (
    <section className="card">
      <div className="sechead">
        <h2 className="h2">{days ? `Last ${days} days by platform` : 'This week by platform'}</h2>
        <div className="legend">
          <span>
            <i className="sw seg-ok" />
            Applied
          </span>
          <span>
            <i className="sw seg-bad" />
            Failed
          </span>
          <span>
            <i className="sw seg-skip" />
            Skipped
          </span>
        </div>
      </div>
      <div style={{ padding: '6px 0' }}>
        {rows.map((r) => {
          const total = r.applied + r.failed + r.skipped;
          return (
            <div className="bdrow" key={r.id}>
              <PlatformBadge id={r.id} />
              <span style={{ display: 'block', minWidth: 0 }} aria-hidden="true">
                <span className="sbar" style={{ width: `${Math.round((total / max) * 100)}%` }}>
                  <span className="seg-ok" style={{ flex: r.applied }} />
                  <span className="seg-bad" style={{ flex: r.failed }} />
                  <span className="seg-skip" style={{ flex: r.skipped }} />
                </span>
              </span>
              <span className="bdtxt num help" style={{ textAlign: 'right' }}>
                {r.applied} applied · {r.failed} failed · {r.skipped} skipped
              </span>
            </div>
          );
        })}
        {soon.map((p) => (
          <div className="bdrow" key={p.id}>
            <PlatformBadge id={p.id} name={p.name} soon />
            <span className="help">Coming soon</span>
            <span />
          </div>
        ))}
      </div>
    </section>
  );
}

function ActivityFeed({ recent, expired, last }: { recent: Application[]; expired: PlatformInfo[]; last: { finished_at: string; platforms: { platform: string; count?: number }[]; jobs: unknown[]; params: { platforms: string[] } } | null }) {
  const items: Feed[] = recent.map(feedFor);
  if (last) {
    items.push({
      t: fmtFeedTime(last.finished_at),
      at: last.finished_at,
      dot: 'fdot fd-info',
      a: 'Search finished',
      b: `${lastTotal(last.platforms, last.jobs.length)} matches across ${joinList(last.params.platforms.map(platName))}`,
    });
  }
  expired.forEach((p) => {
    if (p.last_checked) items.push({ t: fmtFeedTime(p.last_checked), at: p.last_checked, dot: 'fdot fd-warn', a: 'Session expired', b: `${p.name}. Log in again to include it.` });
  });
  items.sort((a, b) => b.at.localeCompare(a.at));
  if (!items.length)
    return (
      <div className="help" style={{ padding: '12px 16px' }}>
        No activity yet. Run a search and start with a dry run.
      </div>
    );
  return (
    <div>
      {items.slice(0, 8).map((f, i) => (
        <div className="fitem" key={i}>
          <span className="mono help">{f.t}</span>
          <span className={f.dot} aria-hidden="true" />
          <div style={{ minWidth: 0 }}>
            <span style={{ fontWeight: 500 }}>{f.a}</span> <span style={{ color: 'var(--text-2)' }}>{f.b}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function Onboarding() {
  const nav = useNavigate();
  return (
    <section className="card">
      <div className="sechead">
        <div>
          <h2 className="h2">Set up Job MCP</h2>
          <div className="help">Three steps before your first application. Nothing is sent until you choose Live mode.</div>
        </div>
      </div>
      <div className="onb" style={{ padding: 12 }}>
        <div className="onb-step card">
          <span className="onb-n">1</span>
          <div className="h2">Log in to a job portal</div>
          <p>Log in once in a real browser window. Job MCP reuses that session and never sees your password.</p>
          <button className="btn btn-primary btn-sm" onClick={() => nav('/platforms')}>
            Set up platforms
          </button>
        </div>
        <div className="onb-step card">
          <span className="onb-n onb-n-muted">2</span>
          <div className="h2">Run your first search</div>
          <p>Search Naukri, Instahyre and Hirist at once. Jobs are ranked against your profile.</p>
          <button className="btn btn-sm" onClick={() => nav('/search')}>
            Go to Search
          </button>
        </div>
        <div className="onb-step card">
          <span className="onb-n onb-n-muted">3</span>
          <div className="h2">Do a dry run</div>
          <p>Bulk apply starts in Dry run: it fills every form and stops before submitting, so you can check first.</p>
          <button className="btn btn-sm" onClick={() => nav('/profile')}>
            Check your profile
          </button>
        </div>
      </div>
    </section>
  );
}
