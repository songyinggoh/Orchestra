/**
 * Thin wrapper around fetch for Orchestra API calls.
 *
 * Reads the API key from useAuthStore.getState() (outside React) so it
 * can be called from react-query queryFns without hook rules.
 * On 401: clears the stored key so the settings page prompts for a new one.
 */

import { useAuthStore } from '../stores/useAuthStore';
import type {
  RunStatus,
  EventItem,
  RunState,
  RunCost,
  GraphInfo,
  ForkRequest,
  ForkResponse,
  ResumeRequest,
  CreateRunRequest,
  CreateRunResponse,
  CostAggregateResponse,
} from '../types/api';

const BASE = '/api/v1';

export class UnauthorizedError extends Error {
  constructor() {
    super('Missing or invalid API key');
    this.name = 'UnauthorizedError';
  }
}

function authHeaders(): Record<string, string> {
  const key = useAuthStore.getState().apiKey;
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

  if (res.status === 401) {
    useAuthStore.getState().setApiKey(null);
    throw new UnauthorizedError();
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }

  return res.json() as Promise<T>;
}

export const api = {
  listRuns: () => apiFetch<RunStatus[]>('/runs'),
  getRun: (id: string) => apiFetch<RunStatus>(`/runs/${encodeURIComponent(id)}`),
  getEvents: (id: string, afterSeq = -1) =>
    apiFetch<EventItem[]>(
      `/runs/${encodeURIComponent(id)}/events?after_sequence=${afterSeq}`,
    ),
  getState: (id: string) => apiFetch<RunState>(`/runs/${encodeURIComponent(id)}/state`),
  getCost: (id: string) => apiFetch<RunCost>(`/runs/${encodeURIComponent(id)}/cost`),
  cancelRun: (id: string) =>
    apiFetch<RunStatus>(`/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  forkRun: (id: string, body: ForkRequest) =>
    apiFetch<ForkResponse>(`/runs/${encodeURIComponent(id)}/fork`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  resumeRun: (id: string, body: ResumeRequest) =>
    apiFetch<void>(`/runs/${encodeURIComponent(id)}/resume`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  createRun: (body: CreateRunRequest) =>
    apiFetch<CreateRunResponse>('/runs', {
      method: 'POST',
      // Server expects graph_name + input (not workflow_name + initial_input).
      body: JSON.stringify({ graph_name: body.workflow_name, input: body.initial_input }),
    }),
  getCostAggregate: (params: { from: string; to: string; group_by: 'model' | 'agent' | 'graph' | 'week' }) =>
    apiFetch<CostAggregateResponse>(
      `/cost/aggregate?from=${encodeURIComponent(params.from)}&to=${encodeURIComponent(params.to)}&group_by=${params.group_by}`,
    ),
  listGraphs: () => apiFetch<GraphInfo[]>('/graphs'),
  getGraph: (name: string) => apiFetch<GraphInfo>(`/graphs/${encodeURIComponent(name)}`),
};
