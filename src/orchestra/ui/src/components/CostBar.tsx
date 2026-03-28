interface CostBarProps {
  status: string;
  elapsed: number | null;
  tokens: number;
  cost: number;
  calls: number;
}

export function CostBar({ status, elapsed, tokens, cost, calls }: CostBarProps) {
  const statusColor: Record<string, string> = {
    running: 'bg-amber-500',
    completed: 'bg-emerald-500',
    failed: 'bg-red-500',
    cancelled: 'bg-zinc-500',
  };

  return (
    <div className="flex items-center gap-4 px-4 py-2 bg-zinc-900 border-b border-zinc-800 text-xs font-mono">
      <span className="flex items-center gap-1.5">
        <span className={`w-2 h-2 rounded-full ${statusColor[status] ?? 'bg-zinc-600'}`} />
        <span className="text-zinc-300 capitalize">{status}</span>
      </span>
      {elapsed != null && (
        <span className="text-zinc-500">
          {(elapsed / 1000).toFixed(1)}s
        </span>
      )}
      <span className="text-zinc-500">
        {tokens.toLocaleString()} tokens
      </span>
      <span className={cost > 0.10 ? 'text-amber-400' : 'text-zinc-500'}>
        ${cost.toFixed(4)}
      </span>
      <span className="text-zinc-600">
        {calls} LLM call{calls !== 1 ? 's' : ''}
      </span>
    </div>
  );
}
