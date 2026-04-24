import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';
import { Share2 } from 'lucide-react';
import { api } from '../hooks/useApi';
import type { GraphInfo } from '../types/api';

export function GraphsListPage() {
  const { data: graphs = [], isLoading } = useQuery<GraphInfo[]>({
    queryKey: ['graphs'],
    queryFn: api.listGraphs,
  });

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-zinc-800 px-6 py-4">
        <h1 className="text-base font-semibold text-zinc-100">Graphs</h1>
      </header>
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {isLoading && (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="h-12 animate-pulse rounded-lg bg-zinc-800" />
            ))}
          </div>
        )}
        {!isLoading && graphs.length === 0 && (
          <p className="py-12 text-center text-sm text-zinc-600">No graphs registered</p>
        )}
        <div className="space-y-2">
          {graphs.map((g) => (
            <Link
              key={g.name}
              to={`/graphs/${encodeURIComponent(g.name)}`}
              className="flex items-center gap-3 rounded-lg border border-zinc-800 px-4 py-3 text-sm transition-colors hover:border-zinc-700 hover:bg-zinc-900"
            >
              <Share2 size={16} className="flex-shrink-0 text-zinc-500" />
              <span className="font-medium text-zinc-200">{g.name}</span>
              <span className="ml-auto text-xs text-zinc-600">
                {g.nodes.length} nodes · {g.edges.length} edges
              </span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
