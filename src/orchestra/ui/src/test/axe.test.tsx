/**
 * T-6.3.8 — Axe-core a11y test suite.
 */

import { render } from '@testing-library/react';
import { axe } from 'vitest-axe';
import { expect, test, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

vi.mock('../hooks/useApi', () => ({
  api: {
    listRuns: () => Promise.resolve([]),
    getRun: () => Promise.resolve({ run_id: 'r1', status: 'completed', created_at: '2026-01-01T00:00:00', completed_at: null, event_count: 0, workflow_name: 'test' }),
    getEvents: () => Promise.resolve([]),
    getState: () => Promise.resolve({ run_id: 'r1', state: {}, event_count: 0 }),
    getCost: () => Promise.resolve({ run_id: 'r1', total_cost_usd: 0, total_input_tokens: 0, total_output_tokens: 0, total_tokens: 0, call_count: 0, by_model: {}, by_agent: {} }),
    listGraphs: () => Promise.resolve([]),
    getCostAggregate: () => Promise.resolve({ from_date: '2026-01-01', to_date: '2026-01-31', group_by: 'model', entries: [], total: { key: '__total__', cost_usd: 0, input_tokens: 0, output_tokens: 0, call_count: 0 } }),
  },
  UnauthorizedError: class extends Error {},
}));

vi.mock('../hooks/useSSE', () => ({ useSSE: () => ({ close: vi.fn() }) }));
vi.mock('../hooks/useLayout', () => ({ layoutGraph: () => ({ nodes: [], edges: [] }) }));
vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ children }: { children?: React.ReactNode }) => React.createElement('div', null, children),
  Background: () => null, Controls: () => null, MiniMap: () => null,
}));

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    React.createElement(QueryClientProvider, { client: qc },
      React.createElement(MemoryRouter, null, children)
    )
  );
}

test('RunListPage has no critical Axe violations', async () => {
  const { RunListPage } = await import('../pages/RunListPage');
  render(React.createElement(RunListPage), { wrapper: Wrapper });
  const results = await axe(document.body);
  const critical = results.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious');
  expect(critical).toHaveLength(0);
});

test('CostDashboardPage has no critical Axe violations', async () => {
  const { CostDashboardPage } = await import('../pages/CostDashboardPage');
  render(React.createElement(CostDashboardPage), { wrapper: Wrapper });
  const results = await axe(document.body);
  const critical = results.violations.filter((v) => v.impact === 'critical' || v.impact === 'serious');
  expect(critical).toHaveLength(0);
});
