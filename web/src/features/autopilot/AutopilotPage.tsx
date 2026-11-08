import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, errorMessage } from '../../api';
import type { AutopilotConfig, AutopilotStatus, AutopilotUpdate } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Alert, Bar, cx, LoadingCard, Pill } from '../../components/ui';
import { fmtDayTime, platName } from '../../lib/format';
import { useApply } from '../../state/apply';

const KEY = ['autopilot'] as const;
const STATUS_TONE: Record<string, string> = { done: 'st-applied', running: 'st-applying', cancelled: 'st-skipped', interrupted: 'st-skipped', error: 'st-failed' };

export function AutopilotPage() {
  const q = useQuery({ queryKey: KEY, queryFn: () => api.autopilot(), refetchInterval: 15_000 });
  if (q.isLoading) return <div className="page"><LoadingCard label="Loading autopilot…" /></div>;
  if (!q.data)
    return (
      <div className="page">
        <Alert tone="danger" title="Couldn't load autopilot" actions={<button className="btn btn-sm" onClick={() => void q.refetch()}>Retry</button>}>
          {errorMessage(q.error)}
        </Alert>
      </div>
    );
  return <Autopilot s={q.data} />;
}

function Autopilot({ s }: { s: AutopilotStatus }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const apply = useApply();
  const [draft, setDraft] = useState<AutopilotConfig>(s.config);
  const [confirmLive, setConfirmLive] = useState(false);
  const [typed, setTyped] = useState('');
  const [kw, setKw] = useState('');
  const [time, setTime] = useState('13:00');
  useEffect(() => setDraft(s.config), [s.config]);

  const save = useMutation({
    mutationFn: (body: AutopilotUpdate) => api.setAutopilot(body),
    onSuccess: (data) => {
      qc.setQueryData(KEY, data);
      setConfirmLive(false);
      setTyped('');
    },
  });
  const runNow = useMutation({
    mutationFn: () => api.runAutopilot(),
    onSuccess: ({ task_id }) => {
      apply.attach(task_id, s.config.live, true);
      void qc.invalidateQueries({ queryKey: KEY });
    },
  });

  const dirty = JSON.stringify(draft) !== JSON.stringify(s.config);
  const set = (patch: Partial<AutopilotConfig>) => setDraft((d) => ({ ...d, ...patch }));
  const running = !!s.running_task_id || (!!apply.run && !apply.run.done);
  const err = save.error || runNow.error;

  return (
    <div className="page">
      <div className="pagehead">
        <div>
          <h1 className="h1">Autopilot</h1>
          <p className="sub">Searches and applies on a schedule, within your daily limits, while Job MCP is running.</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {running && (
            <button className="btn" onClick={() => nav('/apply')}>
              View current run
            </button>
          )}
          <button className="btn btn-primary" onClick={() => runNow.mutate()} disabled={running || runNow.isPending}>
            <Icon name="play" small />
            Run now {s.config.live ? '(live)' : '(dry run)'}
          </button>
        </div>
      </div>

      {err && <Alert tone="danger" title="That didn't work">{errorMessage(err)}</Alert>}

      <section className="card" style={{ padding: 16, display: 'grid', gap: 16, gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span className="eyebrow">Schedule</span>
          <label className="switch">
            <input type="checkbox" checked={s.config.enabled} onChange={() => save.mutate({ enabled: !s.config.enabled })} disabled={save.isPending} />
            {s.config.enabled ? 'On' : 'Off'}
          </label>
          <span className="help">
            {s.config.enabled && s.next_run_at ? `Next run ${fmtDayTime(s.next_run_at)}` : 'Turn on to run at the times below.'}
          </span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span className="eyebrow">Mode</span>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className={cx('btn btn-sm', !s.config.live && 'chip-on')} onClick={() => s.config.live && save.mutate({ live: false })} aria-pressed={!s.config.live}>
              Dry run
            </button>
            <button className={cx('btn btn-sm', s.config.live && 'btn-danger chip-on')} onClick={() => !s.config.live && setConfirmLive(true)} aria-pressed={s.config.live}>
              Live
            </button>
          </div>
          <span className="help">{s.config.live ? 'Real applications are submitted.' : 'Fills forms but never submits. Use it to check the setup.'}</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span className="eyebrow">Today</span>
          {s.config.platforms.map((p) => {
            const cap = s.config.daily_caps[p] ?? 0;
            const n = s.today[p] ?? 0;
            return (
              <div key={p} style={{ display: 'grid', gridTemplateColumns: '90px 1fr auto', gap: 8, alignItems: 'center' }}>
                <span>{platName(p)}</span>
                <Bar value={cap ? (n / cap) * 100 : 0} color={n >= cap ? 'var(--success)' : 'var(--accent)'} />
                <span className="mono help">
                  {n}/{cap}
                </span>
              </div>
            );
          })}
        </div>
      </section>

      {confirmLive && (
        <Alert
          tone="warn"
          title="Turn on live autopilot?"
          actions={
            <>
              <input className="input" style={{ width: 120 }} value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Type APPLY" aria-label="Type APPLY to confirm" />
              <button className="btn btn-sm btn-danger" disabled={typed !== 'APPLY' || save.isPending} onClick={() => save.mutate({ live: true, confirm: 'APPLY' })}>
                Turn on live
              </button>
              <button className="btn btn-sm btn-ghost" onClick={() => (setConfirmLive(false), setTyped(''))}>
                Cancel
              </button>
            </>
          }
        >
          Every scheduled run will submit real applications from your accounts, up to your daily limits, to jobs scoring at least {s.config.min_score}.
        </Alert>
      )}

      <section className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <h2 className="h2">Settings</h2>
        <div className="field">
          <span className="lbl">Run at</span>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            {draft.times.map((t) => (
              <span key={t} className="chip chip-on">
                {t}
                <button className="btn btn-ghost btn-icon btn-sm" aria-label={`Remove ${t}`} onClick={() => set({ times: draft.times.filter((x) => x !== t) })}>
                  <Icon name="x" small />
                </button>
              </span>
            ))}
            <input className="input" type="time" value={time} onChange={(e) => setTime(e.target.value)} style={{ width: 120 }} aria-label="New run time" />
            <button className="btn btn-sm" onClick={() => time && !draft.times.includes(time) && set({ times: [...draft.times, time].sort() })}>
              Add time
            </button>
          </div>
          <span className="help">Your laptop must be on with Job MCP running. A slot missed by up to 3 hours still runs.</span>
        </div>

        <div className="field">
          <span className="lbl">Platforms and daily limits</span>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            {Object.keys(draft.daily_caps).map((p) => {
              const on = draft.platforms.includes(p);
              return (
                <label key={p} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <input type="checkbox" checked={on} onChange={() => set({ platforms: on ? draft.platforms.filter((x) => x !== p) : [...draft.platforms, p] })} />
                  {platName(p)}
                  <input
                    className="input num"
                    type="number"
                    min={0}
                    max={500}
                    value={draft.daily_caps[p]}
                    onChange={(e) => set({ daily_caps: { ...draft.daily_caps, [p]: Math.max(0, Math.min(500, parseInt(e.target.value, 10) || 0)) } })}
                    style={{ width: 80 }}
                    aria-label={`${platName(p)} daily limit`}
                  />
                  <span className="help">/ day</span>
                </label>
              );
            })}
          </div>
        </div>

        <div style={{ display: 'grid', gap: 14, gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <label className="field">
            <span className="lbl">Minimum match score: {draft.min_score.toFixed(2)}</span>
            <input type="range" min={0.4} max={0.95} step={0.05} value={draft.min_score} onChange={(e) => set({ min_score: parseFloat(e.target.value) })} />
            <span className="help">0.7 keeps proper AI/ML roles where most listed skills match.</span>
          </label>
          <label className="field">
            <span className="lbl">Location</span>
            <input className="input" value={draft.location} onChange={(e) => set({ location: e.target.value })} />
          </label>
          <label className="field">
            <span className="lbl">Questions it can't answer</span>
            <label className="switch">
              <input type="checkbox" checked={draft.wait_for_me} onChange={() => set({ wait_for_me: !draft.wait_for_me })} />
              {draft.wait_for_me ? 'Wait up to 3 min for me' : "Skip and save to Answers"}
            </label>
          </label>
        </div>

        <div className="field">
          <span className="lbl">Keywords</span>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            {draft.keywords.map((k) => (
              <span key={k} className="chip chip-on">
                {k}
                <button className="btn btn-ghost btn-icon btn-sm" aria-label={`Remove ${k}`} onClick={() => set({ keywords: draft.keywords.filter((x) => x !== k) })}>
                  <Icon name="x" small />
                </button>
              </span>
            ))}
            <form
              style={{ display: 'flex', gap: 6 }}
              onSubmit={(e) => {
                e.preventDefault();
                const k = kw.trim();
                if (k && !draft.keywords.includes(k)) set({ keywords: [...draft.keywords, k] });
                setKw('');
              }}
            >
              <input className="input" value={kw} onChange={(e) => setKw(e.target.value)} placeholder="Add keyword" style={{ width: 180 }} aria-label="New keyword" />
              <button className="btn btn-sm" type="submit">
                Add
              </button>
            </form>
          </div>
        </div>

        {dirty && (
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-primary" onClick={() => save.mutate({ ...draft, live: s.config.live, enabled: s.config.enabled })} disabled={save.isPending}>
              Save settings
            </button>
            <button className="btn btn-ghost" onClick={() => setDraft(s.config)}>
              Discard
            </button>
          </div>
        )}
      </section>

      <section className="card" style={{ overflow: 'hidden' }}>
        <div className="sechead">
          <h2 className="h2">Recent runs</h2>
        </div>
        {s.runs.length === 0 ? (
          <div className="help" style={{ padding: '4px 16px 16px' }}>No runs yet.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr className="help" style={{ textAlign: 'left' }}>
                  {['Started', 'Slot', 'Mode', 'Status', 'Found', 'Picked', 'Applied', 'Failed', 'Skipped'].map((h) => (
                    <th key={h} style={{ padding: '8px 12px', fontWeight: 500 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {s.runs.map((r) => (
                  <tr key={r.id} style={{ borderTop: '1px solid var(--border)' }} title={r.message ?? undefined}>
                    <td style={{ padding: '8px 12px', whiteSpace: 'nowrap' }}>{fmtDayTime(r.started_at)}</td>
                    <td style={{ padding: '8px 12px' }}>{r.slot === 'manual' ? 'Run now' : r.slot}</td>
                    <td style={{ padding: '8px 12px' }}>{r.live ? 'Live' : 'Dry run'}</td>
                    <td style={{ padding: '8px 12px' }}>
                      <Pill tone={STATUS_TONE[r.status] ?? 'st-skipped'}>{r.status}</Pill>
                    </td>
                    {[r.searched, r.selected, r.applied, r.failed, r.skipped].map((n, i) => (
                      <td key={i} className="mono" style={{ padding: '8px 12px' }}>{n}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
