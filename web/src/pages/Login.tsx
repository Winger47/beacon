import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { setDevUser } from '../api/client';

export default function Login(): JSX.Element {
  const [user, setUser] = useState('admin-user');
  const navigate = useNavigate();

  return (
    <main style={{ maxWidth: 420 }}>
      <h1>Kata</h1>
      <p>
        Dev login (Phase 1). Enter a user id; it is sent as <code>X-Kata-Dev-User</code> to the API
        (run it with <code>KATA_DEV_AUTH=true</code>). OIDC PKCE against Keycloak is the production
        path.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setDevUser(user.trim());
          navigate('/products');
        }}
      >
        <label>
          User id{' '}
          <input value={user} onChange={(e) => setUser(e.target.value)} aria-label="user id" />
        </label>{' '}
        <button type="submit" disabled={!user.trim()}>
          Sign in
        </button>
      </form>
    </main>
  );
}
