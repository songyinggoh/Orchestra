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
        className="w-full px-3 py-1.5 text-left text-[11px] font-medium text-zinc-400 hover:text-zinc-300 flex items-center gap-1"
        onClick={() => setCollapsed(!collapsed)}
      >
        <span className="transition-transform" style={{ transform: collapsed ? 'rotate(-90deg)' : 'rotate(0)' }}>
          {'\u25BE'}
        </span>
        State ({keys.length} key{keys.length !== 1 ? 's' : ''})
      </button>
      {!collapsed && (
        <pre className="px-3 pb-2 text-[11px] font-mono text-zinc-400 overflow-auto max-h-48 scroll-thin">
          {JSON.stringify(state, null, 2)}
        </pre>
      )}
    </div>
  );
}
