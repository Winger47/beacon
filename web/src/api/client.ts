import createClient from 'openapi-fetch';
import type { paths } from './schema';

const baseUrl = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8001';

export const api = createClient<paths>({ baseUrl });

const DEV_USER_KEY = 'kata_dev_user';

export function getDevUser(): string | null {
  try {
    return localStorage.getItem(DEV_USER_KEY);
  } catch {
    return null;
  }
}

export function setDevUser(user: string): void {
  try {
    localStorage.setItem(DEV_USER_KEY, user);
  } catch {
    /* ignore */
  }
}

export function clearDevUser(): void {
  try {
    localStorage.removeItem(DEV_USER_KEY);
  } catch {
    /* ignore */
  }
}

// Phase 1 dev auth: send the stored dev user as a header. OIDC PKCE (Keycloak realm
// `kata`, client `kata-web`) replaces this with a real token in a later iteration.
api.use({
  onRequest({ request }) {
    const devUser = getDevUser();
    if (devUser) request.headers.set('X-Kata-Dev-User', devUser);
    return request;
  },
});
