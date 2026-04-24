import { useQuery } from '@tanstack/react-query';
import { api } from '../useApi';
import type { RunStatus } from '../../types/api';

export function useRun(runId: string | undefined) {
  return useQuery<RunStatus>({
    queryKey: ['runs', runId],
    queryFn: () => api.getRun(runId!),
    enabled: !!runId,
  });
}
