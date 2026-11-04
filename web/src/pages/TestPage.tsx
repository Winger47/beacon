import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { api } from '../api/client';

export default function TestPage(): JSX.Element {
  const { id } = useParams();
  const testId = Number(id);
  const enabled = Number.isFinite(testId);

  const test = useQuery({
    queryKey: ['test', testId],
    enabled,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/tests/{test_id}', {
        params: { path: { test_id: testId } },
      });
      if (error) throw new Error('failed to load test');
      return data;
    },
  });

  const findings = useQuery({
    queryKey: ['findings', 'test', testId],
    enabled,
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/findings', {
        params: { query: { test_id: testId, limit: 100 } },
      });
      if (error) throw new Error('failed to load findings');
      return data;
    },
  });

  if (test.isLoading) return <p>Loading test…</p>;
  if (test.error || !test.data) return <p role="alert">Could not load this test.</p>;

  const imports = test.data.imports ?? [];
  const items = findings.data?.items ?? [];

  return (
    <section>
      <h2>
        Test #{test.data.id} — <code>{test.data.scanner_key}</code>
        {test.data.title ? ` · ${test.data.title}` : ''}
      </h2>

      <h3>Import history</h3>
      {imports.length === 0 ? (
        <p>No imports recorded.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th align="left">When</th>
              <th align="left">Kind</th>
              <th align="right">Created</th>
              <th align="right">Untouched</th>
              <th align="right">Reactivated</th>
              <th align="right">Closed</th>
              <th align="left">Job</th>
            </tr>
          </thead>
          <tbody>
            {imports.map((imp) => (
              <tr key={imp.id}>
                <td>{new Date(imp.created_at).toLocaleString()}</td>
                <td>{imp.kind}</td>
                <td align="right">{imp.created_count}</td>
                <td align="right">{imp.untouched_count}</td>
                <td align="right">{imp.reactivated_count}</td>
                <td align="right">{imp.closed_count}</td>
                <td>
                  <code style={{ color: '#888' }}>{imp.import_job_id.slice(0, 8)}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Findings</h3>
      {findings.isLoading ? (
        <p>Loading findings…</p>
      ) : items.length === 0 ? (
        <p>No findings in this test.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th align="left">ID</th>
              <th align="left">Severity</th>
              <th align="left">Status</th>
              <th align="left">Title</th>
            </tr>
          </thead>
          <tbody>
            {items.map((f) => (
              <tr key={f.id}>
                <td>{f.id}</td>
                <td>{f.severity}</td>
                <td>{f.status}</td>
                <td>{f.title}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {findings.data?.next_cursor ? (
        <p style={{ color: '#888' }}>More pages available (keyset).</p>
      ) : null}
    </section>
  );
}
