import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { useAuthStore } from '../stores/useAuthStore';
import { api } from './useApi';

const capturedHeaders: Record<string, string> = {};

const server = setupServer(
  http.get('/api/v1/runs', ({ request }) => {
    capturedHeaders['authorization'] = request.headers.get('authorization') ?? '';
    return HttpResponse.json([]);
  }),
  http.get('/api/v1/graphs', ({ request }) => {
    capturedHeaders['authorization'] = request.headers.get('authorization') ?? '';
    return HttpResponse.json([]);
  }),
);

beforeAll(() => server.listen());
afterEach(() => { server.resetHandlers(); useAuthStore.setState({ apiKey: null }); });
afterAll(() => server.close());

describe('useApi auth header', () => {
  it('attaches Bearer token when apiKey is set', async () => {
    useAuthStore.setState({ apiKey: 'test-key-123' });
    await api.listRuns();
    expect(capturedHeaders['authorization']).toBe('Bearer test-key-123');
  });

  it('sends no Authorization header when apiKey is null', async () => {
    useAuthStore.setState({ apiKey: null });
    await api.listRuns();
    expect(capturedHeaders['authorization']).toBe('');
  });

  it('clears apiKey and throws UnauthorizedError on 401', async () => {
    server.use(
      http.get('/api/v1/runs', () => HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 })),
    );
    useAuthStore.setState({ apiKey: 'bad-key' });
    await expect(api.listRuns()).rejects.toThrow('Missing or invalid API key');
    expect(useAuthStore.getState().apiKey).toBeNull();
  });
});
