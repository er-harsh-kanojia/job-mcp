import { useQueryClient } from '@tanstack/react-query';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, ApiError, errorFromPayload } from '../api';
import type { AnalyseStepEvent, LoginState, PlatformInfo, Review } from '../api/types';
import { qk } from '../lib/queries';

export type LoginTask = { taskId: string | null; state: LoginState | 'starting'; error: ApiError | null };
export type AnalyseTask = { role: string; taskId: string | null; steps: AnalyseStepEvent[]; error: ApiError | null };

type TasksCtx = {
  logins: Record<string, LoginTask>;
  startLogin: (id: string) => Promise<void>;
  cancelLogin: (id: string) => Promise<void>;
  dismissLogin: (id: string) => void;
  analysis: AnalyseTask | null;
  startAnalysis: (role: string, compareTo?: number) => Promise<void>;
  clearAnalysisError: () => void;
};

const Ctx = createContext<TasksCtx | null>(null);

/** App-level long-running tasks (platform logins and resume analysis), so they survive navigation. */
export function TasksProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [logins, setLogins] = useState<Record<string, LoginTask>>({});
  const [analysis, setAnalysis] = useState<AnalyseTask | null>(null);
  const subs = useRef(new Map<string, () => void>());

  useEffect(() => {
    const m = subs.current;
    return () => m.forEach((u) => u());
  }, []);

  const patchLogin = (id: string, p: Partial<LoginTask>) =>
    setLogins((cur) => (cur[id] ? { ...cur, [id]: { ...cur[id], ...p } } : cur));

  const updatePlatform = useCallback(
    (p: PlatformInfo) => {
      qc.setQueryData<PlatformInfo[]>(qk.platforms, (cur) => (cur ? cur.map((x) => (x.id === p.id ? p : x)) : cur));
      void qc.invalidateQueries({ queryKey: qk.platforms });
    },
    [qc],
  );

  const dismissLogin = useCallback((id: string) => {
    subs.current.get(`login:${id}`)?.();
    subs.current.delete(`login:${id}`);
    setLogins((cur) => {
      const next = { ...cur };
      delete next[id];
      return next;
    });
  }, []);

  const startLogin = useCallback(
    async (id: string) => {
      setLogins((cur) => ({ ...cur, [id]: { taskId: null, state: 'starting', error: null } }));
      try {
        const { task_id } = await api.login(id);
        patchLogin(id, { taskId: task_id, state: 'waiting_for_user' });
        subs.current.get(`login:${id}`)?.();
        subs.current.set(
          `login:${id}`,
          api.subscribe('login', task_id, (ev) => {
            if (ev.type === 'status') {
              patchLogin(id, { state: ev.data.state });
            } else if (ev.type === 'done') {
              const info = typeof ev.data.platform === 'object' ? ev.data.platform : ev.data.platform_info;
              if (info) updatePlatform(info);
              else void qc.invalidateQueries({ queryKey: qk.platforms });
              setLogins((cur) => {
                const t = cur[id];
                // Keep a timeout visible until dismissed; otherwise the card goes back to normal.
                if (t && t.state === 'timeout') return cur;
                const next = { ...cur };
                delete next[id];
                return next;
              });
              subs.current.delete(`login:${id}`);
            } else if (ev.type === 'error') {
              if (ev.data.code === 'cancelled') dismissLogin(id);
              else patchLogin(id, { error: ev.data });
              void qc.invalidateQueries({ queryKey: qk.platforms });
              subs.current.delete(`login:${id}`);
            }
          }),
        );
      } catch (e) {
        patchLogin(id, { error: e instanceof ApiError ? e : errorFromPayload(0, e) });
      }
    },
    [qc, updatePlatform, dismissLogin],
  );

  const cancelLogin = useCallback(
    async (id: string) => {
      const t = logins[id];
      dismissLogin(id);
      if (t?.taskId) {
        try {
          await api.cancelTask(t.taskId);
        } catch {
          // nothing to do; the login window may already be closed
        }
      }
      void qc.invalidateQueries({ queryKey: qk.platforms });
    },
    [logins, dismissLogin, qc],
  );

  const startAnalysis = useCallback(
    async (role: string, compareTo?: number) => {
      subs.current.get('analyse')?.();
      setAnalysis({ role, taskId: null, steps: [], error: null });
      try {
        const { task_id } = await api.analyse(role, compareTo);
        setAnalysis((a) => (a ? { ...a, taskId: task_id } : a));
        subs.current.set(
          'analyse',
          api.subscribe('analyse', task_id, (ev) => {
            if (ev.type === 'step') {
              setAnalysis((a) => {
                if (!a) return a;
                const steps = [...a.steps];
                steps[ev.data.index] = ev.data;
                return { ...a, steps };
              });
            } else if (ev.type === 'done') {
              qc.setQueryData<Review | null>(qk.review(role), ev.data.review);
              void qc.invalidateQueries({ queryKey: ['reviews'] });
              setAnalysis(null);
              subs.current.delete('analyse');
            } else if (ev.type === 'error') {
              setAnalysis((a) => (a ? { ...a, error: ev.data } : a));
              subs.current.delete('analyse');
            }
          }),
        );
      } catch (e) {
        setAnalysis((a) => (a ? { ...a, error: e instanceof ApiError ? e : errorFromPayload(0, e) } : a));
      }
    },
    [qc],
  );

  const value = useMemo<TasksCtx>(
    () => ({ logins, startLogin, cancelLogin, dismissLogin, analysis, startAnalysis, clearAnalysisError: () => setAnalysis(null) }),
    [logins, startLogin, cancelLogin, dismissLogin, analysis, startAnalysis],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useTasks(): TasksCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error('useTasks outside TasksProvider');
  return c;
}
