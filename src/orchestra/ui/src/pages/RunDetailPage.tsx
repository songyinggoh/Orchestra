/**
 * RunDetailPage — stub wired up in T-6.1.3; fully implemented in T-6.1.9.
 * Reads route params and seeds UIStore so W2 scrubber can consume them.
 */
import { useEffect } from 'react';
import { useParams } from 'react-router';
import { useUIStore } from '../stores/useUIStore';

interface RunDetailPageProps {
  securityFilter?: boolean;
  costTab?: boolean;
}

export function RunDetailPage({ securityFilter, costTab }: RunDetailPageProps) {
  const { runId, sequence } = useParams<{ runId: string; sequence?: string }>();
  const setSelectedSequence = useUIStore((s) => s.setSelectedSequence);
  const setTimelineFilter = useUIStore((s) => s.setTimelineFilter);
  const setRightPaneTab = useUIStore((s) => s.setRightPaneTab);

  useEffect(() => {
    if (sequence !== undefined) {
      setSelectedSequence(parseInt(sequence, 10));
    } else {
      setSelectedSequence(null);
    }
  }, [sequence, setSelectedSequence]);

  useEffect(() => {
    if (securityFilter) {
      setTimelineFilter({ type: 'security' });
      setRightPaneTab('security');
    } else if (costTab) {
      setRightPaneTab('cost');
    } else {
      setTimelineFilter({ type: 'all' });
      setRightPaneTab('timeline');
    }
  }, [securityFilter, costTab, setTimelineFilter, setRightPaneTab]);

  if (!runId) return null;

  // Full implementation in T-6.1.9 — renders RunDetailShell.
  return (
    <div className="flex h-full items-center justify-center">
      <p className="text-sm text-zinc-500">Loading run {runId}…</p>
    </div>
  );
}
