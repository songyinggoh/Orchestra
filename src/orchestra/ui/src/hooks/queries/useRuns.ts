import { useQuery } from '@tanstack/react-query';
import { api } from '../useApi';
import type { RunStatus } from '../../types/api';

export function useRuns() {
  return useQuery<RunStatus[]>({
    queryKey: ['runs'],
    queryFn: api.listRuns,
    refetchInterval: (query) =>
      query.state.data?.some((r) => r.status === 'running') ? 3000 : 10_000,
  });
}
