import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

function TerminalNodeInner({ data }: { data: { label: string; nodeId: string } }) {
  const isStart = data.nodeId === '__start__';

  return (
    <div className="rounded-full border border-zinc-600 bg-zinc-800 px-4 py-1.5 text-xs text-zinc-300 font-medium">
      {!isStart && <Handle type="target" position={Position.Top} className="!bg-zinc-500 !w-2 !h-2" />}
      {data.label}
      {isStart && <Handle type="source" position={Position.Bottom} className="!bg-zinc-500 !w-2 !h-2" />}
    </div>
  );
}

export const TerminalNode = memo(TerminalNodeInner);
