import { useState } from 'react';
import { ReactFlowProvider } from '@xyflow/react';
import { RunList } from './components/RunList';
import { RunDetail } from './components/RunDetail';
import { GraphBrowser } from './components/GraphBrowser';

type View = 'runs' | 'run-detail' | 'graphs';

export default function App() {
  const [view, setView] = useState<View>('runs');
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  return (
    <ReactFlowProvider>
      <div className="flex h-screen bg-[#0a0a0f] text-zinc-200">
        {view === 'runs' && (
          <>
            {/* Left sidebar: run list */}
            <div className="w-72 border-r border-zinc-800 flex flex-col">
              <RunList
                onSelectRun={(id) => {
                  setSelectedRunId(id);
                  setView('run-detail');
                }}
                selectedRunId={selectedRunId}
              />
            </div>

            {/* Main area */}
            <div className="flex-1 flex flex-col">
              <NavBar view={view} onNavigate={setView} />
              <div className="flex-1 flex items-center justify-center">
                <div className="text-center">
                  <div className="text-4xl text-zinc-700 mb-3">{'\u266B'}</div>
                  <div className="text-sm text-zinc-500">Select a run to inspect</div>
                  <div className="text-xs text-zinc-700 mt-1">or browse registered graphs</div>
                </div>
              </div>
            </div>
          </>
        )}

        {view === 'run-detail' && selectedRunId && (
          <RunDetail
            runId={selectedRunId}
            onBack={() => setView('runs')}
          />
        )}

        {view === 'graphs' && (
          <GraphBrowser onBack={() => setView('runs')} />
        )}
      </div>
    </ReactFlowProvider>
  );
}

function NavBar({ view, onNavigate }: { view: View; onNavigate: (v: View) => void }) {
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-zinc-800 bg-zinc-900">
      <div className="flex items-center gap-2">
        <span className="text-sm font-bold text-zinc-100">Orchestra</span>
        <span className="text-[10px] text-zinc-600 font-mono">UI</span>
      </div>
      <div className="flex gap-1">
        <NavButton active={view === 'runs'} onClick={() => onNavigate('runs')}>Runs</NavButton>
        <NavButton active={view === 'graphs'} onClick={() => onNavigate('graphs')}>Graphs</NavButton>
      </div>
    </div>
  );
}

function NavButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 rounded text-xs transition-colors ${
        active
          ? 'bg-zinc-700 text-zinc-200'
          : 'text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800'
      }`}
    >
      {children}
    </button>
  );
}
