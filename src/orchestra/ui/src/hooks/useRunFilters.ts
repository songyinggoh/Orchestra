import { useCallback } from 'react';
import { useSearchParams } from 'react-router';

export interface RunFilters {
  q: string;
  status: string[];
  graph: string[];
  from: string;
  to: string;
}

const EMPTY: RunFilters = { q: '', status: [], graph: [], from: '', to: '' };

export function useRunFilters() {
  const [params, setParams] = useSearchParams();

  const filters: RunFilters = {
    q: params.get('q') ?? '',
    status: params.get('status') ? params.get('status')!.split(',').filter(Boolean) : [],
    graph: params.get('graph') ? params.get('graph')!.split(',').filter(Boolean) : [],
    from: params.get('from') ?? '',
    to: params.get('to') ?? '',
  };

  const setFilter = useCallback(
    (patch: Partial<RunFilters>) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        const merged = { ...filters, ...patch };
        merged.q ? next.set('q', merged.q) : next.delete('q');
        merged.status.length ? next.set('status', merged.status.join(',')) : next.delete('status');
        merged.graph.length ? next.set('graph', merged.graph.join(',')) : next.delete('graph');
        merged.from ? next.set('from', merged.from) : next.delete('from');
        merged.to ? next.set('to', merged.to) : next.delete('to');
        return next;
      }, { replace: true });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [params, setParams],
  );

  const clearAll = useCallback(() => {
    setParams({}, { replace: true });
  }, [setParams]);

  const isActive = filters.q !== '' || filters.status.length > 0 || filters.graph.length > 0 || filters.from !== '' || filters.to !== '';

  return { filters, setFilter, clearAll, isActive, empty: EMPTY };
}
