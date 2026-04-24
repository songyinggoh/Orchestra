import { useState } from 'react';

interface StateViewerProps {
  state: Record<string, unknown>;
}

export function StateViewer({ state }: StateViewerProps) {
  const [collapsed, setCollapsed] = useState(false);
  const keys = Object.keys(state);

  return (
    <div className="border-t border-zinc-800 bg-zinc-900/50">
      <button
        className="flex w-full items-center gap-1 px-3 py-1.5 text-left text-[11px] font-medium text-zinc-400 hover:text-zinc-300"
        onClick={() => setCollapsed(!collapsed)}
      >
        <span style={{ transform: collapsed ? 'rotate(-90deg)' : 'rotate(0)' }}>▾</span>
        State ({keys.length} key{keys.length !== 1 ? 's' : ''})
      </button>
      {!collapsed && (
        <pre className="max-h-48 overflow-auto px-3 pb-2 font-mono text-[11px] text-zinc-400">
          {JSON.stringify(state, null, 2)}
        </pre>
      )}
    </div>
  );
}
