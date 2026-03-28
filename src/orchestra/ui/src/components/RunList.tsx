import { useEffect, useState } from 'react';
import { api } from '../hooks/useApi';
import type { RunStatus } from '../types/api';

interface RunListProps {
  onSelectRun: (runId: string) => void;
  selectedRunId: string | null;
}

const statusDot: Record<string, string> = {
  running: 'bg-amber-500 animate-pulse',
  completed: 'bg-emerald-500',
  failed: 'bg-red-500',
  cancelled: 'bg-zinc-500',
};

function timeAgo(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return `${Math.floor(diff / 86400000)}d ago`;
  } catch {
    return '';
  }
}

export function RunList({ onSelectRun, selectedRunId }: RunListProps) {
  const [runs, setRuns] = useState<RunStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const data = await api.listRuns();
        if (active) {
          setRuns(data);
          setError(null);
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    };
    load();
    const interval = setInterval(load, 3000);
    return () => { active = false; clearInterval(interval); };
  }, []);

  const active = runs.filter((r) => r.status === 'running');
  const finished = runs.filter((r) => r.status !== 'running');

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b border-zinc-800">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-zinc-200">Runs</h2>
          <span className="text-[10px] text-zinc-600 font-mono">{runs.length} total</span>
        </div>
      </div>

      {error && (
        <div className="px-4 py-2 text-xs text-red-400 bg-red-500/10">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto scroll-thin">
        {/* Active runs */}
        {active.length > 0 && (
          <div className="px-3 pt-2 pb-1">
            <div className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider mb-1">Active</div>
            {active.map((run) => (
              <RunRow key={run.run_id} run={run} selected={run.run_id === selectedRunId} onClick={() => onSelectRun(run.run_id)} />
            ))}
          </div>
        )}

        {/* Finished runs */}
        {finished.length > 0 && (
          <div className="px-3 pt-2 pb-1">
            <div className="text-[10px] font-medium text-zinc-500 uppercase tracking-wider mb-1">History</div>
            {finished.map((run) => (
              <RunRow key={run.run_id} run={run} selected={run.run_id === selectedRunId} onClick={() => onSelectRun(run.run_id)} />
            ))}
          </div>
        )}

        {runs.length === 0 && !error && (
          <div className="text-zinc-600 text-sm text-center py-8">No runs yet</div>
        )}
      </div>
    </div>
  );
}

function RunRow({ run, selected, onClick }: { run: RunStatus; selected: boolean; onClick: () => void }) {
  return (
    <button
      className={`w-full text-left px-2 py-1.5 rounded flex items-center gap-2 transition-colors ${
        selected ? 'bg-zinc-700/50' : 'hover:bg-zinc-800/50'
      }`}
      onClick={onClick}
    >
      <span className={`w-2 h-2 rounded-full shrink-0 ${statusDot[run.status] ?? 'bg-zinc-600'}`} />
      <div className="flex-1 min-w-0">
        <div className="text-xs text-zinc-300 truncate">
          {run.workflow_name || 'workflow'}
        </div>
        <div className="text-[10px] text-zinc-600 font-mono truncate">
          {run.run_id.slice(0, 8)}
        </div>
      </div>
      <div className="text-right shrink-0">
        <div className="text-[10px] text-zinc-500 font-mono">
          {run.event_count} evt
        </div>
        <div className="text-[10px] text-zinc-600">
          {timeAgo(run.created_at)}
        </div>
      </div>
    </button>
  );
}
