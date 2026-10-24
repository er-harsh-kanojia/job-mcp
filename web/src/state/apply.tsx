import { useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, ApiError, errorFromPayload } from '../api';
import type { ApplyJobState, ApplyPreview, Job, Platform, SkipReason } from '../api/types';
import { platName } from '../lib/format';
import { qk } from '../lib/queries';
import { useSearch } from './search';

export type RowState = ApplyJobState;
export type RunRow = {
  url: string;
  title: string;
  company: string;
  platform: Platform;
  state: RowState;
  reason: string;
  permanent?: boolean;
};
export type ApplyRun = {
  taskId: string | null;
  live: boolean;
  retry: boolean;
  order: string[];
  rows: Record<string, RunRow>;
  progress: { done: number; total: number };
  done: boolean;
  stopping: boolean;
  stopped: boolean;
  error: ApiError | null;
};

export function skipReasonText(reason: SkipReason, job: Job, max: number): string {
  switch (reason) {
    case 'already_applied':
      return `Already applied on ${platName(job.platform)}`;
    case 'not_easy_apply':
      return 'Not Easy Apply. Apply on the employer site.';
    case 'over_limit':
      return `Over your limit of ${max} for this run`;
    case 'session_expired':
      return `${platName(job.platform)} session expired`;
    case 'excluded_company':
      return `Excluded company (${job.company})`;
    default:
      return 'Skipped';
  }
}

type ApplyCtx = {
  step: number;
  setStep: (n: number) => void;
  maxApps: number;
  setMaxApps: (n: number) => void;
  confirmText: string;
  setConfirmText: (s: string) => void;
  run: ApplyRun | null;
  /** URLs queued for a retry pass that still needs confirmation (live mode). */
  retryUrls: string[] | null;
  begin: () => void;
  /** Re-attach to a run that is still going on the server (e.g. after a page reload). */
  attach: (taskId: string, live: boolean) => void;
  start: (args: { preview: ApplyPreview; live: boolean; urls: string[] }) => Promise<void>;
  startRetry: (urls: string[], live: boolean) => Promise<void>;
  prepareRetry: (urls: string[]) => void;
  stop: () => Promise<void>;
};

const Ctx = createContext<ApplyCtx | null>(null);

export function ApplyProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const { markApplied } = useSearch();
  const [step, setStep] = useState(0);
  const [maxApps, setMaxApps] = useState(20);
  const [confirmText, setConfirmText] = useState('');
  const [run, setRun] = useState<ApplyRun | null>(null);
  const [retryUrls, setRetryUrls] = useState<string[] | null>(null);
  const unsub = useRef<(() => void) | null>(null);

  useEffect(() => () => unsub.current?.(), []);

  const listen = useCallback(
    (taskId: string) => {
      unsub.current?.();
      unsub.current = api.subscribe('apply', taskId, (ev) => {
        if (ev.type === 'job') {
          const d = ev.data;
          if (d.state === 'applied') markApplied([d.apply_url]);
          setRun((r) => {
            if (!r) return r;
            const prev = r.rows[d.apply_url];
            const reason =
              d.state === 'applying'
                ? 'Filling the application form…'
                : d.state === 'applied'
                  ? 'Submitted'
                  : d.state === 'dry_run'
                    ? 'Form filled, stopped before submit'
                    : d.state === 'queued'
                      ? 'Waiting'
                      : d.state === 'skipped' && d.error === 'cancelled'
                        ? 'Stopped before this job'
                        : d.state === 'skipped' && prev?.state === 'skipped'
                          ? prev.reason
                          : d.error || prev?.reason || (d.state === 'failed' ? 'Failed' : 'Skipped');
            const row: RunRow = { url: d.apply_url, title: d.title, company: d.company, platform: d.platform, state: d.state, reason, permanent: d.permanent };
            // Don't let a server "queued" overwrite a skip we already know the reason for.
            if (d.state === 'queued' && prev && prev.state === 'skipped') return r;
            return {
              ...r,
              order: r.order.includes(d.apply_url) ? r.order : [...r.order, d.apply_url],
              rows: { ...r.rows, [d.apply_url]: row },
            };
          });
        } else if (ev.type === 'progress') {
          setRun((r) => (r ? { ...r, progress: ev.data } : r));
        } else if (ev.type === 'done' || ev.type === 'error') {
          setRun((r) => {
            if (!r) return r;
            const rows = { ...r.rows };
            const stopped = r.stopping || (ev.type === 'done' && !!ev.data.summary?.cancelled) || (ev.type === 'error' && ev.data.code === 'cancelled');
            for (const u of r.order) {
              const s = rows[u].state;
              if (s === 'queued' || s === 'applying') rows[u] = { ...rows[u], state: 'skipped', reason: stopped ? 'Stopped before this job' : 'Not processed' };
            }
            return { ...r, rows, done: true, stopped, stopping: false, error: ev.type === 'error' && ev.data.code !== 'cancelled' ? ev.data : null };
          });
          void qc.invalidateQueries({ queryKey: qk.stats });
          void qc.invalidateQueries({ queryKey: ['applications'] });
        }
      });
    },
    [markApplied, qc],
  );

  const kick = useCallback(
    async (urls: string[], live: boolean, base: Omit<ApplyRun, 'taskId'>) => {
      setRun({ ...base, taskId: null });
      setStep(2);
      setConfirmText('');
      setRetryUrls(null);
      try {
        const { task_id } = await api.apply({
          apply_urls: urls,
          max_applications: maxApps,
          dry_run: !live,
          ...(live ? { confirm: 'APPLY' as const } : {}),
        });
        setRun((r) => (r ? { ...r, taskId: task_id } : r));
        listen(task_id);
      } catch (e) {
        const err = e instanceof ApiError ? e : errorFromPayload(0, e);
        setRun((r) => (r ? { ...r, done: true, error: err } : r));
      }
    },
    [listen, maxApps],
  );

  const start = useCallback(
    async ({ preview, live, urls }: { preview: ApplyPreview; live: boolean; urls: string[] }) => {
      const rows: Record<string, RunRow> = {};
      const all: { job: Job; will: boolean; reason: string }[] = [
        ...preview.will_apply.map((job) => ({ job, will: true, reason: 'Waiting' })),
        ...preview.will_skip.map((s) => ({ job: s.job, will: false, reason: skipReasonText(s.reason, s.job, maxApps) })),
      ].sort((a, b) => b.job.rank_score - a.job.rank_score);
      for (const x of all) {
        rows[x.job.apply_url] = {
          url: x.job.apply_url,
          title: x.job.title,
          company: x.job.company,
          platform: x.job.platform,
          state: x.will ? 'queued' : 'skipped',
          reason: x.reason,
        };
      }
      await kick(urls, live, {
        live,
        retry: false,
        order: all.map((x) => x.job.apply_url),
        rows,
        progress: { done: 0, total: preview.will_apply.length },
        done: false,
        stopping: false,
        stopped: false,
        error: null,
      });
    },
    [kick, maxApps],
  );

  const startRetry = useCallback(
    async (urls: string[], live: boolean) => {
      const prev = run;
      const rows = { ...(prev?.rows ?? {}) };
      urls.forEach((u) => {
        if (rows[u]) rows[u] = { ...rows[u], state: 'queued', reason: 'Waiting', permanent: undefined };
      });
      await kick(urls, live, {
        live,
        retry: true,
        order: prev?.order ?? urls,
        rows,
        progress: { done: 0, total: urls.length },
        done: false,
        stopping: false,
        stopped: false,
        error: null,
      });
    },
    [kick, run],
  );

  const prepareRetry = useCallback((urls: string[]) => {
    setRetryUrls(urls);
    setConfirmText('');
    setStep(1);
  }, []);

  const attach = useCallback(
    (taskId: string, live: boolean) => {
      // Events replay from the start, so the rows rebuild themselves.
      setRun({ taskId, live, retry: false, order: [], rows: {}, progress: { done: 0, total: 0 }, done: false, stopping: false, stopped: false, error: null });
      setStep(2);
      listen(taskId);
    },
    [listen],
  );

  // After a reload, pick up a bulk apply that is still running on the server.
  const attachIfIdle = useRef<(id: string, live: boolean) => void>(() => {});
  attachIfIdle.current = (id, live) => {
    if (!run || run.done) attach(id, live);
  };
  const checked = useRef(false);
  useEffect(() => {
    if (checked.current) return;
    checked.current = true;
    api
      .tasks('apply', 'running')
      .then(({ tasks }) => {
        const t = tasks[0];
        if (t) attachIfIdle.current(t.id, t.meta?.dry_run === false);
      })
      .catch(() => {
        // backend unreachable: nothing to re-attach to
      });
  }, []);

  const stop = useCallback(async () => {
    const id = run?.taskId;
    setRun((r) => (r ? { ...r, stopping: true } : r));
    if (id) {
      try {
        await api.cancelTask(id);
      } catch {
        // the stream's done/error event still ends the run
      }
    }
  }, [run?.taskId]);

  const begin = useCallback(() => {
    if (run && !run.done) return; // keep showing a run in progress
    setStep(0);
    setRun(null);
    setConfirmText('');
    setRetryUrls(null);
  }, [run]);

  const value = useMemo<ApplyCtx>(
    () => ({ step, setStep, maxApps, setMaxApps, confirmText, setConfirmText, run, retryUrls, begin, attach, start, startRetry, prepareRetry, stop }),
    [step, maxApps, confirmText, run, retryUrls, begin, attach, start, startRetry, prepareRetry, stop],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApply(): ApplyCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error('useApply outside ApplyProvider');
  return c;
}
