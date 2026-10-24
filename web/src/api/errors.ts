import type { ApiErrorBody } from './types';

/** Error thrown by the API client. status 0 means the server could not be reached at all. */
export class ApiError extends Error {
  status: number;
  code: string;
  detail?: Record<string, unknown>;
  constructor(status: number, code: string, message: string, detail?: Record<string, unknown>) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** Network failure, or the dev proxy answering for a server that is down. */
export function isUnreachable(e: unknown): boolean {
  return isApiError(e) && (e.status === 0 || e.code === 'unreachable');
}

export function isAiNotConfigured(e: unknown): boolean {
  return isApiError(e) && e.status === 503 && e.code === 'ai_not_configured';
}

/** Normalise an `{error: {...}}` envelope or a bare `{code, message}` object (used by SSE `error` events). */
export function errorFromPayload(status: number, payload: unknown): ApiError {
  const p = payload as Partial<ApiErrorBody> & { code?: string; message?: string; detail?: Record<string, unknown> };
  const inner = p && typeof p === 'object' && p.error && typeof p.error === 'object' ? p.error : p;
  const code = (inner && typeof inner.code === 'string' && inner.code) || (status ? `http_${status}` : 'error');
  const message = (inner && typeof inner.message === 'string' && inner.message) || 'Something went wrong.';
  return new ApiError(status, code, message, inner?.detail);
}

export async function errorFromResponse(res: Response): Promise<ApiError> {
  let payload: unknown = null;
  try {
    payload = await res.json();
  } catch {
    // Vite's dev proxy answers 500/502/504 with plain text when the backend is not running.
    if (res.status >= 500) return new ApiError(0, 'unreachable', "Can't reach the Job MCP server.");
  }
  return errorFromPayload(res.status, payload);
}

const FRIENDLY: Record<string, string> = {
  unreachable: "Can't reach the Job MCP server. Make sure it's running, then try again.",
  confirm_required: 'Live runs need you to type APPLY to confirm.',
  jobs_not_found: 'These jobs are no longer in the last search. Run the search again, then select them.',
  platform_not_live: 'That platform is not available yet.',
  provider_not_configured: 'That AI provider has no API key. Add it to D:\\Job-MCP\\.env and restart.',
  ai_rate_limited: 'The AI provider is rate-limiting requests. Wait a minute, then try again.',
  ai_refused: 'The AI provider declined this request. Try rephrasing, or try again later.',
  ai_auth: 'The AI provider rejected the API key. Check the key in D:\\Job-MCP\\.env and restart.',
  ai_model: "The configured AI model isn't available. Check the model setting and restart.",
  ai_unavailable: 'The AI provider is having problems. Try again in a few minutes.',
  ai_unreachable: "Can't reach the AI provider. Check your internet connection.",
  ai_invalid_output: 'The AI answer could not be read. Try again.',
  ai_bad_request: 'The AI provider rejected the request. Try again.',
  resume_missing: 'There is no resume on your profile. Upload one first.',
  resume_legacy_doc: 'Old .doc files can’t be read. Save it as .docx or PDF and upload again.',
  resume_empty: 'Your resume file has no readable text. Upload a text-based PDF or .docx.',
  resume_unreadable: 'Your resume file could not be read. Try exporting it again as PDF.',
  resume_type: 'Use a PDF or Word (.docx) resume.',
  file_too_large: 'That file is larger than 5 MB.',
  interview_finished: 'This practice session is finished. Start a new one to practise again.',
  cancelled: 'Cancelled.',
};

export function errorMessage(e: unknown): string {
  if (isApiError(e)) return FRIENDLY[e.code] ?? e.message;
  if (e instanceof Error) return e.message;
  return 'Something went wrong.';
}
