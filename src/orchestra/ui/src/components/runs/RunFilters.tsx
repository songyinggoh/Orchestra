import { useQuery } from '@tanstack/react-query';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { api } from '../../hooks/useApi';
import { useRunFilters } from '../../hooks/useRunFilters';
import type { GraphInfo } from '../../types/api';

const STATUSES = ['pending', 'running', 'completed', 'error', 'cancelled'];

export function RunFilters() {
  const { filters, setFilter, clearAll, isActive } = useRunFilters();
  const { data: graphs } = useQuery<GraphInfo[]>({ queryKey: ['graphs'], queryFn: () => api.listGraphs(), staleTime: 60_000 });

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-zinc-800 bg-zinc-950 px-4 py-2">
      <Input
        aria-label="Search runs"
        placeholder="Search…"
        value={filters.q}
        onChange={(e) => setFilter({ q: e.target.value })}
        className="h-7 w-40 text-xs"
      />
      <div className="flex flex-wrap gap-1">
        {STATUSES.map((s) => (
          <button
            key={s}
            onClick={() => {
              const next = filters.status.includes(s)
                ? filters.status.filter((x) => x !== s)
                : [...filters.status, s];
              setFilter({ status: next });
            }}
            className={`rounded px-2 py-0.5 text-[10px] capitalize ${filters.status.includes(s) ? 'bg-violet-500 text-white' : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'}`}
          >
            {s}
          </button>
        ))}
      </div>
      {graphs && graphs.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {graphs.map((g) => (
            <button
              key={g.name}
              onClick={() => {
                const next = filters.graph.includes(g.name)
                  ? filters.graph.filter((x) => x !== g.name)
                  : [...filters.graph, g.name];
                setFilter({ graph: next });
              }}
              className={`rounded px-2 py-0.5 font-mono text-[10px] ${filters.graph.includes(g.name) ? 'bg-violet-500 text-white' : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700'}`}
            >
              {g.name}
            </button>
          ))}
        </div>
      )}
      {isActive && (
        <Button variant="ghost" size="sm" className="h-6 text-[10px] text-zinc-500" onClick={clearAll}>
          Clear all
        </Button>
      )}
    </div>
  );
}
