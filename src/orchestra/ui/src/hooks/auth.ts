/** Shared auth helpers for REST and SSE calls. */

export function getApiKey(): string | null {
  const envKey = (import.meta as { env?: Record<string, string | undefined> }).env
    ?.VITE_ORCHESTRA_API_KEY;
  if (envKey) return envKey;
  try {
    return typeof localStorage !== 'undefined' ? localStorage.getItem('orchestra_api_key') : null;
  } catch {
    return null;
  }
}

export function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { Authorization: `Bearer ${key}` } : {};
}
