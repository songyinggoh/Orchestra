import { NavLink } from 'react-router';
import { useQuery } from '@tanstack/react-query';
import { cn } from '@/lib/utils';
import { api } from '../hooks/useApi';
import type { RunStatus } from '../types/api';

const STATUS_DOT: Record<string, string> = {
  running: 'bg-amber-400 animate-pulse',
  completed: 'bg-emerald-500',
  error: 'bg-red-500',
  pending: 'bg-zinc-500',
};

function RunRow({ run }: { run: RunStatus }) {
  const dot = STATUS_DOT[run.status] ?? 'bg-zinc-600';
  return (
    <NavLink
      to={`/runs/${run.run_id}`}
      className={({ isActive }) =>
        cn(
          'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-zinc-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500',
          isActive ? 'bg-zinc-800 text-zinc-100' : 'text-zinc-400',
        )
      }
    >
      <span
        className={cn('mt-0.5 h-2 w-2 flex-shrink-0 rounded-full', dot)}
        aria-label={`status: ${run.status}`}
        role="status"
      />
      <span className="min-w-0 flex-1 truncate font-medium">{run.workflow_name}</span>
      <span className="flex-shrink-0 font-mono text-xs text-zinc-600">
        {run.run_id.slice(0, 7)}
      </span>
    </NavLink>
  );
}

export function RunsSidebar() {
  const { data: runs = [], isLoading } = useQuery<RunStatus[]>({
    queryKey: ['runs'],
    queryFn: api.listRuns,
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === 'running') ? 3000 : 10000,
  });

  const active = runs.filter((r) => r.status === 'running');
  const history = runs.filter((r) => r.status !== 'running');

  return (
    <aside className="flex h-full w-72 flex-col border-r border-zinc-800 bg-zinc-950">
      <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-3">
        <h2 className="text-sm font-semibold text-zinc-100">Runs</h2>
        <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
          {runs.length}
        </span>
      </div>

      <div
        className="flex-1 overflow-y-auto px-2 py-2"
        role="feed"
        aria-busy={isLoading}
        aria-label="Run list"
      >
        {isLoading && (
          <div className="space-y-1 px-1">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-8 animate-pulse rounded-md bg-zinc-800" />
            ))}
          </div>
        )}

        {active.length > 0 && (
          <section className="mb-3">
            <p className="mb-1 px-1 text-xs font-medium uppercase tracking-widest text-zinc-500">
              Active
            </p>
            <div className="space-y-0.5">
              {active.map((r) => (
                <RunRow key={r.run_id} run={r} />
              ))}
            </div>
          </section>
        )}

        {history.length > 0 && (
          <section>
            <p className="mb-1 px-1 text-xs font-medium uppercase tracking-widest text-zinc-500">
              History
            </p>
            <div className="space-y-0.5">
              {history.map((r) => (
                <RunRow key={r.run_id} run={r} />
              ))}
            </div>
          </section>
        )}

        {!isLoading && runs.length === 0 && (
          <p className="py-12 text-center text-sm text-zinc-600">No runs yet</p>
        )}
      </div>
    </aside>
  );
}
