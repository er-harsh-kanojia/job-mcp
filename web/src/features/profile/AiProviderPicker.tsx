import type { AiProvider } from '../../api/types';
import { errorMessage } from '../../api';
import { cx, LoadingCard } from '../../components/ui';
import { providerSetupHint, useAiSettings, useBackendDown, useSetAiProvider } from '../../lib/queries';

/**
 * Radio cards for Claude (Anthropic) / ChatGPT (OpenAI) / a local model, from GET/PUT /api/settings/ai.
 * Keys live only in .env: this never asks for or shows an API key.
 */
export function AiProviderPicker({ compact }: { compact?: boolean }) {
  const q = useAiSettings();
  const set = useSetAiProvider();
  const down = useBackendDown();
  if (q.isLoading) return <LoadingCard label="Loading AI settings…" />;
  if (!q.data) return <span className="err">{q.error ? errorMessage(q.error) : 'AI settings unavailable.'}</span>;
  const { provider, providers } = q.data;
  const missing = providers.filter((p) => !p.configured);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div role="radiogroup" aria-label="AI provider" style={{ display: 'grid', gridTemplateColumns: compact ? 'minmax(0,1fr)' : 'repeat(auto-fit, minmax(min(240px, 100%), 1fr))', gap: 10 }}>
        {providers.map((p) => {
          const on = p.id === provider;
          const pending = set.isPending && set.variables === p.id;
          return (
            <label
              key={p.id}
              className={cx('card', on && 'chip-on')}
              style={{
                display: 'flex',
                gap: 10,
                alignItems: 'flex-start',
                padding: '12px 14px',
                cursor: p.configured && !down ? 'pointer' : 'not-allowed',
                borderStyle: p.configured ? 'solid' : 'dashed',
                background: on ? 'var(--accent-soft)' : p.configured ? 'var(--surface)' : 'var(--surface-2)',
                borderColor: on ? 'var(--accent)' : undefined,
                color: 'var(--text)',
                fontWeight: 400,
              }}
            >
              <input
                type="radio"
                name="ai-provider"
                value={p.id}
                checked={on}
                disabled={!p.configured || down || set.isPending}
                onChange={() => set.mutate(p.id as AiProvider)}
                style={{ accentColor: 'var(--accent)', margin: '3px 0 0', width: 15, height: 15 }}
                aria-describedby={`ai-${p.id}-state`}
              />
              <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
                <span style={{ fontWeight: 600, color: p.configured ? 'var(--text)' : 'var(--text-3)' }}>{p.name}</span>
                <span className="help" id={`ai-${p.id}-state`} style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <span className={cx('sdot', p.configured ? 'sdot-ok' : 'sdot-none')} />
                  {p.configured ? 'Configured' : 'Not configured'}
                  {p.model ? <span className="mono">· {p.model}</span> : null}
                  {pending && <span className="spin" aria-hidden="true" />}
                  {on && <span className="pill st-will" style={{ height: 18 }}>In use</span>}
                </span>
              </span>
            </label>
          );
        })}
      </div>
      {missing.length > 0 && (
        <div className="help" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {missing.map((p) => (
            <span key={p.id}>
              To enable {p.short}, {providerSetupHint(p.id as AiProvider)}.
            </span>
          ))}
          <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start', marginTop: 4 }} onClick={() => void q.refetch()}>
            Check again
          </button>
        </div>
      )}
      {set.error && <span className="err">{errorMessage(set.error)}</span>}
    </div>
  );
}
