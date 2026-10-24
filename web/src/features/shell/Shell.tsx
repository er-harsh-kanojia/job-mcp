import { useEffect, useMemo } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Icon, type IconName } from '../../components/Icon';
import { cx, SESSION_LABEL, SessionDot } from '../../components/ui';
import { hhmm } from '../../lib/format';
import { useAiProvider, useBackendDown, useHealth, useLivePlatforms, useReview } from '../../lib/queries';
import { useApply } from '../../state/apply';
import { useSearch } from '../../state/search';
import { useTasks } from '../../state/tasks';
import { useUi } from '../../state/ui';
import { CommandPalette } from './CommandPalette';
import { InterviewDrawer } from '../resume/InterviewDrawer';

const TITLES: Record<string, string> = {
  '/': 'Dashboard',
  '/search': 'Search and results',
  '/apply': 'Bulk apply',
  '/applications': 'Applications',
  '/resume': 'Resume and prep',
  '/platforms': 'Platforms',
  '/profile': 'Profile',
};

/** Starts a manual login for a platform and moves to the Platforms page, where its waiting state shows. */
export function useStartLogin() {
  const { startLogin } = useTasks();
  const nav = useNavigate();
  return (id: string) => {
    void startLogin(id);
    nav('/platforms');
  };
}

/** Pages where the Live warning matters: the ones that start or run a bulk apply. */
const APPLY_PAGES = new Set(['/search', '/apply']);

export function Shell() {
  const loc = useLocation();
  const ui = useUi();
  const { setPaletteOpen, setNavOpen } = ui;
  const title = TITLES[loc.pathname] ?? 'Job MCP';

  useEffect(() => {
    document.title = `${title} · Job MCP`;
    setNavOpen(false);
  }, [title, setNavOpen]);

  // Ctrl+K / Cmd+K anywhere toggles the command palette.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        setPaletteOpen(!ui.paletteOpen);
      } else if (e.key === 'Escape' && ui.navOpen) {
        setNavOpen(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [ui.paletteOpen, ui.navOpen, setPaletteOpen, setNavOpen]);

  return (
    <>
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-[100] focus:rounded-sm focus:bg-surface focus:p-2">
        Skip to content
      </a>
      <div className="shell">
        <Sidebar />
        {ui.navOpen && (
          <div className="fixed inset-0 z-[55] bg-[var(--scrim)]" onClick={() => setNavOpen(false)} aria-hidden="true" />
        )}
        <div className="main">
          <Topbar title={title} />
          {ui.mode === 'live' && APPLY_PAGES.has(loc.pathname) && <LiveBar />}
          <BackendBanner />
          {loc.pathname !== '/apply' && <RunningApplyBar />}
          <main id="main" tabIndex={-1} className="outline-none">
            <Outlet />
          </main>
        </div>
      </div>
      {ui.paletteOpen && <CommandPalette />}
      {ui.interview && <InterviewDrawer />}
    </>
  );
}

function NavItem({ to, icon, label, children }: { to: string; icon: IconName; label: string; children?: React.ReactNode }) {
  const loc = useLocation();
  const active = to === '/search' ? loc.pathname === '/search' || loc.pathname === '/apply' : to === '/' ? loc.pathname === '/' : loc.pathname.startsWith(to);
  return (
    <NavLink to={to} className={cx('nav-btn', active && 'nav-on')} aria-current={active ? 'page' : undefined} end={to === '/'}>
      <Icon name={icon} />
      {label}
      {children}
    </NavLink>
  );
}

function Sidebar() {
  const ui = useUi();
  const health = useHealth();
  const down = useBackendDown();
  const plats = useLivePlatforms();
  const search = useSearch();
  const review = useReview(ui.role);
  const aip = useAiProvider();
  const shown = search.jobs.filter((j) => j.match_score >= search.minScore - 1e-9).length;
  const openMistakes = review.data ? review.data.issues.filter((i) => i.severity === 'mistake' && i.status === 'open').length : 0;
  const anyExpired = plats.some((p) => p.session === 'expired');
  const tools = health.data?.mcp_tools;

  return (
    <aside className={cx('sidebar', ui.navOpen && 'sidebar-open')} aria-label="Sidebar">
      <div className="brand">
        <span className="logo">
          <Icon name="logo" />
        </span>
        <div>
          <div style={{ fontWeight: 600 }}>Job MCP</div>
          <div className="help">Local · v{health.data?.version ?? '0.4'}</div>
        </div>
        {ui.navOpen && (
          <button className="btn btn-ghost btn-icon ml-auto" onClick={() => ui.setNavOpen(false)} aria-label="Close menu">
            <Icon name="x" />
          </button>
        )}
      </div>
      <nav className="navlist" aria-label="Primary">
        <NavItem to="/" icon="dashboard" label="Dashboard" />
        <NavItem to="/search" icon="search" label="Search">
          {!down && search.jobs.length > 0 && <span className="nav-count num">{shown}</span>}
        </NavItem>
        <NavItem to="/applications" icon="applications" label="Applications" />
        <NavItem to="/resume" icon="resume" label="Resume and prep">
          {openMistakes > 0 && (
            <span className="nav-count num" style={{ color: 'var(--danger)' }} aria-label={`${openMistakes} mistakes to fix`}>
              {openMistakes}
            </span>
          )}
        </NavItem>
        <NavItem to="/platforms" icon="platforms" label="Platforms">
          {anyExpired && <span className="sdot sdot-expired" style={{ marginLeft: 'auto' }} role="img" aria-label="Session expired" />}
        </NavItem>
        <NavItem to="/profile" icon="profile" label="Profile" />
      </nav>
      <div className="side-foot" role="status">
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 500 }}>
          <span className={`sdot ${down ? 'sdot-expired' : health.data ? 'sdot-ok' : 'sdot-unknown'}`} />
          {down ? 'Server unreachable' : health.data ? 'MCP server running' : 'Connecting…'}
        </div>
        <div className="help">{down ? 'Retrying every 10 s' : tools != null ? `Claude connected · ${tools} tools` : '—'}</div>
        {!down && health.data && (
          <div className="help" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span className={`sdot ${aip.configured ? 'sdot-ok' : 'sdot-none'}`} style={{ width: 6, height: 6 }} />
            Resume AI: {aip.short}
            {aip.configured ? '' : ' · not set up'}
          </div>
        )}
      </div>
    </aside>
  );
}

function Topbar({ title }: { title: string }) {
  const ui = useUi();
  const nav = useNavigate();
  const plats = useLivePlatforms();
  const down = useBackendDown();
  const health = useHealth();
  const aip = useAiProvider();
  const startLogin = useStartLogin();
  const expired = plats.filter((p) => p.session === 'expired');
  const live = ui.mode === 'live';

  return (
    <header className="topbar">
      <button className="btn btn-ghost tb-menu" onClick={() => ui.setNavOpen(true)} aria-label="Open menu" aria-expanded={ui.navOpen}>
        <Icon name="menu" />
      </button>
      <div className="tb-title">{title}</div>
      <button className="cmdk" onClick={() => ui.setPaletteOpen(true)} aria-label="Search or run a command (Ctrl+K)">
        <Icon name="search" />
        <span>Search or run a command</span>
        <span className="kbds" style={{ marginLeft: 'auto' }}>
          <span className="kbd">Ctrl</span>
          <span className="kbd">K</span>
        </span>
      </button>
      <div className="tb-right">
        <span
          className="tb-server"
          title={down ? 'Server unreachable · retrying every 10 s' : `MCP server running · Claude connected · ${health.data?.mcp_tools ?? '?'} tools · Resume AI: ${aip.short}`}
        >
          <span className={`sdot ${down ? 'sdot-expired' : 'sdot-ok'}`} role="img" aria-label={down ? 'Server unreachable' : 'Server running'} />
        </span>
        {plats.length > 0 && (
          <button className="sess-dots" aria-label="Session health. Open Platforms" onClick={() => nav('/platforms')}>
            {plats.map((p) => {
              const tip = `${p.name}: ${down ? 'Unknown, server unreachable' : SESSION_LABEL[p.session]}`;
              return (
                <span className="sess" title={tip} key={p.id}>
                  <SessionDot state={down ? 'unknown' : p.session} label={tip} />
                  <span className="sess-name">{p.name}</span>
                </span>
              );
            })}
          </button>
        )}
        {!down && expired[0] && (
          <button className="btn btn-sm btn-danger tb-login" onClick={() => startLogin(String(expired[0].id))}>
            Log in to {expired[0].name}
          </button>
        )}
        <button
          className={cx('modechip', live ? 'modechip-live' : 'modechip-dry')}
          onClick={() => ui.setMode(live ? 'dry' : 'live')}
          title={live ? 'Live mode: bulk apply submits real applications. Click to switch to Dry run.' : 'Dry run: forms are filled but never submitted. Click to switch to Live.'}
          aria-label={live ? 'Mode: Live, real applications. Switch to Dry run' : 'Mode: Dry run, simulation. Switch to Live'}
        >
          <span className="mdot" />
          {live ? 'Live' : 'Dry run'}
          <span className="mode-sub">· {live ? 'real applications' : 'Simulation'}</span>
        </button>
        <button className="btn btn-ghost btn-icon" onClick={ui.toggleTheme} aria-label={ui.theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>
          <Icon name={ui.theme === 'dark' ? 'sun' : 'moon'} />
        </button>
      </div>
    </header>
  );
}

/** A bulk apply still running while you're on another page: progress, a way back, and Stop. */
function RunningApplyBar() {
  const a = useApply();
  const nav = useNavigate();
  const run = a.run;
  if (!run || run.done) return null;
  const rows = Object.values(run.rows);
  const applied = rows.filter((r) => r.state === 'applied' || r.state === 'dry_run').length;
  const current = rows.find((r) => r.state === 'applying');
  return (
    <div className="runbar" role="status" aria-live="polite">
      <span className="spin" aria-hidden="true" />
      <strong>{run.stopping ? 'Stopping bulk apply…' : `Bulk apply running${run.live ? ' (live)' : ' (dry run)'}`}</strong>
      <span className="num">
        {run.progress.done} of {run.progress.total || '?'} done · {applied} {run.live ? 'applied' : 'would apply'}
      </span>
      {current && !run.stopping && <span className="help" style={{ color: 'inherit' }}>Now: {current.title} @ {current.company}</span>}
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
        <button className="btn btn-sm" onClick={() => nav('/apply')}>
          View
        </button>
        <button className="btn btn-sm btn-danger" onClick={() => void a.stop()} disabled={run.stopping || !run.taskId}>
          <Icon name="stop" small />
          {run.stopping ? 'Stopping…' : 'Stop'}
        </button>
      </span>
    </div>
  );
}

function LiveBar() {
  const ui = useUi();
  return (
    <div className="livebar" role="status">
      <Icon name="warn" />
      <strong style={{ letterSpacing: '.04em' }}>LIVE MODE</strong>
      <span>Bulk apply submits real applications to employers from your accounts.</span>
      <button className="btn btn-sm" onClick={() => ui.setMode('dry')} style={{ marginLeft: 'auto' }}>
        Switch to Dry run
      </button>
    </div>
  );
}

function BackendBanner() {
  const health = useHealth();
  const down = useBackendDown();
  const last = useMemo(() => (health.dataUpdatedAt ? hhmm(new Date(health.dataUpdatedAt)) : null), [health.dataUpdatedAt]);
  if (!down) return null;
  return (
    <div className="banner-err" role="alert">
      <Icon name="server" />
      <div style={{ flex: '1 1 320px' }}>
        <strong>Can't reach the Job MCP server.</strong> Search, session checks and applying are paused. Make sure the local server is running, then retry.
        {last ? ` Last contact ${last}.` : ''} Retrying every 10 s.
      </div>
      <button className="btn btn-sm" onClick={() => void health.refetch()} disabled={health.isFetching}>
        <Icon name="retry" small />
        {health.isFetching ? 'Retrying…' : 'Retry connection'}
      </button>
    </div>
  );
}

