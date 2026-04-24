/**
 * CostBreakdownPanel — renders "By model" + "By agent" tables from
 * GET /api/v1/runs/{id}/cost. Wired as the "Cost" tab in RunDetailShell.
 */

import { useCost } from '../../hooks/queries/useCost';

interface TableRowProps {
  label: string;
  calls: number;
  inputTok?: number;
  outputTok?: number;
  cost: number;
}

function TableRow({ label, calls, inputTok, outputTok, cost }: TableRowProps) {
  return (
    <tr className="border-t border-zinc-800 text-xs hover:bg-zinc-800/40">
      <td className="px-3 py-1.5 font-mono text-zinc-300">{label}</td>
      <td className="px-3 py-1.5 tabular-nums text-zinc-500 text-right">{calls}</td>
      {inputTok !== undefined && (
        <td className="px-3 py-1.5 tabular-nums text-zinc-500 text-right">
          {inputTok.toLocaleString()}
        </td>
      )}
      {outputTok !== undefined && (
        <td className="px-3 py-1.5 tabular-nums text-zinc-500 text-right">
          {outputTok.toLocaleString()}
        </td>
      )}
      <td className={`px-3 py-1.5 tabular-nums text-right font-mono ${cost > 0.1 ? 'text-amber-400' : 'text-zinc-400'}`}>
        ${cost.toFixed(4)}
      </td>
    </tr>
  );
}

interface CostBreakdownPanelProps {
  runId: string;
}

export function CostBreakdownPanel({ runId }: CostBreakdownPanelProps) {
  const { data, isLoading, error } = useCost(runId);

  if (isLoading) {
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-6 animate-pulse rounded bg-zinc-800" />
        ))}
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <p className="text-center text-sm text-zinc-600">
          No cost data yet — runs need at least one <code>llm.called</code> event to appear
        </p>
      </div>
    );
  }

  const byModelEntries = Object.entries(data.by_model).sort(
    ([, a], [, b]) => b.cost_usd - a.cost_usd,
  );
  const byAgentEntries = Object.entries(data.by_agent).sort(
    ([, a], [, b]) => b.cost_usd - a.cost_usd,
  );

  return (
    <div className="overflow-y-auto p-4 space-y-6">
      {/* Totals */}
      <div className="flex gap-6 font-mono text-xs">
        <div>
          <p className="text-zinc-600">Total</p>
          <p className={`text-lg font-semibold tabular-nums ${data.total_cost_usd > 0.1 ? 'text-amber-400' : 'text-zinc-300'}`}>
            ${data.total_cost_usd.toFixed(4)}
          </p>
        </div>
        <div>
          <p className="text-zinc-600">Tokens</p>
          <p className="text-lg font-semibold tabular-nums text-zinc-300">
            {data.total_tokens.toLocaleString()}
          </p>
        </div>
        <div>
          <p className="text-zinc-600">LLM calls</p>
          <p className="text-lg font-semibold tabular-nums text-zinc-300">{data.call_count}</p>
        </div>
      </div>

      {/* By model */}
      {byModelEntries.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-zinc-500">
            By model
          </h3>
          <table className="w-full text-left">
            <thead>
              <tr className="text-[11px] text-zinc-600">
                <th className="px-3 py-1 font-medium">Model</th>
                <th className="px-3 py-1 font-medium text-right">Calls</th>
                <th className="px-3 py-1 font-medium text-right">Input tok</th>
                <th className="px-3 py-1 font-medium text-right">Output tok</th>
                <th className="px-3 py-1 font-medium text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {byModelEntries.map(([model, b]) => (
                <TableRow
                  key={model}
                  label={model}
                  calls={b.call_count}
                  inputTok={b.input_tokens}
                  outputTok={b.output_tokens}
                  cost={b.cost_usd}
                />
              ))}
            </tbody>
          </table>
        </section>
      )}

      {/* By agent */}
      {byAgentEntries.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-widest text-zinc-500">
            By agent
          </h3>
          <table className="w-full text-left">
            <thead>
              <tr className="text-[11px] text-zinc-600">
                <th className="px-3 py-1 font-medium">Agent</th>
                <th className="px-3 py-1 font-medium text-right">Calls</th>
                <th className="px-3 py-1 font-medium text-right">Cost</th>
              </tr>
            </thead>
            <tbody>
              {byAgentEntries.map(([agent, b]) => (
                <TableRow key={agent} label={agent} calls={b.call_count} cost={b.cost_usd} />
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
