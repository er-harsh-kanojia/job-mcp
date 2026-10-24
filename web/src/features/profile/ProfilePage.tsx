import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { api, errorMessage, isApiError } from '../../api';
import type { Profile } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Alert, cx, LoadingCard } from '../../components/ui';
import { fileKind, fmtBytes, fmtDayTime, fmtShortDate, hhmm, skillLabel } from '../../lib/format';
import { qk, useBackendDown, useProfile } from '../../lib/queries';
import { AiProviderPicker } from './AiProviderPicker';

const LOCS = ['Delhi NCR', 'Gurugram', 'Noida', 'Hyderabad', 'Jaipur', 'Remote', 'Pune', 'Bengaluru', 'Mumbai'];
const NOTICE = ['Immediate', '15 days', '30 days', '60 days', '90 days'];
const QUALS = ['B.Tech, Computer Science', 'B.E., Electronics', 'M.Tech, AI and ML', 'M.Sc, Data Science', 'MCA'];
const CLOUDS = ['AWS', 'GCP', 'Azure'];
const GENDERS = [
  ['male', 'Male'],
  ['female', 'Female'],
  ['other', 'Other'],
  ['prefer_not', 'Prefer not to say'],
];

type Form = {
  name: string;
  email: string;
  phone: string;
  location: string;
  experience_years: string;
  current_ctc: string;
  expected_ctc: string;
  notice_period: string;
  highest_qualification: string;
  graduation_year: string;
  primary_cloud: string;
  total_experience: string;
  gender: string;
  contract_based: string;
  offer_in_hand: string;
  last_working_day: string;
  skills: Record<string, string>;
  locs: string[];
  excluded_companies: string[];
};
type Field = Exclude<keyof Form, 'skills' | 'locs' | 'excluded_companies'>;

function toForm(p: Profile): Form {
  const a = p.autofill;
  return {
    name: p.name ?? '',
    email: p.email ?? '',
    phone: p.phone ?? '',
    location: p.location ?? '',
    experience_years: String(p.experience_years ?? ''),
    current_ctc: a.current_ctc ?? '',
    expected_ctc: a.expected_ctc ?? '',
    notice_period: a.notice_period ?? '',
    highest_qualification: a.highest_qualification ?? '',
    graduation_year: a.graduation_year ?? '',
    primary_cloud: a.primary_cloud ?? '',
    total_experience: a.total_experience ?? '',
    gender: a.gender ?? '',
    contract_based: a.contract_based ?? '',
    offer_in_hand: a.offer_in_hand ?? '',
    last_working_day: a.last_working_day ?? '',
    skills: { ...(a.experience ?? {}) },
    locs: [...(a.preferred_locations ?? [])],
    excluded_companies: [...(p.excluded_companies ?? [])],
  };
}

function validate(f: Form): Record<string, string> {
  const e: Record<string, string> = {};
  const year = new Date().getFullYear();
  if (!f.name.trim()) e.name = 'Enter your full name';
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(f.email)) e.email = 'Enter a valid email address, like name@example.com';
  if (!/^[6-9]\d{9}$/.test(f.phone.replace(/[\s-]/g, '').replace(/^\+?91/, ''))) e.phone = 'Use a 10-digit Indian mobile number';
  if (f.experience_years === '' || isNaN(+f.experience_years) || +f.experience_years < 0 || +f.experience_years > 50) e.experience_years = 'Enter years of experience, like 4';
  if (f.current_ctc === '' || isNaN(+f.current_ctc)) e.current_ctc = 'Enter a number in LPA, like 18';
  if (f.expected_ctc === '' || isNaN(+f.expected_ctc)) e.expected_ctc = 'Enter a number in LPA, like 28';
  const g = +f.graduation_year;
  if (!(g >= 1970 && g <= year + 1)) e.graduation_year = `Year must be between 1970 and ${year + 1}`;
  Object.entries(f.skills).forEach(([k, v]) => {
    if (v !== '' && (isNaN(+v) || +v < 0 || +v > 40)) e[`skills.${k}`] = 'Years, 0 to 40';
  });
  return e;
}

/** Map server 422 detail keys ("autofill.expected_ctc", "experience.python", "email") to form keys. */
function mapServerErrors(detail: Record<string, unknown> | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  Object.entries(detail ?? {}).forEach(([k, v]) => {
    let key = k.replace(/^autofill\./, '');
    if (key === 'preferred_locations') key = 'locs';
    key = key.replace(/^experience\./, 'skills.');
    out[key] = typeof v === 'string' ? v : 'Check this field';
  });
  return out;
}

export function ProfilePage() {
  const q = useProfile();
  const down = useBackendDown();
  const qc = useQueryClient();
  const nav = useNavigate();
  const loc = useLocation();
  const [form, setForm] = useState<Form | null>(null);
  const [saved, setSaved] = useState<Form | null>(null);
  const [serverErr, setServerErr] = useState<Record<string, string>>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [newSkill, setNewSkill] = useState('');
  const [newLoc, setNewLoc] = useState('');
  const [newExclude, setNewExclude] = useState('');
  const [uploadErr, setUploadErr] = useState<string | null>(null);
  const aiRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (q.data && !form) {
      const f = toForm(q.data);
      setForm(f);
      setSaved(f);
    }
  }, [q.data, form]);

  useEffect(() => {
    if (loc.hash === '#ai-provider' && form) aiRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [loc.hash, form]);

  const errs = useMemo(() => (form ? { ...validate(form), ...serverErr } : {}), [form, serverErr]);
  const dirty = !!form && !!saved && JSON.stringify(form) !== JSON.stringify(saved);

  // Warn before leaving the page with unsaved changes.
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', h);
    return () => window.removeEventListener('beforeunload', h);
  }, [dirty]);

  const addExclude = () => {
    if (!form) return;
    const t = newExclude.trim();
    if (t && !form.excluded_companies.some((x) => x.toLowerCase() === t.toLowerCase())) {
      setForm({ ...form, excluded_companies: [...form.excluded_companies, t] });
    }
    setNewExclude('');
  };

  const save = useMutation({
    mutationFn: (f: Form) =>
      api.updateProfile({
        name: f.name.trim(),
        email: f.email.trim(),
        phone: f.phone.trim(),
        location: f.location.trim(),
        experience_years: Number(f.experience_years),
        excluded_companies: f.excluded_companies,
        autofill: {
          ...(q.data?.autofill ?? {}),
          current_ctc: f.current_ctc,
          expected_ctc: f.expected_ctc,
          notice_period: f.notice_period,
          highest_qualification: f.highest_qualification,
          graduation_year: f.graduation_year,
          primary_cloud: f.primary_cloud,
          total_experience: f.total_experience,
          gender: f.gender,
          contract_based: f.contract_based,
          offer_in_hand: f.offer_in_hand,
          last_working_day: f.last_working_day,
          experience: Object.fromEntries(Object.entries(f.skills).filter(([, v]) => v !== '')),
          preferred_locations: f.locs,
        },
      }),
    onSuccess: (p) => {
      qc.setQueryData(qk.profile, p);
      const f = toForm(p);
      setForm(f);
      setSaved(f);
      setServerErr({});
      setSaveError(null);
      setSavedAt(new Date().toISOString());
    },
    onError: (e) => {
      if (isApiError(e) && e.status === 422) {
        setServerErr(mapServerErrors(e.detail));
        setSaveError(null);
      } else setSaveError(errorMessage(e));
    },
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadResume(file),
    onSuccess: (resume) => {
      setUploadErr(null);
      qc.setQueryData<Profile>(qk.profile, (p) => (p ? { ...p, resume } : p));
      void qc.invalidateQueries({ queryKey: ['review'] });
    },
    onError: (e) => setUploadErr(errorMessage(e)),
  });

  if (q.isLoading || (!form && !q.error))
    return (
      <div className="page">
        <LoadingCard label="Loading your profile…" />
      </div>
    );
  if (!form)
    return (
      <div className="page">
        <Alert tone="danger" title="Couldn't load your profile" actions={<button className="btn btn-sm" onClick={() => void q.refetch()}>Retry</button>}>
          {errorMessage(q.error)}
        </Alert>
      </div>
    );

  const set = (k: Field, v: string) => {
    setForm({ ...form, [k]: v });
    if (serverErr[k]) {
      const n = { ...serverErr };
      delete n[k];
      setServerErr(n);
    }
  };
  const errN = Object.keys(errs).length;
  const ctcWarn = !errs.current_ctc && !errs.expected_ctc && +form.expected_ctc < +form.current_ctc;
  const resume = q.data?.resume ?? null;

  const input = (k: Field, label: string, props: React.InputHTMLAttributes<HTMLInputElement> = {}, extra?: ReactNode) => (
    <label className="field">
      <span className="lbl">{label}</span>
      <input
        className={cx('input', errs[k] && 'input-err')}
        value={form[k]}
        onChange={(e) => set(k, e.target.value)}
        aria-invalid={!!errs[k]}
        aria-describedby={errs[k] ? `err-${k}` : undefined}
        {...props}
      />
      {errs[k] && (
        <span className="err" id={`err-${k}`}>
          {errs[k]}
        </span>
      )}
      {extra}
    </label>
  );
  const select = (k: Field, label: string, options: (string | string[])[]) => {
    const opts = options.map((o) => (Array.isArray(o) ? o : [o, o]));
    if (form[k] && !opts.some(([v]) => v === form[k])) opts.unshift([form[k], form[k]]);
    return (
      <label className="field">
        <span className="lbl">{label}</span>
        <select className={cx('input', errs[k] && 'input-err')} value={form[k]} onChange={(e) => set(k, e.target.value)}>
          {!form[k] && <option value="">Choose…</option>}
          {opts.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        {errs[k] && <span className="err">{errs[k]}</span>}
      </label>
    );
  };

  const allLocs = [...LOCS, ...form.locs.filter((l) => !LOCS.includes(l))];
  const addSkill = () => {
    const k = newSkill.trim();
    if (k && !(k in form.skills)) setForm({ ...form, skills: { ...form.skills, [k]: '1' } });
    setNewSkill('');
  };
  const addLoc = () => {
    const l = newLoc.trim();
    if (l && !form.locs.includes(l)) setForm({ ...form, locs: [...form.locs, l] });
    setNewLoc('');
  };

  const saveMsg = errN
    ? `${errN} ${errN > 1 ? 'fields need' : 'field needs'} attention before saving`
    : dirty
      ? 'Unsaved changes'
      : savedAt
        ? `All changes saved · ${hhmm(new Date(savedAt))}`
        : 'All changes saved';

  return (
    <div className="page">
      <div className="pagehead">
        <div>
          <h1 className="h1">Profile and autofill</h1>
          <p className="sub">Used to rank jobs and to fill application forms.</p>
        </div>
      </div>
      <Alert
        tone="info"
        icon="lock"
        title="No passwords here"
        actions={
          <button className="btn btn-sm" onClick={() => nav('/platforms')}>
            Go to Platforms
          </button>
        }
      >
        Logins happen manually in your browser from the Platforms page. Job MCP only reuses the saved session.
      </Alert>
      {saveError && (
        <Alert tone="danger" title="Couldn't save your profile" role="alert">
          {saveError}
        </Alert>
      )}
      <form
        className="card"
        onSubmit={(e) => {
          e.preventDefault();
          if (!errN && dirty) save.mutate(form);
        }}
        noValidate
      >
        <div className="psec">
          <div className="psec-h">
            <h2 className="h2">Personal</h2>
            <p>Sent with every application.</p>
          </div>
          <div className="pfields">
            {input('name', 'Full name', { autoComplete: 'name' })}
            {input('email', 'Email', { type: 'email', autoComplete: 'email' })}
            {input('phone', 'Phone', { type: 'tel', autoComplete: 'tel' })}
            {input('location', 'Current location')}
            {input('experience_years', 'Experience (years)', { inputMode: 'decimal', className: cx('input num', errs.experience_years && 'input-err') })}
            <div className="field" style={{ gridColumn: '1 / -1' }}>
              <span className="lbl">Resume</span>
              <div className="filebox">
                <Icon name="file" />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis' }}>{resume?.filename ?? 'No resume uploaded'}</div>
                  <div className="help">
                    {upload.isPending
                      ? 'Uploading…'
                      : resume
                        ? `${fileKind(resume.filename)} · ${fmtBytes(resume.size_bytes)} · uploaded ${fmtShortDate(resume.uploaded_at)}`
                        : 'PDF or Word, up to 5 MB'}
                  </div>
                </div>
                <button type="button" className="btn btn-sm" onClick={() => nav('/resume')} disabled={!resume}>
                  Review resume
                </button>
                <label className={cx('btn btn-sm', (down || upload.isPending) && 'opacity-45 pointer-events-none')}>
                  {resume ? 'Replace' : 'Upload'}
                  <input
                    className="sr-only"
                    type="file"
                    accept=".pdf,.doc,.docx"
                    disabled={down || upload.isPending}
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      e.target.value = '';
                      if (!f) return;
                      if (!/\.(pdf|docx?)$/i.test(f.name)) return setUploadErr('Use a PDF or Word file (.pdf, .doc, .docx).');
                      if (f.size > 5 * 1024 * 1024) return setUploadErr('That file is larger than 5 MB.');
                      upload.mutate(f);
                    }}
                  />
                </label>
              </div>
              {uploadErr && <span className="err">{uploadErr}</span>}
            </div>
          </div>
        </div>

        <div className="psec">
          <div className="psec-h">
            <h2 className="h2">Compensation and notice</h2>
            <p>In lakhs per annum (LPA).</p>
          </div>
          <div className="pfields">
            {input('current_ctc', 'Current CTC (LPA)', { inputMode: 'decimal' })}
            {input('expected_ctc', 'Expected CTC (LPA)', { inputMode: 'decimal' }, ctcWarn ? <span className="warnmsg">Expected is lower than current. Is that intended?</span> : null)}
            {select('notice_period', 'Notice period', NOTICE)}
          </div>
        </div>

        <div className="psec">
          <div className="psec-h">
            <h2 className="h2">Education and cloud</h2>
          </div>
          <div className="pfields">
            {select('highest_qualification', 'Highest qualification', QUALS)}
            {input('graduation_year', 'Graduation year', { inputMode: 'numeric' })}
            {select('primary_cloud', 'Primary cloud', CLOUDS)}
          </div>
        </div>

        <div className="psec">
          <div className="psec-h">
            <h2 className="h2">Other application answers</h2>
            <p>Common screening questions, answered once.</p>
          </div>
          <div className="pfields">
            {input('total_experience', 'Total experience (years)', { inputMode: 'decimal' })}
            {select('gender', 'Gender', GENDERS)}
            {select('contract_based', 'Open to contract roles', ['Yes', 'No'])}
            {select('offer_in_hand', 'Offer in hand', ['Yes', 'No'])}
            {input('last_working_day', 'Last working day')}
          </div>
        </div>

        <div className="psec">
          <div className="psec-h">
            <h2 className="h2">Skills</h2>
            <p>Years of hands-on experience. Feeds the match score.</p>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div className="skillgrid">
              {Object.entries(form.skills).map(([k, v]) => (
                <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <label className="skillcell" style={errs[`skills.${k}`] ? { borderColor: 'var(--danger)' } : undefined}>
                    <span className="sk" title={k}>
                      {skillLabel(k)}
                    </span>
                    <input
                      className="input input-sm num"
                      type="number"
                      min={0}
                      max={40}
                      step={0.5}
                      value={v}
                      onChange={(e) => setForm({ ...form, skills: { ...form.skills, [k]: e.target.value } })}
                      aria-label={`Years of ${skillLabel(k)}`}
                      aria-invalid={!!errs[`skills.${k}`]}
                    />
                    <span className="help">yrs</span>
                    <button
                      type="button"
                      className="chip-x"
                      style={{ marginRight: 0 }}
                      onClick={() => {
                        const n = { ...form.skills };
                        delete n[k];
                        setForm({ ...form, skills: n });
                      }}
                      aria-label={`Remove ${skillLabel(k)}`}
                    >
                      <Icon name="x" small />
                    </button>
                  </label>
                  {errs[`skills.${k}`] && <span className="err">{errs[`skills.${k}`]}</span>}
                </div>
              ))}
            </div>
            <div>
              <input
                className="chip-input"
                value={newSkill}
                onChange={(e) => setNewSkill(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    addSkill();
                  }
                }}
                placeholder="Add skill, Enter"
                aria-label="Add skill"
              />
            </div>
          </div>
        </div>

        <div className="psec">
          <div className="psec-h">
            <h2 className="h2">Preferred locations</h2>
            <p>Jobs elsewhere rank lower.</p>
          </div>
          <div className="chips" role="group" aria-label="Preferred locations">
            {allLocs.map((l) => {
              const on = form.locs.includes(l);
              return (
                <button type="button" key={l} className={cx('chip', on && 'chip-on')} aria-pressed={on} onClick={() => setForm({ ...form, locs: on ? form.locs.filter((x) => x !== l) : [...form.locs, l] })}>
                  {l}
                </button>
              );
            })}
            <input
              className="chip-input"
              value={newLoc}
              onChange={(e) => setNewLoc(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addLoc();
                }
              }}
              placeholder="Add location, Enter"
              aria-label="Add location"
            />
            {errs.locs && <span className="err">{errs.locs}</span>}
          </div>
        </div>

        <div className="psec">
          <div className="psec-h">
            <h2 className="h2">Excluded companies</h2>
            <p>Companies you do not want to see in search results or apply to.</p>
          </div>
          <div className="chips" role="group" aria-label="Excluded companies">
            {form.excluded_companies.map((c) => (
              <span key={c} className="chip chip-on" style={{ borderColor: 'var(--border-subtle, #fca5a5)' }}>
                {c}
                <button
                  type="button"
                  className="chip-x"
                  onClick={() => setForm({ ...form, excluded_companies: form.excluded_companies.filter((x) => x !== c) })}
                  aria-label={`Remove excluded company ${c}`}
                >
                  <Icon name="x" small />
                </button>
              </span>
            ))}
            <input
              className="chip-input"
              value={newExclude}
              onChange={(e) => setNewExclude(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  addExclude();
                }
              }}
              placeholder="Add company to exclude, Enter (e.g. TCS)"
              aria-label="Add company to exclude"
            />
          </div>
        </div>
        <button type="submit" hidden />
      </form>

      <section className="card" id="ai-provider" ref={aiRef} aria-labelledby="ai-h" style={{ scrollMarginTop: 72 }}>
        <div className="psec">
          <div className="psec-h">
            <h2 className="h2" id="ai-h">
              AI provider
            </h2>
            <p>Used for resume review, the prep plan and mock interviews. Saved as soon as you pick one.</p>
          </div>
          <AiProviderPicker />
        </div>
      </section>

      <div className="savebar" role="region" aria-label="Save changes">
        <span className={cx('sdot', errN ? 'sdot-expired' : dirty ? 'sdot-warn' : 'sdot-ok')} />
        <span className="num" style={{ fontWeight: 500 }} aria-live="polite">
          {save.isPending ? 'Saving…' : saveMsg}
        </span>
        {!dirty && !errN && q.dataUpdatedAt > 0 && !savedAt && <span className="help hide-sm">Loaded {fmtDayTime(new Date(q.dataUpdatedAt).toISOString())}</span>}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button
            className="btn btn-ghost"
            onClick={() => {
              setForm(saved);
              setServerErr({});
            }}
            disabled={!dirty || save.isPending}
          >
            Discard
          </button>
          <button className="btn btn-primary" onClick={() => save.mutate(form)} disabled={errN > 0 || !dirty || save.isPending || down}>
            Save profile
          </button>
        </div>
      </div>
    </div>
  );
}
