/** Thin wrapper around fetch for Orchestra API calls. */

const BASE = '/api/v1';

function getApiKey(): string | null {
  // Build-time key (set via VITE_ORCHESTRA_API_KEY) takes precedence; falls back
  // to a runtime key stored in localStorage under `orchestra_api_key`.
  const envKey = (import.meta as { env?: Record<string, string | undefined> }).env
    ?.VITE_ORCHESTRA_API_KEY;
  if (envKey) return envKey;
  try {
    return typeof localStorage !== 'undefined' ? localStorage.getItem('orchestra_api_key') : null;
  } catch {
    return null;
  }
}

function authHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { Authorization: `Bearer ${key}` } : {};
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export const api = {
  listRuns: () => apiFetch<import('../types/api').RunStatus[]>('/runs'),
  getRun: (id: string) => apiFetch<import('../types/api').RunStatus>(`/runs/${encodeURIComponent(id)}`),
  getEvents: (id: string, afterSeq = -1) =>
    apiFetch<import('../types/api').EventItem[]>(`/runs/${encodeURIComponent(id)}/events?after_sequence=${afterSeq}`),
  getState: (id: string) => apiFetch<import('../types/api').RunState>(`/runs/${encodeURIComponent(id)}/state`),
  getCost: (id: string) => apiFetch<import('../types/api').RunCost>(`/runs/${encodeURIComponent(id)}/cost`),
  cancelRun: (id: string) =>
    apiFetch<import('../types/api').RunStatus>(`/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  listGraphs: () => apiFetch<import('../types/api').GraphInfo[]>('/graphs'),
  getGraph: (name: string) => apiFetch<import('../types/api').GraphInfo>(`/graphs/${encodeURIComponent(name)}`),
};
