import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { api } from '../api/client';

export default function ProductFindings(): JSX.Element {
  const { id } = useParams();
  const productId = Number(id);

  const { data, isLoading, error } = useQuery({
    queryKey: ['findings', productId],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/findings', {
        params: { query: { product_id: productId, limit: 100 } },
      });
      if (error) throw new Error('failed to load findings');
      return data;
    },
    enabled: Number.isFinite(productId),
  });

  if (isLoading) return <p>Loading findings…</p>;
  if (error) return <p role="alert">Could not load findings.</p>;

  const items = data?.items ?? [];
  return (
    <section>
      <h2>Findings — product #{productId}</h2>
      {items.length === 0 ? (
        <p>No findings in this product.</p>
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
      {data?.next_cursor ? <p style={{ color: '#888' }}>More pages available (keyset).</p> : null}
    </section>
  );
}
