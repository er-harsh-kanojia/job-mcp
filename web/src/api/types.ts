// Types from docs/api-contract.md (v1). Keep in sync with the contract, not with the backend code.

export type Platform = 'naukri' | 'instahyre' | 'hirist';
/** Any platform id GET /api/platforms may return, including planned ones (linkedin, wellfound, indeed). */
export type PlatformId = Platform | 'linkedin' | 'wellfound' | 'indeed' | (string & {});

export type Job = {
  platform: Platform;
  job_id: string;
  title: string;
  company: string;
  location: string;
  salary: string;
  apply_url: string;
  description: string;
  skills: string[];
  exp_min: number;
  exp_max: number;
  posted_days_ago: number;
  match_score: number;
  rank_score: number;
  easy_apply: boolean;
  already_applied: boolean;
};

export type AppStatus = 'applied' | 'failed' | 'skipped' | 'dry_run';

export type Application = {
  id: number;
  platform: Platform;
  job_id: string;
  title: string;
  company: string;
  location: string;
  apply_url: string;
  status: AppStatus;
  error: string | null;
  applied_at: string;
};

export type ApiErrorBody = { error: { code: string; message: string; detail?: Record<string, unknown> } };

// Health and platforms
export type AiProvider = 'anthropic' | 'openai' | 'local';
export type Health = {
  ok: true;
  version: string;
  mcp_tools: number;
  ai: { configured: boolean; provider: AiProvider; provider_name: string; model: string | null };
};
export type AiProviderInfo = { id: AiProvider; name: string; short: string; configured: boolean; model: string };
export type AiSettings = { provider: AiProvider; providers: AiProviderInfo[] };
export type SessionState = 'logged_in' | 'expired' | 'not_set_up' | 'unknown';
export type PlatformInfo = {
  id: PlatformId;
  name: string;
  live: boolean;
  session: SessionState;
  last_checked: string | null;
  /** Backend addition: why a check could not run (session is then "unknown"). */
  error?: string;
};
export type LoginState = 'waiting_for_user' | 'captcha' | 'logged_in' | 'timeout';

// Tasks
export type TaskRef = { task_id: string };
export type TaskSnapshot = {
  id: string;
  kind: string;
  status: 'running' | 'done' | 'error' | 'cancelled';
  result?: unknown;
  error?: unknown;
  /** For apply: { dry_run, requested } so the UI can re-attach after a reload. */
  meta?: { dry_run?: boolean; requested?: number };
  progress?: { done: number; total: number };
};

// Search
export type SearchParams = {
  keywords: string[];
  location: string;
  experience_years: number;
  platforms: Platform[];
  min_match_score: number;
  /** Maximum jobs to return; null means no overall cap. */
  max_jobs: number | null;
  exclude_companies?: string[];
};
export type PlatformRunState = 'queued' | 'fetching' | 'done' | 'failed' | 'skipped';
export type PlatformFailReason = 'captcha_required' | 'session_expired' | 'timeout' | 'error';
export type SearchPlatformEvent = {
  platform: Platform;
  state: PlatformRunState;
  count?: number;
  reason?: PlatformFailReason;
  message?: string;
};
export type SearchJobsEvent = { platform: Platform; jobs: Job[] };
export type SearchDoneEvent = { total: number; shown: number; jobs: Job[] };
export type LastSearch = {
  params: SearchParams;
  finished_at: string;
  /** Backend addition. */
  total?: number;
  platforms: SearchPlatformEvent[];
  jobs: Job[];
} | null;

// Apply
export type ApplyRequest = { apply_urls: string[]; max_applications: number; dry_run: boolean; confirm?: 'APPLY' };
export type SkipReason = 'already_applied' | 'not_easy_apply' | 'over_limit' | 'session_expired' | 'excluded_company';
export type ApplyPreview = { will_apply: Job[]; will_skip: { job: Job; reason: SkipReason }[]; /** Backend addition: URLs not in the search cache. */ not_found?: string[] };
export type ApplyJobState = 'queued' | 'applying' | 'applied' | 'dry_run' | 'failed' | 'skipped';
export type ApplyJobEvent = {
  apply_url: string;
  title: string;
  company: string;
  platform: Platform;
  state: ApplyJobState;
  error?: string;
  permanent?: boolean;
};
export type ApplyProgressEvent = { done: number; total: number };
export type ApplySummary = {
  dry_run: boolean;
  attempted: number;
  applied: number;
  would_apply: number;
  failed: number;
  skipped: number;
  already_applied: number;
  by_platform: Record<string, unknown>;
  /** Backend additions. */
  requested?: number;
  considered?: number;
  cancelled?: boolean;
};
export type ApplyDoneEvent = { summary: ApplySummary; applied: unknown[]; failed: unknown[]; skipped: unknown[] };

// Tracker
export type ApplicationsQuery = { days?: number; status?: AppStatus[]; platform?: Platform };
export type PlatformCounts = { applied: number; failed: number; skipped: number; dry_run: number };
export type Stats = {
  applied_today: number;
  applied_week: number;
  success_rate: number;
  by_platform: Record<string, PlatformCounts>;
  recent: Application[];
  /** Backend addition: the window by_platform covers (30). */
  window_days?: number;
};

// Profile
export type ResumeFile = { filename: string; size_bytes: number; uploaded_at: string };
export type Autofill = {
  current_ctc: string;
  expected_ctc: string;
  total_experience: string;
  notice_period: string;
  gender: string;
  highest_qualification: string;
  graduation_year: string;
  primary_cloud: string;
  contract_based: string;
  offer_in_hand: string;
  last_working_day: string;
  experience: Record<string, string>;
  preferred_locations: string[];
  [extra: string]: unknown;
};
export type Profile = {
  name: string;
  email: string;
  phone: string;
  location: string;
  experience_years: number;
  excluded_companies?: string[];
  resume: ResumeFile | null;
  autofill: Autofill;
};
export type ProfileUpdate = Partial<Omit<Profile, 'resume' | 'autofill'>> & { autofill?: Partial<Autofill> };

// Resume review and prep
export type Severity = 'mistake' | 'change' | 'polish';
export type ScoreKey = 'accuracy' | 'ats' | 'fit' | 'impact';
export type IssueStatus = 'open' | 'fixed' | 'dismissed';
export type Issue = {
  id: string;
  severity: Severity;
  title: string;
  where: string;
  why: string;
  before: string;
  after: string;
  note: string;
  gain: Partial<Record<ScoreKey, number>>;
  line_ids: string[];
  status: IssueStatus;
};
export type ResumeLine = { id: string; text: string; kind: 'name' | 'role' | 'text' | 'bullet' };
export type ResumeSection = { title: string; lines: ResumeLine[] };
export type DemandRow = { skill: string; jobs: number; you: 'strong' | 'some' | 'gap' };
export type PlanItem = {
  id: string;
  week: 1 | 2;
  text: string;
  type: 'Resume' | 'Learn' | 'Build' | 'Practice';
  time: string;
  hours: number;
  done: boolean;
};
export type Round = 'llm' | 'design' | 'fund' | 'code' | 'behav';
export type Question = {
  id: string;
  round: Round;
  q: string;
  why: string;
  outline: string[];
  from_resume: string;
  practised: boolean;
};
export type Prep = {
  matched_jobs: number;
  demand: DemandRow[];
  plan: PlanItem[];
  questions: Question[];
  /** Backend additions: whether demand was counted from cached jobs or estimated per 100 postings. */
  demand_source?: 'jobs' | 'estimate';
  demand_scale?: number;
  note?: string;
};
export type ReviewSummary = {
  review_id: number;
  target_role: string;
  analysed_at: string;
  overall: number;
  projected: number;
  resume_filename?: string;
  /** The report this one was compared with, if any. */
  compared_to?: number | null;
};
export type PrevOutcome = 'resolved' | 'partly' | 'still_open' | 'not_applicable';
/** How this review compares with an earlier report (scores are as analysed, before any "fixed" marks). */
export type Comparison = {
  previous_review_id: number;
  previous_analysed_at: string;
  previous_filename: string;
  previous_role: string;
  identical_resume: boolean;
  scores_before: Record<ScoreKey, number>;
  scores_after: Record<ScoreKey, number>;
  overall_before: number;
  overall_after: number;
  summary: string;
  changes: string[];
  previous: { title: string; severity: Severity; previous_status: IssueStatus; outcome: PrevOutcome; evidence: string }[];
  new_issue_ids: string[];
};
export type ReportFormat = 'pdf' | 'md';
export type Review = {
  id?: number;
  analysed_at: string;
  resume_filename: string;
  target_role: string;
  model: string;
  provider?: AiProvider;
  scores: Record<ScoreKey, number>;
  overall: number;
  projected: number;
  issues: Issue[];
  sections: ResumeSection[];
  prep: Prep | null;
  comparison?: Comparison;
};
export type AnalyseStepEvent = { index: number; label: string; state: 'running' | 'done' };
export type IssuePatchResult = { overall: number; projected: number; issue: Issue };

// Mock interview
export type ChatMessage = { role: 'assistant' | 'user'; content: string };
export type Feedback = { score: number; strengths: string[]; improve: string[] };
export type InterviewSession = { session_id: string; messages: ChatMessage[] };
export type InterviewDone = { message: ChatMessage; feedback?: Feedback };
export type InterviewSessionState = {
  session_id: string;
  question_id: string;
  messages: ChatMessage[];
  feedback: Feedback | null;
};

// Task event maps, used to type the SSE subscriptions.
export type TaskEvents = {
  search: { platform: SearchPlatformEvent; jobs: SearchJobsEvent; done: SearchDoneEvent };
  apply: { job: ApplyJobEvent; progress: ApplyProgressEvent; done: ApplyDoneEvent };
  // The contract says done {platform}; the backend sends {platform: id, status, platform_info}. Both are handled.
  login: { status: { state: LoginState; message?: string }; done: { platform: PlatformInfo | string; status?: string; platform_info?: PlatformInfo } };
  analyse: { step: AnalyseStepEvent; done: { review: Review } };
};
