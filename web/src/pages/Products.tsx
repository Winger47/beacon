import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api/client';

export default function Products(): JSX.Element {
  const { data, isLoading, error } = useQuery({
    queryKey: ['products'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/products');
      if (error) throw new Error('failed to load products');
      return data;
    },
  });

  if (isLoading) return <p>Loading products…</p>;
  if (error) return <p role="alert">Could not load products. Is the API running?</p>;

  return (
    <section>
      <h2>Products</h2>
      {data && data.length > 0 ? (
        <ul>
          {data.map((p) => (
            <li key={p.id}>
              <Link to={`/products/${p.id}/findings`}>{p.name}</Link>{' '}
              <span style={{ color: '#888' }}>#{p.id}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p>No products yet.</p>
      )}
    </section>
  );
}
