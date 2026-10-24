import type {
  AiProvider,
  AiSettings,
  Application,
  ApplicationsQuery,
  ApplyPreview,
  ApplyRequest,
  Health,
  InterviewDone,
  InterviewSession,
  InterviewSessionState,
  IssuePatchResult,
  IssueStatus,
  LastSearch,
  PlanItem,
  PlatformId,
  PlatformInfo,
  Profile,
  ProfileUpdate,
  Question,
  ReportFormat,
  ResumeFile,
  Review,
  ReviewSummary,
  SearchParams,
  Stats,
  TaskEvents,
  TaskRef,
  TaskSnapshot,
} from './types';
import type { ApiError } from './errors';

type EventUnion<M> = { [T in keyof M]: { type: T; data: M[T] } }[keyof M];
export type TaskKind = keyof TaskEvents;
/** Every message a task stream can deliver. `error` covers both the server's `error` event and a lost stream. */
export type TaskEvent<K extends TaskKind> = EventUnion<TaskEvents[K]> | { type: 'error'; data: ApiError };

/** Event names each task kind emits (besides `error`). */
export const TASK_EVENT_TYPES: { [K in TaskKind]: (keyof TaskEvents[K] & string)[] } = {
  search: ['platform', 'jobs', 'done'],
  apply: ['job', 'progress', 'done'],
  login: ['status', 'done'],
  analyse: ['step', 'done'],
};

/** The API surface used by the UI. Implemented over HTTP (http.ts) and in memory (mocks/mockApi.ts). */
export interface Api {
  health(): Promise<Health>;
  platforms(): Promise<{ platforms: PlatformInfo[] }>;
  checkPlatform(id: PlatformId): Promise<PlatformInfo>;
  login(id: PlatformId): Promise<TaskRef>;

  aiSettings(): Promise<AiSettings>;
  setAiProvider(provider: AiProvider): Promise<AiSettings>;

  search(params: SearchParams): Promise<TaskRef>;
  lastSearch(): Promise<LastSearch>;

  applyPreview(body: { apply_urls: string[]; max_applications: number }): Promise<ApplyPreview>;
  apply(body: ApplyRequest): Promise<TaskRef>;

  applications(q: ApplicationsQuery): Promise<{ applications: Application[] }>;
  stats(): Promise<Stats>;

  profile(): Promise<Profile>;
  updateProfile(body: ProfileUpdate): Promise<Profile>;
  uploadResume(file: File): Promise<ResumeFile>;

  review(role: string): Promise<Review | null>;
  /** Latest review per role, or every stored report (newest first) with all = true. */
  reviews(all?: boolean): Promise<{ reviews: ReviewSummary[] }>;
  /** compareTo: a previous report id; omitted = the latest previous report; 0 = don't compare. */
  analyse(targetRole: string, compareTo?: number): Promise<TaskRef>;
  /** URL that downloads a stored report as a file. */
  reportUrl(reviewId: number, format: ReportFormat): string;
  patchIssue(id: string, status: IssueStatus): Promise<IssuePatchResult>;
  patchPlan(id: string, done: boolean): Promise<{ plan_item: PlanItem }>;
  patchQuestion(id: string, practised: boolean): Promise<{ question: Question }>;

  createInterview(questionId: string, role: string): Promise<InterviewSession>;
  /** Streams the assistant reply. onDelta receives each text chunk; resolves with the final `done` payload. */
  sendInterview(sessionId: string, content: string, onDelta: (text: string) => void, signal?: AbortSignal): Promise<InterviewDone>;
  getInterview(sessionId: string): Promise<InterviewSessionState>;

  task(id: string): Promise<TaskSnapshot>;
  /** Tasks the server still holds, newest first (e.g. a bulk apply still running after a reload). */
  tasks(kind?: string, status?: TaskSnapshot['status']): Promise<{ tasks: TaskSnapshot[] }>;
  cancelTask(id: string): Promise<unknown>;
  /** Subscribe to a task's event stream. Returns an unsubscribe function. The stream ends after `done` or `error`. */
  subscribe<K extends TaskKind>(kind: K, taskId: string, onEvent: (e: TaskEvent<K>) => void): () => void;
}
