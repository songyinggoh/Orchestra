import { useState } from 'react';
import type { AnyEvent, EventType } from '../types/events';

const typeIcons: Partial<Record<EventType, string>> = {
  'execution.started': '\u25B6',
  'execution.completed': '\u2713',
  'node.started': '\u25CB',
  'node.completed': '\u25CF',
  'llm.called': '\u2726',
  'tool.called': '\u2692',
  'edge.traversed': '\u2192',
  'parallel.started': '\u2942',
  'parallel.completed': '\u2943',
  'error.occurred': '\u2717',
  'state.updated': '\u0394',
  'interrupt.requested': '\u23F8',
  'handoff.initiated': '\u21C4',
  'security.violation': '\u26A0',
};

const typeColors: Partial<Record<EventType, string>> = {
  'execution.started': 'text-blue-400',
  'execution.completed': 'text-emerald-400',
  'node.started': 'text-zinc-400',
  'node.completed': 'text-emerald-400',
  'llm.called': 'text-purple-400',
  'tool.called': 'text-cyan-400',
  'error.occurred': 'text-red-400',
  'parallel.started': 'text-amber-400',
  'parallel.completed': 'text-amber-400',
  'security.violation': 'text-red-500',
};

function formatTime(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString('en-US', { hour12: false, fractionalSecondDigits: 3 });
  } catch {
    return ts;
  }
}

function EventDetail({ event }: { event: AnyEvent }) {
  const details: string[] = [];
  const e = event as unknown as Record<string, unknown>;

  if (e.node_id) details.push(`node: ${e.node_id}`);
  if (e.agent_name) details.push(`agent: ${e.agent_name}`);
  if (e.model) details.push(`model: ${e.model}`);
  if (e.input_tokens) details.push(`in: ${(e.input_tokens as number).toLocaleString()}`);
  if (e.output_tokens) details.push(`out: ${(e.output_tokens as number).toLocaleString()}`);
  if (e.cost_usd) details.push(`$${(e.cost_usd as number).toFixed(4)}`);
  if (e.duration_ms) details.push(`${((e.duration_ms as number) / 1000).toFixed(2)}s`);
  if (e.tool_name) details.push(`tool: ${e.tool_name}`);
  if (e.from_node) details.push(`${e.from_node} \u2192 ${e.to_node}`);
  if (e.error_message) details.push(`${e.error_message}`);
  if (e.workflow_name) details.push(`workflow: ${e.workflow_name}`);

  return (
    <span className="text-zinc-500 text-[10px] font-mono">
      {details.join(' \u00B7 ')}
    </span>
  );
}

interface EventTimelineProps {
  events: AnyEvent[];
}

export function EventTimeline({ events }: EventTimelineProps) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const toggle = (seq: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(seq)) next.delete(seq);
      else next.add(seq);
      return next;
    });
  };

  return (
    <div className="flex flex-col gap-0.5 scroll-thin overflow-y-auto h-full p-2">
      {events.length === 0 && (
        <div className="text-zinc-600 text-sm text-center py-8">Waiting for events...</div>
      )}
      {events.map((event) => {
        const icon = typeIcons[event.event_type] ?? '\u25A0';
        const color = typeColors[event.event_type] ?? 'text-zinc-500';
        const isExpanded = expanded.has(event.sequence);

        return (
          <div
            key={event.sequence}
            className="flex flex-col px-2 py-1 hover:bg-zinc-800/50 rounded cursor-pointer transition-colors"
            onClick={() => toggle(event.sequence)}
          >
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-zinc-600 font-mono w-20 shrink-0">
                {formatTime(event.timestamp)}
              </span>
              <span className={`w-4 text-center ${color}`}>{icon}</span>
              <span className="text-xs text-zinc-300 truncate">{event.event_type}</span>
            </div>
            <div className="ml-[88px] mt-0.5">
              <EventDetail event={event} />
            </div>
            {isExpanded && (
              <pre className="ml-[88px] mt-1 text-[10px] text-zinc-500 bg-zinc-900 rounded p-2 overflow-x-auto max-h-48 font-mono">
                {JSON.stringify(event, null, 2)}
              </pre>
            )}
          </div>
        );
      })}
    </div>
  );
}
