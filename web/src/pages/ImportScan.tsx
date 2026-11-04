import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';

type ImportResult = { test_id: number; import_job_id: string; created_count: number };

export default function ImportScan(): JSX.Element {
  const navigate = useNavigate();
  const [engagementId, setEngagementId] = useState('');
  const [scannerKey, setScannerKey] = useState('generic');
  const [title, setTitle] = useState('');
  const [file, setFile] = useState<File | null>(null);

  const mutation = useMutation<ImportResult, Error>({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a report file first.');
      const { data, error, response } = await api.POST('/api/v1/import', {
        body: {
          engagement_id: Number(engagementId),
          scanner_key: scannerKey,
          title: title || null,
          // The multipart serializer below sends the real File; the generated
          // type models the field as a string, so cast here.
          file: file as unknown as string,
        },
        bodySerializer(body: Record<string, unknown>) {
          const fd = new FormData();
          fd.append('engagement_id', String(body.engagement_id));
          fd.append('scanner_key', String(body.scanner_key));
          if (body.title != null) fd.append('title', String(body.title));
          fd.append('file', body.file as Blob);
          return fd;
        },
      });
      if (error || !data) {
        const detail =
          error && typeof error === 'object' && 'detail' in error
            ? String((error as { detail: unknown }).detail)
            : `Import failed (HTTP ${response.status}).`;
        throw new Error(detail);
      }
      return data as ImportResult;
    },
    onSuccess: (result) => {
      navigate(`/tests/${result.test_id}`);
    },
  });

  return (
    <section>
      <h2>Import a scan</h2>
      <p style={{ color: '#666' }}>
        Synchronous import (Phase 2): small, size-capped reports parsed into a new Test.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
        style={{ display: 'grid', gap: 10, maxWidth: 420 }}
      >
        <label>
          Engagement ID
          <input
            type="number"
            required
            value={engagementId}
            onChange={(e) => setEngagementId(e.target.value)}
            style={{ display: 'block', width: '100%' }}
          />
        </label>
        <label>
          Scanner
          <select
            value={scannerKey}
            onChange={(e) => setScannerKey(e.target.value)}
            style={{ display: 'block', width: '100%' }}
          >
            <option value="generic">Kata Generic JSON</option>
            <option value="trivy">Trivy</option>
            <option value="kubescape">Kubescape</option>
          </select>
        </label>
        <label>
          Title (optional)
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            style={{ display: 'block', width: '100%' }}
          />
        </label>
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
        <button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? 'Importing…' : 'Import'}
        </button>
      </form>
      {mutation.isError ? (
        <p role="alert" style={{ color: '#b00' }}>
          {mutation.error.message}
        </p>
      ) : null}
    </section>
  );
}
