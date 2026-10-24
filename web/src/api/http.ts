import type { Api, TaskEvent, TaskKind } from './client';
import { TASK_EVENT_TYPES } from './client';
import { ApiError, errorFromPayload, errorFromResponse } from './errors';
import { readSse, safeJson } from './sse';
import type { InterviewDone, TaskSnapshot } from './types';

const BASE = '/api';

async function request<T>(method: string, path: string, body?: unknown, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: body instanceof FormData ? { Accept: 'application/json' } : { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
      ...init,
    });
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') throw e;
    throw new ApiError(0, 'unreachable', "Can't reach the Job MCP server.");
  }
  if (!res.ok) throw await errorFromResponse(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : null) as T;
}

const enc = encodeURIComponent;

function subscribe<K extends TaskKind>(kind: K, taskId: string, onEvent: (e: TaskEvent<K>) => void): () => void {
  let es: EventSource | null = null;
  let stopped = false;
  let retries = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const emit = (e: TaskEvent<K>) => {
    if (!stopped) onEvent(e);
  };
  const finish = () => {
    stopped = true;
    es?.close();
    if (timer) clearTimeout(timer);
  };
  const fail = (err: ApiError) => {
    emit({ type: 'error', data: err });
    finish();
  };

  // The stream dropped before `done`/`error`: ask for the task snapshot and either replay its result or reconnect.
  const recover = async () => {
    if (stopped) return;
    let snap: TaskSnapshot;
    try {
      snap = await request<TaskSnapshot>('GET', `/tasks/${enc(taskId)}`);
    } catch (e) {
      if (++retries > 15) return fail(e instanceof ApiError ? e : new ApiError(0, 'unreachable', 'Lost the connection to this task.'));
      timer = setTimeout(recover, 2000);
      return;
    }
    if (stopped) return;
    if (snap.status === 'running') {
      if (++retries > 15) return fail(new ApiError(0, 'stream_lost', 'Lost the progress stream for this task.'));
      timer = setTimeout(open, Math.min(5, retries) * 700);
    } else if ((snap.status === 'done' || snap.status === 'cancelled') && snap.result !== undefined && snap.result !== null) {
      emit({ type: 'done', data: snap.result } as TaskEvent<K>);
      finish();
    } else if (snap.status === 'cancelled') {
      fail(new ApiError(0, 'cancelled', 'The task was cancelled.'));
    } else {
      fail(errorFromPayload(500, snap.error ?? { message: 'The task failed.' }));
    }
  };

  const open = () => {
    if (stopped) return;
    es = new EventSource(`${BASE}/tasks/${enc(taskId)}/events`);
    for (const type of TASK_EVENT_TYPES[kind]) {
      es.addEventListener(type, (ev) => {
        retries = 0;
        emit({ type, data: safeJson((ev as MessageEvent<string>).data) } as TaskEvent<K>);
        if (type === 'done') finish();
      });
    }
    // `error` is both the server's error event (a MessageEvent with data) and EventSource's own connection error.
    es.addEventListener('error', (ev) => {
      const data = (ev as MessageEvent<string>).data;
      if (typeof data === 'string' && data.length) {
        fail(errorFromPayload(500, safeJson(data)));
        return;
      }
      // EventSource reconnects by itself and resends Last-Event-ID, so the backend resumes after the last event.
      if (es && es.readyState === EventSource.CONNECTING && ++retries <= 8) return;
      es?.close();
      void recover();
    });
  };

  open();
  return finish;
}

async function sendInterview(sessionId: string, content: string, onDelta: (t: string) => void, signal?: AbortSignal): Promise<InterviewDone> {
  let res: Response;
  try {
    res = await fetch(`${BASE}/interview/sessions/${enc(sessionId)}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ content }),
      signal,
    });
  } catch (e) {
    if ((e as Error)?.name === 'AbortError') throw e;
    throw new ApiError(0, 'unreachable', "Can't reach the Job MCP server.");
  }
  if (!res.ok) throw await errorFromResponse(res);
  if (!res.body) throw new ApiError(500, 'no_stream', 'The server did not stream a reply.');
  let final: InterviewDone | null = null;
  let failure: ApiError | null = null;
  await readSse(res.body, (m) => {
    if (m.event === 'delta') {
      const d = safeJson(m.data) as { text?: string };
      if (d && typeof d.text === 'string') onDelta(d.text);
    } else if (m.event === 'done') {
      final = safeJson(m.data) as InterviewDone;
    } else if (m.event === 'error') {
      failure = errorFromPayload(500, safeJson(m.data));
    }
  });
  if (failure) throw failure;
  if (!final) throw new ApiError(500, 'stream_incomplete', 'The reply ended before it finished.');
  return final;
}

export function createHttpApi(): Api {
  return {
    health: () => request('GET', '/health'),
    platforms: () => request('GET', '/platforms'),
    checkPlatform: (id) => request('POST', `/platforms/${enc(id)}/check`),
    login: (id) => request('POST', `/platforms/${enc(id)}/login`),

    aiSettings: () => request('GET', '/settings/ai'),
    setAiProvider: (provider) => request('PUT', '/settings/ai', { provider }),

    search: (params) => request('POST', '/search', params),
    lastSearch: () => request('GET', '/search/last'),

    applyPreview: (body) => request('POST', '/apply/preview', body),
    apply: (body) => request('POST', '/apply', body),

    applications: (q) => {
      const p = new URLSearchParams();
      if (q.days) p.set('days', String(q.days));
      if (q.status?.length) p.set('status', q.status.join(','));
      if (q.platform) p.set('platform', q.platform);
      const qs = p.toString();
      return request('GET', `/applications${qs ? `?${qs}` : ''}`);
    },
    stats: () => request('GET', '/stats'),

    profile: () => request('GET', '/profile'),
    updateProfile: (body) => request('PUT', '/profile', body),
    uploadResume: (file) => {
      const fd = new FormData();
      fd.append('file', file);
      return request('POST', '/profile/resume', fd);
    },

    review: (role) => request('GET', `/resume/review?role=${enc(role)}`),
    reviews: (all) => request('GET', `/resume/reviews${all ? '?all=true' : ''}`),
    analyse: (target_role, compare_to) =>
      request('POST', '/resume/analyse', compare_to === undefined ? { target_role } : { target_role, compare_to }),
    reportUrl: (id, format) => `${BASE}/resume/reviews/${id}/report?format=${format}`,
    patchIssue: (id, status) => request('PATCH', `/resume/issues/${enc(id)}`, { status }),
    patchPlan: (id, done) => request('PATCH', `/resume/plan/${enc(id)}`, { done }),
    patchQuestion: (id, practised) => request('PATCH', `/resume/questions/${enc(id)}`, { practised }),

    createInterview: (question_id, role) => request('POST', '/interview/sessions', { question_id, role }),
    sendInterview,
    getInterview: (id) => request('GET', `/interview/sessions/${enc(id)}`),

    task: (id) => request('GET', `/tasks/${enc(id)}`),
    cancelTask: (id) => request('POST', `/tasks/${enc(id)}/cancel`),
    tasks: (kind, status) => {
      const q = new URLSearchParams();
      if (kind) q.set('kind', kind);
      if (status) q.set('status', status);
      return request('GET', `/tasks${q.toString() ? `?${q}` : ''}`);
    },
    subscribe,
  };
}
