import { useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, ApiError, errorFromPayload } from '../api';
import type { Job, Platform, SearchParams, SearchPlatformEvent } from '../api/types';
import { Overlay } from '../components/ui';
import { LIVE_PLATFORMS } from '../lib/format';
import { qk, useLastSearch, useProfile } from '../lib/queries';

export const DEFAULT_KEYWORDS = ['AI/ML Engineer', 'ML Engineer', 'AI Engineer', 'Python AI Engineer', 'AI Cloud Engineer', 'GenAI Engineer', 'LLM Engineer', 'Deep Learning Engineer'];
export const DEFAULT_MIN = 0.25;

type SearchCtx = {
  params: SearchParams;
  setParams: (p: Partial<SearchParams>) => void;
  /** Client-side minimum match filter (the slider). Runs send it as min_match_score. */
  minScore: number;
  setMinScore: (n: number) => void;
  running: boolean;
  hasRun: boolean;
  /** Platforms included in the current or last run. */
  runPlatforms: Platform[];
  platformEvents: Partial<Record<Platform, SearchPlatformEvent>>;
  jobs: Job[];
  total: number | null;
  finishedAt: string | null;
  error: ApiError | null;
  run: (override?: Partial<SearchParams>) => Promise<void>;
  /** Selection, keyed by apply_url. */
  selected: string[];
  isSelected: (url: string) => boolean;
  toggle: (url: string) => void;
  setSelected: (urls: string[]) => void;
  /** Every job seen this session, so selections survive a re-run or a filter change. */
  jobByUrl: (url: string) => Job | undefined;
  markApplied: (urls: string[]) => void;
};

const Ctx = createContext<SearchCtx | null>(null);

function byRank(a: Job, b: Job) {
  return b.rank_score - a.rank_score;
}

export function SearchProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const last = useLastSearch();
  const profile = useProfile();
  const [params, setParamsState] = useState<SearchParams>({
    keywords: DEFAULT_KEYWORDS,
    location: 'India',
    experience_years: 4,
    platforms: [...LIVE_PLATFORMS],
    min_match_score: DEFAULT_MIN,
    max_jobs: 50,
    exclude_companies: [],
  });
  const [minScore, setMinScore] = useState(DEFAULT_MIN);
  const [running, setRunning] = useState(false);
  const [hasRun, setHasRun] = useState(false);
  const [runPlatforms, setRunPlatforms] = useState<Platform[]>([]);
  const [platformEvents, setPlatformEvents] = useState<Partial<Record<Platform, SearchPlatformEvent>>>({});
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [finishedAt, setFinishedAt] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [selected, setSelectedState] = useState<string[]>([]);
  const [limitDialog, setLimitDialog] = useState<{ value: number | null } | null>(null);
  const limitResolver = useRef<((value: number | null | undefined) => void) | null>(null);
  const known = useRef(new Map<string, Job>());
  const unsub = useRef<(() => void) | null>(null);
  const seeded = useRef(false);
  const touched = useRef(false);

  const remember = (list: Job[]) => list.forEach((j) => known.current.set(j.apply_url, j));

  // Seed from GET /api/search/last once, unless the user already started a run.
  useEffect(() => {
    if (seeded.current || last.data === undefined || hasRun) return;
    seeded.current = true;
    const l = last.data;
    if (!l) return;
    remember(l.jobs);
    setParamsState({ ...l.params, max_jobs: l.params.max_jobs ?? 50, exclude_companies: l.params.exclude_companies ?? [] });
    setMinScore(l.params.min_match_score);
    setJobs([...l.jobs].sort(byRank));
    setRunPlatforms(l.params.platforms);
    const ev: Partial<Record<Platform, SearchPlatformEvent>> = {};
    l.platforms.forEach((p) => (ev[p.platform] = p));
    setPlatformEvents(ev);
    const counted = l.platforms.reduce((a, p) => a + (p.count ?? 0), 0);
    setTotal(l.total ?? (counted || l.jobs.length));
    setFinishedAt(l.finished_at);
  }, [last.data, hasRun]);

  // Without a previous search, take experience and default excluded companies from the profile.
  useEffect(() => {
    if (!touched.current && !last.data && profile.data) {
      setParamsState((p) => ({
        ...p,
        experience_years: profile.data.experience_years,
        exclude_companies: p.exclude_companies?.length ? p.exclude_companies : (profile.data.excluded_companies ?? []),
      }));
    }
  }, [profile.data, last.data]);

  useEffect(() => () => unsub.current?.(), []);

  const setParams = useCallback((p: Partial<SearchParams>) => {
    touched.current = true;
    setParamsState((cur) => ({ ...cur, ...p }));
  }, []);

  const askMaxJobs = useCallback((initial: number | null): Promise<number | null | undefined> => {
    setLimitDialog({ value: initial });
    return new Promise((resolve) => { limitResolver.current = resolve; });
  }, []);
  const finishLimitDialog = useCallback((value: number | null | undefined) => {
    setLimitDialog(null);
    limitResolver.current?.(value);
    limitResolver.current = null;
  }, []);

  const run = useCallback(
    async (override?: Partial<SearchParams>) => {
      const initial: SearchParams = { ...params, ...override, min_match_score: override?.min_match_score ?? minScore };
      const maxJobs = await askMaxJobs(initial.max_jobs ?? 50);
      if (maxJobs === undefined) return;
      setParamsState((cur) => ({ ...cur, max_jobs: maxJobs }));
      const body: SearchParams = { ...initial, max_jobs: maxJobs };
      unsub.current?.();
      setHasRun(true);
      setRunning(true);
      setError(null);
      setJobs([]);
      setTotal(null);
      setRunPlatforms(body.platforms);
      const queued: Partial<Record<Platform, SearchPlatformEvent>> = {};
      body.platforms.forEach((p) => (queued[p] = { platform: p, state: 'queued' }));
      setPlatformEvents(queued);
      let taskId: string;
      try {
        taskId = (await api.search(body)).task_id;
      } catch (e) {
        setRunning(false);
        setError(e instanceof ApiError ? e : errorFromPayload(0, e));
        return;
      }
      unsub.current = api.subscribe('search', taskId, (ev) => {
        if (ev.type === 'platform') {
          setPlatformEvents((cur) => ({ ...cur, [ev.data.platform]: ev.data }));
        } else if (ev.type === 'jobs') {
          remember(ev.data.jobs);
          setJobs((cur) => {
            const m = new Map(cur.map((j) => [j.apply_url, j]));
            ev.data.jobs.forEach((j) => m.set(j.apply_url, j));
            const ranked = [...m.values()].sort(byRank);
            return body.max_jobs === null ? ranked : ranked.slice(0, body.max_jobs ?? 50);
          });
        } else if (ev.type === 'done') {
          remember(ev.data.jobs);
          const ranked = [...ev.data.jobs].sort(byRank);
          setJobs(body.max_jobs === null ? ranked : ranked.slice(0, body.max_jobs ?? 50));
          setTotal(ev.data.total);
          setFinishedAt(new Date().toISOString());
          setRunning(false);
          // Platforms still marked queued/fetching never reported; treat them as done with nothing.
          setPlatformEvents((cur) => {
            const next = { ...cur };
            (Object.keys(next) as Platform[]).forEach((p) => {
              const s = next[p]?.state;
              if (s === 'queued' || s === 'fetching') next[p] = { platform: p, state: 'done', count: 0 };
            });
            return next;
          });
          void qc.invalidateQueries({ queryKey: qk.lastSearch });
          void qc.invalidateQueries({ queryKey: ['review'] });
        } else if (ev.type === 'error') {
          setError(ev.data);
          setRunning(false);
        }
      });
    },
    [params, minScore, qc, askMaxJobs],
  );

  const toggle = useCallback((url: string) => {
    setSelectedState((cur) => (cur.includes(url) ? cur.filter((u) => u !== url) : [...cur, url]));
  }, []);

  const markApplied = useCallback((urls: string[]) => {
    const set = new Set(urls);
    setJobs((cur) => cur.map((j) => (set.has(j.apply_url) ? { ...j, already_applied: true } : j)));
    urls.forEach((u) => {
      const j = known.current.get(u);
      if (j) known.current.set(u, { ...j, already_applied: true });
    });
  }, []);

  const value = useMemo<SearchCtx>(() => {
    const sel = new Set(selected);
    return {
      params,
      setParams,
      minScore,
      setMinScore,
      running,
      hasRun,
      runPlatforms,
      platformEvents,
      jobs,
      total,
      finishedAt,
      error,
      run,
      selected,
      isSelected: (u) => sel.has(u),
      toggle,
      setSelected: setSelectedState,
      jobByUrl: (u) => known.current.get(u),
      markApplied,
    };
  }, [params, setParams, minScore, running, hasRun, runPlatforms, platformEvents, jobs, total, finishedAt, error, run, selected, toggle, markApplied]);

  return (
    <Ctx.Provider value={value}>
      {children}
      {limitDialog && (
        <Overlay variant="center" onClose={() => finishLimitDialog(undefined)} scrimLabel="Cancel job search">
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="search-limit-title" style={{ width: 'min(440px, 100%)', padding: 22 }}>
            <h2 className="h2" id="search-limit-title">How many jobs should we fetch?</h2>
            <p className="help" style={{ margin: '8px 0 18px' }}>Choose a maximum before the search starts.</p>
            <label className="field">
              <span className="lbl">Maximum number of jobs (1–1000)</span>
              <input className="input num" type="number" min={1} max={1000} disabled={limitDialog.value === null}
                value={limitDialog.value ?? ''}
                onChange={(e) => setLimitDialog({ value: Math.max(1, Math.min(1000, Number(e.target.value) || 1)) })}
                aria-label="Maximum number of jobs" />
            </label>
            <label className="help" style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
              <input type="checkbox" checked={limitDialog.value === null}
                onChange={(e) => setLimitDialog({ value: e.target.checked ? null : 50 })} />
              Fetch all available jobs
            </label>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 22 }}>
              <button className="btn" onClick={() => finishLimitDialog(undefined)}>Cancel</button>
              <button className="btn btn-primary" onClick={() => finishLimitDialog(limitDialog.value)}>Start search</button>
            </div>
          </section>
        </Overlay>
      )}
    </Ctx.Provider>
  );
}

export function useSearch(): SearchCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error('useSearch outside SearchProvider');
  return c;
}
