import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorMessage, isAiNotConfigured, type ApiError } from '../../api';
import type { ChatMessage, Feedback } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Alert, cx, Overlay, Spinner } from '../../components/ui';
import { useAiProvider } from '../../lib/queries';
import { useUi } from '../../state/ui';
import { AiSetupCard } from './AiSetupCard';

/** "Practise with Claude/ChatGPT": a mock-interview chat that streams the interviewer's replies. */
export function InterviewDrawer() {
  const ui = useUi();
  const target = ui.interview!;
  const aip = useAiProvider();
  const qc = useQueryClient();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [draft, setDraft] = useState('');
  const [starting, setStarting] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const abort = useRef<AbortController | null>(null);
  const chatRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Start (or restart) a session for this question.
  useEffect(() => {
    let live = true;
    setStarting(true);
    setError(null);
    setMessages([]);
    setFeedback(null);
    setSessionId(null);
    api
      .createInterview(target.questionId, target.role)
      .then((s) => {
        if (!live) return;
        setSessionId(s.session_id);
        setMessages(s.messages);
      })
      .catch((e) => live && setError(e))
      .finally(() => live && setStarting(false));
    return () => {
      live = false;
    };
  }, [target.questionId, target.role, attempt]);

  useEffect(() => () => abort.current?.abort(), []);

  useEffect(() => {
    const el = chatRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streaming, feedback]);

  useEffect(() => {
    if (!starting && sessionId && !feedback) inputRef.current?.focus();
  }, [starting, sessionId, feedback]);

  const send = useCallback(async () => {
    const content = draft.trim();
    if (!content || !sessionId || streaming !== null || feedback) return;
    setDraft('');
    setError(null);
    setMessages((m) => [...m, { role: 'user', content }]);
    setStreaming('');
    const ctl = new AbortController();
    abort.current = ctl;
    try {
      const done = await api.sendInterview(sessionId, content, (t) => setStreaming((s) => (s ?? '') + t), ctl.signal);
      setMessages((m) => [...m, done.message]);
      if (done.feedback) {
        setFeedback(done.feedback);
        void qc.invalidateQueries({ queryKey: ['review'] });
      }
    } catch (e) {
      if ((e as Error)?.name !== 'AbortError') {
        setError(e);
        if ((e as ApiError).code === 'interview_finished') void qc.invalidateQueries({ queryKey: ['review'] });
      }
    } finally {
      setStreaming(null);
      abort.current = null;
    }
  }, [draft, sessionId, streaming, feedback, qc]);

  const close = () => {
    abort.current?.abort();
    ui.closeInterview();
  };
  const busy = streaming !== null;

  return (
    <Overlay variant="right" onClose={close} scrimLabel="Close mock interview">
      <aside className="drawer drawer-wide" role="dialog" aria-modal="true" aria-labelledby="iv-title">
        <div className="dhead" style={{ padding: '10px 12px 10px 16px' }}>
          <div style={{ minWidth: 0 }}>
            <div className="eyebrow">
              {target.role}
              {target.round ? ` · ${target.round}` : ''}
            </div>
            <h2 className="h2" id="iv-title">
              Mock interview with {aip.short}
            </h2>
          </div>
          <button className="btn btn-ghost btn-icon" onClick={close} aria-label="Close">
            <Icon name="x" />
          </button>
        </div>
        <div className="chat-q">
          <div className="help">Question</div>
          <div className="qtext">{target.question}</div>
        </div>

        {isAiNotConfigured(error) ? (
          <div className="dbody">
            <AiSetupCard compact />
          </div>
        ) : (
          <div className="chat" ref={chatRef} aria-live="polite" aria-busy={busy || starting}>
            {starting && (
              <div className="msg msg-ai" style={{ display: 'flex', gap: 8, alignItems: 'center', color: 'var(--text-3)' }}>
                <Spinner style={{ color: 'var(--info)' }} />
                {aip.short} is getting the question ready…
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={cx('msg', m.role === 'user' ? 'msg-user' : 'msg-ai')}>
                <div className="msg-who">{m.role === 'user' ? 'You' : `${aip.short} · interviewer`}</div>
                {m.content}
              </div>
            ))}
            {streaming !== null && (
              <div className="msg msg-ai">
                <div className="msg-who">{aip.short} · interviewer</div>
                {streaming}
                <span className="caret" aria-hidden="true" />
              </div>
            )}
            {feedback && <FeedbackCard f={feedback} />}
            {!!error && (
              <Alert
                tone="danger"
                title={(error as ApiError).code === 'interview_finished' ? 'This session is finished' : "Couldn't get a reply"}
                role="alert"
                actions={
                  <button className="btn btn-sm" onClick={() => setAttempt((a) => a + 1)}>
                    Start a new session
                  </button>
                }
              >
                {errorMessage(error)}
              </Alert>
            )}
          </div>
        )}

        {!isAiNotConfigured(error) && (
          <div className="chat-foot">
            {feedback ? (
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                <button className="btn" onClick={() => setAttempt((a) => a + 1)}>
                  <Icon name="retry" small />
                  Practise again
                </button>
                <button className="btn btn-primary" onClick={close}>
                  Done
                </button>
              </div>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void send();
                }}
                style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
              >
                <label className="sr-only" htmlFor="iv-answer">
                  Your answer
                </label>
                <textarea
                  id="iv-answer"
                  ref={inputRef}
                  className="input"
                  rows={3}
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                  placeholder={starting ? 'Waiting for the question…' : 'Answer as you would in the interview…'}
                  disabled={starting || !sessionId}
                />
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span className="help hide-sm">
                    <span className="kbd">↵</span> send · <span className="kbd">Shift</span> <span className="kbd">↵</span> new line
                  </span>
                  <button type="submit" className="btn btn-primary" style={{ marginLeft: 'auto' }} disabled={!draft.trim() || busy || !sessionId}>
                    {busy ? <Spinner /> : <Icon name="send" small />}
                    {busy ? `${aip.short} is replying…` : 'Send answer'}
                  </button>
                </div>
              </form>
            )}
          </div>
        )}
      </aside>
    </Overlay>
  );
}

function FeedbackCard({ f }: { f: Feedback }) {
  const color = f.score >= 7 ? 'var(--success)' : f.score >= 5 ? 'var(--accent)' : 'var(--warning)';
  return (
    <section className="fbcard" aria-label="Feedback on your answer">
      <div className="fbcard-h">
        <span>
          <span className="bigscore num" style={{ color }}>
            {f.score}
          </span>
          <span className="muted"> / 10</span>
        </span>
        <div>
          <div style={{ fontWeight: 600 }}>Feedback on your answer</div>
          <div className="help">Marked as practised on the Prepare tab.</div>
        </div>
      </div>
      <div className="fbcard-b">
        <div>
          <div className="eyebrow" style={{ color: 'var(--success)' }}>
            Strengths
          </div>
          <ul>
            {f.strengths.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
        <div>
          <div className="eyebrow" style={{ color: 'var(--warning)' }}>
            To improve
          </div>
          <ul>
            {f.improve.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
