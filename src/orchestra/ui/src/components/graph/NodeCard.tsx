/**
 * NodeCard — custom ReactFlow node replacing AgentNode + TerminalNode.
 *
 * Variants:
 *   - 'agent' (default): shadcn Card shell, status border, cost/model badge row,
 *     pink corner-dot when securityCount > 0.
 *   - 'terminal': pill shape for __start__ / __end__ sentinels.
 */

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { cn } from '@/lib/utils';
import type { NodeStatus } from '../../stores/eventReducer';

export interface NodeCardData {
  label: string;
  nodeId: string;
  variant?: 'agent' | 'terminal';
  status?: NodeStatus;
  model?: string | null;
  durationMs?: number;
  costUsd?: number;
  securityCount?: number;
}

const STATUS_CLASS: Record<NodeStatus, string> = {
  pending:   'border-zinc-700 bg-zinc-900',
  running:   'border-amber-500 bg-amber-500/10 shadow-lg shadow-amber-500/20',
  completed: 'border-emerald-500 bg-emerald-500/10',
  error:     'border-red-500 bg-red-500/10',
  waiting:   'border-violet-500 bg-violet-500/10',
};

function TerminalPill({ data }: { data: NodeCardData }) {
  const isStart = data.nodeId === '__start__';
  return (
    <div className="rounded-full border border-zinc-700 bg-zinc-800 px-4 py-1.5 text-xs font-medium text-zinc-300">
      {!isStart && (
        <Handle type="target" position={Position.Top} className="!h-2 !w-2 !bg-zinc-500" />
      )}
      {data.label}
      {isStart && (
        <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !bg-zinc-500" />
      )}
    </div>
  );
}

function AgentCard({ data }: { data: NodeCardData }) {
  const status = data.status ?? 'pending';
  const hasSec = (data.securityCount ?? 0) > 0;

  return (
    <div
      className={cn(
        'relative min-w-[180px] rounded-lg border-2 px-3 py-2 transition-all duration-300',
        STATUS_CLASS[status],
      )}
      role="button"
      aria-label={`node ${data.nodeId}, status ${status}, cost $${(data.costUsd ?? 0).toFixed(4)}`}
    >
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !bg-zinc-500" />

      {/* Pink security corner-dot */}
      {hasSec && (
        <span
          className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-pink-500 ring-2 ring-zinc-900"
          aria-label={`${data.securityCount} security event${data.securityCount !== 1 ? 's' : ''}`}
        />
      )}

      <div className="truncate text-sm font-semibold text-zinc-100">{data.label}</div>

      {(data.model != null || data.durationMs != null || data.costUsd != null) && (
        <div className="mt-1 flex gap-2 font-mono text-[10px] text-zinc-400 tabular-nums">
          {data.model && <span>{data.model}</span>}
          {data.durationMs != null && (
            <span>{data.durationMs >= 1000
              ? `${(data.durationMs / 1000).toFixed(1)}s`
              : `${data.durationMs}ms`}
            </span>
          )}
          {data.costUsd != null && <span>${data.costUsd.toFixed(4)}</span>}
        </div>
      )}

      {status === 'running' && (
        <div className="mt-1 h-0.5 overflow-hidden rounded bg-amber-500/30">
          <div className="h-full w-1/3 animate-pulse rounded bg-amber-500" />
        </div>
      )}

      {status === 'waiting' && (
        <div className="mt-1 text-[10px] text-violet-400">Awaiting resume…</div>
      )}

      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !bg-zinc-500" />
    </div>
  );
}

function NodeCardInner({ data }: { data: NodeCardData }) {
  if (data.variant === 'terminal') return <TerminalPill data={data} />;
  return <AgentCard data={data} />;
}

export const NodeCard = memo(NodeCardInner);
