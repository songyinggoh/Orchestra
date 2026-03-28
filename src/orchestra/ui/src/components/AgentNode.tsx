import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

export interface AgentNodeData {
  label: string;
  nodeId: string;
  status?: 'pending' | 'running' | 'completed' | 'error';
  model?: string;
  durationMs?: number;
  costUsd?: number;
  tokens?: number;
}

const statusColors: Record<string, string> = {
  pending: 'border-zinc-600 bg-zinc-800/50',
  running: 'border-amber-500 bg-amber-500/10 shadow-amber-500/20 shadow-lg',
  completed: 'border-emerald-500 bg-emerald-500/10',
  error: 'border-red-500 bg-red-500/10',
};

function AgentNodeInner({ data }: { data: AgentNodeData }) {
  const status = data.status ?? 'pending';
  const color = statusColors[status] ?? statusColors.pending;

  return (
    <div className={`rounded-lg border-2 px-3 py-2 min-w-[180px] ${color} transition-all duration-300`}>
      <Handle type="target" position={Position.Top} className="!bg-zinc-500 !w-2 !h-2" />

      <div className="text-sm font-semibold text-zinc-100 truncate">{data.label}</div>

      {(data.model || data.durationMs != null || data.costUsd != null) && (
        <div className="flex gap-2 mt-1 text-[10px] text-zinc-400 font-mono">
          {data.model && <span>{data.model}</span>}
          {data.durationMs != null && <span>{(data.durationMs / 1000).toFixed(1)}s</span>}
          {data.costUsd != null && <span>${data.costUsd.toFixed(4)}</span>}
        </div>
      )}

      {data.tokens != null && (
        <div className="text-[10px] text-zinc-500 font-mono mt-0.5">
          {data.tokens.toLocaleString()} tok
        </div>
      )}

      {status === 'running' && (
        <div className="mt-1 h-0.5 bg-amber-500/30 rounded overflow-hidden">
          <div className="h-full w-1/3 bg-amber-500 rounded animate-pulse" />
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-zinc-500 !w-2 !h-2" />
    </div>
  );
}

export const AgentNode = memo(AgentNodeInner);
