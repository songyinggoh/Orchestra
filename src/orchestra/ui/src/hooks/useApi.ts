/** Thin wrapper around fetch for Orchestra API calls. */

const BASE = '/api/v1';

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
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
