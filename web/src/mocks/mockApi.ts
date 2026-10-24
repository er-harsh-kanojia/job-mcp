// In-memory implementation of the Api interface for `npm run dev:mock`. Never bundled in production.
//
// URL flags (read once on load), handy for previewing states:
//   ?mock_ai=claude|openai|none   which AI providers have a key (default: both)
//   ?mock_down=1                  backend unreachable
//   ?mock_empty=1                 first run: no sessions, no applications, no resume review
//   ?mock_captcha=1               Indeed answers searches with captcha_required
//   ?mock_expired=1               Instahyre session expired
import type { Api, TaskEvent, TaskKind } from '../api/client';
import { ApiError } from '../api/errors';
import type {
  AiProvider,
  AiSettings,
  Application,
  ApplyJobEvent,
  ApplyPreview,
  ChatMessage,
  Comparison,
  Feedback,
  Job,
  LastSearch,
  Platform,
  PlatformInfo,
  Profile,
  Review,
  ScoreKey,
  SearchParams,
  SearchPlatformEvent,
  SkipReason,
} from '../api/types';
import { baseScores, COUNTS, DEMAND, FAILS, localIso, makeApps, makeIssues, makeJobs, makePlan, makeProfile, makeQuestions, makeSections } from './data';

const NAMES: Record<string, string> = { naukri: 'Naukri', instahyre: 'Instahyre', hirist: 'Hirist', linkedin: 'LinkedIn', wellfound: 'Wellfound', indeed: 'Indeed' };
const LIVE: Platform[] = ['naukri', 'instahyre', 'hirist'];
const SOON = ['linkedin', 'wellfound', 'indeed'];

function flags() {
  const q = new URLSearchParams(location.search);
  const stored = (() => {
    try {
      return JSON.parse(sessionStorage.getItem('jobmcp.mockflags') || '{}') as Record<string, string>;
    } catch {
      return {};
    }
  })();
  const get = (k: string) => q.get(k) ?? stored[k] ?? null;
  const f = {
    ai: get('mock_ai') ?? 'both',
    down: get('mock_down') === '1',
    empty: get('mock_empty') === '1',
    captcha: get('mock_captcha') === '1',
    expired: get('mock_expired') === '1',
  };
  try {
    const keep: Record<string, string> = {};
    ['mock_ai', 'mock_down', 'mock_empty', 'mock_captcha', 'mock_expired'].forEach((k) => {
      const v = get(k);
      if (v !== null) keep[k] = v;
    });
    sessionStorage.setItem('jobmcp.mockflags', JSON.stringify(keep));
  } catch {
    // ignore
  }
  return f;
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

type Listener = (e: { type: string; data: unknown }) => void;
class MockTask {
  events: { type: string; data: unknown }[] = [];
  listeners = new Set<Listener>();
  status: 'running' | 'done' | 'error' | 'cancelled' = 'running';
  cancelled = false;
  result: unknown;
  constructor(
    public id: string,
    public kind: TaskKind,
  ) {}
  emit(type: string, data: unknown) {
    if (this.status !== 'running') return;
    this.events.push({ type, data });
    if (type === 'done') {
      this.status = this.cancelled ? 'cancelled' : 'done';
      this.result = data;
    }
    if (type === 'error') this.status = 'error';
    this.listeners.forEach((l) => l({ type, data }));
  }
}

export function createMockApi(): Api {
  const F = flags();
  console.info('[Job MCP] Mock API active', F);

  const ai: Record<AiProvider, boolean> = { anthropic: F.ai === 'both' || F.ai === 'claude', openai: F.ai === 'both' || F.ai === 'openai', local: F.ai === 'local' };
  let provider: AiProvider = ai.anthropic ? 'anthropic' : ai.openai ? 'openai' : 'anthropic';
  const aiShort = () => (provider === 'openai' ? 'ChatGPT' : 'Claude');
  const MODELS: Record<AiProvider, string> = { anthropic: 'claude (mock)', openai: 'gpt (mock)', local: 'openai/gpt-oss-20b (mock)' };

  const minsAgo = (m: number) => localIso(new Date(Date.now() - m * 60000));
  const sessions: Record<string, PlatformInfo> = {};
  LIVE.forEach((id) => {
    let s: PlatformInfo['session'] = 'logged_in';
    if (F.empty) s = 'not_set_up';
    if (F.expired && id === 'instahyre') s = 'expired';
    sessions[id] = { id, name: NAMES[id], live: true, session: s, last_checked: s === 'not_set_up' ? null : minsAgo(12) };
  });
  SOON.forEach((id) => (sessions[id] = { id, name: NAMES[id], live: false, session: 'not_set_up', last_checked: null }));

  const jobs = makeJobs();
  const apps: Application[] = F.empty ? [] : makeApps();
  let profile: Profile = makeProfile();
  let lastSearch: LastSearch = F.empty
    ? null
    : {
        params: { keywords: ['AI/ML Engineer', 'ML Engineer', 'AI Engineer', 'Python AI Engineer', 'AI Cloud Engineer', 'GenAI Engineer', 'LLM Engineer', 'Deep Learning Engineer'], location: 'India', experience_years: 4, platforms: [...LIVE], min_match_score: 0.25, max_jobs: 50 },
        finished_at: minsAgo(35),
        total: COUNTS.naukri + COUNTS.instahyre + COUNTS.hirist,
        platforms: LIVE.map((p) => ({ platform: p, state: 'done' as const, count: COUNTS[p] })),
        jobs: makeJobs().filter((j) => j.match_score >= 0.25).sort((a, b) => b.rank_score - a.rank_score),
      };
  const reviews: Record<string, Review | null> = {};
  const retried = new Set<string>();
  const tasks = new Map<string, MockTask>();
  const interviews = new Map<string, { question_id: string; role: string; messages: ChatMessage[]; feedback: Feedback | null; turns: number }>();
  let seq = 1;

  const net = async <T,>(fn: () => T | Promise<T>, ms = 140): Promise<T> => {
    await wait(ms + Math.random() * 80);
    if (F.down) throw new ApiError(0, 'unreachable', "Can't reach the Job MCP server.");
    return clone(await fn());
  };
  const aiGuard = () => {
    if (!ai[provider]) {
      const key = provider === 'openai' ? 'OPENAI_API_KEY' : 'ANTHROPIC_API_KEY';
      throw new ApiError(503, 'ai_not_configured', `${key} is not set. Add it to .env and restart the server.`);
    }
  };
  const newTask = (kind: TaskKind) => {
    const t = new MockTask(`t${seq++}`, kind);
    tasks.set(t.id, t);
    return t;
  };

  // ---------- review model ----------
  const recompute = (r: Review) => {
    const calc = (withOpen: boolean) => {
      const sc: Record<ScoreKey, number> = { ...r.scores };
      r.issues.forEach((it) => {
        if (it.status === 'fixed' || (withOpen && it.status === 'open'))
          (Object.keys(it.gain) as ScoreKey[]).forEach((k) => (sc[k] = Math.min(100, sc[k] + (it.gain[k] ?? 0))));
      });
      return Math.round((sc.accuracy + sc.impact + sc.fit + sc.ats) / 4);
    };
    r.overall = calc(false);
    r.projected = calc(true);
  };
  const buildReview = (role: string, minutesAgo = 0): Review => {
    const rd = DEMAND[role] ?? DEMAND['GenAI Engineer'];
    const r: Review = {
      analysed_at: minutesAgo ? minsAgo(minutesAgo) : localIso(),
      resume_filename: profile.resume?.filename ?? 'resume.pdf',
      target_role: role,
      id: seq++,
      model: MODELS[provider],
      provider,
      scores: baseScores(role),
      overall: 0,
      projected: 0,
      issues: makeIssues(role),
      sections: makeSections(),
      prep:
        role === 'LLM Engineer'
          ? {
              // Few cached jobs for this role: the backend estimates demand per 100 typical postings.
              matched_jobs: 3,
              demand_source: 'estimate',
              demand_scale: 100,
              note: 'Only 3 matching LLM Engineer jobs were cached, so demand is estimated per 100 typical postings.',
              demand: rd.rows.map(([skill, n, you]) => ({ skill, jobs: Math.round((n / rd.jobs) * 100), you })),
              plan: makePlan(role, aiShort()),
              questions: makeQuestions(role),
            }
          : {
              matched_jobs: rd.jobs,
              demand_source: 'jobs',
              demand_scale: rd.jobs,
              note: `Counted from ${rd.jobs} ${role} jobs in your cached search results.`,
              demand: rd.rows.map(([skill, n, you]) => ({ skill, jobs: n, you })),
              plan: makePlan(role, aiShort()),
              questions: makeQuestions(role),
            },
    };
    recompute(r);
    return r;
  };
  if (!F.empty) {
    const now = new Date();
    const m = Math.max(5, now.getHours() * 60 + now.getMinutes() - (9 * 60 + 40));
    reviews['GenAI Engineer'] = buildReview('GenAI Engineer', m);
    reviews['GenAI Engineer'].id = 1;
  }
  // Every report ever made, newest first (the Reports tab and comparisons read this).
  const history: Review[] = Object.values(reviews).filter((r): r is Review => !!r).map((r) => clone(r));
  const mockComparison = (prev: Review, next: Review): Comparison => ({
    previous_review_id: prev.id ?? 0,
    previous_analysed_at: prev.analysed_at,
    previous_filename: prev.resume_filename,
    previous_role: prev.target_role,
    identical_resume: false,
    scores_before: prev.scores,
    scores_after: { ...next.scores, impact: Math.min(100, next.scores.impact + 9), accuracy: Math.min(100, next.scores.accuracy + 6) },
    overall_before: Math.round((prev.scores.accuracy + prev.scores.ats + prev.scores.fit + prev.scores.impact) / 4),
    overall_after: Math.round((next.scores.accuracy + 6 + next.scores.ats + next.scores.fit + next.scores.impact + 9) / 4),
    summary: 'The summary now names your role and stack, and two bullets show results. The date overlap is still there.',
    changes: ['Rewrote the summary around GenAI and RAG', 'Fixed the phone number in the header', 'Added F1 numbers to the fine-tuning bullet'],
    previous: prev.issues.slice(0, 6).map((i, ix) => ({
      title: i.title,
      severity: i.severity,
      previous_status: i.status,
      outcome: (['resolved', 'resolved', 'partly', 'still_open', 'still_open', 'not_applicable'] as const)[ix],
      evidence: ix < 2 ? 'Fixed in the new version.' : ix === 2 ? 'Improved, but no numbers yet.' : 'Unchanged.',
    })),
    new_issue_ids: next.issues.slice(-1).map((i) => i.id),
  });
  const findIssue = (id: string) => {
    for (const r of Object.values(reviews)) {
      const it = r?.issues.find((i) => i.id === id);
      if (r && it) return { r, it };
    }
    throw new ApiError(404, 'not_found', 'Issue not found');
  };

  // ---------- tracker ----------
  const record = (j: Job, status: Application['status'], error: string | null) => {
    apps.unshift({ id: 1000 + seq++, platform: j.platform, job_id: j.job_id, title: j.title, company: j.company, location: j.location, apply_url: j.apply_url, status, error, applied_at: localIso() });
  };
  const daysBack = (iso: string) => {
    const d = new Date(iso);
    const a = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const n = new Date();
    return Math.round((new Date(n.getFullYear(), n.getMonth(), n.getDate()).getTime() - a) / 86400000);
  };

  // ---------- search ----------
  const runSearch = async (t: MockTask, body: SearchParams) => {
    const order = LIVE.filter((p) => body.platforms.includes(p));
    order.forEach((p) => t.emit('platform', { platform: p, state: 'queued' } satisfies SearchPlatformEvent));
    const events: SearchPlatformEvent[] = [];
    const found: Job[] = [];
    let total = 0;
    for (const p of order) {
      if (t.cancelled) break;
      if (sessions[p].session !== 'logged_in') {
        const ev: SearchPlatformEvent = { platform: p, state: 'skipped', reason: 'session_expired', message: `${NAMES[p]} session ${sessions[p].session === 'expired' ? 'expired' : 'is not set up'}` };
        if (sessions[p].session === 'not_set_up') ev.message = `${NAMES[p]} is not set up`;
        events.push(ev);
        t.emit('platform', ev);
        continue;
      }
      t.emit('platform', { platform: p, state: 'fetching' });
      await wait(1100);
      if (p === 'hirist' && F.captcha) {
        const ev: SearchPlatformEvent = { platform: p, state: 'failed', reason: 'captcha_required', count: 0, message: 'Hirist showed a captcha' };
        events.push(ev);
        t.emit('platform', ev);
        continue;
      }
      const pj = jobs.filter((j) => j.platform === p);
      found.push(...pj);
      total += COUNTS[p];
      const ev: SearchPlatformEvent = { platform: p, state: 'done', count: COUNTS[p] };
      events.push(ev);
      t.emit('platform', ev);
      t.emit('jobs', { platform: p, jobs: pj });
    }
    const exList = (body.exclude_companies ?? []).map((x) => x.trim().toLowerCase()).filter(Boolean);
    const isExcluded = (comp: string) => {
      const c = comp.toLowerCase();
      return exList.some((ex) => c === ex || c.includes(ex));
    };
    const ranked = found
      .filter((j) => j.match_score >= body.min_match_score - 1e-9 && !isExcluded(j.company))
      .sort((a, b) => b.rank_score - a.rank_score);
    const final = body.max_jobs === null ? ranked : ranked.slice(0, body.max_jobs ?? 50);
    total = final.length;
    lastSearch = { params: body, finished_at: localIso(), total, platforms: events, jobs: final };
    t.emit('done', { total, shown: final.length, jobs: final });
  };

  // ---------- apply ----------
  const plan = (urls: string[], max: number) => {
    const sel = jobs.filter((j) => urls.includes(j.apply_url)).sort((a, b) => b.rank_score - a.rank_score);
    const will: Job[] = [];
    const skip: { job: Job; reason: SkipReason }[] = [];
    sel.forEach((j) => {
      if (j.already_applied) return skip.push({ job: j, reason: 'already_applied' });
      if (!j.easy_apply) return skip.push({ job: j, reason: 'not_easy_apply' });
      if ((profile.excluded_companies ?? []).some((ex) => j.company.toLowerCase().includes(ex.toLowerCase()))) {
        return skip.push({ job: j, reason: 'excluded_company' });
      }
      if (sessions[j.platform].session !== 'logged_in') return skip.push({ job: j, reason: 'session_expired' });
      if (will.length >= max) return skip.push({ job: j, reason: 'over_limit' });
      will.push(j);
    });
    return { will_apply: will, will_skip: skip } satisfies ApplyPreview;
  };
  const SKIP_TEXT: Record<SkipReason, string> = {
    already_applied: 'Already applied',
    not_easy_apply: 'Not Easy Apply',
    over_limit: 'Over the limit for this run',
    session_expired: 'Session expired',
    excluded_company: 'Excluded company',
  };

  const runApply = async (t: MockTask, urls: string[], max: number, dry: boolean) => {
    const p = plan(urls, max);
    const ev = (j: Job, state: ApplyJobEvent['state'], extra: Partial<ApplyJobEvent> = {}) =>
      t.emit('job', { apply_url: j.apply_url, title: j.title, company: j.company, platform: j.platform, state, ...extra } satisfies ApplyJobEvent);
    p.will_skip.forEach((s) => {
      ev(s.job, 'skipped', { error: SKIP_TEXT[s.reason] });
      record(s.job, 'skipped', SKIP_TEXT[s.reason]);
    });
    p.will_apply.forEach((j) => ev(j, 'queued'));
    const total = p.will_apply.length;
    t.emit('progress', { done: 0, total });
    const res = { applied: [] as Job[], failed: [] as Job[], skipped: p.will_skip.map((s) => s.job) };
    let done = 0;
    for (const j of p.will_apply) {
      if (t.cancelled) {
        ev(j, 'skipped', { error: 'cancelled' });
        res.skipped.push(j);
        continue;
      }
      ev(j, 'applying');
      await wait(900);
      const f = FAILS[j.job_id];
      if (f && (f.permanent || !retried.has(j.apply_url))) {
        retried.add(j.apply_url);
        ev(j, 'failed', { error: f.reason, permanent: f.permanent });
        record(j, 'failed', f.reason);
        res.failed.push(j);
      } else if (dry) {
        ev(j, 'dry_run');
        record(j, 'dry_run', null);
        res.applied.push(j);
      } else {
        ev(j, 'applied');
        record(j, 'applied', null);
        j.already_applied = true;
        res.applied.push(j);
      }
      t.emit('progress', { done: ++done, total });
    }
    t.emit('done', {
      summary: {
        dry_run: dry,
        requested: urls.length,
        considered: p.will_apply.length + p.will_skip.length,
        cancelled: t.cancelled,
        attempted: done,
        applied: dry ? 0 : res.applied.length,
        would_apply: dry ? res.applied.length : 0,
        failed: res.failed.length,
        skipped: res.skipped.length,
        already_applied: p.will_skip.filter((s) => s.reason === 'already_applied').length,
        by_platform: {},
      },
      applied: res.applied,
      failed: res.failed,
      skipped: res.skipped,
    });
  };

  // ---------- login ----------
  const runLogin = async (t: MockTask, id: string) => {
    t.emit('status', { state: 'waiting_for_user' });
    if (id === 'indeed') {
      await wait(2500);
      if (t.cancelled) return t.emit('error', new ApiError(0, 'cancelled', 'Login cancelled'));
      t.emit('status', { state: 'captcha', message: 'Indeed is showing a captcha' });
    }
    await wait(4500);
    if (t.cancelled) return t.emit('error', new ApiError(0, 'cancelled', 'Login cancelled'));
    sessions[id] = { ...sessions[id], session: 'logged_in', last_checked: localIso() };
    t.emit('status', { state: 'logged_in' });
    t.emit('done', { platform: id, status: 'logged_in', platform_info: clone(sessions[id]) });
  };

  // ---------- analysis ----------
  const runAnalyse = async (t: MockTask, role: string, compareTo?: number) => {
    const rd = DEMAND[role] ?? DEMAND['GenAI Engineer'];
    const labels = [`Reading ${profile.resume?.filename ?? 'your resume'}`, 'Checking facts against your profile', `Comparing with ${rd.jobs} matched ${role} jobs`, 'Writing suggestions and a prep plan'];
    for (let i = 0; i < 4; i++) {
      if (t.cancelled) return t.emit('error', new ApiError(0, 'cancelled', 'Analysis cancelled'));
      t.emit('step', { index: i, label: labels[i], state: 'running' });
      await wait(900);
      t.emit('step', { index: i, label: labels[i], state: 'done' });
    }
    const prev = compareTo === 0 ? null : compareTo ? history.find((h) => h.id === compareTo) ?? null : reviews[role] ?? history[0] ?? null;
    const next = buildReview(role);
    next.id = history.length + 1;
    if (prev) next.comparison = mockComparison(prev, next);
    reviews[role] = next;
    history.unshift(clone(next));
    t.emit('done', { review: clone(next) });
  };

  // ---------- interview ----------
  const reply = (turn: number, q: string): { text: string; feedback?: Feedback } => {
    if (turn === 1)
      return {
        text: 'Thanks, that’s a solid start. A follow-up: how would you know your change actually helped? Tell me what you would measure, on what data, and what result would make you roll it back.',
      };
    return {
      text: 'Good. That covers it, so let me score this answer.\n\nYou tied the answer to your own project and named concrete metrics, which is what interviewers listen for. To make it stronger, lead with the outcome in one sentence and give one number from your work.',
      feedback: {
        score: 7,
        strengths: ['Grounded the answer in your own project', 'Named concrete metrics and a fixed evaluation set', 'Clear structure: problem, approach, result'],
        improve: [`Open with the one-line outcome before the details (asked: “${q.slice(0, 48)}${q.length > 48 ? '…' : ''}”)`, 'Quote one real number from your work', 'Say what you would do differently next time'],
      },
    };
  };

  const subscribe = <K extends TaskKind>(_kind: K, taskId: string, onEvent: (e: TaskEvent<K>) => void) => {
    const t = tasks.get(taskId);
    let active = true;
    if (!t) {
      setTimeout(() => active && onEvent({ type: 'error', data: new ApiError(404, 'not_found', 'Task not found') } as TaskEvent<K>), 0);
      return () => void (active = false);
    }
    const l: Listener = (e) => {
      if (active) onEvent(clone(e.type === 'error' ? { type: 'error', data: e.data } : e) as TaskEvent<K>);
    };
    setTimeout(() => {
      if (!active) return;
      t.events.forEach((e) => l(e.type === 'error' ? { type: 'error', data: e.data } : e));
      t.listeners.add(l);
    }, 0);
    return () => {
      active = false;
      t.listeners.delete(l);
    };
  };

  const aiSettings = (): AiSettings => ({
    provider,
    providers: [
      { id: 'anthropic', name: 'Claude (Anthropic)', short: 'Claude', configured: ai.anthropic, model: MODELS.anthropic },
      { id: 'openai', name: 'ChatGPT (OpenAI)', short: 'ChatGPT', configured: ai.openai, model: MODELS.openai },
      { id: 'local', name: 'Local model (LM Studio / Ollama)', short: 'Local AI', configured: ai.local, model: MODELS.local },
    ],
  });

  return {
    health: () =>
      net(() => ({ ok: true as const, version: '0.4.0', mcp_tools: 7, ai: { configured: ai[provider], provider, provider_name: provider === 'openai' ? 'ChatGPT (OpenAI)' : 'Claude (Anthropic)', model: MODELS[provider] } })),
    platforms: () => net(() => ({ platforms: Object.values(sessions) })),
    checkPlatform: (id) =>
      net(() => {
        const p = sessions[id];
        if (!p) throw new ApiError(404, 'not_found', 'Unknown platform');
        if (p.live && p.session !== 'not_set_up') p.last_checked = localIso();
        return p;
      }, 700),
    login: (id) =>
      net(() => {
        const t = newTask('login');
        void runLogin(t, id);
        return { task_id: t.id };
      }),

    aiSettings: () => net(aiSettings),
    setAiProvider: (p) =>
      net(() => {
        if (!ai[p]) throw new ApiError(400, 'provider_not_configured', `${p === 'openai' ? 'OPENAI_API_KEY' : 'ANTHROPIC_API_KEY'} is not set.`);
        provider = p;
        return aiSettings();
      }),

    search: (body) =>
      net(() => {
        const t = newTask('search');
        void runSearch(t, body);
        return { task_id: t.id };
      }),
    lastSearch: () => net(() => lastSearch),

    applyPreview: ({ apply_urls, max_applications }) => net(() => plan(apply_urls, max_applications), 300),
    apply: ({ apply_urls, max_applications, dry_run, confirm }) =>
      net(() => {
        if (!dry_run && confirm !== 'APPLY') throw new ApiError(400, 'confirm_required', 'Live runs need confirm: "APPLY".');
        const t = newTask('apply');
        void runApply(t, apply_urls, max_applications, dry_run);
        return { task_id: t.id };
      }),

    applications: (q) =>
      net(() => ({
        applications: apps.filter(
          (a) => (!q.days || daysBack(a.applied_at) < q.days) && (!q.status?.length || q.status.includes(a.status)) && (!q.platform || a.platform === q.platform),
        ),
      })),
    stats: () =>
      net(() => {
        const week = apps.filter((a) => daysBack(a.applied_at) < 7);
        const month = apps.filter((a) => daysBack(a.applied_at) < 30);
        const ok = month.filter((a) => a.status === 'applied').length;
        const bad = month.filter((a) => a.status === 'failed').length;
        const by: Record<string, { applied: number; failed: number; skipped: number; dry_run: number }> = {};
        LIVE.forEach((p) => (by[p] = { applied: 0, failed: 0, skipped: 0, dry_run: 0 }));
        month.forEach((a) => by[a.platform][a.status]++);
        return {
          applied_today: apps.filter((a) => a.status === 'applied' && daysBack(a.applied_at) === 0).length,
          applied_week: week.filter((a) => a.status === 'applied').length,
          success_rate: ok + bad ? ok / (ok + bad) : 0,
          by_platform: by,
          recent: [...apps].sort((a, b) => b.applied_at.localeCompare(a.applied_at)).slice(0, 10),
          window_days: 30,
        };
      }),

    profile: () => net(() => profile),
    updateProfile: (body) =>
      net(() => {
        const next: Profile = { ...profile, ...body, resume: profile.resume, autofill: { ...profile.autofill, ...(body.autofill ?? {}) } };
        const detail: Record<string, string> = {};
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(next.email)) detail.email = 'Enter a valid email address, like name@example.com';
        if (Number(next.autofill.expected_ctc) > 500) detail['autofill.expected_ctc'] = 'That looks too high. Use lakhs per annum, like 28';
        if (Object.keys(detail).length) throw new ApiError(422, 'validation', 'Some fields need attention', detail);
        profile = next;
        return profile;
      }, 400),
    uploadResume: (file) =>
      net(() => {
        if (!/\.(pdf|docx?)$/i.test(file.name)) throw new ApiError(422, 'validation', 'Use a PDF or Word file', { file: 'Use a PDF or Word file' });
        if (file.size > 5 * 1024 * 1024) throw new ApiError(413, 'file_too_large', 'The file is larger than 5 MB');
        profile = { ...profile, resume: { filename: file.name, size_bytes: file.size, uploaded_at: localIso() } };
        return profile.resume!;
      }, 600),

    // Reading stored reviews works without a key; with none stored, the mock reports the setup state.
    review: (role) =>
      net(() => {
        if (!reviews[role]) aiGuard();
        return reviews[role] ?? null;
      }),
    reviews: (all) =>
      net(() => ({
        reviews: (all ? history : Object.values(reviews).filter((r): r is Review => !!r)).map((r) => ({
          review_id: r.id ?? 0,
          target_role: r.target_role,
          analysed_at: r.analysed_at,
          overall: r.overall,
          projected: r.projected,
          resume_filename: r.resume_filename,
          compared_to: r.comparison?.previous_review_id ?? null,
        })),
      })),
    reportUrl: (id, format) => {
      const r = history.find((h) => h.id === id);
      const text = r ? `# Resume report: ${r.target_role}

Score ${r.overall} / 100 (mock report)
` : 'Report not found';
      return URL.createObjectURL(new Blob([text], { type: format === 'pdf' ? 'application/pdf' : 'text/markdown' }));
    },
    analyse: (role, compareTo) =>
      net(() => {
        aiGuard();
        if (!profile.resume) throw new ApiError(400, 'resume_missing', 'Upload a resume on your Profile first.');
        const t = newTask('analyse');
        void runAnalyse(t, role, compareTo);
        return { task_id: t.id };
      }),
    patchIssue: (id, status) =>
      net(() => {
        const { r, it } = findIssue(id);
        it.status = status;
        recompute(r);
        return { overall: r.overall, projected: r.projected, issue: it };
      }),
    patchPlan: (id, done) =>
      net(() => {
        for (const r of Object.values(reviews)) {
          const it = r?.prep?.plan.find((p) => p.id === id);
          if (it) {
            it.done = done;
            return { plan_item: it };
          }
        }
        throw new ApiError(404, 'not_found', 'Plan item not found');
      }),
    patchQuestion: (id, practised) =>
      net(() => {
        let found = null;
        for (const r of Object.values(reviews)) {
          const q = r?.prep?.questions.find((x) => x.id === id);
          if (q) {
            q.practised = practised;
            found = q;
          }
        }
        if (!found) throw new ApiError(404, 'not_found', 'Question not found');
        return { question: found };
      }),

    createInterview: (question_id, role) =>
      net(() => {
        aiGuard();
        const q = reviews[role]?.prep?.questions.find((x) => x.id === question_id) ?? makeQuestions(role).find((x) => x.id === question_id);
        const id = `s${seq++}`;
        const opening = `Let’s run this like a real ${role} interview. I’ll ask, you answer as you would on the call, and I may follow up before scoring.\n\n${q?.q ?? 'Tell me about a project you’re proud of.'}`;
        interviews.set(id, { question_id, role, messages: [{ role: 'assistant', content: opening }], feedback: null, turns: 0 });
        return { session_id: id, messages: [{ role: 'assistant' as const, content: opening }] };
      }, 700),
    sendInterview: async (sessionId, content, onDelta, signal) => {
      await wait(250);
      if (F.down) throw new ApiError(0, 'unreachable', "Can't reach the Job MCP server.");
      aiGuard();
      const s = interviews.get(sessionId);
      if (!s) throw new ApiError(404, 'not_found', 'Session not found');
      if (s.feedback) throw new ApiError(409, 'interview_finished', 'This session already has feedback.');
      s.messages.push({ role: 'user', content });
      s.turns++;
      const q = reviews[s.role]?.prep?.questions.find((x) => x.id === s.question_id);
      const r = reply(s.turns, q?.q ?? '');
      const tokens = r.text.match(/\S+\s*|\s+/g) ?? [];
      let out = '';
      for (const tok of tokens) {
        if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
        await wait(28 + Math.random() * 30);
        out += tok;
        onDelta(tok);
      }
      const message: ChatMessage = { role: 'assistant', content: out };
      s.messages.push(message);
      if (r.feedback) {
        s.feedback = r.feedback;
        Object.values(reviews).forEach((rv) => rv?.prep?.questions.forEach((x) => x.id === s.question_id && (x.practised = true)));
      }
      return clone({ message, feedback: r.feedback });
    },
    getInterview: (id) =>
      net(() => {
        const s = interviews.get(id);
        if (!s) throw new ApiError(404, 'not_found', 'Session not found');
        return { session_id: id, question_id: s.question_id, role: s.role, messages: s.messages, feedback: s.feedback };
      }),

    task: (id) =>
      net(() => {
        const t = tasks.get(id);
        if (!t) throw new ApiError(404, 'not_found', 'Task not found');
        return { id, kind: t.kind, status: t.status, result: t.result };
      }),
    tasks: (kind, status) =>
      net(() => ({
        tasks: [...tasks.values()]
          .filter((t) => (!kind || t.kind === kind) && (!status || t.status === status))
          .reverse()
          .map((t) => ({ id: t.id, kind: t.kind, status: t.status })),
      })),
    cancelTask: (id) =>
      net(() => {
        const t = tasks.get(id);
        if (t) t.cancelled = true;
        return { ok: true };
      }),
    subscribe,
  };
}

