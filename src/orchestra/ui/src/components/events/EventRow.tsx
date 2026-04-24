/**
 * Single 32px-tall row in the event timeline.
 * Security rows get a pink tint + left border + SecurityChip.
 * Non-security rows on a node that had a prior security event get a pink dot.
 */

import { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { cn } from '@/lib/utils';
import { EventIcon } from './EventIcon';
import { EventDetail } from './EventDetail';
import { SecurityChip } from '../security/SecurityChip';
import type { AnyEvent } from '../../types/events';

const SECURITY_TYPES = new Set<AnyEvent['event_type']>([
  'security.violation',
  'security.restricted_mode_entered',
  'input.rejected',
  'output.rejected',
]);

function isSecurity(event: AnyEvent): boolean {
  return SECURITY_TYPES.has(event.event_type);
}

function getNodeId(event: AnyEvent): string | null {
  if ('node_id' in event && typeof event.node_id === 'string') return event.node_id;
  return null;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  const ms = String(d.getMilliseconds()).padStart(3, '0');
  return `${hh}:${mm}:${ss}.${ms}`;
}

interface EventRowProps {
  event: AnyEvent;
  /** nodeIds that have had at least one security event (from useRunStore) */
  securityNodeIds: Set<string>;
  onClick?: () => void;
  isHighlighted?: boolean;
}

export function EventRow({ event, securityNodeIds, onClick, isHighlighted }: EventRowProps) {
  const [open, setOpen] = useState(false);
  const sec = isSecurity(event);
  const nodeId = getNodeId(event);
  const hasPriorSec = !sec && nodeId != null && securityNodeIds.has(nodeId);

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <div
          role="listitem"
          className={cn(
            'group flex min-h-8 cursor-pointer items-start gap-2 px-3 py-1 text-xs transition-colors hover:bg-zinc-800/60',
            sec && 'border-l-2 border-pink-500 bg-pink-500/5',
            isHighlighted && 'ring-1 ring-inset ring-violet-500/50',
          )}
          onClick={onClick}
        >
          {/* Icon slot — pink dot overlay for prior-security nodes */}
          <div className="relative mt-0.5 flex-shrink-0">
            <EventIcon eventType={event.event_type} size={14} />
            {hasPriorSec && (
              <span className="absolute -right-1 -top-1 h-2 w-2 rounded-full bg-pink-500 ring-1 ring-zinc-900" />
            )}
          </div>

          {/* Timestamp */}
          <span className="w-28 flex-shrink-0 font-mono text-zinc-500 tabular-nums">
            {formatTime(event.timestamp)}
          </span>

          {/* Event type label */}
          <span className="w-48 flex-shrink-0 truncate font-medium text-zinc-300">
            {event.event_type}
          </span>

          {/* Detail */}
          <span className="min-w-0 flex-1 truncate text-zinc-500">
            <EventDetail event={event} />
          </span>

          {/* Chips */}
          <div className="flex flex-shrink-0 items-center gap-1">
            {sec && <SecurityChip event={event} />}
            <span className="text-zinc-700 opacity-0 transition-opacity group-hover:opacity-100">
              {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </span>
          </div>
        </div>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <pre className="overflow-x-auto whitespace-pre-wrap break-all border-l-2 border-zinc-800 bg-zinc-900/60 px-4 py-2 font-mono text-xs text-zinc-400">
          {JSON.stringify(event, null, 2)}
        </pre>
      </CollapsibleContent>
    </Collapsible>
  );
}
