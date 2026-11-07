import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { api } from '../api/client';

type ReimportResult = {
  status: string;
  import_job_id: string;
  created: number;
  reactivated: number;
  untouched: number;
  closed: number;
  close_candidates: number;
};

export default function TestPage(): JSX.Element {
  const { id } = useParams();
  const testId = Number(id);
  const enabled = Number.isFinite(testId);
  const queryClient = useQueryClient();

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

  function refresh(): void {
    void queryClient.invalidateQueries({ queryKey: ['test', testId] });
    void queryClient.invalidateQueries({ queryKey: ['findings', 'test', testId] });
  }

  if (test.isLoading) return <p>Loading test…</p>;
  if (test.error || !test.data) return <p role="alert">Could not load this test.</p>;

  const imports = test.data.imports ?? [];
  const pending = test.data.pending_decisions ?? [];
  const items = findings.data?.items ?? [];

  return (
    <section>
      <h2>
        Test #{test.data.id} — <code>{test.data.scanner_key}</code>
        {test.data.title ? ` · ${test.data.title}` : ''}
      </h2>

      {pending.length > 0 ? <PendingDecisions decisions={pending} onResolved={refresh} /> : null}

      <ReimportPanel testId={testId} scannerKey={test.data.scanner_key} onDone={refresh} />

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

type PendingDecision = {
  import_job_id: string;
  active_before: number;
  incoming_count: number;
  close_candidate_count: number;
  created_at: string;
};

function PendingDecisions({
  decisions,
  onResolved,
}: {
  decisions: PendingDecision[];
  onResolved: () => void;
}): JSX.Element {
  return (
    <div
      role="alert"
      style={{
        border: '1px solid #e0a800',
        background: '#fff8e1',
        borderRadius: 6,
        padding: 12,
        margin: '12px 0',
      }}
    >
      <strong>⚠ Mass-closure paused — human confirmation required</strong>
      {decisions.map((d) => (
        <PendingDecisionRow key={d.import_job_id} decision={d} onResolved={onResolved} />
      ))}
    </div>
  );
}

function PendingDecisionRow({
  decision,
  onResolved,
}: {
  decision: PendingDecision;
  onResolved: () => void;
}): JSX.Element {
  const resolve = useMutation<unknown, Error, 'confirm' | 'reject'>({
    mutationFn: async (action) => {
      const path =
        action === 'confirm'
          ? '/api/v1/reimport/{job_id}/confirm'
          : '/api/v1/reimport/{job_id}/reject';
      const { data, error, response } = await api.POST(path, {
        params: { path: { job_id: decision.import_job_id } },
      });
      if (error || !data) throw new Error(`Failed to ${action} (HTTP ${response.status}).`);
      return data;
    },
    onSuccess: onResolved,
  });

  return (
    <div style={{ marginTop: 8, fontSize: 14 }}>
      <p style={{ margin: '4px 0' }}>
        Reimport <code>{decision.import_job_id.slice(0, 8)}</code> would close{' '}
        <strong>{decision.close_candidate_count}</strong> of {decision.active_before} active
        findings, but the incoming report only had {decision.incoming_count}. This looks like a
        truncated report.
      </p>
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          type="button"
          disabled={resolve.isPending}
          onClick={() => resolve.mutate('confirm')}
        >
          Confirm closure
        </button>
        <button type="button" disabled={resolve.isPending} onClick={() => resolve.mutate('reject')}>
          Reject (keep active)
        </button>
      </div>
      {resolve.isError ? (
        <p style={{ color: '#b00', margin: '4px 0' }}>{resolve.error.message}</p>
      ) : null}
    </div>
  );
}

function ReimportPanel({
  testId,
  scannerKey,
  onDone,
}: {
  testId: number;
  scannerKey: string;
  onDone: () => void;
}): JSX.Element {
  const [file, setFile] = useState<File | null>(null);
  const [closeOld, setCloseOld] = useState(true);
  const [doNotReactivate, setDoNotReactivate] = useState(false);

  const mutation = useMutation<ReimportResult, Error>({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a report file first.');
      const { data, error, response } = await api.POST('/api/v1/reimport', {
        body: {
          test_id: testId,
          close_old_findings: closeOld,
          do_not_reactivate: doNotReactivate,
          file: file as unknown as string,
        },
        bodySerializer(body: Record<string, unknown>) {
          const fd = new FormData();
          fd.append('test_id', String(body.test_id));
          fd.append('close_old_findings', String(body.close_old_findings));
          fd.append('do_not_reactivate', String(body.do_not_reactivate));
          fd.append('file', body.file as Blob);
          return fd;
        },
      });
      if (error || !data) throw new Error(`Reimport failed (HTTP ${response.status}).`);
      return data as ReimportResult;
    },
    onSuccess: onDone,
  });

  const r = mutation.data;

  return (
    <details style={{ margin: '12px 0', border: '1px solid #ddd', borderRadius: 6, padding: 12 }}>
      <summary style={{ cursor: 'pointer' }}>
        Reimport a <code>{scannerKey}</code> report into this test
      </summary>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
        style={{ display: 'grid', gap: 8, maxWidth: 420, marginTop: 10 }}
      >
        <label>
          Report file
          <input
            type="file"
            accept="application/json,.json"
            required
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            style={{ display: 'block', width: '100%' }}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={closeOld}
            onChange={(e) => setCloseOld(e.target.checked)}
          />{' '}
          Close findings absent from this report (close_old_findings)
        </label>
        <label>
          <input
            type="checkbox"
            checked={doNotReactivate}
            onChange={(e) => setDoNotReactivate(e.target.checked)}
          />{' '}
          Do not reactivate mitigated findings (do_not_reactivate)
        </label>
        <button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Reimporting…' : 'Reimport'}
        </button>
      </form>
      {mutation.isError ? (
        <p role="alert" style={{ color: '#b00' }}>
          {mutation.error.message}
        </p>
      ) : null}
      {r ? (
        <p style={{ color: r.status === 'needs_confirmation' ? '#8a6d00' : '#2a7' }} role="status">
          {r.status === 'needs_confirmation'
            ? `Paused: ${r.close_candidates} findings would close — confirm or reject above.`
            : `Done — created ${r.created}, untouched ${r.untouched}, reactivated ${r.reactivated}, closed ${r.closed}.`}
        </p>
      ) : null}
    </details>
  );
}
