import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { api, errorMessage } from '../../api';
import type { PendingQuestion, SavedAnswer } from '../../api/types';
import { Icon } from '../../components/Icon';
import { Alert, EmptyState, LoadingCard, Pill } from '../../components/ui';
import { fmtDayTime } from '../../lib/format';

export const answersKey = ['answers'] as const;

export function useAnswers() {
  return useQuery({ queryKey: answersKey, queryFn: () => api.answers(), refetchInterval: 20_000 });
}

/** Questions the bot couldn't answer, and the answers it reuses (learned from you or added here). */
export function AnswersPage() {
  const q = useAnswers();
  return (
    <div className="page">
      <div className="pagehead">
        <div>
          <h1 className="h1">Answers</h1>
          <p className="sub">Answer an application question once and the bot reuses it on every job that asks it again.</p>
        </div>
      </div>
      {q.isLoading && <LoadingCard label="Loading your answers…" />}
      {q.error && (
        <Alert tone="danger" title="Couldn't load your answers" actions={<button className="btn btn-sm" onClick={() => void q.refetch()}>Retry</button>}>
          {errorMessage(q.error)}
        </Alert>
      )}
      {q.data && (
        <>
          <PendingSection items={q.data.pending} />
          <SavedSection items={q.data.answers} />
        </>
      )}
    </div>
  );
}

function PendingSection({ items }: { items: PendingQuestion[] }) {
  const qc = useQueryClient();
  const done = () => void qc.invalidateQueries({ queryKey: answersKey });
  const answer = useMutation({ mutationFn: ({ id, text }: { id: number; text: string }) => api.answerPending(id, text), onSuccess: done });
  const dismiss = useMutation({ mutationFn: (id: number) => api.dismissPending(id), onSuccess: done });
  return (
    <section className="card" style={{ overflow: 'hidden' }}>
      <div className="sechead">
        <div>
          <h2 className="h2">
            Waiting for your answer <span className="help num">· {items.length}</span>
          </h2>
          <div className="help">The bot skipped these jobs because it didn't know the answer. Answer once; it's used automatically next time.</div>
        </div>
      </div>
      {items.length === 0 ? (
        <EmptyState icon="check" title="Nothing waiting">
          New questions appear here when a job asks something the bot doesn't know.
        </EmptyState>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {items.map((p) => (
            <PendingRow
              key={p.id}
              p={p}
              busy={(answer.isPending && answer.variables?.id === p.id) || (dismiss.isPending && dismiss.variables === p.id)}
              onAnswer={(text) => answer.mutate({ id: p.id, text })}
              onDismiss={() => dismiss.mutate(p.id)}
            />
          ))}
        </div>
      )}
      {(answer.error || dismiss.error) && <div className="err" style={{ padding: '8px 16px' }}>{errorMessage(answer.error || dismiss.error)}</div>}
    </section>
  );
}

function PendingRow({ p, busy, onAnswer, onDismiss }: { p: PendingQuestion; busy: boolean; onAnswer: (text: string) => void; onDismiss: () => void }) {
  const [text, setText] = useState('');
  const where = [p.company, p.job_title].filter(Boolean).join(' · ');
  return (
    <div style={{ padding: '12px 16px', borderTop: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 600 }}>{p.question}</span>
        {p.times_seen > 1 && <Pill tone="st-warn">asked {p.times_seen}×</Pill>}
      </div>
      <div className="help">
        {where && `${where} · `}
        {p.platform ?? ''} · last seen {fmtDayTime(p.updated_at)}
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        {p.options.map((o) => (
          <button key={o} className="btn btn-sm" disabled={busy} onClick={() => onAnswer(o)}>
            {o}
          </button>
        ))}
        <form
          style={{ display: 'flex', gap: 6, flex: '1 1 260px' }}
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) onAnswer(text.trim());
          }}
        >
          <input
            className="input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={p.options.length ? 'Or type an answer' : 'Your answer'}
            aria-label={`Answer to: ${p.question}`}
            style={{ flex: 1, minWidth: 0 }}
          />
          <button className="btn btn-sm btn-primary" type="submit" disabled={busy || !text.trim()}>
            Save
          </button>
        </form>
        <button className="btn btn-sm btn-ghost" onClick={onDismiss} disabled={busy} title="Remove without answering">
          Dismiss
        </button>
      </div>
    </div>
  );
}

function SavedSection({ items }: { items: SavedAnswer[] }) {
  const qc = useQueryClient();
  const done = () => void qc.invalidateQueries({ queryKey: answersKey });
  const add = useMutation({ mutationFn: ({ q, a }: { q: string; a: string }) => api.addAnswer(q, a), onSuccess: done });
  const [newQ, setNewQ] = useState('');
  const [newA, setNewA] = useState('');
  return (
    <section className="card" style={{ overflow: 'hidden' }}>
      <div className="sechead">
        <div>
          <h2 className="h2">
            Saved answers <span className="help num">· {items.length}</span>
          </h2>
          <div className="help">Matched by exact question (case and punctuation ignored). These win over the profile's automatic answers.</div>
        </div>
      </div>
      <form
        style={{ display: 'flex', gap: 8, padding: '12px 16px', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}
        onSubmit={(e) => {
          e.preventDefault();
          if (newQ.trim() && newA.trim())
            add.mutate({ q: newQ.trim(), a: newA.trim() }, { onSuccess: () => (setNewQ(''), setNewA('')) });
        }}
      >
        <input className="input" style={{ flex: '2 1 280px' }} placeholder="Question, exactly as the site asks it" value={newQ} onChange={(e) => setNewQ(e.target.value)} aria-label="New question" />
        <input className="input" style={{ flex: '1 1 160px' }} placeholder="Answer" value={newA} onChange={(e) => setNewA(e.target.value)} aria-label="New answer" />
        <button className="btn btn-sm" type="submit" disabled={add.isPending || !newQ.trim() || !newA.trim()}>
          Add
        </button>
        {add.error && <span className="err">{errorMessage(add.error)}</span>}
      </form>
      {items.map((a) => (
        <SavedRow key={a.id} a={a} />
      ))}
      {items.length === 0 && <div className="help" style={{ padding: '4px 16px 16px' }}>No saved answers yet.</div>}
    </section>
  );
}

function SavedRow({ a }: { a: SavedAnswer }) {
  const qc = useQueryClient();
  const done = () => void qc.invalidateQueries({ queryKey: answersKey });
  const [val, setVal] = useState(a.answer);
  const save = useMutation({ mutationFn: () => api.updateAnswer(a.id, val.trim()), onSuccess: done });
  const del = useMutation({ mutationFn: () => api.deleteAnswer(a.id), onSuccess: done });
  const dirty = val.trim() !== a.answer && val.trim() !== '';
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr) auto', gap: '6px 12px', alignItems: 'center', padding: '10px 16px', borderTop: '1px solid var(--border)' }}>
      <div style={{ minWidth: 0 }}>
        <div>{a.question}</div>
        <div className="help">
          {a.source === 'you' ? 'Learned from your answer' : 'Added here'} · used {a.uses}× · {fmtDayTime(a.updated_at)}
        </div>
      </div>
      <input className="input" value={val} onChange={(e) => setVal(e.target.value)} aria-label={`Answer to: ${a.question}`} />
      <div style={{ display: 'flex', gap: 6 }}>
        {dirty && (
          <button className="btn btn-sm btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
            Save
          </button>
        )}
        <button className="btn btn-sm btn-ghost btn-icon" onClick={() => del.mutate()} disabled={del.isPending} aria-label={`Delete answer to: ${a.question}`} title="Delete">
          <Icon name="x" small />
        </button>
      </div>
    </div>
  );
}
