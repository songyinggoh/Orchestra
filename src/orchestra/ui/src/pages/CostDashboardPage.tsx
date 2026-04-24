import { lazy, Suspense, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router';
import { api } from '../hooks/useApi';
import type { CostAggregateResponse, CostAggregateEntry } from '../types/api';

const LineChart = lazy(() => import('recharts').then((m) => ({ default: m.LineChart })));
const Line = lazy(() => import('recharts').then((m) => ({ default: m.Line })));
const XAxis = lazy(() => import('recharts').then((m) => ({ default: m.XAxis })));
const YAxis = lazy(() => import('recharts').then((m) => ({ default: m.YAxis })));
const CartesianGrid = lazy(() => import('recharts').then((m) => ({ default: m.CartesianGrid })));
const RechartsTooltip = lazy(() => import('recharts').then((m) => ({ default: m.Tooltip })));
const ResponsiveContainer = lazy(() => import('recharts').then((m) => ({ default: m.ResponsiveContainer })));

type GroupBy = 'model' | 'agent' | 'graph' | 'week';

function fmt(n: number) { return `$${n.toFixed(4)}`; }
function today() { return new Date().toISOString().slice(0, 10); }
function daysAgo(n: number) {
  const d = new Date(); d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function useCostFilters() {
  const [params, setParams] = useSearchParams();
  const from = params.get('from') ?? daysAgo(30);
  const to = params.get('to') ?? today();
  const groupBy = (params.get('group_by') ?? 'model') as GroupBy;

  const setFrom = useCallback((v: string) => setParams((p) => { const n = new URLSearchParams(p); n.set('from', v); return n; }, { replace: true }), [setParams]);
  const setTo = useCallback((v: string) => setParams((p) => { const n = new URLSearchParams(p); n.set('to', v); return n; }, { replace: true }), [setParams]);
  const setGroupBy = useCallback((v: GroupBy) => setParams((p) => { const n = new URLSearchParams(p); n.set('group_by', v); return n; }, { replace: true }), [setParams]);

  return { from, to, groupBy, setFrom, setTo, setGroupBy };
}

function CostTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900 p-4">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 font-mono text-lg font-semibold text-zinc-100 tabular-nums">{value}</p>
    </div>
  );
}

function BreakdownTable({ entries }: { entries: CostAggregateEntry[] }) {
  return (
    <table className="w-full border-collapse text-xs">
      <thead>
        <tr className="border-b border-zinc-800 text-left text-zinc-500">
          <th className="py-1 pr-4">Key</th>
          <th className="py-1 pr-4 text-right tabular-nums">Cost</th>
          <th className="py-1 pr-4 text-right tabular-nums">Tokens in</th>
          <th className="py-1 pr-4 text-right tabular-nums">Tokens out</th>
          <th className="py-1 text-right tabular-nums">Calls</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <tr key={e.key} className="border-b border-zinc-900 hover:bg-zinc-900/50">
            <td className="py-1 pr-4 font-mono text-zinc-300">{e.key}</td>
            <td className="py-1 pr-4 text-right tabular-nums text-amber-400">{fmt(e.cost_usd)}</td>
            <td className="py-1 pr-4 text-right tabular-nums text-zinc-500">{e.input_tokens.toLocaleString()}</td>
            <td className="py-1 pr-4 text-right tabular-nums text-zinc-500">{e.output_tokens.toLocaleString()}</td>
            <td className="py-1 text-right tabular-nums text-zinc-500">{e.call_count}</td>
          </tr>
        ))}
        {entries.length === 0 && (
          <tr><td colSpan={5} className="py-4 text-center text-zinc-600">No data for this window</td></tr>
        )}
      </tbody>
    </table>
  );
}

export function CostDashboardPage() {
  const { from, to, groupBy, setFrom, setTo, setGroupBy } = useCostFilters();

  const { data, isLoading } = useQuery<CostAggregateResponse>({
    queryKey: ['cost', 'aggregate', { from, to, groupBy }],
    queryFn: () => api.getCostAggregate({ from, to, group_by: groupBy }),
    staleTime: 30_000,
  });

  const total = data?.total;
  const entries = data?.entries ?? [];

  const trendData = groupBy === 'week'
    ? entries.map((e) => ({ name: e.key, cost: e.cost_usd }))
    : [];

  return (
    <div className="flex h-full flex-col overflow-auto">
      <header className="border-b border-zinc-800 px-6 py-4">
        <h1 className="text-base font-semibold text-zinc-100">Cost</h1>
      </header>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 border-b border-zinc-800 px-6 py-3">
        <div className="flex items-center gap-1 text-xs text-zinc-500">
          <label htmlFor="cost-from">From</label>
          <input id="cost-from" type="date" value={from} onChange={(e) => setFrom(e.target.value)}
            className="rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-zinc-200" />
        </div>
        <div className="flex items-center gap-1 text-xs text-zinc-500">
          <label htmlFor="cost-to">To</label>
          <input id="cost-to" type="date" value={to} onChange={(e) => setTo(e.target.value)}
            className="rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-zinc-200" />
        </div>
        <div className="flex items-center gap-1 text-xs text-zinc-500">
          <label htmlFor="cost-groupby">Group by</label>
          <select id="cost-groupby" value={groupBy} onChange={(e) => setGroupBy(e.target.value as GroupBy)}
            className="rounded border border-zinc-700 bg-zinc-900 px-2 py-0.5 text-zinc-200">
            {(['model', 'agent', 'graph', 'week'] as const).map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex-1 space-y-6 overflow-auto p-6">
        {/* Tiles */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <CostTile label="Total cost" value={total ? fmt(total.cost_usd) : '—'} />
          <CostTile label="Total tokens" value={total ? total.input_tokens + total.output_tokens > 0 ? (total.input_tokens + total.output_tokens).toLocaleString() : '0' : '—'} />
          <CostTile label="Total calls" value={total ? String(total.call_count) : '—'} />
          <CostTile label="Avg $/call" value={total && total.call_count > 0 ? fmt(total.cost_usd / total.call_count) : '—'} />
        </div>

        {/* Trend chart (week grouping only) */}
        {groupBy === 'week' && trendData.length > 0 && (
          <div className="rounded-md border border-zinc-800 bg-zinc-900 p-4">
            <p className="mb-3 text-[10px] uppercase tracking-wide text-zinc-500">Cost trend by week</p>
            <Suspense fallback={<div className="h-40 text-center text-xs text-zinc-600">Loading chart…</div>}>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#71717a' }} />
                  <YAxis tick={{ fontSize: 10, fill: '#71717a' }} tickFormatter={(v) => `$${v.toFixed(2)}`} />
                  <RechartsTooltip formatter={(v: unknown) => [`$${(v as number).toFixed(6)}`, 'Cost']} contentStyle={{ background: '#18181b', border: '1px solid #3f3f46', fontSize: 11 }} />
                  <Line type="monotone" dataKey="cost" stroke="#8b5cf6" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </Suspense>
          </div>
        )}

        {/* Breakdown table */}
        <div className="rounded-md border border-zinc-800 bg-zinc-900 p-4">
          <p className="mb-3 text-[10px] uppercase tracking-wide text-zinc-500">Breakdown by {groupBy}</p>
          {isLoading ? (
            <p className="text-xs text-zinc-600">Loading…</p>
          ) : (
            <BreakdownTable entries={entries} />
          )}
        </div>
      </div>
    </div>
  );
}
