/** Re-homed from components/CostBar.tsx — same props, updated token colors. */

interface CostBarProps {
  status: string;
  elapsed: number | null;
  tokens: number;
  cost: number;
  calls: number;
}

const STATUS_DOT: Record<string, string> = {
  running:   'bg-amber-400 animate-pulse',
  completed: 'bg-emerald-500',
  error:     'bg-red-500',
  cancelled: 'bg-zinc-500',
};

export function CostBar({ status, elapsed, tokens, cost, calls }: CostBarProps) {
  return (
    <div className="flex items-center gap-4 border-b border-zinc-800 bg-zinc-900 px-4 py-2 font-mono text-xs">
      <span className="flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${STATUS_DOT[status] ?? 'bg-zinc-600'}`} />
        <span className="capitalize text-zinc-300">{status}</span>
      </span>
      {elapsed != null && (
        <span className="text-zinc-500 tabular-nums">{(elapsed / 1000).toFixed(1)}s</span>
      )}
      <span className="tabular-nums text-zinc-500">{tokens.toLocaleString()} tokens</span>
      <span className={`tabular-nums ${cost > 0.1 ? 'text-amber-400' : 'text-zinc-500'}`}>
        ${cost.toFixed(4)}
      </span>
      <span className="text-zinc-600">
        {calls} LLM call{calls !== 1 ? 's' : ''}
      </span>
    </div>
  );
}
