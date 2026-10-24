import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Job, Platform, PlatformInfo, SearchPlatformEvent } from '../../api/types';
import { errorMessage } from '../../api';
import { Icon } from '../../components/Icon';
import { Alert, cx, EmptyState, MatchScore, Pill, PlatformBadge, SkeletonRows } from '../../components/ui';
import { expLabel, joinList, LIVE_PLATFORMS, matchColor, pct, platName, PLATFORM_ORDER, postedLabel, salaryLow, skillLabel } from '../../lib/format';
import { useBackendDown, usePlatforms, useProfile } from '../../lib/queries';
import { useApply } from '../../state/apply';
import { DEFAULT_MIN, useSearch } from '../../state/search';
import { readLS, useUi, writeLS } from '../../state/ui';
import { useStartLogin } from '../shell/Shell';
import { CompareModal } from './CompareModal';
import { JobDrawer } from './JobDrawer';

type SortKey = 'rank' | 'match' | 'posted' | 'salary';
const SORT_LABEL: Record<SortKey, string> = { rank: 'rank score', match: 'match score', posted: 'recency', salary: 'salary' };
const SORT_FN: Record<SortKey, (j: Job) => number> = {
  rank: (j) => j.rank_score,
  match: (j) => j.match_score,
  salary: (j) => salaryLow(j.salary),
  posted: (j) => (j.posted_days_ago < 0 ? -999 : -j.posted_days_ago),
};

/** Client-side estimate of the bulk-apply split, used for the selection bar summary. */
export function estimateSkips(jobs: Job[], sessions: PlatformInfo[]) {
  const ok = new Set(sessions.filter((s) => s.session === 'logged_in').map((s) => s.id));
  let skip = 0;
  jobs.forEach((j) => {
    if (j.already_applied || !j.easy_apply || (sessions.length && !ok.has(j.platform))) skip++;
  });
  return { will: jobs.length - skip, skip };
}

export function SearchPage() {
  const ui = useUi();
  const nav = useNavigate();
  const s = useSearch();
  const apply = useApply();
  const down = useBackendDown();
  const platQ = usePlatforms();
  const profile = useProfile();
  const startLogin = useStartLogin();
  const allPlats = platQ.data ?? [];
  const livePlats: PlatformInfo[] = allPlats.filter((p) => p.live);
  const soonPlats = allPlats.filter((p) => !p.live);
  const liveIds: Platform[] = livePlats.length ? (livePlats.map((p) => p.id) as Platform[]) : [...LIVE_PLATFORMS];
  const sessionOf = (id: string) => livePlats.find((p) => p.id === id)?.session ?? 'unknown';
  const noSessions = livePlats.length > 0 && !livePlats.some((p) => p.session === 'logged_in');
  const live = ui.mode === 'live';

  const [sort, setSort] = useState<SortKey>('rank');
  const [dir, setDir] = useState<'asc' | 'desc'>('desc');
  const [density, setDensityState] = useState<'comfortable' | 'compact'>(() => (readLS('jobmcp.density') === 'compact' ? 'compact' : 'comfortable'));
  const setDensity = (d: 'comfortable' | 'compact') => {
    setDensityState(d);
    writeLS('jobmcp.density', d);
  };
  const [focus, setFocus] = useState(0);
  const [drawer, setDrawer] = useState<string | null>(null);
  const [compare, setCompare] = useState(false);
  const [kwDraft, setKwDraft] = useState('');
  const [excludeDraft, setExcludeDraft] = useState('');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const kwRef = useRef<HTMLInputElement>(null);
  const rowRefs = useRef(new Map<number, HTMLElement>());

  const excludedLower = useMemo(
    () => (s.params.exclude_companies ?? []).map((c) => c.trim().toLowerCase()).filter(Boolean),
    [s.params.exclude_companies],
  );

  const rows = useMemo(() => {
    const k = SORT_FN[sort];
    const d = dir === 'asc' ? 1 : -1;
    return s.jobs
      .filter((j) => {
        if (j.match_score < s.minScore - 1e-9) return false;
        if (excludedLower.length > 0) {
          const comp = (j.company || '').toLowerCase();
          if (excludedLower.some((ex) => comp === ex || comp.includes(ex))) return false;
        }
        return true;
      })
      .sort((a, b) => (k(a) - k(b)) * d || b.rank_score - a.rank_score);
  }, [s.jobs, s.minScore, sort, dir, excludedLower]);
  const f = Math.max(0, Math.min(focus, rows.length - 1));

  // Keyboard: J/K move, X select, Enter open, / focus keywords (design hints in the results toolbar).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const tag = t?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || t?.isContentEditable) return;
      if (e.ctrlKey || e.metaKey || e.altKey || ui.paletteOpen || ui.interview || compare) return;
      if (e.key === '/') {
        e.preventDefault();
        setFiltersOpen(true);
        setTimeout(() => kwRef.current?.focus(), 0);
        return;
      }
      if (!rows.length) return;
      const move = (n: number) => {
        e.preventDefault();
        setFocus(n);
        if (drawer) setDrawer(rows[n].apply_url);
        rowRefs.current.get(n)?.scrollIntoView({ block: 'nearest' });
      };
      if (e.key === 'j' || e.key === 'J' || (e.key === 'ArrowDown' && !drawer)) move(Math.min(rows.length - 1, f + 1));
      else if (e.key === 'k' || e.key === 'K' || (e.key === 'ArrowUp' && !drawer)) move(Math.max(0, f - 1));
      else if ((e.key === 'x' || e.key === 'X') && rows[f]) {
        e.preventDefault();
        s.toggle(rows[f].apply_url);
      } else if (e.key === 'Enter' && !drawer && rows[f] && (t === document.body || t?.id === 'main' || t?.closest('.jrow,.jcard') == null)) {
        if (tag === 'BUTTON' || tag === 'A') return;
        e.preventDefault();
        setDrawer(rows[f].apply_url);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [rows, f, drawer, compare, ui.paletteOpen, ui.interview, s]);

  const addKeyword = () => {
    const t = kwDraft.trim();
    if (t && !s.params.keywords.includes(t)) s.setParams({ keywords: [...s.params.keywords, t] });
    setKwDraft('');
  };

  const addExcludeCompany = () => {
    const t = excludeDraft.trim();
    const current = s.params.exclude_companies ?? [];
    if (t && !current.some((x) => x.toLowerCase() === t.toLowerCase())) {
      s.setParams({ exclude_companies: [...current, t] });
    }
    setExcludeDraft('');
  };

  const selectedPlats = s.params.platforms.filter((p) => liveIds.includes(p));
  const runnable = selectedPlats.some((p) => sessionOf(p) === 'logged_in' || sessionOf(p) === 'unknown');
  const runDisabled = down || noSessions || s.running || !runnable || s.params.keywords.length === 0;

  // Platform progress rows and soft failures.
  const events = s.platformEvents;
  // A platform can fail outright, or finish with partial results and still carry a reason (backend addition).
  const evList = Object.values(events) as SearchPlatformEvent[];
  const captcha = evList.filter((e) => (e.state === 'failed' || e.state === 'done') && e.reason === 'captcha_required');
  const otherFail = evList.filter((e) => (e.state === 'failed' || e.state === 'done') && !!e.reason && e.reason !== 'captcha_required' && e.reason !== 'session_expired');
  const expiredInRun = (Object.values(events) as SearchPlatformEvent[]).filter((e) => e.reason === 'session_expired').map((e) => e.platform);
  const expiredNow = livePlats.filter((p) => p.session === 'expired').map((p) => p.id as Platform);
  const expired = [...new Set([...expiredInRun.filter((p) => sessionOf(p) !== 'logged_in'), ...expiredNow])];
  const okNames = liveIds.filter((p) => events[p]?.state === 'done').map(platName);
  const hasResultsContext = s.hasRun || !!s.finishedAt;
  const showProg = !down && !noSessions && (hasResultsContext || s.running);
  const blocked = down || noSessions;

  const selJobs = s.selected.map((u) => s.jobByUrl(u)).filter((j): j is Job => !!j);
  const est = estimateSkips(selJobs, livePlats);
  const mine = Object.keys(profile.data?.autofill.experience ?? {});
  const prefLocs = profile.data?.autofill.preferred_locations ?? [];

  const goApply = (urls?: string[]) => {
    if (urls) s.setSelected(urls);
    setCompare(false);
    setDrawer(null);
    apply.begin();
    nav('/apply');
  };

  const allSel = rows.length > 0 && rows.every((j) => s.isSelected(j.apply_url));
  const toggleAll = () => {
    const urls = new Set(s.selected);
    if (allSel) rows.forEach((j) => urls.delete(j.apply_url));
    else rows.forEach((j) => urls.add(j.apply_url));
    s.setSelected([...urls]);
  };
  const sortBy = (k: SortKey) => {
    if (sort === k) setDir(dir === 'desc' ? 'asc' : 'desc');
    else {
      setSort(k);
      setDir('desc');
    }
  };
  const ind = (k: SortKey) => (sort === k ? (dir === 'desc' ? ' ↓' : ' ↑') : '');
  const ariaSort = (k: SortKey) => (sort === k ? (dir === 'desc' ? 'descending' : 'ascending') : 'none');
  const compact = density === 'compact';
  const profileLine = profile.data
    ? `Jobs are ranked against your profile: ${profile.data.experience_years} yrs, ${mine.slice(0, 4).map(skillLabel).join(' · ') || 'your skills'}, ${prefLocs.slice(0, 2).join(' and ') || profile.data.location}.`
    : 'Jobs are ranked against your profile.';

  return (
    <div className="page">
      <div className="pagehead">
        <div>
          <h1 className="h1">Search</h1>
          <p className="sub">{profileLine}</p>
        </div>
        <button className="btn btn-primary hide-xs" onClick={() => void s.run()} disabled={runDisabled}>
          {s.running ? <span className="spin" aria-hidden="true" /> : <Icon name="play" />}
          {s.running ? 'Searching…' : 'Run search'}
        </button>
      </div>

      {!down && expired.length > 0 && (
        <Alert
          tone="danger"
          title={`${joinList(expired.map(platName))} session expired, so ${s.hasRun || s.finishedAt ? 'this search skipped it' : 'searches skip it'}`}
          actions={
            <button className="btn btn-sm" onClick={() => startLogin(expired[0])}>
              Log in to {platName(expired[0])}
            </button>
          }
        >
          Log in again and re-run to include {joinList(expired.map(platName))}.{okNames.length ? ` ${joinList(okNames)} results are below.` : ''}
        </Alert>
      )}

      {s.error && (
        <Alert tone="danger" title="The search didn't finish" actions={<button className="btn btn-sm" onClick={() => void s.run()} disabled={runDisabled}><Icon name="retry" small />Try again</button>} role="alert">
          {errorMessage(s.error)}
        </Alert>
      )}

      {/* phone: filter summary + run (Mobile.dc.html) */}
      <div className="mfilter" style={{ gap: 8 }}>
        <button className="btn mfilter-btn" onClick={() => setFiltersOpen(!filtersOpen)} aria-expanded={filtersOpen} aria-controls="search-filters">
          <Icon name="filter" />
          <span style={{ overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }} className="num">
            {s.params.keywords.length} keywords · {s.params.location || 'Anywhere'} · {s.params.experience_years} yrs · ≥ {s.minScore.toFixed(2)}
            {(s.params.exclude_companies?.length ?? 0) > 0 ? ` · ${s.params.exclude_companies?.length} excluded` : ''}
          </span>
        </button>
        <button className="btn btn-primary" style={{ minHeight: 44, width: 44, padding: 0 }} onClick={() => void s.run()} disabled={runDisabled} aria-label="Run search">
          {s.running ? <span className="spin" aria-hidden="true" /> : <Icon name="play" />}
        </button>
      </div>

      <section className={cx('card filters filters-collapsible', filtersOpen && 'filters-open')} aria-label="Search filters" id="search-filters">
        <div className="frow">
          <span className="lbl flbl" id="kw-label">
            Keywords
          </span>
          <div className="chips" style={{ flex: '1 1 400px' }} role="group" aria-labelledby="kw-label">
            {s.params.keywords.map((k) => (
              <span className="chip chip-on" key={k}>
                {k}
                <button className="chip-x" onClick={() => s.setParams({ keywords: s.params.keywords.filter((x) => x !== k) })} aria-label={`Remove keyword ${k}`}>
                  <Icon name="x" small />
                </button>
              </span>
            ))}
            <input
              ref={kwRef}
              className="chip-input"
              value={kwDraft}
              onChange={(e) => setKwDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addKeyword();
                }
                if (e.key === 'Escape') (e.target as HTMLInputElement).blur();
                if (e.key === 'Backspace' && !kwDraft && s.params.keywords.length) s.setParams({ keywords: s.params.keywords.slice(0, -1) });
              }}
              placeholder="Add keyword, Enter"
              aria-label="Add keyword"
            />
            <span className="kbd hide-sm" title="Press / to focus">
              /
            </span>
          </div>
        </div>
        <div className="frow" style={{ marginTop: 12 }}>
          <span className="lbl flbl" id="exclude-label">
            Exclude
          </span>
          <div className="chips" style={{ flex: '1 1 400px' }} role="group" aria-labelledby="exclude-label">
            {(s.params.exclude_companies ?? []).map((c) => (
              <span className="chip chip-on" key={c} style={{ borderColor: 'var(--border-subtle, #fca5a5)' }}>
                {c}
                <button
                  className="chip-x"
                  onClick={() => s.setParams({ exclude_companies: (s.params.exclude_companies ?? []).filter((x) => x !== c) })}
                  aria-label={`Remove excluded company ${c}`}
                >
                  <Icon name="x" small />
                </button>
              </span>
            ))}
            <input
              className="chip-input"
              value={excludeDraft}
              onChange={(e) => setExcludeDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addExcludeCompany();
                }
                if (e.key === 'Escape') (e.target as HTMLInputElement).blur();
                if (e.key === 'Backspace' && !excludeDraft && (s.params.exclude_companies ?? []).length) {
                  s.setParams({ exclude_companies: (s.params.exclude_companies ?? []).slice(0, -1) });
                }
              }}
              placeholder="Exclude company (e.g. TCS, Infosys), Enter"
              aria-label="Exclude company"
            />
          </div>
        </div>
        <div className="fgrid">
          <label className="field">
            <span className="lbl">Location</span>
            <input className="input" value={s.params.location} onChange={(e) => s.setParams({ location: e.target.value })} />
          </label>
          <label className="field">
            <span className="lbl">Experience (years)</span>
            <input
              className="input num"
              type="number"
              min={0}
              max={30}
              value={s.params.experience_years}
              onChange={(e) => s.setParams({ experience_years: Math.max(0, Math.min(30, Number(e.target.value) || 0)) })}
            />
          </label>
          <div className="field">
            <span className="lbl" id="plat-label">
              Platforms
            </span>
            <div className="chips" role="group" aria-labelledby="plat-label">
              {(livePlats.length ? livePlats.map((p) => p.id) : [...LIVE_PLATFORMS]).map((id) => {
                const on = s.params.platforms.includes(id as Platform);
                return (
                  <button
                    key={id}
                    className={cx('chip', `p-${id}`, on && 'chip-on')}
                    aria-pressed={on}
                    onClick={() => s.setParams({ platforms: on ? s.params.platforms.filter((p) => p !== id) : [...s.params.platforms, id as Platform] })}
                  >
                    <span className="pdot" />
                    {platName(id)}
                  </button>
                );
              })}
              {soonPlats
                .sort((a, b) => PLATFORM_ORDER.indexOf(a.id) - PLATFORM_ORDER.indexOf(b.id))
                .map((p) => (
                  <button key={p.id} className={`chip p-${p.id}`} disabled aria-pressed={false} title={`${p.name} is coming soon`}>
                    <span className="pdot" />
                    {p.name}
                    <span className="soon">Soon</span>
                  </button>
                ))}
            </div>
          </div>
          <label className="field">
            <span className="lbl" style={{ display: 'flex', justifyContent: 'space-between' }}>
              Minimum match
              <span className="mono" style={{ color: 'var(--text)' }}>
                {s.minScore.toFixed(2)}
              </span>
            </span>
            <input
              className="range"
              type="range"
              min={0}
              max={0.9}
              step={0.05}
              value={s.minScore}
              onChange={(e) => {
                s.setMinScore(parseFloat(e.target.value));
                setFocus(0);
              }}
              aria-valuetext={s.minScore.toFixed(2)}
            />
          </label>
        </div>
      </section>

      {showProg && (
        <>
          <section className="card prog" aria-label="Search progress by platform" aria-live="polite">
            {liveIds.map((id) => (
              <ProgressRow key={id} id={id} ev={events[id]} inRun={s.runPlatforms.includes(id)} session={sessionOf(id)} />
            ))}
          </section>
          <section className="card mprog" aria-label="Search progress by platform">
            {liveIds.map((id) => {
              const r = progressView(events[id], s.runPlatforms.includes(id), sessionOf(id));
              return (
                <div key={id} style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
                  <PlatformBadge id={id} />
                  <span className="help num" style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                    {r.spin && <span className="spin" style={{ color: 'var(--info)' }} />}
                    {r.state === 'done' ? r.count : r.label}
                  </span>
                </div>
              );
            })}
          </section>
        </>
      )}

      {!down &&
        captcha.map((c) => (
          <Alert
            key={c.platform}
            tone="warn"
            title={c.state === 'done' ? `${platName(c.platform)} showed a captcha part-way, so its results are partial` : `${platName(c.platform)} blocked this search with a captcha`}
            actions={
              <>
                <button className="btn btn-sm" onClick={() => void s.run()} disabled={s.running}>
                  <Icon name="retry" small />
                  Retry {platName(c.platform)}
                </button>
                <button className="btn btn-sm btn-ghost" onClick={() => startLogin(c.platform)}>
                  Log in to solve it once
                </button>
              </>
            }
          >
            {okNames.length ? `${joinList(okNames)} results are kept below. ` : ''}Solve the captcha once in a browser window from Platforms, then retry. Retrying runs the search again.
          </Alert>
        ))}
      {!down &&
        otherFail.map((c) => (
          <Alert key={c.platform} tone="warn" title={c.state === 'done' ? `${platName(c.platform)} returned partial results` : `${platName(c.platform)} ${c.reason === 'timeout' ? 'timed out' : 'failed'} during this search`} actions={<button className="btn btn-sm" onClick={() => void s.run()} disabled={s.running}><Icon name="retry" small />Retry {platName(c.platform)}</button>}>
            {c.message || 'Other platforms are kept below.'}
          </Alert>
        ))}

      {blocked && (
        <section className="card">
          <EmptyState
            icon="platforms"
            title={down ? 'Results unavailable' : 'No platforms connected yet'}
            action={
              down ? null : (
                <button className="btn btn-primary" onClick={() => nav('/platforms')}>
                  Set up platforms
                </button>
              )
            }
          >
            {down
              ? 'Job MCP can’t reach its local server, so it can’t search. Your last results come back once it reconnects.'
              : 'Log in to at least one portal, then run a search. Job MCP reuses your browser session and never stores passwords.'}
          </EmptyState>
        </section>
      )}

      {!blocked && !hasResultsContext && !s.running && (
        <section className="card">
          <EmptyState
            icon="search"
            title="Run your first search"
            action={
              <button className="btn btn-primary" onClick={() => void s.run()} disabled={runDisabled}>
                <Icon name="play" />
                Run search
              </button>
            }
          >
            Search {joinList(liveIds.map(platName))} at once. Jobs stream in as each platform finishes and are ranked against your profile.
          </EmptyState>
        </section>
      )}

      {!blocked && (hasResultsContext || s.running) && (
        <section className="card" style={{ overflow: 'hidden' }}>
          <div className="rtool">
            <div aria-live="polite">
              <span style={{ fontWeight: 600 }} className="num">
                {s.running ? 'Streaming results…' : `${rows.length} shown`}
              </span>{' '}
              <span className="muted num">{s.running ? '· ranked as they arrive' : `of ${s.total ?? s.jobs.length} matches · ranked by ${SORT_LABEL[sort]}`}</span>
            </div>
            <div className="rtool-right">
              <span className="hints hide-sm">
                <span className="kbd">J</span>
                <span className="kbd">K</span>move<span className="gap" />
                <span className="kbd">X</span>select<span className="gap" />
                <span className="kbd">↵</span>open
              </span>
              <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span className="lbl">Sort</span>
                <select
                  className="input input-sm"
                  value={sort}
                  onChange={(e) => {
                    setSort(e.target.value as SortKey);
                    setDir('desc');
                  }}
                >
                  <option value="rank">Rank score</option>
                  <option value="match">Match score</option>
                  <option value="posted">Most recent</option>
                  <option value="salary">Salary</option>
                </select>
              </label>
              <div className="seg hide-sm" role="group" aria-label="Row density">
                <button className={density === 'comfortable' ? 'seg-on' : ''} aria-pressed={density === 'comfortable'} onClick={() => setDensity('comfortable')}>
                  Comfortable
                </button>
                <button className={density === 'compact' ? 'seg-on' : ''} aria-pressed={density === 'compact'} onClick={() => setDensity('compact')}>
                  Compact
                </button>
              </div>
            </div>
          </div>

          <div className="tscroll jobs-table">
            <div className="tbl" role="table" aria-label="Search results" aria-rowcount={rows.length + 1}>
              <div className="trow jgrid thead" role="row">
                <label className="cbx" role="columnheader">
                  <input type="checkbox" checked={allSel} onChange={toggleAll} aria-label="Select all visible jobs" />
                </label>
                <span role="columnheader" aria-sort={ariaSort('rank')}>
                  <button className={cx('sortbtn', sort === 'rank' && 'sort-on')} onClick={() => sortBy('rank')}>
                    Rank{ind('rank')}
                  </button>
                </span>
                <span role="columnheader">Role</span>
                <span role="columnheader">Platform</span>
                <span role="columnheader">Location</span>
                <span role="columnheader" aria-sort={ariaSort('salary')}>
                  <button className={cx('sortbtn', sort === 'salary' && 'sort-on')} onClick={() => sortBy('salary')}>
                    Salary{ind('salary')}
                  </button>
                </span>
                <span role="columnheader">Experience</span>
                <span role="columnheader" aria-sort={ariaSort('posted')}>
                  <button className={cx('sortbtn', sort === 'posted' && 'sort-on')} onClick={() => sortBy('posted')}>
                    Posted{ind('posted')}
                  </button>
                </span>
                <span role="columnheader">Apply</span>
                <span className="c-match" role="columnheader" aria-sort={ariaSort('match')}>
                  <button className={cx('sortbtn', sort === 'match' && 'sort-on')} onClick={() => sortBy('match')}>
                    Match{ind('match')}
                  </button>
                </span>
              </div>
              {rows.map((j, i) => {
                const on = s.isSelected(j.apply_url);
                return (
                  <div
                    key={j.apply_url}
                    role="row"
                    ref={(el) => {
                      if (el) rowRefs.current.set(i, el);
                    }}
                    className={cx('trow jgrid jrow', compact && 'trow-compact', on && 'jrow-sel', i === f && 'jrow-focus')}
                    onClick={() => setFocus(i)}
                  >
                    <label className="cbx c-cb" role="cell">
                      <input type="checkbox" checked={on} onChange={() => s.toggle(j.apply_url)} aria-label={`Select ${j.title} at ${j.company}`} />
                    </label>
                    <span className="c-rank mono help" role="cell">
                      {j.rank_score.toFixed(2)}
                    </span>
                    <div className="c-role" role="cell">
                      <div className="rline">
                        <button
                          className="linkbtn"
                          onClick={() => {
                            setFocus(i);
                            setDrawer(j.apply_url);
                          }}
                        >
                          {j.title}
                        </button>
                        {j.already_applied && <span className="pill st-applied">Applied</span>}
                      </div>
                      <div className="rsub">{j.company}</div>
                    </div>
                    <span role="cell">
                      <PlatformBadge id={j.platform} className="c-plat" />
                    </span>
                    <span className="c-loc" role="cell">
                      {j.location}
                    </span>
                    <span className={cx('c-sal num', !salaryLow(j.salary) && 'muted')} role="cell">
                      {j.salary}
                    </span>
                    <span className={cx('c-exp num', j.exp_min === -1 && 'muted')} role="cell">
                      {expLabel(j.exp_min, j.exp_max)}
                    </span>
                    <span className={cx('c-post', j.posted_days_ago === 0 && 'fresh')} role="cell">
                      {postedLabel(j.posted_days_ago)}
                    </span>
                    <span className="c-easy" role="cell">
                      {j.easy_apply ? (
                        <span className="easy">
                          <Icon name="bolt" small />
                          Easy Apply
                        </span>
                      ) : (
                        <span className="help">External</span>
                      )}
                    </span>
                    <span role="cell" style={{ display: 'flex', justifyContent: 'flex-end' }}>
                      <MatchScore value={j.match_score} />
                    </span>
                  </div>
                );
              })}
              {s.running && <SkeletonRows rows={rows.length ? 2 : 4} />}
            </div>
          </div>

          {/* phone: result cards */}
          <div className="jcards" aria-label="Search results">
            {rows.map((j, i) => {
              const on = s.isSelected(j.apply_url);
              return (
                <article key={j.apply_url} className={cx('card jcard', on && 'jcard-sel', i === f && 'jcard-focus')}>
                  <label className="cbx">
                    <input type="checkbox" checked={on} onChange={() => s.toggle(j.apply_url)} aria-label={`Select ${j.title}`} />
                  </label>
                  <div style={{ minWidth: 0 }}>
                    <button className="linkbtn" style={{ fontWeight: 600, whiteSpace: 'normal' }} onClick={() => setDrawer(j.apply_url)}>
                      {j.title}
                    </button>
                    <div className="help">
                      {j.company}
                      {j.already_applied ? ' · Applied' : ''}
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span className="mbar">
                      <span style={{ width: pct(j.match_score), background: matchColor(j.match_score) }} />
                    </span>
                    <span className="mono" style={{ fontWeight: 600 }}>
                      {j.match_score.toFixed(2)}
                    </span>
                  </div>
                  <div className="jmeta">
                    <PlatformBadge id={j.platform} />
                    <span>{j.location}</span>
                    <span className="num">{j.salary}</span>
                    <span className="num">{expLabel(j.exp_min, j.exp_max)}</span>
                    <span className={j.posted_days_ago === 0 ? 'fresh' : ''}>{postedLabel(j.posted_days_ago)}</span>
                    <span>{j.easy_apply ? 'Easy Apply' : 'External'}</span>
                  </div>
                </article>
              );
            })}
            {s.running && (
              <div className="card" style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 8 }} aria-hidden="true">
                <span className="skel" style={{ width: '60%' }} />
                <span className="skel" style={{ width: '35%', height: 8 }} />
              </div>
            )}
          </div>

          {!s.running && rows.length === 0 && (
            <EmptyState
              title={s.jobs.length ? `No jobs at or above ${s.minScore.toFixed(2)}` : 'No matching jobs'}
              action={
                s.jobs.length ? (
                  <button className="btn btn-sm" onClick={() => s.setMinScore(DEFAULT_MIN)}>
                    Reset to {DEFAULT_MIN.toFixed(2)}
                  </button>
                ) : null
              }
            >
              {s.jobs.length ? 'Lower the minimum match or add keywords to see more results.' : 'Try more keywords, a wider location or a lower minimum match, then run the search again.'}
            </EmptyState>
          )}
        </section>
      )}

      {s.selected.length > 0 && !blocked && (
        <div className="selbar" role="region" aria-label="Selection">
          <span className="selcount num">{s.selected.length} selected</span>
          <span className="help hide-sm num">
            {est.will} ready to {live ? 'apply' : 'simulate'} · {est.skip} will be skipped
          </span>
          <div style={{ marginLeft: 'auto', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            <button className="btn btn-ghost btn-sm hide-sm" onClick={() => s.setSelected([])}>
              Clear
            </button>
            <button className="btn btn-sm" onClick={() => setCompare(true)} disabled={s.selected.length < 2}>
              <Icon name="compare" small />
              {s.selected.length > 4 ? 'Compare top 4' : 'Compare'}
            </button>
            <button className={cx('btn btn-sm', live ? 'btn-live' : 'btn-primary')} onClick={() => goApply()}>
              {live ? 'Bulk apply · Live' : 'Bulk apply · Dry run'}
            </button>
          </div>
        </div>
      )}

      {drawer && (
        <JobDrawer
          job={s.jobByUrl(drawer)!}
          rows={rows}
          mine={mine}
          prefLocs={prefLocs}
          onClose={() => setDrawer(null)}
          onMove={(i) => {
            setFocus(i);
            setDrawer(rows[i].apply_url);
          }}
        />
      )}
      {compare && (
        <CompareModal
          jobs={selJobs}
          mine={mine}
          onClose={() => setCompare(false)}
          onApply={(urls) => goApply(urls)}
        />
      )}
    </div>
  );
}

type ProgView = { label: string; tone: string; spin?: boolean; bar: string; width: string; count: string; state: string };

function progressView(ev: SearchPlatformEvent | undefined, inRun: boolean, session: string): ProgView {
  if (!inRun) return { label: 'Not selected', tone: 'st-queued', bar: 'pfill', width: '0%', count: '—', state: 'off' };
  if (!ev) {
    if (session === 'expired') return { label: 'Session expired', tone: 'st-failed', bar: 'pfill', width: '0%', count: 'Skipped', state: 'skipped' };
    if (session === 'not_set_up') return { label: 'Not set up', tone: 'st-skipped', bar: 'pfill', width: '0%', count: 'Skipped', state: 'skipped' };
    return { label: 'Queued', tone: 'st-queued', bar: 'pfill', width: '0%', count: '—', state: 'queued' };
  }
  const n = ev.count != null ? `${ev.count} jobs` : '—';
  switch (ev.state) {
    case 'done':
      if (ev.reason) return { label: 'Partial', tone: 'st-warn', bar: 'pfill pfill-warn', width: '100%', count: n, state: 'done' };
      return { label: 'Done', tone: 'st-applied', bar: 'pfill pfill-ok', width: '100%', count: n, state: 'done' };
    case 'fetching':
      return { label: 'Fetching', tone: 'st-applying', spin: true, bar: 'pfill pfill-ind', width: '40%', count: '…', state: 'fetching' };
    case 'queued':
      return { label: 'Queued', tone: 'st-queued', bar: 'pfill', width: '0%', count: '—', state: 'queued' };
    case 'failed':
      if (ev.reason === 'captcha_required') return { label: 'Captcha', tone: 'st-warn', bar: 'pfill pfill-warn', width: '100%', count: '0 jobs', state: 'failed' };
      if (ev.reason === 'session_expired') return { label: 'Session expired', tone: 'st-failed', bar: 'pfill', width: '0%', count: 'Skipped', state: 'failed' };
      return { label: ev.reason === 'timeout' ? 'Timed out' : 'Failed', tone: 'st-failed', bar: 'pfill pfill-bad', width: '100%', count: '0 jobs', state: 'failed' };
    case 'skipped':
    default:
      if (ev.reason === 'session_expired' && session !== 'not_set_up') return { label: 'Session expired', tone: 'st-failed', bar: 'pfill', width: '0%', count: 'Skipped', state: 'skipped' };
      if (session === 'not_set_up') return { label: 'Not set up', tone: 'st-skipped', bar: 'pfill', width: '0%', count: 'Skipped', state: 'skipped' };
      return { label: 'Skipped', tone: 'st-skipped', bar: 'pfill', width: '0%', count: 'Skipped', state: 'skipped' };
  }
}

function ProgressRow({ id, ev, inRun, session }: { id: Platform; ev?: SearchPlatformEvent; inRun: boolean; session: string }) {
  const r = progressView(ev, inRun, session);
  return (
    <div className="prow" title={ev?.message}>
      <PlatformBadge id={id} />
      <span>
        <Pill tone={r.tone} spin={r.spin}>
          {r.label}
        </Pill>
      </span>
      <span className="num help" style={{ textAlign: 'right' }}>
        {r.count}
      </span>
      <span className="pbar" aria-hidden="true">
        <span className={r.bar} style={{ width: r.width }} />
      </span>
    </div>
  );
}
