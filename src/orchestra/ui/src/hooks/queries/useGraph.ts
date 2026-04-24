import { useQuery } from '@tanstack/react-query';
import { api } from '../useApi';
import type { GraphInfo } from '../../types/api';

export function useGraph(name: string | undefined) {
  return useQuery<GraphInfo>({
    queryKey: ['graphs', name],
    queryFn: () => api.getGraph(name!),
    enabled: !!name,
    staleTime: 60_000, // graphs rarely change mid-session
  });
}
