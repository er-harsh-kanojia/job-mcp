import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api, errorMessage, isAiNotConfigured } from '../../api';
import type { Profile, Review } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Alert, cx, LoadingCard, Spinner } from '../../components/ui';
import { fmtDayTime } from '../../lib/format';
import { providerSetupHint, qk, useAiProvider, useBackendDown, useProfile, useReview } from '../../lib/queries';
import { useTasks } from '../../state/tasks';
import { DEFAULT_KEYWORDS, useSearch } from '../../state/search';
import { ROLES, useUi } from '../../state/ui';
import { AiProviderPicker } from '../profile/AiProviderPicker';
import { AiSetupCard } from './AiSetupCard';
import { ComparisonCard } from './ComparisonCard';
import { PrepTab } from './PrepTab';
import { ReportsTab } from './ReportsTab';
import { ReviewTab } from './ReviewTab';

type Tab = 'review' | 'prep' | 'reports';

export const PROVIDER_SHORT: Record<string, string> = { anthropic: 'Claude', openai: 'ChatGPT', local: 'Local AI' };

export function ResumePage() {
  const ui = useUi();
  const role = ui.role;
  const [sp, setSp] = useSearchParams();
  const tabParam = sp.get('tab');
  const tab: Tab = tabParam === 'prep' || tabParam === 'reports' ? tabParam : 'review';
  const setTab = (t: Tab) => setSp(t === 'review' ? {} : { tab: t }, { replace: true });
  const history = useQuery({ queryKey: ['reviews', 'all'], queryFn: () => api.reviews(true), staleTime: 10_000 });
  // undefined = compare with the latest report (the server's default); 0 = don't compare
  const [compareTo, setCompareTo] = useState<number | undefined>(undefined);
  const review = useReview(role);
  const profile = useProfile();
  const tasks = useTasks();
  const aip = useAiProvider();
  const down = useBackendDown();
  const qc = useQueryClient();
  const [showAi, setShowAi] = useState(false);
  const [drag, setDrag] = useState(false);
  const [uploadErr, setUploadErr] = useState<string | null>(null);

  const analysing = tasks.analysis && tasks.analysis.role === role ? tasks.analysis : null;
  const busy = !!analysing && !analysing.error;
  const data: Review | null | undefined = review.data;
  // Setup card: the server said ai_not_configured, or there's nothing stored yet and the selected provider has no key
  // (reading stored reviews works without a key, so a saved review still shows with a warning instead).
  const aiMissing =
    isAiNotConfigured(review.error) || (analysing?.error && isAiNotConfigured(analysing.error)) || (data === null && !aip.configured);
  const resumeName = profile.data?.resume?.filename ?? 'your resume';

  const upload = useMutation({
    mutationFn: (f: File) => api.uploadResume(f),
    onSuccess: (resume) => {
      setUploadErr(null);
      qc.setQueryData<Profile>(qk.profile, (p) => (p ? { ...p, resume } : p));
      void tasks.startAnalysis(role, compareTo);
    },
    onError: (e) => setUploadErr(errorMessage(e)),
  });
  const pickFile = (f: File | undefined) => {
    if (!f) return;
    if (!/\.(pdf|docx?)$/i.test(f.name)) return setUploadErr('Use a PDF or Word file (.pdf, .doc, .docx).');
    if (f.size > 5 * 1024 * 1024) return setUploadErr('That file is larger than 5 MB.');
    upload.mutate(f);
  };

  const analyse = () => void tasks.startAnalysis(role, compareTo);
  const reviewer = data ? PROVIDER_SHORT[data.provider ?? ''] ?? aip.short : aip.short;
  const sub =
    data && !busy
      ? `Reviewed ${fmtDayTime(data.analysed_at).replace(/^Today/, 'today').replace(/^Yesterday/, 'yesterday')} by ${reviewer}, against your profile${data.prep ? ` and ${data.prep.matched_jobs} matched ${role} jobs` : ''}.`
      : `${aip.short} reviews your resume and helps you prepare for the roles you target.`;
  const openMistakes = data ? data.issues.filter((i) => i.severity === 'mistake' && i.status === 'open').length : 0;
  const defaultSteps = [`Reading ${resumeName}`, 'Checking facts against your profile', `Comparing with matched ${role} jobs`, 'Writing suggestions and a prep plan'];
  const runningIdx = analysing ? analysing.steps.findIndex((s) => s && s.state === 'running') : -1;

  return (
    <div className="page">
      <div className="pagehead">
        <div>
          <h1 className="h1">Resume and prep</h1>
          <p className="sub">{sub}</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setShowAi(!showAi)} aria-expanded={showAi} aria-controls="resume-ai" title="Switch AI provider">
            <span className={cx('sdot', aip.configured ? 'sdot-ok' : 'sdot-none')} />
            AI: {aip.short}
            <Icon name="chevDown" small />
          </button>
          <RoleInput role={role} onCommit={ui.setRole} />
          {(history.data?.reviews.length ?? 0) > 0 && (
            <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span className="lbl">Compare with</span>
              <select
                className="input"
                style={{ width: 'auto', maxWidth: 230 }}
                value={compareTo === undefined ? 'latest' : String(compareTo)}
                onChange={(e) => setCompareTo(e.target.value === 'latest' ? undefined : Number(e.target.value))}
              >
                <option value="latest">Latest report</option>
                {history.data!.reviews.map((r) => (
                  <option key={r.review_id} value={r.review_id}>
                    {fmtDayTime(r.analysed_at)} · {r.target_role} ({r.overall})
                  </option>
                ))}
                <option value="0">Don't compare</option>
              </select>
            </label>
          )}
          {data?.id != null && (
            <>
              <a className="btn" href={api.reportUrl(data.id, 'pdf')} download title="Download this report as a PDF">
                <Icon name="file" small />
                PDF
              </a>
              <a className="btn btn-ghost" href={api.reportUrl(data.id, 'md')} download title="Download this report as Markdown">
                Markdown
              </a>
            </>
          )}
          <button className="btn" onClick={analyse} disabled={down || busy || !!aiMissing || !aip.configured || !profile.data?.resume}>
            <Icon name="retry" small />
            {data ? 'Re-analyse' : 'Analyse'}
          </button>
          {data && (
            <label
              className={cx('btn btn-primary', (down || busy || upload.isPending || !aip.configured) && 'opacity-45 pointer-events-none')}
              title="Upload an edited resume: it's analysed and compared with your latest report"
            >
              <Icon name="upload" small />
              {upload.isPending ? 'Uploading…' : 'Upload new resume'}
              <input
                className="sr-only"
                type="file"
                accept=".pdf,.doc,.docx"
                onChange={(e) => {
                  pickFile(e.target.files?.[0]);
                  e.target.value = '';
                }}
              />
            </label>
          )}
        </div>
      </div>
      {uploadErr && data && (
        <Alert tone="danger" title="Couldn't upload that file" actions={<button className="btn btn-sm" onClick={() => setUploadErr(null)}>Dismiss</button>}>
          {uploadErr}
        </Alert>
      )}

      {showAi && (
        <section className="card" id="resume-ai" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <h2 className="h2">AI provider</h2>
            <button className="btn btn-ghost btn-sm btn-icon" onClick={() => setShowAi(false)} aria-label="Close AI provider settings">
              <Icon name="x" small />
            </button>
          </div>
          <AiProviderPicker />
        </section>
      )}

      {aiMissing ? (
        <AiSetupCard />
      ) : busy ? (
        <section className="card" style={{ padding: '18px 20px', maxWidth: 640 }} aria-live="polite">
          <div className="h2" style={{ marginBottom: 6 }}>
            {aip.short} is analysing your resume for {role} roles…
          </div>
          {defaultSteps.map((label, i) => {
            const st = analysing?.steps[i];
            const running = st?.state === 'running' || (runningIdx === -1 && i === 0 && !st);
            const done = st?.state === 'done';
            return (
              <div key={i} className={cx('anstep', running && 'anstep-on', done && 'anstep-done')}>
                {running && <Spinner style={{ color: 'var(--info)' }} />}
                {done && <Icon name="check" small style={{ color: 'var(--success)' }} />}
                {!running && !done && <span className="sdot sdot-none" />}
                <span>{st?.label ?? label}</span>
              </div>
            );
          })}
        </section>
      ) : (
        <>
          {analysing?.error && (
            <Alert
              tone="danger"
              title="The analysis didn't finish"
              role="alert"
              actions={
                <>
                  <button className="btn btn-sm" onClick={analyse}>
                    Try again
                  </button>
                  <button className="btn btn-sm btn-ghost" onClick={tasks.clearAnalysisError}>
                    Dismiss
                  </button>
                </>
              }
            >
              {errorMessage(analysing.error)}
            </Alert>
          )}
          {data && !aip.configured && !down && (
            <Alert
              tone="warn"
              icon="key"
              title={`${aip.short} isn't set up, so this is your last saved review`}
              actions={
                <button className="btn btn-sm" onClick={() => setShowAi(true)}>
                  AI provider
                </button>
              }
            >
              To re-analyse or practise interviews, {providerSetupHint(aip.id)}.
            </Alert>
          )}
          {review.isLoading && <LoadingCard label="Loading your review…" />}
          {review.error && !aiMissing && !down && (
            <Alert tone="danger" title="Couldn't load the review" actions={<button className="btn btn-sm" onClick={() => void review.refetch()}>Retry</button>}>
              {errorMessage(review.error)}
            </Alert>
          )}
          {data === null && (
            <section className="card" style={{ padding: 16 }}>
              <div
                className={cx('dropzone', drag && 'dropzone-over')}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDrag(true);
                }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDrag(false);
                  pickFile(e.dataTransfer.files?.[0]);
                }}
              >
                <span className="empty-ic">
                  <Icon name="upload" />
                </span>
                <div className="h2">Get a review of your resume</div>
                <p style={{ margin: 0, maxWidth: 520, color: 'var(--text-2)' }}>
                  {aip.short} reads your resume, flags mistakes and inconsistencies, checks it against the jobs you're matching, then builds an interview prep plan for your target role.
                </p>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
                  <button className="btn btn-primary" onClick={analyse} disabled={down || !profile.data?.resume}>
                    Analyse resume from Profile
                  </button>
                  <label className={cx('btn', (down || upload.isPending) && 'opacity-45 pointer-events-none')}>
                    {upload.isPending ? 'Uploading…' : 'Upload a different file'}
                    <input className="sr-only" type="file" accept=".pdf,.doc,.docx" onChange={(e) => {
                      pickFile(e.target.files?.[0]);
                      e.target.value = '';
                    }} />
                  </label>
                </div>
                <span className="help">
                  PDF or Word, up to 5 MB · {profile.data?.resume ? `On your profile: ${profile.data.resume.filename}` : 'No resume on your profile yet'}
                </span>
                {uploadErr && <span className="err">{uploadErr}</span>}
              </div>
            </section>
          )}
          {data && (
            <>
              <div className="tabs" role="tablist" aria-label="Resume sections">
                <button className={cx('tab', tab === 'review' && 'tab-on')} role="tab" aria-selected={tab === 'review'} onClick={() => setTab('review')}>
                  Review
                  {openMistakes > 0 && (
                    <span className="cnt num" aria-label={`${openMistakes} mistakes`}>
                      {openMistakes}
                    </span>
                  )}
                </button>
                <button className={cx('tab', tab === 'prep' && 'tab-on')} role="tab" aria-selected={tab === 'prep'} onClick={() => setTab('prep')}>
                  Prepare for {role}
                </button>
                <button className={cx('tab', tab === 'reports' && 'tab-on')} role="tab" aria-selected={tab === 'reports'} onClick={() => setTab('reports')}>
                  Reports
                  {(history.data?.reviews.length ?? 0) > 0 && <span className="cnt num">{history.data!.reviews.length}</span>}
                </button>
              </div>
              {tab === 'review' && (
                <>
                  {data.comparison && <ComparisonCard c={data.comparison} issues={data.issues} />}
                  <ReviewTab review={data} role={role} />
                </>
              )}
              {tab === 'prep' && <PrepTab review={data} role={role} />}
              {tab === 'reports' && <ReportsTab />}
            </>
          )}
        </>
      )}
    </div>
  );
}

/** Free-text target role. Suggestions come from your search keywords and roles you've analysed before. */
function RoleInput({ role, onCommit }: { role: string; onCommit: (r: string) => void }) {
  const search = useSearch();
  const reviews = useQuery({ queryKey: ['reviews'], queryFn: () => api.reviews(), staleTime: 60_000 });
  const [draft, setDraft] = useState(role);
  useEffect(() => setDraft(role), [role]);
  const suggestions = [
    ...new Set([
      ...(reviews.data?.reviews ?? []).map((r) => r.target_role),
      ...search.params.keywords,
      ...DEFAULT_KEYWORDS,
      ...ROLES,
    ]),
  ].filter((r) => r && r !== role);
  const commit = () => {
    const r = draft.trim().replace(/\s+/g, ' ');
    if (r.length >= 2 && r !== role) onCommit(r);
    else setDraft(role);
  };
  return (
    <label style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
      <span className="lbl">Target role</span>
      <input
        className="input"
        style={{ width: 220 }}
        list="target-role-suggestions"
        value={draft}
        maxLength={120}
        placeholder="Any role, e.g. Data Scientist"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
          if (e.key === 'Escape') setDraft(role);
        }}
      />
      <datalist id="target-role-suggestions">
        {suggestions.map((r) => (
          <option key={r} value={r} />
        ))}
      </datalist>
    </label>
  );
}
