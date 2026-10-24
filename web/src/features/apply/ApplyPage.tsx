import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, errorMessage } from '../../api';
import type { ApplyPreview, Job, Platform } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Alert, cx, EmptyState, LoadingCard, Pill, PlatformBadge } from '../../components/ui';
import { joinList, LIVE_PLATFORMS, platName, plural } from '../../lib/format';
import { useBackendDown } from '../../lib/queries';
import { skipReasonText, useApply, type RunRow } from '../../state/apply';
import { useSearch } from '../../state/search';
import { useUi } from '../../state/ui';

const STEPS = ['Review', 'Confirm', 'Apply', 'Results'];
/** Matches the backend's upper bound for max_applications. */
const MAX_APPS = 1000;

export function ApplyPage() {
  const ui = useUi();
  const nav = useNavigate();
  const search = useSearch();
  const a = useApply();
  const down = useBackendDown();
  const live = ui.mode === 'live';
  const urls = a.retryUrls ?? search.selected;

  // No cap by default: the run covers every selected job unless the user lowers it.
  const userSetMax = useRef(false);
  const { step, setMaxApps } = a;
  useEffect(() => {
    if (step === 0 && !userSetMax.current) setMaxApps(Math.min(MAX_APPS, Math.max(1, urls.length)));
  }, [step, urls.length, setMaxApps]);

  const preview = useQuery({
    queryKey: ['apply-preview', urls, a.maxApps],
    queryFn: () => api.applyPreview({ apply_urls: urls, max_applications: a.maxApps }),
    enabled: urls.length > 0 && a.step < 2,
    placeholderData: (prev) => prev,
    staleTime: 0,
  });

  const back = () => nav('/search');

  return (
    <div className="page">
      <div className="pagehead">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'flex-start' }}>
          <button className="btn btn-ghost btn-sm" onClick={back} style={{ marginLeft: -8 }}>
            <Icon name="back" small />
            Back to results
          </button>
          <h1 className="h1">Bulk apply</h1>
        </div>
        <ol className="stepper" aria-label="Steps">
          {STEPS.map((l, i) => (
            <li key={l} style={{ display: 'contents' }}>
              {i > 0 && <span className="step-line" aria-hidden="true" />}
              <span className={cx('step', i === a.step && 'step-cur', i < a.step && 'step-done')} aria-current={i === a.step ? 'step' : undefined}>
                <span className="stepnum">{i < a.step ? '✓' : i + 1}</span>
                <span className="step-label">{l}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>

      {a.step === 0 && <ReviewStep urls={urls} preview={preview.data} loading={preview.isLoading} error={preview.error} live={live} down={down} onBack={back} onMaxEdit={() => { userSetMax.current = true; }} />}
      {a.step === 1 && (preview.data ? <ConfirmStep preview={preview.data} live={live} urls={urls} /> : <LoadingCard label="Checking the selected jobs…" />)}
      {a.step === 2 && <RunStep />}
      {a.step === 3 && <ResultsStep />}
    </div>
  );
}

function ReviewStep({ urls, preview, loading, error, live, down, onBack, onMaxEdit }: { urls: string[]; preview?: ApplyPreview; loading: boolean; error: unknown; live: boolean; down: boolean; onBack: () => void; onMaxEdit: () => void }) {
  const ui = useUi();
  const a = useApply();
  const search = useSearch();

  if (urls.length === 0)
    return (
      <section className="card">
        <EmptyState title="Nothing selected" action={<button className="btn btn-sm" onClick={onBack}>Back to results</button>}>
          Go back to results and select jobs with X or the checkboxes.
        </EmptyState>
      </section>
    );
  if (loading && !preview) return <LoadingCard label="Checking the selected jobs…" />;
  if (error && !preview)
    return (
      <Alert tone="danger" title="Couldn't check these jobs" role="alert">
        {errorMessage(error)} {down ? '' : 'Try again in a moment.'}
      </Alert>
    );
  if (!preview) return null;

  const items: { job: Job; will: boolean; reason: string }[] = [
    ...preview.will_apply.map((job) => ({ job, will: true, reason: '' })),
    ...preview.will_skip.map((s) => ({ job: s.job, will: false, reason: skipReasonText(s.reason, s.job, a.maxApps) })),
  ].sort((x, y) => y.job.rank_score - x.job.rank_score);
  const will = preview.will_apply;
  const skips = preview.will_skip;
  const reasons = new Map<string, number>();
  skips.forEach((s) => {
    const k = {
      already_applied: 'already applied',
      not_easy_apply: 'not Easy Apply',
      over_limit: 'over your limit',
      session_expired: 'session expired',
      excluded_company: 'excluded company',
    }[s.reason] ?? 'skipped';
    reasons.set(k, (reasons.get(k) ?? 0) + 1);
  });
  const skipWhy = `${[...reasons].map(([k, n]) => `${n} × ${k}`).join(' · ')}. They stay in your selection.`;
  const wp = LIVE_PLATFORMS.filter((p) => will.some((j) => j.platform === p));

  return (
    <div className="apply-grid">
      <section className="card" style={{ overflow: 'hidden' }}>
        <div className="sechead">
          <h2 className="h2 num">Review {items.length} selected jobs</h2>
          <span className="help num">
            {will.length} will {live ? 'apply' : 'simulate'} · {skips.length} skipped
          </span>
        </div>
        {!!preview.not_found?.length && (
          <div style={{ padding: '12px 16px 0' }}>
            <Alert tone="warn" title={`${preview.not_found.length} selected ${preview.not_found.length === 1 ? 'job is' : 'jobs are'} no longer in the last search`}>
              They can't be applied to from here. Run the search again to bring them back.
            </Alert>
          </div>
        )}
        {skips.length > 0 && (
          <div style={{ padding: '12px 16px 0' }}>
            <Alert tone="warn" title={`${skips.length} will be skipped`}>
              {skipWhy}
            </Alert>
          </div>
        )}
        <ul className="plist" style={{ marginTop: 8 }}>
          {items.map((p) => (
            <li key={p.job.apply_url} className={cx('pitem', !p.will && 'pitem-skip')}>
              <div className="c-role" style={{ minWidth: 0 }}>
                <div className="ptitle">{p.job.title}</div>
                <div className="reason">
                  {p.job.company} · {p.job.location} · {p.job.salary}
                </div>
              </div>
              <span className="c-plat">
                <PlatformBadge id={p.job.platform} />
              </span>
              <span className="c-m mono">{p.job.match_score.toFixed(2)}</span>
              <span style={{ minWidth: 0 }}>
                <span className={cx('pill', p.will ? 'st-will' : 'st-skipped')} style={{ maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis' }} title={p.reason}>
                  {p.will ? (live ? 'Will apply' : 'Will simulate') : `Skip · ${p.reason.split('.')[0]}`}
                </span>
              </span>
              <button className="btn btn-ghost btn-sm btn-icon c-x" onClick={() => search.toggle(p.job.apply_url)} aria-label={`Remove ${p.job.title} from selection`}>
                <Icon name="x" small />
              </button>
            </li>
          ))}
        </ul>
      </section>
      <aside className="card side" aria-label="Run settings">
        <h2 className="h2">Run settings</h2>
        <label className="field">
          <span className="lbl">Max applications in this run</span>
          <input
            className="input num"
            type="number"
            min={1}
            max={MAX_APPS}
            value={a.maxApps}
            onChange={(e) => {
              const n = parseInt(e.target.value, 10);
              onMaxEdit();
              a.setMaxApps(isNaN(n) ? 1 : Math.max(1, Math.min(MAX_APPS, n)));
            }}
            style={{ maxWidth: 120 }}
          />
          <span className="help">Defaults to every selected job. Lower it to stop after that many submissions.</span>
        </label>
        <div className="field">
          <span className="lbl">Mode</span>
          <label className="switch">
            <input type="checkbox" checked={!live} onChange={() => ui.setMode(live ? 'dry' : 'live')} />
            Dry run (simulation)
          </label>
          <span className="help">{live ? 'Live: applications are really submitted.' : 'Fills each form and stops before Submit. Nothing reaches employers.'}</span>
        </div>
        <div className="summary num">
          <span>Will {live ? 'apply' : 'simulate'}</span>
          <strong>{will.length}</strong>
          <span>Will skip</span>
          <strong>{skips.length}</strong>
          <span>Platforms</span>
          <strong style={{ textAlign: 'right' }}>{wp.map(platName).join(', ') || '—'}</strong>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => {
            a.setConfirmText('');
            a.setStep(1);
          }}
          disabled={will.length === 0 || down}
        >
          Continue to confirm
        </button>
      </aside>
    </div>
  );
}

function ConfirmStep({ preview, live, urls }: { preview: ApplyPreview; live: boolean; urls: string[] }) {
  const a = useApply();
  const down = useBackendDown();
  const will = preview.will_apply;
  const wp = LIVE_PLATFORMS.filter((p) => will.some((j) => j.platform === p));
  const ok = will.length > 0 && !down && (!live || a.confirmText.trim() === 'APPLY');
  const go = () => {
    if (!ok) return;
    if (a.retryUrls) void a.startRetry(urls, live);
    else void a.start({ preview, live, urls });
  };
  return (
    <section className={cx('card confirm', live && 'confirm-live')} aria-labelledby="confirm-h">
      <span className={cx('modechip', live ? 'modechip-live' : 'modechip-dry')} style={{ alignSelf: 'flex-start', cursor: 'default' }}>
        <span className="mdot" />
        {live ? 'Live · real applications' : 'Dry run · Simulation'}
      </span>
      <h2 className="confirm-h num" id="confirm-h">
        {live ? 'Apply to ' : 'Simulate applying to '}
        {plural(will.length, 'job')} on {joinList(wp.map(platName))}
        {a.retryUrls ? ' (retry)' : ''}
      </h2>
      <p className="muted" style={{ margin: 0 }}>
        {live
          ? 'Each application is submitted from your logged-in account with your saved profile and resume, one at a time.'
          : 'Job MCP walks through every form exactly as in Live mode and stops before Submit. Results are logged as dry runs in the tracker.'}
      </p>
      <div className="chips">
        {wp.map((p: Platform) => (
          <span className="tag" key={p}>
            <PlatformBadge id={p} />
            <span className="num" style={{ fontWeight: 600 }}>
              {will.filter((j) => j.platform === p).length}
            </span>
          </span>
        ))}
        <span className="tag num">{preview.will_skip.length} skipped</span>
      </div>
      {live && (
        <>
          <Alert tone="live" title="These go to real employers">
            Each one uses your saved profile and resume, and can't be withdrawn from Job MCP.
          </Alert>
          <label className="field">
            <span className="lbl">Type APPLY to confirm</span>
            <input
              className="input confirm-input"
              value={a.confirmText}
              onChange={(e) => a.setConfirmText(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === 'Enter' && go()}
              placeholder="APPLY"
              autoComplete="off"
              spellCheck={false}
              autoFocus
              aria-describedby="confirm-h"
            />
          </label>
        </>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button className="btn btn-lg" onClick={() => a.setStep(a.retryUrls ? 3 : 0)}>
          Back
        </button>
        <button className={cx('btn btn-lg', live ? 'btn-live' : 'btn-primary')} onClick={go} disabled={!ok}>
          {live ? `Apply for real · ${plural(will.length, 'job')}` : `Start simulation · ${plural(will.length, 'job')}`}
        </button>
      </div>
    </section>
  );
}

const SP: Record<RunRow['state'], [string, string]> = {
  queued: ['st-queued', 'Queued'],
  applying: ['st-applying', 'Applying'],
  applied: ['st-applied', 'Applied'],
  dry_run: ['st-dry', 'Simulated'],
  failed: ['st-failed', 'Failed'],
  skipped: ['st-skipped', 'Skipped'],
};

function RunStep() {
  const a = useApply();
  const r = a.run;
  if (!r) return <LoadingCard />;
  const rows = r.order.map((u) => r.rows[u]);
  const okSt = r.live ? 'applied' : 'dry_run';
  const nOk = rows.filter((x) => x.state === okSt).length;
  const nFail = rows.filter((x) => x.state === 'failed').length;
  const total = r.progress.total;
  const doneN = Math.min(r.progress.done, total);
  const pctNum = total ? Math.round((doneN / total) * 100) : r.done ? 100 : 0;
  const title = !r.done ? (r.stopping ? 'Stopping after the current job…' : r.live ? 'Applying… (live)' : 'Simulating…') : r.stopped ? 'Stopped' : r.error ? 'Run ended with an error' : 'Finished';
  return (
    <>
      {r.error && (
        <Alert tone="danger" title={r.error.code === 'confirm_required' ? 'The server asked for confirmation' : 'The run stopped early'} role="alert">
          {errorMessage(r.error)}
        </Alert>
      )}
      <section className="card" style={{ overflow: 'hidden' }}>
        <div className="sechead" style={{ borderBottom: 0 }}>
          <div>
            <div className="h2" style={{ display: 'flex', gap: 8, alignItems: 'center' }} aria-live="polite">
              {!r.done && <span className="spin" style={{ color: 'var(--info)' }} aria-hidden="true" />}
              {title}
            </div>
            <div className="help num">
              {doneN} of {total} processed · {nOk} {r.live ? 'applied' : 'simulated'} · {nFail} failed{r.retry ? ' · retry pass' : ''}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {!r.done && (
              <button className="btn btn-danger" onClick={() => void a.stop()} disabled={r.stopping || !r.taskId}>
                <Icon name="stop" small />
                {r.stopping ? 'Stopping…' : 'Stop'}
              </button>
            )}
            {r.done && (
              <button className="btn btn-primary" onClick={() => a.setStep(3)} autoFocus>
                See results
              </button>
            )}
          </div>
        </div>
        <div className="bigbar" role="progressbar" aria-label="Run progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pctNum}>
          <span style={{ width: `${pctNum}%`, background: r.live ? 'var(--live)' : 'var(--accent)' }} />
        </div>
        <ul className="plist" style={{ borderTop: '1px solid var(--border)' }}>
          {rows.map((x) => (
            <li key={x.url} className={cx('ritem', x.state === 'applying' && 'ritem-active')}>
              <div className="c-role" style={{ minWidth: 0 }}>
                <div className="ptitle">{x.title}</div>
                <div className={cx('reason', x.state === 'failed' && 'reason-bad')}>
                  {x.company} · {x.reason}
                </div>
              </div>
              <span className="c-plat">
                <PlatformBadge id={x.platform} />
              </span>
              <span>
                <Pill tone={SP[x.state][0]} spin={x.state === 'applying'}>
                  {SP[x.state][1]}
                  {x.state === 'applying' && !r.live ? ' (sim)' : ''}
                </Pill>
              </span>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

function ResultsStep() {
  const a = useApply();
  const ui = useUi();
  const nav = useNavigate();
  const r = a.run;
  if (!r) return null;
  const rows = r.order.map((u) => r.rows[u]);
  const okSt = r.live ? 'applied' : 'dry_run';
  const ok = rows.filter((x) => x.state === okSt);
  const fail = rows.filter((x) => x.state === 'failed');
  const skip = rows.filter((x) => x.state === 'skipped');
  const retryable = fail.filter((x) => !x.permanent).map((x) => x.url);
  const okWord = r.live ? 'Applied' : 'Simulated';

  const retry = () => {
    if (!retryable.length) return;
    // Live retries go back through Confirm and need APPLY typed again.
    if (r.live || ui.mode === 'live') {
      if (ui.mode !== 'live') ui.setMode('live');
      a.prepareRetry(retryable);
    } else void a.startRetry(retryable, false);
  };

  const Item = ({ x }: { x: RunRow }) => (
    <li className="ritem">
      <div className="c-role" style={{ minWidth: 0 }}>
        <div className="ptitle">
          {x.title} <span className="muted" style={{ fontWeight: 400 }}>· {x.company}</span>
        </div>
        <div className={cx('reason', x.state === 'failed' && 'reason-bad')}>
          {x.reason}
          {x.state === 'failed' && x.permanent ? ' Retrying won’t help.' : ''}
        </div>
      </div>
      <span className="c-plat">
        <PlatformBadge id={x.platform} />
      </span>
      <span>
        <span className={`pill ${SP[x.state][0]}`}>{SP[x.state][1]}</span>
      </span>
    </li>
  );

  return (
    <>
      <div className="kpis">
        <div className="card kpi">
          <span className="eyebrow">{okWord}</span>
          <span className="kpi-v num kpi-ok">{ok.length}</span>
          <span className="help">{r.live ? 'Submitted to employers' : 'Forms filled, nothing sent'}</span>
        </div>
        <div className="card kpi">
          <span className="eyebrow">Failed</span>
          <span className="kpi-v num kpi-bad">{fail.length}</span>
          <span className="help">Reasons below. Retry or apply on the site.</span>
        </div>
        <div className="card kpi">
          <span className="eyebrow">Skipped</span>
          <span className="kpi-v num">{skip.length}</span>
          <span className="help">Already applied, external, stopped or over limit</span>
        </div>
      </div>
      <section className="card" style={{ overflow: 'hidden' }}>
        <div className="sechead">
          <h2 className="h2 num">Failed · {fail.length}</h2>
          <button className="btn btn-sm" onClick={retry} disabled={retryable.length === 0} title={fail.length && !retryable.length ? 'These failures need you to apply on the site' : undefined}>
            <Icon name="retry" small />
            Retry failed{retryable.length && retryable.length !== fail.length ? ` (${retryable.length})` : ''}
          </button>
        </div>
        <ul className="plist">
          {fail.map((x) => (
            <Item x={x} key={x.url} />
          ))}
        </ul>
        {fail.length === 0 && (
          <div className="help" style={{ padding: '12px 16px' }}>
            No failures.
          </div>
        )}
      </section>
      <section className="card" style={{ overflow: 'hidden' }}>
        <div className="sechead">
          <h2 className="h2 num">
            {okWord} · {ok.length}
          </h2>
        </div>
        <ul className="plist">
          {ok.map((x) => (
            <Item x={x} key={x.url} />
          ))}
        </ul>
      </section>
      {skip.length > 0 && (
        <section className="card" style={{ overflow: 'hidden' }}>
          <div className="sechead">
            <h2 className="h2 num">Skipped · {skip.length}</h2>
          </div>
          <ul className="plist">
            {skip.map((x) => (
              <Item x={x} key={x.url} />
            ))}
          </ul>
        </section>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button className="btn btn-primary" onClick={() => nav('/applications?range=d7')}>
          View in tracker
        </button>
        <button className="btn" onClick={() => nav('/search')}>
          Back to results
        </button>
      </div>
    </>
  );
}
