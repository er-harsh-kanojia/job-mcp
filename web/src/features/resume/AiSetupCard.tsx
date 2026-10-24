import { useQueryClient } from '@tanstack/react-query';
import { Icon } from '../../components/Icon';
import { PROVIDER_KEY, useAiProvider, useAiSettings, useSetAiProvider } from '../../lib/queries';

/** Shown when an AI endpoint answers 503 ai_not_configured. Never asks for the key itself. */
export function AiSetupCard({ compact }: { compact?: boolean }) {
  const p = useAiProvider();
  const settings = useAiSettings();
  const set = useSetAiProvider();
  const qc = useQueryClient();
  const other = settings.data?.providers.find((x) => x.id !== p.id && x.configured);
  const key = PROVIDER_KEY[p.id];
  return (
    <section className={compact ? 'aisetup' : 'card aisetup'} role="status" aria-labelledby="ai-setup-h">
      <span className="empty-ic" style={{ flex: 'none' }}>
        <Icon name="key" />
      </span>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 0, flex: 1 }}>
        <h2 className="h2" id="ai-setup-h">
          Connect {p.short} to review your resume
        </h2>
        {p.id === 'local' ? (
          <>
            <p style={{ color: 'var(--text-2)', maxWidth: 620 }}>
              Resume review, the prep plan and mock interviews use a model running on this computer, and no local model server is answering. Open LM Studio, load a model
              (gpt-oss-20b works well), set its context length to 32768, and start the server from the Developer tab.
            </p>
            <code className="codeline">http://localhost:1234/v1</code>
            <span className="help">For Ollama or another server, set JOB_MCP_LOCAL_BASE_URL in D:\Job-MCP\.env and restart Job MCP.</span>
          </>
        ) : (
          <>
            <p style={{ color: 'var(--text-2)', maxWidth: 620 }}>
              Resume review, the prep plan and mock interviews use the {p.name} API, and no key is set for it yet. Add {key} to D:\Job-MCP\.env and restart the Job MCP server.
            </p>
            <code className="codeline" aria-label={`Line to add to the .env file: ${key}=your key`}>
              {key}=<span className="muted">your-key-here</span>
            </code>
            <span className="help">The key stays in .env on this machine. Job MCP never shows it or sends it to the browser.</span>
          </>
        )}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => {
              void qc.invalidateQueries({ queryKey: ['ai-settings'] });
              void qc.invalidateQueries({ queryKey: ['health'] });
              void qc.invalidateQueries({ queryKey: ['review'] });
            }}
          >
            <Icon name="retry" small />
            Check again
          </button>
          {other && (
            <button className="btn btn-sm" onClick={() => set.mutate(other.id)} disabled={set.isPending}>
              Use {other.short} instead
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
