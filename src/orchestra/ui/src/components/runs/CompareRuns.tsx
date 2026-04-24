import { useSearchParams } from 'react-router';
import { RunDetailPage } from '../../pages/RunDetailPage';

export function CompareRuns() {
  const [params] = useSearchParams();
  const a = params.get('a');
  const b = params.get('b');

  if (!a || !b) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-zinc-500">
        Pass <code className="mx-1 font-mono text-xs">?a=runId&amp;b=runId</code> to compare two runs.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex items-center gap-2 border-b border-zinc-800 bg-zinc-950 px-4 py-2">
        <span className="text-xs text-zinc-500">Comparing</span>
        <code className="font-mono text-xs text-violet-400">{a.slice(0, 8)}</code>
        <span className="text-xs text-zinc-600">vs</span>
        <code className="font-mono text-xs text-violet-400">{b.slice(0, 8)}</code>
      </header>
      <div className="flex flex-1 overflow-hidden divide-x divide-zinc-800">
        {/* Each half renders its own RunDetailPage keyed by runId */}
        <div className="flex-1 overflow-hidden">
          <RunDetailPage key={a} forceRunId={a} />
        </div>
        <div className="flex-1 overflow-hidden">
          <RunDetailPage key={b} forceRunId={b} />
        </div>
      </div>
    </div>
  );
}
