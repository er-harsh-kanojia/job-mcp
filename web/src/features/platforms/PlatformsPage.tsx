import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, errorMessage } from '../../api';
import type { PlatformInfo } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Alert, cx, LoadingCard, PlatformBadge } from '../../components/ui';
import { ago, hhmm, parseTime, PLATFORM_ORDER } from '../../lib/format';
import { qk, useBackendDown, usePlatforms } from '../../lib/queries';
import { useTasks, type LoginTask } from '../../state/tasks';

const DESC: Record<string, string> = {
  naukri: 'Searches Naukri and applies to jobs with the Apply button, using your Naukri profile.',
  instahyre: 'Searches your Instahyre matches and applies with one click.',
  hirist: 'Searches Hirist tech jobs and applies with your Hirist profile.',
  indeed: 'Planned. Direct search and Indeed Apply integration.',
  linkedin: 'Planned. Search and Easy Apply support are in progress.',
  wellfound: 'Planned. Startup roles with salary and equity ranges.',
};
const DOMAINS: Record<string, string> = { naukri: 'naukri.com/nlogin', instahyre: 'instahyre.com/login', hirist: 'hirist.tech/login' };

export function PlatformsPage() {
  const q = usePlatforms();
  const down = useBackendDown();
  const qc = useQueryClient();
  const [checking, setChecking] = useState<Record<string, boolean>>({});
  const [checkErr, setCheckErr] = useState<string | null>(null);
  const plats = [...(q.data ?? [])].sort((a, b) => Number(b.live) - Number(a.live) || PLATFORM_ORDER.indexOf(a.id) - PLATFORM_ORDER.indexOf(b.id));

  const check = useMutation({
    mutationFn: (id: string) => api.checkPlatform(id),
    onMutate: (id) => setChecking((c) => ({ ...c, [id]: true })),
    onSuccess: (p) => {
      setCheckErr(null);
      qc.setQueryData<PlatformInfo[]>(qk.platforms, (cur) => cur?.map((x) => (x.id === p.id ? p : x)));
    },
    onError: (e) => setCheckErr(errorMessage(e)),
    onSettled: (_d, _e, id) => setChecking((c) => ({ ...c, [id]: false })),
  });
  const checkAll = () => plats.filter((p) => p.live).forEach((p) => check.mutate(String(p.id)));

  return (
    <div className="page">
      <div className="pagehead">
        <div>
          <h1 className="h1">Platforms and sessions</h1>
          <p className="sub">Job MCP reuses the browser sessions you create here. It never sees or stores your passwords.</p>
        </div>
        <button className="btn" onClick={checkAll} disabled={down || !plats.length || Object.values(checking).some(Boolean)}>
          <Icon name="retry" small />
          Check all sessions
        </button>
      </div>
      {checkErr && (
        <Alert tone="danger" title="Couldn't check the session">
          {checkErr}
        </Alert>
      )}
      {q.isLoading && <LoadingCard label="Loading platforms…" />}
      {q.error && !down && <Alert tone="danger" title="Couldn't load platforms">{errorMessage(q.error)}</Alert>}
      <div className="pgrid">
        {plats.map((p) => (
          <PlatformCard key={p.id} p={p} down={down} checking={!!checking[p.id]} onCheck={() => check.mutate(String(p.id))} />
        ))}
      </div>
      <Alert tone="info" icon="lock" title="How login works">
        Login opens the portal in a real browser window. You sign in yourself; Job MCP saves only the session cookies on this machine and checks them before every search and apply run.
      </Alert>
    </div>
  );
}

function checkedText(p: PlatformInfo, down: boolean): string {
  if (down) return 'Can’t check while the server is unreachable';
  const d = parseTime(p.last_checked);
  if (p.session === 'not_set_up') return 'Never logged in';
  if (!d) return 'Not checked yet';
  if (p.session === 'expired') return `Expired · last checked ${hhmm(d)}`;
  return `Last checked ${hhmm(d)} · ${ago(p.last_checked)}`;
}

function PlatformCard({ p, down, checking, onCheck }: { p: PlatformInfo; down: boolean; checking: boolean; onCheck: () => void }) {
  const t = useTasks();
  const qc = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [notYet, setNotYet] = useState(false);
  const task: LoginTask | undefined = t.logins[String(p.id)];
  if (!p.live) {
    return (
      <article className="card pcard pcard-soon">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
          <PlatformBadge id={p.id} name={p.name} large />
          <span className="pill st-queued">Coming soon</span>
        </div>
        <p>{DESC[p.id] ?? 'Planned.'}</p>
        <div className="help">Not available yet</div>
        <div style={{ marginTop: 'auto' }}>
          <button className="btn" disabled>
            Coming soon
          </button>
        </div>
      </article>
    );
  }
  const waiting = !!task && !task.error && task.state !== 'timeout' && task.state !== 'logged_in';
  const state = down ? 'unknown' : p.session;
  const M: Record<string, [string, string, string]> = {
    logged_in: ['Logged in', 'st-applied', ''],
    expired: ['Session expired', 'st-failed', 'pcard-expired'],
    not_set_up: ['Not set up', 'st-skipped', ''],
    unknown: ['Unknown', 'st-queued', ''],
  };
  const [label, tone, cardCls] = waiting ? ['Waiting for login', 'st-applying', 'pcard-waiting'] : M[state];
  const id = String(p.id);
  // "I've finished": the contract has no endpoint for this, so re-check the session; the login task ends on its own.
  const finished = async () => {
    setConfirming(true);
    setNotYet(false);
    try {
      const fresh = await api.checkPlatform(id);
      qc.setQueryData<PlatformInfo[]>(qk.platforms, (cur) => cur?.map((x) => (x.id === fresh.id ? fresh : x)));
      if (fresh.session === 'logged_in') t.dismissLogin(id);
      else setNotYet(true);
    } catch {
      setNotYet(true);
    } finally {
      setConfirming(false);
    }
  };

  return (
    <article className={cx('card pcard', cardCls)} aria-busy={waiting}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <PlatformBadge id={p.id} name={p.name} large />
        <span className={`pill ${tone}`}>
          {waiting && <span className="spin" aria-hidden="true" />}
          {label}
        </span>
      </div>
      <p>{DESC[id] ?? `Searches and applies on ${p.name}.`}</p>
      <div className="help num">{waiting ? 'Login window open' : checkedText(p, down)}</div>
      {!waiting && p.error && <div className="err">{p.error}</div>}
      {waiting && (
        <div className={cx('waitbox', task.state === 'captcha' && 'waitbox-warn')} role="status" aria-live="polite">
          <span className="spin spin-lg" aria-hidden="true" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontWeight: 600 }}>{task.state === 'captcha' ? 'Solve the captcha in the browser window…' : task.state === 'starting' ? 'Opening a browser window…' : 'Waiting for you to finish logging in…'}</div>
            <div className="help" style={{ color: 'var(--text-2)' }}>
              {task.state === 'captcha'
                ? `${p.name} is showing a captcha. Solve it in the window that opened, then finish signing in. This card updates when the session is saved.`
                : `A browser window opened at ${DOMAINS[id] ?? p.name}. Sign in there, including any OTP. This card updates when the session is saved.`}
            </div>
            {notYet && <div className="help" style={{ color: 'var(--warning)' }}>Not logged in yet. Finish signing in, then try again.</div>}
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="btn btn-sm btn-primary" onClick={() => void finished()} disabled={task.state === 'starting' || confirming}>
                {confirming ? 'Checking…' : 'I’ve finished'}
              </button>
              <button className="btn btn-sm btn-ghost" onClick={() => void t.cancelLogin(id)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
      {task?.state === 'timeout' && (
        <Alert tone="warn" title="The login window timed out" actions={<button className="btn btn-sm" onClick={() => t.dismissLogin(id)}>Dismiss</button>}>
          Nothing was saved. Try again when you’re ready to sign in.
        </Alert>
      )}
      {task?.error && (
        <Alert tone="danger" title="Login didn't finish" actions={<button className="btn btn-sm" onClick={() => t.dismissLogin(id)}>Dismiss</button>}>
          {errorMessage(task.error)}
        </Alert>
      )}
      {!waiting && (
        <div style={{ display: 'flex', gap: 8, marginTop: 'auto' }}>
          <button className={cx('btn', state !== 'logged_in' && 'btn-primary')} onClick={() => void t.startLogin(id)} disabled={down}>
            <Icon name="external" small />
            {state === 'logged_in' ? 'Re-login' : 'Log in'}
          </button>
          <button className="btn btn-ghost" onClick={onCheck} disabled={down || checking}>
            {checking && <span className="spin" aria-hidden="true" />}
            {checking ? 'Checking…' : 'Check now'}
          </button>
        </div>
      )}
    </article>
  );
}
