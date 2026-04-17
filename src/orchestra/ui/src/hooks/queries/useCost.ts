import { useQuery } from '@tanstack/react-query';
import { api } from '../useApi';
import type { RunCost } from '../../types/api';

export function useCost(runId: string | undefined) {
  return useQuery<RunCost>({
    queryKey: ['runs', runId, 'cost'],
    queryFn: () => api.getCost(runId!),
    enabled: !!runId,
  });
}
