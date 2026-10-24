import { useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '../../api';
import { Icon } from '../../components/Icon';
import { Alert, EmptyState, LoadingCard } from '../../components/ui';
import { fmtDayTime } from '../../lib/format';

/** Every stored report, newest first, with downloads and which report each was compared with. */
export function ReportsTab() {
  const q = useQuery({ queryKey: ['reviews', 'all'], queryFn: () => api.reviews(true), staleTime: 10_000 });
  if (q.isLoading) return <LoadingCard label="Loading your reports…" />;
  if (q.error)
    return (
      <Alert tone="danger" title="Couldn't load your reports" actions={<button className="btn btn-sm" onClick={() => void q.refetch()}>Retry</button>}>
        {errorMessage(q.error)}
      </Alert>
    );
  const rows = q.data?.reviews ?? [];
  if (!rows.length) return <EmptyState icon="file" title="No reports yet">Analyse your resume to create the first one.</EmptyState>;
  const byId = new Map(rows.map((r) => [r.review_id, r]));
  return (
    <section className="card" style={{ overflow: 'hidden' }}>
      <div className="sechead">
        <div>
          <h2 className="h2">Your reports</h2>
          <div className="help">Each analysis is kept. A new analysis is compared with your latest report automatically.</div>
        </div>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr className="help" style={{ textAlign: 'left' }}>
              <th style={{ padding: '8px 16px', fontWeight: 500 }}>Date</th>
              <th style={{ padding: '8px', fontWeight: 500 }}>Role</th>
              <th style={{ padding: '8px', fontWeight: 500 }}>Resume file</th>
              <th style={{ padding: '8px', fontWeight: 500, textAlign: 'right' }}>Score</th>
              <th style={{ padding: '8px', fontWeight: 500 }}>Compared with</th>
              <th style={{ padding: '8px 16px', fontWeight: 500, textAlign: 'right' }}>Download</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const prev = r.compared_to ? byId.get(r.compared_to) : undefined;
              return (
                <tr key={r.review_id} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '10px 16px', whiteSpace: 'nowrap' }}>{fmtDayTime(r.analysed_at)}</td>
                  <td style={{ padding: 8 }}>{r.target_role}</td>
                  <td style={{ padding: 8 }} className="help">
                    {r.resume_filename || '—'}
                  </td>
                  <td style={{ padding: 8, textAlign: 'right' }} className="mono">
                    {r.overall}
                  </td>
                  <td style={{ padding: 8 }} className="help">
                    {prev ? `${fmtDayTime(prev.analysed_at)} (${prev.overall})` : r.compared_to ? `Report #${r.compared_to}` : '—'}
                  </td>
                  <td style={{ padding: '8px 16px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                    <a className="btn btn-sm" href={api.reportUrl(r.review_id, 'pdf')} download aria-label={`Download the ${r.target_role} report from ${fmtDayTime(r.analysed_at)} as PDF`}>
                      <Icon name="file" small />
                      PDF
                    </a>{' '}
                    <a className="btn btn-sm btn-ghost" href={api.reportUrl(r.review_id, 'md')} download aria-label={`Download the ${r.target_role} report from ${fmtDayTime(r.analysed_at)} as Markdown`}>
                      Markdown
                    </a>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
