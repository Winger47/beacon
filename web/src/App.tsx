import { Link, Navigate, Outlet, useNavigate } from 'react-router-dom';
import { clearDevUser, getDevUser } from './api/client';
import { appTitle } from './lib/meta';

export default function App(): JSX.Element {
  const navigate = useNavigate();
  const devUser = getDevUser();

  if (!devUser) return <Navigate to="/login" replace />;

  return (
    <div
      style={{ fontFamily: 'system-ui, sans-serif', padding: 16, maxWidth: 960, margin: '0 auto' }}
    >
      <header
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          borderBottom: '1px solid #ddd',
          paddingBottom: 8,
        }}
      >
        <nav style={{ display: 'flex', gap: 12 }}>
          <strong>{appTitle()}</strong>
          <Link to="/products">Products</Link>
          <Link to="/import">Import</Link>
        </nav>
        <span style={{ color: '#666' }}>
          {devUser}{' '}
          <button
            type="button"
            onClick={() => {
              clearDevUser();
              navigate('/login');
            }}
          >
            Sign out
          </button>
        </span>
      </header>
      <main style={{ paddingTop: 16 }}>
        <Outlet />
      </main>
    </div>
  );
}
